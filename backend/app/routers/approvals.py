from datetime import datetime, timezone
import json
import logging
import secrets
import threading
from typing import List, Optional, Dict, Any, Tuple
from fastapi import APIRouter, HTTPException, Request, status, Depends
from pydantic import BaseModel

from app.apps_script_bridge import apps_script_bridge
from app.models import ApprovalRequestModel, ApprovalDecisionRequest
from app.sheets import db
from app.auth import get_current_user, hash_password
from app.permissions import is_owner, is_manager, require_owner, require_manager, role_v2_of

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
    nonce: str = "",
) -> ApprovalRequestModel:
    """Helper to submit a pending approval request in ApprovalRequests sheet via Apps Script."""
    now_iso_str = datetime.now(timezone.utc).isoformat()
    record = {
        "request_type": request_type,
        "target_user_id": target_user_id or "",
        "requested_by": requested_by,
        "requested_by_name": requested_by_name,
        "requested_at": now_iso_str,
        "payload_json": json.dumps(payload),
        "status": "PENDING",
        "decided_by": "",
        "decided_at": "",
        "decision_notes": "",
        "execution_error": "",
        "executed_at": "",
    }
    res = apps_script_bridge.delegate_governed_write(
        action="CREATE_APPROVAL_REQUEST",
        target_tab="ApprovalRequests",
        payload=record,
        nonce=nonce,
        actor_user_id=requested_by,
        actor_role="PA",
        id_field="request_id",
        invalidate_tabs=["ApprovalRequests"],
    )
    req_id = str(res.get("allocated_id") or "")
    db.log_audit(
        actor=requested_by,
        action="SUBMIT_APPROVAL_REQUEST",
        entity_type="ApprovalRequests",
        entity_id=req_id,
        reason=f"PA submitted {request_type} request for target {target_user_id or 'NEW'}",
    )
    return ApprovalRequestModel(request_id=req_id, **record)


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


def _build_approval_execution_payload(request_record: dict, initial_password: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """Prepare governed execution envelope for atomic execution inside Apps Script."""
    req_type = str(request_record.get("request_type") or "")
    target_uid = str(request_record.get("target_user_id") or "")
    payload = json.loads(str(request_record.get("payload_json") or "{}") or "{}")

    if req_type == "CREATE_USER":
        temp_pw = initial_password or f"Kawad@{secrets.token_hex(4)}"
        if len(temp_pw) < 8:
            raise HTTPException(status_code=422, detail="Initial password must be at least 8 characters.")
        return {
            "request_type": req_type,
            "target_user_id": target_uid,
            "user_payload": payload,
            "password_hash": hash_password(temp_pw),
            "must_change_password": "true" if not initial_password else "false",
        }, temp_pw
    if req_type in {"UPDATE_USER", "DEACTIVATE_USER", "REACTIVATE_USER", "PRODUCTION_BATCH"}:
        return {
            "request_type": req_type,
            "target_user_id": target_uid,
            "action_payload": payload,
        }, None
    if req_type == "RESET_PASSWORD":
        new_pw = initial_password or f"Kawad@{secrets.token_hex(4)}"
        if len(new_pw) < 8:
            raise HTTPException(status_code=422, detail="New password must be at least 8 characters.")
        return {
            "request_type": req_type,
            "target_user_id": target_uid,
            "password_hash": hash_password(new_pw),
            "must_change_password": "true",
        }, new_pw
    raise ValueError(f"Unknown request type: {req_type}")


@router.post("/requests/{request_id}/decision", response_model=ApprovalRequestModel)
async def decide_approval_request(
    request_id: str,
    decision_req: ApprovalDecisionRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    require_owner(current_user)
    owner_id = str(current_user.get("user_id") or "")
    now_iso_str = datetime.now(timezone.utc).isoformat()
    decision = decision_req.decision.strip().upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Decision must be APPROVED or REJECTED.")

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
                "request_id": request_id,
                "decision": "REJECTED",
                "request_type": target.get("request_type", ""),
                "target_user_id": str(target.get("target_user_id") or "").strip(),
                "status": "REJECTED",
                "decided_by": owner_id,
                "decided_at": now_iso_str,
                "decision_notes": decision_req.notes or "",
            }
            apps_script_bridge.delegate_governed_write(
                action="REJECT_APPROVAL_REQUEST",
                target_tab="ApprovalRequests",
                payload=updates,
                request=request,
                actor_user_id=owner_id,
                actor_role=role_v2_of(current_user),
                id_field="request_id",
                invalidate_tabs=["ApprovalRequests", "ProductionBatches"],
            )
            db.log_audit(owner_id, "REJECT_APPROVAL", "ApprovalRequests", request_id, reason=decision_req.notes or "Owner rejected request")
            updated_dict = dict(target)
            updated_dict.update(updates)
            return ApprovalRequestModel(**updated_dict)

        exec_payload, temp_pw = _build_approval_execution_payload(target, decision_req.initial_password)
        apps_script_bridge.delegate_governed_write(
            action="APPROVE_AND_EXECUTE_REQUEST",
            target_tab="ApprovalRequests",
            payload={
                "request_id": request_id,
                "decision": "APPROVED",
                "decided_by": owner_id,
                "decided_at": now_iso_str,
                "decision_notes": decision_req.notes or "",
                "execution": exec_payload,
            },
            request=request,
            actor_user_id=owner_id,
            actor_role=role_v2_of(current_user),
            id_field="request_id",
            invalidate_tabs=["ApprovalRequests", "Users", "AuthUsers", "ProductionBatches"],
        )

    db.log_audit(owner_id, "APPROVE_AND_EXECUTE", "ApprovalRequests", request_id, reason=f"Executed {target.get('request_type')}")
    updated_dict = dict(target)
    updated_dict.update({
        "status": "EXECUTED",
        "decided_by": owner_id,
        "decided_at": now_iso_str,
        "decision_notes": decision_req.notes or "",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "execution_error": "",
    })
    if temp_pw:
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
    request: Request,
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
        "request_id": request_id,
        "status": "CANCELLED",
        "decision_notes": f"Cancelled by {user_id}",
    }
    apps_script_bridge.delegate_governed_write(
        action="CANCEL_APPROVAL_REQUEST",
        target_tab="ApprovalRequests",
        payload=updates,
        request=request,
        actor_user_id=user_id,
        actor_role=role_v2_of(current_user),
        id_field="request_id",
        invalidate_tabs=["ApprovalRequests"],
    )
    db.log_audit(user_id, "CANCEL_APPROVAL_REQUEST", "ApprovalRequests", request_id, reason="Requester cancelled pending request")

    updated_dict = dict(target)
    updated_dict.update(updates)
    return ApprovalRequestModel(**updated_dict)
