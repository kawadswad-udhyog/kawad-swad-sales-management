"""
Kawad Swad ERP - Double-Entry General Ledger Accounting API Router
Provides endpoints for Chart of Accounts, Trial Balance, P&L, Balance Sheet, and Journal Vouchers.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.sheets import db
from app.permissions import is_manager
from app.accounting.chart_of_accounts import CHART_OF_ACCOUNTS
from app.accounting.journal_engine import (
    calculate_trial_balance,
    calculate_profit_and_loss,
    calculate_balance_sheet,
    post_journal_voucher,
    reverse_journal_voucher,
)

router = APIRouter(prefix="/api/accounting", tags=["Accounting"])


def require_accounting_access(user: dict):
    role = str(user.get("role", "")).upper()
    if role not in {"OWNER", "OWNER_ADMIN", "ADMIN", "ACCOUNTANT", "PA"}:
        raise HTTPException(403, "Access restricted to Owner, Admin, or Accountant.")
    return str(user.get("user_id", "")), role


class JournalLineInput(BaseModel):
    account_code: str
    debit_amount: float = Field(0.0, ge=0)
    credit_amount: float = Field(0.0, ge=0)
    entity_type: Optional[str] = ""
    entity_id: Optional[str] = ""
    notes: Optional[str] = ""


class ManualJournalVoucherCreate(BaseModel):
    voucher_type: str = "GENERAL"
    reference_type: str = "MANUAL_JOURNAL"
    reference_id: str = ""
    narration: str = Field(..., min_length=3)
    journal_date: Optional[str] = None
    lines: List[JournalLineInput] = Field(..., min_length=2)


class ReversalRequest(BaseModel):
    reason: str = Field(..., min_length=3)


@router.get("/chart-of-accounts")
async def get_chart_of_accounts(user: dict = Depends(get_current_user)):
    require_accounting_access(user)
    return CHART_OF_ACCOUNTS


@router.get("/trial-balance")
async def get_trial_balance_report(
    as_of_date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    require_accounting_access(user)
    return calculate_trial_balance(as_of_date=as_of_date)


@router.get("/profit-and-loss")
async def get_profit_and_loss_report(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    require_accounting_access(user)
    return calculate_profit_and_loss(start_date=start_date, end_date=end_date)


@router.get("/balance-sheet")
async def get_balance_sheet_report(
    as_of_date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    require_accounting_access(user)
    return calculate_balance_sheet(as_of_date=as_of_date)


@router.get("/vouchers")
async def list_journal_vouchers(
    limit: int = 100,
    user: dict = Depends(get_current_user),
):
    require_accounting_access(user)
    headers = db.get_records("JournalHeaders", fresh=True)
    lines = db.get_records("JournalLines", fresh=True)

    lines_by_journal: Dict[str, list] = {}
    for l in lines:
        lines_by_journal.setdefault(str(l.get("journal_id")), []).append(l)

    result = []
    for h in reversed(headers[-limit:]):
        jid = str(h.get("journal_id"))
        result.append({
            **h,
            "lines": lines_by_journal.get(jid, []),
        })
    return result


@router.post("/vouchers")
async def create_manual_journal_voucher(
    req: ManualJournalVoucherCreate,
    user: dict = Depends(get_current_user),
):
    actor, _ = require_accounting_access(user)
    try:
        voucher = post_journal_voucher(
            voucher_type=req.voucher_type,
            reference_type=req.reference_type,
            reference_id=req.reference_id or f"MAN-{int(id(req))}",
            narration=req.narration,
            lines=[l.model_dump() if hasattr(l, 'model_dump') else l.dict() for l in req.lines],
            posted_by=actor,
            journal_date=req.journal_date,
        )
        return voucher
    except ValueError as val_err:
        raise HTTPException(422, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to post journal voucher: {exc}")


@router.post("/vouchers/{journal_id}/reverse")
async def reverse_voucher(
    journal_id: str,
    req: ReversalRequest,
    user: dict = Depends(get_current_user),
):
    actor, _ = require_accounting_access(user)
    try:
        rev = reverse_journal_voucher(journal_id=journal_id, reason=req.reason, actor=actor)
        return rev
    except ValueError as val_err:
        raise HTTPException(400, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to reverse voucher: {exc}")
