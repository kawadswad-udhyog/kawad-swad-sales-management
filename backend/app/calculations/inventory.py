"""
Authoritative Inventory Engine
Implements Part 2 and Part 7 of the specification.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from .units import (
    round_stock,
    to_decimal,
)


def calculate_bulk_stock_balance(
    ledger_records: List[Dict[str, Any]],
    bulk_key_or_product_id: Optional[str] = None,
) -> Dict[str, float]:
    """
    Calculate bulk stock balances from ProductionStockLedger movements:
    Bulk stock = sum(BULK_PRODUCED) - sum(BULK_PACKAGED) + sum(BULK_ADJUSTMENT)
    """
    balances: Dict[str, Decimal] = {}

    for row in ledger_records:
        typ = str(row.get("movement_type", "")).strip().upper()
        kg_raw = row.get("quantity_kg", 0) or 0
        kg_dec = to_decimal(kg_raw)

        # Key definition
        key = str(row.get("bulk_product_key") or row.get("product_name_snapshot") or row.get("product_id") or "").strip().lower()
        if not key:
            continue

        if key not in balances:
            balances[key] = Decimal("0")

        if typ == "BULK_PRODUCED":
            balances[key] += kg_dec
        elif typ == "BULK_PACKAGED":
            balances[key] -= kg_dec
        elif typ == "BULK_ADJUSTMENT":
            balances[key] += kg_dec

    result = {k: round_stock(v) for k, v in balances.items()}

    if bulk_key_or_product_id:
        target = str(bulk_key_or_product_id).strip().lower()
        return {target: result.get(target, 0.0)}

    return result


def calculate_finished_stock_balance(
    ledger_records: List[Dict[str, Any]],
    product_id: Optional[str] = None,
) -> Dict[str, int]:
    """
    Calculate factory finished packet balances from ProductionStockLedger:
    Finished stock = sum(PACKETS_PACKAGED) + sum(PACKET_RETURN) - sum(CHANNEL_DISPATCH) + adjustments
    """
    balances: Dict[str, int] = {}

    for row in ledger_records:
        typ = str(row.get("movement_type", "")).strip().upper()
        qty = int(float(row.get("quantity_packets", 0) or 0))
        pid = str(row.get("product_id", "")).strip()
        if not pid:
            continue

        if pid not in balances:
            balances[pid] = 0

        if typ in {"PACKETS_PACKAGED", "PACKET_RETURN"}:
            balances[pid] += qty
        elif typ == "CHANNEL_DISPATCH":
            balances[pid] -= qty
        elif typ == "PACKET_ADJUSTMENT":
            balances[pid] += qty

    if product_id:
        clean_pid = str(product_id).strip()
        return {clean_pid: balances.get(clean_pid, 0)}

    return balances


def calculate_raw_material_balance(
    raw_material_id_or_name: str,
    raw_materials_master: List[Dict[str, Any]],
    raw_material_ledger: List[Dict[str, Any]],
    exclude_production_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculate available stock for a raw material:
    opening_stock - sum(PRODUCTION_CONSUMPTION) + sum(PURCHASE_RECEIPT) + adjustments
    """
    target = str(raw_material_id_or_name).strip().lower()

    # Find master opening stock
    master_row = next(
        (r for r in raw_materials_master
         if str(r.get("material_name", "")).strip().lower() == target
         or str(r.get("raw_material_id", "")).strip().lower() == target),
        None
    )

    if not master_row:
        return {
            "exists": False,
            "material_name": raw_material_id_or_name,
            "opening_stock": 0.0,
            "consumed": 0.0,
            "available": 0.0,
            "unit": "kg",
        }

    opening = to_decimal(master_row.get("current_stock") or master_row.get("opening_stock") or 0)
    unit = str(master_row.get("unit", "kg")).strip()

    consumed = Decimal("0")
    received = Decimal("0")

    for row in raw_material_ledger:
        m_name = str(row.get("material_name", "")).strip().lower()
        m_id = str(row.get("raw_material_id", "")).strip().lower()
        if m_name != target and m_id != target:
            continue

        # If we are checking available stock for a batch retry, exclude current batch consumption
        if exclude_production_id and str(row.get("production_id", "")).strip() == exclude_production_id:
            continue

        typ = str(row.get("movement_type", "")).strip().upper()
        qty = to_decimal(row.get("quantity", 0) or 0)

        if typ in {"PRODUCTION_CONSUMPTION", "ISSUE", "WASTAGE"}:
            consumed += qty
        elif typ in {"PURCHASE_RECEIPT", "STOCK_IN", "RETURN"}:
            received += qty

    available = opening - consumed + received

    return {
        "exists": True,
        "raw_material_id": str(master_row.get("raw_material_id", "")),
        "material_name": str(master_row.get("material_name", raw_material_id_or_name)),
        "opening_stock": round_stock(opening),
        "consumed": round_stock(consumed),
        "received": round_stock(received),
        "available": round_stock(available),
        "unit": unit,
    }
