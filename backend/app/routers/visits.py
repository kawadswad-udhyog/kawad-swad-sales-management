from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from app.apps_script_bridge import apps_script_bridge
from app.models import ShopVisit, ShopVisitCreate
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager, require_module_action

router = APIRouter(prefix="/api/visits", tags=["Shop Visits"])

@router.get("", response_model=List[ShopVisit])
async def list_shop_visits(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    require_module_action(current_user, "sales", "view")

    records = db.get_records("ShopVisits")
    visits = []
    for r in records:
        s_user = str(r.get("salesman_user_id", ""))
        if not is_manager(current_user) and s_user != user_id:
            continue
        visits.append(ShopVisit(
            visit_id=str(r.get("visit_id", "")),
            visit_datetime=str(r.get("visit_datetime", "")),
            salesman_user_id=s_user,
            customer_id=str(r.get("customer_id", "")),
            shop_name_snapshot=str(r.get("shop_name_snapshot", "")),
            visit_outcome=str(r.get("visit_outcome", "Order Placed")),
            order_taken=str(r.get("order_taken", "false")).lower() == "true",
            follow_up_date=str(r.get("follow_up_date", "")),
            next_action=str(r.get("next_action", "")),
            created_at=str(r.get("created_at", "")),
            notes=str(r.get("notes", "")),
        ))
    visits.reverse()
    return visits

@router.post("", response_model=ShopVisit, dependencies=[Depends(require_sheets_connection)])
async def log_shop_visit(req: ShopVisitCreate, request: Request, current_user: dict = Depends(get_current_user)):
    user_id, actor_role = require_module_action(current_user, "sales", "create")
    now_iso_str = datetime.now(timezone.utc).isoformat()

    record = {
        "visit_datetime": now_iso_str,
        "salesman_user_id": user_id,
        "customer_id": req.customer_id,
        "shop_name_snapshot": req.shop_name_snapshot,
        "visit_outcome": req.visit_outcome,
        "order_taken": "true" if req.order_taken else "false",
        "follow_up_date": req.follow_up_date or "",
        "next_action": req.next_action or "",
        "created_at": now_iso_str,
        "notes": req.notes or "",
    }
    res = apps_script_bridge.delegate_governed_write(
        action="LOG_SHOP_VISIT",
        target_tab="ShopVisits",
        payload=record,
        request=request,
        actor_user_id=user_id,
        actor_role=actor_role,
        id_field="visit_id",
        invalidate_tabs=["ShopVisits"],
    )
    visit_id = str(res.get("allocated_id") or "")

    db.log_audit(
        actor=user_id,
        action="LOG_VISIT",
        entity_type="ShopVisits",
        entity_id=visit_id,
        reason=f"Logged visit to {req.shop_name_snapshot} ({req.visit_outcome})"
    )

    return ShopVisit(visit_id=visit_id, **{**record, "order_taken": req.order_taken})
