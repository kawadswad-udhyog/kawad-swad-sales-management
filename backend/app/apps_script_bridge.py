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

from decimal import Decimal
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    PENDING_OWNER_MAPPING_TABS,
    TAB_RECONCILIATION_CONFLICTS,
    is_forbidden_scratch_tab,
    is_valid_locked_id_prefix,
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


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value if value is not None else "").strip()
    if s.lower() in {"true", "false"}:
        return s.lower()
    return s


def _lookup_expected_value(payload: Dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload.get(key)
    for nested_key in ("sale", "order", "payroll_run", "payment", "user_updates", "auth_updates", "item_update"):
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
    def _validate_id_format(spec: GovernedActionSpec, allocated_id: str) -> bool:
        clean = str(allocated_id or "").strip().upper()
        if not clean:
            return False
        if not spec.locked_prefix:
            return True
        allowed = {spec.locked_prefix.upper()}
        # Transitional legacy ID prefixes allowed alongside locked v2 prefixes for pre-existing tables
        if spec.target_tab == "JournalHeaders":
            allowed.add("JRN")
        elif spec.target_tab == "Sales":
            allowed.add("SALE")
        elif spec.target_tab == "PackagingBatches":
            allowed.add("PKG")
        elif spec.target_tab == "ProductionBatches":
            allowed.add("PRB")
        elif spec.target_tab == "Customers":
            allowed.add("CUS")
        elif spec.target_tab == "RawMaterials":
            allowed.add("RWM")
        prefix = clean.split("-", 1)[0] if "-" in clean else ""
        if prefix in allowed and is_valid_locked_id_prefix(clean, expected_prefix=prefix):
            return True
        return is_valid_locked_id_prefix(clean, expected_prefix=spec.locked_prefix)

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

        if spec.id_field and lookup_id:
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
            matched = next(
                (
                    r for r in fresh_rows
                    if all(str(r.get(k, "")).strip() == v for k, v in criteria)
                ),
                None,
            )
            if matched is None:
                raise _ReadBackFailure(
                    f"Primary row matching {criteria} on '{spec.target_tab}' not found on read-back."
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
                items_val = payload.get(child_check.min_rows_payload_key)
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

        if clean_tab in PENDING_OWNER_MAPPING_TABS:
            conflict = next(
                (c for c in TAB_RECONCILIATION_CONFLICTS.values() if clean_tab in {c.get("snapshot_tab"), c.get("draft_tab")}),
                None,
            )
            error_code = conflict["status"] if conflict else "PENDING_OWNER_MAPPING"
            return BridgeResult(
                status="BLOCKED_PENDING_OWNER_SETUP",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code=error_code,
                dependency="OWNER_SCHEMA_MAPPING_DEPENDENCY",
                message=(
                    f"Governed write blocked for '{clean_tab}' ({error_code}): "
                    "Canonical Row-1 workbook headers have not been supplied or reconciled by Owner. Data was NOT SAVED."
                ),
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

        if allocated_id and spec.locked_prefix and not self._validate_id_format(spec, allocated_id):
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                allocated_id=allocated_id,
                error_code="INVALID_ALLOCATED_ID_FORMAT",
                message=f"Status not confirmed; allocated_id '{allocated_id}' failed prefix validation ({spec.locked_prefix}).",
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

        # Immediate allowlisted cache invalidation on confirmed write
        tabs_to_clear = set(requested_inv)
        tabs_to_clear.add(spec.target_tab)
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


class _ReadBackFailure(RuntimeError):
    """Internal fail-closed signal when Sheets read-back does not confirm the committed write."""


apps_script_bridge = AppsScriptBridge()
