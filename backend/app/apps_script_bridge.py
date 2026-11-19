"""
Kawad Swad ERP — Signed Apps Script Single-Write-Owner Bridge.

Architectural rules enforced here:
1. Apps Script is the single governed write/posting owner when SALES_APPS_SCRIPT_ENABLED=true
   and SALES_APPS_SCRIPT_WEBAPP_URL + SALES_APPS_SCRIPT_SHARED_SECRET are configured.
2. FastAPI validates requests, checks RBAC, signs payload + client `nonce` unchanged,
   forwards over HTTPS with finite timeouts, parses response state (`CONFIRMED`, `REJECTED`,
   `PENDING_UNKNOWN`, `BLOCKED_PENDING_OWNER_SETUP`), verifies read-back ID on confirmed writes,
   and invalidates affected read caches immediately upon confirmation.
3. Fail closed when Apps Script endpoint is unconfigured (`BLOCKED_PENDING_OWNER_SETUP` -> HTTP 503)
   or when an ambiguous timeout/network error occurs (`PENDING_UNKNOWN` -> retryable with SAME nonce).
4. Never log raw secrets, bank details, or personal identity numbers.
"""

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


class AppsScriptBridge:
    """Signed HTTPS bridge delegating ALL governed ERP writes to Apps Script (Single Write Owner)."""

    @staticmethod
    def extract_request_nonce(
        request: Optional[Request] = None,
        explicit_nonce: Optional[str] = None,
    ) -> str:
        """Preserve client-supplied nonce or X-Idempotency-Key unchanged."""
        if explicit_nonce and str(explicit_nonce).strip():
            return str(explicit_nonce).strip()
        if request is not None:
            hdr_nonce = (
                request.headers.get("X-KS-Idempotency-Key")
                or request.headers.get("X-Idempotency-Key")
                or ""
            ).strip()
            if hdr_nonce:
                return hdr_nonce
        return ""

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
        # Only permit non-TLS localhost during local development; production requires strict https://
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

        if is_forbidden_scratch_tab(target_tab):
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="SCRATCH_TAB_FORBIDDEN",
                message=f"Write rejected: legacy scratch tab '{target_tab}' is forbidden.",
                retryable=False,
                http_status=403,
            )

        if target_tab in PENDING_OWNER_MAPPING_TABS:
            conflict = next(
                (c for c in TAB_RECONCILIATION_CONFLICTS.values() if target_tab in {c.get("snapshot_tab"), c.get("draft_tab")}),
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
                    f"Governed write blocked for '{target_tab}' ({error_code}): "
                    "Canonical Row-1 workbook headers have not been supplied or reconciled by Owner. Data was NOT SAVED."
                ),
                retryable=False,
                http_status=503,
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
            )

        envelope = {
            "action": action,
            "target_tab": target_tab,
            "nonce": clean_nonce,
            "correlation_id": corr_id,
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
            },
        )
        opener = urllib.request.build_opener(_NoRedirectHandler)

        try:
            with opener.open(req, timeout=SALES_APPS_SCRIPT_TIMEOUT_SECONDS) as resp:
                raw_text = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw_text) if raw_text else {}
        except urllib.error.HTTPError as http_err:
            code = http_err.code
            if 300 <= code < 400:
                logger.warning("Blocked HTTP %s redirect from Apps Script bridge action=%s corr=%s", code, action, corr_id)
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code=f"APPS_SCRIPT_REDIRECT_BLOCKED_{code}",
                    message=f"Apps Script endpoint attempted HTTP {code} redirect; blocked for HMAC envelope safety.",
                    retryable=False,
                    http_status=502,
                )
            if 400 <= code < 500:
                return BridgeResult(
                    status="REJECTED",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    error_code=f"APPS_SCRIPT_HTTP_{code}",
                    message=f"Apps Script rejected request '{action}' (HTTP {code}). Form data was NOT SAVED.",
                    retryable=False,
                    http_status=code,
                )
            logger.warning("Ambiguous Apps Script HTTP %s for action=%s corr=%s", code, action, corr_id)
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="APPS_SCRIPT_UNKNOWN_OUTCOME",
                message="Status not confirmed; do not submit a new transaction. Retry safely with the same nonce.",
                retryable=True,
                http_status=504,
            )
        except Exception as exc:
            logger.warning("Network/timeout calling Apps Script for action=%s corr=%s: %s", action, corr_id, exc)
            return BridgeResult(
                status="PENDING_UNKNOWN",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code="APPS_SCRIPT_UNKNOWN_OUTCOME",
                message="Status not confirmed; do not submit a new transaction. Retry safely with the same nonce.",
                retryable=True,
                http_status=504,
            )

        outcome = str(data.get("status", "")).strip().upper()
        if outcome not in {"CONFIRMED", "OK", "SUCCESS"}:
            return BridgeResult(
                status="REJECTED",
                correlation_id=corr_id,
                nonce=clean_nonce,
                error_code=str(data.get("error_code") or "APPS_SCRIPT_REJECTED"),
                message=str(data.get("message") or "Apps Script did not confirm write. NOT SAVED."),
                retryable=bool(data.get("retryable", False)),
                http_status=int(data.get("http_status") or 422),
            )

        allocated_id = data.get("allocated_id") or (data.get("record") or {}).get(id_field or "")
        record = data.get("record")

        # Read-back verification when id_field + allocated_id are supplied and target_tab is readable
        if allocated_id and id_field:
            try:
                db.invalidate_tab_cache(target_tab)
                fresh_rows = db.get_records(target_tab, fresh=True)
                matched = next((r for r in fresh_rows if str(r.get(id_field, "")).strip() == str(allocated_id).strip()), None)
                if matched is not None:
                    record = matched
                else:
                    return BridgeResult(
                        status="PENDING_UNKNOWN",
                        correlation_id=corr_id,
                        nonce=clean_nonce,
                        allocated_id=str(allocated_id),
                        error_code="READ_BACK_UNCONFIRMED",
                        message="Status not confirmed; do not submit a new transaction. Read-back did not confirm record yet.",
                        retryable=True,
                        http_status=504,
                    )
            except Exception as rb_exc:
                logger.warning("Read-back failed after Apps Script response corr=%s: %s", corr_id, rb_exc)
                return BridgeResult(
                    status="PENDING_UNKNOWN",
                    correlation_id=corr_id,
                    nonce=clean_nonce,
                    allocated_id=str(allocated_id) if allocated_id else None,
                    error_code="READ_BACK_UNCONFIRMED",
                    message="Status not confirmed; do not submit a new transaction.",
                    retryable=True,
                    http_status=504,
                )

        # Immediate cache invalidation on confirmed write
        tabs_to_clear = set(invalidate_tabs or [])
        tabs_to_clear.add(target_tab)
        for tab in tabs_to_clear:
            db.invalidate_tab_cache(tab)

        return BridgeResult(
            status="CONFIRMED",
            correlation_id=corr_id,
            nonce=clean_nonce,
            allocated_id=str(allocated_id) if allocated_id else None,
            record=record if isinstance(record, dict) else None,
            message=str(data.get("message") or "Write confirmed via Apps Script read-back."),
            retryable=False,
            http_status=200,
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
        allow_generated_nonce: bool = True,
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
                "retryable": res.retryable,
                "allocated_id": res.allocated_id,
            },
        )


apps_script_bridge = AppsScriptBridge()
