"""Basic tests for the production-to-packets-to-dispatch workflow."""
import asyncio
import pytest
from fastapi import HTTPException
from app.sheets import db
from app.routers import production as prod


def reset_db():
    db.is_connected = False
    for key in list(db.memory_store):
        db.memory_store[key] = []
    db.memory_store.update({"Products": [], "RawMaterials": [], "Workers": [], "Recipes": [], "ProductionBatches": [], "PackagingBatches": [], "ProductionStockLedger": [], "ProductionDispatches": [], "RawMaterialLedger": [], "AuditLog": []})


def setup_product():
    db.memory_store["Products"].append({"product_id":"PRD-000001","sku":"KS-MP-200","product_name":"Moong Master Papad","active":"true","pack_weight_g":200})
    db.memory_store["Products"].append({"product_id":"PRD-000002","sku":"KS-MP-500","product_name":"Moong Master Papad","active":"true","pack_weight_g":500})
    db.memory_store["Products"].append({"product_id":"PRD-000003","sku":"KS-MP-1000","product_name":"Moong Master Papad","active":"true","pack_weight_g":1000})
    db.memory_store["RawMaterials"].append({"raw_material_id":"RM-1","material_name":"Moong Flour","current_stock":100,"unit":"kg"})


def test_production_requires_approved_recipe_and_consumes_materials():
    reset_db(); setup_product()
    batch = asyncio.run(prod.create_batch(prod.ProductionCreate(product_id="PRD-000001", production_date="2026-10-17", quantity_kg=10, wastage_kg=1), {"user_id":"USR-1","role":"OWNER"}))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(prod.approve_batch(batch["production_id"], prod.ApprovalRequest(approved=True), {"user_id":"USR-1","role":"OWNER"}))
    assert exc.value.status_code == 400
    asyncio.run(prod.save_recipe(prod.RecipeSave(product_id="PRD-000001", items=[prod.RecipeItemInput(material_name="Moong Flour", quantity_per_kg=0.8, unit="kg")], approved=True), {"user_id":"USR-1","role":"OWNER"}))
    approved = asyncio.run(prod.approve_batch(batch["production_id"], prod.ApprovalRequest(approved=True), {"user_id":"USR-1","role":"OWNER"}))
    assert approved["status"] == "APPROVED"
    assert len(db.memory_store["RawMaterialLedger"]) == 1
    assert db.memory_store["RawMaterialLedger"][0]["quantity"] == pytest.approx(7.2)
    assert any(r["movement_type"] == "BULK_PRODUCED" and r["quantity_kg"] == pytest.approx(9) for r in db.memory_store["ProductionStockLedger"])


def test_packaging_consumes_bulk_and_dispatch_is_not_sale():
    reset_db(); setup_product()
    db.memory_store["ProductionStockLedger"].append({"movement_id":"x","movement_type":"BULK_PRODUCED","product_id":"PRD-000001","bulk_product_key":"moong master papad","product_name_snapshot":"Moong Master Papad","quantity_kg":20,"quantity_packets":0})
    pack = asyncio.run(prod.create_packaging(prod.PackagingCreate(product_id="PRD-000001", packaging_date="2026-10-17", bulk_kg_used=10, packets_200g=25, packets_500g=10, packets_1000g=0), {"user_id":"USR-1","role":"OWNER"}))
    assert pack["total_packets"] == 35
    assert pack["expected_kg"] == pytest.approx(10)
    packet_rows = [r for r in db.memory_store["ProductionStockLedger"] if r["movement_type"] == "PACKETS_PACKAGED"]
    assert {r["product_id"] for r in packet_rows} == {"PRD-000001", "PRD-000002"}
    dispatch = asyncio.run(prod.dispatch(prod.DispatchCreate(product_id="PRD-000001", channel="ECOMMERCE", destination="Warehouse", quantity_packets=10), {"user_id":"USR-1","role":"OWNER"}))
    assert dispatch["status"] == "DISPATCHED_NOT_SALE"
    assert not db.memory_store.get("Sales")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(prod.dispatch(prod.DispatchCreate(product_id="PRD-000001", channel="RETAIL", destination="Shop", quantity_packets=1000), {"user_id":"USR-1","role":"OWNER"}))
    assert exc.value.status_code == 400
