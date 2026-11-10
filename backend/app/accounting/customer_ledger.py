"""
Kawad Swad ERP - Customer Outstanding & Accounts Receivable Sub-Ledger
Authoritative transaction ledger for debtor management, credit limits, and aging.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, date, timedelta
from decimal import Decimal
import json
import logging
from fastapi import HTTPException

from app.sheets import db
from app.timeutil import now_iso
from app.accounting.journal_engine import to_decimal, round_money
from app.permissions import is_owner, is_manager, is_salesman


class CustomerTxnType:
    INVOICE = "INVOICE"
    COLLECTION = "COLLECTION"
    REFUND = "REFUND"
    CREDIT_NOTE = "CREDIT_NOTE"
    DEBIT_NOTE = "DEBIT_NOTE"
    INVOICE_CANCELLATION = "INVOICE_CANCELLATION"


def get_customer_transactions(customer_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns unified chronological customer ledger transactions:
    - INVOICE: From Sales records (debit / increases receivable)
    - INVOICE_CANCELLATION: For cancelled Sales records (credit / offsets cancelled invoice)
    - COLLECTION: From positive Payments records (credit / decreases receivable)
    - REFUND: From refund Payments records (debit / reverses collection credit)
    - CREDIT_NOTE: From authorized CustomerReturns (credit / decreases receivable)
    - DEBIT_NOTE: Debit adjustments (debit / increases receivable)
    """
    sales = db.get_records("Sales", fresh=True) or []
    payments = db.get_records("Payments", fresh=True) or []
    returns = db.get_records("CustomerReturns", fresh=True) or []

    clean_cid = str(customer_id or "").strip()
    sales_map = {str(s.get("sale_id")): s for s in sales}

    transactions: List[Dict[str, Any]] = []

    # 1. Invoices & Invoice Cancellations
    for s in sales:
        s_cid = str(s.get("customer_id") or "").strip()
        if clean_cid and s_cid != clean_cid:
            continue
        if not s_cid or s_cid in {"CUS-WALKIN", "WALK-IN"}:
            continue
        if str(s.get("txn_status", "")).upper() == "INCOMPLETE":
            continue

        bill_total = float(s.get("bill_total", 0) or 0)
        sale_id = str(s.get("sale_id", ""))
        bill_no = str(s.get("bill_number", "") or sale_id)
        s_date = str(s.get("sale_datetime") or s.get("created_at") or "")[:10]
        bill_status = str(s.get("bill_status", "ISSUED")).upper()

        if bill_status in {"CANCELLED", "VOID"}:
            # Reconcile cancelled invoice: show invoice and its cancellation credit offset
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
                "payment_status": "CANCELLED",
                "notes": f"Sales Invoice #{bill_no} (Cancelled)",
            })
            transactions.append({
                "txn_id": f"REV-{bill_no}",
                "txn_date": s_date,
                "txn_type": CustomerTxnType.INVOICE_CANCELLATION,
                "customer_id": s_cid,
                "customer_name": str(s.get("customer_name_snapshot") or ""),
                "sale_id": sale_id,
                "bill_number": bill_no,
                "reference_id": f"CANCEL-{bill_no}",
                "debit_amount": 0.0,
                "credit_amount": bill_total,
                "payment_status": "CANCELLED",
                "notes": f"Cancellation Reversal for Invoice #{bill_no}",
            })
        else:
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

    # 2. Collections and Refunds
    for p in payments:
        if str(p.get("payment_status", "")).upper() == "FAILED":
            continue
        sid = str(p.get("sale_id") or "").strip()
        target_sale = sales_map.get(sid, {})
        p_cid = str(target_sale.get("customer_id") or p.get("customer_id") or "").strip()
        if clean_cid and p_cid != clean_cid:
            continue
        if not p_cid or p_cid in {"CUS-WALKIN", "WALK-IN"}:
            continue

        raw_amt = float(p.get("amount", 0) or 0)
        if raw_amt == 0:
            continue

        pay_id = str(p.get("payment_id", ""))
        p_date = str(p.get("payment_datetime") or "")[:10]
        pay_method = str(p.get("payment_method", "CASH")).upper()
        ref_no = str(p.get("reference_number") or pay_id)
        p_status = str(p.get("payment_status", "")).upper()

        if raw_amt < 0 or p_status == "REFUNDED":
            # Refund reverses previous collection credit (debit / increases receivable back)
            refund_val = abs(raw_amt)
            transactions.append({
                "txn_id": pay_id,
                "txn_date": p_date,
                "txn_type": CustomerTxnType.REFUND,
                "customer_id": p_cid,
                "customer_name": str(target_sale.get("customer_name_snapshot") or ""),
                "sale_id": sid,
                "bill_number": str(target_sale.get("bill_number") or sid),
                "reference_id": ref_no,
                "debit_amount": refund_val,
                "credit_amount": 0.0,
                "payment_method": pay_method,
                "notes": f"Refund via {pay_method} (Ref: {ref_no})",
            })
        else:
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
                "credit_amount": raw_amt,
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
    Outstanding = Sum(Debits: Invoices + Refunds + Debit Notes) - Sum(Credits: Collections + Credit Notes + Cancellations)
    Note: Preserves negative credit balances (genuine customer advances/credits).
    """
    cid = str(customer_id or "").strip()
    if not cid or cid in {"CUS-WALKIN", "WALK-IN"}:
        return 0.0

    txns = get_customer_transactions(customer_id=cid)
    tot_debits = sum(float(t.get("debit_amount", 0) or 0) for t in txns)
    tot_credits = sum(float(t.get("credit_amount", 0) or 0) for t in txns)
    return round(tot_debits - tot_credits, 2)


def get_customer_balance_breakdown(customer_id: str) -> Dict[str, Any]:
    """
    Exposes debit balance and credit balance separately so customer credits are never masked.
    """
    cid = str(customer_id or "").strip()
    txns = get_customer_transactions(customer_id=cid)
    tot_debits = sum(float(t.get("debit_amount", 0) or 0) for t in txns)
    tot_credits = sum(float(t.get("credit_amount", 0) or 0) for t in txns)
    net_bal = round(tot_debits - tot_credits, 2)
    return {
        "customer_id": cid,
        "total_debits": round(tot_debits, 2),
        "total_credits": round(tot_credits, 2),
        "net_balance": net_bal,
        "debit_balance": max(0.0, net_bal),
        "credit_balance": abs(min(0.0, net_bal)),
        "customer_credit_balance": abs(min(0.0, net_bal)),
        "has_credit_balance": net_bal < 0,
    }


def get_customer_overdue_invoices(customer_id: str, max_overdue_days: int = 30) -> List[Dict[str, Any]]:
    """
    Identify unpaid or partially paid customer invoices where the credit period has expired.
    Excludes cancelled and void invoices.
    """
    cid = str(customer_id or "").strip()
    if not cid or cid in {"CUS-WALKIN", "WALK-IN"}:
        return []

    sales = db.get_records("Sales", fresh=True) or []
    payments = db.get_records("Payments", fresh=True) or []

    # Map net collections per sale (collections minus refunds)
    net_collections_by_sale: Dict[str, float] = {}
    for p in payments:
        if str(p.get("payment_status", "")).upper() == "FAILED":
            continue
        sid = str(p.get("sale_id") or "").strip()
        amt = float(p.get("amount", 0) or 0)
        net_collections_by_sale[sid] = net_collections_by_sale.get(sid, 0.0) + amt

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
        paid = max(0.0, net_collections_by_sale.get(sid, 0.0))
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
    Returns {bill_total, original_invoice_amount, total_collected, total_refunded, net_collected,
             remaining_balance, final_outstanding, payment_status, bill_status, cancellation_status, is_cancelled}
    """
    clean_sid = str(sale_id or "").strip()
    sales = db.get_records("Sales", fresh=True) or []
    sale = next((s for s in sales if str(s.get("sale_id", "")).strip() == clean_sid), None)
    if not sale:
        raise HTTPException(status_code=404, detail=f"Sale invoice {sale_id} not found.")

    bill_total = round(float(sale.get("bill_total", 0) or 0), 2)
    bill_status = str(sale.get("bill_status", "ISSUED")).upper()
    is_cancelled = bill_status in {"CANCELLED", "VOID"}

    all_payments = [
        p for p in db.get_records("Payments", fresh=True)
        if str(p.get("sale_id", "")).strip() == clean_sid
        and str(p.get("payment_status", "")).upper() != "FAILED"
    ]
    positive_payments = [p for p in all_payments if float(p.get("amount", 0) or 0) > 0 and str(p.get("payment_status", "")).upper() != "REFUNDED"]
    refund_payments = [p for p in all_payments if float(p.get("amount", 0) or 0) < 0 or str(p.get("payment_status", "")).upper() == "REFUNDED"]

    total_collected = round(sum(float(p.get("amount", 0) or 0) for p in positive_payments), 2)
    total_refunded = round(sum(abs(float(p.get("amount", 0) or 0)) for p in refund_payments), 2)
    net_collected = round(total_collected - total_refunded, 2)

    if is_cancelled:
        return {
            "sale_id": clean_sid,
            "bill_number": str(sale.get("bill_number") or clean_sid),
            "bill_total": bill_total,
            "original_invoice_amount": bill_total,
            "total_collected": total_collected,
            "total_refunded": total_refunded,
            "net_collected": net_collected,
            "remaining_balance": 0.0,
            "final_outstanding": 0.0,
            "payment_status": "CANCELLED",
            "bill_status": "CANCELLED",
            "cancellation_status": "CANCELLED",
            "is_cancelled": True,
            "payment_count": len(all_payments),
            "payments": all_payments,
        }

    remaining_balance = max(0.0, round(bill_total - net_collected, 2))
    if remaining_balance <= 0.05:
        p_status = "PAID"
    elif net_collected > 0.0:
        p_status = "PARTIAL"
    else:
        p_status = "UNPAID"

    return {
        "sale_id": clean_sid,
        "bill_number": str(sale.get("bill_number") or clean_sid),
        "bill_total": bill_total,
        "original_invoice_amount": bill_total,
        "total_collected": total_collected,
        "total_refunded": total_refunded,
        "net_collected": net_collected,
        "remaining_balance": remaining_balance,
        "final_outstanding": remaining_balance,
        "payment_status": p_status,
        "bill_status": bill_status,
        "cancellation_status": "ACTIVE",
        "is_cancelled": False,
        "payment_count": len(all_payments),
        "payments": all_payments,
    }


def check_credit_control(
    customer_id: str,
    requested_credit: float,
    current_user: dict,
    approval_request_id: Optional[str] = None,
    current_sale_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Enforces business credit rules:
    - Walk-in customers cannot receive credit.
    - Customer must be registered and active.
    - Outstanding + requested credit must not exceed customer's credit_limit.
    - Customer must not have invoices exceeding max_overdue_days.
    - Salesmen and Personal Assistants CANNOT independently approve credit exceptions.
    - Only an authenticated Owner may directly authorize a credit exception.
    - ApprovalRequests must be strictly verified:
        1. APPROVED status
        2. Authorized Owner identity
        3. Correct request type (CREDIT_EXCEPTION, CUSTOMER_CREDIT, SALE_CREDIT)
        4. Matching customer
        5. Approved amount limit
        6. Request validity and expiry
        7. Not revoked
        8. Not already consumed or reserved by an unrelated transaction
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

    clean_app_id = str(approval_request_id or "").strip()
    if clean_app_id:
        approvals = db.get_records("ApprovalRequests", fresh=True) or []
        appr = next((a for a in approvals if str(a.get("request_id", "")).strip() == clean_app_id), None)
        if not appr:
            raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' not found.")

        validation_result = validate_credit_approval_request(
            appr=appr,
            approval_id=clean_app_id,
            customer_id=cid,
            requested_credit=req_credit,
            current_sale_id=current_sale_id,
        )

        return {
            "approved": True,
            "credit_exception": True,
            "approved_by_owner": True,
            "approval_request_id": clean_app_id,
            "authorized_by": validation_result.get("decided_by"),
            "current_outstanding": current_outstanding,
            "new_total_exposure": new_total_exposure,
            "reason": f"Authorized via approved Owner request {clean_app_id}",
        }

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

    # 1. Direct Owner Authorization: ONLY OWNER (PA and Salesman cannot directly authorize)
    if is_owner(current_user):
        return {
            "approved": True,
            "credit_exception": True,
            "approved_by_owner": True,
            "authorized_by": str(current_user.get("user_id")),
            "current_outstanding": current_outstanding,
            "new_total_exposure": new_total_exposure,
            "reason": f"Owner authorized credit exception: {violation_text}",
        }

    # PA or Salesman blocked without valid Owner approval
    role_name = "Personal Assistant" if is_manager(current_user) else "Salesman"
    raise HTTPException(
        status_code=400,
        detail=f"Credit sale rejected for {customer.get('shop_name') or cid}: {violation_text}. "
               f"{role_name} cannot independently approve credit. Owner approval is required."
    )


def validate_credit_approval_request(
    appr: Dict[str, Any],
    approval_id: str,
    customer_id: str,
    requested_credit: float,
    current_sale_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Strict validation of ApprovalRequest for credit exception.
    Enforces all mandatory fields:
    - Status must be APPROVED.
    - Approval must not be revoked.
    - Request type must be a valid credit approval type.
    - Decider must be an active Owner in Users.
    - Customer ID must be present and exactly match customer_id.
    - Approved amount must be present, valid, > 0, and >= requested_credit.
    - Expiry date must be present, valid YYYY-MM-DD, and not expired.
    - Not already consumed or reserved by another sale.
    Missing or malformed fields raise HTTPException(400).
    """
    clean_app_id = str(approval_id or "").strip()

    # 1. Status check
    app_status = str(appr.get("status", "")).upper()
    if app_status != "APPROVED":
        raise HTTPException(
            status_code=400,
            detail=f"Approval request '{clean_app_id}' has status '{app_status}' (must be APPROVED).",
        )

    # 2. Revocation check
    if str(appr.get("revoked", "")).lower() in {"true", "1", "yes"} or app_status == "REVOKED":
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' has been revoked.")

    # 3. Request type check
    app_type = str(appr.get("request_type", "")).upper()
    if app_type not in {"CREDIT_EXCEPTION", "CUSTOMER_CREDIT", "SALE_CREDIT"}:
        raise HTTPException(
            status_code=400,
            detail=f"Approval request '{clean_app_id}' has invalid type '{app_type}' for credit exception.",
        )

    # 4. Decider (active Owner) check
    decided_by = str(appr.get("decided_by") or appr.get("approved_by") or "").strip()
    if not decided_by:
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' lacks authorized Owner identity.")
    users = db.get_records("Users", fresh=True) or []
    decider = next((u for u in users if str(u.get("user_id", "")).strip() == decided_by), None)
    if not decider or not is_owner(decider) or str(decider.get("active", "true")).lower() in {"false", "0", "no", "inactive"}:
        raise HTTPException(status_code=400, detail=f"Approver '{decided_by}' is not an active Owner.")

    # Parse payload_json if present
    payload = {}
    if appr.get("payload_json"):
        try:
            payload = json.loads(str(appr["payload_json"])) if isinstance(appr["payload_json"], str) else appr["payload_json"]
        except Exception:
            payload = {}

    # 5. Customer ID check: MANDATORY & EXACT MATCH
    target_cid = str(appr.get("customer_id") or payload.get("customer_id") or payload.get("target_customer_id") or "").strip()
    if not target_cid:
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' has missing customer ID.")
    if target_cid != customer_id:
        raise HTTPException(
            status_code=400,
            detail=f"Approval request '{clean_app_id}' is for customer '{target_cid}', does not match current customer '{customer_id}'.",
        )

    # 6. Approved amount check: MANDATORY, VALID FLOAT, > 0, >= requested_credit
    raw_approved_amt = (
        appr.get("approved_amount")
        if appr.get("approved_amount") is not None and str(appr.get("approved_amount")).strip() != ""
        else (
            appr.get("amount")
            if appr.get("amount") is not None and str(appr.get("amount")).strip() != ""
            else (
                payload.get("approved_amount")
                if payload.get("approved_amount") is not None and str(payload.get("approved_amount")).strip() != ""
                else (
                    payload.get("amount")
                    if payload.get("amount") is not None and str(payload.get("amount")).strip() != ""
                    else payload.get("credit_limit")
                )
            )
        )
    )
    if raw_approved_amt is None or str(raw_approved_amt).strip() in {"", "null", "none"}:
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' has missing approved amount.")
    try:
        app_amt = float(raw_approved_amt)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"Approval request '{clean_app_id}' has invalid approved amount '{raw_approved_amt}'.",
        )
    if app_amt <= 0:
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' has approved amount <= 0 (must be > 0).")
    if requested_credit > app_amt + 0.05:
        raise HTTPException(
            status_code=400,
            detail=f"Requested credit ₹{requested_credit:.2f} exceeds approved limit of ₹{app_amt:.2f} in approval request '{clean_app_id}'.",
        )

    # 7. Expiry date check: MANDATORY, VALID YYYY-MM-DD, NOT EXPIRED
    raw_expiry = (
        appr.get("expires_at")
        or appr.get("valid_until")
        or appr.get("expiry_date")
        or payload.get("expires_at")
        or payload.get("valid_until")
    )
    if not raw_expiry or str(raw_expiry).strip() in {"", "null", "none"}:
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' has missing expiry date.")
    try:
        exp_str = str(raw_expiry).strip()[:10]
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"Approval request '{clean_app_id}' has malformed expiry date '{raw_expiry}'.",
        )
    if date.today() > exp_date:
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_app_id}' expired on {exp_str}.")

    # 8. Consumed check: Cannot be consumed by another transaction
    consumed_sale = str(appr.get("consumed_by_sale_id") or payload.get("consumed_by_sale_id") or "").strip()
    is_consumed = bool(appr.get("is_consumed") or payload.get("is_consumed"))
    if is_consumed or consumed_sale:
        if current_sale_id and consumed_sale == current_sale_id:
            pass  # Idempotent retry by the same sale
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Approval request '{clean_app_id}' has already been consumed by sale '{consumed_sale or 'ANOTHER_SALE'}'.",
            )

    # 9. Reserved check: Cannot be reserved by another transaction
    reserved_sale = str(appr.get("reserved_by_sale_id") or payload.get("reserved_by_sale_id") or "").strip()
    if reserved_sale:
        if current_sale_id and reserved_sale == current_sale_id:
            pass  # Re-entrant by the same sale
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Approval request '{clean_app_id}' is already reserved by sale '{reserved_sale}'.",
            )

    return {
        "approved_amount": app_amt,
        "expiry_date": exp_date,
        "decided_by": decided_by,
        "customer_id": target_cid,
    }


def reserve_credit_approval(
    approval_request_id: str,
    sale_id: str,
    customer_id: str,
    requested_credit: float,
) -> bool:
    """
    Atomically reserves an approval request for a specific sale ID.
    Enforces validation, rejects if consumed or reserved by another sale,
    and performs Compare-And-Swap update.
    """
    if not approval_request_id:
        return False
    clean_id = str(approval_request_id).strip()
    approvals = db.get_records("ApprovalRequests", fresh=True) or []
    appr = next((a for a in approvals if str(a.get("request_id", "")).strip() == clean_id), None)
    if not appr:
        raise HTTPException(status_code=400, detail=f"Approval request '{clean_id}' not found.")

    # Validate approval constraints with intended sale ID
    validate_credit_approval_request(
        appr=appr,
        approval_id=clean_id,
        customer_id=customer_id,
        requested_credit=requested_credit,
        current_sale_id=sale_id,
    )

    current_reserved = str(appr.get("reserved_by_sale_id", "")).strip()
    if current_reserved == sale_id:
        return True  # Idempotent retry

    now = now_iso()
    # Atomic reservation with expected condition
    updated = db.update_record(
        tab_name="ApprovalRequests",
        id_field="request_id",
        id_value=clean_id,
        updates={
            "reserved_by_sale_id": sale_id,
            "reserved_at": now,
        },
        expected_conditions={
            "is_consumed": False,
            "reserved_by_sale_id": "",
        },
    )
    if not updated:
        # Check if another sale raced and reserved it
        fresh_apprs = db.get_records("ApprovalRequests", fresh=True) or []
        fresh_appr = next((a for a in fresh_apprs if str(a.get("request_id", "")).strip() == clean_id), None)
        other_holder = str(fresh_appr.get("reserved_by_sale_id", "") if fresh_appr else "").strip()
        if other_holder and other_holder != sale_id:
            raise HTTPException(
                status_code=400,
                detail=f"Approval request '{clean_id}' was concurrently reserved by sale '{other_holder}'.",
            )
        raise HTTPException(status_code=503, detail=f"Failed to reserve approval request '{clean_id}' for sale {sale_id}. Retry.")
    return True


def consume_credit_approval(approval_request_id: str, sale_id: str) -> bool:
    """
    Marks an approval request as permanently consumed by a completed sale.
    Returns True on success, False on failure.
    """
    if not approval_request_id:
        return False
    clean_id = str(approval_request_id).strip()
    now = now_iso()
    try:
        updated = db.update_record(
            tab_name="ApprovalRequests",
            id_field="request_id",
            id_value=clean_id,
            updates={
                "is_consumed": True,
                "consumed_by_sale_id": sale_id,
                "consumed_at": now,
                "reserved_by_sale_id": sale_id,
            },
        )
        return bool(updated)
    except Exception as e:
        logging.error("Failed to mark approval request %s as consumed by sale %s: %s", clean_id, sale_id, e)
        return False


def release_credit_approval(approval_request_id: str, sale_id: str) -> bool:
    """
    Releases an approval reservation if a sale failed prior to completion.
    Only releases if the approval was reserved by this sale and has NOT been consumed.
    """
    if not approval_request_id:
        return False
    clean_id = str(approval_request_id).strip()
    try:
        apprs = db.get_records("ApprovalRequests", fresh=True) or []
        appr = next((a for a in apprs if str(a.get("request_id", "")).strip() == clean_id), None)
        if appr:
            is_consumed = bool(appr.get("is_consumed"))
            holder = str(appr.get("reserved_by_sale_id", "")).strip()
            if not is_consumed and holder == sale_id:
                db.update_record("ApprovalRequests", "request_id", clean_id, {
                    "reserved_by_sale_id": "",
                    "reserved_at": "",
                })
                return True
    except Exception as e:
        logging.warning("Failed to release approval reservation %s: %s", clean_id, e)
    return False


def mark_approval_consumed(approval_request_id: str, sale_id: str) -> bool:
    """Backward-compatible wrapper for consume_credit_approval."""
    return consume_credit_approval(approval_request_id, sale_id)

