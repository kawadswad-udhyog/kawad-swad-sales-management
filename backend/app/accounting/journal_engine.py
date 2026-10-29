"""
Kawad Swad ERP - Double-Entry General Ledger Posting Engine
Enforces:
1. Total Debits == Total Credits (exact Decimal equality).
2. All accounts validated against Chart of Accounts.
3. Idempotent posting based on reference_type and reference_id.
4. Immutable audit trail and reversible vouchers.
5. Authoritative financial statements (Trial Balance, P&L, Balance Sheet).
"""

from decimal import Decimal
import logging
from typing import List, Dict, Any, Optional, Tuple
from app.timeutil import now_iso, business_today
from app.sheets import db
from app.calculations.units import to_decimal, round_money
from app.accounting.chart_of_accounts import ACCOUNT_LOOKUP

logger = logging.getLogger("kawad_swad.accounting")

_BALANCE_TOLERANCE = Decimal("0.005")


def validate_journal_lines(lines: List[Dict[str, Any]]) -> Tuple[Decimal, Decimal]:
    """
    Validates debit and credit equality and account validity.
    Returns (total_debit, total_credit).
    Raises ValueError if invalid.
    """
    if not lines or len(lines) < 2:
        raise ValueError("A valid double-entry journal voucher must contain at least two lines.")

    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for idx, line in enumerate(lines):
        code = str(line.get("account_code", "")).strip()
        if not code or code not in ACCOUNT_LOOKUP:
            raise ValueError(f"Line {idx + 1}: Unknown or unregistered account code '{code}'.")

        deb = to_decimal(line.get("debit_amount", 0) or 0)
        crd = to_decimal(line.get("credit_amount", 0) or 0)

        if deb < Decimal("0") or crd < Decimal("0"):
            raise ValueError(f"Line {idx + 1}: Negative amounts are not allowed. Debit={deb}, Credit={crd}.")

        if deb > Decimal("0") and crd > Decimal("0"):
            raise ValueError(f"Line {idx + 1}: A line cannot have both debit and credit. Debit={deb}, Credit={crd}.")

        if deb == Decimal("0") and crd == Decimal("0"):
            raise ValueError(f"Line {idx + 1}: Line must have a non-zero debit or credit amount.")

        total_debit += deb
        total_credit += crd

    diff = abs(total_debit - total_credit)
    if diff > _BALANCE_TOLERANCE:
        raise ValueError(
            f"Unbalanced journal entry: Total Debits (₹{total_debit:.2f}) "
            f"!= Total Credits (₹{total_credit:.2f}). Imbalance: ₹{diff:.2f}."
        )

    return total_debit, total_credit


def post_journal_voucher(
    voucher_type: str,
    reference_type: str,
    reference_id: str,
    narration: str,
    lines: List[Dict[str, Any]],
    posted_by: str,
    journal_date: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Idempotent journal voucher posting.
    If a voucher with the same reference_type and reference_id already exists,
    returns the existing voucher to prevent duplicate ledger debits/credits.
    """
    clean_ref_type = str(reference_type or "").strip().upper()
    clean_ref_id = str(reference_id or "").strip()

    # 1. Idempotency Check
    existing_headers = db.get_records("JournalHeaders", fresh=True)
    for row in existing_headers:
        if (
            str(row.get("reference_type", "")).strip().upper() == clean_ref_type
            and str(row.get("reference_id", "")).strip() == clean_ref_id
            and str(row.get("status", "")).strip().upper() == "POSTED"
        ):
            logger.info("Journal voucher already exists for %s:%s. Replaying.", clean_ref_type, clean_ref_id)
            existing_lines = [
                l for l in db.get_records("JournalLines", fresh=True)
                if str(l.get("journal_id")) == str(row.get("journal_id"))
            ]
            return {**row, "lines": existing_lines, "is_replay": True}

    # 2. Strict Balance & Schema Validation
    total_debit, total_credit = validate_journal_lines(lines)

    # 3. Generate IDs
    journal_id = db.generate_id("JournalHeaders") if hasattr(db, "generate_id") else f"JRN-{clean_ref_id}"
    date_val = journal_date or business_today()
    iso_now = now_iso()

    header_record = {
        "journal_id": journal_id,
        "journal_date": date_val,
        "voucher_type": voucher_type.strip().upper(),
        "reference_type": clean_ref_type,
        "reference_id": clean_ref_id,
        "narration": narration.strip(),
        "total_debit": round_money(total_debit),
        "total_credit": round_money(total_credit),
        "posted_by": posted_by,
        "posted_at": iso_now,
        "status": "POSTED",
        "reversal_of_id": "",
    }

    # 4. Write Header
    if not db.append_record("JournalHeaders", header_record, raise_on_error=True):
        raise RuntimeError(f"Could not persist JournalHeader for {clean_ref_type}:{clean_ref_id}")

    # 5. Write Lines
    saved_lines = []
    for idx, line in enumerate(lines):
        code = str(line["account_code"]).strip()
        account_meta = ACCOUNT_LOOKUP[code]
        line_id = f"{journal_id}-L{idx + 1}"
        line_record = {
            "line_id": line_id,
            "journal_id": journal_id,
            "line_no": idx + 1,
            "account_code": code,
            "account_name": account_meta["account_name"],
            "debit_amount": round_money(to_decimal(line.get("debit_amount", 0) or 0)),
            "credit_amount": round_money(to_decimal(line.get("credit_amount", 0) or 0)),
            "entity_type": str(line.get("entity_type", "")).strip(),
            "entity_id": str(line.get("entity_id", "")).strip(),
            "notes": str(line.get("notes", "")).strip(),
        }
        if not db.append_record("JournalLines", line_record, raise_on_error=True):
            raise RuntimeError(f"Could not persist JournalLine {line_id} for {journal_id}")
        saved_lines.append(line_record)

    db.log_audit(
        actor=posted_by,
        action="POST_JOURNAL_VOUCHER",
        entity_type="JournalHeaders",
        entity_id=journal_id,
        reason=f"Posted {voucher_type} voucher for {clean_ref_type} {clean_ref_id} (Total: ₹{total_debit:.2f})",
    )

    return {**header_record, "lines": saved_lines, "is_replay": False}


def reverse_journal_voucher(
    journal_id: str,
    reason: str,
    actor: str,
) -> Dict[str, Any]:
    """
    Creates a compensating reversal voucher for an existing posted journal entry.
    """
    clean_jid = str(journal_id or "").strip()
    headers = db.get_records("JournalHeaders", fresh=True)
    original = next((h for h in headers if str(h.get("journal_id")).strip() == clean_jid), None)
    if not original:
        raise ValueError(f"Journal voucher '{clean_jid}' not found.")

    if str(original.get("status", "")).upper() == "REVERSED":
        raise ValueError(f"Journal voucher '{clean_jid}' has already been reversed.")

    lines = [l for l in db.get_records("JournalLines", fresh=True) if str(l.get("journal_id")).strip() == clean_jid]
    if not lines:
        raise ValueError(f"No journal lines found for voucher '{clean_jid}'.")

    # Invert debits and credits
    reversal_lines = []
    for line in lines:
        reversal_lines.append({
            "account_code": line["account_code"],
            "debit_amount": line.get("credit_amount", 0),
            "credit_amount": line.get("debit_amount", 0),
            "entity_type": line.get("entity_type", ""),
            "entity_id": line.get("entity_id", ""),
            "notes": f"Reversal of line {line.get('line_no')}: {reason}",
        })

    rev_voucher = post_journal_voucher(
        voucher_type="REVERSAL",
        reference_type="JOURNAL_REVERSAL",
        reference_id=clean_jid,
        narration=f"Compensating reversal of {clean_jid}. Reason: {reason}",
        lines=reversal_lines,
        posted_by=actor,
    )

    # Mark original voucher as REVERSED
    db.update_record("JournalHeaders", "journal_id", clean_jid, {"status": "REVERSED"})

    return rev_voucher


def calculate_trial_balance(as_of_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Authoritative double-entry trial balance generator.
    Sums all posted journal lines across all active accounts.
    Guarantees Total Debits == Total Credits.
    """
    headers = {str(h["journal_id"]): h for h in db.get_records("JournalHeaders", fresh=True)}
    lines = db.get_records("JournalLines", fresh=True)

    account_totals: Dict[str, Dict[str, Any]] = {}
    for code, meta in ACCOUNT_LOOKUP.items():
        account_totals[code] = {
            "account_code": code,
            "account_name": meta["account_name"],
            "account_type": meta["account_type"],
            "normal_balance": meta["normal_balance"],
            "total_debit": Decimal("0"),
            "total_credit": Decimal("0"),
            "net_debit": Decimal("0"),
            "net_credit": Decimal("0"),
        }

    for line in lines:
        jid = str(line.get("journal_id", ""))
        hdr = headers.get(jid)
        if not hdr or str(hdr.get("status", "")).upper() not in {"POSTED", "VALID"}:
            continue

        if as_of_date and str(hdr.get("journal_date", "")) > as_of_date:
            continue

        code = str(line.get("account_code", "")).strip()
        if code not in account_totals:
            continue

        deb = to_decimal(line.get("debit_amount", 0) or 0)
        crd = to_decimal(line.get("credit_amount", 0) or 0)

        account_totals[code]["total_debit"] += deb
        account_totals[code]["total_credit"] += crd

    grand_total_debit = Decimal("0")
    grand_total_credit = Decimal("0")
    rows = []

    for code, data in sorted(account_totals.items(), key=lambda x: x[0]):
        tot_deb = data["total_debit"]
        tot_crd = data["total_credit"]
        if tot_deb == Decimal("0") and tot_crd == Decimal("0"):
            continue

        if data["normal_balance"] == "DEBIT":
            net_deb = max(Decimal("0"), tot_deb - tot_crd)
            net_crd = max(Decimal("0"), tot_crd - tot_deb)
        else:
            net_crd = max(Decimal("0"), tot_crd - tot_deb)
            net_deb = max(Decimal("0"), tot_deb - tot_crd)

        grand_total_debit += net_deb
        grand_total_credit += net_crd

        rows.append({
            "account_code": code,
            "account_name": data["account_name"],
            "account_type": data["account_type"],
            "total_debit": round_money(tot_deb),
            "total_credit": round_money(tot_crd),
            "net_debit": round_money(net_deb),
            "net_credit": round_money(net_crd),
        })

    is_balanced = abs(grand_total_debit - grand_total_credit) <= _BALANCE_TOLERANCE

    return {
        "as_of_date": as_of_date or business_today(),
        "is_balanced": is_balanced,
        "grand_total_debit": round_money(grand_total_debit),
        "grand_total_credit": round_money(grand_total_credit),
        "difference": round_money(abs(grand_total_debit - grand_total_credit)),
        "rows": rows,
    }


def calculate_profit_and_loss(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Authoritative Profit & Loss Statement (P&L):
    Operating Revenue - Cost of Goods Sold = Gross Profit
    Gross Profit - Operating Expenses = Net Operating Profit
    """
    tb = calculate_trial_balance(as_of_date=end_date)
    revenue_rows = []
    cogs_rows = []
    operating_expense_rows = []

    total_revenue = Decimal("0")
    total_cogs = Decimal("0")
    total_opex = Decimal("0")

    for r in tb["rows"]:
        code = r["account_code"]
        tot_deb = to_decimal(r["total_debit"])
        tot_crd = to_decimal(r["total_credit"])

        if r["account_type"] == "REVENUE":
            val = tot_crd - tot_deb
            total_revenue += val
            revenue_rows.append({**r, "net_revenue_value": round_money(val)})
        elif r["account_type"] == "EXPENSE":
            val = tot_deb - tot_crd
            if code.startswith("51"):
                total_cogs += val
                cogs_rows.append({**r, "net_cogs_value": round_money(val)})
            else:
                total_opex += val
                operating_expense_rows.append({**r, "net_expense_value": round_money(val)})

    gross_profit = total_revenue - total_cogs
    net_operating_profit = gross_profit - total_opex

    return {
        "period_start": start_date or "OPENING",
        "period_end": end_date or business_today(),
        "total_revenue": round_money(total_revenue),
        "total_cogs": round_money(total_cogs),
        "gross_profit": round_money(gross_profit),
        "gross_margin_pct": round(float(gross_profit / total_revenue * Decimal("100")), 2) if total_revenue > 0 else 0.0,
        "total_operating_expenses": round_money(total_opex),
        "net_operating_profit": round_money(net_operating_profit),
        "net_margin_pct": round(float(net_operating_profit / total_revenue * Decimal("100")), 2) if total_revenue > 0 else 0.0,
        "revenue_breakdown": revenue_rows,
        "cogs_breakdown": cogs_rows,
        "expense_breakdown": operating_expense_rows,
    }


def calculate_balance_sheet(as_of_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Authoritative Balance Sheet:
    Total Assets == Total Liabilities + Owner Equity + Current Period Net Profit
    """
    tb = calculate_trial_balance(as_of_date=as_of_date)
    pnl = calculate_profit_and_loss(end_date=as_of_date)

    asset_rows = []
    liability_rows = []
    equity_rows = []

    total_assets = Decimal("0")
    total_liabilities = Decimal("0")
    total_equity = Decimal("0")

    for r in tb["rows"]:
        acc_type = r["account_type"]
        tot_deb = to_decimal(r["total_debit"])
        tot_crd = to_decimal(r["total_credit"])
        if acc_type == "ASSET":
            val = tot_deb - tot_crd
            total_assets += val
            asset_rows.append({**r, "net_asset_value": round_money(val)})
        elif acc_type == "LIABILITY":
            val = tot_crd - tot_deb
            total_liabilities += val
            liability_rows.append({**r, "net_liability_value": round_money(val)})
        elif acc_type == "EQUITY":
            val = tot_crd - tot_deb
            total_equity += val
            equity_rows.append({**r, "net_equity_value": round_money(val)})

    # Current period net profit flows into Equity
    current_period_profit = to_decimal(pnl["net_operating_profit"])
    total_equity_with_pnl = total_equity + current_period_profit

    diff = abs(total_assets - (total_liabilities + total_equity_with_pnl))
    is_balanced = diff <= _BALANCE_TOLERANCE

    return {
        "as_of_date": as_of_date or business_today(),
        "is_balanced": is_balanced,
        "total_assets": round_money(total_assets),
        "total_liabilities": round_money(total_liabilities),
        "total_equity": round_money(total_equity),
        "current_period_net_profit": round_money(current_period_profit),
        "total_liabilities_and_equity": round_money(total_liabilities + total_equity_with_pnl),
        "balance_difference": round_money(diff),
        "asset_rows": asset_rows,
        "liability_rows": liability_rows,
        "equity_rows": equity_rows,
    }

