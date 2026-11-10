"""
Kawad Swad ERP - Customer Outstanding & Accounts Receivable Sub-Ledger
Authoritative transaction ledger for debtor management, credit limits, and aging.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, date, timedelta
from decimal import Decimal
from fastapi import HTTPException

from app.sheets import db
from app.accounting.journal_engine import to_decimal, round_money
from app.permissions import is_owner, is_manager, is_salesman


class CustomerTxnType:
    INVOICE = "INVOICE"
    COLLECTION = "COLLECTION"
    CREDIT_NOTE = "CREDIT_NOTE"
    DEBIT_NOTE = "DEBIT_NOTE"


def get_customer_transactions(customer_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns unified chronological customer ledger transactions:
    - INVOICE: From non-cancelled Sales records (debit / increases receivable)
    - COLLECTION: From non-refunded Payments records (credit / decreases receivable)
    - CREDIT_NOTE: From authorized CustomerReturns (credit / decreases receivable)
    - DEBIT_NOTE: Debit adjustments (debit / increases receivable)
    """
    sales = db.get_records("Sales", fresh=True) or []
    payments = db.get_records("Payments", fresh=True) or []
    returns = db.get_records("CustomerReturns", fresh=True) or []

    clean_cid = str(customer_id or "").strip()
    sales_map = {str(s.get("sale_id")): s for s in sales}

    transactions: List[Dict[str, Any]] = []

    # 1. Invoices
    for s in sales:
        s_cid = str(s.get("customer_id") or "").strip()
        if clean_cid and s_cid != clean_cid:
            continue
        if not s_cid or s_cid in {"CUS-WALKIN", "WALK-IN"}:
            continue
        if str(s.get("bill_status", "")).upper() in {"CANCELLED", "VOID"}:
            continue
        if str(s.get("txn_status", "")).upper() == "INCOMPLETE":
            continue

        bill_total = float(s.get("bill_total", 0) or 0)
        sale_id = str(s.get("sale_id", ""))
        bill_no = str(s.get("bill_number", "") or sale_id)
        s_date = str(s.get("sale_datetime") or s.get("created_at") or "")[:10]

        transactions.append({
            "txn_id": f"INV-{bill_no}",
            "txn_date": s_date,
            "txn_type": CustomerTxnType.INVOICE,
            "customer_id": s_cid,
            "customer_name": str(s.get("customer_name_snapshot") or ""),
            "sale_id": sale_id,
            "bill_number": bill_no,
            "reference_id": bill_no,
            "debit_amount": bill_total,
            "credit_amount": 0.0,
            "payment_status": str(s.get("payment_status") or "UNPAID"),
            "notes": f"Sales Invoice #{bill_no}",
        })

    # 2. Collections (Payments against invoices)
    for p in payments:
        if str(p.get("payment_status", "")).upper() in {"REFUNDED", "FAILED"}:
            continue
        sid = str(p.get("sale_id") or "").strip()
        target_sale = sales_map.get(sid, {})
        p_cid = str(target_sale.get("customer_id") or "").strip()
        if clean_cid and p_cid != clean_cid:
            continue
        if not p_cid or p_cid in {"CUS-WALKIN", "WALK-IN"}:
            continue

        amt = float(p.get("amount", 0) or 0)
        if amt <= 0:
            continue

        pay_id = str(p.get("payment_id", ""))
        p_date = str(p.get("payment_datetime") or "")[:10]
        pay_method = str(p.get("payment_method", "CASH")).upper()
        ref_no = str(p.get("reference_number") or pay_id)

        transactions.append({
            "txn_id": pay_id,
            "txn_date": p_date,
            "txn_type": CustomerTxnType.COLLECTION,
            "customer_id": p_cid,
            "customer_name": str(target_sale.get("customer_name_snapshot") or ""),
            "sale_id": sid,
            "bill_number": str(target_sale.get("bill_number") or sid),
            "reference_id": ref_no,
            "debit_amount": 0.0,
            "credit_amount": amt,
            "payment_method": pay_method,
            "notes": f"Payment collection via {pay_method} (Ref: {ref_no})",
        })

    # 3. Credit Notes from Customer Returns
    for r in returns:
        r_cid = str(r.get("customer_id") or "").strip()
        if clean_cid and r_cid != clean_cid:
            continue
        if str(r.get("status", "")).upper() not in {"APPROVED", "COMPLETED", "PROCESSED"}:
            continue
        ret_id = str(r.get("return_id", ""))
        ref_amt = float(r.get("refund_amount", 0) or r.get("total_refund", 0) or 0)
        if ref_amt <= 0:
            continue
        transactions.append({
            "txn_id": ret_id,
            "txn_date": str(r.get("return_date") or "")[:10],
            "txn_type": CustomerTxnType.CREDIT_NOTE,
            "customer_id": r_cid,
            "customer_name": str(r.get("customer_name") or ""),
            "sale_id": str(r.get("sale_id") or ""),
            "bill_number": str(r.get("bill_number") or ""),
            "reference_id": ret_id,
            "debit_amount": 0.0,
            "credit_amount": ref_amt,
            "notes": f"Credit note for return {ret_id}: {r.get('notes', '')}",
        })

    transactions.sort(key=lambda t: (t.get("txn_date", ""), t.get("txn_id", "")))
    return transactions


def calculate_customer_outstanding(customer_id: str) -> float:
    """
    Authoritative customer outstanding balance calculated from ledger transactions:
    Outstanding = Sum(Debits / Invoices + Debit Notes) - Sum(Credits / Collections + Credit Notes)
    """
    cid = str(customer_id or "").strip()
    if not cid or cid in {"CUS-WALKIN", "WALK-IN"}:
        return 0.0

    txns = get_customer_transactions(customer_id=cid)
    tot_debits = sum(float(t.get("debit_amount", 0) or 0) for t in txns)
    tot_credits = sum(float(t.get("credit_amount", 0) or 0) for t in txns)
    return max(0.0, round(tot_debits - tot_credits, 2))


def get_customer_overdue_invoices(customer_id: str, max_overdue_days: int = 30) -> List[Dict[str, Any]]:
    """
    Identify unpaid or partially paid customer invoices where the credit period has expired.
    """
    cid = str(customer_id or "").strip()
    if not cid or cid in {"CUS-WALKIN", "WALK-IN"}:
        return []

    sales = db.get_records("Sales", fresh=True) or []
    payments = db.get_records("Payments", fresh=True) or []

    # Map collections per sale
    collections_by_sale: Dict[str, float] = {}
    for p in payments:
        if str(p.get("payment_status", "")).upper() in {"REFUNDED", "FAILED"}:
            continue
        sid = str(p.get("sale_id") or "").strip()
        collections_by_sale[sid] = collections_by_sale.get(sid, 0.0) + float(p.get("amount", 0) or 0)

    today = date.today()
    overdue: List[Dict[str, Any]] = []

    for s in sales:
        s_cid = str(s.get("customer_id") or "").strip()
        if s_cid != cid:
            continue
        if str(s.get("bill_status", "")).upper() in {"CANCELLED", "VOID"}:
            continue
        if str(s.get("txn_status", "")).upper() == "INCOMPLETE":
            continue

        sid = str(s.get("sale_id", ""))
        bill_tot = float(s.get("bill_total", 0) or 0)
        paid = collections_by_sale.get(sid, 0.0)
        unpaid = max(0.0, round(bill_tot - paid, 2))
        if unpaid <= 0.05:
            continue

        s_date_str = str(s.get("sale_datetime") or s.get("created_at") or "")[:10]
        try:
            inv_date = datetime.strptime(s_date_str, "%Y-%m-%d").date()
            age_days = (today - inv_date).days
        except Exception:
            age_days = 0

        if age_days > max_overdue_days:
            overdue.append({
                "sale_id": sid,
                "bill_number": str(s.get("bill_number") or sid),
                "invoice_date": s_date_str,
                "age_days": age_days,
                "bill_total": bill_tot,
                "paid_amount": paid,
                "overdue_balance": unpaid,
            })

    return overdue


def get_invoice_settlement_status(sale_id: str) -> Dict[str, Any]:
    """
    Authoritative settlement status of an individual invoice calculated from Payments:
    Returns {bill_total, total_collected, remaining_balance, payment_status}
    """
    clean_sid = str(sale_id or "").strip()
    sales = db.get_records("Sales", fresh=True) or []
    sale = next((s for s in sales if str(s.get("sale_id", "")).strip() == clean_sid), None)
    if not sale:
        raise HTTPException(status_code=404, detail=f"Sale invoice {sale_id} not found.")

    bill_total = round(float(sale.get("bill_total", 0) or 0), 2)
    payments = [
        p for p in db.get_records("Payments", fresh=True)
        if str(p.get("sale_id", "")).strip() == clean_sid
        and str(p.get("payment_status", "")).upper() not in {"REFUNDED", "FAILED"}
    ]
    total_collected = round(sum(float(p.get("amount", 0) or 0) for p in payments), 2)
    remaining_balance = max(0.0, round(bill_total - total_collected, 2))

    if remaining_balance <= 0.05:
        p_status = "PAID"
    elif total_collected > 0.0:
        p_status = "PARTIAL"
    else:
        p_status = "UNPAID"

    return {
        "sale_id": clean_sid,
        "bill_number": str(sale.get("bill_number") or clean_sid),
        "bill_total": bill_total,
        "total_collected": total_collected,
        "remaining_balance": remaining_balance,
        "payment_status": p_status,
        "payment_count": len(payments),
        "payments": payments,
    }


def check_credit_control(
    customer_id: str,
    requested_credit: float,
    current_user: dict,
    approval_request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Enforces business credit rules:
    - Walk-in customers cannot receive credit.
    - Customer must be registered and active.
    - Outstanding + requested credit must not exceed customer's credit_limit.
    - Customer must not have invoices exceeding max_overdue_days.
    - Salesmen CANNOT independently approve credit exceptions.
    - Owner can approve directly or via an approved ApprovalRequest.
    """
    req_credit = round(float(requested_credit or 0.0), 2)
    if req_credit <= 0:
        return {"approved": True, "reason": "No credit requested (full payment)"}

    cid = str(customer_id or "").strip()
    if not cid or cid in {"CUS-WALKIN", "WALK-IN"}:
        raise HTTPException(
            status_code=400,
            detail="Credit sale is not allowed for Walk-in customers. Credit requires a registered customer account."
        )

    customers = db.get_records("Customers", fresh=True) or []
    customer = next((c for c in customers if str(c.get("customer_id", "")).strip() == cid), None)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{cid}' not found.")

    is_active = str(customer.get("active", "true")).strip().lower() not in {"false", "0", "no", "inactive"}
    if not is_active:
        raise HTTPException(status_code=400, detail=f"Customer '{customer.get('shop_name') or cid}' is inactive.")

    credit_limit = float(customer.get("credit_limit", 0) or 0.0)
    max_overdue_days = int(float(customer.get("max_overdue_days", 30) or 30))

    current_outstanding = calculate_customer_outstanding(cid)
    new_total_exposure = round(current_outstanding + req_credit, 2)

    limit_exceeded = (credit_limit > 0 and new_total_exposure > credit_limit) or (credit_limit <= 0 and req_credit > 0)
    overdue_invoices = get_customer_overdue_invoices(cid, max_overdue_days=max_overdue_days)

    if not limit_exceeded and not overdue_invoices:
        return {
            "approved": True,
            "credit_limit": credit_limit,
            "current_outstanding": current_outstanding,
            "new_total_exposure": new_total_exposure,
            "reason": "Within customer credit limit and payment terms",
        }

    # Exception required
    violation_reasons = []
    if limit_exceeded:
        violation_reasons.append(
            f"Exposure ₹{new_total_exposure:.2f} exceeds credit limit ₹{credit_limit:.2f} "
            f"(Current Outstanding: ₹{current_outstanding:.2f}, Requested: ₹{req_credit:.2f})"
        )
    if overdue_invoices:
        max_age = max(o["age_days"] for o in overdue_invoices)
        tot_overdue = sum(o["overdue_balance"] for o in overdue_invoices)
        violation_reasons.append(
            f"{len(overdue_invoices)} overdue invoice(s) totaling ₹{tot_overdue:.2f} exceeding terms ({max_overdue_days} days, oldest {max_age} days)"
        )

    violation_text = "; ".join(violation_reasons)

    # 1. Direct Owner Authorization
    if is_owner(current_user) or is_manager(current_user):
        return {
            "approved": True,
            "credit_exception": True,
            "approved_by_owner": True,
            "authorized_by": str(current_user.get("user_id")),
            "current_outstanding": current_outstanding,
            "new_total_exposure": new_total_exposure,
            "reason": f"Owner authorized credit exception: {violation_text}",
        }

    # 2. Verified Pre-Approved ApprovalRequest by Owner
    clean_app_id = str(approval_request_id or "").strip()
    if clean_app_id:
        approvals = db.get_records("ApprovalRequests", fresh=True) or []
        appr = next((a for a in approvals if str(a.get("request_id", "")).strip() == clean_app_id), None)
        if appr:
            app_status = str(appr.get("status", "")).upper()
            app_type = str(appr.get("request_type", "")).upper()
            app_by = str(appr.get("decided_by") or appr.get("approved_by") or "")
            if app_status == "APPROVED" and app_type in {"CREDIT_EXCEPTION", "CUSTOMER_CREDIT", "SALE_CREDIT"} and app_by:
                return {
                    "approved": True,
                    "credit_exception": True,
                    "approved_by_owner": True,
                    "approval_request_id": clean_app_id,
                    "authorized_by": app_by,
                    "current_outstanding": current_outstanding,
                    "new_total_exposure": new_total_exposure,
                    "reason": f"Authorized via approved Owner request {clean_app_id}: {violation_text}",
                }

    # Salesman blocked
    raise HTTPException(
        status_code=400,
        detail=f"Credit sale rejected for {customer.get('shop_name') or cid}: {violation_text}. "
               f"Salesmen cannot independently approve credit. Owner approval is required."
    )
