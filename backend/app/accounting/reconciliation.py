"""
Reconciliation & Audit Engine for Kawad Swad Double-Entry Accounting
Compares operational source-of-truth tables with the general journal ledger.
Supports safe dry-run discovery, idempotent backfill, and opening balance proposal.
"""
from decimal import Decimal
from typing import Dict, Any, List, Optional
import logging

from app.sheets import db
from app.accounting.journal_engine import (
    to_decimal,
    round_money,
    calculate_trial_balance,
)
from app.accounting.postings import (
    post_receipt_journal,
    post_milling_journal,
    post_production_batch_journal,
    post_packaging_batch_journal,
    post_sale_journal,
    post_daily_closing_cash_remittance_journal,
    post_expense_journal,
    post_payment_collection_journal,
)

logger = logging.getLogger(__name__)


def audit_and_reconcile_operational_events(
    dry_run: bool = True,
    actor: str = "RECONCILIATION_ENGINE",
) -> Dict[str, Any]:
    """
    Performs an authoritative operational vs ledger reconciliation.
    Identifies all historical and operational events lacking general journal postings.
    Distinguishes MISSING (never posted), FAILED, and INCOMPLETE vouchers.
    Detects duplicate references in JournalHeaders.
    When dry_run=False, safely and idempotently posts/repairs vouchers.
    """
    headers = db.get_records("JournalHeaders", fresh=True)
    posted_refs: Dict[str, Dict[str, Any]] = {}
    failed_refs: Dict[str, Dict[str, Any]] = {}
    incomplete_refs: Dict[str, Dict[str, Any]] = {}
    seen_refs: Dict[str, List[Dict[str, Any]]] = {}

    for h in headers:
        r_type = str(h.get("reference_type", "")).strip().upper()
        r_id = str(h.get("reference_id", "")).strip()
        st = str(h.get("status", "")).strip().upper()
        if r_type and r_id:
            k = f"{r_type}:{r_id}"
            seen_refs.setdefault(k, []).append(h)
            if st in {"POSTED", "VALID", "REVERSED"}:
                posted_refs[k] = h
            elif st == "FAILED":
                failed_refs[k] = h
            elif st == "INCOMPLETE":
                incomplete_refs[k] = h

    duplicate_references: List[Dict[str, Any]] = []
    for k, v in seen_refs.items():
        if len(v) > 1:
            duplicate_references.append({
                "reference_key": k,
                "voucher_count": len(v),
                "journal_ids": [str(x.get("journal_id")) for x in v],
            })

    unposted_events: List[Dict[str, Any]] = []
    failed_vouchers: List[Dict[str, Any]] = []
    incomplete_vouchers: List[Dict[str, Any]] = []
    missing_items: List[Dict[str, Any]] = []
    reconciled_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    def check_and_queue(source_table: str, ref_type: str, ref_id: str, date_str: str, desc: str, post_fn):
        ref_key = f"{ref_type}:{ref_id}"
        if ref_key in posted_refs:
            return  # Already posted and verified

        if ref_key in failed_refs:
            hdr = failed_refs[ref_key]
            issue_type = "FAILED"
            journal_id = str(hdr.get("journal_id"))
            fail_reason = str(hdr.get("narration", ""))
        elif ref_key in incomplete_refs:
            hdr = incomplete_refs[ref_key]
            issue_type = "INCOMPLETE"
            journal_id = str(hdr.get("journal_id"))
            fail_reason = "Voucher lines write was incomplete."
        else:
            issue_type = "MISSING"
            journal_id = ""
            fail_reason = "Voucher was never posted."

        item_info = {
            "source_table": source_table,
            "reference_type": ref_type,
            "reference_id": ref_id,
            "date": date_str,
            "description": desc,
            "issue_type": issue_type,
            "journal_id": journal_id,
            "failure_reason": fail_reason,
        }
        missing_items.append(item_info)
        if issue_type == "FAILED":
            failed_vouchers.append(item_info)
        elif issue_type == "INCOMPLETE":
            incomplete_vouchers.append(item_info)
        else:
            unposted_events.append(item_info)

        if not dry_run:
            try:
                res = post_fn()
                reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
            except Exception as e:
                errors.append({**item_info, "error": str(e)})

    # 1. Audit RawMaterialLedger (RECEIVE & DAL_MILLING)
    rm_records = db.get_records("RawMaterialLedger", fresh=True)
    for row in rm_records:
        txn_id = str(row.get("raw_material_txn_id", "")).strip()
        txn_type = str(row.get("txn_type", "")).upper()

        if txn_type == "RECEIVE":
            check_and_queue(
                "RawMaterialLedger",
                "RAW_MATERIAL_RECEIPT",
                txn_id,
                str(row.get("txn_datetime", ""))[:10],
                f"Receipt of {row.get('quantity_kg') or row.get('quantity')}kg {row.get('material_name_snapshot') or row.get('material_name')}",
                lambda r=row: post_receipt_journal(r, actor=actor),
            )
        elif txn_type in {"DAL_MILLING", "MILLING_ISSUE", "MILLING_YIELD"}:
            check_and_queue(
                "RawMaterialLedger",
                "DAL_MILLING",
                txn_id,
                str(row.get("txn_datetime", ""))[:10],
                f"Dal milling conversion {txn_id}",
                lambda r=row: post_milling_journal(r, actor=actor),
            )

    # 2. Audit ProductionBatches
    pb_records = db.get_records("ProductionBatches", fresh=True)
    for row in pb_records:
        batch_id = str(row.get("batch_id", "")).strip()
        status = str(row.get("status", "")).upper()
        if status == "APPROVED":
            check_and_queue(
                "ProductionBatches",
                "PRODUCTION_BATCH",
                batch_id,
                str(row.get("production_date", "") or row.get("created_at", ""))[:10],
                f"Approved bulk papad batch {batch_id} ({row.get('actual_output_kg')}kg)",
                lambda r=row: post_production_batch_journal(r, actor=actor),
            )

    # 3. Audit PackagingBatches
    pkg_records = db.get_records("PackagingBatches", fresh=True)
    for row in pkg_records:
        pkg_id = str(row.get("packaging_batch_id", "")).strip()
        status = str(row.get("status", "")).upper()
        if status == "APPROVED":
            check_and_queue(
                "PackagingBatches",
                "PACKAGING_BATCH",
                pkg_id,
                str(row.get("packaging_date", "") or row.get("created_at", ""))[:10],
                f"Approved packaging batch {pkg_id} ({row.get('packet_count')} pkts)",
                lambda r=row: post_packaging_batch_journal(r, actor=actor),
            )

    # 4. Audit Sales
    sales_records = db.get_records("Sales", fresh=True)
    for row in sales_records:
        sale_id = str(row.get("sale_id", "")).strip()
        status = str(row.get("bill_status", "")).upper()
        if status != "CANCELLED":
            check_and_queue(
                "Sales",
                "SALE_INVOICE",
                sale_id,
                str(row.get("sale_datetime", ""))[:10],
                f"Sales invoice {row.get('bill_number')} (₹{row.get('bill_total')})",
                lambda r=row: post_sale_journal(row, actor=actor),
            )

    # 5. Audit DailyClosing
    closing_records = db.get_records("DailyClosing", fresh=True)
    for row in closing_records:
        closing_id = str(row.get("closing_id", "")).strip()
        status = str(row.get("closing_status", "")).upper()
        if status in {"REVIEWED", "CONFIRMED", "APPROVED"}:
            check_and_queue(
                "DailyClosing",
                "DAILY_CLOSING_REMITTANCE",
                closing_id,
                str(row.get("closing_date", "")),
                f"Daily closing safe remittance {closing_id} (₹{row.get('physical_cash_returned')})",
                lambda r=row: post_daily_closing_cash_remittance_journal(row, actor=actor),
            )

    # 6. Audit Expenses
    expense_records = db.get_records("Expenses", fresh=True)
    for row in expense_records:
        exp_id = str(row.get("expense_id", "")).strip()
        status = str(row.get("approval_status", "")).upper()
        if status == "APPROVED":
            check_and_queue(
                "Expenses",
                "EXPENSE",
                exp_id,
                str(row.get("expense_datetime", ""))[:10],
                f"Expense {exp_id} ({row.get('category')} - ₹{row.get('amount')})",
                lambda r=row: post_expense_journal(row, actor=actor),
            )

    # 7. Audit Credit Customer Collections in Payments
    payment_records = db.get_records("Payments", fresh=True)
    for row in payment_records:
        pay_id = str(row.get("payment_id", "")).strip()
        status = str(row.get("payment_status", "")).upper()
        if status == "COLLECTED":
            check_and_queue(
                "Payments",
                "PAYMENT_COLLECTION",
                pay_id,
                str(row.get("payment_datetime", ""))[:10],
                f"Debt collection {pay_id} for sale {row.get('sale_id')} (₹{row.get('amount')})",
                lambda r=row: post_payment_collection_journal(row, actor=actor),
            )

    return {
        "status": "COMPLETED",
        "dry_run": dry_run,
        "missing_count": len(missing_items),
        "unposted_count": len(unposted_events),
        "failed_count": len(failed_vouchers),
        "incomplete_count": len(incomplete_vouchers),
        "duplicate_reference_count": len(duplicate_references),
        "reconciled_count": len(reconciled_items),
        "error_count": len(errors),
        "missing_events": missing_items,
        "unposted_events": unposted_events,
        "failed_vouchers": failed_vouchers,
        "incomplete_vouchers": incomplete_vouchers,
        "duplicate_references": duplicate_references,
        "reconciled_events": reconciled_items,
        "errors": errors,
    }


def propose_opening_balances() -> Dict[str, Any]:
    """
    Read-only calculation proposing standard opening balance accounts based on
    live operational physical stock, cash balances, and customer accounts receivable.
    Satisfies fundamental accounting equation: Assets = Liabilities + Equity.
    """
    # 1. Assets: Raw Material Inventory (1210 / 1220 / 1230)
    rm_records = db.get_records("RawMaterialLedger", fresh=True)
    whole_dal_kg = Decimal("0")
    flour_kg = Decimal("0")
    rm_value = Decimal("0")
    for r in rm_records:
        qty = to_decimal(r.get("quantity_kg", 0) or 0)
        rate = to_decimal(r.get("unit_price_inr", 0) or 0)
        t = str(r.get("txn_type", "")).upper()
        cat = str(r.get("category", "")).upper()
        if "WHOLE" in cat:
            whole_dal_kg += qty
        elif "FLOUR" in cat:
            flour_kg += qty
        rm_value += (qty * rate)

    # 2. Assets: Finished Goods Inventory (1240)
    pkg_records = db.get_records("PackagingBatches", fresh=True)
    fg_pkts = sum(int(float(p.get("packet_count", 0) or 0)) for p in pkg_records if str(p.get("status", "")).upper() == "APPROVED")
    # Estimated standard cost ₹45.00 / 500g packet
    fg_value = Decimal(str(fg_pkts)) * Decimal("45.00")

    # 3. Assets: Cash in Hand (Factory Safe 1110 & Van Floats 1115)
    cash_records = db.get_records("CashLedger", fresh=True)
    cash_balance = sum(to_decimal(c.get("amount", 0) or 0) for c in cash_records)
    factory_cash = max(Decimal("0"), cash_balance)

    # 4. Assets: Accounts Receivable / Debtors (1130)
    sales_records = db.get_records("Sales", fresh=True)
    payment_records = db.get_records("Payments", fresh=True)
    total_sales_value = sum(
        to_decimal(s.get("bill_total", 0) or 0)
        for s in sales_records
        if str(s.get("bill_status", "")).upper() != "CANCELLED"
    )
    total_collected = sum(
        to_decimal(p.get("amount", 0) or 0)
        for p in payment_records
        if str(p.get("payment_status", "")).upper() != "REFUNDED"
    )
    accounts_receivable = max(Decimal("0"), total_sales_value - total_collected)

    total_assets = rm_value + fg_value + factory_cash + accounts_receivable

    # Liabilities: Accrued Operating Expenses (2130) & GST (2210/2220)
    total_liabilities = Decimal("0.00")

    # Balancing Equity: Owner Capital (3100)
    owner_equity = total_assets - total_liabilities

    proposed_lines = [
        {"account_code": "1110", "account_name": "Cash in Factory Safe", "debit": round_money(factory_cash), "credit": 0.0},
        {"account_code": "1130", "account_name": "Accounts Receivable (Debtors)", "debit": round_money(accounts_receivable), "credit": 0.0},
        {"account_code": "1210", "account_name": "Raw Material - Whole Dal", "debit": round_money(rm_value), "credit": 0.0},
        {"account_code": "1240", "account_name": "Finished Goods - Packets", "debit": round_money(fg_value), "credit": 0.0},
        {"account_code": "3100", "account_name": "Owner's Capital", "debit": 0.0, "credit": round_money(owner_equity)},
    ]

    total_debits = sum(line["debit"] for line in proposed_lines)
    total_credits = sum(line["credit"] for line in proposed_lines)

    return {
        "status": "PROPOSED",
        "balance_check": "BALANCED" if abs(total_debits - total_credits) < 0.01 else "UNBALANCED",
        "total_assets": float(total_assets),
        "total_liabilities": float(total_liabilities),
        "owner_equity": float(owner_equity),
        "total_debits": round(total_debits, 2),
        "total_credits": round(total_credits, 2),
        "proposed_lines": proposed_lines,
        "note": "Read-only proposal. Opening balance migration remains withheld per strict safety rules.",
    }
