"""
Kawad Swad ERP - Accounting Engine Compatibility Module
Exposes journal engine functions for backward compatibility with app.accounting.engine imports.
"""
from app.accounting.journal_engine import (
    validate_journal_lines,
    post_journal_voucher,
    append_journal_voucher,
    reverse_journal_voucher,
    calculate_trial_balance,
    calculate_profit_and_loss,
    calculate_balance_sheet,
)

__all__ = [
    "validate_journal_lines",
    "post_journal_voucher",
    "append_journal_voucher",
    "reverse_journal_voucher",
    "calculate_trial_balance",
    "calculate_profit_and_loss",
    "calculate_balance_sheet",
]
