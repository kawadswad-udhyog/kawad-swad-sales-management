import asyncio
import logging
import math
import re
import threading
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, status, Depends
from pydantic import BaseModel

from app.apps_script_bridge import apps_script_bridge
from app.models import Sale, SaleCreate, SaleItem, SalePaymentCreate
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager, is_salesman, require_roles, role_v2_of
from app.stock_math import salesman_available
from app.timeutil import now_iso
from app.accounting.customer_ledger import (
    get_customer_credit_lock,
    get_approval_lock,
    CrossProcessLock,
)

logger = logging.getLogger("kawad_swad.sales")
router = APIRouter(prefix="/api/sales", tags=["Sales"])

SALES_READ_ALL_ROLES = {"OWNER_ADMIN", "PA", "ACCOUNTS", "SALES", "AUDITOR"}
SALES_READ_ROLES = SALES_READ_ALL_ROLES | {"FIELD_SALESMAN"}
SALES_WRITE_ROLES = {"OWNER_ADMIN", "PA", "SALES", "FIELD_SALESMAN"}
SALES_PAYMENT_ROLES = {"OWNER_ADMIN", "PA", "ACCOUNTS", "SALES", "FIELD_SALESMAN"}


def _reject_auditor(user: dict) -> None:
    if role_v2_of(user) == "AUDITOR":
        raise HTTPException(status_code=403, detail="AUDITOR role is strictly read-only.")


def _can_view_all_sales(user: dict) -> bool:
    return is_manager(user) or role_v2_of(user) in SALES_READ_ALL_ROLES
class UniversalSalesLock:
    """
    Universal thread and async lock.
    Unlike standard asyncio.Lock, this does NOT bind to a single event loop,
    making it completely safe across multiple asyncio.run() calls, multiple threads,
    and distinct worker processes.
    """
    def __init__(self):
        self._thread_lock = threading.RLock()

    async def __aenter__(self):
        self._thread_lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._thread_lock.release()

    def __enter__(self):
        self._thread_lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._thread_lock.release()

_sales_lock = UniversalSalesLock()
_SALES_THREAD_LOCK = _sales_lock._thread_lock
_IDEMP_LOCKS: Dict[str, threading.RLock] = {}
_IDEMP_LOCKS_GUARD = threading.Lock()

def get_idempotency_lock(key: str) -> threading.RLock:
    clean_k = str(key or "").strip()
    with _IDEMP_LOCKS_GUARD:
        if clean_k not in _IDEMP_LOCKS:
            _IDEMP_LOCKS[clean_k] = threading.RLock()
        return _IDEMP_LOCKS[clean_k]

_MONEY = 0.05


def _clean(value) -> str:
    text = str(value or "").strip()
    if text.lower() in {"none", "null", "undefined"}:
        return ""
    return text


def _money(value) -> float:
    return round(float(value or 0), 2)


def _find_sale_by_key(sales: List[dict], key: str) -> Optional[dict]:
    for row in reversed(sales):
        stored = _clean(row.get("idempotency_key"))
        notes = str(row.get("notes", ""))
        if stored == key or f"[idemp:{key}]" in notes:
            return row
    return None


def _items_for(sale_id: str) -> List[dict]:
    return [row for row in db.get_records("SaleItems", fresh=True) if str(row.get("sale_id")) == sale_id]


def _payments_for(sale_id: str) -> List[dict]:
    return [row for row in db.get_records("Payments", fresh=True) if str(row.get("sale_id")) == sale_id]


def _stock_for(sale_id: str) -> List[dict]:
    return [
        row for row in db.get_records("SalesmanStockLedger", fresh=True)
        if str(row.get("related_sale_id")) == sale_id and str(row.get("txn_type", "")).upper() in {"SOLD_DELIVERY", "SALE_DELIVERY"}
    ]


def _cash_for(sale_id: str) -> List[dict]:
    return [
        row for row in db.get_records("CashLedger", fresh=True)
        if str(row.get("related_sale_id")) == sale_id and str(row.get("txn_type", "")).upper() == "SALE_COLLECTION"
    ]


def _to_item(row: dict) -> SaleItem:
    return SaleItem(
        sale_item_id=str(row.get("sale_item_id", "")),
        sale_id=str(row.get("sale_id", "")),
        product_id=str(row.get("product_id", "")),
        product_name_snapshot=str(row.get("product_name_snapshot", "")),
        sku_snapshot=str(row.get("sku_snapshot", "")),
        pack_weight_g=int(float(row.get("pack_weight_g", 500) or 500)),
        unit=str(row.get("unit", "PACKET")),
        quantity=int(float(row.get("quantity", 1) or 1)),
        actual_unit_price=float(row.get("actual_unit_price", 0) or 0),
        discount_amount=float(row.get("discount_amount", 0) or 0),
        line_total=float(row.get("line_total", 0) or 0),
        qualifying_kg=float(row.get("qualifying_kg", 0) or 0),
        created_at=str(row.get("created_at", "")),
        notes=_clean(row.get("notes")),
    )


def _to_sale(row: dict, items: List[SaleItem], key: str = "") -> Sale:
    notes = re.sub(r"\[idemp:[^\]]+\]\s*", "", str(row.get("notes", ""))).strip()
    notes = re.sub(r"\[txn:[^\]]+\]\s*", "", notes).strip()
    payment = _payments_for(str(row.get("sale_id", "")))
    method = _clean(row.get("payment_method")) or (str(payment[0].get("payment_method", "")) if payment else "")
    reference = _clean(row.get("payment_reference"))
    if payment and not reference:
        reference = _clean(payment[0].get("reference_number"))
        if reference == str(row.get("bill_number", "")):
            reference = _clean(payment[0].get("notes")) if "ref:" in str(payment[0].get("notes", "")) else reference
    bill_total_val = float(row.get("bill_total", 0) or 0)
    cash_coll = float(row.get("cash_collected", 0) if row.get("cash_collected") is not None else (bill_total_val if method != "CREDIT" else 0.0))
    cred_amt = float(row.get("credit_amount", 0) if row.get("credit_amount") is not None else (0.0 if method != "CREDIT" else bill_total_val))
    return Sale(
        sale_id=str(row.get("sale_id", "")),
        bill_number=str(row.get("bill_number", "")),
        idempotency_key=key or _clean(row.get("idempotency_key")),
        sale_datetime=str(row.get("sale_datetime", "")),
        sales_type=str(row.get("sales_type", "Retailer Sale")),
        customer_id=_clean(row.get("customer_id")) or "CUS-WALKIN",
        customer_name_snapshot=_clean(row.get("customer_name_snapshot")) or "Walk-in Customer",
        customer_mobile=_clean(row.get("customer_mobile")),
        customer_gstin=_clean(row.get("customer_gstin")),
        entered_by_user_id=str(row.get("entered_by_user_id", "")),
        salesman_user_id=str(row.get("salesman_user_id", "")),
        delivery_status=str(row.get("delivery_status", "DELIVERED")),
        payment_status=str(row.get("payment_status", "PAID")),
        subtotal=float(row.get("subtotal", 0) or 0),
        discount_amount=float(row.get("discount_amount", 0) or 0),
        tax_amount=float(row.get("tax_amount", 0) or 0),
        bill_total=bill_total_val,
        bill_status=str(row.get("bill_status", "ISSUED")),
        created_at=str(row.get("created_at", "")),
        notes=_clean(notes),
        items=items,
        txn_status=str(row.get("txn_status", "COMPLETE") or "COMPLETE"),
        payment_method=method,
        payment_reference=reference if reference != str(row.get("bill_number", "")) else _clean(row.get("payment_reference")),
        lines=items,
        total_amount=bill_total_val,
        cash_collected=cash_coll,
        credit_amount=cred_amt,
    )


def _sale_is_complete(sale_id: str, line_count: int, payment_method: str, is_unpaid: bool = False, is_cash: bool = True) -> bool:
    if len(_items_for(sale_id)) < line_count:
        return False
    if len(_stock_for(sale_id)) < line_count:
        return False
    if not is_unpaid and not _payments_for(sale_id):
        return False
    if is_cash and not _cash_for(sale_id):
        return False
    return True


def _compute_authoritative_cogs(validated: list):
    from decimal import Decimal
    from app.calculations.costing import get_sku_finished_cost
    from app.calculations.units import to_decimal, round_money

    products = {}
    for p in db.get_records("Products", fresh=True):
        if p.get("product_id"):
            products[str(p.get("product_id")).strip()] = p
        if p.get("sku"):
            products[str(p.get("sku")).strip()] = p

    batches = db.get_records("ProductionBatches", fresh=True)
    recipes = db.get_records("Recipes", fresh=True)
    stock_ledger = db.get_records("ProductionStockLedger", fresh=True)
    rm_master = db.get_records("RawMaterials", fresh=True) or db.get_records("RawMaterialsMaster", fresh=True)

    cogs_total = Decimal("0")
    for item in validated:
        key = str(item.get("product_id") or item.get("sku") or "").strip()
        prod = products.get(key, {})
        qty = to_decimal(item.get("quantity", 0) or 0)
        try:
            sku_cost = get_sku_finished_cost(
                prod,
                production_batches=batches,
                recipes=recipes,
                production_stock_ledger=stock_ledger,
                raw_materials_master=rm_master,
            )
            cogs_total += qty * sku_cost
        except Exception:
            std_cost = prod.get("standard_cost") or prod.get("unit_cost")
            if std_cost:
                cogs_total += qty * to_decimal(std_cost)
            else:
                cogs_total += Decimal("0")
    return round_money(cogs_total)


@router.get("", response_model=List[Sale])
async def list_sales(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, SALES_READ_ROLES)
    user_id = str(current_user.get("user_id", ""))
    can_view_all = _can_view_all_sales(current_user)
    sales_records = db.get_records("Sales")
    items_records = db.get_records("SaleItems")
    payments = db.get_records("Payments")
    pay_by_sale = {}
    for payment in payments:
        pay_by_sale.setdefault(str(payment.get("sale_id", "")), payment)
    items_by_sale = {}
    for row in items_records:
        items_by_sale.setdefault(str(row.get("sale_id", "")), []).append(_to_item(row))
    result = []
    for row in sales_records:
        salesman_id = str(row.get("salesman_user_id", ""))
        if not can_view_all and salesman_id != user_id and str(row.get("entered_by_user_id", "")) != user_id:
            continue
        if str(row.get("txn_status", "COMPLETE")).upper() == "INCOMPLETE":
            continue
        if str(row.get("bill_status", "ISSUED")).upper() == "CANCELLED":
            continue
        sale_id = str(row.get("sale_id", ""))
        if pay_by_sale.get(sale_id) and not row.get("payment_method"):
            row = dict(row)
            row["payment_method"] = pay_by_sale[sale_id].get("payment_method", "")
            row["payment_reference"] = pay_by_sale[sale_id].get("reference_number", "")
        result.append(_to_sale(row, items_by_sale.get(sale_id, [])))
    return result


@router.get("/payments")
async def list_payments(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, SALES_READ_ROLES)
    user_id = str(current_user.get("user_id", ""))
    can_view_all = _can_view_all_sales(current_user)
    sales = {str(row.get("sale_id")): row for row in db.get_records("Sales")}
    payments = []
    for row in db.get_records("Payments"):
        sale = sales.get(str(row.get("sale_id")), {})
        salesman_id = str(sale.get("salesman_user_id", ""))
        if not can_view_all and salesman_id not in {user_id, ""} and str(sale.get("entered_by_user_id", "")) != user_id:
            continue
        if str(sale.get("txn_status", "COMPLETE")).upper() == "INCOMPLETE":
            continue
        payments.append({
            "payment_id": str(row.get("payment_id", "")),
            "sale_id": str(row.get("sale_id", "")),
            "payment_datetime": str(row.get("payment_datetime", "")),
            "payment_method": str(row.get("payment_method", "CASH")),
            "amount": float(row.get("amount", 0) or 0),
            "reference_number": str(row.get("reference_number", "")),
            "received_by_user_id": str(row.get("received_by_user_id", "")),
            "payment_status": "RECEIVED" if str(row.get("payment_status", "PAID")).upper() in {"PAID", "RECEIVED"} else str(row.get("payment_status", "")),
            "notes": _clean(row.get("notes")),
            "bill_number": str(sale.get("bill_number", "")),
        })
    return payments


@router.post("", response_model=Sale, dependencies=[Depends(require_sheets_connection)])
async def create_sale(req: SaleCreate, request: Request, current_user: dict = Depends(get_current_user)):
    _reject_auditor(current_user)
    actor_role = role_v2_of(current_user)
    user_id = str(current_user.get("user_id") or "")
    requested_salesman = _clean(req.salesman_user_id) or user_id
    if is_salesman(current_user) and requested_salesman != user_id:
        raise HTTPException(status_code=403, detail="A salesman can only record a sale against their own user id.")
    if not is_manager(current_user) and not is_salesman(current_user) and actor_role != "SALES":
        raise HTTPException(status_code=403, detail="You do not have permission to record a sale.")

    raw_items = req.items or req.lines or []
    if not raw_items:
        raise HTTPException(status_code=422, detail="Sale must contain at least one valid product line.")

    clean_key = _clean(req.idempotency_key)
    if req.idempotency_key is not None and not clean_key:
        clean_key = ""
    if clean_key:
        if len(clean_key) > 120:
            raise HTTPException(status_code=422, detail="idempotency_key must not exceed 120 characters.")
        if re.search(r"[\r\n\t]", clean_key):
            raise HTTPException(status_code=422, detail="idempotency_key contains invalid control characters.")

    payment_mode_raw = str(getattr(req, "payment_mode", "") or req.payment_method or "CASH").upper()

    products = {str(p.get("product_id")): p for p in db.get_records("Products", fresh=True)}
    validated = []
    subtotal = 0.0
    demand = {}
    for index, item in enumerate(raw_items):
        product_id = _clean(item.product_id)
        product = products.get(product_id)
        if not product:
            if not product_id:
                raise HTTPException(status_code=422, detail=f"Line {index + 1}: Product selection is mandatory.")
            raise HTTPException(status_code=422, detail=f"Line {index + 1}: product {product_id} does not exist.")
        active = str(product.get("active", "true")).strip().lower()
        if active in {"false", "0", "no", "inactive"}:
            raise HTTPException(status_code=422, detail=f"Line {index + 1}: {product.get('product_name') or product_id} is inactive.")
        if item.quantity is None or int(item.quantity) <= 0:
            raise HTTPException(status_code=422, detail=f"Line {index + 1}: Quantity must be greater than zero.")
        actual_price = item.actual_unit_price if item.actual_unit_price is not None else getattr(item, "unit_price", None)
        if actual_price is None or float(actual_price) < 0:
            raise HTTPException(status_code=422, detail=f"Line {index + 1}: Price cannot be negative.")
        item.actual_unit_price = float(actual_price)
        qty = int(item.quantity)
        price = _money(item.actual_unit_price)
        discount = _money(item.discount_amount or 0)
        if discount < 0 or discount > _money(qty * price):
            raise HTTPException(status_code=422, detail=f"Line {index + 1}: discount cannot exceed the line amount.")
        line_total = _money(qty * price - discount)
        if item.line_total is not None and abs(_money(item.line_total) - line_total) > _MONEY:
            raise HTTPException(status_code=422, detail=f"Line {index + 1}: line total does not match quantity × price − discount. The server total is ₹{line_total:.2f}.")
        pack = int(float(item.pack_weight_g or product.get("pack_weight_g") or 500))
        unit = _clean(item.unit or product.get("selling_unit") or "PACKET") or "PACKET"
        sales_type = _clean(req.sales_type or "Retailer Sale")
        if sales_type.lower() == "retail sale" and pack not in {200, 500, 1000}:
            raise HTTPException(status_code=422, detail="A retail packet sale must use a 200 g, 500 g, or 1000 g pack.")
        qualifying_kg = round((pack * qty) / 1000.0, 3) if "kg" not in unit.lower() else float(qty)
        subtotal = _money(subtotal + line_total)
        demand[product_id] = demand.get(product_id, 0) + qty
        validated.append({
            "line_no": index,
            "product_id": product_id,
            "product_name_snapshot": _clean(item.product_name_snapshot or product.get("product_name") or product_id),
            "sku_snapshot": _clean(item.sku_snapshot or product.get("sku") or product_id),
            "pack_weight_g": pack,
            "unit": unit,
            "quantity": qty,
            "actual_unit_price": price,
            "discount_amount": discount,
            "line_total": line_total,
            "qualifying_kg": qualifying_kg,
            "notes": _clean(item.notes),
        })

    discount_amount = _money(req.discount_amount or 0)
    if discount_amount < 0 or discount_amount > subtotal:
        raise HTTPException(status_code=422, detail="Discount cannot exceed subtotal.")
    tax_amount = _money(req.tax_amount or 0)
    if tax_amount < 0:
        raise HTTPException(status_code=422, detail="Tax amount cannot be negative. GST rates are not configured; do not send a negative adjustment.")
    bill_total = _money(subtotal - discount_amount + tax_amount)
    if req.bill_total is not None and abs(_money(req.bill_total) - bill_total) > _MONEY:
        raise HTTPException(status_code=422, detail=f"Bill total does not match the server calculation of ₹{bill_total:.2f}.")
    if req.subtotal is not None and abs(_money(req.subtotal) - subtotal) > _MONEY:
        raise HTTPException(status_code=422, detail=f"Subtotal does not match the server calculation of ₹{subtotal:.2f}.")

    customer_id = _clean(req.customer_id)
    customer_name = _clean(req.customer_name_snapshot)
    if not customer_id or customer_id in {"WALK-IN", "CUS-WALKIN"}:
        customer_id = "CUS-WALKIN"
        customer_name = customer_name or "Walk-in Customer"
    elif not customer_name:
        match = next((c for c in db.get_records("Customers") if str(c.get("customer_id")) == customer_id), None)
        customer_name = _clean(match.get("shop_name")) if match else "Walk-in Customer"
        customer_name = customer_name or "Walk-in Customer"

    reference = _clean(getattr(req, "payment_reference", "") or "")

    # Authoritative settlement split: cash collected vs credit extended
    req_collected = getattr(req, "cash_collected", None)
    req_credit = getattr(req, "credit_amount", None)

    if req_collected is not None and req_credit is not None:
        cash_collected = _money(float(req_collected))
        credit_amount = _money(float(req_credit))
        if abs(cash_collected + credit_amount - bill_total) > 0.05:
            raise HTTPException(status_code=422, detail=f"Sum of cash_collected (₹{cash_collected:.2f}) and credit_amount (₹{credit_amount:.2f}) does not match bill total (₹{bill_total:.2f}).")
    elif req_collected is not None:
        cash_collected = _money(float(req_collected))
        if cash_collected > bill_total + 0.05:
            raise HTTPException(status_code=422, detail=f"cash_collected (₹{cash_collected:.2f}) cannot exceed bill total (₹{bill_total:.2f}).")
        credit_amount = _money(max(0.0, bill_total - cash_collected))
    elif req_credit is not None:
        credit_amount = _money(float(req_credit))
        if credit_amount > bill_total + 0.05:
            raise HTTPException(status_code=422, detail=f"credit_amount (₹{credit_amount:.2f}) cannot exceed bill total (₹{bill_total:.2f}).")
        cash_collected = _money(max(0.0, bill_total - credit_amount))
    elif payment_mode_raw in {"CREDIT", "UNPAID"}:
        cash_collected = 0.0
        credit_amount = bill_total
    elif payment_mode_raw == "PARTIAL":
        cash_collected = 0.0
        credit_amount = bill_total
    else:
        # Full immediate payment
        cash_collected = bill_total
        credit_amount = 0.0

    # Determine payment method for collected portion
    if cash_collected > 0:
        method = _clean(req.payment_method or "CASH").upper() or "CASH"
        if method in {"CREDIT", "NONE", "UNPAID"}:
            method = "CASH"
        elif method not in {"CASH", "UPI", "BANK_TRANSFER", "OTHER"}:
            method = "CASH"
    else:
        method = "CREDIT"

    # Canonical status calculation from actual receipts
    if cash_collected >= bill_total - 0.01:
        calc_payment_status = "PAID"
    elif cash_collected > 0.0:
        calc_payment_status = "PARTIAL"
    else:
        calc_payment_status = "UNPAID"

    if any(math.isnan(v) or math.isinf(v) for v in [subtotal, discount_amount, tax_amount, bill_total, cash_collected, credit_amount]):
        raise HTTPException(status_code=422, detail="Financial settlement amounts must be finite numbers.")

    approval_id = _clean(getattr(req, "owner_credit_approval_id", None))
    idemp_thread_lock = get_idempotency_lock(clean_key) if clean_key else threading.RLock()
    idemp_xp_lock = CrossProcessLock("idemp", clean_key) if clean_key else CrossProcessLock("noop", "none")
    cus_thread_lock = get_customer_credit_lock(customer_id) if (credit_amount > 0 or approval_id) else threading.RLock()
    cus_xp_lock = CrossProcessLock("customer", customer_id) if (credit_amount > 0 or approval_id) else CrossProcessLock("noop", "none")

    async with _sales_lock:
        with _SALES_THREAD_LOCK, idemp_thread_lock, idemp_xp_lock, cus_thread_lock, cus_xp_lock:
            if clean_key:
                existing = _find_sale_by_key(db.get_records("Sales", fresh=True), clean_key)
                if existing:
                    owner = str(existing.get("salesman_user_id", ""))
                    entered = str(existing.get("entered_by_user_id", ""))
                    if not is_manager(current_user) and user_id not in {owner, entered}:
                        raise HTTPException(status_code=409, detail="This idempotency key already belongs to another user.")
                    sale_id = str(existing.get("sale_id"))
                    existing_status = str(existing.get("payment_status", "")).upper()
                    existing_collected = float(existing.get("cash_collected", 0) or 0)
                    is_unpaid = existing_status == "UNPAID" or existing_collected <= 0
                    is_cash = (str(existing.get("payment_method") or method).upper() == "CASH") and (existing_collected > 0)
                    if _sale_is_complete(sale_id, len(validated), method, is_unpaid=is_unpaid, is_cash=is_cash) or _sale_is_complete(sale_id, len(_items_for(sale_id)) or len(validated), str(existing.get("payment_method") or method).upper(), is_unpaid=is_unpaid, is_cash=is_cash):
                        if str(existing.get("txn_status", "")).upper() != "COMPLETE":
                            app_id_res = _clean(existing.get("owner_credit_approval_id"))
                            if app_id_res:
                                from app.accounting.customer_ledger import consume_credit_approval
                                if not consume_credit_approval(app_id_res, sale_id):
                                    raise HTTPException(status_code=503, detail="The sale rows exist but approval consumption could not be saved. Retry the same request.")
                            apps_script_bridge.delegate_governed_write(
                                action="MARK_SALE_COMPLETE",
                                target_tab="Sales",
                                payload={"sale_id": sale_id, "txn_status": "COMPLETE"},
                                actor_user_id=user_id,
                                actor_role=actor_role,
                                nonce=clean_key or None,
                                request=request,
                                id_field="sale_id",
                                invalidate_tabs=["Sales"],
                            )
                            existing["txn_status"] = "COMPLETE"
                        items = [_to_item(row) for row in _items_for(sale_id)]
                        return _to_sale(existing, items, clean_key)
                    return await _resume_sale(existing, validated, method, reference, bill_total, user_id, actor_role, clean_key, request=request)

            if credit_amount > 0 or approval_id:
                from app.accounting.customer_ledger import check_credit_control
                check_credit_control(
                    customer_id=customer_id,
                    requested_credit=credit_amount,
                    current_user=current_user,
                    approval_request_id=approval_id,
                )

            ledger = db.get_records("SalesmanStockLedger", fresh=True)
            for product_id, qty in demand.items():
                available = salesman_available(ledger, requested_salesman, product_id)
                if qty > available:
                    name = products[product_id].get("product_name") or product_id
                    raise HTTPException(
                        status_code=422,
                        detail=f"Insufficient stock for {name}. Available {available}, requested {qty}. Issue stock to this salesman before billing.",
                    )

            now = now_iso()
            notes = _clean(req.notes)
            if clean_key:
                notes = f"[idemp:{clean_key}] [txn:COMPLETE] {notes}".strip()

            sale_record = {
                "idempotency_key": clean_key,
                "txn_status": "COMPLETE",
                "sale_datetime": now,
                "sales_type": _clean(req.sales_type or "Retailer Sale") or "Retailer Sale",
                "customer_id": customer_id,
                "customer_name_snapshot": customer_name,
                "customer_mobile": _clean(req.customer_mobile),
                "customer_gstin": _clean(req.customer_gstin),
                "entered_by_user_id": user_id,
                "salesman_user_id": requested_salesman,
                "delivery_status": req.delivery_status or "DELIVERED",
                "payment_status": calc_payment_status,
                "payment_method": method,
                "payment_reference": reference,
                "cash_collected": cash_collected,
                "credit_amount": credit_amount,
                "subtotal": subtotal,
                "discount_amount": discount_amount,
                "tax_amount": tax_amount,
                "bill_total": bill_total,
                "bill_status": "ISSUED",
                "created_at": now,
                "notes": notes,
                "owner_credit_approval_id": approval_id or "",
            }
            children_bundle = _build_children_bundle(sale_record, validated, method, reference, user_id, now)
            cogs = _compute_authoritative_cogs(validated)

            bridge_res = apps_script_bridge.delegate_governed_write(
                action="CREATE_SALE",
                target_tab="Sales",
                payload={
                    "sale": sale_record,
                    **children_bundle,
                    "owner_credit_approval_id": approval_id or "",
                    "estimated_cogs": float(cogs),
                },
                actor_user_id=user_id,
                actor_role=actor_role,
                nonce=clean_key or None,
                request=request,
                id_field="sale_id",
                invalidate_tabs=["Sales", "SaleItems", "SalesmanStockLedger", "Payments", "CashLedger", "ApprovalRequests"],
            )
            sale_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("sale_id") or "")
            saved_sale = bridge_res.get("record") or {**sale_record, "sale_id": sale_id}
            bill_number = str(saved_sale.get("bill_number") or sale_id)

            db.log_audit(user_id, "ISSUE_BILL", "Sales", sale_id, reason=f"Issued bill {bill_number} for ₹{bill_total:.2f} to {customer_name}")

            from app.accounting.postings import post_sale_journal
            post_sale_journal(saved_sale, cogs, user_id)

            items = [_to_item(row) for row in _items_for(sale_id)] or [_to_item({**itm, "sale_id": sale_id}) for itm in children_bundle["sale_items"]]
            res_sale = _to_sale(saved_sale, items, clean_key)
            res_sale.total_amount = float(bill_total)
            res_sale.cash_collected = float(cash_collected)
            res_sale.credit_amount = float(credit_amount)
            return res_sale


async def _resume_sale(
    existing: dict,
    validated: list,
    method: str,
    reference: str,
    bill_total: float,
    user_id: str,
    actor_role: str,
    clean_key: str,
    request: Optional[Request] = None,
) -> Sale:
    sale_id = str(existing.get("sale_id"))
    if abs(_money(existing.get("bill_total")) - _money(bill_total)) > _MONEY:
        raise HTTPException(status_code=409, detail="This idempotency key belongs to a different bill total. Start a new bill.")
    now = now_iso()
    children_bundle = _build_children_bundle(
        existing,
        validated,
        method or str(existing.get("payment_method") or "CASH"),
        reference or _clean(existing.get("payment_reference")),
        user_id,
        now,
    )
    approval_id = _clean(existing.get("owner_credit_approval_id"))
    if approval_id:
        from app.accounting.customer_ledger import consume_credit_approval
        if not consume_credit_approval(approval_id, sale_id):
            raise HTTPException(status_code=503, detail=f"Sale {sale_id} recovery blocked because credit approval consumption was not confirmed. Retry.")

    notes = str(existing.get("notes", "")).replace("[txn:INCOMPLETE]", "[txn:COMPLETE]")
    apps_script_bridge.delegate_governed_write(
        action="RESUME_SALE",
        target_tab="Sales",
        payload={
            "sale_id": sale_id,
            "txn_status": "COMPLETE",
            "notes": notes,
            **children_bundle,
        },
        actor_user_id=user_id,
        actor_role=actor_role,
        nonce=clean_key or None,
        request=request,
        id_field="sale_id",
        invalidate_tabs=["Sales", "SaleItems", "SalesmanStockLedger", "Payments", "CashLedger"],
    )
    existing["txn_status"] = "COMPLETE"
    db.log_audit(user_id, "RECOVER_BILL", "Sales", sale_id, reason="Completed missing sale rows on retry via Apps Script bridge")

    from app.accounting.postings import post_sale_journal
    cogs = _compute_authoritative_cogs(validated)
    post_sale_journal(existing, cogs, user_id)

    return _to_sale(existing, [_to_item(row) for row in _items_for(sale_id)], clean_key)


def _build_children_bundle(sale: dict, validated: list, method: str, reference: str, user_id: str, now: str) -> dict:
    sale_id = str(sale.get("sale_id") or "")
    bill_number = str(sale.get("bill_number") or "")
    salesman_id = str(sale.get("salesman_user_id") or "")
    existing_items = _items_for(sale_id) if sale_id else []
    existing_stock = _stock_for(sale_id) if sale_id else []

    sale_items = []
    stock_ledger_rows = []
    for line in validated:
        marker = f"[line:{line['line_no']}]"
        if not any(marker in str(row.get("notes", "")) for row in existing_items):
            sale_items.append({
                "line_no": line["line_no"],
                "sale_id": sale_id,
                "product_id": line["product_id"],
                "product_name_snapshot": line["product_name_snapshot"],
                "sku_snapshot": line["sku_snapshot"],
                "pack_weight_g": line["pack_weight_g"],
                "unit": line["unit"],
                "quantity": line["quantity"],
                "actual_unit_price": line["actual_unit_price"],
                "discount_amount": line["discount_amount"],
                "line_total": line["line_total"],
                "qualifying_kg": line["qualifying_kg"],
                "created_at": now,
                "notes": f"{marker} {line['notes']}".strip(),
            })
        if not any(marker in str(row.get("notes", "")) or (bill_number and str(row.get("reference_id")) == f"{bill_number}#{line['line_no']}") for row in existing_stock):
            stock_ledger_rows.append({
                "line_no": line["line_no"],
                "txn_datetime": now,
                "salesman_user_id": salesman_id,
                "product_id": line["product_id"],
                "sku_snapshot": line["sku_snapshot"],
                "txn_type": "SOLD_DELIVERY",
                "quantity": -line["quantity"],
                "unit": line["unit"],
                "pack_weight_g": line["pack_weight_g"],
                "related_sale_id": sale_id,
                "issued_by_user_id": user_id,
                "received_by_user_id": str(sale.get("customer_id", "")),
                "confirmed_by_user_id": salesman_id,
                "reference_id": f"{bill_number}#{line['line_no']}" if bill_number else f"LINE#{line['line_no']}",
                "notes": f"{marker} Sale delivery against bill",
            })

    collected = float(sale.get("cash_collected", 0) if sale.get("cash_collected") is not None else (sale.get("bill_total", 0) if method != "CREDIT" else 0.0))
    payments = []
    if collected > 0 and (not sale_id or not _payments_for(sale_id)):
        p_status = "PAID" if collected >= float(sale.get("bill_total", 0) or 0) - 0.01 else "PARTIAL"
        payments.append({
            "sale_id": sale_id,
            "payment_datetime": now,
            "payment_method": method,
            "amount": _money(collected),
            "reference_number": reference or bill_number,
            "received_by_user_id": salesman_id,
            "payment_status": p_status,
            "notes": f"ref:{reference}" if reference else "Payment for bill",
        })

    cash_ledger_rows = []
    if method == "CASH" and collected > 0 and (not sale_id or not _cash_for(sale_id)):
        cash_ledger_rows.append({
            "txn_datetime": now,
            "salesman_user_id": salesman_id,
            "txn_type": "SALE_COLLECTION",
            "amount": _money(collected),
            "payment_method": "CASH",
            "related_sale_id": sale_id,
            "related_expense_id": "",
            "issued_by_user_id": str(sale.get("customer_id", "")),
            "received_by_user_id": salesman_id,
            "confirmed_by_user_id": salesman_id,
            "reference_id": bill_number,
            "notes": "Cash collection for bill",
        })

    return {
        "sale_items": sale_items,
        "stock_ledger_rows": stock_ledger_rows,
        "payments": payments,
        "cash_ledger_rows": cash_ledger_rows,
    }


class SaleCancelRequest(BaseModel):
    reason: str = "Customer cancellation / authorized reversal"


@router.get("/incomplete", response_model=List[Sale])
async def list_incomplete_sales(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, SALES_READ_ROLES)
    user_id = str(current_user.get("user_id", ""))
    can_view_all = _can_view_all_sales(current_user)
    sales_records = db.get_records("Sales", fresh=True)
    items_records = db.get_records("SaleItems", fresh=True)
    items_by_sale = {}
    for row in items_records:
        items_by_sale.setdefault(str(row.get("sale_id", "")), []).append(_to_item(row))
    incomplete = []
    for row in sales_records:
        if str(row.get("txn_status", "")).upper() != "INCOMPLETE":
            continue
        salesman_id = str(row.get("salesman_user_id", ""))
        if not can_view_all and salesman_id != user_id and str(row.get("entered_by_user_id", "")) != user_id:
            continue
        incomplete.append(_to_sale(row, items_by_sale.get(str(row.get("sale_id")), [])))
    return incomplete


@router.post("/{sale_id}/cancel", dependencies=[Depends(require_sheets_connection)])
async def cancel_sale(sale_id: str, req: SaleCancelRequest, request: Request, current_user: dict = Depends(get_current_user)):
    _reject_auditor(current_user)
    actor_role = role_v2_of(current_user)
    user_id = str(current_user.get("user_id", ""))
    async with _sales_lock:
        sales = db.get_records("Sales", fresh=True)
        match = next((s for s in sales if str(s.get("sale_id")) == sale_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Sale record not found.")
        if str(match.get("bill_status", "")).upper() == "CANCELLED":
            # Idempotency / reconciliation: Ensure any active journal voucher is reversed
            # and any interrupted cancellation is recovered safely.
            accounting_status = "NO_VOUCHER"
            reversal_journal_ids = []
            accounting_error = None
            try:
                from app.accounting.journal_engine import reverse_journal_voucher
                headers = db.get_records("JournalHeaders", fresh=True)
                sale_payments = [p for p in db.get_records("Payments", fresh=True) if str(p.get("sale_id", "")).strip() == sale_id]
                sale_payment_ids = {str(p.get("payment_id", "")).strip() for p in sale_payments if str(p.get("payment_id", "")).strip()}

                # Active vouchers: sale invoice vouchers and any payment collection vouchers
                active_sale_vouchers = [
                    h for h in headers
                    if ((str(h.get("reference_id", "")).strip() == sale_id and str(h.get("reference_type", "")).strip().upper() in {"SALE_INVOICE", "SALE"})
                        or (str(h.get("reference_id", "")).strip() in sale_payment_ids and str(h.get("reference_type", "")).strip().upper() == "PAYMENT_COLLECTION"))
                    and str(h.get("status", "")).strip().upper() in {"POSTED", "PROVISIONAL"}
                ]
                # Order invoice vouchers first, then payment collection vouchers
                active_sale_vouchers.sort(key=lambda h: 0 if str(h.get("reference_type", "")).strip().upper() in {"SALE_INVOICE", "SALE"} else 1)

                already_reversed_vouchers = [
                    h for h in headers
                    if ((str(h.get("reference_id", "")).strip() == sale_id and str(h.get("reference_type", "")).strip().upper() in {"SALE_INVOICE", "SALE"})
                        or (str(h.get("reference_id", "")).strip() in sale_payment_ids and str(h.get("reference_type", "")).strip().upper() == "PAYMENT_COLLECTION"))
                    and str(h.get("status", "")).strip().upper() == "REVERSED"
                ]

                if active_sale_vouchers:
                    for v in active_sale_vouchers:
                        orig_jid = str(v.get("journal_id", "")).strip()
                        if orig_jid:
                            rev_res = reverse_journal_voucher(
                                journal_id=orig_jid,
                                reason=f"Sale {sale_id} cancelled (reconciled): {req.reason.strip() or 'Reconciliation'}",
                                actor=user_id,
                                reversed_by=user_id,
                            )
                            rev_id = rev_res.get("journal_id") if isinstance(rev_res, dict) else orig_jid
                            reversal_journal_ids.append(rev_id)
                    accounting_status = "REVERSED"
                elif already_reversed_vouchers:
                    accounting_status = "ALREADY_REVERSED"
                    rev_parent_ids = {str(av.get("journal_id", "")).strip() for av in already_reversed_vouchers}
                    reversals = [
                        h for h in headers
                        if str(h.get("reference_type", "")).strip().upper() == "JOURNAL_REVERSAL"
                        and str(h.get("reference_id", "")).strip() in rev_parent_ids
                    ]
                    reversal_journal_ids = [str(r.get("journal_id", "")) for r in reversals if str(r.get("journal_id", ""))]
                else:
                    accounting_status = "NO_VOUCHER"

                if accounting_status in {"REVERSED", "ALREADY_REVERSED"}:
                    logger.info("Accounting reversal reconciled for cancelled sale %s (%s)", sale_id, accounting_status)
            except HTTPException:
                raise
            except Exception as acct_exc:
                accounting_status = "FAILED"
                accounting_error = str(acct_exc)
                logging.warning("Accounting reversal check for already cancelled sale %s: %s", sale_id, acct_exc)

            return {
                "ok": True,
                "sale_id": sale_id,
                "bill_number": match.get("bill_number"),
                "bill_status": "CANCELLED",
                "already_cancelled": True,
                "accounting_status": accounting_status,
                "reversal_journal_id": reversal_journal_ids[0] if reversal_journal_ids else None,
                "reversal_journal_ids": reversal_journal_ids,
                "accounting_error": accounting_error,
                "message": f"Bill {match.get('bill_number')} has already been cancelled. (Accounting status: {accounting_status})",
            }

        salesman_id = str(match.get("salesman_user_id", ""))
        if not is_manager(current_user) and salesman_id != user_id:
            raise HTTPException(status_code=403, detail="Only an Owner/PA or the issuing salesman can cancel a bill.")

        now = now_iso()
        bill_number = str(match.get("bill_number", ""))
        reason_text = req.reason.strip() or "Customer cancellation / authorized reversal"

        # 1. Build SalesmanStockLedger reversal rows
        existing_stock_reversals = [
            r for r in db.get_records("SalesmanStockLedger", fresh=True)
            if str(r.get("related_sale_id")) == sale_id and str(r.get("txn_type", "")).upper() == "RETURN_FROM_SALESMAN"
        ]
        items = _items_for(sale_id)
        stock_reversals = []
        for itm in items:
            p_id = str(itm.get("product_id"))
            qty = int(float(itm.get("quantity", 0) or 0))
            if qty > 0 and not any(str(r.get("product_id")) == p_id and int(float(r.get("quantity", 0) or 0)) == qty for r in existing_stock_reversals):
                stock_reversals.append({
                    "txn_datetime": now,
                    "salesman_user_id": salesman_id,
                    "product_id": p_id,
                    "sku_snapshot": str(itm.get("sku_snapshot", "")),
                    "txn_type": "RETURN_FROM_SALESMAN",
                    "quantity": qty,
                    "unit": str(itm.get("unit", "PACKET")),
                    "pack_weight_g": int(float(itm.get("pack_weight_g", 500) or 500)),
                    "related_sale_id": sale_id,
                    "issued_by_user_id": user_id,
                    "received_by_user_id": salesman_id,
                    "confirmed_by_user_id": user_id,
                    "reference_id": f"CANCEL-{bill_number}",
                    "notes": f"Stock reversal for cancelled bill {bill_number}: {reason_text}",
                })

        # 2. Build Payments / CashLedger reversal rows
        bill_total = float(match.get("bill_total", 0) or 0)
        method = str(match.get("payment_method", "CASH")).upper()

        all_sale_payments = [
            p for p in db.get_records("Payments", fresh=True)
            if str(p.get("sale_id", "")).strip() == sale_id
        ]
        sale_payment_ids = {str(p.get("payment_id", "")).strip() for p in all_sale_payments if str(p.get("payment_id", "")).strip()}
        positive_payments = [
            p for p in all_sale_payments
            if float(p.get("amount", 0) or 0) > 0 and str(p.get("payment_status", "")).upper() not in {"REFUNDED", "CANCELLED"}
        ]
        existing_refunds = [
            p for p in all_sale_payments
            if float(p.get("amount", 0) or 0) < 0 or str(p.get("payment_status", "")).upper() == "REFUNDED"
        ]
        existing_refund_refs = {str(r.get("reference_number", "")).strip() for r in existing_refunds}

        payment_reversals = []
        cash_reversals = []
        if positive_payments:
            for p in positive_payments:
                p_id = str(p.get("payment_id", "")).strip()
                p_amt = round(float(p.get("amount", 0) or 0), 2)
                p_method = str(p.get("payment_method", "CASH")).upper()
                ref_refund = f"REFUND-{p_id}"
                if ref_refund not in existing_refund_refs and not any(p_id in str(r.get("notes", "")) for r in existing_refunds):
                    payment_reversals.append({
                        "sale_id": sale_id,
                        "payment_datetime": now,
                        "payment_method": p_method,
                        "amount": -p_amt,
                        "reference_number": ref_refund,
                        "received_by_user_id": salesman_id,
                        "payment_status": "REFUNDED",
                        "notes": f"Payment reversal for collection {p_id} of cancelled bill {bill_number}: {reason_text}",
                    })

                if p_method == "CASH":
                    existing_cash_refunds = [
                        c for c in db.get_records("CashLedger", fresh=True)
                        if str(c.get("related_sale_id")) == sale_id and str(c.get("reference_id", "")).strip() in {f"CANCEL-{bill_number}-{p_id}", f"CANCEL-{bill_number}"}
                    ]
                    if not existing_cash_refunds:
                        cash_reversals.append({
                            "txn_datetime": now,
                            "salesman_user_id": salesman_id,
                            "txn_type": "SALE_REFUND",
                            "amount": -p_amt,
                            "payment_method": "CASH",
                            "related_sale_id": sale_id,
                            "related_expense_id": "",
                            "issued_by_user_id": salesman_id,
                            "received_by_user_id": str(match.get("customer_id", "")),
                            "confirmed_by_user_id": user_id,
                            "reference_id": f"CANCEL-{bill_number}-{p_id}",
                            "notes": f"Cash refund reversal for collection {p_id} of cancelled bill {bill_number}",
                        })
        else:
            p_status = str(match.get("payment_status", "")).upper()
            if p_status != "UNPAID" and method != "CREDIT":
                leg_collected = float(match.get("cash_collected") if match.get("cash_collected") is not None else bill_total)
            else:
                leg_collected = float(match.get("cash_collected", 0) or 0)
            if leg_collected > 0 and not existing_refunds:
                payment_reversals.append({
                    "sale_id": sale_id,
                    "payment_datetime": now,
                    "payment_method": method,
                    "amount": -leg_collected,
                    "reference_number": f"REFUND-{bill_number}",
                    "received_by_user_id": salesman_id,
                    "payment_status": "REFUNDED",
                    "notes": f"Payment reversal for cancelled bill {bill_number}: {reason_text}",
                })
                if method == "CASH":
                    existing_cash_refunds = [
                        c for c in db.get_records("CashLedger", fresh=True)
                        if str(c.get("related_sale_id")) == sale_id and str(c.get("txn_type", "")).upper() == "SALE_REFUND"
                    ]
                    if not existing_cash_refunds:
                        cash_reversals.append({
                            "txn_datetime": now,
                            "salesman_user_id": salesman_id,
                            "txn_type": "SALE_REFUND",
                            "amount": -leg_collected,
                            "payment_method": "CASH",
                            "related_sale_id": sale_id,
                            "related_expense_id": "",
                            "issued_by_user_id": salesman_id,
                            "received_by_user_id": str(match.get("customer_id", "")),
                            "confirmed_by_user_id": user_id,
                            "reference_id": f"CANCEL-{bill_number}",
                            "notes": f"Cash refund reversal for cancelled bill {bill_number}",
                        })

        # 3. Delegate atomic cancellation via Apps Script bridge
        apps_script_bridge.delegate_governed_write(
            action="CANCEL_SALE",
            target_tab="Sales",
            payload={
                "sale_id": sale_id,
                "bill_status": "CANCELLED",
                "reason": reason_text,
                "notes": f"{match.get('notes', '')} [CANCELLED:{now}:{user_id}:{reason_text}]".strip(),
                "stock_reversals": stock_reversals,
                "payment_reversals": payment_reversals,
                "cash_reversals": cash_reversals,
            },
            actor_user_id=user_id,
            actor_role=actor_role,
            request=request,
            id_field="sale_id",
            invalidate_tabs=["Sales", "SalesmanStockLedger", "Payments", "CashLedger"],
        )

        db.log_audit(user_id, "CANCEL_BILL", "Sales", sale_id, reason=f"Cancelled bill {bill_number} for ₹{bill_total:.2f}. Reason: {reason_text}")

        # 4. Double-Entry Accounting Compensating Reversal Vouchers
        accounting_status = "NO_VOUCHER"
        reversal_journal_ids = []
        accounting_error = None
        try:
            from app.accounting.journal_engine import reverse_journal_voucher
            headers = db.get_records("JournalHeaders", fresh=True)
            all_sale_vouchers = [
                h for h in headers
                if ((str(h.get("reference_id", "")).strip() == sale_id and str(h.get("reference_type", "")).strip().upper() in {"SALE_INVOICE", "SALE"})
                    or (str(h.get("reference_id", "")).strip() in sale_payment_ids and str(h.get("reference_type", "")).strip().upper() == "PAYMENT_COLLECTION"))
            ]
            active_vouchers = [
                h for h in all_sale_vouchers
                if str(h.get("status", "")).strip().upper() in {"POSTED", "PROVISIONAL"}
            ]
            active_vouchers.sort(key=lambda h: 0 if str(h.get("reference_type", "")).strip().upper() in {"SALE_INVOICE", "SALE"} else 1)

            already_reversed_vouchers = [
                h for h in all_sale_vouchers
                if str(h.get("status", "")).strip().upper() == "REVERSED"
            ]

            if active_vouchers:
                for v in active_vouchers:
                    orig_jid = str(v.get("journal_id", "")).strip()
                    if orig_jid:
                        rev_res = reverse_journal_voucher(
                            journal_id=orig_jid,
                            reason=f"Sale {sale_id} cancelled: {reason_text}",
                            actor=user_id,
                            reversed_by=user_id,
                        )
                        rev_id = rev_res.get("journal_id") if isinstance(rev_res, dict) else orig_jid
                        reversal_journal_ids.append(rev_id)
                accounting_status = "REVERSED"
            elif already_reversed_vouchers:
                accounting_status = "ALREADY_REVERSED"
                rev_parent_ids = {str(av.get("journal_id", "")).strip() for av in already_reversed_vouchers}
                reversals = [
                    h for h in headers
                    if str(h.get("reference_type", "")).strip().upper() == "JOURNAL_REVERSAL"
                    and str(h.get("reference_id", "")).strip() in rev_parent_ids
                ]
                reversal_journal_ids = [str(r.get("journal_id", "")) for r in reversals if str(r.get("journal_id", ""))]
            else:
                accounting_status = "NO_VOUCHER"
        except HTTPException:
            raise
        except Exception as acct_exc:
            accounting_status = "FAILED"
            accounting_error = str(acct_exc)
            logging.error("Accounting reversal for sale %s failed: %s", sale_id, acct_exc)

        msg = (
            f"Bill {bill_number} cancelled and stock/payment reversed successfully. Accounting voucher reversed ({', '.join(reversal_journal_ids)})."
            if accounting_status == "REVERSED"
            else f"Bill {bill_number} cancelled. Accounting voucher was already reversed."
            if accounting_status == "ALREADY_REVERSED"
            else f"Bill {bill_number} cancelled. No accounting voucher found to reverse."
            if accounting_status == "NO_VOUCHER"
            else f"Bill {bill_number} cancelled, but accounting reversal failed: {accounting_error}."
        )

        return {
            "ok": True,
            "sale_id": sale_id,
            "bill_number": bill_number,
            "bill_status": "CANCELLED",
            "accounting_status": accounting_status,
            "reversal_journal_id": reversal_journal_ids[0] if reversal_journal_ids else None,
            "reversal_journal_ids": reversal_journal_ids,
            "accounting_error": accounting_error,
            "message": msg,
        }


@router.post("/{sale_id}/payments", dependencies=[Depends(require_sheets_connection)])
async def record_sale_payment(
    sale_id: str,
    payload: SalePaymentCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    _reject_auditor(current_user)
    user_id, actor_role = require_roles(current_user, SALES_PAYMENT_ROLES)
    username = str(current_user.get("username", "OPERATOR")).strip()

    async with _sales_lock:
        sales = db.get_records("Sales", fresh=True)
        sale = next((s for s in sales if str(s.get("sale_id", "")).strip() == sale_id), None)
        if not sale:
            raise HTTPException(status_code=404, detail=f"Sale {sale_id} not found.")

        if str(sale.get("bill_status", "")).upper() == "CANCELLED":
            raise HTTPException(status_code=400, detail="Cannot record payment for a cancelled bill.")

        bill_total = round(float(sale.get("bill_total", 0) or 0), 2)
        payments = [
            p for p in db.get_records("Payments", fresh=True)
            if str(p.get("sale_id", "")).strip() == sale_id and str(p.get("payment_status", "")).upper() != "REFUNDED"
        ]
        total_paid_so_far = round(sum(float(p.get("amount", 0) or 0) for p in payments), 2)
        remaining_balance = round(bill_total - total_paid_so_far, 2)

        clean_key = _clean(getattr(payload, "idempotency_key", None))
        if clean_key:
            for p in payments:
                p_notes = str(p.get("notes", ""))
                p_key = _clean(p.get("idempotency_key"))
                if p_key == clean_key or f"[idemp:{clean_key}]" in p_notes:
                    existing_amt = round(float(p.get("amount", 0) or 0), 2)
                    if abs(existing_amt - round(payload.amount, 2)) > 0.05:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Conflict: Idempotency key '{clean_key}' already used with amount ₹{existing_amt:.2f}, conflicting with ₹{payload.amount:.2f}."
                        )
                    return {
                        "ok": True,
                        "payment_id": str(p.get("payment_id")),
                        "sale_id": sale_id,
                        "amount_paid": existing_amt,
                        "remaining_balance": remaining_balance,
                        "payment_status": str(sale.get("payment_status", "PAID")),
                        "journal_result": {"status": "ALREADY_RECORDED"},
                        "is_replay": True,
                    }

        if payload.amount <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")

        if payload.amount > remaining_balance + 0.05:
            raise HTTPException(
                status_code=400,
                detail=f"Payment amount ₹{payload.amount:.2f} exceeds remaining balance of ₹{remaining_balance:.2f}."
            )

        now = now_iso()
        pay_method = str(payload.payment_method or "CASH").upper()
        ref_num = payload.reference_number or str(sale.get("bill_number", ""))
        notes_text = payload.notes or f"Customer collection against bill {sale.get('bill_number')}"
        if clean_key:
            notes_text = f"[idemp:{clean_key}] {notes_text}".strip()

        payment_record = {
            "sale_id": sale_id,
            "idempotency_key": clean_key,
            "payment_datetime": now,
            "payment_method": pay_method,
            "amount": round(payload.amount, 2),
            "reference_number": ref_num,
            "received_by_user_id": user_id,
            "payment_status": "COLLECTED",
            "notes": notes_text,
        }
        cash_row = (
            {
                "txn_datetime": now,
                "salesman_user_id": str(sale.get("salesman_user_id", "")) or user_id,
                "txn_type": "SALE_COLLECTION",
                "amount": round(payload.amount, 2),
                "payment_method": "CASH",
                "related_sale_id": sale_id,
                "related_expense_id": "",
                "issued_by_user_id": str(sale.get("customer_id", "")) or "CUSTOMER",
                "received_by_user_id": user_id,
                "confirmed_by_user_id": user_id,
                "reference_id": ref_num,
                "notes": f"Cash collection for bill {sale.get('bill_number')}",
            }
            if pay_method == "CASH"
            else None
        )

        new_total_paid = round(total_paid_so_far + payload.amount, 2)
        new_balance = max(0.0, round(bill_total - new_total_paid, 2))
        new_status = "PAID" if new_balance <= 0.05 else "PARTIAL"

        bridge_res = apps_script_bridge.delegate_governed_write(
            action="RECORD_SALE_PAYMENT",
            target_tab="Payments",
            payload={
                "payment": payment_record,
                "cash_ledger_row": cash_row,
                "sale_payment_status_update": {"sale_id": sale_id, "payment_status": new_status},
            },
            actor_user_id=user_id,
            actor_role=actor_role,
            nonce=clean_key or None,
            request=request,
            id_field="payment_id",
            invalidate_tabs=["Payments", "CashLedger", "Sales"],
        )
        payment_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("payment_id") or "")
        saved_payment = bridge_res.get("record") or {**payment_record, "payment_id": payment_id}

        db.log_audit(
            user_id,
            "RECORD_PAYMENT",
            "Payments",
            payment_id,
            reason=f"Recorded {pay_method} collection of ₹{payload.amount:.2f} for bill {sale.get('bill_number')}",
        )

        from app.accounting.postings import post_payment_collection_journal
        journal_res = post_payment_collection_journal(saved_payment, actor=username)

        return {
            "ok": True,
            "payment_id": payment_id,
            "sale_id": sale_id,
            "amount_paid": round(payload.amount, 2),
            "remaining_balance": new_balance,
            "payment_status": new_status,
            "journal_result": journal_res,
        }


@router.get("/customers/{customer_id}/ledger")
async def get_customer_ledger(customer_id: str, current_user: dict = Depends(get_current_user)):
    """Authoritative chronological customer ledger transactions (invoices, collections, credit notes)."""
    require_roles(current_user, SALES_READ_ROLES)
    from app.accounting.customer_ledger import get_customer_transactions
    return get_customer_transactions(customer_id)


@router.get("/customers/{customer_id}/outstanding")
async def get_customer_outstanding_summary(customer_id: str, current_user: dict = Depends(get_current_user)):
    """Customer outstanding balance and overdue aging breakdown."""
    require_roles(current_user, SALES_READ_ROLES)
    from app.accounting.customer_ledger import calculate_customer_outstanding, get_customer_overdue_invoices
    outstanding = calculate_customer_outstanding(customer_id)
    overdue = get_customer_overdue_invoices(customer_id)
    return {
        "customer_id": customer_id,
        "outstanding_balance": outstanding,
        "overdue_invoices": overdue,
        "is_overdue": len(overdue) > 0,
    }


@router.get("/customers/{customer_id}/breakdown")
async def get_customer_balance_breakdown_endpoint(customer_id: str, current_user: dict = Depends(get_current_user)):
    """Customer debit vs credit balance breakdown (exposing customer credit balances clearly)."""
    require_roles(current_user, SALES_READ_ROLES)
    from app.accounting.customer_ledger import get_customer_balance_breakdown
    return get_customer_balance_breakdown(customer_id)


@router.get("/{sale_id}/settlement")
async def get_sale_settlement(sale_id: str, current_user: dict = Depends(get_current_user)):
    """Invoice settlement status (bill_total, total_collected, remaining_balance, payment_status)."""
    require_roles(current_user, SALES_READ_ROLES)
    from app.accounting.customer_ledger import get_invoice_settlement_status
    return get_invoice_settlement_status(sale_id)


@router.get("/orders")
async def list_sales_orders(current_user: dict = Depends(get_current_user)):
    """List sales orders, distinguishing quotations, drafts, and confirmed orders."""
    require_roles(current_user, SALES_READ_ROLES)
    user_id = str(current_user.get("user_id", ""))
    can_view_all = _can_view_all_sales(current_user)
    sales_records = db.get_records("Sales", fresh=True)
    items_records = db.get_records("SaleItems", fresh=True)
    items_by_sale: Dict[str, List[SaleItem]] = {}
    for row in items_records:
        items_by_sale.setdefault(str(row.get("sale_id", "")), []).append(_to_item(row))

    orders = []
    for row in sales_records:
        salesman_id = str(row.get("salesman_user_id", ""))
        if not can_view_all and salesman_id != user_id and str(row.get("entered_by_user_id", "")) != user_id:
            continue
        status = str(row.get("bill_status", "")).upper()
        if status in {"DRAFT", "ORDER_CONFIRMED", "ORDER_DRAFT"}:
            orders.append(_to_sale(row, items_by_sale.get(str(row.get("sale_id")), [])))
    return orders


@router.post("/orders", response_model=Sale, dependencies=[Depends(require_sheets_connection)])
async def create_sales_order(req: SaleCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Create a sales order in DRAFT status atomically via Apps Script bridge."""
    _reject_auditor(current_user)
    user_id, actor_role = require_roles(current_user, SALES_WRITE_ROLES)
    salesman_id = _clean(req.salesman_user_id) or user_id
    customer_id = _clean(req.customer_id)

    customers = db.get_records("Customers", fresh=True)
    cust = next((c for c in customers if str(c.get("customer_id")) == customer_id), None)
    cust_name = str(cust.get("shop_name") or cust.get("shopkeeper_name") or "Direct Customer") if cust else "Direct Customer"

    now = now_iso()
    products = {str(p.get("product_id")): p for p in db.get_records("Products", fresh=True)}
    line_items = []
    subtotal = 0.0
    for idx, item in enumerate(req.items):
        prod = products.get(item.product_id)
        if not prod:
            raise HTTPException(400, f"Product {item.product_id} not found.")
        unit_price = float(item.actual_unit_price or 0.0)
        line_tot = round(unit_price * item.quantity, 2)
        subtotal += line_tot
        line_items.append({
            "line_no": idx,
            "product_id": item.product_id,
            "product_name_snapshot": str(prod.get("product_name", "")),
            "sku_snapshot": str(prod.get("sku", "")),
            "pack_weight_g": int(float(prod.get("pack_weight_g", 500) or 500)),
            "unit": "PACKET",
            "quantity": item.quantity,
            "actual_unit_price": unit_price,
            "discount_amount": 0.0,
            "line_total": line_tot,
            "qualifying_kg": (int(float(prod.get("pack_weight_g", 500) or 500)) * item.quantity) / 1000.0,
            "created_at": now,
            "notes": "Sales Order Item",
        })

    tax_amt = round(subtotal * 0.05, 2)
    bill_total = subtotal + tax_amt
    clean_key = _clean(req.idempotency_key)

    order_record = {
        "idempotency_key": clean_key,
        "txn_status": "COMPLETE",
        "sale_datetime": now,
        "sales_type": req.sales_type or "Retailer Sale",
        "customer_id": customer_id,
        "customer_name_snapshot": cust_name,
        "customer_mobile": cust.get("mobile", "") if cust else "",
        "customer_gstin": cust.get("gstin", "") if cust else "",
        "entered_by_user_id": user_id,
        "salesman_user_id": salesman_id,
        "delivery_status": "PENDING_CONFIRMATION",
        "payment_status": "UNPAID",
        "payment_method": req.payment_method or "CREDIT",
        "payment_reference": "",
        "subtotal": subtotal,
        "discount_amount": 0.0,
        "tax_amount": tax_amt,
        "bill_total": bill_total,
        "bill_status": "DRAFT",
        "created_at": now,
        "notes": f"[SALES_ORDER_DRAFT] {req.notes or ''}".strip(),
    }

    bridge_res = apps_script_bridge.delegate_governed_write(
        action="CREATE_SALES_ORDER",
        target_tab="Sales",
        payload={"order": order_record, "items": line_items},
        actor_user_id=user_id,
        actor_role=actor_role,
        nonce=clean_key or None,
        request=request,
        id_field="sale_id",
        invalidate_tabs=["Sales", "SaleItems"],
    )
    sale_id = str(bridge_res.get("allocated_id") or (bridge_res.get("record") or {}).get("sale_id") or "")
    saved_order = bridge_res.get("record") or {**order_record, "sale_id": sale_id}
    order_num = str(saved_order.get("bill_number") or sale_id)

    db.log_audit(user_id, "CREATE_SALES_ORDER", "Sales", sale_id, reason=f"Created sales order {order_num} for ₹{bill_total:.2f}")
    return _to_sale(saved_order, [_to_item({**i, "sale_id": sale_id}) for i in line_items])


@router.post("/orders/{sale_id}/confirm", dependencies=[Depends(require_sheets_connection)])
async def confirm_sales_order(sale_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Confirm a DRAFT sales order atomically via Apps Script bridge and post accounting voucher."""
    _reject_auditor(current_user)
    user_id, actor_role = require_roles(current_user, SALES_WRITE_ROLES)
    async with _sales_lock:
        sales = db.get_records("Sales", fresh=True)
        sale = next((s for s in sales if str(s.get("sale_id")) == sale_id), None)
        if not sale:
            raise HTTPException(404, f"Sales order {sale_id} not found.")
        order_status = str(sale.get("bill_status", "")).upper()
        if order_status != "DRAFT":
            raise HTTPException(400, f"Cannot confirm order with status '{order_status}'. Must be in DRAFT state.")

        now = now_iso()
        items = _items_for(sale_id)
        salesman_id = str(sale.get("salesman_user_id") or user_id)

        stock_rows = []
        for itm in items:
            p_id = str(itm.get("product_id"))
            qty = int(float(itm.get("quantity", 0) or 0))
            stock_rows.append({
                "txn_datetime": now,
                "salesman_user_id": salesman_id,
                "product_id": p_id,
                "sku_snapshot": str(itm.get("sku_snapshot", "")),
                "txn_type": "SOLD_DELIVERY",
                "quantity": -qty,
                "unit": "PACKET",
                "pack_weight_g": int(float(itm.get("pack_weight_g", 500) or 500)),
                "related_sale_id": sale_id,
                "issued_by_user_id": salesman_id,
                "received_by_user_id": str(sale.get("customer_id", "")),
                "confirmed_by_user_id": user_id,
                "reference_id": str(sale.get("bill_number", "")),
                "notes": f"Stock deduction for confirmed bill {sale.get('bill_number')}",
            })

        apps_script_bridge.delegate_governed_write(
            action="CONFIRM_SALES_ORDER",
            target_tab="Sales",
            payload={
                "sale_id": sale_id,
                "bill_status": "ISSUED",
                "delivery_status": "DELIVERED",
                "stock_ledger_rows": stock_rows,
            },
            actor_user_id=user_id,
            actor_role=actor_role,
            request=request,
            id_field="sale_id",
            invalidate_tabs=["Sales", "SalesmanStockLedger"],
        )

        from app.accounting.postings import post_sale_journal
        cogs = _compute_authoritative_cogs(items)
        post_sale_journal(sale, estimated_cogs=cogs, actor=user_id)

        db.log_audit(user_id, "CONFIRM_SALES_ORDER", "Sales", sale_id, reason=f"Confirmed and issued order {sale.get('bill_number')}")
        return {"ok": True, "sale_id": sale_id, "bill_status": "ISSUED", "message": f"Order {sale.get('bill_number')} confirmed and stock deducted."}


@router.get("/dispatch-summary")
async def sales_dispatch_summary(current_user: dict = Depends(get_current_user)):
    """Overview of sales orders, dispatches, and fulfillment status."""
    require_roles(current_user, SALES_READ_ROLES)
    sales = db.get_records("Sales", fresh=True)
    items = db.get_records("SaleItems", fresh=True)
    items_by_sale = {}
    for itm in items:
        items_by_sale.setdefault(str(itm.get("sale_id")), []).append(itm)

    dispatches = db.get_records("ProductionDispatches", fresh=True)

    summary_list = []
    for s in sales:
        sid = str(s.get("sale_id"))
        st = str(s.get("bill_status", "")).upper()
        if st in {"CANCELLED"}:
            continue
        sale_items = items_by_sale.get(sid, [])
        total_qty = sum(int(float(i.get("quantity", 0) or 0)) for i in sale_items)
        summary_list.append({
            "sale_id": sid,
            "bill_number": str(s.get("bill_number", "")),
            "customer_name": str(s.get("customer_name_snapshot", "")),
            "sale_datetime": str(s.get("sale_datetime", "")),
            "bill_total": float(s.get("bill_total", 0) or 0),
            "total_packets": total_qty,
            "bill_status": st,
            "delivery_status": str(s.get("delivery_status", "PENDING")),
            "payment_status": str(s.get("payment_status", "UNPAID")),
        })
    summary_list.sort(key=lambda x: x["sale_datetime"], reverse=True)
    return summary_list


# Compatibility alias for acceptance tests
record_sale = create_sale




