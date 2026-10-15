from typing import List
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import Product, ProductCreate
from app.sheets import db
from app.auth import get_current_user

router = APIRouter(prefix="/api/products", tags=["Products"])

@router.get("", response_model=List[Product])
async def list_products(current_user: dict = Depends(get_current_user)):
    records = db.get_records("Products")
    products = []
    for r in records:
        products.append(Product(
            product_id=str(r.get("product_id", "")),
            sku=str(r.get("sku", "")),
            product_name=str(r.get("product_name", "")),
            category=str(r.get("category", "Papad")),
            variant=str(r.get("variant", "")),
            pack_weight_g=int(r.get("pack_weight_g", 500) or 500),
            selling_unit=str(r.get("selling_unit", "PACKET")),
            retail_pack_only=str(r.get("retail_pack_only", "false")).lower() == "true",
            active=str(r.get("active", "true")).lower() == "true",
            notes=str(r.get("notes", "")),
        ))
    return products

@router.post("", response_model=Product)
async def create_product(req: ProductCreate, current_user: dict = Depends(get_current_user)):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can create products")

    product_id = db.generate_id("Products")
    record = {
        "product_id": product_id,
        "sku": req.sku,
        "product_name": req.product_name,
        "category": req.category or "Papad",
        "variant": req.variant or "",
        "pack_weight_g": req.pack_weight_g,
        "selling_unit": req.selling_unit or "PACKET",
        "retail_pack_only": "true" if req.retail_pack_only else "false",
        "active": "true" if req.active else "false",
        "notes": req.notes or "",
    }
    db.append_record("Products", record)

    db.log_audit(
        actor=current_user.get("user_id"),
        action="CREATE_PRODUCT",
        entity_type="Products",
        entity_id=product_id,
        reason=f"Created product {req.product_name} ({req.sku})"
    )

    return Product(
        product_id=product_id,
        sku=req.sku,
        product_name=req.product_name,
        category=req.category or "Papad",
        variant=req.variant or "",
        pack_weight_g=req.pack_weight_g,
        selling_unit=req.selling_unit or "PACKET",
        retail_pack_only=req.retail_pack_only,
        active=req.active,
        notes=req.notes or "",
    )

@router.put("/{product_id}", response_model=Product)
async def update_product(product_id: str, req: ProductCreate, current_user: dict = Depends(get_current_user)):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can update products")

    updates = {
        "sku": req.sku,
        "product_name": req.product_name,
        "category": req.category or "Papad",
        "variant": req.variant or "",
        "pack_weight_g": req.pack_weight_g,
        "selling_unit": req.selling_unit or "PACKET",
        "retail_pack_only": "true" if req.retail_pack_only else "false",
        "active": "true" if req.active else "false",
        "notes": req.notes or "",
    }
    db.update_record("Products", "product_id", product_id, updates)

    db.log_audit(
        actor=current_user.get("user_id"),
        action="UPDATE_PRODUCT",
        entity_type="Products",
        entity_id=product_id,
        reason=f"Updated product {req.product_name}"
    )

    return Product(
        product_id=product_id,
        **updates
    )
