from datetime import datetime, timezone
import json
import logging
from typing import List, Optional
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
            payload_json=str(r.get("payload_json") or "{}"),
            status=str(r.get("status") or "PENDING"),
            decided_by=str(r.get("decided_by") or ""),
            decided_at=str(r.get("decided_at") or ""),
            decision_notes=str(r.get("decision_notes") or ""),
            execution_error=str(r.get("execution_error") or ""),
            executed_at=str(r.get("executed_at") or ""),
        ))

    # Sort latest first
    requests.sort(key=lambda x: x.requested_at, reverse=True)
    return requests


def _run_request_execution(request_record: dict, actor_user_id: str):
    """Executes the approved action. Raises Exception on failure."""
    req_type = str(request_record.get("request_type") or "")
    target_uid = str(request_record.get("target_user_id") or "")
    payload_str = str(request_record.get("payload_json") or "{}")
    payload = json.loads(payload_str)

    if req_type == "CREATE_USER":
        return execute_create_user(payload, actor_user_id)
    elif req_type == "UPDATE_USER":
        return execute_update_user(target_uid, payload, actor_user_id)
    elif req_type == "DEACTIVATE_USER":
        return execute_set_user_status(target_uid, False, actor_user_id, reason=payload.get("reason", "Approved deactivation"))
    elif req_type == "REACTIVATE_USER":
        return execute_set_user_status(target_uid, True, actor_user_id, reason=payload.get("reason", "Approved reactivation"))
    elif req_type == "RESET_PASSWORD":
        new_pw = str(payload.get("new_password") or "")
        return execute_reset_password(target_uid, new_pw, actor_user_id, reason="Owner approved password reset")
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

    records = db.get_records("ApprovalRequests", fresh=True)
    target = next((r for r in records if str(r.get("request_id") or "").strip() == request_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Approval request not found.")

    current_status = str(target.get("status") or "PENDING").upper()
    if current_status not in {"PENDING", "EXECUTION_FAILED"}:
        raise HTTPException(status_code=400, detail=f"Cannot decide request currently in status {current_status}.")

    decision = decision_req.decision.strip().upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Decision must be APPROVED or REJECTED.")

    if decision == "REJECTED":
        updates = {
            "status": "REJECTED",
            "decided_by": owner_id,
            "decided_at": now_iso,
            "decision_notes": decision_req.notes or "",
        }
        db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)
        db.log_audit(owner_id, "REJECT_APPROVAL", "ApprovalRequests", request_id, reason=decision_req.notes or "Owner rejected request")
        updated_dict = dict(target)
        updated_dict.update(updates)
        return ApprovalRequestModel(**updated_dict)

    # Decision is APPROVED: attempt execution
    updates = {
        "decided_by": owner_id,
        "decided_at": now_iso,
        "decision_notes": decision_req.notes or "",
    }

    try:
        _run_request_execution(target, owner_id)
        updates["status"] = "EXECUTED"
        updates["executed_at"] = datetime.now(timezone.utc).isoformat()
        updates["execution_error"] = ""
        db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)
        db.log_audit(owner_id, "APPROVE_AND_EXECUTE", "ApprovalRequests", request_id, reason=f"Executed {target.get('request_type')}")
    except Exception as exc:
        logger.error(f"Execution failed for approved request {request_id}: {exc}")
        updates["status"] = "EXECUTION_FAILED"
        updates["execution_error"] = str(exc)
        db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)
        db.log_audit(owner_id, "APPROVAL_EXECUTION_FAILED", "ApprovalRequests", request_id, reason=str(exc))

    updated_dict = dict(target)
    updated_dict.update(updates)
    return ApprovalRequestModel(**updated_dict)


@router.post("/requests/{request_id}/retry", response_model=ApprovalRequestModel)
async def retry_failed_execution(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    require_owner(current_user)
    owner_id = str(current_user.get("user_id") or "")
    now_iso = datetime.now(timezone.utc).isoformat()

    records = db.get_records("ApprovalRequests", fresh=True)
    target = next((r for r in records if str(r.get("request_id") or "").strip() == request_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Approval request not found.")

    current_status = str(target.get("status") or "").upper()
    if current_status != "EXECUTION_FAILED":
        raise HTTPException(status_code=400, detail="Only requests with status EXECUTION_FAILED can be retried.")

    updates = {}
    try:
        _run_request_execution(target, owner_id)
        updates["status"] = "EXECUTED"
        updates["executed_at"] = now_iso
        updates["execution_error"] = ""
        db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)
        db.log_audit(owner_id, "RETRY_EXECUTION_SUCCESS", "ApprovalRequests", request_id, reason="Execution retry succeeded")
    except Exception as exc:
        logger.error(f"Execution retry failed for request {request_id}: {exc}")
        updates["status"] = "EXECUTION_FAILED"
        updates["execution_error"] = str(exc)
        db.update_record("ApprovalRequests", "request_id", request_id, updates, raise_on_error=True)
        db.log_audit(owner_id, "RETRY_EXECUTION_FAILED", "ApprovalRequests", request_id, reason=str(exc))

    updated_dict = dict(target)
    updated_dict.update(updates)
    return ApprovalRequestModel(**updated_dict)


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
