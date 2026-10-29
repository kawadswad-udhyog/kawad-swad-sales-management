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
    When dry_run=False, safely and idempotently posts missing vouchers.
    """
    headers = db.get_records("JournalHeaders", fresh=True)
    existing_posted_refs = {
        f"{str(h.get('reference_type', '')).strip()}:{str(h.get('reference_id', '')).strip()}": h
        for h in headers
        if str(h.get("status", "")).upper() in {"POSTED", "REVERSED"}
    }

    missing_items: List[Dict[str, Any]] = []
    reconciled_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    # 1. Audit RawMaterialLedger (RECEIVE & DAL_MILLING)
    rm_records = db.get_records("RawMaterialLedger", fresh=True)
    for row in rm_records:
        txn_id = str(row.get("raw_material_txn_id", "")).strip()
        txn_type = str(row.get("txn_type", "")).upper()

        if txn_type == "RECEIVE":
            ref_key = f"RAW_MATERIAL_RECEIPT:{txn_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "RawMaterialLedger",
                    "reference_type": "RAW_MATERIAL_RECEIPT",
                    "reference_id": txn_id,
                    "date": row.get("txn_datetime", "")[:10],
                    "description": f"Receipt of {row.get('quantity_kg')}kg {row.get('material_name_snapshot')}",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_receipt_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

        elif txn_type in {"DAL_MILLING", "MILLING_ISSUE", "MILLING_YIELD"}:
            ref_key = f"DAL_MILLING:{txn_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "RawMaterialLedger",
                    "reference_type": "DAL_MILLING",
                    "reference_id": txn_id,
                    "date": row.get("txn_datetime", "")[:10],
                    "description": f"Dal milling conversion {txn_id}",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_milling_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

    # 2. Audit ProductionBatches
    pb_records = db.get_records("ProductionBatches", fresh=True)
    for row in pb_records:
        batch_id = str(row.get("batch_id", "")).strip()
        status = str(row.get("status", "")).upper()
        if status == "APPROVED":
            ref_key = f"PRODUCTION_BATCH:{batch_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "ProductionBatches",
                    "reference_type": "PRODUCTION_BATCH",
                    "reference_id": batch_id,
                    "date": row.get("production_date", "") or row.get("created_at", "")[:10],
                    "description": f"Approved bulk papad batch {batch_id} ({row.get('actual_output_kg')}kg)",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_production_batch_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

    # 3. Audit PackagingBatches
    pkg_records = db.get_records("PackagingBatches", fresh=True)
    for row in pkg_records:
        pkg_id = str(row.get("packaging_batch_id", "")).strip()
        status = str(row.get("status", "")).upper()
        if status == "APPROVED":
            ref_key = f"PACKAGING_BATCH:{pkg_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "PackagingBatches",
                    "reference_type": "PACKAGING_BATCH",
                    "reference_id": pkg_id,
                    "date": row.get("packaging_date", "") or row.get("created_at", "")[:10],
                    "description": f"Approved packaging batch {pkg_id} ({row.get('packet_count')} pkts)",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_packaging_batch_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

    # 4. Audit Sales
    sales_records = db.get_records("Sales", fresh=True)
    for row in sales_records:
        sale_id = str(row.get("sale_id", "")).strip()
        status = str(row.get("bill_status", "")).upper()
        if status != "CANCELLED":
            ref_key = f"SALE_INVOICE:{sale_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "Sales",
                    "reference_type": "SALE_INVOICE",
                    "reference_id": sale_id,
                    "date": str(row.get("sale_datetime", ""))[:10],
                    "description": f"Sales invoice {row.get('bill_number')} (₹{row.get('bill_total')})",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_sale_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

    # 5. Audit DailyClosing
    closing_records = db.get_records("DailyClosing", fresh=True)
    for row in closing_records:
        closing_id = str(row.get("closing_id", "")).strip()
        status = str(row.get("closing_status", "")).upper()
        if status in {"REVIEWED", "CONFIRMED", "APPROVED"}:
            ref_key = f"DAILY_CLOSING_REMITTANCE:{closing_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "DailyClosing",
                    "reference_type": "DAILY_CLOSING_REMITTANCE",
                    "reference_id": closing_id,
                    "date": str(row.get("closing_date", "")),
                    "description": f"Daily closing safe remittance {closing_id} (₹{row.get('physical_cash_returned')})",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_daily_closing_cash_remittance_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

    # 6. Audit Expenses
    expense_records = db.get_records("Expenses", fresh=True)
    for row in expense_records:
        exp_id = str(row.get("expense_id", "")).strip()
        status = str(row.get("approval_status", "")).upper()
        if status == "APPROVED":
            ref_key = f"EXPENSE:{exp_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "Expenses",
                    "reference_type": "EXPENSE",
                    "reference_id": exp_id,
                    "date": str(row.get("expense_datetime", ""))[:10],
                    "description": f"Expense {exp_id} ({row.get('category')} - ₹{row.get('amount')})",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_expense_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

    # 7. Audit Credit Customer Collections in Payments
    payment_records = db.get_records("Payments", fresh=True)
    for row in payment_records:
        pay_id = str(row.get("payment_id", "")).strip()
        status = str(row.get("payment_status", "")).upper()
        if status == "COLLECTED":
            ref_key = f"PAYMENT_COLLECTION:{pay_id}"
            if ref_key not in existing_posted_refs:
                item_info = {
                    "source_table": "Payments",
                    "reference_type": "PAYMENT_COLLECTION",
                    "reference_id": pay_id,
                    "date": str(row.get("payment_datetime", ""))[:10],
                    "description": f"Debt collection {pay_id} for sale {row.get('sale_id')} (₹{row.get('amount')})",
                }
                missing_items.append(item_info)
                if not dry_run:
                    try:
                        res = post_payment_collection_journal(row, actor=actor)
                        reconciled_items.append({**item_info, "voucher_id": res.get("voucher_id")})
                    except Exception as e:
                        errors.append({**item_info, "error": str(e)})

    return {
        "status": "COMPLETED",
        "dry_run": dry_run,
        "missing_count": len(missing_items),
        "reconciled_count": len(reconciled_items),
        "error_count": len(errors),
        "missing_events": missing_items,
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
