"""
Kawad Swad ERP - Quality, Product Lots, Traceability, Returns & Recalls Router
Integrates:
- QualityChecks
- ProductLots
- LotMovements
- CustomerReturns & CustomerReturnItems
- ComplaintsRecalls
"""

from typing import List, Dict, Any, Optional
import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.apps_script_bridge import apps_script_bridge
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager, is_owner, require_manager, require_owner, require_roles, role_v2_of
from app.schema_registry import LOT_QUALITY_STATES
from app.sheets import db
from app.timeutil import now_iso, business_today
from app.calculations.units import to_decimal, round_money, round_stock
from app.accounting.postings import post_customer_return_journal

router = APIRouter(prefix="/api/quality", tags=["Quality & Traceability"])

QUALITY_ROLES = {"OWNER_ADMIN", "OWNER", "ADMIN", "QUALITY"}


def require_quality_read_access(user: dict):
    return require_roles(
        user,
        {"OWNER_ADMIN", "PA", "QUALITY", "AUDITOR", "PRODUCTION", "PACKAGING", "STORE", "PROCUREMENT", "ACCOUNTS", "SALES"},
        detail="Access denied. Viewing Quality & Traceability records is restricted.",
    )


def require_quality_access(user: dict):
    return require_roles(
        user,
        {"OWNER_ADMIN", "QUALITY"},
        detail="Access denied. Quality & Traceability mutations require Quality or Owner permissions.",
    )


def require_owner_access(user: dict):
    return require_owner(user)


# ============================================================================
# Models
# ============================================================================

class QualityCheckCreate(BaseModel):
    check_type: str = Field(..., description="RAW_MATERIAL, MILLING, PRODUCTION_BATCH, PACKAGING, FINISHED_LOT")
    reference_type: str = Field(..., description="GRN, MILLING_BATCH, PRODUCTION_BATCH, PACKAGING_BATCH, PRODUCT_LOT")
    reference_id: str = Field(..., min_length=2)
    product_or_material_id: str
    item_name: str
    decision: str = Field("PASS", description="PASS, FAIL, HOLD")
    parameters_json: Optional[str] = "{}"
    defect_details: Optional[str] = ""
    corrective_action: Optional[str] = ""
    notes: Optional[str] = ""


class ProductLotCreate(BaseModel):
    product_id: str
    product_name: str
    production_id: Optional[str] = ""
    packaging_id: Optional[str] = ""
    lot_number: Optional[str] = None
    expiry_date: Optional[str] = ""
    initial_quantity: float = Field(..., gt=0)
    unit: str = "PACKET"
    notes: Optional[str] = ""


class LotStatusUpdate(BaseModel):
    quality_status: str = Field(..., description="RELEASED, QUARANTINE, REJECTED, RECALLED")
    hold_reason: Optional[str] = ""
    notes: Optional[str] = ""


class CustomerReturnItemInput(BaseModel):
    product_id: str
    sku: str
    product_name: str
    quantity: int = Field(..., gt=0)
    unit: str = "PACKET"
    unit_price: float = Field(..., ge=0)
    refund_amount: float = Field(..., ge=0)
    reason: str = Field(..., min_length=3)
    notes: Optional[str] = ""


class CustomerReturnCreate(BaseModel):
    sale_id: str
    bill_number: Optional[str] = ""
    customer_id: str
    customer_name: Optional[str] = None
    return_date: Optional[str] = ""
    disposition: str = Field("SCRAP", description="SCRAP, RESTOCK, PENDING_INSPECTION")
    is_cash_refund: bool = False
    items: List[CustomerReturnItemInput] = Field(..., min_items=1)
    notes: Optional[str] = ""


class CustomerReturnInspectRequest(BaseModel):
    inspection_status: str = Field(..., description="PASSED, REJECTED, SCRAPPED")
    disposition: str = Field(..., description="RESTOCK, SCRAP")
    notes: Optional[str] = ""


class ComplaintRecallCreate(BaseModel):
    report_type: str = Field("COMPLAINT", description="COMPLAINT or RECALL")
    customer_id: Optional[str] = ""
    customer_name: Optional[str] = ""
    product_id: str
    lot_id: Optional[str] = ""
    quantity_affected: float = Field(0.0, ge=0)
    severity: str = Field("MEDIUM", description="LOW, MEDIUM, HIGH, CRITICAL")
    description: str = Field(..., min_length=5)
    investigation: Optional[str] = ""
    corrective_action: Optional[str] = ""
    notes: Optional[str] = ""


# ============================================================================
# Quality Checks Endpoints
# ============================================================================

@router.get("/checks")
async def list_quality_checks(user: dict = Depends(get_current_user)):
    require_quality_read_access(user)
    checks = db.get_records("QualityChecks", fresh=True)
    checks.sort(key=lambda x: str(x.get("check_date", "") or x.get("created_at", "")), reverse=True)
    return checks


@router.post("/checks", dependencies=[Depends(require_sheets_connection)])
async def create_quality_check(
    req: QualityCheckCreate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    actor, actor_role = require_roles(
        user,
        {"OWNER_ADMIN", "QUALITY", "PRODUCTION"},
        detail="Access denied. Submitting quality checks requires Quality, Production, or Owner permissions.",
    )
    now = now_iso()
    today = business_today()

    lot_status_update: Optional[Dict[str, Any]] = None
    if req.reference_type.upper() in {"PRODUCT_LOT", "LOT"}:
        lots = db.get_records("ProductLots", fresh=True)
        lot = next((l for l in lots if str(l.get("lot_id")) == req.reference_id or str(l.get("lot_number")) == req.reference_id), None)
        if lot:
            dec_up = req.decision.upper()
            new_status = "RELEASED" if dec_up == "PASS" else ("ON_HOLD" if dec_up == "HOLD" else "REJECTED")
            lot_status_update = {
                "lot_id": str(lot.get("lot_id")),
                "quality_status": new_status,
                "hold_reason": (req.defect_details or req.notes or "").strip(),
            }

    qc_payload = {
        "check_date": today,
        "check_type": req.check_type.upper(),
        "reference_type": req.reference_type.upper(),
        "reference_id": req.reference_id.strip(),
        "product_or_material_id": req.product_or_material_id.strip(),
        "item_name": req.item_name.strip(),
        "inspector_user_id": actor,
        "status": "COMPLETED",
        "decision": req.decision.upper(),
        "parameters_json": req.parameters_json or "{}",
        "defect_details": (req.defect_details or "").strip(),
        "corrective_action": (req.corrective_action or "").strip(),
        "created_at": now,
        "notes": (req.notes or "").strip(),
        "lot_status_update": lot_status_update,
    }
    res = apps_script_bridge.delegate_governed_write(
        action="CREATE_QUALITY_CHECK",
        target_tab="QualityChecks",
        payload=qc_payload,
        request=request,
        actor_user_id=actor,
        actor_role=actor_role,
        id_field="qc_id",
        invalidate_tabs=["QualityChecks", "ProductLots"],
    )
    qc_id = str(res.get("allocated_id") or "")
    db.log_audit(actor, "CREATE_QUALITY_CHECK", "QualityChecks", qc_id, reason=f"Recorded QC check for {req.item_name}: {req.decision}")
    return {**qc_payload, "qc_id": qc_id, **res}


# ============================================================================
# Product Lots Endpoints
# ============================================================================

@router.get("/lots")
async def list_product_lots(user: dict = Depends(get_current_user)):
    require_quality_read_access(user)
    lots = db.get_records("ProductLots", fresh=True)
    lots.sort(key=lambda x: str(x.get("creation_date", "")), reverse=True)
    return lots


@router.post("/lots", dependencies=[Depends(require_sheets_connection)])
async def create_product_lot(
    req: ProductLotCreate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    actor, actor_role = require_quality_access(user)
    now = now_iso()
    today = business_today()

    lot_payload = {
        "lot_number": req.lot_number or "",
        "product_id": req.product_id,
        "product_name": req.product_name,
        "production_id": req.production_id or "",
        "packaging_id": req.packaging_id or "",
        "creation_date": today,
        "expiry_date": req.expiry_date or "",
        "initial_quantity": float(req.initial_quantity),
        "current_quantity": float(req.initial_quantity),
        "unit": req.unit,
        "quality_status": "PENDING_QC",
        "hold_reason": "",
        "status": "ACTIVE",
        "created_at": now,
        "created_by": actor,
        "notes": (req.notes or "").strip(),
        "initial_movement": {
            "movement_date": today,
            "source_type": "PACKAGING_BATCH" if req.packaging_id else "PRODUCTION_BATCH",
            "source_id": req.packaging_id or req.production_id or "",
            "movement_type": "LOT_CREATION",
            "quantity": float(req.initial_quantity),
            "unit": req.unit,
            "actor_user_id": actor,
            "created_at": now,
            "notes": f"Initial creation of lot for {req.product_name} (PENDING_QC)",
        },
    }
    res = apps_script_bridge.delegate_governed_write(
        action="CREATE_PRODUCT_LOT",
        target_tab="ProductLots",
        payload=lot_payload,
        request=request,
        actor_user_id=actor,
        actor_role=actor_role,
        id_field="lot_id",
        invalidate_tabs=["ProductLots", "LotMovements"],
    )
    lot_id = str(res.get("allocated_id") or "")
    lot_num = str((res.get("record") or {}).get("lot_number") or req.lot_number or lot_id)
    db.log_audit(actor, "CREATE_PRODUCT_LOT", "ProductLots", lot_id, reason=f"Created Lot {lot_num} for {req.product_name} ({req.initial_quantity} {req.unit})")
    return {**lot_payload, "lot_id": lot_id, "lot_number": lot_num, **res}


@router.post("/lots/{lot_id}/status", dependencies=[Depends(require_sheets_connection)])
async def update_lot_status(
    lot_id: str,
    req: LotStatusUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    actor, actor_role = require_roles(
        user,
        {"OWNER_ADMIN", "QUALITY"},
        detail="Only Quality Controller or OWNER_ADMIN can release, hold, or reject a product lot.",
    )
    new_st = req.quality_status.strip().upper()
    if new_st == "QUARANTINE":
        new_st = "ON_HOLD"
    valid_statuses = set(LOT_QUALITY_STATES) | {"RECALLED"}
    if new_st not in valid_statuses:
        raise HTTPException(422, f"Invalid lot quality_status '{req.quality_status}'. Allowed: {sorted(valid_statuses)}.")

    lots = db.get_records("ProductLots", fresh=True)
    lot = next((l for l in lots if str(l.get("lot_id")) == lot_id or str(l.get("lot_number")) == lot_id), None)
    if not lot:
        raise HTTPException(404, f"Product lot {lot_id} not found.")

    clean_lot_id = str(lot.get("lot_id"))
    now = now_iso()
    updates = {
        "lot_id": clean_lot_id,
        "quality_status": new_st,
        "hold_reason": (req.hold_reason or "").strip(),
        "notes": f"{lot.get('notes', '')} [Status -> {new_st}: {req.notes or ''}]".strip(),
        "lot_movement": {
            "movement_date": business_today(),
            "lot_id": clean_lot_id,
            "source_type": "QUALITY_STATUS_CHANGE",
            "source_id": clean_lot_id,
            "movement_type": f"STATUS_{new_st}",
            "quantity": float(lot.get("current_quantity", 0) or 0),
            "unit": str(lot.get("unit", "PACKET")),
            "actor_user_id": actor,
            "created_at": now,
            "notes": f"Status updated to {new_st}: {req.hold_reason}",
        },
    }
    res = apps_script_bridge.delegate_governed_write(
        action="UPDATE_LOT_STATUS",
        target_tab="ProductLots",
        payload=updates,
        request=request,
        actor_user_id=actor,
        actor_role=actor_role,
        id_field="lot_id",
        invalidate_tabs=["ProductLots", "LotMovements"],
    )
    db.log_audit(actor, f"LOT_STATUS_{new_st}", "ProductLots", clean_lot_id, reason=f"Lot {lot.get('lot_number')} status changed to {new_st}")
    return {**lot, **updates, **res}


@router.get("/lots/{lot_id}/movements")
async def list_lot_movements(lot_id: str, user: dict = Depends(get_current_user)):
    require_quality_read_access(user)
    movements = [m for m in db.get_records("LotMovements", fresh=True) if str(m.get("lot_id")) == lot_id]
    movements.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return movements


# ============================================================================
# Customer Returns Endpoints
# ============================================================================

@router.get("/customer-returns")
async def list_customer_returns(user: dict = Depends(get_current_user)):
    require_quality_read_access(user)
    returns = db.get_records("CustomerReturns", fresh=True)
    items = db.get_records("CustomerReturnItems", fresh=True)
    items_by_ret = {}
    for itm in items:
        items_by_ret.setdefault(str(itm.get("return_id")), []).append(itm)

    res = []
    for ret in returns:
        rid = str(ret.get("return_id"))
        res.append({
            **ret,
            "items": items_by_ret.get(rid, []),
        })
    res.sort(key=lambda x: str(x.get("return_date", "")), reverse=True)
    return res


@router.post("/customer-returns", dependencies=[Depends(require_sheets_connection)])
async def create_customer_return(
    req: CustomerReturnCreate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Records a customer sales return atomically via Apps Script Single Write Owner:
    1. Items do NOT automatically become saleable stock unless disposition == RESTOCK.
    2. Posts double-entry sales credit note via post_customer_return_journal.
    """
    actor, actor_role = require_quality_access(user)
    customers = db.get_records("Customers", fresh=True)
    cust = next((c for c in customers if str(c.get("customer_id")) == req.customer_id), None)
    cust_name = str(cust.get("shop_name") or cust.get("shopkeeper_name") or "Customer") if cust else (req.customer_name or "Customer")

    products = db.get_records("Products", fresh=True)
    prod_map = {str(p.get("product_id")): p for p in products}

    now = now_iso()
    today = business_today()
    ret_date = req.return_date or today
    disp_up = req.disposition.upper()

    total_refund = Decimal("0")
    item_rows = []
    restock_movements = []

    for itm in req.items:
        ref_amt_dec = to_decimal(itm.refund_amount)
        total_refund += ref_amt_dec
        prod = prod_map.get(itm.product_id, {})

        if disp_up == "RESTOCK":
            restock_movements.append({
                "txn_datetime": ret_date,
                "movement_type": "PACKET_RETURN",
                "product_id": itm.product_id,
                "bulk_product_key": str(prod.get("product_name", "")).lower(),
                "product_name_snapshot": itm.product_name,
                "sku_snapshot": itm.sku,
                "pack_weight_g": int(float(prod.get("pack_weight_g", 500) or 500)),
                "quantity_kg": 0,
                "quantity_packets": itm.quantity,
                "channel": "FACTORY_FINISHED",
                "destination": "FACTORY",
                "created_by": actor,
                "notes": f"Restocked customer return from {cust_name}: {itm.reason}",
            })

        item_rows.append({
            "product_id": itm.product_id,
            "sku": itm.sku,
            "product_name": itm.product_name,
            "quantity": itm.quantity,
            "unit": itm.unit,
            "unit_price": itm.unit_price,
            "refund_amount": float(round_money(ref_amt_dec)),
            "reason": itm.reason,
            "inspection_notes": f"Initial disposition: {disp_up}",
            "notes": (itm.notes or "").strip(),
        })

    ret_record = {
        "sale_id": req.sale_id,
        "bill_number": req.bill_number or "",
        "customer_id": req.customer_id,
        "customer_name": cust_name,
        "return_date": ret_date,
        "status": "APPROVED",
        "inspection_status": "INSPECTED" if disp_up != "PENDING_INSPECTION" else "PENDING",
        "disposition": disp_up,
        "approved_by": actor,
        "approved_at": now,
        "created_by": actor,
        "created_at": now,
        "notes": (req.notes or "").strip(),
        "items": item_rows,
        "restock_movements": restock_movements,
    }

    res = apps_script_bridge.delegate_governed_write(
        action="CREATE_CUSTOMER_RETURN",
        target_tab="CustomerReturns",
        payload=ret_record,
        request=request,
        actor_user_id=actor,
        actor_role=actor_role,
        id_field="return_id",
        invalidate_tabs=["CustomerReturns", "CustomerReturnItems", "ProductionStockLedger"],
    )
    return_id = str(res.get("allocated_id") or "")
    ret_num = str((res.get("record") or {}).get("return_number") or f"CN-{return_id}")

    # Post accounting sales credit note via Apps Script bridge (fail-closed if unconfigured or rejected)
    ret_dict = {
        "return_id": return_id,
        "refund_amount": float(total_refund),
        "tax_amount": float(total_refund * Decimal("0.05")),
        "customer_name": cust_name,
        "is_cash_refund": req.is_cash_refund,
        "return_date": ret_date,
    }
    post_customer_return_journal(ret_dict, actor=actor)

    db.log_audit(actor, "CREATE_CUSTOMER_RETURN", "CustomerReturns", return_id, reason=f"Created return {ret_num} from {cust_name} for ₹{float(total_refund):.2f}")
    return {**ret_record, "return_id": return_id, "return_number": ret_num, **res}


# ============================================================================
# Complaints and Recalls Endpoints
# ============================================================================

@router.get("/complaints")
async def list_complaints_recalls(user: dict = Depends(get_current_user)):
    require_quality_read_access(user)
    records = db.get_records("ComplaintsRecalls", fresh=True)
    records.sort(key=lambda x: str(x.get("report_date", "")), reverse=True)
    return records


@router.post("/complaints", dependencies=[Depends(require_sheets_connection)])
async def create_complaint_or_recall(
    req: ComplaintRecallCreate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    actor, actor_role = require_quality_access(user)
    now = now_iso()
    today = business_today()

    lot_quarantine_update = None
    if req.lot_id and (req.report_type.upper() == "RECALL" or req.severity.upper() == "CRITICAL"):
        lots = db.get_records("ProductLots", fresh=True)
        target_lot = next((l for l in lots if str(l.get("lot_id")) == req.lot_id or str(l.get("lot_number")) == req.lot_id), None)
        if target_lot:
            lot_quarantine_update = {
                "lot_id": str(target_lot.get("lot_id")),
                "quality_status": "RECALLED" if req.report_type.upper() == "RECALL" else "ON_HOLD",
                "hold_reason": f"Automated quarantine triggered by {req.report_type.upper()}: {req.description}",
            }

    record = {
        "report_date": today,
        "report_type": req.report_type.upper(),
        "customer_id": req.customer_id or "",
        "customer_name": (req.customer_name or "").strip(),
        "product_id": req.product_id,
        "lot_id": req.lot_id or "",
        "quantity_affected": float(req.quantity_affected),
        "severity": req.severity.upper(),
        "status": "OPEN",
        "description": req.description.strip(),
        "investigation": (req.investigation or "").strip(),
        "corrective_action": (req.corrective_action or "").strip(),
        "responsible_user_id": actor,
        "closure_date": "",
        "created_at": now,
        "notes": (req.notes or "").strip(),
        "lot_quarantine_update": lot_quarantine_update,
    }
    res = apps_script_bridge.delegate_governed_write(
        action="CREATE_COMPLAINT_OR_RECALL",
        target_tab="ComplaintsRecalls",
        payload=record,
        request=request,
        actor_user_id=actor,
        actor_role=actor_role,
        id_field="complaint_id",
        invalidate_tabs=["ComplaintsRecalls", "ProductLots"],
    )
    cmp_id = str(res.get("allocated_id") or "")
    db.log_audit(actor, f"RECORD_{req.report_type.upper()}", "ComplaintsRecalls", cmp_id, reason=f"{req.report_type} for lot {req.lot_id}: {req.description}")
    return {**record, "complaint_id": cmp_id, **res}


@router.post("/complaints/{complaint_id}/close", dependencies=[Depends(require_sheets_connection)])
async def close_complaint(
    complaint_id: str,
    request: Request,
    corrective_action: str = Query(..., min_length=5),
    user: dict = Depends(get_current_user),
):
    actor, actor_role = require_owner_access(user)
    records = db.get_records("ComplaintsRecalls", fresh=True)
    rec = next((c for c in records if str(c.get("complaint_id")) == complaint_id), None)
    if not rec:
        raise HTTPException(404, f"Complaint {complaint_id} not found.")

    updates = {
        "complaint_id": complaint_id,
        "status": "CLOSED",
        "closure_date": business_today(),
        "corrective_action": corrective_action.strip(),
    }
    res = apps_script_bridge.delegate_governed_write(
        action="CLOSE_COMPLAINT",
        target_tab="ComplaintsRecalls",
        payload=updates,
        request=request,
        actor_user_id=actor,
        actor_role=actor_role,
        id_field="complaint_id",
        invalidate_tabs=["ComplaintsRecalls"],
    )
    db.log_audit(actor, "CLOSE_COMPLAINT", "ComplaintsRecalls", complaint_id, reason=corrective_action)
    return {"ok": True, **res, "complaint_id": complaint_id, "status": "CLOSED", "bridge_status": res.get("status")}


@router.get("/summary")
async def quality_summary(user: dict = Depends(get_current_user)):
    require_quality_read_access(user)
    checks = db.get_records("QualityChecks", fresh=True)
    lots = db.get_records("ProductLots", fresh=True)
    complaints = db.get_records("ComplaintsRecalls", fresh=True)
    returns = db.get_records("CustomerReturns", fresh=True)

    open_complaints = sum(1 for c in complaints if str(c.get("status", "")).upper() == "OPEN")
    quarantined_lots = sum(1 for l in lots if str(l.get("quality_status", "")).upper() in {"QUARANTINE", "RECALLED", "REJECTED"})
    pending_returns = sum(1 for r in returns if str(r.get("inspection_status", "")).upper() == "PENDING")

    return {
        "total_checks": len(checks),
        "active_lots": len(lots),
        "quarantined_lots_count": quarantined_lots,
        "open_complaints_count": open_complaints,
        "pending_returns_count": pending_returns,
    }
