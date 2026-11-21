"""
Kawad Swad ERP — Signed Apps Script Single-Write-Owner Bridge.

Architectural rules enforced here:
1. Apps Script is the single governed write/posting owner when SALES_APPS_SCRIPT_ENABLED=true
   and SALES_APPS_SCRIPT_WEBAPP_URL + SALES_APPS_SCRIPT_SHARED_SECRET are configured.
2. Strict 1:1 centralized action-to-table allowlist (`GOVERNED_ACTION_REGISTRY`):
   unregistered actions, mismatched target tabs, mismatched ID fields, and unauthorized
   cache-invalidation tabs are rejected fail-closed.
3. Deterministic retry identity: client/domain `nonce` is preserved unchanged; deterministic
   `payload_hash` (excluding volatile `timestamp`/`correlation_id`) is included in the signed
   envelope and HTTP headers. Silent random UUID nonce generation is disabled by default.
4. Strict response parsing & correlation validation: non-dict JSON, unexpected status, or
   mismatched echoed `correlation_id`/`nonce`/`action`/`target_tab` fail closed cleanly.
5. Explicit transaction-specific read-back verification (`_verify_readback`) across primary row,
   expected state transitions, child/ledger rows, and double-entry balance before returning
   `CONFIRMED`. Unconfirmed outcomes return `PENDING_UNKNOWN` (HTTP 504, retryable with SAME nonce).
6. Never log raw secrets, bank details, or personal identity numbers.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request

from app.action_registry import (
    GovernedActionSpec,
    get_governed_action_spec,
)
from app.config import (
    SALES_APPS_SCRIPT_ENABLED,
    SALES_APPS_SCRIPT_SHARED_SECRET,
    SALES_APPS_SCRIPT_TIMEOUT_SECONDS,
    SALES_APPS_SCRIPT_WEBAPP_URL,
    SALES_ENV,
)
from app.schema_registry import (
    COLLIDING_LEGACY_PREFIX_TABS,
    CONFIDENTIAL_TABS_NO_CACHE,
    SECURITY_NO_CACHE_TABS,
    get_allowed_id_prefixes_for_tab,
    get_locked_prefix_for_tab,
    get_schema_write_block_reason,
    is_forbidden_scratch_tab,
    validate_table_id_prefix,
)
from app.sheets import db
from app.timeutil import now_iso

logger = logging.getLogger("kawad_swad.apps_script_bridge")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail-closed redirect blocker so signed HMAC envelopes are never forwarded across HTTP redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            newurl,
            code,
            f"HTTP {code} redirect blocked on signed Apps Script bridge request.",
            headers,
            fp,
        )


@dataclass
class BridgeResult:
    status: str  # CONFIRMED | REJECTED | PENDING_UNKNOWN | BLOCKED_PENDING_OWNER_SETUP
    correlation_id: str
    nonce: str
    allocated_id: Optional[str] = None
    record: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    message: str = ""
    retryable: bool = False
    http_status: int = 200
    dependency: Optional[str] = None
    payload_hash: Optional[str] = None


# Strict plain decimal syntax for string-serialized Google Sheets numbers:
# accepts optional sign, non-zero-padded integer or single "0", optional fractional part,
# or leading decimal point (e.g. ".50"). Deliberately rejects zero-padded codes ("0010"),
# scientific-notation lookalikes ("1E2"), and underscore separators ("1_000") so IDs/SKUs
# are never coerced into numbers.
_PLAIN_DECIMAL_RE = re.compile(r"^[+-]?(?:(?:0|[1-9]\d*)(?:\.\d+)?|\.\d+)$")


def _format_decimal_canonical(dec: Decimal) -> str:
    """
    Format a finite Decimal canonically without precision loss or integer-digit truncation.

    Uses fixed-point formatting directly on `dec` (avoiding `dec.normalize()`, which rounds
    to decimal context precision on values exceeding 28 digits and can emit exponents), and
    strips trailing fractional zeroes ONLY when a decimal point '.' is present so meaningful
    trailing zeroes on integers (e.g. 10, 100, 1000, 120) are never removed.
    """
    if dec == 0:
        return "0"
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _normalize_scalar(value: Any) -> str:
    """
    Normalize a scalar value for Google Sheets read-back comparison.

    Explicit comparison contract:
    - Booleans (`bool` and case-insensitive `"true"` / `"false"`): normalized to `"true"` or
      `"false"`. Checked BEFORE numeric types because `bool` subclasses `int` in Python, so
      `True` NEVER collides with `1` and `False` NEVER collides with `0`.
    - Null / Empty (`None`, `""`, whitespace-only strings): normalized to `""`, matching
      Google Sheets' existing empty-cell representation where blank cells read back as `""`.
      Does NOT collide with numeric `0` (`"0"`) or boolean `False` (`"false"`).
    - Numeric values (`int`, `float`, `Decimal`) and strict plain-decimal strings (matching
      `_PLAIN_DECIMAL_RE`, which Google Sheets returns via text formatting or `get_all_values()`
      fallback): converted via `Decimal` (no float conversion on `Decimal` or numeric strings)
      and formatted canonically so `1.2` == `1.20`, `0.5` == `0.50`, `100` == `"100"` == `100.0`,
      while preserving all integer digits (`10` != `100` != `1000`, `120` != `12`, `0` != `10`).
    - All other strings (IDs, SKUs, dates, statuses, zero-padded codes like `"0010"`,
      alphanumeric codes like `"1E2"`, non-finite floats/Decimals): preserved as trimmed strings.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if value.is_finite():
            return _format_decimal_canonical(value)
        return str(value).strip()
    if isinstance(value, float):
        try:
            dec = Decimal(str(value))
            if dec.is_finite():
                return _format_decimal_canonical(dec)
        except (InvalidOperation, ValueError):
            pass
        return str(value).strip()

    s = str(value).strip()
    if not s:
        return ""
    lower = s.lower()
    if lower in {"true", "false"}:
        return lower
    if _PLAIN_DECIMAL_RE.match(s):
        try:
            dec = Decimal(s)
            if dec.is_finite():
                return _format_decimal_canonical(dec)
        except (InvalidOperation, ValueError):
            pass
    return s


_PRIMARY_RECORD_NESTED_KEYS: Tuple[str, ...] = (
    "record",
    "updates",
    "packaging_updates",
    "sale",
    "order",
    "po",
    "grn",
    "supplier_return",
    "payment",
    "payment_update",
    "salary_structure",
    "payroll_run",
    "user_updates",
    "auth_updates",
    "item_update",
    "milling_batch",
    "leg2_row",
)


def _lookup_expected_value(payload: Dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload.get(key)
    for nested_key in _PRIMARY_RECORD_NESTED_KEYS:
        sub = payload.get(nested_key)
        if isinstance(sub, dict) and key in sub:
            return sub.get(key)
    return None


class AppsScriptBridge:
    """Signed HTTPS bridge delegating ALL governed ERP writes to Apps Script (Single Write Owner)."""

    @staticmethod
    def compute_payload_hash(
        *,
        action: str,
        target_tab: str,
        nonce: str,
        actor_user_id: str,
        actor_role: str,
        payload: Dict[str, Any],
    ) -> str:
        """
        Compute a deterministic SHA-256 digest over the business request envelope
        excluding volatile per-attempt metadata (`timestamp`, `correlation_id`).
        """
        canonical = json.dumps(
            {
                "action": str(action or "").strip().upper(),
                "target_tab": str(target_tab or "").strip(),
                "nonce": str(nonce or "").strip(),
                "actor_user_id": str(actor_user_id or "").strip(),
                "actor_role": str(actor_role or "").strip().upper(),
                "payload": payload,
            },
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def extract_request_nonce(
        request: Optional[Request] = None,
        explicit_nonce: Optional[str] = None,
        *,
        fail_on_conflict: bool = True,
    ) -> str:
        """
        Extract client-supplied nonce or X-KS-Idempotency-Key / X-Idempotency-Key unchanged.
        Fails closed with HTTP 409 if both explicit nonce and header are supplied and disagree.
        """
        explicit = str(explicit_nonce or "").strip()
        hdr_nonce = ""
        if request is not None:
            headers = getattr(request, "headers", None) or {}
            hdr_nonce = str(
                headers.get("X-KS-Idempotency-Key")
                or headers.get("X-Idempotency-Key")
                or headers.get("x-ks-idempotency-key")
                or headers.get("x-idempotency-key")
                or ""
            ).strip()
        if fail_on_conflict and explicit and hdr_nonce and explicit != hdr_nonce:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "REJECTED",
                    "error_code": "IDEMPOTENCY_NONCE_MISMATCH",
                    "message": "Body nonce and X-KS-Idempotency-Key header do not match.",
                    "retryable": False,
                },
            )
        return explicit or hdr_nonce

    @staticmethod
    def is_valid_webapp_url(url: str) -> bool:
        clean = str(url or "").strip()
        if not clean:
            return False
        try:
            parsed = urllib.parse.urlparse(clean)
        except Exception:
            return False
        if not parsed.netloc:
            return False
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        if scheme == "https":
            return True
        if scheme == "http" and SALES_ENV != "production" and hostname in {"localhost", "127.0.0.1", "::1"}:
            return True
        return False

    @classmethod
    def is_configured(cls) -> bool:
        return bool(
            SALES_APPS_SCRIPT_ENABLED
            and cls.is_valid_webapp_url(SALES_APPS_SCRIPT_WEBAPP_URL)
            and len(SALES_APPS_SCRIPT_SHARED_SECRET) >= 32
        )

    @staticmethod
    def sign_envelope(canonical_body: str, secret: str) -> str:
        return hmac.new(
            secret.encode("utf-8"),
            canonical_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _effective_locked_prefix(spec: GovernedActionSpec) -> Optional[str]:
        if spec.locked_prefix:
            return spec.locked_prefix
        if spec.requires_allocated_id:
            return get_locked_prefix_for_tab(spec.target_tab)
        return None

    @classmethod
    def _validate_id_format(
        cls,
        spec: GovernedActionSpec,
        allocated_id: str,
        *,
        for_new_allocation: bool = True,
    ) -> bool:
        clean = str(allocated_id or "").strip().upper()
        if not clean:
            return False
        effective_prefix = cls._effective_locked_prefix(spec)
        # Always delegate to centralized validate_table_id_prefix(), even when
        # effective_prefix is None, so COLLIDING_LEGACY_PREFIX_TABS (SalaryIncentives,
        # SalaryReceipts) and cross-table LOCKED_32_ID_PREFIXES collisions are always enforced.
        return validate_table_id_prefix(
            spec.target_tab,
            clean,
            for_new_allocation=for_new_allocation,
            explicit_locked_prefix=effective_prefix,
        )

    @staticmethod
    def _extract_payload_field(payload: Dict[str, Any], field_name: str) -> Tuple[bool, str]:
        """Search top-level payload and known nested entity containers for an identifier field."""
        if not field_name or not isinstance(payload, dict):
            return False, ""
        if field_name in payload:
            raw = payload.get(field_name)
            return True, str(raw).strip() if raw is not None else ""
        for container_key in ("record", "payment", "grn", "order", "invoice", "receipt", "batch"):
            sub = payload.get(container_key)
            if isinstance(sub, dict) and field_name in sub:
                raw = sub.get(field_name)
                return True, str(raw).strip() if raw is not None else ""
        return False, ""

    # In-process concurrency guard: prevents two threads in the same backend worker from
    # passing pre-write duplicate-ID validation concurrently for the exact same (tab, ID).
    # NOTE: Cross-worker / distributed atomic uniqueness still requires LockService inside
    # the external Apps Script writer (tracked under DB-008).
    _INFLIGHT_ID_LOCK = threading.Lock()
    _INFLIGHT_IDS: Dict[Tuple[str, str], str] = {}

    @classmethod
    def _check_id_exists_authoritative(
        cls,
        tab_name: str,
        id_fields: Tuple[str, ...],
        candidate_id: str,
    ) -> Tuple[bool, Optional[Tuple[str, int, str]]]:
        """
        Authoritative, fail-closed duplicate-ID lookup against fresh Google Sheets data.

        Returns `(exists, error_info)` where `error_info` is `None` ONLY when:
        1. `db.get_records(tab_name, fresh=True)` succeeded without exception.
        2. Returned payload is a list of dict rows (never None / malformed / non-dict).
        3. Row-1 header evidence (`db.get_verified_tab_headers(tab_name, fresh=True)`)
           confirms the table schema includes at least one expected identifier column
           (preventing missing/wrong-header reads from masquerading as an empty table).
        4. For non-empty tables, every row contains at least one expected identifier column.

        On ANY read outage, timeout, 429/500/503, auth failure, malformed response, or
        unverified schema header, returns `(False, (error_code, 503, message))` so callers
        FAIL CLOSED and perform zero remote writes.
        """
        target_upper = str(candidate_id or "").strip().upper()
        if not target_upper:
            return False, None

        expected_fields = {str(f or "").strip() for f in id_fields if str(f or "").strip()}
        if not expected_fields:
            return False, (
                "DUPLICATE_CHECK_SCHEMA_UNVERIFIED",
                503,
                f"Pre-write duplicate-ID check failed: no identifier columns specified for '{tab_name}'. Data was NOT SAVED.",
            )

        try:
            rows = db.get_records(tab_name, fresh=True)
        except Exception as exc:
            logger.error("Authoritative duplicate-ID read failed for '%s': %s", tab_name, exc)
            return False, (
                "DUPLICATE_CHECK_STORE_UNAVAILABLE",
                503,
                f"Pre-write duplicate-ID check failed: authoritative fresh read of '{tab_name}' is unavailable ({exc}). Data was NOT SAVED.",
            )

        if not isinstance(rows, list):
            logger.error(
                "Authoritative duplicate-ID read for '%s' returned malformed non-list type %s",
                tab_name,
                type(rows).__name__,
            )
            return False, (
                "DUPLICATE_CHECK_DATA_MALFORMED",
                503,
                f"Pre-write duplicate-ID check failed: '{tab_name}' returned malformed non-list data ({type(rows).__name__}). Data was NOT SAVED.",
            )

        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                logger.error(
                    "Authoritative duplicate-ID read for '%s' contains malformed non-dict row at index %d (%s)",
                    tab_name,
                    idx,
                    type(row).__name__,
                )
                return False, (
                    "DUPLICATE_CHECK_DATA_MALFORMED",
                    503,
                    f"Pre-write duplicate-ID check failed: '{tab_name}' contains malformed row data at index {idx}. Data was NOT SAVED.",
                )

        # Require trustworthy Row-1 header evidence for BOTH empty and non-empty tables
        try:
            verified_headers = db.get_verified_tab_headers(tab_name, fresh=True)
        except Exception as exc:
            logger.error("Authoritative header verification failed for '%s': %s", tab_name, exc)
            return False, (
                "DUPLICATE_CHECK_SCHEMA_UNVERIFIED",
                503,
                f"Pre-write duplicate-ID check failed: unable to verify Row-1 schema headers for '{tab_name}' ({exc}). Data was NOT SAVED.",
            )

        if not isinstance(verified_headers, list) or not verified_headers:
            return False, (
                "DUPLICATE_CHECK_SCHEMA_UNVERIFIED",
                503,
                f"Pre-write duplicate-ID check failed: Row-1 schema headers for '{tab_name}' are missing or empty. Data was NOT SAVED.",
            )

        header_set = {str(h).strip() for h in verified_headers if isinstance(h, str) and str(h).strip()}
        if not (expected_fields & header_set):
            return False, (
                "DUPLICATE_CHECK_SCHEMA_UNVERIFIED",
                503,
                (
                    f"Pre-write duplicate-ID check failed: '{tab_name}' headers do not include expected "
                    f"identifier column(s) {sorted(expected_fields)}. Data was NOT SAVED."
                ),
            )

        # For non-empty tables, ensure returned rows actually carry at least one expected ID column
        for idx, row in enumerate(rows):
            row_keys = {str(k).strip() for k in row.keys()}
            if not (expected_fields & row_keys):
                return False, (
                    "DUPLICATE_CHECK_SCHEMA_UNVERIFIED",
                    503,
                    (
                        f"Pre-write duplicate-ID check failed: row {idx} in '{tab_name}' is missing expected "
                        f"identifier column(s) {sorted(expected_fields)}. Data was NOT SAVED."
                    ),
                )

        for row in rows:
            for field in id_fields:
                existing_val = str(row.get(field) or "").strip().upper()
                if existing_val and existing_val == target_upper:
                    return True, None

        with cls._INFLIGHT_ID_LOCK:
            if (tab_name, target_upper) in cls._INFLIGHT_IDS:
                return True, None

        return False, None

    @classmethod
    def _id_exists_in_tab(cls, tab_name: str, id_fields: Tuple[str, ...], candidate_id: str) -> bool:
        """Fail-closed wrapper around `_check_id_exists_authoritative` (never fails open to False)."""
        exists, err_info = cls._check_id_exists_authoritative(tab_name, id_fields, candidate_id)
        if err_info is not None:
            raise RuntimeError(f"{err_info[0]}: {err_info[2]}")
        return exists

    @classmethod
    def _reserve_inflight_ids(
        cls,
        keys: List[Tuple[str, str]],
        corr_id: str,
    ) -> Tuple[Optional[Tuple[str, str]], List[Tuple[str, str]]]:
        """Atomically reserve validated (tab_name, upper_id) keys for the duration of this write."""
        unique_keys: List[Tuple[str, str]] = []
        for k in keys:
            if k not in unique_keys:
                unique_keys.append(k)
        if not unique_keys:
            return None, []
        with cls._INFLIGHT_ID_LOCK:
            for key in unique_keys:
                if key in cls._INFLIGHT_IDS:
                    return key, []
            for key in unique_keys:
                cls._INFLIGHT_IDS[key] = corr_id
            return None, unique_keys

    @classmethod
    def _release_inflight_ids(cls, keys: List[Tuple[str, str]], corr_id: str) -> None:
        if not keys:
            return
        with cls._INFLIGHT_ID_LOCK:
            for key in keys:
                if cls._INFLIGHT_IDS.get(key) == corr_id:
                    cls._INFLIGHT_IDS.pop(key, None)

    @staticmethod
    def _duplicate_check_error_result(
        *,
        err_info: Tuple[str, int, str],
        corr_id: str,
        clean_nonce: str,
        payload_hash: str,
        allocated_id: Optional[str] = None,
    ) -> BridgeResult:
        err_code, http_status, message = err_info
        return BridgeResult(
            status="REJECTED",
            correlation_id=corr_id,
            nonce=clean_nonce,
            allocated_id=allocated_id,
            error_code=err_code,
            message=message,
            retryable=True,
            http_status=http_status,
            payload_hash=payload_hash,
        )

    def _preflight_validate_payload_ids(
        self,
        *,
        spec: GovernedActionSpec,
        payload: Dict[str, Any],
        corr_id: str,
        clean_nonce: str,
        payload_hash: str,
    ) -> Tuple[Optional[BridgeResult], List[Tuple[str, str]]]:
        """
        Pre-write identifier, prefix, parent-reference, child-row, and cross-table
        collision validation. Runs BEFORE any bridge HTTP POST or mutation so invalid,
        colliding, or unverifiable IDs never create partial records.

        Returns `(error_result, reserved_inflight_keys)`. Caller MUST release
        `reserved_inflight_keys` in a `finally:` block whenever `error_result is None`.
        """
        effective_prefix = self._effective_locked_prefix(spec)
        primary_fields = spec.readback.primary_match_fields or ()
        keys_to_reserve: List[Tuple[str, str]] = []

        # 1. Primary target identifier validation (if supplied in payload or explicitly blank on update/delete)
        if spec.id_field:
            present, supplied_id = self._extract_payload_field(payload, spec.id_field)
            if not spec.requires_allocated_id and len(primary_fields) == 1 and primary_fields[0] == spec.id_field:
                if present and not supplied_id:
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        error_code="MISSING_TARGET_IDENTIFIER",
                        message=f"Action '{spec.action}' requires a non-empty '{spec.id_field}' before mutation.",
                        retryable=False,
                        http_status=422,
                        payload_hash=payload_hash,
                    ), []
            if supplied_id:
                enforces_prefix = bool(
                    effective_prefix
                    or get_locked_prefix_for_tab(spec.target_tab)
                    or spec.target_tab in COLLIDING_LEGACY_PREFIX_TABS
                    or spec.requires_allocated_id
                )
                if enforces_prefix and not validate_table_id_prefix(
                    spec.target_tab,
                    supplied_id,
                    for_new_allocation=spec.requires_allocated_id,
                    explicit_locked_prefix=effective_prefix,
                ):
                    allowed_prefixes = get_allowed_id_prefixes_for_tab(
                        spec.target_tab,
                        for_new_allocation=spec.requires_allocated_id,
                        explicit_locked_prefix=effective_prefix,
                    )
                    allowed_desc = ", ".join(allowed_prefixes) if allowed_prefixes else "non-colliding canonical format"
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        allocated_id=supplied_id,
                        error_code="INVALID_PAYLOAD_ID_FORMAT",
                        message=(
                            f"Pre-write validation failed: '{spec.id_field}'='{supplied_id}' is invalid for "
                            f"'{spec.target_tab}' (allowed: {allowed_desc}). Data was NOT SAVED."
                        ),
                        retryable=False,
                        http_status=422,
                        payload_hash=payload_hash,
                    ), []
                if spec.requires_allocated_id:
                    check_fields = (spec.id_field,)
                    if spec.target_tab == "SalaryIncentives":
                        check_fields = ("record_id", "incentive_id")
                    exists, err_info = self._check_id_exists_authoritative(spec.target_tab, check_fields, supplied_id)
                    if err_info is not None:
                        return self._duplicate_check_error_result(
                            err_info=err_info,
                            corr_id=corr_id,
                            clean_nonce=clean_nonce,
                            payload_hash=payload_hash,
                            allocated_id=supplied_id,
                        ), []
                    if exists:
                        return BridgeResult(
                            status="REJECTED",
                            correlation_id=corr_id,
                            nonce=clean_nonce,
                            allocated_id=supplied_id,
                            error_code="DUPLICATE_RECORD_ID",
                            message=(
                                f"Pre-write validation failed: '{supplied_id}' already exists in "
                                f"'{spec.target_tab}'. Data was NOT SAVED."
                            ),
                            retryable=False,
                            http_status=409,
                            payload_hash=payload_hash,
                        ), []
                    keys_to_reserve.append((spec.target_tab, supplied_id.strip().upper()))

                    # Cross-table uniqueness for RCPT (Payments <-> SalaryReceipts) and SAL (SalaryPayments <-> SalaryIncentives)
                    if spec.target_tab == "Payments":
                        exists_x, err_x = self._check_id_exists_authoritative(
                            "SalaryReceipts", ("receipt_id", "receipt_number"), supplied_id
                        )
                        if err_x is not None:
                            return self._duplicate_check_error_result(
                                err_info=err_x,
                                corr_id=corr_id,
                                clean_nonce=clean_nonce,
                                payload_hash=payload_hash,
                                allocated_id=supplied_id,
                            ), []
                        if exists_x:
                            return BridgeResult(
                                status="REJECTED",
                                correlation_id=corr_id,
                                nonce=clean_nonce,
                                allocated_id=supplied_id,
                                error_code="CROSS_TABLE_ID_COLLISION",
                                message=(
                                    f"Pre-write validation failed: '{supplied_id}' collides with an existing "
                                    "SalaryReceipts identifier. Data was NOT SAVED."
                                ),
                                retryable=False,
                                http_status=409,
                                payload_hash=payload_hash,
                            ), []
                        keys_to_reserve.append(("SalaryReceipts", supplied_id.strip().upper()))
                    elif spec.target_tab == "SalaryIncentives":
                        exists_x, err_x = self._check_id_exists_authoritative(
                            "SalaryPayments", ("salary_payment_id", "payment_id", "record_id"), supplied_id
                        )
                        if err_x is not None:
                            return self._duplicate_check_error_result(
                                err_info=err_x,
                                corr_id=corr_id,
                                clean_nonce=clean_nonce,
                                payload_hash=payload_hash,
                                allocated_id=supplied_id,
                            ), []
                        if exists_x:
                            return BridgeResult(
                                status="REJECTED",
                                correlation_id=corr_id,
                                nonce=clean_nonce,
                                allocated_id=supplied_id,
                                error_code="CROSS_TABLE_ID_COLLISION",
                                message=(
                                    f"Pre-write validation failed: '{supplied_id}' collides with an existing "
                                    "SalaryPayments identifier. Data was NOT SAVED."
                                ),
                                retryable=False,
                                http_status=409,
                                payload_hash=payload_hash,
                            ), []
                        keys_to_reserve.append(("SalaryPayments", supplied_id.strip().upper()))

        # 2. Child-row ID & RCPT cross-table collision validation (e.g. RECORD_WORKFORCE_PAYMENT -> SalaryReceipts)
        touches_salary_receipts = (
            spec.target_tab == "SalaryReceipts"
            or "SalaryReceipts" in spec.allowed_invalidate_tabs
            or any(c.tab == "SalaryReceipts" for c in spec.readback.child_checks)
        )
        if touches_salary_receipts:
            receipt_obj = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
            child_receipt_candidates = [
                str(payload.get("receipt_id") or "").strip(),
                str(receipt_obj.get("receipt_id") or "").strip(),
                str(receipt_obj.get("receipt_number") or "").strip(),
            ]
            for child_rid in [c for c in child_receipt_candidates if c]:
                if not validate_table_id_prefix("SalaryReceipts", child_rid, for_new_allocation=True):
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        error_code="INVALID_CHILD_ID_FORMAT",
                        message=(
                            f"Pre-write validation failed: SalaryReceipts child identifier '{child_rid}' "
                            "violates table prefix/collision rules (RCPT is locked to Payments). Data was NOT SAVED."
                        ),
                        retryable=False,
                        http_status=422,
                        payload_hash=payload_hash,
                    ), []
                exists_sr, err_sr = self._check_id_exists_authoritative(
                    "SalaryReceipts", ("receipt_id", "receipt_number"), child_rid
                )
                if err_sr is not None:
                    return self._duplicate_check_error_result(
                        err_info=err_sr,
                        corr_id=corr_id,
                        clean_nonce=clean_nonce,
                        payload_hash=payload_hash,
                        allocated_id=child_rid,
                    ), []
                if exists_sr:
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        error_code="DUPLICATE_CHILD_RECORD_ID",
                        message=(
                            f"Pre-write validation failed: SalaryReceipts identifier '{child_rid}' "
                            "already exists. Data was NOT SAVED."
                        ),
                        retryable=False,
                        http_status=409,
                        payload_hash=payload_hash,
                    ), []
                exists_pay, err_pay = self._check_id_exists_authoritative(
                    "Payments", ("payment_id", "receipt_id", "receipt_number"), child_rid
                )
                if err_pay is not None:
                    return self._duplicate_check_error_result(
                        err_info=err_pay,
                        corr_id=corr_id,
                        clean_nonce=clean_nonce,
                        payload_hash=payload_hash,
                        allocated_id=child_rid,
                    ), []
                if exists_pay:
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        error_code="CROSS_TABLE_ID_COLLISION",
                        message=(
                            f"Pre-write validation failed: SalaryReceipts identifier '{child_rid}' "
                            "collides with an existing Payments identifier. Data was NOT SAVED."
                        ),
                        retryable=False,
                        http_status=409,
                        payload_hash=payload_hash,
                    ), []
                keys_to_reserve.append(("SalaryReceipts", child_rid.strip().upper()))
                keys_to_reserve.append(("Payments", child_rid.strip().upper()))

        # 3. Validate any explicit child-item IDs supplied inside nested child row arrays
        child_array_contracts = (
            ("items", "SaleItems", "sale_item_id"),
            ("lines", "JournalLines", "line_id"),
            ("order_items", "SalesOrderItems", "order_item_id"),
        )
        for arr_key, child_tab, child_id_field in child_array_contracts:
            if child_tab not in spec.allowed_invalidate_tabs and not any(c.tab == child_tab for c in spec.readback.child_checks):
                continue
            rows_list = payload.get(arr_key)
            if not isinstance(rows_list, list):
                continue
            seen_child_ids: set = set()
            for item in rows_list:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get(child_id_field) or "").strip()
                if not cid:
                    continue
                if not validate_table_id_prefix(child_tab, cid, for_new_allocation=True):
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        error_code="INVALID_CHILD_ID_FORMAT",
                        message=(
                            f"Pre-write validation failed: child '{child_id_field}'='{cid}' is invalid "
                            f"for '{child_tab}'. Data was NOT SAVED."
                        ),
                        retryable=False,
                        http_status=422,
                        payload_hash=payload_hash,
                    ), []
                cid_upper = cid.upper()
                if cid_upper in seen_child_ids:
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        error_code="DUPLICATE_CHILD_RECORD_ID",
                        message=(
                            f"Pre-write validation failed: duplicate child '{child_id_field}'='{cid}' "
                            f"for '{child_tab}'. Data was NOT SAVED."
                        ),
                        retryable=False,
                        http_status=409,
                        payload_hash=payload_hash,
                    ), []
                exists_child, err_child = self._check_id_exists_authoritative(child_tab, (child_id_field,), cid)
                if err_child is not None:
                    return self._duplicate_check_error_result(
                        err_info=err_child,
                        corr_id=corr_id,
                        clean_nonce=clean_nonce,
                        payload_hash=payload_hash,
                        allocated_id=cid,
                    ), []
                if exists_child:
                    return BridgeResult(
                        status="REJECTED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        error_code="DUPLICATE_CHILD_RECORD_ID",
                        message=(
                            f"Pre-write validation failed: duplicate child '{child_id_field}'='{cid}' "
                            f"for '{child_tab}'. Data was NOT SAVED."
                        ),
                        retryable=False,
                        http_status=409,
                        payload_hash=payload_hash,
                    ), []
                seen_child_ids.add(cid_upper)
                keys_to_reserve.append((child_tab, cid_upper))

        # 4. Atomically reserve validated IDs in-process to prevent concurrent duplicate writes
        colliding_key, reserved_keys = self._reserve_inflight_ids(keys_to_reserve, corr_id)
        if colliding_key is not None:
            col_tab, col_id = colliding_key
            is_cross_tab = col_tab != spec.target_tab
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=col_id,
                error_code="CROSS_TABLE_ID_COLLISION" if is_cross_tab else "DUPLICATE_RECORD_ID",
                message=(
                    f"Pre-write concurrency guard rejected concurrent duplicate identifier '{col_id}' "
                    f"for '{col_tab}'. Data was NOT SAVED."
                ),
                retryable=False,
                http_status=409,
                payload_hash=payload_hash,
            ), []

        return None, reserved_keys

    def _verify_readback(
        self,
        *,
        spec: GovernedActionSpec,
        payload: Dict[str, Any],
        allocated_id: Optional[str],
        corr_id: str,
        clean_nonce: str,
        payload_hash: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Perform transaction-specific read-back verification against Google Sheets (`fresh=True`).
        Raises BridgeResult-wrapped verification error marker (`_ReadBackFailure`) if unconfirmed.
        """
        db.invalidate_tab_cache(spec.target_tab)
        fresh_rows = db.get_records(spec.target_tab, fresh=True)
        matched: Optional[Dict[str, Any]] = None

        lookup_id = str(allocated_id or "").strip()
        if not lookup_id and spec.id_field:
            raw_payload_id = _lookup_expected_value(payload, spec.id_field)
            if raw_payload_id:
                lookup_id = str(raw_payload_id).strip()

        scoped_rows: Optional[List[Dict[str, Any]]] = None
        if spec.readback.expect_absent or spec.readback.expect_absent_or_soft_deleted:
            target_criteria: List[Tuple[str, str]] = []
            if spec.id_field and lookup_id:
                target_criteria = [(spec.id_field, lookup_id)]
            elif spec.readback.primary_match_fields:
                for f_name in spec.readback.primary_match_fields:
                    expected_v = _lookup_expected_value(payload, f_name)
                    if expected_v is not None and str(expected_v).strip() != "":
                        target_criteria.append((f_name, str(expected_v).strip()))
            if not target_criteria:
                raise _ReadBackFailure(
                    f"Cannot verify deletion read-back on '{spec.target_tab}': missing target identifier."
                )
            existing_row = next(
                (
                    r for r in fresh_rows
                    if all(str(r.get(k, "")).strip() == v for k, v in target_criteria)
                ),
                None,
            )
            if spec.readback.expect_absent:
                if existing_row is not None:
                    raise _ReadBackFailure(
                        f"Deleted row matching {target_criteria} still present on read-back in '{spec.target_tab}'."
                    )
            else:
                if existing_row is not None:
                    is_deleted_flag = _normalize_scalar(existing_row.get("deleted", "")) == "true"
                    is_inactive_flag = _normalize_scalar(existing_row.get("active", "")) == "false"
                    if not (is_deleted_flag or is_inactive_flag):
                        raise _ReadBackFailure(
                            f"Soft-deleted row matching {target_criteria} in '{spec.target_tab}' is still active on read-back."
                        )
            matched = None
        elif spec.id_field and lookup_id:
            matched = next(
                (r for r in fresh_rows if str(r.get(spec.id_field, "")).strip() == lookup_id),
                None,
            )
            if matched is None:
                raise _ReadBackFailure(
                    f"Primary row '{spec.target_tab}[{spec.id_field}={lookup_id}]' not found on read-back."
                )
        elif spec.readback.primary_match_fields:
            criteria = []
            for f_name in spec.readback.primary_match_fields:
                expected_v = _lookup_expected_value(payload, f_name)
                if expected_v is not None and str(expected_v).strip() != "":
                    criteria.append((f_name, str(expected_v).strip()))
            if not criteria:
                raise _ReadBackFailure(
                    f"Cannot verify read-back on '{spec.target_tab}': missing match fields {spec.readback.primary_match_fields}."
                )
            scoped_rows = [
                r for r in fresh_rows
                if all(str(r.get(k, "")).strip() == v for k, v in criteria)
            ]
            matched = scoped_rows[0] if scoped_rows else None
            if matched is None:
                raise _ReadBackFailure(
                    f"Primary row matching {criteria} on '{spec.target_tab}' not found on read-back."
                )

        if spec.readback.bulk_rows_check is not None:
            bulk_check = spec.readback.bulk_rows_check
            rows_pool = scoped_rows if scoped_rows is not None else fresh_rows
            submitted_items: List[Dict[str, Any]] = []
            for list_key in bulk_check.payload_list_keys:
                raw_list = payload.get(list_key)
                if isinstance(raw_list, list):
                    submitted_items.extend(item for item in raw_list if isinstance(item, dict))
            if not submitted_items:
                raise _ReadBackFailure(
                    f"Bulk read-back failed on '{spec.target_tab}': no submitted rows found in payload keys {bulk_check.payload_list_keys}."
                )
            for item in submitted_items:
                exp_key = str(item.get(bulk_check.item_key_field, "") or "").strip()
                if not exp_key:
                    raise _ReadBackFailure(
                        f"Bulk read-back failed on '{spec.target_tab}': submitted row missing '{bulk_check.item_key_field}'."
                    )
                exp_state_raw = item.get(bulk_check.item_state_field) if bulk_check.item_state_field else None
                check_state = (
                    bulk_check.item_state_field is not None
                    and exp_state_raw is not None
                    and str(exp_state_raw).strip() != ""
                )
                exp_state_norm = _normalize_scalar(exp_state_raw) if check_state else ""
                found_item = any(
                    str(r.get(bulk_check.item_key_field, "") or "").strip() == exp_key
                    and (
                        not check_state
                        or _normalize_scalar(r.get(bulk_check.item_state_field or "", "")) == exp_state_norm
                    )
                    for r in rows_pool
                )
                if not found_item:
                    raise _ReadBackFailure(
                        f"Bulk read-back failed on '{spec.target_tab}': missing or unconfirmed row for {bulk_check.item_key_field}='{exp_key}'."
                    )

        if matched is not None and spec.readback.state_assertions:
            for payload_key, record_field in spec.readback.state_assertions:
                exp_raw = _lookup_expected_value(payload, payload_key)
                if exp_raw is None or str(exp_raw).strip() == "":
                    continue
                exp_norm = _normalize_scalar(exp_raw)
                actual_norm = _normalize_scalar(matched.get(record_field, ""))
                if actual_norm != exp_norm:
                    raise _ReadBackFailure(
                        f"State mismatch on '{spec.target_tab}.{record_field}': expected '{exp_norm}', got '{actual_norm}'."
                    )

        if matched is not None and spec.readback.clear_assertions:
            for record_field in spec.readback.clear_assertions:
                actual_val = str(matched.get(record_field, "") or "").strip()
                if actual_val != "":
                    raise _ReadBackFailure(
                        f"Expected cleared field '{spec.target_tab}.{record_field}' to be empty, got '{actual_val}'."
                    )

        for child_check in spec.readback.child_checks:
            if child_check.condition_payload_key:
                cond_val = _lookup_expected_value(payload, child_check.condition_payload_key)
                if not cond_val:
                    continue

            if child_check.source_id_key == "allocated_id":
                fk_val = str(allocated_id or (matched.get(spec.id_field) if (matched and spec.id_field) else "") or "").strip()
            else:
                raw_fk = _lookup_expected_value(payload, child_check.source_id_key)
                if not raw_fk and matched:
                    raw_fk = matched.get(child_check.source_id_key)
                fk_val = str(raw_fk or "").strip()

            if not fk_val:
                raise _ReadBackFailure(
                    f"Missing foreign key '{child_check.source_id_key}' for child read-back on '{child_check.tab}'."
                )

            db.invalidate_tab_cache(child_check.tab)
            child_rows_all = db.get_records(child_check.tab, fresh=True)
            child_rows = [
                r for r in child_rows_all
                if str(r.get(child_check.fk_field, "")).strip() == fk_val
            ]

            expected_min = 1
            if child_check.min_rows_payload_key:
                items_val = _lookup_expected_value(payload, child_check.min_rows_payload_key)
                if isinstance(items_val, list) and len(items_val) > 0:
                    expected_min = len(items_val)

            if len(child_rows) < expected_min:
                raise _ReadBackFailure(
                    f"Child read-back failed on '{child_check.tab}' for {child_check.fk_field}={fk_val}: "
                    f"expected >= {expected_min} row(s), found {len(child_rows)}."
                )

            if child_check.verify_journal_balance:
                tot_deb = sum(Decimal(str(r.get("debit_amount", 0) or 0)) for r in child_rows)
                tot_crd = sum(Decimal(str(r.get("credit_amount", 0) or 0)) for r in child_rows)
                if abs(tot_deb - tot_crd) > Decimal("0.01"):
                    raise _ReadBackFailure(
                        f"JournalLines imbalance on {fk_val}: debit={tot_deb}, credit={tot_crd}."
                    )

        return matched

    def execute_governed_write(
        self,
        *,
        action: str,
        target_tab: str,
        payload: Dict[str, Any],
        nonce: str,
        actor_user_id: str,
        actor_role: str,
        id_field: Optional[str] = None,
        invalidate_tabs: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
    ) -> BridgeResult:
        corr_id = correlation_id or f"CORR-{uuid.uuid4().hex[:12].upper()}"
        clean_nonce = str(nonce or "").strip()
        clean_action = str(action or "").strip().upper()
        clean_tab = str(target_tab or "").strip()

        if not clean_nonce:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce="",
                error_code="MISSING_IDEMPOTENCY_NONCE",
                message="Client idempotency nonce is required for governed writes.",
                retryable=False,
                http_status=422,
            )

        if is_forbidden_scratch_tab(clean_tab):
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="SCRATCH_TAB_FORBIDDEN",
                message=f"Write rejected: legacy scratch tab '{clean_tab}' is forbidden.",
                retryable=False,
                http_status=403,
            )

        # Strict centralized action-to-table allowlist enforcement
        spec = get_governed_action_spec(clean_action)
        if spec is None:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="UNREGISTERED_GOVERNED_ACTION",
                message=f"Governed action '{clean_action}' is not registered in the allowlist.",
                retryable=False,
                http_status=403,
            )

        if clean_tab != spec.target_tab:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="ACTION_TABLE_MISMATCH",
                message=f"Action '{clean_action}' may only target '{spec.target_tab}', not '{clean_tab}'.",
                retryable=False,
                http_status=422,
            )

        if id_field != spec.id_field:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="ACTION_ID_FIELD_MISMATCH",
                message=f"Action '{clean_action}' requires id_field='{spec.id_field}', got '{id_field}'.",
                retryable=False,
                http_status=422,
            )

        requested_inv = [str(t or "").strip() for t in (invalidate_tabs or []) if str(t or "").strip()]
        bad_inv_tabs = [
            t for t in requested_inv
            if is_forbidden_scratch_tab(t) or t not in spec.allowed_invalidate_tabs
        ]
        if bad_inv_tabs:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="UNAUTHORIZED_INVALIDATION_TAB",
                message=f"Action '{clean_action}' attempted unauthorized cache invalidation tabs: {bad_inv_tabs}.",
                retryable=False,
                http_status=422,
            )

        # Fail-closed schema write gate across the FULL authoritative union of:
        # 1. Primary target tab (`clean_tab`)
        # 2. ALL required secondary tabs declared on the trusted action spec (`spec.allowed_invalidate_tabs`)
        # 3. Any caller-requested invalidation tabs (`requested_inv`, already allowlist-checked)
        # 4. ALL read-back child tabs (`spec.readback.child_checks`)
        # Caller-supplied `invalidate_tabs` can NEVER replace or shrink the required validation set (P1.5-001).
        candidate_write_tabs: List[str] = [clean_tab]
        for sec_tab in sorted(spec.allowed_invalidate_tabs):
            if sec_tab not in candidate_write_tabs:
                candidate_write_tabs.append(sec_tab)
        for req_tab in requested_inv:
            if req_tab not in candidate_write_tabs:
                candidate_write_tabs.append(req_tab)
        for child_check in spec.readback.child_checks:
            if child_check.tab not in candidate_write_tabs:
                candidate_write_tabs.append(child_check.tab)

        for candidate_tab in candidate_write_tabs:
            schema_block = get_schema_write_block_reason(candidate_tab)
            if schema_block is not None:
                is_secondary = candidate_tab != clean_tab
                base_msg = str(
                    schema_block.get("message")
                    or f"Governed write blocked for '{candidate_tab}'. Data was NOT SAVED."
                )
                msg = (
                    f"Action '{clean_action}' blocked on secondary table '{candidate_tab}': {base_msg}"
                    if is_secondary
                    else base_msg
                )
                return BridgeResult(
                    status="BLOCKED_PENDING_OWNER_SETUP",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code=str(schema_block.get("error_code") or "PENDING_OWNER_MAPPING"),
                    dependency=str(schema_block.get("dependency") or "OWNER_SCHEMA_MAPPING_DEPENDENCY"),
                    message=msg,
                    retryable=False,
                    http_status=503,
                )

        payload_hash = self.compute_payload_hash(
            action=clean_action,
            target_tab=clean_tab,
            nonce=clean_nonce,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload=payload,
        )

        # Pre-write identifier, prefix, child-row, and cross-table collision validation (P1.5-002 / P1.5-007 / Phase 1.8)
        preflight_id_err, reserved_inflight_keys = self._preflight_validate_payload_ids(
            spec=spec,
            payload=payload,
            corr_id=corr_id,
            clean_nonce=clean_nonce,
            payload_hash=payload_hash,
        )
        if preflight_id_err is not None:
            return preflight_id_err

        try:
            return self._execute_after_preflight(
                spec=spec,
                clean_action=clean_action,
                clean_tab=clean_tab,
                payload=payload,
                corr_id=corr_id,
                clean_nonce=clean_nonce,
                payload_hash=payload_hash,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                requested_inv=requested_inv,
            )
        finally:
            self._release_inflight_ids(reserved_inflight_keys, corr_id)

    def _execute_after_preflight(
        self,
        *,
        spec: GovernedActionSpec,
        clean_action: str,
        clean_tab: str,
        payload: Dict[str, Any],
        corr_id: str,
        clean_nonce: str,
        payload_hash: str,
        actor_user_id: str,
        actor_role: str,
        requested_inv: List[str],
    ) -> BridgeResult:
        if not self.is_configured():
            return BridgeResult(
                status="BLOCKED_PENDING_OWNER_SETUP",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="APPS_SCRIPT_BRIDGE_UNCONFIGURED",
                dependency="APPS_SCRIPT_DEPENDENCY",
                message=(
                    "Governed write blocked (APPS_SCRIPT_DEPENDENCY): Single-Write-Owner Apps Script Web App "
                    "URL (https://) or >=32-char HMAC secret is not configured. Data was NOT SAVED."
                ),
                retryable=True,
                http_status=503,
                payload_hash=payload_hash,
            )

        envelope = {
            "action": clean_action,
            "target_tab": clean_tab,
            "nonce": clean_nonce,
            "correlation_id": corr_id,
            "payload_hash": payload_hash,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "timestamp": now_iso(),
            "payload": payload,
        }
        canonical_body = json.dumps(envelope, separators=(",", ":"), sort_keys=True, default=str)
        signature = self.sign_envelope(canonical_body, SALES_APPS_SCRIPT_SHARED_SECRET)

        req = urllib.request.Request(
            SALES_APPS_SCRIPT_WEBAPP_URL,
            data=canonical_body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-KS-Signature": signature,
                "X-KS-Correlation-Id": corr_id,
                "X-KS-Idempotency-Key": clean_nonce,
                "X-KS-Payload-Hash": payload_hash,
            },
        )
        opener = urllib.request.build_opener(_NoRedirectHandler)

        try:
            with opener.open(req, timeout=SALES_APPS_SCRIPT_TIMEOUT_SECONDS) as resp:
                raw_text = resp.read().decode("utf-8", errors="replace").strip()
                if not raw_text:
                    raise ValueError("Empty response body from Apps Script bridge.")
                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict):
                    raise TypeError(f"Expected JSON object from Apps Script bridge, got {type(parsed).__name__}.")
                data: Dict[str, Any] = parsed
        except urllib.error.HTTPError as http_err:
            code = http_err.code
            if 300 <= code < 400:
                logger.warning("Blocked HTTP %s redirect from Apps Script bridge action=%s corr=%s", code, clean_action, corr_id)
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code=f"APPS_SCRIPT_REDIRECT_BLOCKED_{code}",
                    message=f"Apps Script endpoint attempted HTTP {code} redirect; blocked for HMAC envelope safety.",
                    retryable=False,
                    http_status=502,
                    payload_hash=payload_hash,
                )
            if 400 <= code < 500:
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code=f"APPS_SCRIPT_HTTP_{code}",
                    message=f"Apps Script rejected request '{clean_action}' (HTTP {code}). Form data was NOT SAVED.",
                    retryable=False,
                    http_status=code,
                    payload_hash=payload_hash,
                )
            logger.warning("Ambiguous Apps Script HTTP %s for action=%s corr=%s", code, clean_action, corr_id)
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="APPS_SCRIPT_UNKNOWN_OUTCOME",
                message="Status not confirmed; do not submit a new transaction. Retry safely with the same nonce.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )
        except Exception as exc:
            logger.warning("Invalid/timeout response calling Apps Script for action=%s corr=%s: %s", clean_action, corr_id, exc)
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="APPS_SCRIPT_UNKNOWN_OUTCOME",
                message="Status not confirmed; do not submit a new transaction. Retry safely with the same nonce.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        # Validate echoed correlation, nonce, action, and target_tab if returned
        echo_corr = str(data.get("correlation_id") or "").strip()
        if echo_corr and echo_corr != corr_id:
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="RESPONSE_CORRELATION_MISMATCH",
                message="Status not confirmed; Apps Script response correlation_id did not match request.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        echo_nonce = str(data.get("nonce") or data.get("idempotency_key") or "").strip()
        if echo_nonce and echo_nonce != clean_nonce:
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="RESPONSE_NONCE_MISMATCH",
                message="Status not confirmed; Apps Script response nonce did not match request.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        echo_action = str(data.get("action") or "").strip().upper()
        if echo_action and echo_action != clean_action:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="RESPONSE_ACTION_MISMATCH",
                message=f"Apps Script response action '{echo_action}' did not match '{clean_action}'.",
                retryable=False,
                http_status=502,
                payload_hash=payload_hash,
            )

        echo_tab = str(data.get("target_tab") or "").strip()
        if echo_tab and echo_tab != clean_tab:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="RESPONSE_TABLE_MISMATCH",
                message=f"Apps Script response target_tab '{echo_tab}' did not match '{clean_tab}'.",
                retryable=False,
                http_status=502,
                payload_hash=payload_hash,
            )

        outcome = str(data.get("status", "")).strip().upper()
        if outcome == "REJECTED":
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code=str(data.get("error_code") or "APPS_SCRIPT_REJECTED"),
                message=str(data.get("message") or "Apps Script did not confirm write. NOT SAVED."),
                retryable=bool(data.get("retryable", False)),
                http_status=int(data.get("http_status") or 422),
                payload_hash=payload_hash,
            )
        if outcome != "CONFIRMED":
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code=str(data.get("error_code") or "APPS_SCRIPT_UNCONFIRMED_STATUS"),
                message="Status not confirmed; do not submit a new transaction. Retry safely with the same nonce.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        # Mandatory fail-closed echo presence check for all CONFIRMED responses
        if not echo_corr:
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="MISSING_RESPONSE_CORRELATION",
                message="Status not confirmed; Apps Script CONFIRMED response omitted correlation_id.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )
        if not echo_nonce:
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="MISSING_RESPONSE_NONCE",
                message="Status not confirmed; Apps Script CONFIRMED response omitted nonce.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )
        if not echo_action:
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="MISSING_RESPONSE_ACTION",
                message="Status not confirmed; Apps Script CONFIRMED response omitted action.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )
        if not echo_tab:
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="MISSING_RESPONSE_TABLE",
                message="Status not confirmed; Apps Script CONFIRMED response omitted target_tab.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        record_obj = data.get("record")
        if record_obj is not None and not isinstance(record_obj, dict):
            record_obj = None
        record: Optional[Dict[str, Any]] = record_obj

        raw_alloc = data.get("allocated_id") or (record.get(spec.id_field) if (record and spec.id_field) else None)
        allocated_id = str(raw_alloc).strip() if raw_alloc is not None and str(raw_alloc).strip() else None

        if spec.requires_allocated_id and not allocated_id:
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="MISSING_ALLOCATED_ID",
                message="Status not confirmed; Apps Script omitted allocated_id for creation write.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        effective_locked_prefix = self._effective_locked_prefix(spec)
        should_validate_allocated = bool(
            allocated_id
            and (
                effective_locked_prefix
                or spec.requires_allocated_id
                or spec.target_tab in COLLIDING_LEGACY_PREFIX_TABS
            )
        )
        if should_validate_allocated and not self._validate_id_format(spec, allocated_id):
            allowed_prefixes = get_allowed_id_prefixes_for_tab(
                spec.target_tab,
                for_new_allocation=True,
                explicit_locked_prefix=effective_locked_prefix,
            )
            allowed_desc = ", ".join(allowed_prefixes) if allowed_prefixes else "non-colliding canonical format"
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=allocated_id,
                error_code="INVALID_ALLOCATED_ID_FORMAT",
                message=(
                    f"Status not confirmed; allocated_id '{allocated_id}' failed prefix validation for "
                    f"'{spec.target_tab}' (allowed: {allowed_desc})."
                ),
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        # Defense-in-depth post-write validation for SalaryReceipts child-row IDs (P1.5-002)
        if any(c.tab == "SalaryReceipts" for c in spec.readback.child_checks) or "SalaryReceipts" in spec.allowed_invalidate_tabs:
            child_receipt_id = str(
                data.get("receipt_id")
                or (record.get("receipt_id") if isinstance(record, dict) else "")
                or ""
            ).strip()
            if child_receipt_id and not validate_table_id_prefix("SalaryReceipts", child_receipt_id, for_new_allocation=True):
                return BridgeResult(
                    status="PENDING_UNKNOWN",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    allocated_id=allocated_id,
                    error_code="INVALID_CHILD_ALLOCATED_ID_FORMAT",
                    message=(
                        f"Status not confirmed; child SalaryReceipts identifier '{child_receipt_id}' "
                        "violates table prefix/collision rules (RCPT is locked to Payments)."
                    ),
                    retryable=True,
                    http_status=504,
                    payload_hash=payload_hash,
                )

        # Explicit transaction-specific read-back verification before confirming
        try:
            verified_record = self._verify_readback(
                spec=spec,
                payload=payload,
                allocated_id=allocated_id,
                corr_id=corr_id,
                clean_nonce=clean_nonce,
                payload_hash=payload_hash,
            )
            if verified_record is not None:
                record = verified_record
                if not allocated_id and spec.id_field and verified_record.get(spec.id_field):
                    allocated_id = str(verified_record.get(spec.id_field)).strip()
        except _ReadBackFailure as rb_fail:
            logger.warning("Read-back unconfirmed for action=%s corr=%s: %s", clean_action, corr_id, rb_fail)
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=allocated_id,
                error_code="READ_BACK_UNCONFIRMED",
                message=f"Status not confirmed; do not submit a new transaction. {rb_fail}",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )
        except Exception as rb_exc:
            logger.warning("Read-back failed after Apps Script response corr=%s: %s", corr_id, rb_exc)
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=allocated_id,
                error_code="READ_BACK_UNCONFIRMED",
                message="Status not confirmed; do not submit a new transaction.",
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
            )

        # Immediate full-union allowlisted cache invalidation on confirmed write
        tabs_to_clear = set(requested_inv) | set(spec.allowed_invalidate_tabs) | {spec.target_tab}
        for tab in tabs_to_clear:
            db.invalidate_tab_cache(tab)

        return BridgeResult(
            status="CONFIRMED",
            correlation_id=corr_id,
            nonce=clean_nonce,
            allocated_id=allocated_id,
            record=record if isinstance(record, dict) else None,
            message=str(data.get("message") or "Write confirmed via Apps Script read-back."),
            retryable=False,
            http_status=200,
            payload_hash=payload_hash,
        )

    def delegate_governed_write(
        self,
        *,
        action: str,
        target_tab: str,
        payload: Dict[str, Any],
        actor_user_id: str,
        actor_role: str,
        nonce: Optional[str] = None,
        request: Optional[Request] = None,
        id_field: Optional[str] = None,
        invalidate_tabs: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
        allow_generated_nonce: bool = False,
    ) -> Dict[str, Any]:
        """
        Single-Write-Owner delegation helper for all FastAPI endpoints and services.
        Raises HTTPException fail-closed unless Apps Script confirms the write.
        """
        resolved_nonce = self.extract_request_nonce(request=request, explicit_nonce=nonce)
        if not resolved_nonce and allow_generated_nonce:
            resolved_nonce = f"REQ-{uuid.uuid4().hex[:16].upper()}"

        res = self.execute_governed_write(
            action=action,
            target_tab=target_tab,
            payload=payload,
            nonce=resolved_nonce,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            id_field=id_field,
            invalidate_tabs=invalidate_tabs,
            correlation_id=correlation_id,
        )
        if res.status == "CONFIRMED":
            return {
                "status": "CONFIRMED",
                "correlation_id": res.correlation_id,
                "nonce": res.nonce,
                "payload_hash": res.payload_hash,
                "allocated_id": res.allocated_id,
                "record": res.record,
                "message": res.message,
            }
        raise HTTPException(
            status_code=res.http_status,
            detail={
                "status": res.status,
                "error_code": res.error_code or "GOVERNED_WRITE_NOT_CONFIRMED",
                "dependency": res.dependency,
                "message": res.message,
                "correlation_id": res.correlation_id,
                "nonce": res.nonce,
                "payload_hash": res.payload_hash,
                "retryable": res.retryable,
                "allocated_id": res.allocated_id,
            },
        )

    def check_transaction_status(
        self,
        *,
        nonce: str,
        correlation_id: Optional[str] = None,
        actor_is_owner: bool = False,
    ) -> Dict[str, Any]:
        """
        Read-only transaction status lookup against IdAllocations and AuditLog (`fresh=True`).
        Allows clients recovering from HTTP 504 / PENDING_UNKNOWN timeouts to verify whether a
        prior governed write committed before deciding to retry safely with the SAME nonce.
        Never mutates Google Sheets and redacts confidential table details for non-OWNER_ADMIN roles.
        """
        clean_nonce = str(nonce or "").strip()
        clean_corr = str(correlation_id or "").strip()
        if not clean_nonce:
            raise ValueError("Transaction nonce is required for status lookup.")

        checked_at = now_iso()
        alloc_match: Optional[Dict[str, Any]] = None
        audit_match: Optional[Dict[str, Any]] = None
        alloc_error: Optional[str] = None
        audit_error: Optional[str] = None

        try:
            db.invalidate_tab_cache("IdAllocations")
            alloc_rows = db.get_records("IdAllocations", fresh=True) or []
            alloc_match = next(
                (r for r in alloc_rows if str(r.get("nonce", "")).strip() == clean_nonce),
                None,
            )
        except Exception as exc:
            alloc_error = str(exc)

        try:
            db.invalidate_tab_cache("AuditLog")
            audit_rows = db.get_records("AuditLog", fresh=True) or []
            alloc_id_hint = str((alloc_match or {}).get("allocated_id", "")).strip()
            for row in reversed(audit_rows):
                row_related = str(row.get("related_record_id", "")).strip()
                row_entity = str(row.get("entity_id", "")).strip()
                row_reason = str(row.get("reason", "")).strip()
                row_new = str(row.get("new_value", "")).strip()
                if (
                    clean_nonce in {row_related, row_entity}
                    or (clean_nonce and (clean_nonce in row_reason or clean_nonce in row_new))
                    or (clean_corr and (clean_corr in row_related or clean_corr in row_reason))
                    or (alloc_id_hint and row_entity == alloc_id_hint)
                ):
                    audit_match = row
                    break
        except Exception as exc:
            audit_error = str(exc)

        if alloc_match or audit_match:
            tab_name = str(
                (alloc_match or {}).get("tab_name")
                or (audit_match or {}).get("entity_type")
                or ""
            ).strip()
            allocated_id = str(
                (alloc_match or {}).get("allocated_id")
                or (audit_match or {}).get("entity_id")
                or ""
            ).strip() or None
            is_confidential_tab = tab_name in CONFIDENTIAL_TABS_NO_CACHE or tab_name in SECURITY_NO_CACHE_TABS
            safe_audit: Optional[Dict[str, Any]] = None
            if audit_match:
                safe_audit = {
                    "audit_id": str(audit_match.get("audit_id", "")).strip(),
                    "event_datetime": str(audit_match.get("event_datetime", "")).strip(),
                    "action": str(audit_match.get("action", "")).strip(),
                    "entity_type": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else str(audit_match.get("entity_type", "")).strip(),
                    "entity_id": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else str(audit_match.get("entity_id", "")).strip(),
                }
            return {
                "status": "CONFIRMED_RECORDED",
                "nonce": clean_nonce,
                "correlation_id": clean_corr or None,
                "allocated_id": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else allocated_id,
                "tab_name": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else (tab_name or None),
                "recorded_at": str(
                    (alloc_match or {}).get("created_at")
                    or (audit_match or {}).get("event_datetime")
                    or ""
                ).strip() or None,
                "audit_entry": safe_audit,
                "safe_to_retry_same_nonce": False,
                "checked_at": checked_at,
                "message": (
                    "Transaction was already recorded in Google Sheets. Do NOT submit a duplicate transaction; "
                    "refresh the view to see the saved record."
                ),
            }

        if alloc_error and audit_error:
            return {
                "status": "UNKNOWN_STORAGE_UNAVAILABLE",
                "nonce": clean_nonce,
                "correlation_id": clean_corr or None,
                "allocated_id": None,
                "tab_name": None,
                "recorded_at": None,
                "audit_entry": None,
                "safe_to_retry_same_nonce": False,
                "checked_at": checked_at,
                "message": (
                    "Outcome still unknown: Google Sheets status tables (IdAllocations/AuditLog) are currently unreachable. "
                    "Keep your form inputs and retry status check before submitting again."
                ),
            }

        return {
            "status": "NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE",
            "nonce": clean_nonce,
            "correlation_id": clean_corr or None,
            "allocated_id": None,
            "tab_name": None,
            "recorded_at": None,
            "audit_entry": None,
            "safe_to_retry_same_nonce": True,
            "checked_at": checked_at,
            "message": (
                "No committed entry was found for this nonce in IdAllocations or AuditLog. "
                "You may safely retry the submission using the SAME preserved nonce."
            ),
        }


class _ReadBackFailure(RuntimeError):
    """Internal fail-closed signal when Sheets read-back does not confirm the committed write."""


apps_script_bridge = AppsScriptBridge()
