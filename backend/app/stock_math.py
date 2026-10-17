"""Single stock-balance definition for company packets and salesman packets.

Ledger quantity is stored as a positive magnitude. Direction comes from txn_type.
SOLD_DELIVERY may also be stored as a negative quantity by older writes; abs() is
applied so those rows are not subtracted twice.
"""
from typing import Dict, List, Tuple


COMPANY_IN = {"COMPANY_RECEIPT", "POSITIVE_ADJUSTMENT", "RETURN_FROM_SALESMAN"}
COMPANY_OUT = {"ISSUE_TO_SALESMAN"}
SALESMAN_IN = {"ISSUE_TO_SALESMAN", "SALESMAN_POSITIVE_ADJUSTMENT"}
SALESMAN_OUT = {"RETURN_FROM_SALESMAN", "SOLD_DELIVERY", "SALE_DELIVERY"}


def _qty(txn: dict) -> int:
    try:
        return abs(int(float(txn.get("quantity", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def _type(txn: dict) -> str:
    return str(txn.get("txn_type", "")).upper()


def apply_transaction(company: Dict[str, int], salesman: Dict[Tuple[str, str], int], txn: dict) -> None:
    product_id = str(txn.get("product_id", "")).strip()
    if not product_id:
        return
    user_id = str(txn.get("salesman_user_id", "")).strip()
    kind = _type(txn)
    qty = _qty(txn)
    if kind in COMPANY_IN:
        company[product_id] = company.get(product_id, 0) + qty
    elif kind in COMPANY_OUT:
        company[product_id] = company.get(product_id, 0) - qty
    if user_id and kind in SALESMAN_IN:
        key = (user_id, product_id)
        salesman[key] = salesman.get(key, 0) + qty
    elif user_id and kind in SALESMAN_OUT:
        key = (user_id, product_id)
        salesman[key] = salesman.get(key, 0) - qty


def balances(transactions: List[dict]):
    company: Dict[str, int] = {}
    salesman: Dict[Tuple[str, str], int] = {}
    for txn in transactions:
        apply_transaction(company, salesman, txn)
    return company, salesman


def salesman_available(transactions: List[dict], salesman_user_id: str, product_id: str) -> int:
    _, salesman = balances(transactions)
    return int(salesman.get((salesman_user_id, product_id), 0))
