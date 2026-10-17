from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import Expense, ExpenseCreate, ExpenseApproveRequest
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection

router = APIRouter(prefix="/api/expenses", tags=["Expenses"])

@router.get("", response_model=List[Expense])
async def list_expenses(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = current_user.get("role", "").upper()

    records = db.get_records("Expenses")
    expenses = []
    for r in records:
        s_user = str(r.get("salesman_user_id", ""))
        sub_user = str(r.get("submitted_by_user_id", ""))
        if role not in ["OWNER", "OWNER_ADMIN", "PA"] and user_id not in [s_user, sub_user]:
            continue
        expenses.append(Expense(
            expense_id=str(r.get("expense_id", "")),
            expense_datetime=str(r.get("expense_datetime", "")),
            submitted_by_user_id=sub_user,
            salesman_user_id=s_user,
            category=str(r.get("category", "Petrol / Travel")),
            amount=float(r.get("amount", 0.0) or 0.0),
            description=str(r.get("description", "")),
            receipt_link_or_file_ref=str(r.get("receipt_link_or_file_ref", "")),
            approval_status=str(r.get("approval_status", "PENDING")),
            approved_by_user_id=str(r.get("approved_by_user_id", "")),
            approval_datetime=str(r.get("approval_datetime", "")),
            cash_reducing_expense=str(r.get("cash_reducing_expense", "false")).lower() == "true",
            related_closing_id=str(r.get("related_closing_id", "")),
            notes=str(r.get("notes", "")),
        ))
    expenses.reverse()
    return expenses

@router.post("", response_model=Expense, dependencies=[Depends(require_sheets_connection)])
async def submit_expense(req: ExpenseCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    salesman_id = req.salesman_user_id or user_id
    now_iso = datetime.utcnow().isoformat()
    expense_id = db.generate_id("Expenses")

    record = {
        "expense_id": expense_id,
        "expense_datetime": now_iso,
        "submitted_by_user_id": user_id,
        "salesman_user_id": salesman_id,
        "category": req.category,
        "amount": req.amount,
        "description": req.description,
        "receipt_link_or_file_ref": req.receipt_link_or_file_ref or "",
        "approval_status": "PENDING",
        "approved_by_user_id": "",
        "approval_datetime": "",
        "cash_reducing_expense": "false",
        "related_closing_id": "",
        "notes": req.notes or "",
    }
    db.append_record("Expenses", record)

    db.log_audit(
        actor=user_id,
        action="SUBMIT_EXPENSE",
        entity_type="Expenses",
        entity_id=expense_id,
        reason=f"Submitted expense ₹{req.amount} under {req.category}"
    )

    return Expense(**record, cash_reducing_expense=False)

@router.post("/{expense_id}/approve", response_model=Expense, dependencies=[Depends(require_sheets_connection)])
async def review_expense(expense_id: str, req: ExpenseApproveRequest, current_user: dict = Depends(get_current_user)):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can approve expenses")

    user_id = current_user.get("user_id")
    now_iso = datetime.utcnow().isoformat()
    status_str = "APPROVED" if req.approved else "REJECTED"

    updates = {
        "approval_status": status_str,
        "approved_by_user_id": user_id,
        "approval_datetime": now_iso,
        "cash_reducing_expense": "true" if req.approved else "false",
        "notes": req.notes or "",
    }
    db.update_record("Expenses", "expense_id", expense_id, updates)

    db.log_audit(
        actor=user_id,
        action="REVIEW_EXPENSE",
        entity_type="Expenses",
        entity_id=expense_id,
        reason=f"{status_str} expense {expense_id}: {req.notes or 'No remarks'}"
    )

    records = db.get_records("Expenses")
    matched = next((r for r in records if str(r.get("expense_id")) == expense_id), {})
    return Expense(
        expense_id=expense_id,
        expense_datetime=str(matched.get("expense_datetime", now_iso)),
        submitted_by_user_id=str(matched.get("submitted_by_user_id", "")),
        salesman_user_id=str(matched.get("salesman_user_id", "")),
        category=str(matched.get("category", "")),
        amount=float(matched.get("amount", 0.0) or 0.0),
        description=str(matched.get("description", "")),
        receipt_link_or_file_ref=str(matched.get("receipt_link_or_file_ref", "")),
        approval_status=status_str,
        approved_by_user_id=user_id,
        approval_datetime=now_iso,
        cash_reducing_expense=req.approved,
        related_closing_id=str(matched.get("related_closing_id", "")),
        notes=req.notes or "",
    )
