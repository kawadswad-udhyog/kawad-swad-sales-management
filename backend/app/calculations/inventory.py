"""
Authoritative Inventory Engine
Implements Part 2 and Part 7 of the specification.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from .units import (
    round_stock,
    round_money,
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


def calculate_batch_bulk_balances(
    ledger_records: List[Dict[str, Any]],
    production_batches: List[Dict[str, Any]],
    bulk_key_or_product_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Calculate unpackaged bulk stock balance independently for every approved production batch.
    Follows Phase 1 multi-batch inventory rules:
    - Maintains batch-level inventory balances.
    - Tracks produced vs packaged kg per batch.
    - Accurately associates actual_cost_per_kg with each batch.
    - Prevents negative inventory.
    """
    clean_target = str(bulk_key_or_product_id or "").strip().lower()

    # 1. Filter approved batches matching product if target provided
    approved_batches = []
    for b in production_batches:
        st = str(b.get("status", "")).strip().upper()
        if st != "APPROVED":
            continue
        b_pid = str(b.get("product_id", "")).strip().lower()
        b_name = str(b.get("product_name_snapshot", "")).strip().lower()
        b_key = str(b.get("bulk_product_key", "")).strip().lower()

        if clean_target:
            if (
                clean_target != b_pid
                and clean_target != b_name
                and clean_target != b_key
                and not (len(clean_target) >= 4 and clean_target in b_name)
            ):
                continue
        approved_batches.append(b)

    # Also discover any ledger-recorded BULK_PRODUCED movements not in ProductionBatches
    seen_batch_ids = {str(b.get("production_id") or b.get("batch_id") or "").strip() for b in approved_batches}
    for m in ledger_records:
        typ = str(m.get("movement_type", "")).strip().upper()
        if typ != "BULK_PRODUCED":
            continue
        m_pid = str(m.get("product_id", "")).strip().lower()
        m_name = str(m.get("product_name_snapshot", "")).strip().lower()
        m_key = str(m.get("bulk_product_key", "")).strip().lower()

        if clean_target:
            if (
                clean_target != m_pid
                and clean_target != m_name
                and clean_target != m_key
                and not (len(clean_target) >= 4 and clean_target in m_name)
            ):
                continue

        ref_id = str(m.get("reference_id", "")).strip() or str(m.get("movement_id", "")).strip()
        if ref_id not in seen_batch_ids:
            seen_batch_ids.add(ref_id)
            unit_cost = m.get("unit_cost_per_kg") or m.get("unit_cost")
            approved_batches.append({
                "production_id": ref_id,
                "batch_id": ref_id,
                "production_date": str(m.get("txn_datetime", "") or "")[:10],
                "product_id": m.get("product_id"),
                "product_name_snapshot": m.get("product_name_snapshot") or m.get("bulk_product_key"),
                "net_quantity_kg": m.get("quantity_kg", 0),
                "actual_cost_per_kg": unit_cost,
                "status": "APPROVED",
            })

    # Sort batches chronologically (FIFO order)
    def batch_sort_key(batch):
        dt = str(batch.get("production_date") or batch.get("approved_at") or batch.get("created_at") or "")
        bid = str(batch.get("production_id") or batch.get("batch_id") or "")
        return (dt, bid)

    approved_batches.sort(key=batch_sort_key)

    # 2. Sum produced and consumed kg per batch
    batch_balances = []
    for b in approved_batches:
        b_id = str(b.get("production_id") or b.get("batch_id") or "").strip()
        b_date = str(b.get("production_date") or b.get("created_at") or "")[:10]
        cost_val = b.get("actual_cost_per_kg") or b.get("cost_per_kg")
        b_actual = (
            to_decimal(cost_val)
            if cost_val is not None and str(cost_val).strip() not in {"", "0", "null", "none"}
            else Decimal("0")
        )

        # Baseline produced kg from batch record
        b_produced = to_decimal(
            b.get("net_quantity_kg") or b.get("saleable_output_kg") or b.get("quantity_kg") or 0
        )

        # Reconcile against ProductionStockLedger BULK_PRODUCED
        ledger_produced = Decimal("0")
        for m in ledger_records:
            typ = str(m.get("movement_type", "")).strip().upper()
            ref_id = str(m.get("reference_id", "")).strip()
            if typ == "BULK_PRODUCED" and ref_id == b_id:
                ledger_produced += to_decimal(m.get("quantity_kg", 0) or 0)

        if ledger_produced > Decimal("0"):
            b_produced = ledger_produced

        # Calculate consumed kg for this specific batch from BULK_PACKAGED movements
        b_consumed = Decimal("0")
        for m in ledger_records:
            typ = str(m.get("movement_type", "")).strip().upper()
            if typ != "BULK_PACKAGED":
                continue
            batch_ref = str(m.get("production_batch_id", "")).strip()
            m_notes = str(m.get("notes", ""))
            m_ref = str(m.get("reference_id", "")).strip()

            if (
                batch_ref == b_id
                or f"batch {b_id}" in m_notes.lower()
                or f"batch: {b_id}" in m_notes.lower()
                or m_ref == b_id
            ):
                b_consumed += to_decimal(m.get("quantity_kg", 0) or 0)

        available_kg = max(Decimal("0"), b_produced - b_consumed)

        # Distinguish ACTUAL, ESTIMATED, and MISSING cost statuses
        raw_status = str(b.get("cost_status", "")).strip().upper()
        cost_source = str(b.get("cost_source", "")).strip()
        cost_notes = str(b.get("cost_notes", "")).strip()
        cost_date = str(b.get("cost_estimated_at") or b.get("cost_resolved_at") or b_date)[:10]

        if b_actual > Decimal("0") and raw_status != "ESTIMATED":
            cost_status = "ACTUAL"
            cost_source = cost_source or "PRODUCTION_BATCH"
            cost_notes = cost_notes or "Verified actual production batch cost"
            unit_cost = b_actual
        else:
            # Check for owner-approved or recorded estimated rate
            est_val = b.get("estimated_cost_per_kg") or b.get("estimated_cost")
            if est_val is not None and str(est_val).strip() not in {"", "0", "null", "none"}:
                try:
                    dec_est = to_decimal(est_val)
                    if dec_est > Decimal("0"):
                        cost_status = "ESTIMATED"
                        cost_source = cost_source or "OWNER_ESTIMATE"
                        cost_notes = cost_notes or "Owner-approved estimated rate"
                        unit_cost = dec_est
                    else:
                        cost_status = "MISSING"
                        cost_source = "NONE"
                        cost_notes = "Missing actual cost - requires Owner resolution"
                        unit_cost = Decimal("0")
                except Exception:
                    cost_status = "MISSING"
                    cost_source = "NONE"
                    cost_notes = "Missing actual cost - requires Owner resolution"
                    unit_cost = Decimal("0")
            elif b_actual > Decimal("0") and raw_status == "ESTIMATED":
                cost_status = "ESTIMATED"
                cost_source = cost_source or "ESTIMATED_RATE"
                cost_notes = cost_notes or "Recorded estimated rate"
                unit_cost = b_actual
            else:
                cost_status = "MISSING"
                cost_source = "NONE"
                cost_notes = "Missing actual cost - requires Owner resolution"
                unit_cost = Decimal("0")

        batch_balances.append({
            "batch_id": b_id,
            "production_date": b_date,
            "product_id": str(b.get("product_id", "")),
            "product_name": str(b.get("product_name_snapshot", "")),
            "produced_kg": float(round_stock(b_produced)),
            "consumed_kg": float(round_stock(b_consumed)),
            "available_kg": float(round_stock(available_kg)),
            "actual_cost_per_kg": float(round_money(b_actual if cost_status == "ACTUAL" else Decimal("0"))),
            "unit_cost": float(round_money(unit_cost)),
            "cost_status": cost_status,
            "cost_source": cost_source,
            "cost_date": cost_date,
            "cost_notes": cost_notes,
            "remaining_value": float(round_money(available_kg * unit_cost)),
        })

    return batch_balances


def resolve_packaging_batch_allocations(
    bulk_kg_required: float,
    product_id_or_name: str,
    ledger_records: List[Dict[str, Any]],
    production_batches: List[Dict[str, Any]],
    batch_allocations_requested: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Resolve and validate batch allocations for a packaging operation.
    Enforces Phase 1 requirements:
    1. Multi-batch allocation in one packaging operation.
    2. Per-batch inventory availability validation (prevent negative inventory).
    3. Consumed cost calculation using each batch's actual cost.
    4. Deterministic FIFO auto-allocation if allocations are omitted.
    5. Rejection of unconfirmed/missing batch costs.
    """
    req_kg = to_decimal(bulk_kg_required)
    if req_kg <= Decimal("0"):
        raise ValueError(f"Required bulk kg must be positive, got {bulk_kg_required}")

    balances = calculate_batch_bulk_balances(
        ledger_records=ledger_records,
        production_batches=production_batches,
        bulk_key_or_product_id=product_id_or_name,
    )
    balance_map = {b["batch_id"]: b for b in balances}

    resolved = []
    total_cost = Decimal("0")

    if batch_allocations_requested and len(batch_allocations_requested) > 0:
        alloc_sum = Decimal("0")
        for item in batch_allocations_requested:
            bid = str(item.get("batch_id", "")).strip()
            qty = to_decimal(item.get("quantity_kg", 0) or 0)
            if not bid:
                raise ValueError("Batch allocation item must include a valid batch_id")
            if qty <= Decimal("0"):
                raise ValueError(f"Allocated quantity for batch {bid} must be positive, got {qty}")

            if bid not in balance_map:
                raise ValueError(f"Batch '{bid}' not found or not approved for product '{product_id_or_name}'")

            batch_info = balance_map[bid]
            avail = to_decimal(batch_info["available_kg"])
            if qty > (avail + Decimal("0.005")):
                raise ValueError(
                    f"Insufficient unpackaged bulk stock in batch {bid}. "
                    f"Available: {float(avail):.3f} kg; Requested: {float(qty):.3f} kg."
                )

            cost_status = batch_info.get("cost_status", "ACTUAL")
            cost_source = batch_info.get("cost_source", "PRODUCTION_BATCH")
            cost_date = batch_info.get("cost_date", "")
            unit_cost = to_decimal(batch_info.get("unit_cost", 0) or batch_info.get("actual_cost_per_kg", 0))

            if cost_status == "MISSING" or unit_cost <= Decimal("0"):
                raise ValueError(
                    f"Production batch '{bid}' does not have an approved actual cost per kg. "
                    "Cannot package bulk stock with missing or unconfirmed cost."
                )

            line_cost = qty * unit_cost
            alloc_sum += qty
            total_cost += line_cost

            resolved.append({
                "batch_id": bid,
                "quantity_kg": float(round_stock(qty)),
                "unit_cost_per_kg": float(round_money(unit_cost)),
                "total_cost": float(round_money(line_cost)),
                "cost_status": cost_status,
                "cost_source": cost_source,
                "cost_date": cost_date,
            })

        if abs(alloc_sum - req_kg) > Decimal("0.005"):
            raise ValueError(
                f"Sum of batch allocations ({float(alloc_sum):.3f} kg) does not match total bulk kg used ({float(req_kg):.3f} kg)."
            )
    else:
        # Automatic FIFO allocation across available batches
        available_batches = [b for b in balances if to_decimal(b["available_kg"]) > Decimal("0.001")]
        total_available = sum((to_decimal(b["available_kg"]) for b in available_batches), Decimal("0"))
        if req_kg > (total_available + Decimal("0.005")):
            raise ValueError(
                f"Insufficient unpackaged bulk stock for '{product_id_or_name}'. "
                f"Available across all approved batches: {float(total_available):.3f} kg; Requested: {float(req_kg):.3f} kg."
            )

        needed = req_kg
        for b in available_batches:
            if needed <= Decimal("0"):
                break
            b_avail = to_decimal(b["available_kg"])
            take = min(needed, b_avail)
            cost_status = b.get("cost_status", "ACTUAL")
            cost_source = b.get("cost_source", "PRODUCTION_BATCH")
            cost_date = b.get("cost_date", "")
            unit_cost = to_decimal(b.get("unit_cost", 0) or b.get("actual_cost_per_kg", 0))

            if cost_status == "MISSING" or unit_cost <= Decimal("0"):
                try:
                    from .costing import get_authoritative_bulk_cost_per_kg
                    unit_cost = get_authoritative_bulk_cost_per_kg(
                        bulk_key_or_product_id=product_id_or_name,
                        production_batches=production_batches,
                        production_stock_ledger=ledger_records,
                    )
                    cost_status = "ESTIMATED"
                    cost_source = "RECIPE_FORMULA_ESTIMATE"
                    from datetime import datetime, timezone
                    cost_date = datetime.now(timezone.utc).isoformat()[:10]
                except Exception:
                    unit_cost = Decimal("0")
                    cost_status = "MISSING"
                    cost_source = "NONE"

            line_cost = take * unit_cost
            total_cost += line_cost
            needed -= take

            resolved.append({
                "batch_id": b["batch_id"],
                "quantity_kg": float(round_stock(take)),
                "unit_cost_per_kg": float(round_money(unit_cost)),
                "total_cost": float(round_money(line_cost)),
                "cost_status": cost_status,
                "cost_source": cost_source,
                "cost_date": cost_date,
            })

        if needed > Decimal("0.005"):
            raise ValueError(
                f"Could not fulfill required bulk kg ({float(req_kg):.3f} kg) from available batches."
            )

    eff_cost_per_kg = (total_cost / req_kg) if req_kg > Decimal("0") else Decimal("0")
    has_estimated_cost = any(a.get("cost_status") == "ESTIMATED" for a in resolved)
    overall_cost_status = "ESTIMATED" if has_estimated_cost else "ACTUAL"

    return {
        "status": "ALLOCATED",
        "total_bulk_kg": float(round_stock(req_kg)),
        "total_bulk_cost": float(round_money(total_cost)),
        "effective_bulk_cost_per_kg": float(round_money(eff_cost_per_kg)),
        "cost_status": overall_cost_status,
        "has_estimated_cost": has_estimated_cost,
        "allocations": resolved,
    }


def calculate_finished_stock_balance(
    ledger_records: List[Dict[str, Any]],
    product_id: Optional[str] = None,
    packaging_batches: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    """
    Calculate factory finished packet balances from ProductionStockLedger:
    Finished stock = sum(PACKETS_PACKAGED) + sum(PACKET_RETURN) - sum(CHANNEL_DISPATCH) + adjustments

    Safety constraint:
    Excludes any packet movements from INCOMPLETE, PENDING_REVIEW, or FAILED packaging batches.
    """
    balances: Dict[str, int] = {}
    incomplete_pack_ids = set()
    if packaging_batches:
        for p in packaging_batches:
            p_id = str(p.get("packaging_id", "")).strip()
            p_st = str(p.get("status", "")).strip().upper()
            if p_st in {"INCOMPLETE", "PENDING_REVIEW", "REJECTED", "FAILED"}:
                incomplete_pack_ids.add(p_id)

    for row in ledger_records:
        typ = str(row.get("movement_type", "")).strip().upper()
        ref_id = str(row.get("reference_id", "")).strip()
        if ref_id in incomplete_pack_ids:
            continue

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

        if typ in {"PRODUCTION_CONSUMPTION", "ISSUE", "WASTAGE", "MILLING_CONSUMPTION", "MILLING_INPUT"}:
            consumed += qty
        elif typ in {"PURCHASE_RECEIPT", "STOCK_IN", "RETURN", "MILLING_OUTPUT", "MILLING_RECEIPT"}:
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
    packaging_batches: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Consolidated Finished Goods Stock Register.
    Calculates stock across all active packet SKUs and locations:
    Factory, Warehouse, Salesmen, Channels.
    Guarantees every active packet SKU is present (including 0 stock).
    Excludes incomplete packaging batches from usable factory stock.
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

    incomplete_pack_ids = set()
    if packaging_batches:
        for p in packaging_batches:
            p_id = str(p.get("packaging_id", "")).strip()
            p_st = str(p.get("status", "")).strip().upper()
            if p_st in {"INCOMPLETE", "PENDING_REVIEW", "REJECTED", "FAILED"}:
                incomplete_pack_ids.add(p_id)

    # 1. Factory finished stock ledger calculations per product_id
    factory_packaged: Dict[str, int] = {}
    factory_returns: Dict[str, int] = {}
    factory_adjustments: Dict[str, int] = {}
    factory_dispatches: Dict[str, int] = {}
    channel_dispatches: Dict[str, Dict[str, int]] = {}
    last_movements: Dict[str, str] = {}

    for row in production_stock_ledger:
        ref_id = str(row.get("reference_id", "")).strip()
        if ref_id in incomplete_pack_ids:
            continue

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
