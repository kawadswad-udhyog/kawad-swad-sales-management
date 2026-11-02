import asyncio
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from app.models import Sale, SaleCreate, SaleItem, SalePaymentCreate
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager, is_salesman
from app.stock_math import salesman_available
from app.timeutil import now_iso

router = APIRouter(prefix="/api/sales", tags=["Sales"])
_sales_lock = asyncio.Lock()
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
        bill_total=float(row.get("bill_total", 0) or 0),
        bill_status=str(row.get("bill_status", "ISSUED")),
        created_at=str(row.get("created_at", "")),
        notes=_clean(notes),
        items=items,
        txn_status=str(row.get("txn_status", "COMPLETE") or "COMPLETE"),
        payment_method=method,
        payment_reference=reference if reference != str(row.get("bill_number", "")) else _clean(row.get("payment_reference")),
        lines=items,
    )


def _must_write(tab: str, record: dict):
    if not db.append_record(tab, record, raise_on_error=True):
        raise HTTPException(status_code=503, detail=f"Could not save {tab}. The sale is incomplete and can be retried with the same idempotency key.")


def _sale_is_complete(sale_id: str, line_count: int, payment_method: str) -> bool:
    if len(_items_for(sale_id)) < line_count:
        return False
    if len(_stock_for(sale_id)) < line_count:
        return False
    if not _payments_for(sale_id):
        return False
    if payment_method == "CASH" and not _cash_for(sale_id):
        return False
    return True


@router.get("", response_model=List[Sale])
async def list_sales(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
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
        if not is_manager(current_user) and salesman_id != user_id and str(row.get("entered_by_user_id", "")) != user_id:
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
    user_id = str(current_user.get("user_id", ""))
    sales = {str(row.get("sale_id")): row for row in db.get_records("Sales")}
    payments = []
    for row in db.get_records("Payments"):
        sale = sales.get(str(row.get("sale_id")), {})
        salesman_id = str(sale.get("salesman_user_id", ""))
        if not is_manager(current_user) and salesman_id not in {user_id, ""} and str(sale.get("entered_by_user_id", "")) != user_id:
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
async def create_sale(req: SaleCreate, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    requested_salesman = _clean(req.salesman_user_id) or user_id
    if is_salesman(current_user) and requested_salesman != user_id:
        raise HTTPException(status_code=403, detail="A salesman can only record a sale against their own user id.")
    if not is_manager(current_user) and not is_salesman(current_user):
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

    method = _clean(req.payment_method or "CASH").upper() or "CASH"
    if method not in {"CASH", "UPI", "BANK_TRANSFER", "OTHER"}:
        raise HTTPException(status_code=422, detail="Payment method must be CASH, UPI, BANK_TRANSFER, or OTHER.")
    if str(req.payment_status or "PAID").upper() not in {"PAID", "RECEIVED"}:
        raise HTTPException(status_code=422, detail="Only a fully paid sale can be issued. Credit and partial payment are not enabled.")

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
        if item.actual_unit_price is None or float(item.actual_unit_price) < 0:
            raise HTTPException(status_code=422, detail=f"Line {index + 1}: Price cannot be negative.")
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
    async with _sales_lock:
        if clean_key:
            existing = _find_sale_by_key(db.get_records("Sales", fresh=True), clean_key)
            if existing:
                owner = str(existing.get("salesman_user_id", ""))
                entered = str(existing.get("entered_by_user_id", ""))
                if not is_manager(current_user) and user_id not in {owner, entered}:
                    raise HTTPException(status_code=409, detail="This idempotency key already belongs to another user.")
                sale_id = str(existing.get("sale_id"))
                if _sale_is_complete(sale_id, len(validated), method) or _sale_is_complete(sale_id, len(_items_for(sale_id)) or len(validated), str(existing.get("payment_method") or method).upper()):
                    if str(existing.get("txn_status", "")).upper() != "COMPLETE":
                        if not db.update_record("Sales", "sale_id", sale_id, {"txn_status": "COMPLETE"}):
                            raise HTTPException(status_code=503, detail="The sale rows exist but the completion flag could not be saved. Retry the same request.")
                        existing["txn_status"] = "COMPLETE"
                    items = [_to_item(row) for row in _items_for(sale_id)]
                    return _to_sale(existing, items, clean_key)
                return await _resume_sale(existing, validated, method, reference, bill_total, user_id, clean_key)

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
        sale_id = db.generate_id("Sales")
        bill_number = db.allocate_bill_number()
        notes = _clean(req.notes)
        if clean_key:
            notes = f"[idemp:{clean_key}] [txn:INCOMPLETE] {notes}".strip()
        sale_record = {
            "sale_id": sale_id,
            "bill_number": bill_number,
            "idempotency_key": clean_key,
            "txn_status": "INCOMPLETE",
            "sale_datetime": now,
            "sales_type": _clean(req.sales_type or "Retailer Sale") or "Retailer Sale",
            "customer_id": customer_id,
            "customer_name_snapshot": customer_name,
            "customer_mobile": _clean(req.customer_mobile),
            "customer_gstin": _clean(req.customer_gstin),
            "entered_by_user_id": user_id,
            "salesman_user_id": requested_salesman,
            "delivery_status": req.delivery_status or "DELIVERED",
            "payment_status": "PAID",
            "payment_method": method,
            "payment_reference": reference,
            "subtotal": subtotal,
            "discount_amount": discount_amount,
            "tax_amount": tax_amount,
            "bill_total": bill_total,
            "bill_status": "ISSUED",
            "created_at": now,
            "notes": notes,
        }
        try:
            _must_write("Sales", sale_record)
            _write_children(sale_record, validated, method, reference, user_id, now)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Sale {sale_id} is incomplete and was not issued. Retry the same idempotency key. {exc}",
            ) from exc
        if not db.update_record("Sales", "sale_id", sale_id, {"txn_status": "COMPLETE", "notes": notes.replace("[txn:INCOMPLETE]", "[txn:COMPLETE]")}):
            raise HTTPException(status_code=503, detail=f"Sale {sale_id} rows were written but completion could not be marked. Retry the same idempotency key.")
        sale_record["txn_status"] = "COMPLETE"
        db.log_audit(user_id, "ISSUE_BILL", "Sales", sale_id, reason=f"Issued bill {bill_number} for ₹{bill_total:.2f} to {customer_name}")

        # Double-Entry Accounting Journal Posting (Non-blocking / Resilient)
        try:
            from app.accounting.postings import post_sale_journal
            from app.calculations.units import to_decimal
            cogs = sum(to_decimal(item.get("qualifying_kg", 0) or 0) * to_decimal("170.00") for item in validated)
            post_sale_journal(sale_record, cogs, user_id)
        except Exception as acct_err:
            try:
                db.append_record("IncompleteTransactions", {
                    "transaction_id": db.generate_id("IncompleteTransactions"),
                    "transaction_type": "ACCOUNTING_POSTING_PENDING",
                    "idempotency_key": f"acct-sale-{sale_id}",
                    "status": "POSTING_FAILED",
                    "payload_json": f'{{"sale_id": "{sale_id}", "type": "SALE"}}',
                    "error_details": str(acct_err),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "resolved_by": "",
                    "resolved_at": "",
                })
            except Exception:
                pass

        items = [_to_item(row) for row in _items_for(sale_id)]
        return _to_sale(sale_record, items, clean_key)


async def _resume_sale(existing: dict, validated: list, method: str, reference: str, bill_total: float, user_id: str, clean_key: str) -> Sale:
    sale_id = str(existing.get("sale_id"))
    if abs(_money(existing.get("bill_total")) - _money(bill_total)) > _MONEY:
        raise HTTPException(status_code=409, detail="This idempotency key belongs to a different bill total. Start a new bill.")
    now = now_iso()
    try:
        _write_children(existing, validated, method or str(existing.get("payment_method") or "CASH"), reference or _clean(existing.get("payment_reference")), user_id, now)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Recovery of sale {sale_id} is still incomplete. Retry the same idempotency key. {exc}") from exc
    notes = str(existing.get("notes", "")).replace("[txn:INCOMPLETE]", "[txn:COMPLETE]")
    if not db.update_record("Sales", "sale_id", sale_id, {"txn_status": "COMPLETE", "notes": notes}):
        raise HTTPException(status_code=503, detail=f"Sale {sale_id} was recovered but completion could not be marked. Retry.")
    existing["txn_status"] = "COMPLETE"
    db.log_audit(user_id, "RECOVER_BILL", "Sales", sale_id, reason="Completed missing sale rows on retry")

    # Double-Entry Accounting Journal Posting on Resumed Sale
    try:
        from app.accounting.postings import post_sale_journal
        from app.calculations.units import to_decimal
        cogs = sum(to_decimal(item.get("qualifying_kg", 0) or 0) * to_decimal("170.00") for item in validated)
        post_sale_journal(existing, cogs, user_id)
    except Exception:
        pass

    return _to_sale(existing, [_to_item(row) for row in _items_for(sale_id)], clean_key)



def _write_children(sale: dict, validated: list, method: str, reference: str, user_id: str, now: str):
    sale_id = str(sale.get("sale_id"))
    bill_number = str(sale.get("bill_number"))
    salesman_id = str(sale.get("salesman_user_id"))
    existing_items = _items_for(sale_id)
    existing_stock = _stock_for(sale_id)
    for line in validated:
        marker = f"[line:{line['line_no']}]"
        if not any(marker in str(row.get("notes", "")) for row in existing_items):
            item_id = db.generate_id("SaleItems")
            item_notes = f"{marker} {line['notes']}".strip()
            _must_write("SaleItems", {
                "sale_item_id": item_id,
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
                "notes": item_notes,
            })
        if not any(marker in str(row.get("notes", "")) or str(row.get("reference_id")) == f"{bill_number}#{line['line_no']}" for row in existing_stock):
            _must_write("SalesmanStockLedger", {
                "stock_txn_id": db.generate_id("SalesmanStockLedger"),
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
                "reference_id": f"{bill_number}#{line['line_no']}",
                "notes": f"{marker} Sale delivery against bill {bill_number}",
            })
    if not _payments_for(sale_id):
        _must_write("Payments", {
            "payment_id": db.generate_id("Payments"),
            "sale_id": sale_id,
            "payment_datetime": now,
            "payment_method": method,
            "amount": _money(sale.get("bill_total")),
            "reference_number": reference or bill_number,
            "received_by_user_id": salesman_id,
            "payment_status": "PAID",
            "notes": f"ref:{reference}" if reference else f"Full payment for bill {bill_number}",
        })
    if method == "CASH" and not _cash_for(sale_id):
        _must_write("CashLedger", {
            "cash_txn_id": db.generate_id("CashLedger"),
            "txn_datetime": now,
            "salesman_user_id": salesman_id,
            "txn_type": "SALE_COLLECTION",
            "amount": _money(sale.get("bill_total")),
            "payment_method": "CASH",
            "related_sale_id": sale_id,
            "related_expense_id": "",
            "issued_by_user_id": str(sale.get("customer_id", "")),
            "received_by_user_id": salesman_id,
            "confirmed_by_user_id": salesman_id,
            "reference_id": bill_number,
            "notes": f"Cash collection for bill {bill_number}",
        })


class SaleCancelRequest(BaseModel):
    reason: str = "Customer cancellation / authorized reversal"


@router.get("/incomplete", response_model=List[Sale])
async def list_incomplete_sales(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
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
        if not is_manager(current_user) and salesman_id != user_id and str(row.get("entered_by_user_id", "")) != user_id:
            continue
        incomplete.append(_to_sale(row, items_by_sale.get(str(row.get("sale_id")), [])))
    return incomplete


@router.post("/{sale_id}/cancel", dependencies=[Depends(require_sheets_connection)])
async def cancel_sale(sale_id: str, req: SaleCancelRequest, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    async with _sales_lock:
        sales = db.get_records("Sales", fresh=True)
        match = next((s for s in sales if str(s.get("sale_id")) == sale_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Sale record not found.")
        if str(match.get("bill_status", "")).upper() == "CANCELLED":
            return {"ok": True, "message": f"Bill {match.get('bill_number')} has already been cancelled.", "already_cancelled": True}

        salesman_id = str(match.get("salesman_user_id", ""))
        if not is_manager(current_user) and salesman_id != user_id:
            raise HTTPException(status_code=403, detail="Only an Owner/PA or the issuing salesman can cancel a bill.")

        now = now_iso()
        bill_number = str(match.get("bill_number", ""))
        reason_text = req.reason.strip() or "Customer cancellation / authorized reversal"

        # 1. Reverse stock in SalesmanStockLedger (check if reversal line already appended)
        existing_stock_reversals = [
            r for r in db.get_records("SalesmanStockLedger", fresh=True)
            if str(r.get("related_sale_id")) == sale_id and str(r.get("txn_type", "")).upper() == "RETURN_FROM_SALESMAN"
        ]
        items = _items_for(sale_id)
        for itm in items:
            p_id = str(itm.get("product_id"))
            qty = int(float(itm.get("quantity", 0) or 0))
            if qty > 0 and not any(str(r.get("product_id")) == p_id and int(float(r.get("quantity", 0) or 0)) == qty for r in existing_stock_reversals):
                db.append_record("SalesmanStockLedger", {
                    "stock_txn_id": db.generate_id("SalesmanStockLedger"),
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
                }, raise_on_error=True)

        # 2. Reverse payments in Payments / CashLedger (check if refund line already appended)
        bill_total = float(match.get("bill_total", 0) or 0)
        method = str(match.get("payment_method", "CASH")).upper()
        existing_payments = [
            p for p in db.get_records("Payments", fresh=True)
            if str(p.get("sale_id")) == sale_id and str(p.get("payment_status", "")).upper() == "REFUNDED"
        ]
        if not existing_payments:
            db.append_record("Payments", {
                "payment_id": db.generate_id("Payments"),
                "sale_id": sale_id,
                "payment_datetime": now,
                "payment_method": method,
                "amount": -bill_total,
                "reference_number": f"REFUND-{bill_number}",
                "received_by_user_id": salesman_id,
                "payment_status": "REFUNDED",
                "notes": f"Payment reversal for cancelled bill {bill_number}: {reason_text}",
            }, raise_on_error=True)

        if method == "CASH":
            existing_cash_refunds = [
                c for c in db.get_records("CashLedger", fresh=True)
                if str(c.get("related_sale_id")) == sale_id and str(c.get("txn_type", "")).upper() == "SALE_REFUND"
            ]
            if not existing_cash_refunds:
                db.append_record("CashLedger", {
                    "cash_txn_id": db.generate_id("CashLedger"),
                    "txn_datetime": now,
                    "salesman_user_id": salesman_id,
                    "txn_type": "SALE_REFUND",
                    "amount": -bill_total,
                    "payment_method": "CASH",
                    "related_sale_id": sale_id,
                    "related_expense_id": "",
                    "issued_by_user_id": salesman_id,
                    "received_by_user_id": str(match.get("customer_id", "")),
                    "confirmed_by_user_id": user_id,
                    "reference_id": f"CANCEL-{bill_number}",
                    "notes": f"Cash refund reversal for cancelled bill {bill_number}",
                }, raise_on_error=True)

        # 3. Update Sales record status
        updated = db.update_record("Sales", "sale_id", sale_id, {
            "bill_status": "CANCELLED",
            "notes": f"{match.get('notes', '')} [CANCELLED:{now}:{user_id}:{reason_text}]".strip(),
        }, raise_on_error=True)
        if not updated:
            raise HTTPException(status_code=503, detail="Could not update bill status to CANCELLED.")

        db.log_audit(user_id, "CANCEL_BILL", "Sales", sale_id, reason=f"Cancelled bill {bill_number} for ₹{bill_total:.2f}. Reason: {reason_text}")

        # Double-Entry Accounting Compensating Reversal Voucher
        try:
            from app.accounting.journal_engine import reverse_journal_voucher
            reverse_journal_voucher(
                voucher_type="SALES_REVERSAL",
                reference_type="SALE_INVOICE",
                reference_id=sale_id,
                reason=reason_text,
                reversed_by=user_id,
            )
        except Exception:
            pass

        return {"ok": True, "message": f"Bill {bill_number} cancelled and stock/payment reversed successfully."}


@router.post("/{sale_id}/payments", dependencies=[Depends(require_sheets_connection)])
async def record_sale_payment(
    sale_id: str,
    payload: SalePaymentCreate,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.get("user_id", "")).strip()
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

        # Idempotency and conflicting replay detection
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
        payment_id = db.generate_id("Payments")
        pay_method = str(payload.payment_method or "CASH").upper()
        ref_num = payload.reference_number or str(sale.get("bill_number", ""))
        notes_text = payload.notes or f"Customer collection against bill {sale.get('bill_number')}"
        if clean_key:
            notes_text = f"[idemp:{clean_key}] {notes_text}".strip()

        payment_record = {
            "payment_id": payment_id,
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
        db.append_record("Payments", payment_record, raise_on_error=True)

        if pay_method == "CASH":
            try:
                db.append_record("CashLedger", {
                    "cash_txn_id": db.generate_id("CashLedger"),
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
                }, raise_on_error=True)
            except Exception as cash_err:
                try:
                    db.delete_record("Payments", "payment_id", payment_id)
                except Exception:
                    pass
                raise HTTPException(503, f"Failed to persist CashLedger entry: {cash_err}. Payment rolled back.")

        new_total_paid = round(total_paid_so_far + payload.amount, 2)
        new_balance = max(0.0, round(bill_total - new_total_paid, 2))
        new_status = "PAID" if new_balance <= 0.05 else "PARTIALLY_PAID"

        db.update_record("Sales", "sale_id", sale_id, {
            "payment_status": new_status,
        }, raise_on_error=True)

        db.log_audit(
            user_id,
            "RECORD_PAYMENT",
            "Payments",
            payment_id,
            reason=f"Recorded {pay_method} collection of ₹{payload.amount:.2f} for bill {sale.get('bill_number')}",
        )

        journal_res = None
        try:
            from app.accounting.postings import post_payment_collection_journal
            journal_res = post_payment_collection_journal(payment_record, actor=username)
        except Exception as e:
            import logging
            logging.error(f"Non-fatal accounting posting error for payment {payment_id}: {e}")
            try:
                import json
                db.append_record("IncompleteTransactions", {
                    "transaction_id": db.generate_id("IncompleteTransactions"),
                    "transaction_type": "ACCOUNTING_POSTING_PENDING",
                    "idempotency_key": f"acct-pay-{payment_id}",
                    "status": "POSTING_FAILED",
                    "payload_json": json.dumps({"payment_id": payment_id, "type": "CUSTOMER_PAYMENT"}),
                    "error_details": str(e),
                    "created_at": now,
                    "updated_at": now,
                })
            except Exception:
                pass

        return {
            "ok": True,
            "payment_id": payment_id,
            "sale_id": sale_id,
            "amount_paid": round(payload.amount, 2),
            "remaining_balance": new_balance,
            "payment_status": new_status,
            "journal_result": journal_res,
        }


@router.get("/orders")
async def list_sales_orders(current_user: dict = Depends(get_current_user)):
    """List sales orders, distinguishing quotations, drafts, and confirmed orders."""
    user_id = str(current_user.get("user_id", ""))
    sales_records = db.get_records("Sales", fresh=True)
    items_records = db.get_records("SaleItems", fresh=True)
    items_by_sale: Dict[str, List[SaleItem]] = {}
    for row in items_records:
        items_by_sale.setdefault(str(row.get("sale_id", "")), []).append(_to_item(row))

    orders = []
    for row in sales_records:
        salesman_id = str(row.get("salesman_user_id", ""))
        if not is_manager(current_user) and salesman_id != user_id and str(row.get("entered_by_user_id", "")) != user_id:
            continue
        status = str(row.get("bill_status", "")).upper()
        if status in {"DRAFT", "ORDER_CONFIRMED", "ORDER_DRAFT"}:
            orders.append(_to_sale(row, items_by_sale.get(str(row.get("sale_id")), [])))
    return orders


@router.post("/orders", response_model=Sale, dependencies=[Depends(require_sheets_connection)])
async def create_sales_order(req: SaleCreate, current_user: dict = Depends(get_current_user)):
    """Create a sales order in DRAFT status with stock availability verification without immediate deduction."""
    user_id = str(current_user.get("user_id") or "")
    salesman_id = _clean(req.salesman_user_id) or user_id
    customer_id = _clean(req.customer_id)

    customers = db.get_records("Customers", fresh=True)
    cust = next((c for c in customers if str(c.get("customer_id")) == customer_id), None)
    cust_name = str(cust.get("shop_name") or cust.get("shopkeeper_name") or "Direct Customer") if cust else "Direct Customer"

    sale_id = db.generate_id("Sales")
    order_num = f"SO-{db.generate_id('Sales').replace('SALE-', '')}"
    now = now_iso()

    # Pre-check product availability
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
            "sale_item_id": db.generate_id("SaleItems"),
            "sale_id": sale_id,
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

    order_record = {
        "sale_id": sale_id,
        "bill_number": order_num,
        "idempotency_key": req.idempotency_key or f"SO-{sale_id}",
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

    db.append_record("Sales", order_record, raise_on_error=True)
    for itm in line_items:
        db.append_record("SaleItems", itm, raise_on_error=True)

    db.log_audit(user_id, "CREATE_SALES_ORDER", "Sales", sale_id, reason=f"Created sales order {order_num} for ₹{bill_total:.2f}")
    return _to_sale(order_record, [_to_item(i) for i in line_items])


@router.post("/orders/{sale_id}/confirm", dependencies=[Depends(require_sheets_connection)])
async def confirm_sales_order(sale_id: str, current_user: dict = Depends(get_current_user)):
    """Confirm a DRAFT sales order, generating an active invoice, deducting stock, and posting accounting voucher."""
    user_id = str(current_user.get("user_id") or "")
    async with _sales_lock:
        sales = db.get_records("Sales", fresh=True)
        sale = next((s for s in sales if str(s.get("sale_id")) == sale_id), None)
        if not sale:
            raise HTTPException(404, f"Sales order {sale_id} not found.")
        status = str(sale.get("bill_status", "")).upper()
        if status != "DRAFT":
            raise HTTPException(400, f"Cannot confirm order with status '{status}'. Must be in DRAFT state.")

        now = now_iso()
        items = _items_for(sale_id)
        salesman_id = str(sale.get("salesman_user_id") or user_id)

        # 1. Deduct stock from salesman ledger
        for itm in items:
            p_id = str(itm.get("product_id"))
            qty = int(float(itm.get("quantity", 0) or 0))
            db.append_record("SalesmanStockLedger", {
                "stock_txn_id": db.generate_id("SalesmanStockLedger"),
                "txn_datetime": now,
                "salesman_user_id": salesman_id,
                "product_id": p_id,
                "sku_snapshot": str(itm.get("sku_snapshot", "")),
                "txn_type": "SOLD_DELIVERY",
                "quantity": qty,
                "unit": "PACKET",
                "pack_weight_g": int(float(itm.get("pack_weight_g", 500) or 500)),
                "related_sale_id": sale_id,
                "issued_by_user_id": salesman_id,
                "received_by_user_id": str(sale.get("customer_id", "")),
                "confirmed_by_user_id": user_id,
                "reference_id": str(sale.get("bill_number", "")),
                "notes": f"Stock deduction for confirmed bill {sale.get('bill_number')}",
            }, raise_on_error=True)

        # 2. Update status to ISSUED
        db.update_record("Sales", "sale_id", sale_id, {
            "bill_status": "ISSUED",
            "delivery_status": "DELIVERED",
        }, raise_on_error=True)

        # 3. Post double-entry accounting journal
        try:
            from app.accounting.postings import post_sale_journal
            post_sale_journal(sale, actor=user_id)
        except Exception as acct_err:
            logger.error("Non-fatal accounting posting error for confirmed order %s: %s", sale_id, acct_err)

        db.log_audit(user_id, "CONFIRM_SALES_ORDER", "Sales", sale_id, reason=f"Confirmed and issued order {sale.get('bill_number')}")
        return {"ok": True, "sale_id": sale_id, "bill_status": "ISSUED", "message": f"Order {sale.get('bill_number')} confirmed and stock deducted."}


@router.get("/dispatch-summary")
async def sales_dispatch_summary(current_user: dict = Depends(get_current_user)):
    """Overview of sales orders, dispatches, and fulfillment status."""
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




