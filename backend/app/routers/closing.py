from datetime import datetime, date
from typing import List
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import DailyClosing, DailyClosingCreate, ClosingReviewRequest
from app.sheets import db
from app.auth import get_current_user

router = APIRouter(prefix="/api/closing", tags=["Daily Closing"])

@router.get("", response_model=List[DailyClosing])
async def list_daily_closings(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = current_user.get("role", "").upper()

    records = db.get_records("DailyClosing")
    closings = []
    for r in records:
        s_user = str(r.get("salesman_user_id", ""))
        if role not in ["OWNER", "OWNER_ADMIN", "PA"] and s_user != user_id:
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

@router.post("", response_model=DailyClosing)
async def submit_daily_closing(req: DailyClosingCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    today_str = date.today().isoformat()
    now_iso = datetime.utcnow().isoformat()

    # Calculate today's cash collections from CashLedger
    cash_records = db.get_records("CashLedger")
    cash_collected = 0.0
    for c in cash_records:
        if str(c.get("salesman_user_id")) == user_id and str(c.get("txn_datetime", "")).startswith(today_str):
            if str(c.get("txn_type", "")).upper() == "SALE_COLLECTION":
                cash_collected += float(c.get("amount", 0.0) or 0.0)

    # Calculate today's approved cash expenses
    expense_records = db.get_records("Expenses")
    approved_expenses = 0.0
    for e in expense_records:
        if str(e.get("salesman_user_id")) == user_id and str(e.get("expense_datetime", "")).startswith(today_str):
            if str(e.get("approval_status", "")).upper() == "APPROVED" and str(e.get("cash_reducing_expense", "")).lower() == "true":
                approved_expenses += float(e.get("amount", 0.0) or 0.0)

    expected_cash = req.opening_cash + cash_collected - approved_expenses
    diff = req.physical_cash_returned - expected_cash

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
        "opening_stock_reference": req.opening_stock_reference or "",
        "stock_discrepancy_flag": "false",
        "closing_status": "SUBMITTED",
        "submitted_at": now_iso,
        "reviewed_by_user_id": "",
        "reviewed_at": "",
        "notes": req.notes or "",
    }
    db.append_record("DailyClosing", record)

    db.log_audit(
        actor=user_id,
        action="SUBMIT_DAILY_CLOSING",
        entity_type="DailyClosing",
        entity_id=closing_id,
        reason=f"Submitted closing for {today_str}: expected ₹{expected_cash}, returned ₹{req.physical_cash_returned} (diff ₹{diff})"
    )

    return DailyClosing(**record, stock_discrepancy_flag=False)

@router.post("/{closing_id}/review", response_model=DailyClosing)
async def review_daily_closing(closing_id: str, req: ClosingReviewRequest, current_user: dict = Depends(get_current_user)):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can review closing")

    user_id = current_user.get("user_id")
    now_iso = datetime.utcnow().isoformat()
    new_status = "CONFIRMED" if req.confirmed else "NEEDS_CORRECTION"

    updates = {
        "closing_status": new_status,
        "reviewed_by_user_id": user_id,
        "reviewed_at": now_iso,
        "notes": req.notes or "",
    }
    db.update_record("DailyClosing", "closing_id", closing_id, updates)

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
        submitted_at=str(matched.get("submitted_at", now_iso)),
        reviewed_by_user_id=user_id,
        reviewed_at=now_iso,
        notes=req.notes or "",
    )
