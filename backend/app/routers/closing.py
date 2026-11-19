import logging
from typing import List
from fastapi import APIRouter, HTTPException, Request, status, Depends
from app.apps_script_bridge import apps_script_bridge
from app.models import DailyClosing, DailyClosingCreate, ClosingReviewRequest
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager, require_module_action, require_manager
from app.stock_math import salesman_available
from app.timeutil import business_today, business_date_of, now_iso
from app.calculations.units import parse_currency_amount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/closing", tags=["Daily Closing"])


def _closing_from(record: dict) -> DailyClosing:
    return DailyClosing(
        closing_id=str(record.get("closing_id", "")),
        closing_date=str(record.get("closing_date", "")),
        salesman_user_id=str(record.get("salesman_user_id", "")),
        opening_cash=parse_currency_amount(record.get("opening_cash", 0)),
        cash_collected=parse_currency_amount(record.get("cash_collected", 0)),
        approved_cash_expenses=parse_currency_amount(record.get("approved_cash_expenses", 0)),
        expected_cash_return=parse_currency_amount(record.get("expected_cash_return", 0)),
        physical_cash_returned=parse_currency_amount(record.get("physical_cash_returned", 0)),
        cash_difference=parse_currency_amount(record.get("cash_difference", 0)),
        opening_stock_reference=str(record.get("opening_stock_reference", "")),
        stock_discrepancy_flag=str(record.get("stock_discrepancy_flag", "false")).lower() == "true",
        closing_status=str(record.get("closing_status", "SUBMITTED")),
        submitted_at=str(record.get("submitted_at", "")),
        reviewed_by_user_id=str(record.get("reviewed_by_user_id", "")),
        reviewed_at=str(record.get("reviewed_at", "")),
        notes=str(record.get("notes", "")),
        upi_collected=parse_currency_amount(record.get("upi_collected", 0)),
        bank_collected=parse_currency_amount(record.get("bank_collected", 0)),
        other_collected=parse_currency_amount(record.get("other_collected", 0)),
    )

@router.get("", response_model=List[DailyClosing])
async def list_daily_closings(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")

    records = db.get_records("DailyClosing")
    closings = []
    for r in records:
        s_user = str(r.get("salesman_user_id", ""))
        if not is_manager(current_user) and s_user != user_id:
            continue
        closings.append(_closing_from(r))
    closings.reverse()
    return closings

@router.post("", response_model=DailyClosing, dependencies=[Depends(require_sheets_connection)])
async def submit_daily_closing(req: DailyClosingCreate, request: Request, current_user: dict = Depends(get_current_user)):
    user_id, actor_role = require_module_action(current_user, "sales", "create")
    today_str = business_today()
    stamped = now_iso()
    idem = str(getattr(req, "idempotency_key", "") or "").strip()

    existing_rows = db.get_records("DailyClosing", fresh=True)
    if idem:
        prior = next((r for r in existing_rows if str(r.get("idempotency_key", "")) == idem), None)
        if prior:
            return _closing_from(prior)
    if any(str(r.get("salesman_user_id")) == user_id and str(r.get("closing_date")) == today_str and str(r.get("closing_status", "")).upper() != "CANCELLED" for r in existing_rows):
        raise HTTPException(status_code=409, detail=f"A closing for {today_str} is already submitted. Open the existing closing instead of creating another.")

    payments = db.get_records("Payments", fresh=True)
    sales = {str(s.get("sale_id")): s for s in db.get_records("Sales", fresh=True)}
    cash_collected = upi_collected = bank_collected = other_collected = 0.0
    for payment in payments:
        sale = sales.get(str(payment.get("sale_id")), {})
        if str(sale.get("salesman_user_id")) != user_id:
            continue
        if str(sale.get("txn_status", "COMPLETE")).upper() == "INCOMPLETE":
            continue
        if business_date_of(str(payment.get("payment_datetime", ""))) != today_str:
            continue
        amount = float(payment.get("amount", 0) or 0)
        method = str(payment.get("payment_method", "")).upper()
        if method == "CASH":
            cash_collected += amount
        elif method == "UPI":
            upi_collected += amount
        elif method == "BANK_TRANSFER":
            bank_collected += amount
        else:
            other_collected += amount

    expense_records = db.get_records("Expenses", fresh=True)
    approved_expenses = 0.0
    qualifying_expense_ids = []
    for expense in expense_records:
        s_user = str(expense.get("salesman_user_id") or expense.get("submitted_by_user_id") or "").strip()
        if s_user != user_id:
            continue
        exp_dt = str(expense.get("expense_datetime") or expense.get("created_at") or "").strip()
        if business_date_of(exp_dt) != today_str:
            continue
        if str(expense.get("related_closing_id", "")).strip():
            continue
        is_approved = str(expense.get("approval_status", "")).strip().upper() == "APPROVED"
        is_cash_reducing = str(expense.get("cash_reducing_expense", "")).strip().lower() in {"true", "1", "yes"}
        if is_approved and is_cash_reducing:
            try:
                amt = parse_currency_amount(expense.get("amount", 0))
                if amt > 0:
                    approved_expenses += amt
                    exp_id = str(expense.get("expense_id", "")).strip()
                    if exp_id:
                        qualifying_expense_ids.append(exp_id)
            except Exception as exp_err:
                logger.warning("Could not parse expense amount for record %s: %s", expense.get("expense_id"), exp_err)

    expected_cash = float(req.opening_cash) + cash_collected - approved_expenses
    diff = float(req.physical_cash_returned) - expected_cash
    stock_flag = False
    stock_note = req.opening_stock_reference or ""
    physical = getattr(req, "physical_stock", None) or []
    if physical:
        mismatches = []
        for count in physical:
            product_id = str(count.get("product_id", ""))
            counted = int(count.get("quantity", 0) or 0)
            expected = salesman_available(db.get_records("SalesmanStockLedger", fresh=True), user_id, product_id)
            if counted != expected:
                mismatches.append(f"{product_id}: counted {counted}, ledger {expected}")
        stock_flag = bool(mismatches)
        if mismatches:
            stock_note = (stock_note + " | " if stock_note else "") + "; ".join(mismatches)

    record = {
        "closing_date": today_str,
        "salesman_user_id": user_id,
        "opening_cash": req.opening_cash,
        "cash_collected": cash_collected,
        "approved_cash_expenses": approved_expenses,
        "expected_cash_return": expected_cash,
        "physical_cash_returned": req.physical_cash_returned,
        "cash_difference": diff,
        "opening_stock_reference": stock_note,
        "stock_discrepancy_flag": "true" if stock_flag else "false",
        "upi_collected": round(upi_collected, 2),
        "bank_collected": round(bank_collected, 2),
        "other_collected": round(other_collected, 2),
        "idempotency_key": idem,
        "closing_status": "SUBMITTED",
        "submitted_at": stamped,
        "reviewed_by_user_id": "",
        "reviewed_at": "",
        "notes": req.notes or "",
        "qualifying_expense_ids": qualifying_expense_ids,
    }
    res = apps_script_bridge.delegate_governed_write(
        action="SUBMIT_DAILY_CLOSING",
        target_tab="DailyClosing",
        payload=record,
        nonce=idem or None,
        request=request,
        actor_user_id=user_id,
        actor_role=actor_role,
        id_field="closing_id",
        invalidate_tabs=["DailyClosing", "Expenses", "JournalHeaders", "JournalLines"],
    )
    closing_id = str(res.get("allocated_id") or "")

    db.log_audit(
        actor=user_id,
        action="SUBMIT_DAILY_CLOSING",
        entity_type="DailyClosing",
        entity_id=closing_id,
        reason=f"Submitted closing for {today_str}: expected ₹{expected_cash}, returned ₹{req.physical_cash_returned} (diff ₹{diff})"
    )

    return _closing_from({**record, "closing_id": closing_id})


@router.post("/{closing_id}/review", response_model=DailyClosing, dependencies=[Depends(require_sheets_connection)])
async def review_daily_closing(closing_id: str, req: ClosingReviewRequest, request: Request, current_user: dict = Depends(get_current_user)):
    user_id, actor_role = require_manager(current_user)
    stamped = now_iso()
    new_status = "CONFIRMED" if req.confirmed else "NEEDS_CORRECTION"

    records = db.get_records("DailyClosing")
    matched = next((r for r in records if str(r.get("closing_id")) == closing_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"Closing {closing_id} not found")

    updates = {
        "closing_id": closing_id,
        "closing_status": new_status,
        "reviewed_by_user_id": user_id,
        "reviewed_at": stamped,
        "notes": req.notes or "",
    }
    apps_script_bridge.delegate_governed_write(
        action="REVIEW_DAILY_CLOSING",
        target_tab="DailyClosing",
        payload=updates,
        request=request,
        actor_user_id=user_id,
        actor_role=actor_role,
        id_field="closing_id",
        invalidate_tabs=["DailyClosing"],
    )

    db.log_audit(
        actor=user_id,
        action="REVIEW_CLOSING",
        entity_type="DailyClosing",
        entity_id=closing_id,
        reason=f"{new_status} closing {closing_id}"
    )

    return _closing_from({**matched, **updates})
