"""
Kawad Swad ERP - Complete Purchasing & Supplier Management Router
Integrates:
- Suppliers
- PurchaseOrders & PurchaseOrderItems
- GoodsReceipts & GoodsReceiptItems
- SupplierBills
- SupplierPayments
- SupplierReturns & SupplierReturnItems
"""

from contextlib import ExitStack
import hashlib
import json
import math
from typing import List, Dict, Any, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.apps_script_bridge import apps_script_bridge
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_owner, require_roles, role_v2_of
from app.sheets import db
from app.timeutil import now_iso, business_today
from app.calculations.units import to_decimal, round_money, round_stock
from app.accounting.customer_ledger import CrossProcessLock
from app.accounting.postings import (
    post_receipt_journal,
    post_supplier_payment_journal,
    post_supplier_return_journal,
)

router = APIRouter(prefix="/api/purchasing", tags=["Purchasing"])

PROCUREMENT_READ_ROLES = {"OWNER_ADMIN", "PA", "PROCUREMENT", "STORE", "ACCOUNTS", "QUALITY", "AUDITOR"}
PROCUREMENT_WRITE_ROLES = {"OWNER_ADMIN", "PA", "PROCUREMENT"}
PROCUREMENT_RECEIVE_ROLES = {"OWNER_ADMIN", "PA", "PROCUREMENT", "STORE"}
PROCUREMENT_BILL_ROLES = {"OWNER_ADMIN", "PA", "PROCUREMENT", "ACCOUNTS"}
PROCUREMENT_PAYMENT_ROLES = {"OWNER_ADMIN", "ACCOUNTS"}


def _reject_auditor(user: dict) -> None:
    if role_v2_of(user) == "AUDITOR":
        raise HTTPException(403, "AUDITOR role is strictly read-only.")


def require_purchasing_read(user: dict):
    return require_roles(user, PROCUREMENT_READ_ROLES, "Access denied. Purchasing view requires authorized ERP privileges.")


def require_purchasing_access(user: dict):
    _reject_auditor(user)
    return require_roles(user, PROCUREMENT_WRITE_ROLES, "Access denied. Purchasing management requires Owner, PA, or Procurement privileges.")


def require_purchasing_receive(user: dict):
    _reject_auditor(user)
    return require_roles(user, PROCUREMENT_RECEIVE_ROLES, "Access denied. Goods receipt requires Owner, PA, Procurement, or Store privileges.")


def require_purchasing_bill(user: dict):
    _reject_auditor(user)
    return require_roles(user, PROCUREMENT_BILL_ROLES, "Access denied. Recording supplier bills requires Owner, PA, Procurement, or Accounts privileges.")


def require_purchasing_payment(user: dict):
    _reject_auditor(user)
    return require_roles(user, PROCUREMENT_PAYMENT_ROLES, "Access denied. Supplier payments require Owner or Accounts privileges.")


def require_owner_access(user: dict):
    _reject_auditor(user)
    if not is_owner(user):
        raise HTTPException(403, "Access denied. Action requires Owner privileges.")
    return str(user.get("user_id", "")), role_v2_of(user)


# ============================================================================
# Models
# ============================================================================

class SupplierCreate(BaseModel):
    supplier_name: str = Field(..., min_length=2, max_length=150)
    contact_person: Optional[str] = ""
    mobile: Optional[str] = ""
    email: Optional[str] = ""
    address: Optional[str] = ""
    city: Optional[str] = "Barwani"
    gstin: Optional[str] = ""
    notes: Optional[str] = ""


class PurchaseOrderItemInput(BaseModel):
    raw_material_id: str
    material_name: str
    ordered_quantity: float = Field(..., gt=0)
    unit: str = "kg"
    unit_price: float = Field(..., ge=0)
    tax_rate: float = 0.05
    notes: Optional[str] = ""


class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    supplier_name: Optional[str] = None
    expected_delivery_date: Optional[str] = ""
    items: List[PurchaseOrderItemInput] = Field(..., min_items=1)
    notes: Optional[str] = ""


class GoodsReceiptItemInput(BaseModel):
    po_item_id: Optional[str] = ""
    raw_material_id: str
    material_name: str
    delivered_quantity: float = Field(..., gt=0)
    accepted_quantity: float = Field(..., ge=0)
    rejected_quantity: float = Field(0.0, ge=0)
    unit: str = "kg"
    unit_rate: float = Field(..., ge=0)
    rejection_reason: Optional[str] = ""
    notes: Optional[str] = ""


class GoodsReceiptCreate(BaseModel):
    po_id: Optional[str] = ""
    supplier_id: str
    supplier_name: Optional[str] = None
    receipt_date: Optional[str] = ""
    invoice_reference: str = Field(..., min_length=2)
    delivery_challan: Optional[str] = ""
    quality_status: str = "ACCEPTED"
    items: List[GoodsReceiptItemInput] = Field(..., min_items=1)
    notes: Optional[str] = ""


class SupplierBillCreate(BaseModel):
    supplier_id: str
    supplier_name: Optional[str] = None
    receipt_id: Optional[str] = ""
    po_id: Optional[str] = ""
    bill_number: str = Field(..., min_length=2)
    bill_date: Optional[str] = ""
    due_date: Optional[str] = ""
    subtotal: float = Field(..., ge=0)
    tax_amount: float = Field(0.0, ge=0)
    total_amount: float = Field(..., ge=0)
    notes: Optional[str] = ""


class SupplierPaymentCreate(BaseModel):
    bill_id: Optional[str] = ""
    supplier_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    payment_method: str = "BANK_TRANSFER"  # BANK_TRANSFER, BANK, UPI, CASH, CHEQUE, NEFT, RTGS
    reference_number: Optional[str] = ""
    payment_date: Optional[str] = ""
    payment_type: Optional[str] = None
    idempotency_key: Optional[str] = None
    notes: Optional[str] = ""


class SupplierAdvanceApplyRequest(BaseModel):
    bill_id: str = Field(..., min_length=1)
    amount: Optional[float] = None
    idempotency_key: Optional[str] = None
    notes: Optional[str] = ""


class SupplierReturnItemInput(BaseModel):
    raw_material_id: str
    material_name: str
    quantity: float = Field(..., gt=0)
    unit: str = "kg"
    unit_rate: float = Field(..., ge=0)
    tax_amount: float = 0.0
    reason: str = Field(..., min_length=3)
    notes: Optional[str] = ""


class SupplierReturnCreate(BaseModel):
    receipt_id: Optional[str] = ""
    supplier_id: str
    supplier_name: Optional[str] = None
    return_date: Optional[str] = ""
    items: List[SupplierReturnItemInput] = Field(..., min_items=1)
    notes: Optional[str] = ""


# ============================================================================
# Supplier Endpoints
# ============================================================================

@router.get("/suppliers")
async def list_suppliers(user: dict = Depends(get_current_user)):
    require_purchasing_read(user)
    return db.get_records("Suppliers", fresh=True)


@router.post("/suppliers", dependencies=[Depends(require_sheets_connection)])
async def create_supplier(req: SupplierCreate, request: Request, user: dict = Depends(get_current_user)):
    actor, actor_role = require_purchasing_access(user)
    now = now_iso()

    # Duplicate name check
    existing = [s for s in db.get_records("Suppliers", fresh=True) if str(s.get("supplier_name", "")).strip().lower() == req.supplier_name.strip().lower()]
    if existing:
        raise HTTPException(400, f"Supplier with name '{req.supplier_name}' already exists.")

    row = {
        "supplier_name": req.supplier_name.strip(),
        "contact_person": (req.contact_person or "").strip(),
        "mobile": (req.mobile or "").strip(),
        "email": (req.email or "").strip(),
        "address": (req.address or "").strip(),
        "city": (req.city or "Barwani").strip(),
        "gstin": (req.gstin or "").strip(),
        "active": "true",
        "created_at": now,
        "created_by": actor,
        "notes": (req.notes or "").strip(),
    }
    bridge_res = apps_script_bridge.delegate_governed_write(
        action="CREATE_SUPPLIER",
        target_tab="Suppliers",
        payload=row,
        actor_user_id=actor,
        actor_role=actor_role,
        request=request,
        id_field="supplier_id",
        invalidate_tabs=["Suppliers"],
    )
    supp_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("supplier_id") or "")
    saved = bridge_res.get("record") or {**row, "supplier_id": supp_id}
    db.log_audit(actor, "CREATE_SUPPLIER", "Suppliers", supp_id, reason=f"Created supplier {req.supplier_name}")
    return saved


@router.put("/suppliers/{supplier_id}", dependencies=[Depends(require_sheets_connection)])
async def update_supplier(supplier_id: str, req: SupplierCreate, request: Request, user: dict = Depends(get_current_user)):
    actor, actor_role = require_purchasing_access(user)
    supp = next((s for s in db.get_records("Suppliers", fresh=True) if str(s.get("supplier_id")) == supplier_id), None)
    if not supp:
        raise HTTPException(404, f"Supplier {supplier_id} not found.")

    updates = {
        "supplier_id": supplier_id,
        "supplier_name": req.supplier_name.strip(),
        "contact_person": (req.contact_person or "").strip(),
        "mobile": (req.mobile or "").strip(),
        "email": (req.email or "").strip(),
        "address": (req.address or "").strip(),
        "city": (req.city or "Barwani").strip(),
        "gstin": (req.gstin or "").strip(),
        "notes": (req.notes or "").strip(),
        "updated_by": actor,
        "updated_at": now_iso(),
    }
    bridge_res = apps_script_bridge.delegate_governed_write(
        action="UPDATE_SUPPLIER",
        target_tab="Suppliers",
        payload=updates,
        actor_user_id=actor,
        actor_role=actor_role,
        request=request,
        id_field="supplier_id",
        invalidate_tabs=["Suppliers"],
    )
    db.log_audit(actor, "UPDATE_SUPPLIER", "Suppliers", supplier_id, reason=f"Updated details for {req.supplier_name}")
    return bridge_res.get("record") or {**supp, **updates}


# ============================================================================
# Purchase Orders Endpoints
# ============================================================================

@router.get("/orders")
async def list_purchase_orders(user: dict = Depends(get_current_user)):
    require_purchasing_read(user)
    orders = db.get_records("PurchaseOrders", fresh=True)
    items = db.get_records("PurchaseOrderItems", fresh=True)
    items_by_po = {}
    for itm in items:
        items_by_po.setdefault(str(itm.get("po_id")), []).append(itm)

    res = []
    for po in orders:
        pid = str(po.get("po_id"))
        res.append({
            **po,
            "items": items_by_po.get(pid, []),
        })
    res.sort(key=lambda x: str(x.get("order_date", "")), reverse=True)
    return res


@router.post("/orders", dependencies=[Depends(require_sheets_connection)])
async def create_purchase_order(req: PurchaseOrderCreate, request: Request, user: dict = Depends(get_current_user)):
    actor, actor_role = require_purchasing_access(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    now = now_iso()
    today = business_today()

    total_amt = Decimal("0")
    line_rows = []
    for idx, itm in enumerate(req.items):
        qty_dec = to_decimal(itm.ordered_quantity)
        rate_dec = to_decimal(itm.unit_price)
        base = qty_dec * rate_dec
        tax = base * to_decimal(itm.tax_rate)
        line_total = base + tax
        total_amt += line_total

        line_rows.append({
            "line_index": idx,
            "raw_material_id": itm.raw_material_id,
            "material_name": itm.material_name,
            "ordered_quantity": float(round_stock(qty_dec)),
            "received_quantity": 0.0,
            "unit": itm.unit,
            "unit_price": float(round_money(rate_dec)),
            "tax_amount": float(round_money(tax)),
            "line_total": float(round_money(line_total)),
            "notes": (itm.notes or "").strip(),
        })

    po_record = {
        "supplier_id": req.supplier_id,
        "supplier_name": supp_name,
        "order_date": today,
        "expected_delivery_date": req.expected_delivery_date or today,
        "total_amount": float(round_money(total_amt)),
        "status": "APPROVED",
        "created_by": actor,
        "created_at": now,
        "approved_by": actor,
        "approved_at": now,
        "notes": (req.notes or "").strip(),
    }

    bridge_res = apps_script_bridge.delegate_governed_write(
        action="CREATE_PURCHASE_ORDER",
        target_tab="PurchaseOrders",
        payload={"po": po_record, "items": line_rows},
        actor_user_id=actor,
        actor_role=actor_role,
        request=request,
        id_field="po_id",
        invalidate_tabs=["PurchaseOrders", "PurchaseOrderItems"],
    )
    po_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("po_id") or "")
    saved_po = bridge_res.get("record") or {**po_record, "po_id": po_id}
    db.log_audit(actor, "CREATE_PURCHASE_ORDER", "PurchaseOrders", po_id, reason=f"Created PO {saved_po.get('po_number', po_id)} for ₹{float(total_amt):.2f}")
    return {**saved_po, "items": line_rows}


@router.post("/orders/{po_id}/cancel", dependencies=[Depends(require_sheets_connection)])
async def cancel_purchase_order(po_id: str, request: Request, reason: str = Query(...), user: dict = Depends(get_current_user)):
    actor, actor_role = require_owner_access(user)
    orders = db.get_records("PurchaseOrders", fresh=True)
    po = next((p for p in orders if str(p.get("po_id")) == po_id), None)
    if not po:
        raise HTTPException(404, f"PO {po_id} not found.")

    if str(po.get("status")).upper() == "COMPLETED":
        raise HTTPException(400, "Cannot cancel a completed purchase order with recorded receipts.")

    apps_script_bridge.delegate_governed_write(
        action="CANCEL_PURCHASE_ORDER",
        target_tab="PurchaseOrders",
        payload={
            "po_id": po_id,
            "status": "CANCELLED",
            "reason": reason,
            "notes": f"{po.get('notes', '')} [CANCELLED by {actor}: {reason}]".strip(),
            "cancelled_by": actor,
            "cancelled_at": now_iso(),
        },
        actor_user_id=actor,
        actor_role=actor_role,
        request=request,
        id_field="po_id",
        invalidate_tabs=["PurchaseOrders"],
    )

    db.log_audit(actor, "CANCEL_PURCHASE_ORDER", "PurchaseOrders", po_id, reason=reason)
    return {"ok": True, "po_id": po_id, "status": "CANCELLED"}


# ============================================================================
# Goods Receipts Endpoints
# ============================================================================

@router.get("/receipts")
async def list_goods_receipts(user: dict = Depends(get_current_user)):
    require_purchasing_read(user)
    receipts = db.get_records("GoodsReceipts", fresh=True)
    items = db.get_records("GoodsReceiptItems", fresh=True)
    items_by_grn = {}
    for itm in items:
        items_by_grn.setdefault(str(itm.get("receipt_id")), []).append(itm)

    res = []
    for grn in receipts:
        gid = str(grn.get("receipt_id"))
        res.append({
            **grn,
            "items": items_by_grn.get(gid, []),
        })
    res.sort(key=lambda x: str(x.get("receipt_date", "")), reverse=True)
    return res


@router.post("/receipts", dependencies=[Depends(require_sheets_connection)])
async def create_goods_receipt(req: GoodsReceiptCreate, request: Request, user: dict = Depends(get_current_user)):
    """
    Records an authorized Goods Receipt Note (GRN) atomically via Apps Script bridge:
    1. Distinguishes delivered, accepted, and rejected quantities.
    2. Delegates GoodsReceipts + GoodsReceiptItems + RawMaterialLedger + PO received_quantity updates.
    3. Posts balanced double-entry accounting journal for accepted materials via Apps Script bridge.
    """
    actor, actor_role = require_purchasing_receive(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    now = now_iso()
    today = business_today()
    receipt_date = req.receipt_date or today

    po_items = db.get_records("PurchaseOrderItems", fresh=True)
    po_items_by_id = {str(p.get("po_item_id", "")).strip(): p for p in po_items}

    tot_accepted = 0.0
    tot_rejected = 0.0
    item_rows = []
    ledger_rows = []
    po_item_updates = []
    journal_candidates = []

    for idx, itm in enumerate(req.items):
        deliv = float(itm.delivered_quantity)
        acc = float(itm.accepted_quantity)
        rej = float(itm.rejected_quantity)
        if acc + rej != deliv and abs((acc + rej) - deliv) > 0.001:
            rej = round(deliv - acc, 3)

        tot_accepted += acc
        tot_rejected += rej

        if acc > 0:
            ledger_rows.append({
                "line_index": idx,
                "txn_datetime": receipt_date,
                "material_name": itm.material_name,
                "raw_material_id": itm.raw_material_id,
                "movement_type": "PURCHASE_RECEIPT",
                "quantity": acc,
                "unit": itm.unit,
                "rate_per_unit": itm.unit_rate,
                "production_id": "",
                "created_by": actor,
                "notes": f"GRN from {supp_name} (Inv: {req.invoice_reference})",
            })
            journal_candidates.append({
                "line_index": idx,
                "quantity": acc,
                "purchase_rate": itm.unit_rate,
                "freight_amount": 0.0,
                "gst_amount": acc * itm.unit_rate * 0.05,
                "gst_treatment": "RECOVERABLE_ITC",
                "material_name": itm.material_name,
                "supplier_name": supp_name,
                "invoice_number": req.invoice_reference,
                "receipt_date": receipt_date,
            })

        if itm.po_item_id:
            po_itm = po_items_by_id.get(str(itm.po_item_id).strip())
            if po_itm:
                old_recv = float(po_itm.get("received_quantity", 0) or 0)
                po_item_updates.append({
                    "po_item_id": itm.po_item_id,
                    "received_quantity": old_recv + acc,
                })

        item_rows.append({
            "line_index": idx,
            "po_item_id": itm.po_item_id or "",
            "raw_material_id": itm.raw_material_id,
            "material_name": itm.material_name,
            "delivered_quantity": deliv,
            "accepted_quantity": acc,
            "rejected_quantity": rej,
            "unit": itm.unit,
            "unit_rate": itm.unit_rate,
            "rejection_reason": (itm.rejection_reason or "").strip(),
            "notes": (itm.notes or "").strip(),
        })

    grn_record = {
        "po_id": req.po_id or "",
        "supplier_id": req.supplier_id,
        "supplier_name": supp_name,
        "receipt_date": receipt_date,
        "invoice_reference": req.invoice_reference.strip(),
        "delivery_challan": (req.delivery_challan or "").strip(),
        "total_accepted_qty": tot_accepted,
        "total_rejected_qty": tot_rejected,
        "quality_status": req.quality_status,
        "status": "RECEIVED",
        "received_by": actor,
        "created_at": now,
        "notes": (req.notes or "").strip(),
    }

    bridge_res = apps_script_bridge.delegate_governed_write(
        action="RECEIVE_GOODS",
        target_tab="GoodsReceipts",
        payload={
            "grn": grn_record,
            "items": item_rows,
            "raw_material_ledger_rows": ledger_rows,
            "po_item_updates": po_item_updates,
        },
        actor_user_id=actor,
        actor_role=actor_role,
        request=request,
        id_field="receipt_id",
        invalidate_tabs=["GoodsReceipts", "GoodsReceiptItems", "RawMaterialLedger", "RawMaterials", "PurchaseOrderItems", "PurchaseOrders"],
    )
    receipt_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("receipt_id") or "")
    saved_grn = bridge_res.get("record") or {**grn_record, "receipt_id": receipt_id}
    grn_number = str(saved_grn.get("receipt_number") or receipt_id)

    for jc in journal_candidates:
        receipt_dict = {
            **jc,
            "raw_material_txn_id": f"{receipt_id}#L{jc['line_index']}",
        }
        post_receipt_journal(receipt_dict, actor=actor)

    db.log_audit(
        actor,
        "RECEIVE_GOODS",
        "GoodsReceipts",
        receipt_id,
        reason=f"Received GRN {grn_number} ({tot_accepted} accepted, {tot_rejected} rejected) from {supp_name}",
    )
    return {**saved_grn, "items": item_rows}


# ============================================================================
# Supplier Bills Endpoints
# ============================================================================

@router.get("/bills")
async def list_supplier_bills(user: dict = Depends(get_current_user)):
    require_purchasing_read(user)
    bills = db.get_records("SupplierBills", fresh=True)
    bills.sort(key=lambda x: str(x.get("bill_date", "")), reverse=True)
    return bills


@router.post("/bills", dependencies=[Depends(require_sheets_connection)])
async def create_supplier_bill(req: SupplierBillCreate, request: Request, user: dict = Depends(get_current_user)):
    actor, actor_role = require_purchasing_bill(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    # Duplicate bill reference check
    existing_bills = db.get_records("SupplierBills", fresh=True)
    dup = next((b for b in existing_bills if str(b.get("supplier_id")) == req.supplier_id and str(b.get("bill_number")).strip().lower() == req.bill_number.strip().lower()), None)
    if dup:
        raise HTTPException(409, f"Supplier bill '{req.bill_number}' for {supp_name} has already been recorded.")

    now = now_iso()
    today = business_today()

    bill_row = {
        "bill_number": req.bill_number.strip(),
        "supplier_id": req.supplier_id,
        "supplier_name": supp_name,
        "receipt_id": req.receipt_id or "",
        "po_id": req.po_id or "",
        "bill_date": req.bill_date or today,
        "due_date": req.due_date or today,
        "subtotal": round_money(req.subtotal),
        "tax_amount": round_money(req.tax_amount),
        "total_amount": round_money(req.total_amount),
        "paid_amount": 0.0,
        "balance_amount": round_money(req.total_amount),
        "payment_status": "UNPAID",
        "status": "APPROVED",
        "created_by": actor,
        "created_at": now,
        "notes": (req.notes or "").strip(),
    }
    bridge_res = apps_script_bridge.delegate_governed_write(
        action="RECORD_SUPPLIER_BILL",
        target_tab="SupplierBills",
        payload=bill_row,
        actor_user_id=actor,
        actor_role=actor_role,
        request=request,
        id_field="bill_id",
        invalidate_tabs=["SupplierBills"],
    )
    bill_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("bill_id") or "")
    saved_bill = bridge_res.get("record") or {**bill_row, "bill_id": bill_id}
    db.log_audit(actor, "RECORD_SUPPLIER_BILL", "SupplierBills", bill_id, reason=f"Recorded bill {req.bill_number} from {supp_name} for ₹{req.total_amount:.2f}")
    return saved_bill


# ============================================================================
# Supplier Payments Endpoints
# ============================================================================

def _parse_allocations(raw_val: Any) -> List[Dict[str, Any]]:
    if isinstance(raw_val, list):
        return [dict(x) for x in raw_val if isinstance(x, dict)]
    text = str(raw_val or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return [dict(x) for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []
    except Exception:
        return []


def _enrich_payment_row(row: Dict[str, Any]) -> Dict[str, Any]:
    amt = round(float(row.get("amount", 0) or 0), 2)
    bill_id = str(row.get("bill_id", "") or "").strip()
    pay_type = str(row.get("payment_type", "") or "").strip().upper()
    if not pay_type:
        pay_type = "BILL_PAYMENT" if bill_id else "ON_ACCOUNT"
    allocs = _parse_allocations(row.get("allocations_json"))
    raw_alloc = row.get("allocated_amount")
    raw_unalloc = row.get("unallocated_amount")
    if raw_alloc is not None and str(raw_alloc).strip() != "":
        alloc_amt = round(float(raw_alloc or 0), 2)
    elif bill_id:
        alloc_amt = amt
    else:
        alloc_amt = round(sum(float(a.get("amount", 0) or 0) for a in allocs), 2)
    if raw_unalloc is not None and str(raw_unalloc).strip() != "":
        unalloc_amt = max(0.0, round(float(raw_unalloc or 0), 2))
    else:
        unalloc_amt = max(0.0, round(amt - alloc_amt, 2))
    return {
        **row,
        "bill_id": bill_id,
        "payment_type": pay_type,
        "allocated_amount": alloc_amt,
        "unallocated_amount": unalloc_amt,
        "allocations": allocs,
    }


def _normalize_supplier_payment_method(raw_method: str) -> str:
    m = str(raw_method or "").strip().upper()
    aliases = {
        "CASH": "CASH",
        "UPI": "UPI",
        "BANK": "BANK_TRANSFER",
        "BANK_TRANSFER": "BANK_TRANSFER",
        "NEFT": "NEFT",
        "RTGS": "RTGS",
        "CHEQUE": "CHEQUE",
    }
    if m not in aliases:
        raise HTTPException(400, f"Unsupported payment method '{raw_method}'. Allowed: CASH, UPI, BANK_TRANSFER, NEFT, RTGS, CHEQUE.")
    return aliases[m]


def _normalize_payment_date(raw_date: Optional[str], fallback_today: str) -> str:
    txt = str(raw_date or "").strip()
    if not txt:
        return str(fallback_today or "").strip()[:10]
    if len(txt) >= 10 and txt[4:5] == "-" and txt[7:8] == "-":
        return txt[:10]
    return txt


def _normalize_supplier_payment_type(raw_type: Optional[str], clean_bill_id: str) -> str:
    txt = str(raw_type or "").strip().upper()
    if txt:
        return txt
    return "BILL_PAYMENT" if clean_bill_id else "ON_ACCOUNT"


def _canonical_supplier_payment_payload(
    *,
    supplier_id: str,
    bill_id: str,
    amount: Any,
    payment_method: str,
    reference_number: Optional[str],
    payment_date: Optional[str],
    payment_type: Optional[str],
    fallback_today: str,
) -> Dict[str, Any]:
    clean_supp = str(supplier_id or "").strip()
    clean_bill = str(bill_id or "").strip()
    clean_method = _normalize_supplier_payment_method(payment_method)
    clean_ref = str(reference_number if reference_number is not None else "").strip()
    norm_date = _normalize_payment_date(payment_date, fallback_today)
    norm_type = _normalize_supplier_payment_type(payment_type, clean_bill)
    amt_dec = round_money(to_decimal(amount))
    settlement_acct = "1110" if clean_method == "CASH" else "1120"
    return {
        "supplier_id": clean_supp,
        "has_bill": bool(clean_bill),
        "bill_id": clean_bill,
        "amount": amt_dec,
        "payment_method": clean_method,
        "reference_number": clean_ref,
        "payment_date": norm_date,
        "payment_type": norm_type,
        "settlement_account": settlement_acct,
    }


def _supplier_payment_payload_mismatches(
    existing_row: Dict[str, Any],
    incoming: Dict[str, Any],
) -> List[str]:
    ex_bill = str(existing_row.get("bill_id", "") or "").strip()
    ex_raw_method = str(existing_row.get("payment_method", "") or "").strip()
    try:
        ex_method = _normalize_supplier_payment_method(ex_raw_method)
    except HTTPException:
        ex_method = ex_raw_method.upper()
    ex_date_raw = str(existing_row.get("payment_date", "") or "").strip()
    ex_date = _normalize_payment_date(ex_date_raw, incoming["payment_date"])
    ex_type = _normalize_supplier_payment_type(existing_row.get("payment_type"), ex_bill)
    ex_amt = round_money(to_decimal(existing_row.get("amount", 0) or 0))
    ex_ref = str(existing_row.get("reference_number", "") or "").strip()
    ex_supp = str(existing_row.get("supplier_id", "") or "").strip()
    ex_acct = "1110" if ex_method == "CASH" else "1120"

    existing_norm = {
        "supplier_id": ex_supp,
        "has_bill": bool(ex_bill),
        "bill_id": ex_bill,
        "amount": ex_amt,
        "payment_method": ex_method,
        "reference_number": ex_ref,
        "payment_date": ex_date,
        "payment_type": ex_type,
        "settlement_account": ex_acct,
    }

    mismatches: List[str] = []
    for field in (
        "supplier_id",
        "has_bill",
        "bill_id",
        "amount",
        "payment_method",
        "reference_number",
        "payment_date",
        "payment_type",
        "settlement_account",
    ):
        if existing_norm[field] != incoming[field]:
            mismatches.append(f"{field}: {existing_norm[field]!r} != {incoming[field]!r}")
    return mismatches


def _idemp_lock_token(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


@router.get("/payments")
async def list_supplier_payments(user: dict = Depends(get_current_user)):
    require_purchasing_read(user)
    payments = [_enrich_payment_row(p) for p in db.get_records("SupplierPayments", fresh=True)]
    payments.sort(key=lambda x: str(x.get("payment_date", "")), reverse=True)
    return payments


@router.post("/payments", dependencies=[Depends(require_sheets_connection)])
async def record_supplier_payment(req: SupplierPaymentCreate, request: Request, user: dict = Depends(get_current_user)):
    actor, actor_role = require_purchasing_payment(user)

    if not math.isfinite(req.amount) or req.amount <= 0:
        raise HTTPException(400, "Payment amount must be greater than zero.")

    clean_supplier_id = str(req.supplier_id or "").strip()
    if not clean_supplier_id:
        raise HTTPException(400, "Supplier ID is required.")

    today = business_today()
    incoming = _canonical_supplier_payment_payload(
        supplier_id=clean_supplier_id,
        bill_id=req.bill_id or "",
        amount=req.amount,
        payment_method=req.payment_method,
        reference_number=req.reference_number,
        payment_date=req.payment_date,
        payment_type=req.payment_type,
        fallback_today=today,
    )
    clean_bill_id = incoming["bill_id"]
    clean_method = incoming["payment_method"]
    clean_ref = incoming["reference_number"]
    pay_type = incoming["payment_type"]
    payment_date_val = incoming["payment_date"]
    req_amount = float(incoming["amount"])
    clean_idemp_key = str(req.idempotency_key or "").strip()

    with ExitStack() as stack:
        if clean_idemp_key:
            stack.enter_context(CrossProcessLock("supplier_payment_idemp", _idemp_lock_token(clean_idemp_key)))

        payments = db.get_records("SupplierPayments", fresh=True)
        existing_pay = None
        if clean_idemp_key:
            existing_pay = next(
                (p for p in reversed(payments) if str(p.get("idempotency_key", "")).strip() == clean_idemp_key),
                None,
            )
            if existing_pay:
                mismatches = _supplier_payment_payload_mismatches(existing_pay, incoming)
                if mismatches:
                    existing_pay_id = str(existing_pay.get("payment_id", "")).strip()
                    db.log_audit(
                        actor,
                        "SUPPLIER_PAYMENT_IDEMPOTENCY_CONFLICT",
                        "SupplierPayments",
                        existing_pay_id,
                        field_changed="idempotency_key",
                        old_val=json.dumps({
                            "supplier_id": existing_pay.get("supplier_id"),
                            "bill_id": existing_pay.get("bill_id", ""),
                            "amount": str(existing_pay.get("amount")),
                            "payment_method": existing_pay.get("payment_method"),
                            "reference_number": existing_pay.get("reference_number", ""),
                            "payment_date": existing_pay.get("payment_date", ""),
                            "payment_type": existing_pay.get("payment_type", ""),
                        }),
                        new_val=json.dumps({
                            "supplier_id": incoming["supplier_id"],
                            "bill_id": incoming["bill_id"],
                            "amount": str(incoming["amount"]),
                            "payment_method": incoming["payment_method"],
                            "reference_number": incoming["reference_number"],
                            "payment_date": incoming["payment_date"],
                            "payment_type": incoming["payment_type"],
                        }),
                        reason=f"Conflicting retry on idempotency_key '{clean_idemp_key}': {'; '.join(mismatches)}",
                    )
                    raise HTTPException(
                        409,
                        f"Idempotency key already used with a different payment payload ({'; '.join(mismatches)}).",
                    )

                ex_status = str(existing_pay.get("status", "")).strip().upper()
                if ex_status == "PAID":
                    # Fail-closed accounting recovery: ensure journal exists before returning idempotent replay
                    existing_pay_id = str(existing_pay.get("payment_id", "")).strip()
                    if existing_pay_id:
                        existing_journals = db.get_records("JournalHeaders", fresh=True) or []
                        has_journal = any(
                            str(j.get("reference_type", "")).strip().upper() == "SUPPLIER_PAYMENT"
                            and str(j.get("reference_id", "")).strip() == existing_pay_id
                            and str(j.get("status", "")).strip().upper() != "REVERSED"
                            for j in existing_journals
                        )
                        if not has_journal:
                            post_supplier_payment_journal(existing_pay, actor=actor)
                    bills_snapshot = db.get_records("SupplierBills", fresh=True) if clean_bill_id else []
                    bill_row = (
                        next((b for b in bills_snapshot if str(b.get("bill_id", "")).strip() == clean_bill_id), None)
                        if clean_bill_id
                        else None
                    )
                    rem_bal = round(float(bill_row.get("balance_amount", 0) or 0), 2) if bill_row else 0.0
                    b_status = str(bill_row.get("payment_status", "N/A")) if bill_row else pay_type
                    return {
                        "ok": True,
                        "payment": _enrich_payment_row(existing_pay),
                        "remaining_balance": rem_bal,
                        "bill_status": b_status,
                        "payment_type": pay_type,
                        "is_replay": True,
                    }

        if clean_method != "CASH" and len(clean_ref) < 2:
            raise HTTPException(
                400,
                f"External bank/UPI/cheque reference number is required for {clean_method} payment.",
            )

        if existing_pay is None and req.payment_type is not None and str(req.payment_type).strip():
            if pay_type == "BILL_PAYMENT" and not clean_bill_id:
                raise HTTPException(400, "bill_id is required when payment_type is BILL_PAYMENT.")
            if pay_type in {"ON_ACCOUNT", "ADVANCE"} and clean_bill_id:
                raise HTTPException(400, f"bill_id must be empty when payment_type is {pay_type}.")

        suppliers = db.get_records("Suppliers", fresh=True)
        supp = next((s for s in suppliers if str(s.get("supplier_id", "")).strip() == clean_supplier_id), None)
        if not supp:
            raise HTTPException(404, f"Supplier {clean_supplier_id} not found.")
        supp_name = str(supp.get("supplier_name") or clean_supplier_id)

        stack.enter_context(CrossProcessLock("supplier", clean_supplier_id))
        if clean_bill_id:
            stack.enter_context(CrossProcessLock("supplier_bill", clean_bill_id))

        bills = db.get_records("SupplierBills", fresh=True)
        bill = None
        if clean_bill_id:
            bill = next((b for b in bills if str(b.get("bill_id", "")).strip() == clean_bill_id), None)
            if not bill:
                raise HTTPException(404, f"Supplier bill {clean_bill_id} not found.")
            if str(bill.get("supplier_id", "")).strip() != clean_supplier_id:
                raise HTTPException(
                    400,
                    f"Bill {clean_bill_id} belongs to supplier {bill.get('supplier_id')}, not {clean_supplier_id}.",
                )
            cur_bal = round(float(bill.get("balance_amount", 0) or 0), 2)
            spay_marker_present = existing_pay is not None and f"[spay:{existing_pay.get('payment_id')}]" in str(bill.get("notes", ""))
            if not spay_marker_present and float(req_amount) > cur_bal + 0.05:
                raise HTTPException(
                    400,
                    f"Payment of ₹{float(req_amount):.2f} exceeds outstanding balance of ₹{cur_bal:.2f}.",
                )

        now = now_iso()
        allocs_initial = (
            [
                {
                    "bill_id": clean_bill_id,
                    "bill_number": str(bill.get("bill_number", "")) if bill else "",
                    "amount": float(req_amount),
                    "allocated_at": now,
                    "allocated_by": actor,
                }
            ]
            if clean_bill_id
            else []
        )
        pay_row = {
            "bill_id": clean_bill_id,
            "supplier_id": clean_supplier_id,
            "supplier_name": supp_name,
            "payment_date": payment_date_val,
            "amount": req_amount,
            "payment_method": clean_method,
            "reference_number": clean_ref,
            "status": "PAID",
            "paid_by": actor,
            "created_at": (str(existing_pay.get("created_at") or now) if existing_pay else now),
            "notes": (req.notes or "").strip(),
            "payment_type": pay_type,
            "allocated_amount": float(req_amount) if clean_bill_id else 0.0,
            "unallocated_amount": 0.0 if clean_bill_id else float(req_amount),
            "allocations_json": json.dumps(allocs_initial),
            "idempotency_key": clean_idemp_key,
        }
        if existing_pay is not None and str(existing_pay.get("payment_id", "")).strip():
            pay_row["payment_id"] = str(existing_pay.get("payment_id", "")).strip()

        new_bal = 0.0
        new_status = pay_type
        bill_update_payload = None
        if bill is not None:
            spay_marker_present = existing_pay is not None and f"[spay:{existing_pay.get('payment_id')}]" in str(bill.get("notes", ""))
            if spay_marker_present:
                new_bal = round(float(bill.get("balance_amount", 0) or 0), 2)
                new_status = str(bill.get("payment_status", "PARTIALLY_PAID"))
            else:
                old_paid = float(bill.get("paid_amount", 0) or 0)
                new_paid = round(old_paid + float(req_amount), 2)
                tot_amt = float(bill.get("total_amount", 0) or 0)
                new_bal = max(0.0, round(tot_amt - new_paid, 2))
                new_status = "PAID" if new_bal <= 0.05 else "PARTIALLY_PAID"
                bill_update_payload = {
                    "bill_id": clean_bill_id,
                    "paid_amount": new_paid,
                    "balance_amount": new_bal,
                    "payment_status": new_status,
                    "existing_notes": str(bill.get("notes", "") or ""),
                }

        if existing_pay is not None and str(existing_pay.get("payment_id", "")).strip():
            existing_pid = str(existing_pay.get("payment_id", "")).strip()
            pay_row["payment_id"] = existing_pid
            bridge_res = apps_script_bridge.delegate_governed_write(
                action="APPLY_SUPPLIER_ADVANCE",
                target_tab="SupplierPayments",
                payload={
                    "payment_id": existing_pid,
                    "payment_update": pay_row,
                    "bill_update": bill_update_payload,
                },
                actor_user_id=actor,
                actor_role=actor_role,
                nonce=clean_idemp_key or None,
                request=request,
                id_field="payment_id",
                invalidate_tabs=["SupplierPayments", "SupplierBills"],
            )
            pay_id = existing_pid
            saved_pay = bridge_res.get("record") or {**pay_row, "payment_id": pay_id}
        else:
            bridge_res = apps_script_bridge.delegate_governed_write(
                action="RECORD_SUPPLIER_PAYMENT",
                target_tab="SupplierPayments",
                payload={
                    "payment": pay_row,
                    "bill_update": bill_update_payload,
                },
                actor_user_id=actor,
                actor_role=actor_role,
                nonce=clean_idemp_key or None,
                request=request,
                id_field="payment_id",
                invalidate_tabs=["SupplierPayments", "SupplierBills"],
            )
            pay_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("payment_id") or "")
            saved_pay = bridge_res.get("record") or {**pay_row, "payment_id": pay_id}

        # Post double-entry accounting journal (fail-closed via bridge)
        post_supplier_payment_journal(saved_pay, actor=actor)

        audit_target = f"bill {bill.get('bill_number')}" if bill else "on-account advance"
        db.log_audit(
            actor,
            "RECORD_SUPPLIER_PAYMENT",
            "SupplierPayments",
            pay_id,
            reason=f"Paid ₹{float(req_amount):.2f} to {supp_name} ({audit_target})",
        )
        return {
            "ok": True,
            "payment": _enrich_payment_row(saved_pay),
            "remaining_balance": new_bal,
            "bill_status": new_status,
            "payment_type": pay_type,
            "is_replay": bool(existing_pay),
        }


@router.post("/payments/{payment_id}/apply", dependencies=[Depends(require_sheets_connection)])
async def apply_supplier_advance_to_bill(
    payment_id: str,
    req: SupplierAdvanceApplyRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Reconcile an existing On-Account / Advance supplier payment against a supplier bill atomically via Apps Script bridge.
    """
    actor, actor_role = require_purchasing_payment(user)
    clean_pay_id = str(payment_id or "").strip()
    clean_bill_id = str(req.bill_id or "").strip()
    clean_idemp_key = str(req.idempotency_key or "").strip()

    if not clean_bill_id:
        raise HTTPException(400, "Target bill_id is required to apply advance payment.")
    if req.amount is not None and (not math.isfinite(req.amount) or req.amount <= 0):
        raise HTTPException(400, "Applied amount must be greater than zero.")

    pre_payments = db.get_records("SupplierPayments", fresh=True)
    pre_pay = next((p for p in pre_payments if str(p.get("payment_id", "")).strip() == clean_pay_id), None)
    if not pre_pay:
        raise HTTPException(404, f"Supplier payment {clean_pay_id} not found.")
    clean_supplier_id = str(pre_pay.get("supplier_id", "")).strip()

    with ExitStack() as stack:
        if clean_idemp_key:
            stack.enter_context(
                CrossProcessLock("supplier_advance_apply_idemp", _idemp_lock_token(f"{clean_pay_id}:{clean_idemp_key}"))
            )
        stack.enter_context(CrossProcessLock("supplier", clean_supplier_id))
        stack.enter_context(CrossProcessLock("supplier_bill", clean_bill_id))

        payments = db.get_records("SupplierPayments", fresh=True)
        pay_raw = next((p for p in payments if str(p.get("payment_id", "")).strip() == clean_pay_id), None)
        if not pay_raw:
            raise HTTPException(404, f"Supplier payment {clean_pay_id} not found.")
        if str(pay_raw.get("status", "")).strip().upper() != "PAID":
            raise HTTPException(400, f"Payment {clean_pay_id} is in status '{pay_raw.get('status')}' and cannot be applied.")

        bills = db.get_records("SupplierBills", fresh=True)
        bill = next((b for b in bills if str(b.get("bill_id", "")).strip() == clean_bill_id), None)
        if not bill:
            raise HTTPException(404, f"Supplier bill {clean_bill_id} not found.")
        if str(bill.get("supplier_id", "")).strip() != clean_supplier_id:
            raise HTTPException(
                400,
                f"Bill {clean_bill_id} belongs to supplier {bill.get('supplier_id')}, not {clean_supplier_id}.",
            )

        enriched = _enrich_payment_row(pay_raw)
        allocs = list(enriched["allocations"])

        if clean_idemp_key:
            prior = next((a for a in allocs if str(a.get("idempotency_key", "")).strip() == clean_idemp_key), None)
            if prior:
                prior_bill = str(prior.get("bill_id", "")).strip()
                prior_amt = round_money(to_decimal(prior.get("amount", 0) or 0))
                req_amt_dec = round_money(to_decimal(req.amount)) if req.amount is not None else None
                if prior_bill != clean_bill_id or (req_amt_dec is not None and prior_amt != req_amt_dec):
                    db.log_audit(
                        actor,
                        "APPLY_SUPPLIER_ADVANCE_IDEMPOTENCY_CONFLICT",
                        "SupplierPayments",
                        clean_pay_id,
                        field_changed="idempotency_key",
                        old_val=f"bill_id={prior_bill},amount={prior_amt}",
                        new_val=f"bill_id={clean_bill_id},amount={req_amt_dec}",
                        reason=f"Conflicting advance allocation retry on key '{clean_idemp_key}'",
                    )
                    raise HTTPException(409, "Idempotency key already used for a different allocation.")
                return {
                    "ok": True,
                    "payment": enriched,
                    "bill": bill,
                    "applied_amount": float(prior.get("amount", 0)),
                    "is_replay": True,
                }

        available_advance = float(enriched["unallocated_amount"])
        if available_advance <= 0.005:
            raise HTTPException(400, f"Payment {clean_pay_id} has no remaining unallocated advance balance.")

        bill_bal = round(float(bill.get("balance_amount", 0) or 0), 2)
        if bill_bal <= 0.005:
            raise HTTPException(400, f"Supplier bill {bill.get('bill_number')} is already fully paid.")

        apply_amt = round(float(req.amount), 2) if req.amount is not None else round(min(available_advance, bill_bal), 2)
        if apply_amt > available_advance + 0.05:
            raise HTTPException(
                400,
                f"Requested allocation ₹{apply_amt:.2f} exceeds remaining advance ₹{available_advance:.2f}.",
            )
        if apply_amt > bill_bal + 0.05:
            raise HTTPException(
                400,
                f"Requested allocation ₹{apply_amt:.2f} exceeds bill balance ₹{bill_bal:.2f}.",
            )

        now = now_iso()
        alloc_tag = f"[spay-alloc:{clean_pay_id}:{clean_idemp_key or len(allocs) + 1}]"
        bill_notes = str(bill.get("notes", "") or "")
        bill_updates: Dict[str, Any] = {}
        if alloc_tag not in bill_notes:
            old_paid = float(bill.get("paid_amount", 0) or 0)
            new_paid = round(old_paid + apply_amt, 2)
            tot_amt = float(bill.get("total_amount", 0) or 0)
            new_bal = max(0.0, round(tot_amt - new_paid, 2))
            new_bill_status = "PAID" if new_bal <= 0.05 else "PARTIALLY_PAID"
            bill_updates = {
                "bill_id": clean_bill_id,
                "paid_amount": new_paid,
                "balance_amount": new_bal,
                "payment_status": new_bill_status,
                "notes": f"{bill_notes} {alloc_tag}".strip(),
            }

        new_alloc_entry = {
            "bill_id": clean_bill_id,
            "bill_number": str(bill.get("bill_number", "")),
            "amount": apply_amt,
            "allocated_at": now,
            "allocated_by": actor,
            "idempotency_key": clean_idemp_key,
            "notes": (req.notes or "").strip(),
        }
        allocs.append(new_alloc_entry)
        new_allocated = round(float(enriched["allocated_amount"]) + apply_amt, 2)
        new_unallocated = max(0.0, round(float(enriched["amount"]) - new_allocated, 2))
        pay_updates = {
            "payment_id": clean_pay_id,
            "allocated_amount": new_allocated,
            "unallocated_amount": new_unallocated,
            "allocations_json": json.dumps(allocs),
        }

        apps_script_bridge.delegate_governed_write(
            action="APPLY_SUPPLIER_ADVANCE",
            target_tab="SupplierPayments",
            payload={
                "payment_update": pay_updates,
                "bill_update": bill_updates or None,
                "allocation": new_alloc_entry,
            },
            actor_user_id=actor,
            actor_role=actor_role,
            nonce=clean_idemp_key or None,
            request=request,
            id_field="payment_id",
            invalidate_tabs=["SupplierPayments", "SupplierBills"],
        )

        updated_bill = {**bill, **bill_updates} if bill_updates else bill
        updated_pay = _enrich_payment_row({**pay_raw, **pay_updates})

        db.log_audit(
            actor,
            "APPLY_SUPPLIER_ADVANCE",
            "SupplierPayments",
            clean_pay_id,
            reason=f"Applied ₹{apply_amt:.2f} advance from {clean_pay_id} to bill {bill.get('bill_number')} ({clean_bill_id})",
        )
        return {
            "ok": True,
            "payment": updated_pay,
            "bill": updated_bill,
            "applied_amount": apply_amt,
            "remaining_advance": new_unallocated,
            "is_replay": False,
        }


# ============================================================================
# Supplier Returns Endpoints
# ============================================================================

@router.get("/returns")
async def list_supplier_returns(user: dict = Depends(get_current_user)):
    require_purchasing_read(user)
    returns = db.get_records("SupplierReturns", fresh=True)
    items = db.get_records("SupplierReturnItems", fresh=True)
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


@router.post("/returns", dependencies=[Depends(require_sheets_connection)])
async def create_supplier_return(req: SupplierReturnCreate, request: Request, user: dict = Depends(get_current_user)):
    """
    Supplier Return (Debit Note) atomically delegated via Apps Script bridge:
    1. Deducts stock from RawMaterialLedger with movement_type=SUPPLIER_RETURN.
    2. Posts accounting debit note reversing inventory and payable via Apps Script bridge.
    """
    actor, actor_role = require_owner_access(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    now = now_iso()
    today = business_today()
    ret_date = req.return_date or today

    total_return_val = Decimal("0")
    item_rows = []
    ledger_rows = []

    for idx, itm in enumerate(req.items):
        qty_dec = to_decimal(itm.quantity)
        rate_dec = to_decimal(itm.unit_rate)
        val = qty_dec * rate_dec
        total_return_val += val

        ledger_rows.append({
            "line_index": idx,
            "txn_datetime": ret_date,
            "material_name": itm.material_name,
            "raw_material_id": itm.raw_material_id,
            "movement_type": "SUPPLIER_RETURN",
            "quantity": float(round_stock(qty_dec)),
            "unit": itm.unit,
            "rate_per_unit": float(round_money(rate_dec)),
            "production_id": "",
            "created_by": actor,
            "notes": f"Debit Note return to {supp_name}: {itm.reason}",
        })

        item_rows.append({
            "line_index": idx,
            "raw_material_id": itm.raw_material_id,
            "material_name": itm.material_name,
            "quantity": float(round_stock(qty_dec)),
            "unit": itm.unit,
            "unit_rate": float(round_money(rate_dec)),
            "return_amount": float(round_money(val)),
            "reason": itm.reason,
            "notes": (itm.notes or "").strip(),
        })

    ret_record = {
        "receipt_id": req.receipt_id or "",
        "supplier_id": req.supplier_id,
        "supplier_name": supp_name,
        "return_date": ret_date,
        "status": "APPROVED",
        "approved_by": actor,
        "approved_at": now,
        "created_by": actor,
        "created_at": now,
        "notes": (req.notes or "").strip(),
    }

    bridge_res = apps_script_bridge.delegate_governed_write(
        action="CREATE_SUPPLIER_RETURN",
        target_tab="SupplierReturns",
        payload={
            "supplier_return": ret_record,
            "items": item_rows,
            "raw_material_ledger_rows": ledger_rows,
        },
        actor_user_id=actor,
        actor_role=actor_role,
        request=request,
        id_field="return_id",
        invalidate_tabs=["SupplierReturns", "SupplierReturnItems", "RawMaterialLedger"],
    )
    return_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("return_id") or "")
    saved_ret = bridge_res.get("record") or {**ret_record, "return_id": return_id}
    ret_num = str(saved_ret.get("return_number") or return_id)

    ret_dict = {
        "return_id": return_id,
        "return_amount": float(total_return_val),
        "supplier_name": supp_name,
        "material_name": item_rows[0]["material_name"] if item_rows else "Material",
        "tax_amount": float(total_return_val * Decimal("0.05")),
        "return_date": ret_date,
    }
    post_supplier_return_journal(ret_dict, actor=actor)

    db.log_audit(actor, "CREATE_SUPPLIER_RETURN", "SupplierReturns", return_id, reason=f"Debit note {ret_num} to {supp_name} for ₹{float(total_return_val):.2f}")
    return {**saved_ret, "items": item_rows}


# ============================================================================
# Purchasing Summary
# ============================================================================

@router.get("/summary")
async def purchasing_summary(user: dict = Depends(get_current_user)):
    require_purchasing_read(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    orders = db.get_records("PurchaseOrders", fresh=True)
    receipts = db.get_records("GoodsReceipts", fresh=True)
    bills = db.get_records("SupplierBills", fresh=True)
    payments = db.get_records("SupplierPayments", fresh=True)

    total_suppliers = len(suppliers)
    open_orders = sum(1 for po in orders if str(po.get("status", "")).upper() in {"APPROVED", "PENDING"})
    unpaid_bills = [b for b in bills if str(b.get("payment_status", "")).upper() != "PAID"]
    total_billed = round(sum(float(b.get("total_amount", 0) or 0) for b in bills), 2)
    bill_paid_total = round(sum(float(b.get("paid_amount", 0) or 0) for b in bills), 2)
    bill_balance_total = round(sum(float(b.get("balance_amount", 0) or 0) for b in unpaid_bills), 2)

    paid_payments = [_enrich_payment_row(p) for p in payments if str(p.get("status", "")).strip().upper() == "PAID"]
    total_advances = round(sum(float(p.get("unallocated_amount", 0) or 0) for p in paid_payments), 2)
    total_paid = round(bill_paid_total + total_advances, 2)
    net_payable = max(0.0, round(bill_balance_total - total_advances, 2))

    return {
        "total_suppliers": total_suppliers,
        "open_orders_count": open_orders,
        "open_pos": open_orders,
        "total_receipts_count": len(receipts),
        "unpaid_bills_count": len(unpaid_bills),
        "unpaid_bills": len(unpaid_bills),
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_advances": total_advances,
        "total_accounts_payable": net_payable,
        "total_payables": net_payable,
        "net_payable": net_payable,
    }
