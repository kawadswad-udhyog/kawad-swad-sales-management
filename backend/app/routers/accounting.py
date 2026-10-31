"""
Kawad Swad ERP - Double-Entry General Ledger Accounting API Router
Provides endpoints for Chart of Accounts, Trial Balance, P&L, Balance Sheet, and Journal Vouchers.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.sheets import db
from app.permissions import is_manager, is_owner
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


@router.get("/reconcile")
async def audit_reconcile_get(
    user: dict = Depends(get_current_user),
):
    require_accounting_access(user)
    from app.accounting.reconciliation import audit_and_reconcile_operational_events
    return audit_and_reconcile_operational_events(dry_run=True)


@router.post("/reconcile")
async def audit_reconcile_post(
    dry_run: bool = Query(True),
    confirm_live_backfill: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    actor, role = require_accounting_access(user)
    if not dry_run:
        if role not in {"OWNER", "OWNER_ADMIN", "ADMIN"}:
            raise HTTPException(403, "Live accounting backfill writes are restricted to Owner or Admin.")
        if not confirm_live_backfill:
            raise HTTPException(400, "To execute live journal backfill writes, confirm_live_backfill=true must be explicitly passed.")

    from app.accounting.reconciliation import audit_and_reconcile_operational_events
    return audit_and_reconcile_operational_events(dry_run=dry_run, actor=actor)


@router.get("/opening-balances/proposal")
async def get_opening_balance_proposal(
    user: dict = Depends(get_current_user),
):
    require_accounting_access(user)
    from app.accounting.reconciliation import propose_opening_balances
    return propose_opening_balances()


@router.get("/debtors")
async def get_customer_outstanding_balances(
    user: dict = Depends(get_current_user),
):
    """Customer accounts receivable aging and outstanding balances."""
    require_accounting_access(user)
    sales = db.get_records("Sales", fresh=True)
    payments = db.get_records("Payments", fresh=True)
    customers = {str(c.get("customer_id")): c for c in db.get_records("Customers", fresh=True)}

    debtor_map: Dict[str, Dict[str, Any]] = {}
    for s in sales:
        cid = str(s.get("customer_id", "")).strip()
        if not cid:
            continue
        c_meta = customers.get(cid, {})
        c_name = str(s.get("customer_name_snapshot") or c_meta.get("shop_name") or c_meta.get("shopkeeper_name") or cid)
        st = str(s.get("bill_status", "")).upper()
        if st in {"CANCELLED"}:
            continue
        bill_tot = float(s.get("bill_total", 0) or 0)
        if cid not in debtor_map:
            debtor_map[cid] = {
                "customer_id": cid,
                "customer_name": c_name,
                "city": str(c_meta.get("city", "")),
                "total_invoiced": 0.0,
                "total_collected": 0.0,
                "outstanding_balance": 0.0,
                "unpaid_invoices_count": 0,
            }
        debtor_map[cid]["total_invoiced"] = round(debtor_map[cid]["total_invoiced"] + bill_tot, 2)
        if str(s.get("payment_status", "")).upper() != "PAID":
            debtor_map[cid]["unpaid_invoices_count"] += 1

    for p in payments:
        amt = float(p.get("amount", 0) or 0)
        st = str(p.get("payment_status", "")).upper()
        if st in {"REFUNDED"}:
            continue
        sid = str(p.get("sale_id", "")).strip()
        target_sale = next((s for s in sales if str(s.get("sale_id")) == sid), None)
        if target_sale:
            cid = str(target_sale.get("customer_id", "")).strip()
            if cid in debtor_map:
                debtor_map[cid]["total_collected"] = round(debtor_map[cid]["total_collected"] + amt, 2)

    for item in debtor_map.values():
        item["outstanding_balance"] = max(0.0, round(item["total_invoiced"] - item["total_collected"], 2))

    debtors_list = [d for d in debtor_map.values() if d["outstanding_balance"] > 0 or d["total_invoiced"] > 0]
    debtors_list.sort(key=lambda x: x["outstanding_balance"], reverse=True)
    return debtors_list


@router.get("/creditors")
async def get_supplier_outstanding_balances(
    user: dict = Depends(get_current_user),
):
    """Supplier accounts payable aging and outstanding balances."""
    require_accounting_access(user)
    bills = db.get_records("SupplierBills", fresh=True)
    suppliers = {str(s.get("supplier_id")): s for s in db.get_records("Suppliers", fresh=True)}

    creditor_map: Dict[str, Dict[str, Any]] = {}
    for b in bills:
        sid = str(b.get("supplier_id", "")).strip()
        if not sid:
            continue
        s_meta = suppliers.get(sid, {})
        s_name = str(b.get("supplier_name") or s_meta.get("supplier_name") or sid)
        tot = float(b.get("total_amount", 0) or 0)
        paid = float(b.get("paid_amount", 0) or 0)
        bal = float(b.get("balance_amount", 0) or 0)

        if sid not in creditor_map:
            creditor_map[sid] = {
                "supplier_id": sid,
                "supplier_name": s_name,
                "total_billed": 0.0,
                "total_paid": 0.0,
                "outstanding_payable": 0.0,
                "open_bills_count": 0,
            }
        creditor_map[sid]["total_billed"] = round(creditor_map[sid]["total_billed"] + tot, 2)
        creditor_map[sid]["total_paid"] = round(creditor_map[sid]["total_paid"] + paid, 2)
        creditor_map[sid]["outstanding_payable"] = round(creditor_map[sid]["outstanding_payable"] + bal, 2)
        if str(b.get("payment_status", "")).upper() != "PAID":
            creditor_map[sid]["open_bills_count"] += 1

    creditors_list = list(creditor_map.values())
    creditors_list.sort(key=lambda x: x["outstanding_payable"], reverse=True)
    return creditors_list


@router.get("/cash-bank")
async def get_cash_and_bank_report(
    user: dict = Depends(get_current_user),
):
    """Cash and Bank balances across Factory Safe (1110), Van Float (1115), and Bank (1120)."""
    require_accounting_access(user)
    tb = calculate_trial_balance()
    rows = tb.get("rows", [])

    safe_row = next((r for r in rows if r["account_code"] == "1110"), {})
    van_row = next((r for r in rows if r["account_code"] == "1115"), {})
    bank_row = next((r for r in rows if r["account_code"] == "1120"), {})

    return {
        "factory_safe_cash": float(safe_row.get("net_debit", 0.0) or 0.0),
        "salesman_van_float": float(van_row.get("net_debit", 0.0) or 0.0),
        "bank_account_balance": float(bank_row.get("net_debit", 0.0) or 0.0),
        "total_liquid_funds": round(
            float(safe_row.get("net_debit", 0.0) or 0.0)
            + float(van_row.get("net_debit", 0.0) or 0.0)
            + float(bank_row.get("net_debit", 0.0) or 0.0),
            2
        ),
    }


@router.get("/gst-summary")
async def get_gst_summary_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Authoritative GST summary: Output CGST (2210), Output SGST (2220), Input CGST (1310), Input SGST (1320)."""
    require_accounting_access(user)
    tb = calculate_trial_balance(start_date=start_date, end_date=end_date)
    rows = tb.get("rows", [])

    output_cgst = float(next((r.get("net_credit", 0.0) for r in rows if r["account_code"] == "2210"), 0.0) or 0.0)
    output_sgst = float(next((r.get("net_credit", 0.0) for r in rows if r["account_code"] == "2220"), 0.0) or 0.0)
    input_cgst = float(next((r.get("net_debit", 0.0) for r in rows if r["account_code"] == "1310"), 0.0) or 0.0)
    input_sgst = float(next((r.get("net_debit", 0.0) for r in rows if r["account_code"] == "1320"), 0.0) or 0.0)

    total_output_liability = round(output_cgst + output_sgst, 2)
    total_input_itc = round(input_cgst + input_sgst, 2)
    net_payable = round(max(0.0, total_output_liability - total_input_itc), 2)
    excess_itc = round(max(0.0, total_input_itc - total_output_liability), 2)

    return {
        "period": {"start_date": start_date or "All Time", "end_date": end_date or "Current"},
        "output_cgst_payable": output_cgst,
        "output_sgst_payable": output_sgst,
        "total_output_gst": total_output_liability,
        "input_cgst_itc": input_cgst,
        "input_sgst_itc": input_sgst,
        "total_input_itc": total_input_itc,
        "net_gst_payable": net_payable,
        "excess_itc_credit": excess_itc,
    }


@router.get("/periods")
async def list_accounting_periods(user: dict = Depends(get_current_user)):
    require_accounting_access(user)
    periods = db.get_records("AccountingPeriods", fresh=True)
    if not periods:
        # Provide default periods
        return [
            {"period_id": "PER-2026-Q3", "period_name": "Q3 2026 (Jul-Sep)", "start_date": "2026-07-01", "end_date": "2026-09-30", "is_closed": "true", "closed_by": "OWNER"},
            {"period_id": "PER-2026-Q4", "period_name": "Q4 2026 (Oct-Dec)", "start_date": "2026-10-01", "end_date": "2026-12-31", "is_closed": "false", "closed_by": ""},
        ]
    return periods


@router.post("/periods/{period_id}/close")
async def close_accounting_period(
    period_id: str,
    user: dict = Depends(get_current_user),
):
    if not is_owner(user):
        raise HTTPException(403, "Only the business Owner can close an accounting period.")

    actor = str(user.get("user_id", "OWNER"))
    periods = db.get_records("AccountingPeriods", fresh=True)
    per = next((p for p in periods if str(p.get("period_id")) == period_id), None)
    if not per:
        # Create closed period
        per_row = {
            "period_id": period_id,
            "period_name": period_id,
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "is_closed": "true",
            "closed_by": actor,
            "closed_at": now_iso(),
        }
        db.append_record("AccountingPeriods", per_row)
        return per_row

    db.update_record("AccountingPeriods", "period_id", period_id, {
        "is_closed": "true",
        "closed_by": actor,
        "closed_at": now_iso(),
    })
    db.log_audit(actor, "CLOSE_ACCOUNTING_PERIOD", "AccountingPeriods", period_id, reason=f"Closed accounting period {period_id}")
    return {"ok": True, "period_id": period_id, "is_closed": True}

