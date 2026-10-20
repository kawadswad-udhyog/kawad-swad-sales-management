"""
Authoritative Recipe Engine: Scaling, Formulation Protection, and Validation
Implements Part 3 of the specification.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from .units import (
    normalize_to_canonical_unit,
    round_stock,
    round_money,
    round_ratio,
    to_decimal,
)

# Formulation rules: Forbidden ingredients for specific product recipes
FORBIDDEN_INGREDIENTS = {
    # Moong Master Papad must never contain sabudana or urad flour
    "MOONG_MASTER": ["sabudana", "urad", "urad flour", "sabudana flour", "sago"],
}


def validate_recipe_formulation(
    product_key_or_name: str,
    items: List[Dict[str, Any]],
    expected_yield_kg: float,
) -> None:
    """
    Validate that recipe formulation satisfies business rules:
    - Expected yield must be strictly positive
    - All ingredient quantities must be positive
    - Moong Master Papad must not contain sabudana or urad flour
    """
    if expected_yield_kg <= 0:
        raise ValueError(f"Expected recipe yield must be strictly positive, got {expected_yield_kg} kg")

    if not items or len(items) == 0:
        raise ValueError("Recipe must contain at least one ingredient")

    prod_key = str(product_key_or_name or "").strip().upper()
    is_moong_master = "MOONG" in prod_key and "MASTER" in prod_key

    for item in items:
        name = str(item.get("material_name", "")).strip()
        if not name:
            raise ValueError("Ingredient material_name cannot be empty")

        raw_qty = float(item.get("quantity_per_kg") or item.get("quantity") or 0)
        if raw_qty <= 0:
            raise ValueError(f"Ingredient '{name}' quantity must be strictly greater than 0, got {raw_qty}")

        unit = str(item.get("unit", "")).strip()
        if not unit:
            raise ValueError(f"Ingredient '{name}' has missing unit")

        # Check formulation constraints
        if is_moong_master:
            name_lower = name.lower()
            for forbidden in FORBIDDEN_INGREDIENTS["MOONG_MASTER"]:
                if forbidden in name_lower:
                    raise ValueError(
                        f"Formulation violation: Moong Master Papad must not contain '{name}' ({forbidden})."
                    )


def scale_recipe(
    recipe_items: List[Dict[str, Any]],
    expected_yield_kg: float,
    planned_output_kg: float,
    reference_flour_base_kg: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Scale a recipe for a given planned finished output.
    Formula:
      batch_multiplier = planned_finished_output / expected_yield_kg
      required_ingredient_quantity = recipe_ingredient_quantity * batch_multiplier
    """
    if planned_output_kg <= 0:
        raise ValueError(f"Planned output must be strictly positive, got {planned_output_kg} kg")
    if expected_yield_kg <= 0:
        raise ValueError(f"Expected yield must be strictly positive, got {expected_yield_kg} kg")

    planned_dec = to_decimal(planned_output_kg)
    yield_dec = to_decimal(expected_yield_kg)
    multiplier_dec = planned_dec / yield_dec

    scaled_items = []
    total_ingredient_mass_kg = Decimal("0")

    for item in recipe_items:
        name = str(item.get("material_name", "")).strip()
        raw_qty_dec = to_decimal(item.get("quantity", 0))
        unit = str(item.get("unit", "g")).strip()

        # Scale quantity in original recipe unit
        scaled_raw_qty = raw_qty_dec * multiplier_dec

        # Also compute canonical stock unit quantity (kg / L)
        canonical_qty, canonical_unit = normalize_to_canonical_unit(scaled_raw_qty, unit)

        if canonical_unit == "kg":
            total_ingredient_mass_kg += to_decimal(canonical_qty)

        scaled_items.append({
            "material_name": name,
            "raw_material_id": item.get("raw_material_id") or item.get("ingredient_id", ""),
            "recipe_unit_quantity": round_stock(scaled_raw_qty),
            "recipe_unit": unit,
            "canonical_quantity": round_stock(canonical_qty),
            "canonical_unit": canonical_unit,
            "rate_per_unit": item.get("rate_per_unit"),
            "rate_status": item.get("rate_status", "CONFIRMED"),
        })

    # Calculated required flour base
    calculated_flour_base_kg = None
    if reference_flour_base_kg and reference_flour_base_kg > 0:
        flour_dec = to_decimal(reference_flour_base_kg)
        calculated_flour_base_kg = round_stock(flour_dec * multiplier_dec)

    return {
        "planned_output_kg": round_stock(planned_output_kg),
        "expected_yield_kg": round_stock(expected_yield_kg),
        "batch_multiplier": round_ratio(multiplier_dec),
        "calculated_flour_base_kg": calculated_flour_base_kg,
        "total_ingredient_mass_kg": round_stock(total_ingredient_mass_kg),
        "scaled_items": scaled_items,
    }


def calculate_recipe_cost_estimate(
    items: List[Dict[str, Any]],
    expected_yield_kg: float,
) -> Dict[str, Any]:
    """
    Compute standard recipe cost estimate.
    If any ingredient rate is missing or pending, returns status "PENDING_RATES"
    and does not present a false complete total.
    """
    total_batch_cost = Decimal("0")
    has_pending_rate = False
    pending_ingredients: List[str] = []
    enriched_items = []

    yield_dec = to_decimal(expected_yield_kg) if expected_yield_kg > 0 else Decimal("1")

    for item in items:
        name = str(item.get("material_name", "")).strip()
        raw_qty = item.get("quantity", 0) or 0
        raw_qty_dec = to_decimal(raw_qty)
        unit = str(item.get("unit", "g")).strip()
        rate = item.get("rate_per_unit")
        rate_status = str(item.get("rate_status", "CONFIRMED")).upper()

        std_qty, std_unit = normalize_to_canonical_unit(raw_qty_dec, unit)
        std_qty_dec = to_decimal(std_qty)

        # Check if rate is missing
        if (
            rate is None
            or str(rate).strip().lower() in ["", "pending", "none", "null", "rate to confirm"]
            or rate_status == "PENDING"
        ):
            has_pending_rate = True
            pending_ingredients.append(name)
            rate_val = None
            line_cost = None
            rate_status = "PENDING"
        else:
            try:
                rate_dec = to_decimal(rate)
                rate_val = round_money(rate_dec)
                line_cost_dec = std_qty_dec * rate_dec
                line_cost = round_money(line_cost_dec)
                total_batch_cost += line_cost_dec
                rate_status = "CONFIRMED"
            except (ValueError, TypeError):
                has_pending_rate = True
                pending_ingredients.append(name)
                rate_val = None
                line_cost = None
                rate_status = "PENDING"

        # Quantity required per 1 kg finished dry papad
        qty_per_kg = round_ratio(std_qty_dec / yield_dec) if yield_dec > 0 else 0.0

        enriched_items.append({
            "ingredient_id": item.get("ingredient_id", ""),
            "material_name": name,
            "quantity": float(raw_qty_dec),
            "unit": unit,
            "canonical_quantity": std_qty,
            "canonical_unit": std_unit,
            "rate_per_unit": rate_val,
            "rate_status": rate_status,
            "ingredient_cost": line_cost,
            "quantity_per_kg": qty_per_kg,
            "notes": item.get("notes", ""),
        })

    if has_pending_rate:
        cost_status = "PENDING_RATES"
        cost_per_batch = None
        cost_per_kg = None
    else:
        cost_status = "COMPLETE"
        cost_per_batch = round_money(total_batch_cost)
        cost_per_kg = round_money(total_batch_cost / yield_dec) if yield_dec > 0 else None

    return {
        "cost_status": cost_status,
        "cost_per_batch": cost_per_batch,
        "cost_per_kg": cost_per_kg,
        "has_pending_rate": has_pending_rate,
        "pending_ingredients": pending_ingredients,
        "enriched_items": enriched_items,
    }
