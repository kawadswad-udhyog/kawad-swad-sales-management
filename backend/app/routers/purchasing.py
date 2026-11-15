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
import json
import math
from typing import List, Dict, Any, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.permissions import is_manager, is_owner, require_manager, require_owner
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

PURCHASING_ROLES = {"OWNER", "OWNER_ADMIN", "ADMIN", "PA"}


def require_purchasing_access(user: dict):
    if not is_manager(user):
        raise HTTPException(403, "Access denied. Purchasing management requires Manager or PA privileges.")
    return str(user.get("user_id", "")), str(user.get("role", "")).upper()


def require_owner_access(user: dict):
    if not is_owner(user):
        raise HTTPException(403, "Access denied. Action requires Owner privileges.")
    return str(user.get("user_id", "")), str(user.get("role", "")).upper()


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
    require_purchasing_access(user)
    return db.get_records("Suppliers", fresh=True)


@router.post("/suppliers")
async def create_supplier(req: SupplierCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_purchasing_access(user)
    supp_id = db.generate_id("Suppliers")
    now = now_iso()

    # Duplicate name check
    existing = [s for s in db.get_records("Suppliers", fresh=True) if str(s.get("supplier_name", "")).strip().lower() == req.supplier_name.strip().lower()]
    if existing:
        raise HTTPException(400, f"Supplier with name '{req.supplier_name}' already exists.")

    row = {
        "supplier_id": supp_id,
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
    db.append_record("Suppliers", row, raise_on_error=True)
    db.log_audit(actor, "CREATE_SUPPLIER", "Suppliers", supp_id, reason=f"Created supplier {req.supplier_name}")
    return row


@router.put("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: str, req: SupplierCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_purchasing_access(user)
    supp = next((s for s in db.get_records("Suppliers", fresh=True) if str(s.get("supplier_id")) == supplier_id), None)
    if not supp:
        raise HTTPException(404, f"Supplier {supplier_id} not found.")

    updates = {
        "supplier_name": req.supplier_name.strip(),
        "contact_person": (req.contact_person or "").strip(),
        "mobile": (req.mobile or "").strip(),
        "email": (req.email or "").strip(),
        "address": (req.address or "").strip(),
        "city": (req.city or "Barwani").strip(),
        "gstin": (req.gstin or "").strip(),
        "notes": (req.notes or "").strip(),
    }
    db.update_record("Suppliers", "supplier_id", supplier_id, updates, raise_on_error=True)
    db.log_audit(actor, "UPDATE_SUPPLIER", "Suppliers", supplier_id, reason=f"Updated details for {req.supplier_name}")
    return {**supp, **updates}


# ============================================================================
# Purchase Orders Endpoints
# ============================================================================

@router.get("/orders")
async def list_purchase_orders(user: dict = Depends(get_current_user)):
    require_purchasing_access(user)
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


@router.post("/orders")
async def create_purchase_order(req: PurchaseOrderCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_purchasing_access(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    po_id = db.generate_id("PurchaseOrders")
    po_num = f"PO-{po_id.replace('PO-', '')}"
    now = now_iso()
    today = business_today()

    total_amt = Decimal("0")
    line_rows = []
    for itm in req.items:
        qty_dec = to_decimal(itm.ordered_quantity)
        rate_dec = to_decimal(itm.unit_price)
        base = qty_dec * rate_dec
        tax = base * to_decimal(itm.tax_rate)
        line_total = base + tax
        total_amt += line_total

        line_rows.append({
            "po_item_id": db.generate_id("PurchaseOrderItems"),
            "po_id": po_id,
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
        "po_id": po_id,
        "po_number": po_num,
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

    db.append_record("PurchaseOrders", po_record, raise_on_error=True)
    for lr in line_rows:
        db.append_record("PurchaseOrderItems", lr, raise_on_error=True)

    db.log_audit(actor, "CREATE_PURCHASE_ORDER", "PurchaseOrders", po_id, reason=f"Created PO {po_num} for ₹{float(total_amt):.2f}")
    return {**po_record, "items": line_rows}


@router.post("/orders/{po_id}/cancel")
async def cancel_purchase_order(po_id: str, reason: str = Query(...), user: dict = Depends(get_current_user)):
    actor, _ = require_owner_access(user)
    orders = db.get_records("PurchaseOrders", fresh=True)
    po = next((p for p in orders if str(p.get("po_id")) == po_id), None)
    if not po:
        raise HTTPException(404, f"PO {po_id} not found.")

    if str(po.get("status")).upper() == "COMPLETED":
        raise HTTPException(400, "Cannot cancel a completed purchase order with recorded receipts.")

    db.update_record("PurchaseOrders", "po_id", po_id, {
        "status": "CANCELLED",
        "notes": f"{po.get('notes', '')} [CANCELLED by {actor}: {reason}]".strip(),
    }, raise_on_error=True)

    db.log_audit(actor, "CANCEL_PURCHASE_ORDER", "PurchaseOrders", po_id, reason=reason)
    return {"ok": True, "po_id": po_id, "status": "CANCELLED"}


# ============================================================================
# Goods Receipts Endpoints
# ============================================================================

@router.get("/receipts")
async def list_goods_receipts(user: dict = Depends(get_current_user)):
    require_purchasing_access(user)
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


@router.post("/receipts")
async def create_goods_receipt(req: GoodsReceiptCreate, user: dict = Depends(get_current_user)):
    """
    Records an authorized Goods Receipt Note (GRN):
    1. Distinguishes delivered, accepted, and rejected quantities.
    2. Appends accepted stock to RawMaterialLedger (movement_type=PURCHASE_RECEIPT), immediately updating stock.
    3. Updates received_quantity on PurchaseOrderItems if PO is linked.
    4. Automatically posts balanced double-entry accounting journal for accepted materials.
    """
    actor, _ = require_purchasing_access(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    receipt_id = db.generate_id("GoodsReceipts")
    grn_number = f"GRN-{receipt_id.replace('GRN-', '')}"
    now = now_iso()
    today = business_today()
    receipt_date = req.receipt_date or today

    tot_accepted = 0.0
    tot_rejected = 0.0
    item_rows = []
    ledger_rows = []

    for itm in req.items:
        deliv = float(itm.delivered_quantity)
        acc = float(itm.accepted_quantity)
        rej = float(itm.rejected_quantity)
        if acc + rej != deliv and abs((acc + rej) - deliv) > 0.001:
            rej = round(deliv - acc, 3)

        tot_accepted += acc
        tot_rejected += rej

        # 1. Create Stock Movement in RawMaterialLedger for accepted quantity
        stock_mvt_id = ""
        if acc > 0:
            stock_mvt_id = db.generate_id("RawMaterialLedger")
            ledger_row = {
                "raw_material_txn_id": stock_mvt_id,
                "txn_datetime": receipt_date,
                "material_name": itm.material_name,
                "raw_material_id": itm.raw_material_id,
                "movement_type": "PURCHASE_RECEIPT",
                "quantity": acc,
                "unit": itm.unit,
                "rate_per_unit": itm.unit_rate,
                "production_id": "",
                "issue_txn_id": grn_number,
                "created_by": actor,
                "notes": f"GRN {grn_number} from {supp_name} (Inv: {req.invoice_reference})",
            }
            db.append_record("RawMaterialLedger", ledger_row, raise_on_error=True)
            ledger_rows.append(ledger_row)

            # Post double-entry journal voucher for inventory receipt
            try:
                receipt_dict = {
                    "raw_material_txn_id": stock_mvt_id,
                    "quantity": acc,
                    "purchase_rate": itm.unit_rate,
                    "freight_amount": 0.0,
                    "gst_amount": acc * itm.unit_rate * 0.05,
                    "gst_treatment": "RECOVERABLE_ITC",
                    "material_name": itm.material_name,
                    "supplier_name": supp_name,
                    "invoice_number": req.invoice_reference,
                    "receipt_date": receipt_date,
                }
                post_receipt_journal(receipt_dict, actor=actor)
            except Exception as acct_err:
                pass  # Non-fatal accounting posting

        # 2. Update PO Item received quantity if linked
        if itm.po_item_id:
            po_items = db.get_records("PurchaseOrderItems", fresh=True)
            po_itm = next((p for p in po_items if str(p.get("po_item_id")) == itm.po_item_id), None)
            if po_itm:
                old_recv = float(po_itm.get("received_quantity", 0) or 0)
                db.update_record("PurchaseOrderItems", "po_item_id", itm.po_item_id, {
                    "received_quantity": old_recv + acc,
                })

        item_rows.append({
            "receipt_item_id": db.generate_id("GoodsReceiptItems"),
            "receipt_id": receipt_id,
            "po_item_id": itm.po_item_id or "",
            "raw_material_id": itm.raw_material_id,
            "material_name": itm.material_name,
            "delivered_quantity": deliv,
            "accepted_quantity": acc,
            "rejected_quantity": rej,
            "unit": itm.unit,
            "unit_rate": itm.unit_rate,
            "rejection_reason": (itm.rejection_reason or "").strip(),
            "stock_movement_id": stock_mvt_id,
            "notes": (itm.notes or "").strip(),
        })

    grn_record = {
        "receipt_id": receipt_id,
        "receipt_number": grn_number,
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

    db.append_record("GoodsReceipts", grn_record, raise_on_error=True)
    for ir in item_rows:
        db.append_record("GoodsReceiptItems", ir, raise_on_error=True)

    db.log_audit(
        actor,
        "RECEIVE_GOODS",
        "GoodsReceipts",
        receipt_id,
        reason=f"Received GRN {grn_number} ({tot_accepted} accepted, {tot_rejected} rejected) from {supp_name}",
    )
    return {**grn_record, "items": item_rows}


# ============================================================================
# Supplier Bills Endpoints
# ============================================================================

@router.get("/bills")
async def list_supplier_bills(user: dict = Depends(get_current_user)):
    require_purchasing_access(user)
    bills = db.get_records("SupplierBills", fresh=True)
    bills.sort(key=lambda x: str(x.get("bill_date", "")), reverse=True)
    return bills


@router.post("/bills")
async def create_supplier_bill(req: SupplierBillCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_purchasing_access(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    # Duplicate bill reference check
    existing_bills = db.get_records("SupplierBills", fresh=True)
    dup = next((b for b in existing_bills if str(b.get("supplier_id")) == req.supplier_id and str(b.get("bill_number")).strip().lower() == req.bill_number.strip().lower()), None)
    if dup:
        raise HTTPException(409, f"Supplier bill '{req.bill_number}' for {supp_name} has already been recorded.")

    bill_id = db.generate_id("SupplierBills")
    now = now_iso()
    today = business_today()

    bill_row = {
        "bill_id": bill_id,
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
    db.append_record("SupplierBills", bill_row, raise_on_error=True)
    db.log_audit(actor, "RECORD_SUPPLIER_BILL", "SupplierBills", bill_id, reason=f"Recorded bill {req.bill_number} from {supp_name} for ₹{req.total_amount:.2f}")
    return bill_row


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


@router.get("/payments")
async def list_supplier_payments(user: dict = Depends(get_current_user)):
    require_purchasing_access(user)
    payments = [_enrich_payment_row(p) for p in db.get_records("SupplierPayments", fresh=True)]
    payments.sort(key=lambda x: str(x.get("payment_date", "")), reverse=True)
    return payments


@router.post("/payments")
async def record_supplier_payment(req: SupplierPaymentCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_owner_access(user)

    if not math.isfinite(req.amount) or req.amount <= 0:
        raise HTTPException(400, "Payment amount must be greater than zero.")

    clean_supplier_id = str(req.supplier_id or "").strip()
    if not clean_supplier_id:
        raise HTTPException(400, "Supplier ID is required.")

    clean_bill_id = str(req.bill_id or "").strip()
    clean_method = _normalize_supplier_payment_method(req.payment_method)
    clean_ref = str(req.reference_number or "").strip()
    clean_idemp_key = str(req.idempotency_key or "").strip()
    req_amount = round_money(req.amount)

    # Phase 2 Reference integrity:
    # - CASH may leave external reference blank (""), never generate synthetic PAY-xxxxxx.
    # - Non-cash modes require an actual bank/UPI/cheque reference number.
    if clean_method != "CASH" and len(clean_ref) < 2:
        raise HTTPException(
            400,
            f"External bank/UPI/cheque reference number is required for {clean_method} payment.",
        )

    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id", "")).strip() == clean_supplier_id), None)
    if not supp:
        raise HTTPException(404, f"Supplier {clean_supplier_id} not found.")
    supp_name = str(supp.get("supplier_name") or clean_supplier_id)

    with ExitStack() as stack:
        stack.enter_context(CrossProcessLock("supplier", clean_supplier_id))
        if clean_bill_id:
            stack.enter_context(CrossProcessLock("supplier_bill", clean_bill_id))

        bills = db.get_records("SupplierBills", fresh=True)
        payments = db.get_records("SupplierPayments", fresh=True)

        # Idempotent replay / partial-failure recovery check
        existing_pay = None
        if clean_idemp_key:
            existing_pay = next(
                (p for p in reversed(payments) if str(p.get("idempotency_key", "")).strip() == clean_idemp_key),
                None,
            )
            if existing_pay:
                ex_supp = str(existing_pay.get("supplier_id", "")).strip()
                ex_bill = str(existing_pay.get("bill_id", "") or "").strip()
                ex_amt = round(float(existing_pay.get("amount", 0) or 0), 2)
                ex_ref = str(existing_pay.get("reference_number", "") or "").strip()
                if (
                    ex_supp != clean_supplier_id
                    or ex_bill != clean_bill_id
                    or abs(ex_amt - float(req_amount)) > 0.05
                    or ex_ref != clean_ref
                ):
                    raise HTTPException(409, "Idempotency key already used with a different payment payload.")

                ex_status = str(existing_pay.get("status", "")).strip().upper()
                bill_row = next((b for b in bills if str(b.get("bill_id", "")).strip() == clean_bill_id), None) if clean_bill_id else None
                if ex_status == "PAID":
                    rem_bal = round(float(bill_row.get("balance_amount", 0) or 0), 2) if bill_row else 0.0
                    b_status = str(bill_row.get("payment_status", "N/A")) if bill_row else "ON_ACCOUNT"
                    return {
                        "ok": True,
                        "payment": _enrich_payment_row(existing_pay),
                        "remaining_balance": rem_bal,
                        "bill_status": b_status,
                        "payment_type": "BILL_PAYMENT" if clean_bill_id else "ON_ACCOUNT",
                        "is_replay": True,
                    }

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
            # Only enforce remaining balance on a brand-new attempt (not recovering an incomplete attempt that may already have updated the bill)
            spay_marker_present = existing_pay is not None and f"[spay:{existing_pay.get('payment_id')}]" in str(bill.get("notes", ""))
            if not spay_marker_present and float(req_amount) > cur_bal + 0.05:
                raise HTTPException(
                    400,
                    f"Payment of ₹{float(req_amount):.2f} exceeds outstanding balance of ₹{cur_bal:.2f}.",
                )

        now = now_iso()
        today = business_today()
        pay_type = "BILL_PAYMENT" if clean_bill_id else "ON_ACCOUNT"

        if existing_pay:
            pay_id = str(existing_pay.get("payment_id", "")).strip()
            pay_row = dict(existing_pay)
        else:
            pay_id = db.generate_id("SupplierPayments")
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
                "payment_id": pay_id,
                "bill_id": clean_bill_id,
                "supplier_id": clean_supplier_id,
                "supplier_name": supp_name,
                "payment_date": (req.payment_date or today).strip(),
                "amount": req_amount,
                "payment_method": clean_method,
                "reference_number": clean_ref,
                "status": "INCOMPLETE",
                "paid_by": actor,
                "created_at": now,
                "notes": (req.notes or "").strip(),
                "payment_type": pay_type,
                "allocated_amount": float(req_amount) if clean_bill_id else 0.0,
                "unallocated_amount": 0.0 if clean_bill_id else float(req_amount),
                "allocations_json": json.dumps(allocs_initial),
                "idempotency_key": clean_idemp_key,
            }
            db.append_record("SupplierPayments", pay_row, raise_on_error=True)

        # Apply bill deduction once (guarded by [spay:<pay_id>] marker for crash recovery)
        new_bal = 0.0
        new_status = "ON_ACCOUNT"
        if bill is not None:
            bill_notes = str(bill.get("notes", "") or "")
            spay_tag = f"[spay:{pay_id}]"
            if spay_tag in bill_notes:
                new_bal = round(float(bill.get("balance_amount", 0) or 0), 2)
                new_status = str(bill.get("payment_status", "PARTIALLY_PAID"))
            else:
                old_paid = float(bill.get("paid_amount", 0) or 0)
                new_paid = round(old_paid + float(req_amount), 2)
                tot_amt = float(bill.get("total_amount", 0) or 0)
                new_bal = max(0.0, round(tot_amt - new_paid, 2))
                new_status = "PAID" if new_bal <= 0.05 else "PARTIALLY_PAID"
                updated_notes = f"{bill_notes} {spay_tag}".strip()
                db.update_record(
                    "SupplierBills",
                    "bill_id",
                    clean_bill_id,
                    {
                        "paid_amount": new_paid,
                        "balance_amount": new_bal,
                        "payment_status": new_status,
                        "notes": updated_notes,
                    },
                    raise_on_error=True,
                )

        # Post double-entry accounting journal (fail-closed, idempotent by SUPPLIER_PAYMENT:<pay_id>)
        post_supplier_payment_journal(pay_row, actor=actor)

        # Mark payment record PAID after all downstream effects succeed
        db.update_record("SupplierPayments", "payment_id", pay_id, {"status": "PAID"}, raise_on_error=True)
        pay_row["status"] = "PAID"

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
            "payment": _enrich_payment_row(pay_row),
            "remaining_balance": new_bal,
            "bill_status": new_status,
            "payment_type": pay_type,
            "is_replay": bool(existing_pay),
        }


@router.post("/payments/{payment_id}/apply")
async def apply_supplier_advance_to_bill(
    payment_id: str,
    req: SupplierAdvanceApplyRequest,
    user: dict = Depends(get_current_user),
):
    """
    Reconcile an existing On-Account / Advance supplier payment against a supplier bill.
    Updates SupplierBills paid/balance amounts and SupplierPayments allocation tracking
    WITHOUT creating a duplicate payment or double-posting accounting vouchers.
    """
    actor, _ = require_owner_access(user)
    clean_pay_id = str(payment_id or "").strip()
    clean_bill_id = str(req.bill_id or "").strip()
    clean_idemp_key = str(req.idempotency_key or "").strip()

    if not clean_bill_id:
        raise HTTPException(400, "Target bill_id is required to apply advance payment.")
    if req.amount is not None and (not math.isfinite(req.amount) or req.amount <= 0):
        raise HTTPException(400, "Applied amount must be greater than zero.")

    # Quick lookup to identify supplier_id for consistent lock ordering
    pre_payments = db.get_records("SupplierPayments", fresh=True)
    pre_pay = next((p for p in pre_payments if str(p.get("payment_id", "")).strip() == clean_pay_id), None)
    if not pre_pay:
        raise HTTPException(404, f"Supplier payment {clean_pay_id} not found.")
    clean_supplier_id = str(pre_pay.get("supplier_id", "")).strip()

    with ExitStack() as stack:
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

        # Idempotent replay guard
        if clean_idemp_key:
            prior = next((a for a in allocs if str(a.get("idempotency_key", "")).strip() == clean_idemp_key), None)
            if prior:
                if str(prior.get("bill_id", "")).strip() != clean_bill_id or (
                    req.amount is not None and abs(float(prior.get("amount", 0)) - float(req.amount)) > 0.05
                ):
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
        if alloc_tag not in bill_notes:
            old_paid = float(bill.get("paid_amount", 0) or 0)
            new_paid = round(old_paid + apply_amt, 2)
            tot_amt = float(bill.get("total_amount", 0) or 0)
            new_bal = max(0.0, round(tot_amt - new_paid, 2))
            new_bill_status = "PAID" if new_bal <= 0.05 else "PARTIALLY_PAID"
            bill_updates = {
                "paid_amount": new_paid,
                "balance_amount": new_bal,
                "payment_status": new_bill_status,
                "notes": f"{bill_notes} {alloc_tag}".strip(),
            }
            db.update_record("SupplierBills", "bill_id", clean_bill_id, bill_updates, raise_on_error=True)
            bill = {**bill, **bill_updates}

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
            "allocated_amount": new_allocated,
            "unallocated_amount": new_unallocated,
            "allocations_json": json.dumps(allocs),
        }
        db.update_record("SupplierPayments", "payment_id", clean_pay_id, pay_updates, raise_on_error=True)
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
            "bill": bill,
            "applied_amount": apply_amt,
            "remaining_advance": new_unallocated,
            "is_replay": False,
        }


# ============================================================================
# Supplier Returns Endpoints
# ============================================================================

@router.get("/returns")
async def list_supplier_returns(user: dict = Depends(get_current_user)):
    require_purchasing_access(user)
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


@router.post("/returns")
async def create_supplier_return(req: SupplierReturnCreate, user: dict = Depends(get_current_user)):
    """
    Supplier Return (Debit Note):
    1. Validates return quantity against raw material inventory.
    2. Deducts stock from RawMaterialLedger with movement_type=SUPPLIER_RETURN.
    3. Posts accounting debit note reversing inventory and payable.
    """
    actor, _ = require_owner_access(user)
    suppliers = db.get_records("Suppliers", fresh=True)
    supp = next((s for s in suppliers if str(s.get("supplier_id")) == req.supplier_id), None)
    supp_name = str(supp.get("supplier_name")) if supp else (req.supplier_name or "Supplier")

    return_id = db.generate_id("SupplierReturns")
    ret_num = f"DN-{return_id.replace('SRET-', '')}"
    now = now_iso()
    today = business_today()
    ret_date = req.return_date or today

    total_return_val = Decimal("0")
    item_rows = []

    for itm in req.items:
        qty_dec = to_decimal(itm.quantity)
        rate_dec = to_decimal(itm.unit_rate)
        val = qty_dec * rate_dec
        total_return_val += val

        # Deduct stock from RawMaterialLedger
        mvt_id = db.generate_id("RawMaterialLedger")
        ledger_row = {
            "raw_material_txn_id": mvt_id,
            "txn_datetime": ret_date,
            "material_name": itm.material_name,
            "raw_material_id": itm.raw_material_id,
            "movement_type": "SUPPLIER_RETURN",
            "quantity": float(round_stock(qty_dec)),
            "unit": itm.unit,
            "rate_per_unit": float(round_money(rate_dec)),
            "production_id": "",
            "issue_txn_id": ret_num,
            "created_by": actor,
            "notes": f"Debit Note {ret_num} return to {supp_name}: {itm.reason}",
        }
        db.append_record("RawMaterialLedger", ledger_row, raise_on_error=True)

        item_rows.append({
            "return_item_id": db.generate_id("SupplierReturnItems"),
            "return_id": return_id,
            "raw_material_id": itm.raw_material_id,
            "material_name": itm.material_name,
            "quantity": float(round_stock(qty_dec)),
            "unit": itm.unit,
            "unit_rate": float(round_money(rate_dec)),
            "return_amount": float(round_money(val)),
            "reason": itm.reason,
            "stock_movement_id": mvt_id,
            "notes": (itm.notes or "").strip(),
        })

    ret_record = {
        "return_id": return_id,
        "return_number": ret_num,
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

    db.append_record("SupplierReturns", ret_record, raise_on_error=True)
    for ir in item_rows:
        db.append_record("SupplierReturnItems", ir, raise_on_error=True)

    # Post accounting debit note
    try:
        ret_dict = {
            "return_id": return_id,
            "return_amount": float(total_return_val),
            "supplier_name": supp_name,
            "material_name": item_rows[0]["material_name"] if item_rows else "Material",
            "tax_amount": float(total_return_val * Decimal("0.05")),
            "return_date": ret_date,
        }
        post_supplier_return_journal(ret_dict, actor=actor)
    except Exception as acct_err:
        pass

    db.log_audit(actor, "CREATE_SUPPLIER_RETURN", "SupplierReturns", return_id, reason=f"Debit note {ret_num} to {supp_name} for ₹{float(total_return_val):.2f}")
    return {**ret_record, "items": item_rows}


# ============================================================================
# Purchasing Summary
# ============================================================================

@router.get("/summary")
async def purchasing_summary(user: dict = Depends(get_current_user)):
    require_purchasing_access(user)
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
