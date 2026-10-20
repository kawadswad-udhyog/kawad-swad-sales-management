"""
Authoritative Costing Engine
Implements Part 2 and Part 6 of the specification.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
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
