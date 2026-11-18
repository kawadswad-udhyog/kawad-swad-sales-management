"""Test-only helpers for persisted Phase 4 master-data fixtures.

These helpers write exclusively to the injected in-memory db used by tests.
They are not imported by application modules and never seed a live workbook.
"""
import json


def install_recipe(db, recipe_id, product_id, product_name, items,
                   expected_yield_kg=1.2, approved=True, version=1):
    row = {
        "recipe_id": recipe_id,
        "product_id": product_id,
        "product_name_snapshot": product_name,
        "version": str(version),
        "approved": "true" if approved else "false",
        "expected_yield_kg": str(expected_yield_kg),
        "items_json": json.dumps(items),
        "created_at": "2026-11-18T00:00:00Z",
        "created_by": "TEST-OWNER",
        "approved_by": "TEST-OWNER" if approved else "",
        "approved_at": "2026-11-18T00:00:00Z" if approved else "",
        "notes": "Isolated test fixture. Not production data.",
    }
    db.memory_store.setdefault("Recipes", []).append(row)
    return row


def seed_basic_moong_recipe(db, product_id, product_name,
                            ingredient_name="Moong Dal Flour",
                            rate=100.0, quantity_per_kg=0.8,
                            expected_yield_kg=1.2, recipe_id="RCP-TEST-MOONG",
                            approved=True):
    """Install one simple test recipe and its ingredient master if absent."""
    raw_rows = db.memory_store.setdefault("RawMaterials", [])
    material = next((r for r in raw_rows
                     if str(r.get("material_name", "")).strip().casefold() == ingredient_name.strip().casefold()), None)
    if material is None:
        material = {
            "raw_material_id": "RM-TEST-MOONG-FLOUR",
            "material_name": ingredient_name,
            "unit": "kg",
            "current_stock": 500.0,
            "opening_stock_verified": "true",
            "rate_per_unit": rate,
            "rate_status": "CONFIRMED",
            "active": "true",
        }
        raw_rows.append(material)
    else:
        material.setdefault("unit", "kg")
        material.setdefault("active", "true")
    return install_recipe(
        db,
        recipe_id,
        product_id,
        product_name,
        [{"material_name": ingredient_name, "quantity_per_kg": quantity_per_kg, "unit": "kg"}],
        expected_yield_kg,
        approved,
    )
