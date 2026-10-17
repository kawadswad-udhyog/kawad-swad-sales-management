from typing import List
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import DailyClosing, DailyClosingCreate, ClosingReviewRequest
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager
from app.stock_math import salesman_available
from app.timeutil import business_today, business_date_of, now_iso

router = APIRouter(prefix="/api/closing", tags=["Daily Closing"])


def _closing_from(record: dict) -> DailyClosing:
    return DailyClosing(
        closing_id=str(record.get("closing_id", "")),
        closing_date=str(record.get("closing_date", "")),
        salesman_user_id=str(record.get("salesman_user_id", "")),
        opening_cash=float(record.get("opening_cash", 0) or 0),
        cash_collected=float(record.get("cash_collected", 0) or 0),
        approved_cash_expenses=float(record.get("approved_cash_expenses", 0) or 0),
        expected_cash_return=float(record.get("expected_cash_return", 0) or 0),
        physical_cash_returned=float(record.get("physical_cash_returned", 0) or 0),
        cash_difference=float(record.get("cash_difference", 0) or 0),
        opening_stock_reference=str(record.get("opening_stock_reference", "")),
        stock_discrepancy_flag=str(record.get("stock_discrepancy_flag", "false")).lower() == "true",
        closing_status=str(record.get("closing_status", "SUBMITTED")),
        submitted_at=str(record.get("submitted_at", "")),
        reviewed_by_user_id=str(record.get("reviewed_by_user_id", "")),
        reviewed_at=str(record.get("reviewed_at", "")),
        notes=str(record.get("notes", "")),
        upi_collected=float(record.get("upi_collected", 0) or 0),
        bank_collected=float(record.get("bank_collected", 0) or 0),
        other_collected=float(record.get("other_collected", 0) or 0),
    )

@router.get("", response_model=List[DailyClosing])
async def list_daily_closings(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = current_user.get("role", "").upper()

    records = db.get_records("DailyClosing")
    closings = []
    for r in records:
        s_user = str(r.get("salesman_user_id", ""))
        if not is_manager(current_user) and s_user != user_id:
            continue
        closings.append(DailyClosing(
            closing_id=str(r.get("closing_id", "")),
            closing_date=str(r.get("closing_date", "")),
            salesman_user_id=s_user,
            opening_cash=float(r.get("opening_cash", 0.0) or 0.0),
            cash_collected=float(r.get("cash_collected", 0.0) or 0.0),
            approved_cash_expenses=float(r.get("approved_cash_expenses", 0.0) or 0.0),
            expected_cash_return=float(r.get("expected_cash_return", 0.0) or 0.0),
            physical_cash_returned=float(r.get("physical_cash_returned", 0.0) or 0.0),
            cash_difference=float(r.get("cash_difference", 0.0) or 0.0),
            opening_stock_reference=str(r.get("opening_stock_reference", "")),
            stock_discrepancy_flag=str(r.get("stock_discrepancy_flag", "false")).lower() == "true",
            closing_status=str(r.get("closing_status", "SUBMITTED")),
            submitted_at=str(r.get("submitted_at", "")),
            reviewed_by_user_id=str(r.get("reviewed_by_user_id", "")),
            reviewed_at=str(r.get("reviewed_at", "")),
            notes=str(r.get("notes", "")),
        ))
    closings.reverse()
    return closings

@router.post("", response_model=DailyClosing, dependencies=[Depends(require_sheets_connection)])
async def submit_daily_closing(req: DailyClosingCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
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
    for expense in expense_records:
        if str(expense.get("salesman_user_id")) != user_id:
            continue
        if business_date_of(str(expense.get("expense_datetime", ""))) != today_str:
            continue
        if str(expense.get("approval_status", "")).upper() == "APPROVED" and str(expense.get("cash_reducing_expense", "")).lower() == "true":
            approved_expenses += float(expense.get("amount", 0) or 0)

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

    closing_id = db.generate_id("DailyClosing")
    record = {
        "closing_id": closing_id,
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
    }
    if not db.append_record("DailyClosing", record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="The daily closing was not saved.")

    db.log_audit(
        actor=user_id,
        action="SUBMIT_DAILY_CLOSING",
        entity_type="DailyClosing",
        entity_id=closing_id,
        reason=f"Submitted closing for {today_str}: expected ₹{expected_cash}, returned ₹{req.physical_cash_returned} (diff ₹{diff})"
    )

    return _closing_from(record)

@router.post("/{closing_id}/review", response_model=DailyClosing, dependencies=[Depends(require_sheets_connection)])
async def review_daily_closing(closing_id: str, req: ClosingReviewRequest, current_user: dict = Depends(get_current_user)):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can review closing")

    user_id = current_user.get("user_id")
    stamped = now_iso()
    new_status = "CONFIRMED" if req.confirmed else "NEEDS_CORRECTION"

    updates = {
        "closing_status": new_status,
        "reviewed_by_user_id": user_id,
        "reviewed_at": stamped,
        "notes": req.notes or "",
    }
    if not db.update_record("DailyClosing", "closing_id", closing_id, updates):
        raise HTTPException(status_code=503, detail="The closing review was not saved.")

    db.log_audit(
        actor=user_id,
        action="REVIEW_CLOSING",
        entity_type="DailyClosing",
        entity_id=closing_id,
        reason=f"{new_status} closing {closing_id}"
    )

    records = db.get_records("DailyClosing")
    matched = next((r for r in records if str(r.get("closing_id")) == closing_id), {})
    return DailyClosing(
        closing_id=closing_id,
        closing_date=str(matched.get("closing_date", "")),
        salesman_user_id=str(matched.get("salesman_user_id", "")),
        opening_cash=float(matched.get("opening_cash", 0.0) or 0.0),
        cash_collected=float(matched.get("cash_collected", 0.0) or 0.0),
        approved_cash_expenses=float(matched.get("approved_cash_expenses", 0.0) or 0.0),
        expected_cash_return=float(matched.get("expected_cash_return", 0.0) or 0.0),
        physical_cash_returned=float(matched.get("physical_cash_returned", 0.0) or 0.0),
        cash_difference=float(matched.get("cash_difference", 0.0) or 0.0),
        opening_stock_reference=str(matched.get("opening_stock_reference", "")),
        stock_discrepancy_flag=str(matched.get("stock_discrepancy_flag", "false")).lower() == "true",
        closing_status=new_status,
        submitted_at=str(matched.get("submitted_at", stamped)),
        reviewed_by_user_id=user_id,
        reviewed_at=stamped,
        notes=req.notes or "",
    )
