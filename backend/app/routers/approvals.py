from datetime import datetime, timezone
import json
import logging
import secrets
import threading
from typing import List, Optional, Dict, Any, Tuple
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from app.models import ApprovalRequestModel, ApprovalDecisionRequest
from app.sheets import db
from app.auth import get_current_user
from app.permissions import is_owner, is_manager, require_owner, require_manager
from app.user_service import (
    execute_create_user,
    execute_update_user,
    execute_set_user_status,
    execute_reset_password,
)

logger = logging.getLogger("kawad_swad.approvals")

router = APIRouter(prefix="/api/approvals", tags=["Approvals"])

# Process-local serialization. The current Render release runs one Uvicorn worker.
# Production must remain single-instance until a distributed claim/CAS mechanism
# is implemented and verified for Google Sheets.
_APPROVAL_EXECUTION_LOCK = threading.Lock()

_SENSITIVE_APPROVAL_KEYS = {
    "address", "emergency_contact", "bank_details", "document_references",
    "document_reference", "identity_document", "account_number", "account_no",
    "bank_account", "ifsc", "ifsc_code", "aadhaar", "aadhaar_number",
    "pan", "pan_number", "passport_number", "date_of_birth", "dob",
    "password", "password_hash", "username", "mobile", "alternate_mobile",
    "personal_mobile", "phone", "phone_number", "email", "personal_email",
}


def _redact_approval_payload(payload_json: str) -> str:
    """Return safely redacted JSON for non-Owner approval-request views."""
    try:
        payload = json.loads(payload_json or "{}")
    except (TypeError, ValueError):
        return json.dumps({"redacted": True, "reason": "invalid_payload"})

    def redact(value):
        if isinstance(value, dict):
            return {
                key: ("[REDACTED]" if str(key).strip().lower() in _SENSITIVE_APPROVAL_KEYS else redact(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return json.dumps(redact(payload), ensure_ascii=False)


def create_approval_request(
    request_type: str,
    target_user_id: Optional[str],
    payload: dict,
    requested_by: str,
    requested_by_name: str,
) -> ApprovalRequestModel:
    """Helper to create a pending approval request in ApprovalRequests sheet."""
    req_id = db.generate_id("ApprovalRequests")
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "request_id": req_id,
        "request_type": request_type,
        "target_user_id": target_user_id or "",
        "requested_by": requested_by,
        "requested_by_name": requested_by_name,
        "requested_at": now_iso,
        "payload_json": json.dumps(payload),
        "status": "PENDING",
        "decided_by": "",
        "decided_at": "",
        "decision_notes": "",
        "execution_error": "",
        "executed_at": "",
    }
    if not db.append_record("ApprovalRequests", record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Failed to persist approval request to Google Sheets.")

    db.log_audit(
        actor=requested_by,
        action="SUBMIT_APPROVAL_REQUEST",
        entity_type="ApprovalRequests",
        entity_id=req_id,
        reason=f"PA submitted {request_type} request for target {target_user_id or 'NEW'}",
    )
    return ApprovalRequestModel(**record)


@router.get("/requests", response_model=List[ApprovalRequestModel])
async def list_approval_requests(current_user: dict = Depends(get_current_user)):
    require_manager(current_user)
    user_id = str(current_user.get("user_id") or "")
    records = db.get_records("ApprovalRequests", fresh=True)

    requests: List[ApprovalRequestModel] = []
    for r in records:
        req_by = str(r.get("requested_by") or "")
        # PA only sees their own requests; Owner sees all requests
        if not is_owner(current_user) and req_by != user_id:
            continue
        requests.append(ApprovalRequestModel(
            request_id=str(r.get("request_id") or ""),
            request_type=str(r.get("request_type") or ""),
            target_user_id=str(r.get("target_user_id") or ""),
            requested_by=req_by,
            requested_by_name=str(r.get("requested_by_name") or req_by),
            requested_at=str(r.get("requested_at") or ""),
            payload_json=(
                str(r.get("payload_json") or "{}")
                if is_owner(current_user)
                else _redact_approval_payload(str(r.get("payload_json") or "{}"))
            ),
            status=str(r.get("status") or "PENDING"),
            decided_by=str(r.get("decided_by") or ""),
            decided_at=str(r.get("decided_at") or ""),
            decision_notes=str(r.get("decision_notes") or ""),
            execution_error=(
                str(r.get("execution_error") or "")
                if is_owner(current_user)
                else ("Manual review required." if str(r.get("status") or "").upper() in {"EXECUTING", "EXECUTION_FAILED", "EXECUTION_REVIEW_REQUIRED"} else "")
            ),
            executed_at=str(r.get("executed_at") or ""),
        ))

    # Sort latest first
    requests.sort(key=lambda x: x.requested_at, reverse=True)
    return requests


def _run_request_execution(request_record: dict, actor_user_id: str, initial_password: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """Executes the approved action. Returns (result_dict, temporary_password_if_any). Raises Exception on failure."""
    req_type = str(request_record.get("request_type") or "")
    target_uid = str(request_record.get("target_user_id") or "")
    payload_str = str(request_record.get("payload_json") or "{}")
    payload = json.loads(payload_str)

    temp_pw = None
    if req_type == "CREATE_USER":
        if initial_password:
            payload["password"] = initial_password
        res = execute_create_user(payload, actor_user_id)
        temp_pw = res.get("temporary_password") or initial_password
        return res, temp_pw
    elif req_type == "UPDATE_USER":
        res = execute_update_user(target_uid, payload, actor_user_id)
        return res, None
    elif req_type == "DEACTIVATE_USER":
        res = execute_set_user_status(target_uid, False, actor_user_id, reason=payload.get("reason", "Approved deactivation"))
        return res, None
    elif req_type == "REACTIVATE_USER":
        res = execute_set_user_status(target_uid, True, actor_user_id, reason=payload.get("reason", "Approved reactivation"))
        return res, None
    elif req_type == "RESET_PASSWORD":
        new_pw = initial_password or f"Kawad@{secrets.token_hex(4)}"
        res = execute_reset_password(target_uid, new_pw, actor_user_id, reason="Owner approved password reset")
        return res, new_pw
    elif req_type == "PRODUCTION_BATCH":
        import asyncio
        from app.routers.production import approve_batch, ApprovalRequest as ProdApprovalReq
        prod_id = target_uid or payload.get("production_id") or payload.get("batch_id")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                res = pool.submit(
                    asyncio.run,
                    approve_batch(
                        prod_id,
                        ProdApprovalReq(approved=True, notes="Approved by Owner via Request"),
                        {"user_id": actor_user_id, "role": "OWNER"},
                    )
                ).result()
        else:
            res = asyncio.run(approve_batch(
                prod_id,
                ProdApprovalReq(approved=True, notes="Approved by Owner via Request"),
                {"user_id": actor_user_id, "role": "OWNER"},
            ))
        return res, None
    else:
        raise ValueError(f"Unknown request type: {req_type}")


@router.post("/requests/{request_id}/decision", response_model=ApprovalRequestModel)
async def decide_approval_request(
    request_id: str,
    decision_req: ApprovalDecisionRequest,
    current_user: dict = Depends(get_current_user),
):
    require_owner(current_user)
    owner_id = str(current_user.get("user_id") or "")
    now_iso = datetime.now(timezone.utc).isoformat()
    decision = decision_req.decision.strip().upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Decision must be APPROVED or REJECTED.")

    # Claim the request before any side effect. The lock serializes claims inside
    # this process; Google Sheets does not provide a cross-instance compare-and-swap.
    with _APPROVAL_EXECUTION_LOCK:
        records = db.get_records("ApprovalRequests", fresh=True)
        target = next((r for r in records if str(r.get("request_id") or "").strip() == request_id.strip()), None)
        if not target:
            raise HTTPException(status_code=404, detail="Approval request not found.")

        current_status = str(target.get("status") or "PENDING").upper()
        if current_status != "PENDING":
            if current_status in {"EXECUTING", "EXECUTION_FAILED", "EXECUTION_REVIEW_REQUIRED"}:
                raise HTTPException(
                    status_code=409,
                    detail="This request may have partially executed. Automatic retry is disabled; reconcile the target business record before taking further action.",
                )
            raise HTTPException(status_code=400, detail=f"Cannot decide request currently in status {current_status}.")

        if decision == "REJECTED":
            updates = {
                "status": "REJECTED",
                "decided_by": owner_id,
                "decided_at": now_iso,
                "decision_notes": decision_req.notes or "",
            }
            db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)
            # If it was a PRODUCTION_BATCH, also update ProductionBatches.
            if target.get("request_type") == "PRODUCTION_BATCH":
                target_batch_id = str(target.get("target_user_id") or "").strip()
                if target_batch_id:
                    batch_updates = {
                        "status": "REJECTED",
                        "approved_by": owner_id,
                        "approved_at": now_iso,
                        "approval_notes": decision_req.notes or "Rejected via Approval Request",
                    }
                    db.update_record("ProductionBatches", "production_id", target_batch_id, batch_updates)
                    db.update_record("ProductionBatches", "batch_id", target_batch_id, batch_updates)

            db.log_audit(owner_id, "REJECT_APPROVAL", "ApprovalRequests", request_id, reason=decision_req.notes or "Owner rejected request")
            updated_dict = dict(target)
            updated_dict.update(updates)
            return ApprovalRequestModel(**updated_dict)

        # Persist EXECUTING before performing any business write. If the process
        # stops mid-operation, the row remains blocked for manual reconciliation.
        updates = {
            "status": "EXECUTING",
            "decided_by": owner_id,
            "decided_at": now_iso,
            "decision_notes": decision_req.notes or "",
            "execution_error": "",
        }
        db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)

    # The request is now claimed. Never blindly repeat it if outcome is uncertain.
    temp_pw = None
    try:
        _, temp_pw = _run_request_execution(target, owner_id, decision_req.initial_password)
    except Exception:
        logger.exception("Execution failed or outcome is uncertain for approval request %s", request_id)
        review_updates = {
            "status": "EXECUTION_REVIEW_REQUIRED",
            "execution_error": "Execution outcome is uncertain. Manual reconciliation is required; automatic retry is disabled.",
        }
        # If this status update also fails, EXECUTING remains and is still blocked.
        db.update_record("ApprovalRequests", "request_id", request_id, review_updates, raise_on_error=True)
        db.log_audit(
            owner_id,
            "APPROVAL_REQUIRES_RECONCILIATION",
            "ApprovalRequests",
            request_id,
            reason="Execution failed or outcome uncertain; automatic retry disabled",
        )
        updated_dict = dict(target)
        updated_dict.update(updates)
        updated_dict.update(review_updates)
        return ApprovalRequestModel(**updated_dict)

    # A failure to persist EXECUTED leaves the request in EXECUTING, not retryable.
    completed_updates = {
        "status": "EXECUTED",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "execution_error": "",
    }
    db.update_record("ApprovalRequests", "request_id", request_id, completed_updates, raise_on_error=True)
    db.log_audit(owner_id, "APPROVE_AND_EXECUTE", "ApprovalRequests", request_id, reason=f"Executed {target.get('request_type')}")

    updated_dict = dict(target)
    updated_dict.update(updates)
    updated_dict.update(completed_updates)
    if temp_pw:
        # Transient one-time credential is returned only to the Owner who approved
        # this request; it is never persisted in ApprovalRequests or audit records.
        updated_dict["temporary_credentials"] = f"Temporary Password: {temp_pw}"
    return ApprovalRequestModel(**updated_dict)


@router.post("/requests/{request_id}/retry", response_model=ApprovalRequestModel)
async def retry_failed_execution(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    require_owner(current_user)
    records = db.get_records("ApprovalRequests", fresh=True)
    target = next((r for r in records if str(r.get("request_id") or "").strip() == request_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    raise HTTPException(
        status_code=409,
        detail="Automatic execution retry is disabled for safety. Verify whether the business action already occurred, reconcile the target record, and then resolve the request manually.",
    )


@router.post("/requests/{request_id}/cancel", response_model=ApprovalRequestModel)
async def cancel_approval_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    require_manager(current_user)
    user_id = str(current_user.get("user_id") or "")

    records = db.get_records("ApprovalRequests", fresh=True)
    target = next((r for r in records if str(r.get("request_id") or "").strip() == request_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Approval request not found.")

    req_by = str(target.get("requested_by") or "")
    if not is_owner(current_user) and req_by != user_id:
        raise HTTPException(status_code=403, detail="You can only cancel your own pending requests.")

    current_status = str(target.get("status") or "").upper()
    if current_status != "PENDING":
        raise HTTPException(status_code=400, detail="Only PENDING requests can be cancelled.")

    updates = {
        "status": "CANCELLED",
        "decision_notes": f"Cancelled by {user_id}",
    }
    db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)
    db.log_audit(user_id, "CANCEL_APPROVAL_REQUEST", "ApprovalRequests", request_id, reason="Requester cancelled pending request")

    updated_dict = dict(target)
    updated_dict.update(updates)
    return ApprovalRequestModel(**updated_dict)
