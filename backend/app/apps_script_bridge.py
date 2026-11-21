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
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request

from app.accounting.transaction_coordinator import tx_coordinator
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
from app.transaction_safety import (
    FailureCategory,
    TransactionState,
    classify_gateway_exception,
    compute_deterministic_payload_hash,
    map_http_status_to_failure_category,
    sanitize_audit_metadata,
)

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
    status: str  # CONFIRMED | REJECTED | PENDING_UNKNOWN | RECOVERY_REQUIRED | BLOCKED_PENDING_OWNER_SETUP
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
    transaction_id: Optional[str] = None
    transaction_state: Optional[str] = None
    failure_category: Optional[str] = None
    attempt_number: int = 1
    is_replay: bool = False
    audit_logged: bool = False
    recovery_decision: Optional[str] = None


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
        nonce: str = "",
        actor_user_id: str,
        actor_role: str,
        payload: Dict[str, Any],
    ) -> str:
        """
        Compute a deterministic SHA-256 digest over the normalized logical business operation
        excluding volatile per-attempt metadata (timestamps, correlation IDs, nonces) while
        canonically normalizing numbers, booleans, empty strings/nulls, and sorted keys.
        """
        _ = nonce  # Nonce is the transaction key; payload fingerprint compares logical business intent
        return compute_deterministic_payload_hash(
            action=action,
            target_tab=target_tab,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload=payload,
        )

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

    @staticmethod
    def _record_tx_audit(
        *,
        actor_user_id: str,
        action: str,
        target_tab: str,
        entity_id: str,
        transaction_id: Optional[str],
        correlation_id: str,
        nonce: str,
        lifecycle_state: str,
        failure_category: Optional[str] = None,
        error_code: Optional[str] = None,
        attempt_number: int = 1,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Emit a structured, secret-redacted transaction audit event without crashing callers."""
        safe_meta = sanitize_audit_metadata(
            {
                "transaction_id": transaction_id or "",
                "correlation_id": correlation_id,
                "nonce": nonce,
                "state": lifecycle_state,
                "failure_category": failure_category or "",
                "error_code": error_code or "",
                "attempt": attempt_number,
                **(metadata or {}),
            }
        )
        tx_audit_action = str(action or "").strip().upper()
        if tx_audit_action and not tx_audit_action.startswith("TX_"):
            tx_audit_action = f"TX_AUDIT:{tx_audit_action}"
        log_fn = getattr(db, "log_transaction_audit", None)
        try:
            if callable(log_fn):
                return bool(
                    log_fn(
                        actor=actor_user_id,
                        action=tx_audit_action,
                        entity_type=target_tab,
                        entity_id=entity_id or nonce,
                        transaction_id=transaction_id or "",
                        correlation_id=correlation_id,
                        nonce=nonce,
                        lifecycle_state=lifecycle_state,
                        failure_category=failure_category or "",
                        error_code=error_code or "",
                        attempt_number=attempt_number,
                        reason=reason,
                        metadata=safe_meta,
                    )
                )
            db.log_audit(
                actor=actor_user_id,
                action=tx_audit_action,
                entity_type=target_tab,
                entity_id=entity_id or nonce,
                reason=f"[{lifecycle_state}] {reason}".strip(),
                related_id=nonce,
            )
            return True
        except Exception as audit_exc:
            logger.error(
                "Structured transaction audit logging failed tx=%s nonce=%s action=%s: %s",
                transaction_id,
                nonce,
                action,
                audit_exc,
            )
            return False

    @staticmethod
    def _get_fresh_records_with_retry(
        tab_name: str,
        *,
        max_attempts: int = 2,
        retry_delay_s: float = 0.12,
    ) -> List[Dict[str, Any]]:
        """Bounded fresh read-back helper that retries once on transient Sheets read errors."""
        last_exc: Optional[Exception] = None
        for attempt in range(max(1, max_attempts)):
            try:
                db.invalidate_tab_cache(tab_name)
                rows = db.get_records(tab_name, fresh=True)
                if not isinstance(rows, list):
                    raise _ReadBackFailure(
                        f"Fresh read-back for '{tab_name}' returned non-list type {type(rows).__name__}."
                    )
                return rows
            except _ReadBackFailure:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < max_attempts and retry_delay_s > 0:
                    time.sleep(retry_delay_s)
        raise _ReadBackFailure(
            f"Transient read-back error on '{tab_name}' after {max_attempts} attempts: {last_exc}"
        )

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
        Distinguishes:
        - `_ReadBackFailure`: primary row absent or transient storage outage (`PENDING_UNKNOWN`).
        - `_PartialSideEffectFailure`: primary row duplicated OR primary row written with
          mismatched state, missing/imbalanced child rows, or inconsistent totals (`RECOVERY_REQUIRED`).
        """
        fresh_rows = self._get_fresh_records_with_retry(spec.target_tab)
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
            matched_rows = [
                r for r in fresh_rows
                if str(r.get(spec.id_field, "")).strip() == lookup_id
            ]
            if not matched_rows:
                raise _ReadBackFailure(
                    f"Primary row '{spec.target_tab}[{spec.id_field}={lookup_id}]' not found on read-back."
                )
            if len(matched_rows) > 1:
                raise _PartialSideEffectFailure(
                    f"Duplicate primary rows ({len(matched_rows)}) detected in '{spec.target_tab}' "
                    f"for {spec.id_field}={lookup_id}."
                )
            matched = matched_rows[0]
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
            found_count = 0
            missing_keys: List[str] = []
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
                if found_item:
                    found_count += 1
                else:
                    missing_keys.append(exp_key)
            if missing_keys:
                if found_count > 0:
                    raise _PartialSideEffectFailure(
                        f"Partial bulk write on '{spec.target_tab}': {found_count}/{len(submitted_items)} confirmed; "
                        f"missing {bulk_check.item_key_field}={missing_keys[:5]}."
                    )
                raise _ReadBackFailure(
                    f"Bulk read-back failed on '{spec.target_tab}': missing or unconfirmed row for {bulk_check.item_key_field}='{missing_keys[0]}'."
                )

        if matched is not None and spec.readback.state_assertions:
            for payload_key, record_field in spec.readback.state_assertions:
                exp_raw = _lookup_expected_value(payload, payload_key)
                if exp_raw is None or str(exp_raw).strip() == "":
                    continue
                exp_norm = _normalize_scalar(exp_raw)
                actual_norm = _normalize_scalar(matched.get(record_field, ""))
                if actual_norm != exp_norm:
                    raise _PartialSideEffectFailure(
                        f"State mismatch on '{spec.target_tab}.{record_field}': expected '{exp_norm}', got '{actual_norm}'."
                    )

        if matched is not None and spec.readback.clear_assertions:
            for record_field in spec.readback.clear_assertions:
                actual_val = str(matched.get(record_field, "") or "").strip()
                if actual_val != "":
                    raise _PartialSideEffectFailure(
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

            child_rows_all = self._get_fresh_records_with_retry(child_check.tab)
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
                err_msg = (
                    f"Partial side effect on '{child_check.tab}' for {child_check.fk_field}={fk_val}: "
                    f"expected >= {expected_min} row(s), found {len(child_rows)}."
                )
                if matched is not None:
                    raise _PartialSideEffectFailure(err_msg)
                raise _ReadBackFailure(err_msg)

            if child_check.verify_journal_balance:
                tot_deb = sum(Decimal(str(r.get("debit_amount", 0) or 0)) for r in child_rows)
                tot_crd = sum(Decimal(str(r.get("credit_amount", 0) or 0)) for r in child_rows)
                if abs(tot_deb - tot_crd) > Decimal("0.01"):
                    raise _PartialSideEffectFailure(
                        f"JournalLines imbalance on {fk_val}: debit={tot_deb}, credit={tot_crd}."
                    )

            # Financial consistency verification for SaleItems vs Sales subtotal / net bill_total
            # Accounting identity: bill_total = subtotal - discount_amount + tax_amount
            if child_check.tab == "SaleItems" and matched is not None:
                raw_subtotal = matched.get("subtotal")
                raw_bill_total = matched.get("bill_total")
                item_line_totals = [
                    r.get("line_total")
                    for r in child_rows
                    if r.get("line_total") not in (None, "")
                ]
                if len(item_line_totals) == len(child_rows) and (raw_subtotal not in (None, "") or raw_bill_total not in (None, "")):
                    try:
                        lines_dec = sum(Decimal(str(lt)) for lt in item_line_totals)
                        if raw_subtotal not in (None, ""):
                            expected_lines_dec = Decimal(str(raw_subtotal))
                            expected_label = "Sales.subtotal"
                        else:
                            bill_dec = Decimal(str(raw_bill_total))
                            disc_dec = Decimal(str(matched.get("discount_amount") or 0))
                            tax_dec = Decimal(str(matched.get("tax_amount") or 0))
                            expected_lines_dec = bill_dec + disc_dec - tax_dec
                            expected_label = "Sales.bill_total"
                        if abs(lines_dec - expected_lines_dec) > Decimal("0.50"):
                            raise _PartialSideEffectFailure(
                                f"SaleItems line_total sum ({lines_dec}) mismatches {expected_label} ({expected_lines_dec}) for {fk_val}."
                            )
                    except (InvalidOperation, ValueError):
                        pass

        return matched

    def _build_replay_confirmed_result(
        self,
        *,
        existing_tx: Dict[str, Any],
        corr_id: str,
        clean_nonce: str,
        payload_hash: str,
        actor_user_id: str,
        clean_action: str,
        clean_tab: str,
        recovery_decision: Optional[str] = "IDEMPOTENT_REPLAY_COMMITTED",
    ) -> BridgeResult:
        snapshot = existing_tx.get("result_snapshot")
        record = snapshot if isinstance(snapshot, dict) else None
        allocated_id = existing_tx.get("allocated_id")
        tx_id = existing_tx.get("transaction_id")
        attempt_no = int(existing_tx.get("attempt_count") or 1)
        lifecycle = str(existing_tx.get("lifecycle_state") or TransactionState.COMMITTED.value)
        audit_ok = self._record_tx_audit(
            actor_user_id=actor_user_id,
            action=clean_action,
            target_tab=clean_tab,
            entity_id=str(allocated_id or clean_nonce),
            transaction_id=tx_id,
            correlation_id=corr_id,
            nonce=clean_nonce,
            lifecycle_state=lifecycle,
            attempt_number=attempt_no,
            reason="Idempotent replay returned verified committed outcome without duplicate write.",
            metadata={"is_replay": True, "recovery_decision": recovery_decision},
        )
        return BridgeResult(
            status="CONFIRMED",
            correlation_id=corr_id,
            nonce=clean_nonce,
            allocated_id=allocated_id,
            record=record,
            message=str(existing_tx.get("message") or "Transaction already confirmed (idempotent replay)."),
            retryable=False,
            http_status=200,
            payload_hash=payload_hash,
            transaction_id=tx_id,
            transaction_state=lifecycle,
            attempt_number=attempt_no,
            is_replay=True,
            audit_logged=audit_ok,
            recovery_decision=recovery_decision,
        )

    def recover_transaction(
        self,
        *,
        nonce: str,
        spec: GovernedActionSpec,
        payload: Dict[str, Any],
        corr_id: str,
        payload_hash: str,
        actor_user_id: str,
        actor_role: str,
        existing_tx: Dict[str, Any],
        requested_inv: List[str],
    ) -> Optional[BridgeResult]:
        """
        Evidence-based recovery inspection for an UNKNOWN / RECOVERY_REQUIRED / stale-lease transaction.

        Inspects authoritative Google Sheets (`IdAllocations`, `AuditLog`, target tab, child tabs)
        BEFORE permitting any retry:
        - Returns `CONFIRMED` (`is_replay=True`) if all required primary + child effects exist cleanly.
        - Returns `RECOVERY_REQUIRED` (HTTP 409, `retryable=False`) if orphan ID allocation, partial
          child writes, state mismatch, or duplicate primary rows are detected.
        - Returns `PENDING_UNKNOWN` (HTTP 504, `retryable=True`) if authoritative Sheets reads fail.
        - Returns `None` ONLY when Sheets is healthy AND zero side effects exist, authorizing a safe
          same-nonce retry.
        """
        clean_nonce = str(nonce or "").strip()
        tx_id = existing_tx.get("transaction_id")
        attempt_no = int(existing_tx.get("attempt_count") or 1)

        alloc_match: Optional[Dict[str, Any]] = None
        audit_match: Optional[Dict[str, Any]] = None
        read_errors: List[str] = []

        try:
            alloc_rows = self._get_fresh_records_with_retry("IdAllocations", max_attempts=2, retry_delay_s=0.05)
            alloc_match = next(
                (r for r in alloc_rows if str(r.get("nonce", "")).strip() == clean_nonce),
                None,
            )
        except Exception as exc:
            read_errors.append(f"IdAllocations: {exc}")

        try:
            audit_rows = self._get_fresh_records_with_retry("AuditLog", max_attempts=2, retry_delay_s=0.05)
            alloc_id_hint = str((alloc_match or {}).get("allocated_id") or existing_tx.get("allocated_id") or "").strip()
            for row in reversed(audit_rows):
                row_related = str(row.get("related_record_id", "")).strip()
                row_entity = str(row.get("entity_id", "")).strip()
                row_reason = str(row.get("reason", "")).strip()
                row_new = str(row.get("new_value", "")).strip()
                if (
                    clean_nonce in {row_related, row_entity}
                    or (clean_nonce and (clean_nonce in row_reason or clean_nonce in row_new))
                    or (alloc_id_hint and row_entity == alloc_id_hint)
                ):
                    audit_match = row
                    break
        except Exception as exc:
            read_errors.append(f"AuditLog: {exc}")

        if read_errors:
            tx_coordinator.transition_governed_transaction(
                nonce=clean_nonce,
                lifecycle_state=TransactionState.UNKNOWN.value,
                bridge_status="PENDING_UNKNOWN",
                failure_category=FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                error_code="RECOVERY_STORAGE_UNAVAILABLE",
                message="Recovery inspection blocked: authoritative Sheets status tables are unreachable.",
                recovery_decision="DEFER_STORAGE_UNAVAILABLE",
                step_event={"step": "RECOVERY_DEFERRED_STORAGE_ERROR", "errors": read_errors[:3]},
                clear_lease=True,
            )
            audit_ok = self._record_tx_audit(
                actor_user_id=actor_user_id,
                action=spec.action,
                target_tab=spec.target_tab,
                entity_id=str(existing_tx.get("allocated_id") or clean_nonce),
                transaction_id=tx_id,
                correlation_id=corr_id,
                nonce=clean_nonce,
                lifecycle_state=TransactionState.UNKNOWN.value,
                failure_category=FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                error_code="RECOVERY_STORAGE_UNAVAILABLE",
                attempt_number=attempt_no,
                reason="Recovery check could not reach Google Sheets; blind retry prevented.",
            )
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=existing_tx.get("allocated_id"),
                error_code="RECOVERY_STORAGE_UNAVAILABLE",
                message=(
                    "Outcome still unknown: authoritative Google Sheets status tables are unreachable. "
                    "Blind retry blocked; re-check transaction status once storage recovers."
                ),
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
                transaction_id=tx_id,
                transaction_state=TransactionState.UNKNOWN.value,
                failure_category=FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                attempt_number=attempt_no,
                audit_logged=audit_ok,
                recovery_decision="DEFER_STORAGE_UNAVAILABLE",
            )

        candidate_id = str(
            (alloc_match or {}).get("allocated_id")
            or existing_tx.get("allocated_id")
            or (audit_match or {}).get("entity_id")
            or (_lookup_expected_value(payload, spec.id_field) if spec.id_field else "")
            or ""
        ).strip() or None

        has_prior_evidence = bool(alloc_match or audit_match or candidate_id)
        if has_prior_evidence:
            try:
                verified_record = self._verify_readback(
                    spec=spec,
                    payload=payload,
                    allocated_id=candidate_id,
                    corr_id=corr_id,
                    clean_nonce=clean_nonce,
                    payload_hash=payload_hash,
                )
                # Verified complete commit in Google Sheets -> recover cleanly to COMMITTED!
                final_alloc_id = candidate_id
                if not final_alloc_id and verified_record and spec.id_field and verified_record.get(spec.id_field):
                    final_alloc_id = str(verified_record.get(spec.id_field)).strip()
                tabs_to_clear = set(requested_inv) | set(spec.allowed_invalidate_tabs) | {spec.target_tab}
                for tab in tabs_to_clear:
                    db.invalidate_tab_cache(tab)
                tx_coordinator.transition_governed_transaction(
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.COMMITTED.value,
                    bridge_status="CONFIRMED",
                    failure_category=None,
                    error_code=None,
                    allocated_id=final_alloc_id,
                    message="Recovered confirmed transaction from authoritative Google Sheets state without duplicate write.",
                    recovery_decision="AUTO_CONFIRMED_FROM_SHEETS",
                    result_snapshot=verified_record if isinstance(verified_record, dict) else None,
                    step_event={"step": "RECOVERY_AUTO_CONFIRMED", "allocated_id": final_alloc_id},
                    clear_lease=True,
                )
                audit_ok = self._record_tx_audit(
                    actor_user_id=actor_user_id,
                    action=spec.action,
                    target_tab=spec.target_tab,
                    entity_id=str(final_alloc_id or clean_nonce),
                    transaction_id=tx_id,
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.COMMITTED.value,
                    attempt_number=attempt_no,
                    reason="Recovery verified existing complete commit in Google Sheets; prevented duplicate write.",
                    metadata={"recovery_decision": "AUTO_CONFIRMED_FROM_SHEETS"},
                )
                return BridgeResult(
                    status="CONFIRMED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    allocated_id=final_alloc_id,
                    record=verified_record if isinstance(verified_record, dict) else None,
                    message="Transaction was already committed in Google Sheets (recovered cleanly without duplicate write).",
                    retryable=False,
                    http_status=200,
                    payload_hash=payload_hash,
                    transaction_id=tx_id,
                    transaction_state=TransactionState.COMMITTED.value,
                    attempt_number=attempt_no,
                    is_replay=True,
                    audit_logged=audit_ok,
                    recovery_decision="AUTO_CONFIRMED_FROM_SHEETS",
                )
            except _PartialSideEffectFailure as partial_exc:
                tx_coordinator.transition_governed_transaction(
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
                    bridge_status="RECOVERY_REQUIRED",
                    failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                    error_code="PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED",
                    allocated_id=candidate_id,
                    message=str(partial_exc),
                    recovery_decision="QUARANTINED_PARTIAL_SIDE_EFFECT",
                    step_event={"step": "RECOVERY_QUARANTINED_PARTIAL", "detail": str(partial_exc)[:240]},
                    clear_lease=True,
                )
                audit_ok = self._record_tx_audit(
                    actor_user_id=actor_user_id,
                    action=spec.action,
                    target_tab=spec.target_tab,
                    entity_id=str(candidate_id or clean_nonce),
                    transaction_id=tx_id,
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
                    failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                    error_code="PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED",
                    attempt_number=attempt_no,
                    reason=str(partial_exc),
                )
                return BridgeResult(
                    status="RECOVERY_REQUIRED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    allocated_id=candidate_id,
                    error_code="PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED",
                    message=(
                        f"Recovery required: partial or inconsistent side effects detected in Google Sheets ({partial_exc}). "
                        "Automatic retry is blocked to prevent duplicate corruption; Owner reconciliation is required."
                    ),
                    retryable=False,
                    http_status=409,
                    payload_hash=payload_hash,
                    transaction_id=tx_id,
                    transaction_state=TransactionState.RECOVERY_REQUIRED.value,
                    failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                    attempt_number=attempt_no,
                    audit_logged=audit_ok,
                    recovery_decision="QUARANTINED_PARTIAL_SIDE_EFFECT",
                )
            except _ReadBackFailure as rb_exc:
                # If IdAllocations or AuditLog already recorded this nonce, but target row is absent,
                # that is an orphan allocation / partial write -> MUST quarantine, NOT blindly retry!
                if alloc_match or audit_match:
                    quarantine_msg = (
                        f"Orphan allocation/audit record detected for nonce '{clean_nonce}' "
                        f"(allocated_id={candidate_id}), but target state verification failed: {rb_exc}"
                    )
                    tx_coordinator.transition_governed_transaction(
                        nonce=clean_nonce,
                        lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
                        bridge_status="RECOVERY_REQUIRED",
                        failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                        error_code="ORPHAN_ALLOCATION_RECOVERY_REQUIRED",
                        allocated_id=candidate_id,
                        message=quarantine_msg,
                        recovery_decision="QUARANTINED_ORPHAN_ALLOCATION",
                        step_event={"step": "RECOVERY_QUARANTINED_ORPHAN", "detail": str(rb_exc)[:240]},
                        clear_lease=True,
                    )
                    audit_ok = self._record_tx_audit(
                        actor_user_id=actor_user_id,
                        action=spec.action,
                        target_tab=spec.target_tab,
                        entity_id=str(candidate_id or clean_nonce),
                        transaction_id=tx_id,
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
                        failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                        error_code="ORPHAN_ALLOCATION_RECOVERY_REQUIRED",
                        attempt_number=attempt_no,
                        reason=quarantine_msg,
                    )
                    return BridgeResult(
                        status="RECOVERY_REQUIRED",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        allocated_id=candidate_id,
                        error_code="ORPHAN_ALLOCATION_RECOVERY_REQUIRED",
                        message=(
                            f"Recovery required: {quarantine_msg}. Automatic retry is blocked; "
                            "Owner must inspect and reconcile this transaction."
                        ),
                        retryable=False,
                        http_status=409,
                        payload_hash=payload_hash,
                        transaction_id=tx_id,
                        transaction_state=TransactionState.RECOVERY_REQUIRED.value,
                        failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                        attempt_number=attempt_no,
                        audit_logged=audit_ok,
                        recovery_decision="QUARANTINED_ORPHAN_ALLOCATION",
                    )
                # Transient read failure vs genuinely absent candidate_id
                if "Transient read-back error" in str(rb_exc):
                    return BridgeResult(
                        status="PENDING_UNKNOWN",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        allocated_id=candidate_id,
                        error_code="RECOVERY_STORAGE_UNAVAILABLE",
                        message=f"Outcome still unknown: target table read failed during recovery ({rb_exc}).",
                        retryable=True,
                        http_status=504,
                        payload_hash=payload_hash,
                        transaction_id=tx_id,
                        transaction_state=TransactionState.UNKNOWN.value,
                        failure_category=FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                        attempt_number=attempt_no,
                        recovery_decision="DEFER_STORAGE_UNAVAILABLE",
                    )

        # If previously explicitly quarantined as RECOVERY_REQUIRED with no verified recovery, keep blocked
        if str(existing_tx.get("lifecycle_state") or "").upper() == TransactionState.RECOVERY_REQUIRED.value:
            return BridgeResult(
                status="RECOVERY_REQUIRED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=existing_tx.get("allocated_id"),
                error_code=str(existing_tx.get("error_code") or "RECOVERY_REQUIRED"),
                message=(
                    "Transaction is quarantined in RECOVERY_REQUIRED state. "
                    "Automatic retry is blocked until Owner reconciliation completes."
                ),
                retryable=False,
                http_status=409,
                payload_hash=payload_hash,
                transaction_id=tx_id,
                transaction_state=TransactionState.RECOVERY_REQUIRED.value,
                failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                attempt_number=attempt_no,
                recovery_decision="QUARANTINED_AWAITING_OPERATOR",
            )

        # Authoritative Sheets confirmed healthy & ZERO side effects found -> safe to transition to PENDING and retry
        tx_coordinator.transition_governed_transaction(
            nonce=clean_nonce,
            lifecycle_state=TransactionState.PENDING.value,
            bridge_status="PENDING_UNKNOWN",
            failure_category=None,
            error_code=None,
            message="Recovery inspection confirmed zero side effects in Google Sheets; safe to retry with same nonce.",
            recovery_decision="CONFIRMED_ABSENT_SAFE_TO_RETRY",
            step_event={"step": "RECOVERY_CONFIRMED_ABSENT_RETRY_ALLOWED"},
            clear_lease=True,
        )
        return None

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
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.VALIDATION_ERROR.value,
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
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.AUTHORIZATION_ERROR.value,
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
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.AUTHORIZATION_ERROR.value,
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
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.VALIDATION_ERROR.value,
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
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.VALIDATION_ERROR.value,
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
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.VALIDATION_ERROR.value,
            )

        # Fail-closed schema write gate across the FULL authoritative union of tabs
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
                    transaction_state=TransactionState.FAILED.value,
                    failure_category=FailureCategory.DEPENDENCY_UNAVAILABLE.value,
                )

        payload_hash = self.compute_payload_hash(
            action=clean_action,
            target_tab=clean_tab,
            nonce=clean_nonce,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload=payload,
        )

        # Fast-path idempotency / conflict / recovery inspection BEFORE preflight duplicate-ID check
        # so replays of already-committed writes (even with client-supplied IDs) return clean replays
        # and conflicting nonces reject immediately with HTTP 409 IDEMPOTENCY_CONFLICT.
        prior_tx = tx_coordinator.get_governed_transaction(clean_nonce)
        if prior_tx is not None:
            prior_action = str(prior_tx.get("action") or "").strip().upper()
            prior_tab = str(prior_tx.get("target_tab") or "").strip()
            prior_hash = str(prior_tx.get("payload_hash") or "").strip()
            prior_state = str(prior_tx.get("lifecycle_state") or "").strip().upper()
            if prior_action != clean_action or prior_tab != clean_tab:
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code="IDEMPOTENCY_ACTION_CONFLICT",
                    message=(
                        f"Idempotency conflict: nonce '{clean_nonce}' was already used for "
                        f"action '{prior_action}' on '{prior_tab}', not '{clean_action}' on '{clean_tab}'."
                    ),
                    retryable=False,
                    http_status=409,
                    payload_hash=payload_hash,
                    transaction_id=prior_tx.get("transaction_id"),
                    transaction_state=TransactionState.FAILED.value,
                    failure_category=FailureCategory.IDEMPOTENCY_CONFLICT.value,
                )
            if prior_hash != payload_hash and (
                prior_state != TransactionState.FAILED.value
                or bool(prior_tx.get("allocated_id"))
            ):
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code="IDEMPOTENCY_PAYLOAD_CONFLICT",
                    message=(
                        f"Idempotency conflict: nonce '{clean_nonce}' was already used for '{clean_action}' "
                        "with a different request payload. Generate a new nonce for a different mutation."
                    ),
                    retryable=False,
                    http_status=409,
                    payload_hash=payload_hash,
                    transaction_id=prior_tx.get("transaction_id"),
                    transaction_state=TransactionState.FAILED.value,
                    failure_category=FailureCategory.IDEMPOTENCY_CONFLICT.value,
                )
            if prior_state in {TransactionState.COMMITTED.value, TransactionState.RECONCILED.value}:
                return self._build_replay_confirmed_result(
                    existing_tx=prior_tx,
                    corr_id=corr_id,
                    clean_nonce=clean_nonce,
                    payload_hash=payload_hash,
                    actor_user_id=actor_user_id,
                    clean_action=clean_action,
                    clean_tab=clean_tab,
                )
            if prior_state in {TransactionState.UNKNOWN.value, TransactionState.RECOVERY_REQUIRED.value}:
                recovery_res = self.recover_transaction(
                    nonce=clean_nonce,
                    spec=spec,
                    payload=payload,
                    corr_id=corr_id,
                    payload_hash=payload_hash,
                    actor_user_id=actor_user_id,
                    actor_role=actor_role,
                    existing_tx=prior_tx,
                    requested_inv=requested_inv,
                )
                if recovery_res is not None:
                    return recovery_res

        # Pre-write identifier, prefix, child-row, and cross-table collision validation (P1.5-002 / P1.5-007 / Phase 1.8)
        preflight_id_err, reserved_inflight_keys = self._preflight_validate_payload_ids(
            spec=spec,
            payload=payload,
            corr_id=corr_id,
            clean_nonce=clean_nonce,
            payload_hash=payload_hash,
        )
        if preflight_id_err is not None:
            preflight_id_err.transaction_state = TransactionState.FAILED.value
            preflight_id_err.failure_category = map_http_status_to_failure_category(
                preflight_id_err.http_status,
                preflight_id_err.error_code or "",
            ).value
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
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.DEPENDENCY_UNAVAILABLE.value,
            )

        # Atomic host-local cross-process transaction intent acquisition & duplicate/conflict gate
        gate_status, tx_rec = tx_coordinator.begin_governed_transaction(
            nonce=clean_nonce,
            action=clean_action,
            target_tab=clean_tab,
            actor_user_id=actor_user_id,
            payload_hash=payload_hash,
            correlation_id=corr_id,
        )

        if gate_status == "RECOVERY_CHECK_REQUIRED":
            recovery_res = self.recover_transaction(
                nonce=clean_nonce,
                spec=spec,
                payload=payload,
                corr_id=corr_id,
                payload_hash=payload_hash,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                existing_tx=tx_rec,
                requested_inv=requested_inv,
            )
            if recovery_res is not None:
                return recovery_res
            # Recovery verified zero effects in Sheets and moved state to PENDING -> acquire retry slot
            gate_status, tx_rec = tx_coordinator.begin_governed_transaction(
                nonce=clean_nonce,
                action=clean_action,
                target_tab=clean_tab,
                actor_user_id=actor_user_id,
                payload_hash=payload_hash,
                correlation_id=corr_id,
            )

        if gate_status == "ACTION_CONFLICT":
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="IDEMPOTENCY_ACTION_CONFLICT",
                message=(
                    f"Idempotency conflict: nonce '{clean_nonce}' is already bound to action "
                    f"'{tx_rec.get('action')}' on '{tx_rec.get('target_tab')}'."
                ),
                retryable=False,
                http_status=409,
                payload_hash=payload_hash,
                transaction_id=tx_rec.get("transaction_id"),
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.IDEMPOTENCY_CONFLICT.value,
            )

        if gate_status == "PAYLOAD_CONFLICT":
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="IDEMPOTENCY_PAYLOAD_CONFLICT",
                message=(
                    f"Idempotency conflict: nonce '{clean_nonce}' is already bound to '{clean_action}' "
                    "with a different request payload."
                ),
                retryable=False,
                http_status=409,
                payload_hash=payload_hash,
                transaction_id=tx_rec.get("transaction_id"),
                transaction_state=TransactionState.FAILED.value,
                failure_category=FailureCategory.IDEMPOTENCY_CONFLICT.value,
            )

        if gate_status == "ALREADY_COMMITTED":
            return self._build_replay_confirmed_result(
                existing_tx=tx_rec,
                corr_id=corr_id,
                clean_nonce=clean_nonce,
                payload_hash=payload_hash,
                actor_user_id=actor_user_id,
                clean_action=clean_action,
                clean_tab=clean_tab,
            )

        if gate_status == "IN_PROGRESS":
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="CONCURRENT_DUPLICATE_REQUEST",
                message=(
                    f"Transaction with nonce '{clean_nonce}' is already executing. "
                    "Duplicate concurrent submission blocked; check status before retrying."
                ),
                retryable=True,
                http_status=409,
                payload_hash=payload_hash,
                transaction_id=tx_rec.get("transaction_id"),
                transaction_state=TransactionState.PENDING.value,
                failure_category=FailureCategory.DUPLICATE_REQUEST.value,
                attempt_number=int(tx_rec.get("attempt_count") or 1),
            )

        tx_id = str(tx_rec.get("transaction_id") or "")
        attempt_no = int(tx_rec.get("attempt_count") or 1)

        envelope = {
            "action": clean_action,
            "target_tab": clean_tab,
            "nonce": clean_nonce,
            "correlation_id": corr_id,
            "transaction_id": tx_id,
            "attempt_number": attempt_no,
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
                "X-KS-Transaction-Id": tx_id,
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
                err_code = f"APPS_SCRIPT_REDIRECT_BLOCKED_{code}"
                msg = f"Apps Script endpoint attempted HTTP {code} redirect; blocked for HMAC envelope safety."
                tx_coordinator.transition_governed_transaction(
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.FAILED.value,
                    bridge_status="REJECTED",
                    failure_category=FailureCategory.WRITE_REJECTED.value,
                    error_code=err_code,
                    message=msg,
                )
                audit_ok = self._record_tx_audit(
                    actor_user_id=actor_user_id,
                    action=clean_action,
                    target_tab=clean_tab,
                    entity_id=clean_nonce,
                    transaction_id=tx_id,
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.FAILED.value,
                    failure_category=FailureCategory.WRITE_REJECTED.value,
                    error_code=err_code,
                    attempt_number=attempt_no,
                    reason=msg,
                )
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code=err_code,
                    message=msg,
                    retryable=False,
                    http_status=502,
                    payload_hash=payload_hash,
                    transaction_id=tx_id,
                    transaction_state=TransactionState.FAILED.value,
                    failure_category=FailureCategory.WRITE_REJECTED.value,
                    attempt_number=attempt_no,
                    audit_logged=audit_ok,
                )
            if 400 <= code < 500:
                err_code = f"APPS_SCRIPT_HTTP_{code}"
                fail_cat = map_http_status_to_failure_category(code, err_code).value
                msg = f"Apps Script rejected request '{clean_action}' (HTTP {code}). Form data was NOT SAVED."
                tx_coordinator.transition_governed_transaction(
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.FAILED.value,
                    bridge_status="REJECTED",
                    failure_category=fail_cat,
                    error_code=err_code,
                    message=msg,
                )
                audit_ok = self._record_tx_audit(
                    actor_user_id=actor_user_id,
                    action=clean_action,
                    target_tab=clean_tab,
                    entity_id=clean_nonce,
                    transaction_id=tx_id,
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    lifecycle_state=TransactionState.FAILED.value,
                    failure_category=fail_cat,
                    error_code=err_code,
                    attempt_number=attempt_no,
                    reason=msg,
                )
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code=err_code,
                    message=msg,
                    retryable=False,
                    http_status=code,
                    payload_hash=payload_hash,
                    transaction_id=tx_id,
                    transaction_state=TransactionState.FAILED.value,
                    failure_category=fail_cat,
                    attempt_number=attempt_no,
                    audit_logged=audit_ok,
                )
            logger.warning("Ambiguous Apps Script HTTP %s for action=%s corr=%s", code, clean_action, corr_id)
            msg = "Status not confirmed; do not submit a new transaction. Check transaction status before retrying with the same nonce."
            tx_coordinator.transition_governed_transaction(
                nonce=clean_nonce,
                lifecycle_state=TransactionState.UNKNOWN.value,
                bridge_status="PENDING_UNKNOWN",
                failure_category=FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                error_code="APPS_SCRIPT_UNKNOWN_OUTCOME",
                message=msg,
            )
            audit_ok = self._record_tx_audit(
                actor_user_id=actor_user_id,
                action=clean_action,
                target_tab=clean_tab,
                entity_id=clean_nonce,
                transaction_id=tx_id,
                correlation_id=corr_id,
                nonce=clean_nonce,
                lifecycle_state=TransactionState.UNKNOWN.value,
                failure_category=FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                error_code="APPS_SCRIPT_UNKNOWN_OUTCOME",
                attempt_number=attempt_no,
                reason=f"Ambiguous gateway HTTP {code}",
            )
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="APPS_SCRIPT_UNKNOWN_OUTCOME",
                message=msg,
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
                transaction_id=tx_id,
                transaction_state=TransactionState.UNKNOWN.value,
                failure_category=FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                attempt_number=attempt_no,
                audit_logged=audit_ok,
            )
        except Exception as exc:
            tx_state, fail_cat, err_code, http_status, user_msg = classify_gateway_exception(exc)
            bridge_st = "REJECTED" if tx_state == TransactionState.FAILED else "PENDING_UNKNOWN"
            logger.warning(
                "Gateway exception calling Apps Script action=%s corr=%s state=%s code=%s: %s",
                clean_action,
                corr_id,
                tx_state.value,
                err_code,
                exc,
            )
            tx_coordinator.transition_governed_transaction(
                nonce=clean_nonce,
                lifecycle_state=tx_state.value,
                bridge_status=bridge_st,
                failure_category=fail_cat.value,
                error_code=err_code,
                message=user_msg,
            )
            audit_ok = self._record_tx_audit(
                actor_user_id=actor_user_id,
                action=clean_action,
                target_tab=clean_tab,
                entity_id=clean_nonce,
                transaction_id=tx_id,
                correlation_id=corr_id,
                nonce=clean_nonce,
                lifecycle_state=tx_state.value,
                failure_category=fail_cat.value,
                error_code=err_code,
                attempt_number=attempt_no,
                reason=f"Gateway exception ({type(exc).__name__})",
            )
            return BridgeResult(
                status=bridge_st,
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code=err_code,
                message=user_msg,
                retryable=True,
                http_status=http_status,
                payload_hash=payload_hash,
                transaction_id=tx_id,
                transaction_state=tx_state.value,
                failure_category=fail_cat.value,
                attempt_number=attempt_no,
                audit_logged=audit_ok,
            )

        def _transition_unknown(err_code: str, msg: str, alloc_id: Optional[str] = None, fail_cat: FailureCategory = FailureCategory.WRITE_OUTCOME_UNKNOWN) -> BridgeResult:
            tx_coordinator.transition_governed_transaction(
                nonce=clean_nonce,
                lifecycle_state=TransactionState.UNKNOWN.value,
                bridge_status="PENDING_UNKNOWN",
                failure_category=fail_cat.value,
                error_code=err_code,
                allocated_id=alloc_id,
                message=msg,
            )
            audit_ok = self._record_tx_audit(
                actor_user_id=actor_user_id,
                action=clean_action,
                target_tab=clean_tab,
                entity_id=str(alloc_id or clean_nonce),
                transaction_id=tx_id,
                correlation_id=corr_id,
                nonce=clean_nonce,
                lifecycle_state=TransactionState.UNKNOWN.value,
                failure_category=fail_cat.value,
                error_code=err_code,
                attempt_number=attempt_no,
                reason=msg,
            )
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=alloc_id,
                error_code=err_code,
                message=msg,
                retryable=True,
                http_status=504,
                payload_hash=payload_hash,
                transaction_id=tx_id,
                transaction_state=TransactionState.UNKNOWN.value,
                failure_category=fail_cat.value,
                attempt_number=attempt_no,
                audit_logged=audit_ok,
            )

        def _transition_rejected(err_code: str, msg: str, http_code: int, retryable: bool = False) -> BridgeResult:
            fail_cat = map_http_status_to_failure_category(http_code, err_code).value
            tx_coordinator.transition_governed_transaction(
                nonce=clean_nonce,
                lifecycle_state=TransactionState.FAILED.value,
                bridge_status="REJECTED",
                failure_category=fail_cat,
                error_code=err_code,
                message=msg,
            )
            audit_ok = self._record_tx_audit(
                actor_user_id=actor_user_id,
                action=clean_action,
                target_tab=clean_tab,
                entity_id=clean_nonce,
                transaction_id=tx_id,
                correlation_id=corr_id,
                nonce=clean_nonce,
                lifecycle_state=TransactionState.FAILED.value,
                failure_category=fail_cat,
                error_code=err_code,
                attempt_number=attempt_no,
                reason=msg,
            )
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code=err_code,
                message=msg,
                retryable=retryable,
                http_status=http_code,
                payload_hash=payload_hash,
                transaction_id=tx_id,
                transaction_state=TransactionState.FAILED.value,
                failure_category=fail_cat,
                attempt_number=attempt_no,
                audit_logged=audit_ok,
            )

        # Validate echoed correlation, nonce, action, and target_tab if returned
        echo_corr = str(data.get("correlation_id") or "").strip()
        if echo_corr and echo_corr != corr_id:
            return _transition_unknown(
                "RESPONSE_CORRELATION_MISMATCH",
                "Status not confirmed; Apps Script response correlation_id did not match request.",
            )

        echo_nonce = str(data.get("nonce") or data.get("idempotency_key") or "").strip()
        if echo_nonce and echo_nonce != clean_nonce:
            return _transition_unknown(
                "RESPONSE_NONCE_MISMATCH",
                "Status not confirmed; Apps Script response nonce did not match request.",
            )

        echo_action = str(data.get("action") or "").strip().upper()
        if echo_action and echo_action != clean_action:
            return _transition_rejected(
                "RESPONSE_ACTION_MISMATCH",
                f"Apps Script response action '{echo_action}' did not match '{clean_action}'.",
                502,
            )

        echo_tab = str(data.get("target_tab") or "").strip()
        if echo_tab and echo_tab != clean_tab:
            return _transition_rejected(
                "RESPONSE_TABLE_MISMATCH",
                f"Apps Script response target_tab '{echo_tab}' did not match '{clean_tab}'.",
                502,
            )

        outcome = str(data.get("status", "")).strip().upper()
        if outcome == "REJECTED":
            return _transition_rejected(
                str(data.get("error_code") or "APPS_SCRIPT_REJECTED"),
                str(data.get("message") or "Apps Script did not confirm write. NOT SAVED."),
                int(data.get("http_status") or 422),
                retryable=bool(data.get("retryable", False)),
            )
        if outcome != "CONFIRMED":
            return _transition_unknown(
                str(data.get("error_code") or "APPS_SCRIPT_UNCONFIRMED_STATUS"),
                "Status not confirmed; do not submit a new transaction. Check transaction status before retrying with the same nonce.",
            )

        # Mandatory fail-closed echo presence check for all CONFIRMED responses
        if not echo_corr:
            return _transition_unknown(
                "MISSING_RESPONSE_CORRELATION",
                "Status not confirmed; Apps Script CONFIRMED response omitted correlation_id.",
            )
        if not echo_nonce:
            return _transition_unknown(
                "MISSING_RESPONSE_NONCE",
                "Status not confirmed; Apps Script CONFIRMED response omitted nonce.",
            )
        if not echo_action:
            return _transition_unknown(
                "MISSING_RESPONSE_ACTION",
                "Status not confirmed; Apps Script CONFIRMED response omitted action.",
            )
        if not echo_tab:
            return _transition_unknown(
                "MISSING_RESPONSE_TABLE",
                "Status not confirmed; Apps Script CONFIRMED response omitted target_tab.",
            )

        record_obj = data.get("record")
        if record_obj is not None and not isinstance(record_obj, dict):
            record_obj = None
        record: Optional[Dict[str, Any]] = record_obj

        raw_alloc = data.get("allocated_id") or (record.get(spec.id_field) if (record and spec.id_field) else None)
        allocated_id = str(raw_alloc).strip() if raw_alloc is not None and str(raw_alloc).strip() else None

        if spec.requires_allocated_id and not allocated_id:
            return _transition_unknown(
                "MISSING_ALLOCATED_ID",
                "Status not confirmed; Apps Script omitted allocated_id for creation write.",
                fail_cat=FailureCategory.VERIFICATION_FAILED,
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
            return _transition_unknown(
                "INVALID_ALLOCATED_ID_FORMAT",
                (
                    f"Status not confirmed; allocated_id '{allocated_id}' failed prefix validation for "
                    f"'{spec.target_tab}' (allowed: {allowed_desc})."
                ),
                alloc_id=allocated_id,
                fail_cat=FailureCategory.VERIFICATION_FAILED,
            )

        # Defense-in-depth post-write validation for SalaryReceipts child-row IDs (P1.5-002)
        if any(c.tab == "SalaryReceipts" for c in spec.readback.child_checks) or "SalaryReceipts" in spec.allowed_invalidate_tabs:
            child_receipt_id = str(
                data.get("receipt_id")
                or (record.get("receipt_id") if isinstance(record, dict) else "")
                or ""
            ).strip()
            if child_receipt_id and not validate_table_id_prefix("SalaryReceipts", child_receipt_id, for_new_allocation=True):
                return _transition_unknown(
                    "INVALID_CHILD_ALLOCATED_ID_FORMAT",
                    (
                        f"Status not confirmed; child SalaryReceipts identifier '{child_receipt_id}' "
                        "violates table prefix/collision rules (RCPT is locked to Payments)."
                    ),
                    alloc_id=allocated_id,
                    fail_cat=FailureCategory.VERIFICATION_FAILED,
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
        except _PartialSideEffectFailure as partial_fail:
            logger.error("Partial/duplicate side effect on read-back action=%s corr=%s: %s", clean_action, corr_id, partial_fail)
            quarantine_msg = (
                f"Recovery required: partial or duplicate side effects detected after write ({partial_fail}). "
                "Do NOT retry blindly; Owner reconciliation is required."
            )
            tx_coordinator.transition_governed_transaction(
                nonce=clean_nonce,
                lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
                bridge_status="RECOVERY_REQUIRED",
                failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                error_code="PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED",
                allocated_id=allocated_id,
                message=quarantine_msg,
                recovery_decision="QUARANTINED_PARTIAL_READBACK",
                step_event={"step": "READBACK_PARTIAL_QUARANTINED", "detail": str(partial_fail)[:240]},
            )
            audit_ok = self._record_tx_audit(
                actor_user_id=actor_user_id,
                action=clean_action,
                target_tab=clean_tab,
                entity_id=str(allocated_id or clean_nonce),
                transaction_id=tx_id,
                correlation_id=corr_id,
                nonce=clean_nonce,
                lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
                failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                error_code="PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED",
                attempt_number=attempt_no,
                reason=str(partial_fail),
            )
            return BridgeResult(
                status="RECOVERY_REQUIRED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=allocated_id,
                error_code="PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED",
                message=quarantine_msg,
                retryable=False,
                http_status=409,
                payload_hash=payload_hash,
                transaction_id=tx_id,
                transaction_state=TransactionState.RECOVERY_REQUIRED.value,
                failure_category=FailureCategory.RECOVERY_REQUIRED.value,
                attempt_number=attempt_no,
                audit_logged=audit_ok,
                recovery_decision="QUARANTINED_PARTIAL_READBACK",
            )
        except _ReadBackFailure as rb_fail:
            logger.warning("Read-back unconfirmed for action=%s corr=%s: %s", clean_action, corr_id, rb_fail)
            return _transition_unknown(
                "READ_BACK_UNCONFIRMED",
                f"Status not confirmed; do not submit a new transaction. {rb_fail}",
                alloc_id=allocated_id,
                fail_cat=FailureCategory.VERIFICATION_FAILED,
            )
        except Exception as rb_exc:
            logger.warning("Read-back failed after Apps Script response corr=%s: %s", corr_id, rb_exc)
            return _transition_unknown(
                "READ_BACK_UNCONFIRMED",
                "Status not confirmed; do not submit a new transaction.",
                alloc_id=allocated_id,
                fail_cat=FailureCategory.VERIFICATION_FAILED,
            )

        # Immediate full-union allowlisted cache invalidation on confirmed write
        tabs_to_clear = set(requested_inv) | set(spec.allowed_invalidate_tabs) | {spec.target_tab}
        for tab in tabs_to_clear:
            db.invalidate_tab_cache(tab)

        confirm_msg = str(data.get("message") or "Write confirmed via Apps Script read-back.")
        tx_coordinator.transition_governed_transaction(
            nonce=clean_nonce,
            lifecycle_state=TransactionState.COMMITTED.value,
            bridge_status="CONFIRMED",
            failure_category=None,
            error_code=None,
            allocated_id=allocated_id,
            message=confirm_msg,
            result_snapshot=record if isinstance(record, dict) else None,
            step_event={"step": "COMMITTED_VERIFIED", "allocated_id": allocated_id},
            clear_lease=True,
        )
        audit_ok = self._record_tx_audit(
            actor_user_id=actor_user_id,
            action=clean_action,
            target_tab=clean_tab,
            entity_id=str(allocated_id or clean_nonce),
            transaction_id=tx_id,
            correlation_id=corr_id,
            nonce=clean_nonce,
            lifecycle_state=TransactionState.COMMITTED.value,
            attempt_number=attempt_no,
            reason=confirm_msg,
        )

        return BridgeResult(
            status="CONFIRMED",
            correlation_id=corr_id,
            nonce=clean_nonce,
            allocated_id=allocated_id,
            record=record if isinstance(record, dict) else None,
            message=confirm_msg,
            retryable=False,
            http_status=200,
            payload_hash=payload_hash,
            transaction_id=tx_id,
            transaction_state=TransactionState.COMMITTED.value,
            attempt_number=attempt_no,
            is_replay=False,
            audit_logged=audit_ok,
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
                "transaction_id": res.transaction_id,
                "transaction_state": res.transaction_state or TransactionState.COMMITTED.value,
                "correlation_id": res.correlation_id,
                "nonce": res.nonce,
                "payload_hash": res.payload_hash,
                "allocated_id": res.allocated_id,
                "record": res.record,
                "message": res.message,
                "attempt_number": res.attempt_number,
                "is_replay": res.is_replay,
                "audit_logged": res.audit_logged,
                "recovery_decision": res.recovery_decision,
            }
        raise HTTPException(
            status_code=res.http_status,
            detail={
                "status": res.status,
                "transaction_id": res.transaction_id,
                "transaction_state": res.transaction_state,
                "failure_category": res.failure_category,
                "error_code": res.error_code or "GOVERNED_WRITE_NOT_CONFIRMED",
                "dependency": res.dependency,
                "message": res.message,
                "correlation_id": res.correlation_id,
                "nonce": res.nonce,
                "payload_hash": res.payload_hash,
                "retryable": res.retryable,
                "allocated_id": res.allocated_id,
                "attempt_number": res.attempt_number,
                "recovery_decision": res.recovery_decision,
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
        Read-only, fail-closed transaction status inspection against:
        1. Local transaction coordinator state (`governed_transactions`),
        2. Authoritative Google Sheets `IdAllocations` (`fresh=True`),
        3. Authoritative Google Sheets `AuditLog` (`fresh=True`),
        4. Authoritative primary target tab when an allocation/target record is referenced.

        Never returns `safe_to_retry_same_nonce=True` when ANY authoritative status table fails
        to read, or when an orphan ID allocation / partial side effect / duplicate row is detected.
        Never mutates Google Sheets and redacts confidential table details for non-OWNER_ADMIN roles.
        """
        clean_nonce = str(nonce or "").strip()
        clean_corr = str(correlation_id or "").strip()
        if not clean_nonce:
            raise ValueError("Transaction nonce is required for status lookup.")

        checked_at = now_iso()
        local_tx = tx_coordinator.get_governed_transaction(clean_nonce)
        local_state = str((local_tx or {}).get("lifecycle_state") or "").strip().upper() or None
        tx_id = (local_tx or {}).get("transaction_id")
        recovery_decision = (local_tx or {}).get("recovery_decision")

        alloc_match: Optional[Dict[str, Any]] = None
        audit_match: Optional[Dict[str, Any]] = None
        alloc_error: Optional[str] = None
        audit_error: Optional[str] = None

        try:
            db.invalidate_tab_cache("IdAllocations")
            alloc_rows = db.get_records("IdAllocations", fresh=True)
            if not isinstance(alloc_rows, list):
                alloc_error = f"IdAllocations returned non-list ({type(alloc_rows).__name__})"
            else:
                alloc_match = next(
                    (r for r in alloc_rows if str(r.get("nonce", "")).strip() == clean_nonce),
                    None,
                )
        except Exception as exc:
            alloc_error = str(exc)

        try:
            db.invalidate_tab_cache("AuditLog")
            audit_rows = db.get_records("AuditLog", fresh=True)
            if not isinstance(audit_rows, list):
                audit_error = f"AuditLog returned non-list ({type(audit_rows).__name__})"
            else:
                alloc_id_hint = str((alloc_match or {}).get("allocated_id") or (local_tx or {}).get("allocated_id") or "").strip()
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

        # If reconciled explicitly by Owner, return RECONCILED immediately (read-only)
        if local_state == TransactionState.RECONCILED.value:
            tab_name = str((local_tx or {}).get("target_tab") or "").strip()
            allocated_id = str((local_tx or {}).get("allocated_id") or "").strip() or None
            is_conf = tab_name in CONFIDENTIAL_TABS_NO_CACHE or tab_name in SECURITY_NO_CACHE_TABS
            return {
                "status": "RECONCILED",
                "transaction_id": tx_id,
                "transaction_state": TransactionState.RECONCILED.value,
                "nonce": clean_nonce,
                "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                "allocated_id": "REDACTED_CONFIDENTIAL" if (is_conf and not actor_is_owner) else allocated_id,
                "tab_name": "REDACTED_CONFIDENTIAL" if (is_conf and not actor_is_owner) else (tab_name or None),
                "recorded_at": (local_tx or {}).get("updated_at"),
                "audit_entry": None,
                "safe_to_retry_same_nonce": False,
                "recovery_decision": recovery_decision or "RECONCILED_BY_OPERATOR",
                "checked_at": checked_at,
                "message": "Transaction has been reconciled by an administrator. Do NOT retry.",
            }

        # If quarantined locally in RECOVERY_REQUIRED, never mark safe to retry blindly
        if local_state == TransactionState.RECOVERY_REQUIRED.value:
            tab_name = str((local_tx or {}).get("target_tab") or (alloc_match or {}).get("tab_name") or "").strip()
            allocated_id = str((local_tx or {}).get("allocated_id") or (alloc_match or {}).get("allocated_id") or "").strip() or None
            is_conf = tab_name in CONFIDENTIAL_TABS_NO_CACHE or tab_name in SECURITY_NO_CACHE_TABS
            return {
                "status": "RECOVERY_REQUIRED",
                "transaction_id": tx_id,
                "transaction_state": TransactionState.RECOVERY_REQUIRED.value,
                "failure_category": FailureCategory.RECOVERY_REQUIRED.value,
                "nonce": clean_nonce,
                "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                "allocated_id": "REDACTED_CONFIDENTIAL" if (is_conf and not actor_is_owner) else allocated_id,
                "tab_name": "REDACTED_CONFIDENTIAL" if (is_conf and not actor_is_owner) else (tab_name or None),
                "recorded_at": (local_tx or {}).get("updated_at"),
                "audit_entry": None,
                "safe_to_retry_same_nonce": False,
                "recovery_decision": recovery_decision or "QUARANTINED_MANUAL_RECONCILIATION_REQUIRED",
                "checked_at": checked_at,
                "message": (
                    "Recovery required: partial, duplicate, or inconsistent side effects were detected for this transaction. "
                    "Do NOT retry blindly; Owner reconciliation is required."
                ),
            }

        if alloc_match or audit_match:
            tab_name = str(
                (alloc_match or {}).get("tab_name")
                or (audit_match or {}).get("entity_type")
                or (local_tx or {}).get("target_tab")
                or ""
            ).strip()
            allocated_id = str(
                (alloc_match or {}).get("allocated_id")
                or (audit_match or {}).get("entity_id")
                or (local_tx or {}).get("allocated_id")
                or ""
            ).strip() or None
            is_confidential_tab = tab_name in CONFIDENTIAL_TABS_NO_CACHE or tab_name in SECURITY_NO_CACHE_TABS

            # Verify primary row existence & uniqueness whenever an IdAllocations row points to a real business tab
            if alloc_match and tab_name and tab_name != "BillNumbers" and allocated_id:
                spec = get_governed_action_spec(str((local_tx or {}).get("action") or ""))
                candidate_id_fields: List[str] = []
                if spec and spec.id_field:
                    candidate_id_fields.append(spec.id_field)
                try:
                    db.invalidate_tab_cache(tab_name)
                    target_rows = db.get_records(tab_name, fresh=True)
                    if not isinstance(target_rows, list):
                        raise RuntimeError(f"Target tab '{tab_name}' returned non-list data.")
                    if candidate_id_fields:
                        matched_rows = [
                            r for r in target_rows
                            if any(str(r.get(f, "")).strip() == allocated_id for f in candidate_id_fields)
                        ]
                    else:
                        matched_rows = [
                            r for r in target_rows
                            if any(str(v).strip() == allocated_id for v in r.values())
                        ]
                    if len(matched_rows) == 0:
                        return {
                            "status": "RECOVERY_REQUIRED",
                            "transaction_id": tx_id,
                            "transaction_state": TransactionState.RECOVERY_REQUIRED.value,
                            "failure_category": FailureCategory.RECOVERY_REQUIRED.value,
                            "nonce": clean_nonce,
                            "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                            "allocated_id": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else allocated_id,
                            "tab_name": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else (tab_name or None),
                            "recorded_at": str((alloc_match or {}).get("created_at") or "").strip() or None,
                            "audit_entry": None,
                            "safe_to_retry_same_nonce": False,
                            "recovery_decision": "ORPHAN_ID_ALLOCATION_DETECTED",
                            "checked_at": checked_at,
                            "message": (
                                "Recovery required: ID allocation was recorded in IdAllocations, but the primary "
                                "business row is missing in Google Sheets. Do NOT retry blindly; Owner reconciliation is required."
                            ),
                        }
                    if len(matched_rows) > 1:
                        return {
                            "status": "RECOVERY_REQUIRED",
                            "transaction_id": tx_id,
                            "transaction_state": TransactionState.RECOVERY_REQUIRED.value,
                            "failure_category": FailureCategory.RECOVERY_REQUIRED.value,
                            "nonce": clean_nonce,
                            "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                            "allocated_id": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else allocated_id,
                            "tab_name": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else (tab_name or None),
                            "recorded_at": str((alloc_match or {}).get("created_at") or "").strip() or None,
                            "audit_entry": None,
                            "safe_to_retry_same_nonce": False,
                            "recovery_decision": "DUPLICATE_PRIMARY_ROWS_DETECTED",
                            "checked_at": checked_at,
                            "message": (
                                f"Recovery required: {len(matched_rows)} duplicate primary rows were found for "
                                "this transaction in Google Sheets. Do NOT retry; Owner reconciliation is required."
                            ),
                        }
                except Exception as target_exc:
                    logger.warning("Target verification failed during status check for nonce=%s tab=%s: %s", clean_nonce, tab_name, target_exc)
                    return {
                        "status": "UNKNOWN_STORAGE_UNAVAILABLE",
                        "transaction_id": tx_id,
                        "transaction_state": TransactionState.UNKNOWN.value,
                        "failure_category": FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                        "nonce": clean_nonce,
                        "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                        "allocated_id": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else allocated_id,
                        "tab_name": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else (tab_name or None),
                        "recorded_at": None,
                        "audit_entry": None,
                        "safe_to_retry_same_nonce": False,
                        "recovery_decision": "DEFER_TARGET_TABLE_UNAVAILABLE",
                        "checked_at": checked_at,
                        "message": (
                            "Outcome still unknown: ID allocation exists, but primary table verification could not "
                            "reach Google Sheets. Do NOT submit a duplicate; re-check status shortly."
                        ),
                    }

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
                "transaction_id": tx_id,
                "transaction_state": TransactionState.COMMITTED.value,
                "nonce": clean_nonce,
                "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                "allocated_id": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else allocated_id,
                "tab_name": "REDACTED_CONFIDENTIAL" if (is_confidential_tab and not actor_is_owner) else (tab_name or None),
                "recorded_at": str(
                    (alloc_match or {}).get("created_at")
                    or (audit_match or {}).get("event_datetime")
                    or ""
                ).strip() or None,
                "audit_entry": safe_audit,
                "safe_to_retry_same_nonce": False,
                "recovery_decision": "CONFIRMED_IN_AUTHORITATIVE_SHEETS",
                "checked_at": checked_at,
                "message": (
                    "Transaction was already recorded in Google Sheets. Do NOT submit a duplicate transaction; "
                    "refresh the view to see the saved record."
                ),
            }

        # FAIL-CLOSED: if EITHER IdAllocations OR AuditLog failed to read, NEVER claim safe_to_retry_same_nonce=True
        if alloc_error or audit_error:
            return {
                "status": "UNKNOWN_STORAGE_UNAVAILABLE",
                "transaction_id": tx_id,
                "transaction_state": TransactionState.UNKNOWN.value,
                "failure_category": FailureCategory.WRITE_OUTCOME_UNKNOWN.value,
                "nonce": clean_nonce,
                "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                "allocated_id": None,
                "tab_name": None,
                "recorded_at": None,
                "audit_entry": None,
                "safe_to_retry_same_nonce": False,
                "recovery_decision": "DEFER_STORAGE_UNAVAILABLE",
                "checked_at": checked_at,
                "message": (
                    "Outcome still unknown: one or more authoritative Google Sheets status tables "
                    "(IdAllocations/AuditLog) could not be read. Keep your form inputs and re-check status before retrying."
                ),
            }

        # If local transaction is actively executing with unexpired lease, block premature retry
        if local_tx and local_state in {TransactionState.EXECUTING.value, TransactionState.INITIATED.value, TransactionState.VALIDATING.value}:
            return {
                "status": "IN_PROGRESS",
                "transaction_id": tx_id,
                "transaction_state": local_state,
                "nonce": clean_nonce,
                "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
                "allocated_id": None,
                "tab_name": (local_tx or {}).get("target_tab"),
                "recorded_at": None,
                "audit_entry": None,
                "safe_to_retry_same_nonce": False,
                "recovery_decision": "WAIT_IN_FLIGHT",
                "checked_at": checked_at,
                "message": "Transaction is currently in progress. Wait briefly and check status again before retrying.",
            }

        return {
            "status": "NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE",
            "transaction_id": tx_id,
            "transaction_state": local_state or TransactionState.PENDING.value,
            "nonce": clean_nonce,
            "correlation_id": clean_corr or (local_tx or {}).get("correlation_id"),
            "allocated_id": None,
            "tab_name": None,
            "recorded_at": None,
            "audit_entry": None,
            "safe_to_retry_same_nonce": True,
            "recovery_decision": "CONFIRMED_ABSENT_SAFE_TO_RETRY",
            "checked_at": checked_at,
            "message": (
                "No committed entry was found for this nonce in IdAllocations or AuditLog. "
                "You may safely retry the submission using the SAME preserved nonce."
            ),
        }


class _ReadBackFailure(RuntimeError):
    """Internal fail-closed signal when Sheets read-back does not confirm the committed write."""


class _PartialSideEffectFailure(RuntimeError):
    """Internal signal when Sheets read-back detects duplicate primary rows or partial/inconsistent child writes."""


apps_script_bridge = AppsScriptBridge()
