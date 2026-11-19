from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, HTTPException, Request, status, Depends
from app.apps_script_bridge import apps_script_bridge
from app.models import Expense, ExpenseCreate, ExpenseApproveRequest
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import has_permission, is_manager, is_salesman, require_module_action, require_manager
from app.calculations.units import parse_currency_amount

router = APIRouter(prefix="/api/expenses", tags=["Expenses"])

@router.get("", response_model=List[Expense])
async def list_expenses(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    if not has_permission(current_user, "expenses", "view") and not has_permission(current_user, "expenses", "view_own"):
        raise HTTPException(status_code=403, detail="Permission denied for 'expenses:view'.")

    records = db.get_records("Expenses")
    expenses = []
    for r in records:
        s_user = str(r.get("salesman_user_id") or r.get("submitted_by_user_id") or "")
        sub_user = str(r.get("submitted_by_user_id") or r.get("salesman_user_id") or "")
        if not is_manager(current_user) and user_id not in [s_user, sub_user]:
            continue
        expenses.append(Expense(
            expense_id=str(r.get("expense_id", "")),
            expense_datetime=str(r.get("expense_datetime", "")),
            submitted_by_user_id=sub_user,
            salesman_user_id=s_user,
            category=str(r.get("category", "Petrol / Travel")),
            amount=parse_currency_amount(r.get("amount", 0.0)),
            description=str(r.get("description", "")),
            receipt_link_or_file_ref=str(r.get("receipt_link_or_file_ref") or r.get("receipt_image_url") or ""),
            approval_status=str(r.get("approval_status", "PENDING")),
            approved_by_user_id=str(r.get("approved_by_user_id", "")),
            approval_datetime=str(r.get("approval_datetime") or r.get("approved_datetime") or ""),
            cash_reducing_expense=str(r.get("cash_reducing_expense", "false")).strip().lower() in {"true", "1", "yes"},
            related_closing_id=str(r.get("related_closing_id", "")),
            notes=str(r.get("notes", "")),
        ))
    expenses.reverse()
    return expenses

@router.post("", response_model=Expense, dependencies=[Depends(require_sheets_connection)])
async def submit_expense(req: ExpenseCreate, request: Request, current_user: dict = Depends(get_current_user)):
    user_id, actor_role = require_module_action(current_user, "expenses", "create")
    salesman_id = req.salesman_user_id or user_id
    if is_salesman(current_user) and salesman_id != user_id:
        raise HTTPException(status_code=403, detail="A salesman can only submit an expense for themselves.")
    now_iso_str = datetime.now(timezone.utc).isoformat()

    record = {
        "expense_datetime": now_iso_str,
        "submitted_by_user_id": user_id,
        "salesman_user_id": salesman_id,
        "category": req.category,
        "amount": req.amount,
        "description": req.description,
        "receipt_link_or_file_ref": req.receipt_link_or_file_ref or "",
        "receipt_image_url": req.receipt_link_or_file_ref or "",
        "approval_status": "PENDING",
        "approved_by_user_id": "",
        "approval_datetime": "",
        "approved_datetime": "",
        "cash_reducing_expense": "false",
        "related_closing_id": "",
        "notes": req.notes or "",
    }
    res = apps_script_bridge.delegate_governed_write(
        action="SUBMIT_EXPENSE",
        target_tab="Expenses",
        payload=record,
        request=request,
        actor_user_id=user_id,
        actor_role=actor_role,
        id_field="expense_id",
        invalidate_tabs=["Expenses"],
    )
    expense_id = str(res.get("allocated_id") or "")

    db.log_audit(
        actor=user_id,
        action="SUBMIT_EXPENSE",
        entity_type="Expenses",
        entity_id=expense_id,
        reason=f"Submitted expense ₹{req.amount} under {req.category}"
    )

    return Expense(expense_id=expense_id, **{**record, "cash_reducing_expense": False})

@router.post("/{expense_id}/approve", response_model=Expense, dependencies=[Depends(require_sheets_connection)])
async def review_expense(expense_id: str, req: ExpenseApproveRequest, request: Request, current_user: dict = Depends(get_current_user)):
    user_id, actor_role = require_manager(current_user)
    now_iso_str = datetime.now(timezone.utc).isoformat()
    status_str = "APPROVED" if req.approved else "REJECTED"

    records = db.get_records("Expenses")
    matched = next((r for r in records if str(r.get("expense_id")) == expense_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")

    is_cash_red = req.cash_reducing if getattr(req, "cash_reducing", None) is not None else req.approved
    updates = {
        "expense_id": expense_id,
        "approval_status": status_str,
        "approved_by_user_id": user_id,
        "approval_datetime": now_iso_str,
        "approved_datetime": now_iso_str,
        "cash_reducing_expense": "true" if is_cash_red else "false",
        "notes": req.notes or "",
        "post_accounting_journal": bool(req.approved),
    }
    apps_script_bridge.delegate_governed_write(
        action="REVIEW_EXPENSE",
        target_tab="Expenses",
        payload=updates,
        request=request,
        actor_user_id=user_id,
        actor_role=actor_role,
        id_field="expense_id",
        invalidate_tabs=["Expenses", "JournalHeaders", "JournalLines"],
    )

    db.log_audit(
        actor=user_id,
        action="REVIEW_EXPENSE",
        entity_type="Expenses",
        entity_id=expense_id,
        reason=f"{status_str} expense {expense_id}: {req.notes or 'No remarks'}"
    )

    return Expense(
        expense_id=expense_id,
        expense_datetime=str(matched.get("expense_datetime", now_iso_str)),
        submitted_by_user_id=str(matched.get("submitted_by_user_id") or matched.get("salesman_user_id") or ""),
        salesman_user_id=str(matched.get("salesman_user_id") or matched.get("submitted_by_user_id") or ""),
        category=str(matched.get("category", "")),
        amount=parse_currency_amount(matched.get("amount", 0.0)),
        description=str(matched.get("description", "")),
        receipt_link_or_file_ref=str(matched.get("receipt_link_or_file_ref") or matched.get("receipt_image_url") or ""),
        approval_status=status_str,
        approved_by_user_id=user_id,
        approval_datetime=now_iso_str,
        cash_reducing_expense=bool(is_cash_red),
        related_closing_id=str(matched.get("related_closing_id", "")),
        notes=req.notes or "",
    )
