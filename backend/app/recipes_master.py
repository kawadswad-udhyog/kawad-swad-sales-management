"""
Kawad Swad Papad Formula Master - Version 2.0
Primary reference data model and formulas for Kawad Swad Udhyog.

Specifications:
- MOONG FAMILY: 8 variants (Moong Master confirmed at 1.2 kg yield, ₹153.63/batch, ₹128.03/kg)
- CHANA FAMILY: 5 variants (Flour ratio 750g Chana : 250g Urad, SMOS proposed)
- URAD FAMILY: 2 variants (Flour ratio 850g Urad : 150g Sabudana, SMOS proposed)
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

# Standard unit conversion helpers
def normalize_quantity_to_std_unit(qty: float, unit: str) -> Tuple[float, str]:
    """Convert grams to kg and ml to L for unified rate calculation."""
    u = unit.strip().lower()
    if u in ["g", "gram", "grams"]:
        return qty / 1000.0, "kg"
    if u in ["ml", "milliliter", "millilitres", "milliliters"]:
        return qty / 1000.0, "L"
    if u in ["kg", "kilogram", "kgs"]:
        return qty, "kg"
    if u in ["l", "liter", "litre", "liters", "litres"]:
        return qty, "L"
    return qty, unit

def calculate_recipe_cost(
    items: List[Dict[str, Any]], expected_yield_kg: float
) -> Dict[str, Any]:
    """
    Calculate:
    - Ingredient cost = quantity used * applicable ingredient rate (converted to consistent units).
    - Batch ingredient cost = sum of ingredient costs.
    - Ingredient cost per kg = batch ingredient cost / expected_yield_kg.
    - Missing rates: if any rate is missing or pending, mark cost_status="PENDING_RATES"
      and do not present a false final total.
    """
    total_batch_cost = 0.0
    has_pending_rate = False
    pending_ingredients: List[str] = []
    enriched_items = []

    for item in items:
        name = str(item.get("material_name", "")).strip()
        raw_qty = float(item.get("quantity", 0) or 0)
        unit = str(item.get("unit", "g")).strip()
        rate = item.get("rate_per_unit")
        rate_status = str(item.get("rate_status", "CONFIRMED")).upper()

        # Check if rate is pending or rate to confirm
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
                rate_val = float(rate)
                std_qty, std_unit = normalize_quantity_to_std_unit(raw_qty, unit)
                line_cost = round(std_qty * rate_val, 2)
                total_batch_cost += line_cost
                rate_status = "CONFIRMED"
            except (ValueError, TypeError):
                has_pending_rate = True
                pending_ingredients.append(name)
                rate_val = None
                line_cost = None
                rate_status = "PENDING"

        # Quantity required per 1 kg finished dry papad
        qty_per_kg = round(raw_qty / expected_yield_kg, 4) if expected_yield_kg > 0 else 0.0
        # Standard unit quantity per kg (e.g. kg of flour per kg of papad)
        std_qty_raw, _ = normalize_quantity_to_std_unit(raw_qty, unit)
        std_qty_per_kg = round(std_qty_raw / expected_yield_kg, 4) if expected_yield_kg > 0 else 0.0

        enriched_items.append({
            "ingredient_id": item.get("ingredient_id", ""),
            "material_name": name,
            "quantity": raw_qty,
            "unit": unit,
            "rate_per_unit": rate_val,
            "rate_status": rate_status,
            "ingredient_cost": line_cost,
            "quantity_per_kg": std_qty_per_kg,
            "raw_quantity_per_kg": qty_per_kg,
            "notes": item.get("notes", ""),
        })

    if has_pending_rate:
        cost_status = "PENDING_RATES"
        cost_per_batch = None
        cost_per_kg = None
    else:
        cost_status = "COMPLETE"
        cost_per_batch = round(total_batch_cost, 2)
        cost_per_kg = (
            round(total_batch_cost / expected_yield_kg, 2)
            if expected_yield_kg > 0
            else None
        )

    return {
        "items": enriched_items,
        "cost_status": cost_status,
        "cost_per_batch": cost_per_batch,
        "cost_per_kg": cost_per_kg,
        "pending_ingredients": pending_ingredients,
        "expected_yield_kg": expected_yield_kg,
    }


# Standard ingredient unit rates recorded in Version 2.0 master
STANDARD_RATES = {
    "Moong Dal Flour": 120.0,       # ₹ / kg
    "Chana Dal Flour": 85.0,        # ₹ / kg
    "Urad Dal Flour": 130.0,        # ₹ / kg
    "Sabudana Flour": 90.0,         # ₹ / kg
    "Black Pepper": 700.0,          # ₹ / kg
    "Hing": 2500.0,                 # ₹ / kg
    "Salt": 20.0,                   # ₹ / kg
    "SMOS": 1500.0,                 # ₹ / kg
    "Papad Khar": 150.0,            # ₹ / kg
    "Edible Oil": 142.0,            # ₹ / L
    "Garlic Paste / Powder": 160.0, # ₹ / kg
    "Cumin Seeds (Jeera)": 320.0,   # ₹ / kg
    "Pudhina Powder": 250.0,        # ₹ / kg
    "Green Chilli Powder": 280.0,   # ₹ / kg
    "Kasuri Methi": 300.0,          # ₹ / kg
    "Punjabi Masala Blend": 450.0,  # ₹ / kg
    "Amchur (Dry Mango)": 220.0,    # ₹ / kg
    "Tomato Powder": None,          # Rate to confirm (Pending)
    "Sweetener Blend": None,        # Rate to confirm (Pending)
    "Whole Moong Dal": 110.0,       # ₹ / kg
    "Whole Urad Dal": 120.0,        # ₹ / kg
    "Whole Chana Dal": 75.0,        # ₹ / kg
}

# The 15 Version 2.0 Master Recipes
MASTER_RECIPES_DEFINITION: List[Dict[str, Any]] = [
    # -------------------------------------------------------------
    # MOONG FAMILY (8 VARIANTS)
    # -------------------------------------------------------------
    {
        "recipe_id": "RCP-MOONG-MASTER-V2",
        "product_id": "PRD-MOONG-MASTER",
        "product_name_snapshot": "Moong Master Papad",
        "product_family": "MOONG",
        "variant_name": "Master",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "APPROVED",
        "approved": True,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "OWNER",
        "change_notes": "Official Version 2.0 confirmed formula. Pure Moong base, strictly no sabudana flour, no urad flour.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED", "notes": "Primary flour; 100% pure moong"},
            {"material_name": "Black Pepper", "quantity": 15, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED", "notes": "Coarse ground kali mirch"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED", "notes": "Compounded asafoetida"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED", "notes": "Food grade refined salt"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED", "notes": "Sodium metabisulfite shelf-life enhancer"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED", "notes": "Alkaline salt (sajji khar)"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED", "notes": "Refined vegetable oil for kneading"},
        ],
    },
    {
        "recipe_id": "RCP-MOONG-GARLIC-V2",
        "product_id": "PRD-MOONG-GARLIC",
        "product_name_snapshot": "Moong Garlic Papad",
        "product_family": "MOONG",
        "variant_name": "Garlic",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Moong base with garlic addition. Pending owner confirmation.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED"},
            {"material_name": "Garlic Paste / Powder", "quantity": 40, "unit": "g", "rate_per_unit": 160.0, "rate_status": "CONFIRMED"},
            {"material_name": "Black Pepper", "quantity": 15, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-MOONG-JEERA-V2",
        "product_id": "PRD-MOONG-JEERA",
        "product_name_snapshot": "Moong Jeera Papad",
        "product_family": "MOONG",
        "variant_name": "Jeera",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Moong base with whole jeera seeds.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED"},
            {"material_name": "Cumin Seeds (Jeera)", "quantity": 25, "unit": "g", "rate_per_unit": 320.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-MOONG-PUDHINA-V2",
        "product_id": "PRD-MOONG-PUDHINA",
        "product_name_snapshot": "Moong Pudhina Papad",
        "product_family": "MOONG",
        "variant_name": "Pudhina",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Dried pudhina leaf powder with light pepper.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED"},
            {"material_name": "Pudhina Powder", "quantity": 20, "unit": "g", "rate_per_unit": 250.0, "rate_status": "CONFIRMED"},
            {"material_name": "Black Pepper", "quantity": 10, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-MOONG-GREENCHILLI-V2",
        "product_id": "PRD-MOONG-GREENCHILLI",
        "product_name_snapshot": "Moong Green Chilli Papad",
        "product_family": "MOONG",
        "variant_name": "Green Chilli",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Green chilli flakes blend.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED"},
            {"material_name": "Green Chilli Powder", "quantity": 25, "unit": "g", "rate_per_unit": 280.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-MOONG-KASURI-V2",
        "product_id": "PRD-MOONG-KASURI",
        "product_name_snapshot": "Moong Kasuri Methi Papad",
        "product_family": "MOONG",
        "variant_name": "Kasuri Methi",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Aromatic Kasuri methi leaves.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED"},
            {"material_name": "Kasuri Methi", "quantity": 20, "unit": "g", "rate_per_unit": 300.0, "rate_status": "CONFIRMED"},
            {"material_name": "Black Pepper", "quantity": 10, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-MOONG-PUNJABI-V2",
        "product_id": "PRD-MOONG-PUNJABI",
        "product_name_snapshot": "Moong Punjabi Masala Papad",
        "product_family": "MOONG",
        "variant_name": "Punjabi Masala",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Spiced Punjabi garam masala blend with extra black pepper.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED"},
            {"material_name": "Punjabi Masala Blend", "quantity": 30, "unit": "g", "rate_per_unit": 450.0, "rate_status": "CONFIRMED"},
            {"material_name": "Black Pepper", "quantity": 20, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-MOONG-KHATAMEETHA-V2",
        "product_id": "PRD-MOONG-KHATAMEETHA",
        "product_name_snapshot": "Moong Khata Meetha Papad",
        "product_family": "MOONG",
        "variant_name": "Khata Meetha",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Tangy sweet blend. Sweetener rate pending supplier quote.",
        "items": [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 120.0, "rate_status": "CONFIRMED"},
            {"material_name": "Amchur (Dry Mango)", "quantity": 20, "unit": "g", "rate_per_unit": 220.0, "rate_status": "CONFIRMED"},
            {"material_name": "Sweetener Blend", "quantity": 25, "unit": "g", "rate_per_unit": None, "rate_status": "PENDING", "notes": "Rate to confirm"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 40, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },

    # -------------------------------------------------------------
    # CHANA FAMILY (5 VARIANTS) - FLOUR RATIO 750g CHANA : 250g URAD
    # -------------------------------------------------------------
    {
        "recipe_id": "RCP-CHANA-CHOTU-V2",
        "product_id": "PRD-CHANA-CHOTU",
        "product_name_snapshot": "Chana Chotu Papad",
        "product_family": "CHANA",
        "variant_name": "Chotu",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 costing: 750g Chana + 250g Urad with proposed 1g SMOS addition. Pending owner confirmation.",
        "items": [
            {"material_name": "Chana Dal Flour", "quantity": 750, "unit": "g", "rate_per_unit": 85.0, "rate_status": "CONFIRMED", "notes": "75% of flour blend"},
            {"material_name": "Urad Dal Flour", "quantity": 250, "unit": "g", "rate_per_unit": 130.0, "rate_status": "CONFIRMED", "notes": "25% binding flour"},
            {"material_name": "Black Pepper", "quantity": 15, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED", "notes": "Proposed shelf-life addition"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-CHANA-GARLIC-V2",
        "product_id": "PRD-CHANA-GARLIC",
        "product_name_snapshot": "Chana Garlic Papad",
        "product_family": "CHANA",
        "variant_name": "Garlic",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Chana 750:250 ratio with garlic blend and proposed SMOS.",
        "items": [
            {"material_name": "Chana Dal Flour", "quantity": 750, "unit": "g", "rate_per_unit": 85.0, "rate_status": "CONFIRMED"},
            {"material_name": "Urad Dal Flour", "quantity": 250, "unit": "g", "rate_per_unit": 130.0, "rate_status": "CONFIRMED"},
            {"material_name": "Garlic Paste / Powder", "quantity": 40, "unit": "g", "rate_per_unit": 160.0, "rate_status": "CONFIRMED"},
            {"material_name": "Black Pepper", "quantity": 15, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-CHANA-KHATAMITHA-V2",
        "product_id": "PRD-CHANA-KHATAMITHA",
        "product_name_snapshot": "Chana Khata Mitha Papad",
        "product_family": "CHANA",
        "variant_name": "Khata Mitha",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Sweetener blend rate pending quotation.",
        "items": [
            {"material_name": "Chana Dal Flour", "quantity": 750, "unit": "g", "rate_per_unit": 85.0, "rate_status": "CONFIRMED"},
            {"material_name": "Urad Dal Flour", "quantity": 250, "unit": "g", "rate_per_unit": 130.0, "rate_status": "CONFIRMED"},
            {"material_name": "Amchur (Dry Mango)", "quantity": 20, "unit": "g", "rate_per_unit": 220.0, "rate_status": "CONFIRMED"},
            {"material_name": "Sweetener Blend", "quantity": 25, "unit": "g", "rate_per_unit": None, "rate_status": "PENDING", "notes": "Rate to confirm"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 40, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-CHANA-TOMATO-V2",
        "product_id": "PRD-CHANA-TOMATO",
        "product_name_snapshot": "Chana Tomato Papad",
        "product_family": "CHANA",
        "variant_name": "Tomato",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Dehydrated tomato powder rate pending confirmation.",
        "items": [
            {"material_name": "Chana Dal Flour", "quantity": 750, "unit": "g", "rate_per_unit": 85.0, "rate_status": "CONFIRMED"},
            {"material_name": "Urad Dal Flour", "quantity": 250, "unit": "g", "rate_per_unit": 130.0, "rate_status": "CONFIRMED"},
            {"material_name": "Tomato Powder", "quantity": 35, "unit": "g", "rate_per_unit": None, "rate_status": "PENDING", "notes": "Rate to confirm"},
            {"material_name": "Black Pepper", "quantity": 10, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-CHANA-PUNJABI-V2",
        "product_id": "PRD-CHANA-PUNJABI",
        "product_name_snapshot": "Chana Punjabi Masala Papad",
        "product_family": "CHANA",
        "variant_name": "Punjabi Masala",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Chana 750:250 ratio with Punjabi masala spices.",
        "items": [
            {"material_name": "Chana Dal Flour", "quantity": 750, "unit": "g", "rate_per_unit": 85.0, "rate_status": "CONFIRMED"},
            {"material_name": "Urad Dal Flour", "quantity": 250, "unit": "g", "rate_per_unit": 130.0, "rate_status": "CONFIRMED"},
            {"material_name": "Punjabi Masala Blend", "quantity": 30, "unit": "g", "rate_per_unit": 450.0, "rate_status": "CONFIRMED"},
            {"material_name": "Black Pepper", "quantity": 20, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },

    # -------------------------------------------------------------
    # URAD FAMILY (2 VARIANTS) - FLOUR RATIO 850g URAD : 150g SABUDANA
    # -------------------------------------------------------------
    {
        "recipe_id": "RCP-URAD-GURU-V2",
        "product_id": "PRD-URAD-GURU",
        "product_name_snapshot": "Urad Guru Papad",
        "product_family": "URAD",
        "variant_name": "Guru",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 base: 850g Urad + 150g Sabudana with proposed 1g SMOS addition. Pending owner confirmation.",
        "items": [
            {"material_name": "Urad Dal Flour", "quantity": 850, "unit": "g", "rate_per_unit": 130.0, "rate_status": "CONFIRMED", "notes": "85% Urad dal flour"},
            {"material_name": "Sabudana Flour", "quantity": 150, "unit": "g", "rate_per_unit": 90.0, "rate_status": "CONFIRMED", "notes": "15% Sabudana flour"},
            {"material_name": "Black Pepper", "quantity": 15, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED", "notes": "Proposed addition"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
    {
        "recipe_id": "RCP-URAD-GARLIC-V2",
        "product_id": "PRD-URAD-GARLIC",
        "product_name_snapshot": "Urad Garlic Papad",
        "product_family": "URAD",
        "variant_name": "Garlic",
        "version": 2.0,
        "batch_size": 1000.0,
        "batch_unit": "g flour base",
        "expected_yield_kg": 1.2,
        "status": "DRAFT",
        "approved": False,
        "effective_date": "2026-10-17",
        "created_by": "SYSTEM_BOOTSTRAP",
        "approved_by": "",
        "change_notes": "Proposed V2.0 revision: Urad 850:150 ratio with garlic blend and proposed SMOS.",
        "items": [
            {"material_name": "Urad Dal Flour", "quantity": 850, "unit": "g", "rate_per_unit": 130.0, "rate_status": "CONFIRMED"},
            {"material_name": "Sabudana Flour", "quantity": 150, "unit": "g", "rate_per_unit": 90.0, "rate_status": "CONFIRMED"},
            {"material_name": "Garlic Paste / Powder", "quantity": 40, "unit": "g", "rate_per_unit": 160.0, "rate_status": "CONFIRMED"},
            {"material_name": "Black Pepper", "quantity": 15, "unit": "g", "rate_per_unit": 700.0, "rate_status": "CONFIRMED"},
            {"material_name": "Hing", "quantity": 5, "unit": "g", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
            {"material_name": "SMOS", "quantity": 1, "unit": "g", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED"},
            {"material_name": "Papad Khar", "quantity": 40, "unit": "g", "rate_per_unit": 150.0, "rate_status": "CONFIRMED"},
            {"material_name": "Edible Oil", "quantity": 15, "unit": "ml", "rate_per_unit": 142.0, "rate_status": "CONFIRMED"},
        ],
    },
]

# Raw materials to initialize in inventory
RAW_MATERIALS_SEED = [
    {"raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "current_stock": 250.0, "unit": "kg", "rate_per_unit": 120.0, "rate_status": "CONFIRMED", "category": "FLOUR"},
    {"raw_material_id": "RM-CHANA-FLOUR", "material_name": "Chana Dal Flour", "current_stock": 200.0, "unit": "kg", "rate_per_unit": 85.0, "rate_status": "CONFIRMED", "category": "FLOUR"},
    {"raw_material_id": "RM-URAD-FLOUR", "material_name": "Urad Dal Flour", "current_stock": 200.0, "unit": "kg", "rate_per_unit": 130.0, "rate_status": "CONFIRMED", "category": "FLOUR"},
    {"raw_material_id": "RM-SABUDANA-FLOUR", "material_name": "Sabudana Flour", "current_stock": 100.0, "unit": "kg", "rate_per_unit": 90.0, "rate_status": "CONFIRMED", "category": "FLOUR"},
    {"raw_material_id": "RM-BLACK-PEPPER", "material_name": "Black Pepper", "current_stock": 25.0, "unit": "kg", "rate_per_unit": 700.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-HING", "material_name": "Hing", "current_stock": 10.0, "unit": "kg", "rate_per_unit": 2500.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-SALT", "material_name": "Salt", "current_stock": 100.0, "unit": "kg", "rate_per_unit": 20.0, "rate_status": "CONFIRMED", "category": "SALT"},
    {"raw_material_id": "RM-SMOS", "material_name": "SMOS", "current_stock": 5.0, "unit": "kg", "rate_per_unit": 1500.0, "rate_status": "CONFIRMED", "category": "PRESERVATIVE"},
    {"raw_material_id": "RM-PAPAD-KHAR", "material_name": "Papad Khar", "current_stock": 50.0, "unit": "kg", "rate_per_unit": 150.0, "rate_status": "CONFIRMED", "category": "ADDITIVE"},
    {"raw_material_id": "RM-EDIBLE-OIL", "material_name": "Edible Oil", "current_stock": 60.0, "unit": "L", "rate_per_unit": 142.0, "rate_status": "CONFIRMED", "category": "OIL"},
    {"raw_material_id": "RM-GARLIC", "material_name": "Garlic Paste / Powder", "current_stock": 20.0, "unit": "kg", "rate_per_unit": 160.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-JEERA", "material_name": "Cumin Seeds (Jeera)", "current_stock": 20.0, "unit": "kg", "rate_per_unit": 320.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-PUDHINA", "material_name": "Pudhina Powder", "current_stock": 15.0, "unit": "kg", "rate_per_unit": 250.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-GREEN-CHILLI", "material_name": "Green Chilli Powder", "current_stock": 15.0, "unit": "kg", "rate_per_unit": 280.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-KASURI-METHI", "material_name": "Kasuri Methi", "current_stock": 15.0, "unit": "kg", "rate_per_unit": 300.0, "rate_status": "CONFIRMED", "category": "HERB"},
    {"raw_material_id": "RM-PUNJABI-MASALA", "material_name": "Punjabi Masala Blend", "current_stock": 20.0, "unit": "kg", "rate_per_unit": 450.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-AMCHUR", "material_name": "Amchur (Dry Mango)", "current_stock": 15.0, "unit": "kg", "rate_per_unit": 220.0, "rate_status": "CONFIRMED", "category": "SPICE"},
    {"raw_material_id": "RM-TOMATO-POWDER", "material_name": "Tomato Powder", "current_stock": 10.0, "unit": "kg", "rate_per_unit": None, "rate_status": "PENDING", "category": "FLAVOUR"},
    {"raw_material_id": "RM-SWEETENER", "material_name": "Sweetener Blend", "current_stock": 10.0, "unit": "kg", "rate_per_unit": None, "rate_status": "PENDING", "category": "SWEETENER"},
    {"raw_material_id": "RM-WHOLE-MOONG-DAL", "material_name": "Whole Moong Dal", "current_stock": 0.0, "unit": "kg", "rate_per_unit": 110.0, "rate_status": "CONFIRMED", "category": "WHOLE_GRAIN"},
    {"raw_material_id": "RM-WHOLE-URAD-DAL", "material_name": "Whole Urad Dal", "current_stock": 0.0, "unit": "kg", "rate_per_unit": 120.0, "rate_status": "CONFIRMED", "category": "WHOLE_GRAIN"},
    {"raw_material_id": "RM-WHOLE-CHANA-DAL", "material_name": "Whole Chana Dal", "current_stock": 0.0, "unit": "kg", "rate_per_unit": 75.0, "rate_status": "CONFIRMED", "category": "WHOLE_GRAIN"},
]
