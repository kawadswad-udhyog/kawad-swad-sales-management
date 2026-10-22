"""
Authoritative Inventory Engine
Implements Part 2 and Part 7 of the specification.
"""

from typing import Any, Dict, List, Optional, Tuple
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


def calculate_warehouse_stock_balance(
    salesman_stock_ledger: List[Dict[str, Any]],
    product_id: Optional[str] = None,
) -> Dict[str, int]:
    """
    Calculate Central Warehouse (Company) packet balances from SalesmanStockLedger:
    Warehouse = sum(COMPANY_RECEIPT + POSITIVE_ADJUSTMENT + RETURN_FROM_SALESMAN + COMPANY_ADJUSTMENT)
              - sum(ISSUE_TO_SALESMAN + ISSUED + NEGATIVE_ADJUSTMENT)
    """
    balances: Dict[str, int] = {}
    for txn in salesman_stock_ledger:
        pid = str(txn.get("product_id", "")).strip()
        if not pid:
            continue
        kind = str(txn.get("txn_type", "")).strip().upper()
        try:
            qty = abs(int(float(txn.get("quantity", 0) or 0)))
        except (TypeError, ValueError):
            qty = 0

        if kind in {"COMPANY_RECEIPT", "POSITIVE_ADJUSTMENT", "RETURN_FROM_SALESMAN", "COMPANY_ADJUSTMENT"}:
            balances[pid] = balances.get(pid, 0) + qty
        elif kind in {"ISSUE_TO_SALESMAN", "ISSUED", "NEGATIVE_ADJUSTMENT"}:
            balances[pid] = balances.get(pid, 0) - qty

    if product_id:
        clean_pid = str(product_id).strip()
        return {clean_pid: balances.get(clean_pid, 0)}
    return balances


def calculate_salesman_stock_balance(
    salesman_stock_ledger: List[Dict[str, Any]],
    salesman_user_id: Optional[str] = None,
    product_id: Optional[str] = None,
) -> Any:
    """
    Calculate Salesman assigned packet balances from SalesmanStockLedger:
    Salesman = sum(ISSUE_TO_SALESMAN + SALESMAN_POSITIVE_ADJUSTMENT + ISSUED)
             - sum(RETURN_FROM_SALESMAN + SOLD_DELIVERY + SALE_DELIVERY + RETURNED + SALESMAN_NEGATIVE_ADJUSTMENT)
    """
    salesman_map: Dict[Tuple[str, str], int] = {}
    for txn in salesman_stock_ledger:
        pid = str(txn.get("product_id", "")).strip()
        s_user = str(txn.get("salesman_user_id", "")).strip()
        if not pid or not s_user:
            continue
        kind = str(txn.get("txn_type", "")).strip().upper()
        try:
            qty = abs(int(float(txn.get("quantity", 0) or 0)))
        except (TypeError, ValueError):
            qty = 0

        key = (s_user, pid)
        if kind in {"ISSUE_TO_SALESMAN", "SALESMAN_POSITIVE_ADJUSTMENT", "ISSUED"}:
            salesman_map[key] = salesman_map.get(key, 0) + qty
        elif kind in {"RETURN_FROM_SALESMAN", "SOLD_DELIVERY", "SALE_DELIVERY", "RETURNED", "SALESMAN_NEGATIVE_ADJUSTMENT"}:
            salesman_map[key] = salesman_map.get(key, 0) - qty

    if salesman_user_id and product_id:
        return salesman_map.get((salesman_user_id.strip(), product_id.strip()), 0)
    elif salesman_user_id:
        return {pid: qty for (s_id, pid), qty in salesman_map.items() if s_id == salesman_user_id.strip()}
    return salesman_map


def calculate_physical_count_variance(
    expected_count: int,
    physical_count: int,
) -> Dict[str, Any]:
    """
    Calculates physical stock reconciliation variance:
    variance = physical_count - expected_count
    """
    expected = int(expected_count or 0)
    physical = int(physical_count or 0)
    variance = physical - expected
    return {
        "expected_stock": expected,
        "physical_count": physical,
        "variance": variance,
        "status": "BALANCED" if variance == 0 else ("SURPLUS" if variance > 0 else "DEFICIT"),
    }



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


def calculate_consolidated_finished_goods_register(
    products_master: List[Dict[str, Any]],
    production_stock_ledger: List[Dict[str, Any]],
    salesman_stock_ledger: List[Dict[str, Any]],
    users_master: Optional[List[Dict[str, Any]]] = None,
    sale_items_records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Consolidated Finished Goods Stock Register.
    Calculates stock across all active packet SKUs and locations:
    Factory, Warehouse, Salesmen, Channels.
    Guarantees every active packet SKU is present (including 0 stock).
    """
    def _is_truthy(val: Any) -> bool:
        if isinstance(val, bool):
            return val
        s = str(val or "").strip().lower()
        return s in {"true", "1", "yes", "y", "t"}

    users_map = {}
    if users_master:
        for u in users_master:
            uid = str(u.get("user_id", "")).strip()
            name = str(u.get("full_name") or u.get("username") or uid).strip()
            if uid:
                users_map[uid] = name

    # 1. Factory finished stock ledger calculations per product_id
    factory_packaged: Dict[str, int] = {}
    factory_returns: Dict[str, int] = {}
    factory_adjustments: Dict[str, int] = {}
    factory_dispatches: Dict[str, int] = {}
    channel_dispatches: Dict[str, Dict[str, int]] = {}
    last_movements: Dict[str, str] = {}

    for row in production_stock_ledger:
        pid = str(row.get("product_id", "")).strip()
        if not pid:
            continue
        typ = str(row.get("movement_type", "")).strip().upper()
        qty = int(float(row.get("quantity_packets", 0) or 0))
        txn_dt = str(row.get("txn_datetime") or row.get("created_at") or "").strip()
        channel = str(row.get("channel", "")).strip().upper()

        if txn_dt and (pid not in last_movements or txn_dt > last_movements[pid]):
            last_movements[pid] = txn_dt

        if typ == "PACKETS_PACKAGED":
            factory_packaged[pid] = factory_packaged.get(pid, 0) + qty
        elif typ == "PACKET_RETURN":
            factory_returns[pid] = factory_returns.get(pid, 0) + qty
        elif typ == "PACKET_ADJUSTMENT":
            factory_adjustments[pid] = factory_adjustments.get(pid, 0) + qty
        elif typ == "CHANNEL_DISPATCH":
            factory_dispatches[pid] = factory_dispatches.get(pid, 0) + qty
            if pid not in channel_dispatches:
                channel_dispatches[pid] = {}
            chan_key = channel or "OTHER"
            channel_dispatches[pid][chan_key] = channel_dispatches[pid].get(chan_key, 0) + qty

    # 2. Warehouse & Salesman stock calculations from SalesmanStockLedger
    warehouse_balances: Dict[str, int] = {}
    salesman_balances: Dict[str, Dict[str, int]] = {}  # pid -> {salesman_id: qty}

    for txn in salesman_stock_ledger:
        pid = str(txn.get("product_id", "")).strip()
        if not pid:
            continue
        s_user = str(txn.get("salesman_user_id", "")).strip()
        kind = str(txn.get("txn_type", "")).strip().upper()
        try:
            qty = abs(int(float(txn.get("quantity", 0) or 0)))
        except (TypeError, ValueError):
            qty = 0
        txn_dt = str(txn.get("txn_datetime") or "").strip()

        if txn_dt and (pid not in last_movements or txn_dt > last_movements[pid]):
            last_movements[pid] = txn_dt

        # Warehouse (Company) logic
        if kind in {"COMPANY_RECEIPT", "POSITIVE_ADJUSTMENT", "RETURN_FROM_SALESMAN", "COMPANY_ADJUSTMENT"}:
            warehouse_balances[pid] = warehouse_balances.get(pid, 0) + qty
        elif kind in {"ISSUE_TO_SALESMAN", "ISSUED", "NEGATIVE_ADJUSTMENT"}:
            warehouse_balances[pid] = warehouse_balances.get(pid, 0) - qty

        # Salesman logic
        if s_user:
            if pid not in salesman_balances:
                salesman_balances[pid] = {}
            if kind in {"ISSUE_TO_SALESMAN", "SALESMAN_POSITIVE_ADJUSTMENT", "ISSUED"}:
                salesman_balances[pid][s_user] = salesman_balances[pid].get(s_user, 0) + qty
            elif kind in {"RETURN_FROM_SALESMAN", "SOLD_DELIVERY", "SALE_DELIVERY", "RETURNED", "SALESMAN_NEGATIVE_ADJUSTMENT"}:
                salesman_balances[pid][s_user] = salesman_balances[pid].get(s_user, 0) - qty

    # 3. Total sold count per product from SaleItems
    sold_counts: Dict[str, int] = {}
    if sale_items_records:
        for item in sale_items_records:
            pid = str(item.get("product_id", "")).strip()
            if not pid:
                continue
            try:
                sqty = int(float(item.get("quantity", 0) or 0))
            except (TypeError, ValueError):
                sqty = 0
            sold_counts[pid] = sold_counts.get(pid, 0) + sqty

    # 4. Build complete register for every packet SKU
    register = []
    total_factory_packets = 0
    total_warehouse_packets = 0
    total_salesmen_packets = 0
    total_on_hand_packets = 0

    # Ensure all products are considered
    for prod in products_master:
        pid = str(prod.get("product_id", "")).strip()
        if not pid:
            continue

        p_name = str(prod.get("product_name", "")).strip()
        sku = str(prod.get("sku", pid)).strip()
        category = str(prod.get("category", "Papad")).strip()
        variant = str(prod.get("variant", "")).strip()
        try:
            pack_weight = int(float(prod.get("pack_weight_g", 0) or 0))
        except (TypeError, ValueError):
            pack_weight = 0
        selling_unit = str(prod.get("selling_unit", "PACKET")).strip()
        is_active = _is_truthy(prod.get("active", "true"))

        # Skip products that are explicitly raw materials or non-packet unless they have stock
        has_stock_record = (
            pid in factory_packaged
            or pid in factory_dispatches
            or pid in warehouse_balances
            or pid in salesman_balances
        )
        if not is_active and not has_stock_record:
            continue

        # Calculations for this SKU
        pk_packaged = factory_packaged.get(pid, 0)
        pk_returned = factory_returns.get(pid, 0)
        pk_adj = factory_adjustments.get(pid, 0)
        pk_dispatched = factory_dispatches.get(pid, 0)
        factory_stock = pk_packaged + pk_returned + pk_adj - pk_dispatched

        warehouse_stock = warehouse_balances.get(pid, 0)

        s_map = salesman_balances.get(pid, {})
        salesmen_stock = sum(s_map.values())
        salesmen_details = [
            {"salesman_id": sid, "salesman_name": users_map.get(sid, sid), "quantity": sqty}
            for sid, sqty in s_map.items()
            if sqty != 0
        ]

        chan_map = channel_dispatches.get(pid, {})
        dispatched_warehouse = chan_map.get("WAREHOUSE", 0)
        dispatched_salesman = chan_map.get("SALESMAN", 0)
        dispatched_ecommerce = chan_map.get("ECOMMERCE", 0)
        dispatched_retail = chan_map.get("RETAIL", 0)
        dispatched_wholesale = chan_map.get("WHOLESALE", 0)
        dispatched_distributor = chan_map.get("DISTRIBUTOR", 0)

        # Internal on-hand: Factory + Warehouse + Salesmen
        # Every internal packet is counted exactly once across its physical custody
        total_internal_on_hand = factory_stock + warehouse_stock + salesmen_stock
        available_to_sell = max(0, total_internal_on_hand)

        total_sold = sold_counts.get(pid, 0)

        # Status
        has_negative = factory_stock < 0 or warehouse_stock < 0 or any(q < 0 for q in s_map.values())
        if has_negative:
            status = "DISCREPANCY_NEGATIVE"
        elif total_internal_on_hand == 0:
            status = "ZERO_STOCK"
        else:
            status = "BALANCED"

        total_factory_packets += factory_stock
        total_warehouse_packets += warehouse_stock
        total_salesmen_packets += salesmen_stock
        total_on_hand_packets += total_internal_on_hand

        register.append({
            "product_id": pid,
            "sku": sku,
            "product_name": p_name,
            "category": category,
            "variant": variant,
            "pack_weight_g": pack_weight,
            "selling_unit": selling_unit,
            "active": is_active,
            "packets_packaged": pk_packaged,
            "packets_returned": pk_returned,
            "factory_adjustments": pk_adj,
            "factory_dispatches": pk_dispatched,
            "dispatched_warehouse": dispatched_warehouse,
            "dispatched_salesman": dispatched_salesman,
            "dispatched_ecommerce": dispatched_ecommerce,
            "dispatched_retail": dispatched_retail,
            "dispatched_wholesale": dispatched_wholesale,
            "dispatched_distributor": dispatched_distributor,
            "factory_stock": factory_stock,
            "warehouse_stock": warehouse_stock,
            "salesmen_stock": salesmen_stock,
            "salesmen_breakdown": salesmen_details,
            "total_internal_on_hand": total_internal_on_hand,
            "available_to_sell": available_to_sell,
            "total_sold": total_sold,
            "last_movement_datetime": last_movements.get(pid, ""),
            "status": status,
        })

    # Sort alphabetically by product_name then pack_weight_g
    register.sort(key=lambda x: (x["product_name"].lower(), x["pack_weight_g"]))

    return {
        "summary": {
            "total_skus_count": len(register),
            "total_factory_packets": total_factory_packets,
            "total_warehouse_packets": total_warehouse_packets,
            "total_salesmen_packets": total_salesmen_packets,
            "total_on_hand_packets": total_on_hand_packets,
            "active_skus_with_stock": sum(1 for r in register if r["total_internal_on_hand"] > 0),
            "zero_stock_skus": sum(1 for r in register if r["total_internal_on_hand"] == 0),
            "discrepancy_skus": sum(1 for r in register if r["status"] == "DISCREPANCY_NEGATIVE"),
        },
        "register": register,
    }
