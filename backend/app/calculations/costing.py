"""
Authoritative Costing Engine
Implements Part 2 and Part 6 of the specification.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from .units import (
    normalize_to_canonical_unit,
    round_money,
    to_decimal,
)


def get_latest_purchase_rate(
    material_name_or_id: str,
    raw_materials_master: List[Dict[str, Any]],
    purchase_ledger: Optional[List[Dict[str, Any]]] = None,
    as_of_datetime: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Determine the latest valid purchase rate for a raw material.
    Rules:
    - Exclude cancelled/invalid purchases.
    - Exclude future-dated purchases if as_of_datetime is provided.
    - Convert purchase unit to canonical stock unit (kg/L).
    - If no purchase rate exists, check RawMaterials master.
    - If still missing, return status 'MISSING_RATE' and do NOT silently return 0.
    """
    clean_target = str(material_name_or_id or "").strip().lower()
    if not clean_target:
        return {"status": "MISSING_RATE", "rate_per_canonical_unit": None, "source": "NONE"}

    # 1. Search purchase ledger first (most authoritative)
    if purchase_ledger:
        candidates = []
        for entry in purchase_ledger:
            # Match material
            m_name = str(entry.get("material_name", "")).strip().lower()
            m_id = str(entry.get("raw_material_id", "")).strip().lower()
            if m_name != clean_target and m_id != clean_target:
                continue

            # Check status
            status = str(entry.get("status", "VALID")).upper()
            if status in {"CANCELLED", "VOID", "INVALID", "REJECTED"}:
                continue

            # Check date
            entry_dt = str(entry.get("txn_datetime") or entry.get("created_at") or "")
            if as_of_datetime and entry_dt > as_of_datetime:
                continue

            rate = entry.get("rate_per_unit") or entry.get("rate")
            if rate is not None and str(rate).strip() not in {"", "0", "null", "none"}:
                try:
                    rate_val = float(rate)
                    if rate_val > 0:
                        unit = str(entry.get("unit", "kg")).strip()
                        candidates.append((entry_dt, rate_val, unit, str(entry.get("raw_material_txn_id") or "LEDGER")))
                except ValueError:
                    pass

        if candidates:
            # Pick latest
            candidates.sort(key=lambda x: x[0], reverse=True)
            latest = candidates[0]
            dt, rate_val, unit, ref = latest
            # Rate is per 'unit'. If unit was gram, convert to per kg: rate_per_kg = rate_per_g * 1000
            u = unit.lower()
            if u in {"g", "gram", "grams"}:
                canonical_rate = round_money(rate_val * 1000)
            elif u in {"ml", "milliliter"}:
                canonical_rate = round_money(rate_val * 1000)
            else:
                canonical_rate = round_money(rate_val)

            return {
                "status": "CONFIRMED",
                "rate_per_canonical_unit": canonical_rate,
                "source": f"PURCHASE_LEDGER:{ref}",
                "as_of": dt,
            }

    # 2. Fall back to RawMaterials master record
    for rm in raw_materials_master:
        m_name = str(rm.get("material_name", "")).strip().lower()
        m_id = str(rm.get("raw_material_id", "")).strip().lower()
        if m_name == clean_target or m_id == clean_target:
            rate = rm.get("rate_per_unit")
            rate_status = str(rm.get("rate_status", "CONFIRMED")).upper()
            if rate is not None and str(rate).strip() not in {"", "pending", "none", "null", "rate to confirm"} and rate_status != "PENDING":
                try:
                    rate_val = float(rate)
                    if rate_val > 0:
                        unit = str(rm.get("unit", "kg")).strip().lower()
                        if unit in {"g", "gram", "grams"}:
                            canonical_rate = round_money(rate_val * 1000)
                        elif unit in {"ml", "milliliter"}:
                            canonical_rate = round_money(rate_val * 1000)
                        else:
                            canonical_rate = round_money(rate_val)

                        return {
                            "status": "CONFIRMED",
                            "rate_per_canonical_unit": canonical_rate,
                            "source": f"MASTER:{rm.get('raw_material_id', '')}",
                            "as_of": "CURRENT",
                        }
                except ValueError:
                    pass

    return {
        "status": "MISSING_RATE",
        "rate_per_canonical_unit": None,
        "source": "UNAVAILABLE",
    }


def calculate_batch_actual_cost(
    materials_issued: List[Dict[str, Any]],
    actual_saleable_output_kg: float,
    labour_cost: float = 0.0,
    electricity_cost: float = 0.0,
    factory_overhead: float = 0.0,
    other_production_costs: float = 0.0,
) -> Dict[str, Any]:
    """
    Calculate actual production batch cost from issued materials and recorded expenses.
    """
    total_ingredient_cost = Decimal("0")
    has_missing_rates = False
    missing_rate_materials = []
    line_breakdown = []

    for mat in materials_issued:
        name = str(mat.get("material_name", "")).strip()
        qty = mat.get("quantity", 0) or 0
        qty_dec = to_decimal(qty)
        unit = str(mat.get("unit", "kg")).strip()

        std_qty, std_unit = normalize_to_canonical_unit(qty_dec, unit)
        std_qty_dec = to_decimal(std_qty)

        rate = mat.get("rate_per_unit") or mat.get("applicable_unit_rate")
        if rate is None or str(rate).strip() in {"", "none", "null", "pending"}:
            has_missing_rates = True
            missing_rate_materials.append(name)
            line_breakdown.append({
                "material_name": name,
                "quantity": float(qty_dec),
                "unit": unit,
                "rate": None,
                "cost": None,
                "status": "MISSING_RATE",
            })
        else:
            try:
                rate_dec = to_decimal(rate)
                line_cost_dec = std_qty_dec * rate_dec
                total_ingredient_cost += line_cost_dec
                line_breakdown.append({
                    "material_name": name,
                    "quantity": float(qty_dec),
                    "unit": unit,
                    "rate": round_money(rate_dec),
                    "cost": round_money(line_cost_dec),
                    "status": "CONFIRMED",
                })
            except (ValueError, TypeError):
                has_missing_rates = True
                missing_rate_materials.append(name)

    labour_dec = to_decimal(labour_cost)
    elec_dec = to_decimal(electricity_cost)
    overhead_dec = to_decimal(factory_overhead)
    other_dec = to_decimal(other_production_costs)

    non_material_costs = labour_dec + elec_dec + overhead_dec + other_dec
    total_production_cost = total_ingredient_cost + non_material_costs

    cost_per_kg = None
    if actual_saleable_output_kg > 0:
        saleable_dec = to_decimal(actual_saleable_output_kg)
        if not has_missing_rates:
            cost_per_kg = round_money(total_production_cost / saleable_dec)

    return {
        "status": "COMPLETE" if not has_missing_rates else "PENDING_RATES",
        "total_ingredient_cost": round_money(total_ingredient_cost) if not has_missing_rates else None,
        "labour_cost": round_money(labour_dec),
        "electricity_cost": round_money(elec_dec),
        "factory_overhead": round_money(overhead_dec),
        "other_production_costs": round_money(other_dec),
        "total_production_cost": round_money(total_production_cost) if not has_missing_rates else None,
        "saleable_output_kg": actual_saleable_output_kg,
        "cost_per_saleable_kg": cost_per_kg,
        "has_missing_rates": has_missing_rates,
        "missing_rate_materials": missing_rate_materials,
        "materials_breakdown": line_breakdown,
    }


def calculate_finished_sku_cost(
    pack_weight_grams: int,
    production_cost_per_saleable_kg: float,
    packaging_material_cost_per_packet: float = 0.0,
    packing_labour_per_packet: float = 0.0,
    other_packing_per_packet: float = 0.0,
) -> Dict[str, Any]:
    """
    Calculate finished packet cost for a given SKU:
    finished_packet_cost = (packet_net_weight_kg * cost_per_kg) + packing_costs
    """
    if production_cost_per_saleable_kg is None or production_cost_per_saleable_kg <= 0:
        return {
            "status": "PENDING_BASE_COST",
            "pack_weight_grams": pack_weight_grams,
            "finished_packet_cost": None,
        }

    weight_kg_dec = to_decimal(pack_weight_grams) / Decimal("1000")
    cost_per_kg_dec = to_decimal(production_cost_per_saleable_kg)

    base_papad_cost_dec = weight_kg_dec * cost_per_kg_dec
    packing_addon_dec = (
        to_decimal(packaging_material_cost_per_packet)
        + to_decimal(packing_labour_per_packet)
        + to_decimal(other_packing_per_packet)
    )

    total_packet_cost_dec = base_papad_cost_dec + packing_addon_dec

    return {
        "status": "COMPLETE",
        "pack_weight_grams": pack_weight_grams,
        "pack_weight_kg": float(weight_kg_dec),
        "base_papad_cost": round_money(base_papad_cost_dec),
        "packaging_material_cost": round_money(packaging_material_cost_per_packet),
        "packing_labour_cost": round_money(packing_labour_per_packet),
        "total_packing_cost": round_money(packing_addon_dec),
        "finished_packet_cost": round_money(total_packet_cost_dec),
    }


def get_sku_packing_costs(
    product_record: Optional[Dict[str, Any]],
    raw_materials_master: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Decimal, Decimal]:
    """
    Determine packing material and packing labour costs for a specific product SKU.
    Rules:
    - Never silently invent or assume fixed ₹1.50 or ₹0.50 fallback costs.
    - Inspects product_record configuration (packaging_material_cost_per_packet, packing_labour_per_packet).
    - If not explicitly set on SKU, checks RawMaterialsMaster for matching pouch rate.
    - If no cost is defined in master data, returns Decimal('0.00') rather than a fictional value.
    """
    if not product_record:
        return Decimal("0.00"), Decimal("0.00")

    mat_cost = Decimal("0.00")
    lab_cost = Decimal("0.00")

    # 1. Check SKU product fields
    for field_name in ["packaging_material_cost_per_packet", "pouch_cost", "packaging_material_cost"]:
        val = product_record.get(field_name)
        if val is not None and str(val).strip() not in {"", "none", "null"}:
            try:
                dec = to_decimal(val)
                if dec >= 0:
                    mat_cost = dec
                    break
            except Exception:
                pass

    for field_name in ["packing_labour_per_packet", "packing_labor_per_packet", "packing_labour_cost", "packaging_labor_cost"]:
        val = product_record.get(field_name)
        if val is not None and str(val).strip() not in {"", "none", "null"}:
            try:
                dec = to_decimal(val)
                if dec >= 0:
                    lab_cost = dec
                    break
            except Exception:
                pass

    # 2. Check RawMaterialsMaster if pouch cost was not set on the product
    if mat_cost == Decimal("0.00") and raw_materials_master:
        pack_weight = int(float(product_record.get("pack_weight_g", 0) or 0))
        for rm in raw_materials_master:
            name = str(rm.get("material_name", "")).lower()
            if "pouch" in name or "printed bag" in name or "packaging" in name:
                if str(pack_weight) in name:
                    r = rm.get("rate_per_unit") or rm.get("rate")
                    if r is not None and str(r).strip() not in {"", "none", "null", "pending"}:
                        try:
                            mat_cost = to_decimal(r)
                            break
                        except Exception:
                            pass

    return round_money(mat_cost), round_money(lab_cost)


def get_authoritative_bulk_cost_per_kg(
    bulk_key_or_product_id: str,
    production_batches: Optional[List[Dict[str, Any]]] = None,
    recipes: Optional[List[Dict[str, Any]]] = None,
    production_stock_ledger: Optional[List[Dict[str, Any]]] = None,
    raw_materials_master: Optional[List[Dict[str, Any]]] = None,
) -> Decimal:
    """
    Authoritative resolution of bulk papad unit cost per kg.
    Follows established inventory valuation hierarchy:
    1. Checks approved ProductionBatches for this product with actual_cost_per_kg > 0.
       Uses latest approved batch actual cost or batch weighted average.
    2. Checks ProductionStockLedger BULK_PRODUCED entries with unit_cost_per_kg > 0.
    3. Checks approved Recipes for this product and evaluates standard formula cost
       via calculate_recipe_cost_estimate.
    4. If no authoritative cost can be established, raises ValueError.
       NEVER falls back to a silent arbitrary hardcoded constant (such as ₹160/kg).
    """
    from .recipes import calculate_recipe_cost_estimate

    target = str(bulk_key_or_product_id or "").strip().lower()
    if not target:
        raise ValueError("Cannot resolve bulk cost for empty product key")

    # 1. Search approved ProductionBatches
    if production_batches:
        matching_batches = []
        for b in production_batches:
            st = str(b.get("status", "")).strip().upper()
            if st != "APPROVED":
                continue
            b_name = str(b.get("product_name_snapshot", "")).strip().lower()
            b_pid = str(b.get("product_id", "")).strip().lower()
            b_key = str(b.get("bulk_product_key", "")).strip().lower()
            if target == b_name or target == b_pid or target == b_key or (len(target) >= 4 and target in b_name):
                cost_val = b.get("actual_cost_per_kg") or b.get("cost_per_kg")
                if cost_val is not None and str(cost_val).strip() not in {"", "0", "null", "none"}:
                    try:
                        dec = to_decimal(cost_val)
                        if dec > Decimal("0"):
                            dt = str(b.get("approved_at") or b.get("production_date") or b.get("created_at") or "")
                            matching_batches.append((dt, dec))
                    except Exception:
                        pass

        if matching_batches:
            # Sort by datetime descending to get the most recent batch cost
            matching_batches.sort(key=lambda x: x[0], reverse=True)
            return round_money(matching_batches[0][1])

    # 2. Search ProductionStockLedger
    if production_stock_ledger:
        for m in reversed(production_stock_ledger):
            typ = str(m.get("movement_type", "")).strip().upper()
            if typ != "BULK_PRODUCED":
                continue
            m_key = str(m.get("bulk_product_key") or m.get("product_name_snapshot") or m.get("product_id") or "").strip().lower()
            if target == m_key or (len(target) >= 4 and target in m_key):
                unit_cost = m.get("unit_cost_per_kg") or m.get("unit_cost")
                if unit_cost is not None and str(unit_cost).strip() not in {"", "0", "null", "none"}:
                    try:
                        dec = to_decimal(unit_cost)
                        if dec > Decimal("0"):
                            return round_money(dec)
                    except Exception:
                        pass

    # 3. Search approved Recipes
    if recipes:
        import json
        for r in recipes:
            r_name = str(r.get("product_name_snapshot") or r.get("product_name") or "").strip().lower()
            r_pid = str(r.get("product_id", "")).strip().lower()
            is_approved = str(r.get("approved", "")).strip().lower() in {"true", "1", "yes"}
            if not is_approved:
                continue
            if target == r_name or target == r_pid or (len(target) >= 4 and target in r_name):
                # Calculate recipe formula cost
                items_raw = r.get("items") or r.get("items_json")
                if isinstance(items_raw, str):
                    try:
                        items_raw = json.loads(items_raw)
                    except Exception:
                        items_raw = []
                if items_raw:
                    expected_yield = float(r.get("expected_yield_kg", 1.2) or 1.2)
                    recipe_cost = calculate_recipe_cost_estimate(items_raw, expected_yield)
                    if recipe_cost.get("cost_per_kg") is not None:
                        dec = to_decimal(recipe_cost["cost_per_kg"])
                        if dec > Decimal("0"):
                            return round_money(dec)

    raise ValueError(
        f"Authoritative bulk cost cannot be established for '{bulk_key_or_product_id}'. "
        "No approved batch actual cost or formula recipe cost is available. "
        "System refuses to invent or assume an arbitrary fallback cost."
    )


def get_sku_finished_cost(
    product_record: Dict[str, Any],
    production_batches: Optional[List[Dict[str, Any]]] = None,
    recipes: Optional[List[Dict[str, Any]]] = None,
    production_stock_ledger: Optional[List[Dict[str, Any]]] = None,
    raw_materials_master: Optional[List[Dict[str, Any]]] = None,
) -> Decimal:
    """
    Calculate the authoritative finished packet cost for a given product SKU.
    Combines:
    - Net weight proportion of authoritative bulk papad cost
    - Direct packaging material cost for this SKU
    - Direct packaging labour cost for this SKU
    """
    # 1. Direct standard_cost or unit_cost on Product record
    for field_name in ["standard_cost", "finished_packet_cost", "unit_cost"]:
        val = product_record.get(field_name)
        if val is not None and str(val).strip() not in {"", "0", "null", "none"}:
            try:
                dec = to_decimal(val)
                if dec > Decimal("0"):
                    return round_money(dec)
            except Exception:
                pass

    # 2. Derive dynamically from authoritative bulk cost and packaging addons
    p_name = str(product_record.get("product_name", "")).strip()
    p_id = str(product_record.get("product_id", "")).strip()
    pack_g = int(float(product_record.get("pack_weight_g", 500) or 500))

    bulk_cost_per_kg = get_authoritative_bulk_cost_per_kg(
        bulk_key_or_product_id=p_name or p_id,
        production_batches=production_batches,
        recipes=recipes,
        production_stock_ledger=production_stock_ledger,
        raw_materials_master=raw_materials_master,
    )

    mat_cost, lab_cost = get_sku_packing_costs(product_record, raw_materials_master)
    sku_val = calculate_finished_sku_cost(
        pack_weight_grams=pack_g,
        production_cost_per_saleable_kg=float(bulk_cost_per_kg),
        packaging_material_cost_per_packet=float(mat_cost),
        packing_labour_per_packet=float(lab_cost),
    )

    if sku_val.get("finished_packet_cost") is not None:
        return to_decimal(sku_val["finished_packet_cost"])

    raise ValueError(f"Could not calculate finished SKU cost for product {p_id}")

