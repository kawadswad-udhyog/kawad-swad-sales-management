from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from app.models import AuditLogItem, AuditLogCreate
from app.sheets import db
from app.auth import get_current_user
from app.permissions import require_manager

router = APIRouter(prefix="/api/audit-logs", tags=["Audit Log"])

@router.get("", response_model=List[AuditLogItem])
async def list_audit_logs(
    limit: int = Query(250, ge=1, le=1000),
    entity_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    require_manager(current_user)
    records = db.get_records("AuditLog")
    items: List[AuditLogItem] = []
    for r in records:
        if entity_type and str(r.get("entity_type", "")).upper() != entity_type.upper():
            continue
        items.append(AuditLogItem(
            audit_id=str(r.get("audit_id", "")),
            event_datetime=str(r.get("event_datetime", "")),
            actor_user_id=str(r.get("actor_user_id", "")),
            action=str(r.get("action", "")),
            entity_type=str(r.get("entity_type", "")),
            entity_id=str(r.get("entity_id", "")),
            field_changed=str(r.get("field_changed", "")),
            old_value=str(r.get("old_value", "")),
            new_value=str(r.get("new_value", "")),
            reason=str(r.get("reason", "")),
            approved_by_user_id=str(r.get("approved_by_user_id", "")),
            related_record_id=str(r.get("related_record_id", "")),
        ))
    items.reverse()
    return items[:limit]

@router.post("", response_model=AuditLogItem)
async def create_audit_log(
    req: AuditLogCreate,
    current_user: dict = Depends(get_current_user)
):
    require_manager(current_user)
    actor = current_user.get("user_id", "SYSTEM")
    audit_id = db.generate_id("AuditLog")
    now_iso = db.get_records("AuditLog") # trigger or fetch
    from datetime import datetime
    now_iso_str = datetime.utcnow().isoformat()

    record = {
        "audit_id": audit_id,
        "event_datetime": now_iso_str,
        "actor_user_id": actor,
        "action": req.action,
        "entity_type": req.entity_type,
        "entity_id": req.entity_id,
        "field_changed": req.field_changed or "",
        "old_value": req.old_value or "",
        "new_value": req.new_value or "",
        "reason": req.reason or "",
        "approved_by_user_id": actor,
        "related_record_id": req.related_record_id or req.entity_id,
    }
    if not db.append_record("AuditLog", record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Audit log entry could not be saved to persistent storage.")
    return AuditLogItem(**record)
