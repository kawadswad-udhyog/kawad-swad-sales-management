from typing import List, Any, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import Product, ProductCreate, ProductUpdate
from app.sheets import db
from app.auth import get_current_user

router = APIRouter(prefix="/api/products", tags=["Products"])

def _parse_bool(val: Any, default: bool = True) -> bool:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ["true", "1", "yes", "active", "y"]

def _get_val(r: dict, *keys, default=None):
    for k in keys:
        if k in r:
            return r[k]
    lowers = {str(k).strip().lower(): v for k, v in r.items()}
    for k in keys:
        k_low = str(k).strip().lower()
        if k_low in lowers:
            return lowers[k_low]
    return default

@router.get("", response_model=List[Product])
async def list_products(current_user: dict = Depends(get_current_user)):
    records = db.get_records("Products")
    products = []
    for r in records:
        pid = str(_get_val(r, "product_id", default="")).strip()
        if not pid:
            continue
        products.append(Product(
            product_id=pid,
            sku=str(_get_val(r, "sku", default="")),
            product_name=str(_get_val(r, "product_name", default="")),
            category=str(_get_val(r, "category", default="Papad")),
            variant=str(_get_val(r, "variant", default="")),
            pack_weight_g=int(_get_val(r, "pack_weight_g", default=500) or 500),
            selling_unit=str(_get_val(r, "selling_unit", default="PACKET")),
            retail_pack_only=_parse_bool(_get_val(r, "retail_pack_only"), default=False),
            active=_parse_bool(_get_val(r, "active"), default=True),
            notes=str(_get_val(r, "notes", default="")),
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
        "sku": req.sku.strip(),
        "product_name": req.product_name.strip(),
        "category": req.category or "Papad",
        "variant": req.variant or "",
        "pack_weight_g": req.pack_weight_g,
        "selling_unit": req.selling_unit or "PACKET",
        "retail_pack_only": "true" if req.retail_pack_only else "false",
        "active": "true" if req.active else "false",
        "notes": req.notes or "",
    }
    if not db.append_record("Products", record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Could not save product to persistent storage.")

    db.log_audit(
        actor=current_user.get("user_id"),
        action="CREATE_PRODUCT",
        entity_type="Products",
        entity_id=product_id,
        reason=f"Created product {req.product_name} ({req.sku})"
    )

    return Product(
        product_id=product_id,
        sku=req.sku.strip(),
        product_name=req.product_name.strip(),
        category=req.category or "Papad",
        variant=req.variant or "",
        pack_weight_g=req.pack_weight_g,
        selling_unit=req.selling_unit or "PACKET",
        retail_pack_only=bool(req.retail_pack_only),
        active=bool(req.active),
        notes=req.notes or "",
    )

@router.patch("/{product_id}", response_model=Product)
@router.put("/{product_id}", response_model=Product)
async def update_product(product_id: str, req: ProductUpdate, current_user: dict = Depends(get_current_user)):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can update products")

    records = db.get_records("Products")
    existing = next((r for r in records if str(_get_val(r, "product_id", default="")) == product_id), None)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    updates = {}
    if req.sku is not None:
        updates["sku"] = req.sku.strip()
    if req.product_name is not None:
        updates["product_name"] = req.product_name.strip()
    if req.category is not None:
        updates["category"] = req.category.strip()
    if req.variant is not None:
        updates["variant"] = req.variant.strip()
    if req.pack_weight_g is not None:
        updates["pack_weight_g"] = int(req.pack_weight_g)
    if req.selling_unit is not None:
        updates["selling_unit"] = req.selling_unit.strip()
    if req.retail_pack_only is not None:
        updates["retail_pack_only"] = "true" if req.retail_pack_only else "false"
    if req.active is not None:
        updates["active"] = "true" if req.active else "false"
    if req.notes is not None:
        updates["notes"] = req.notes.strip()

    if updates:
        if not db.update_record("Products", "product_id", product_id, updates, raise_on_error=True):
            raise HTTPException(status_code=503, detail="Could not update product in persistent storage.")

    merged = {**existing, **updates}
    p_name = merged.get("product_name") or product_id

    db.log_audit(
        actor=current_user.get("user_id"),
        action="UPDATE_PRODUCT",
        entity_type="Products",
        entity_id=product_id,
        reason=f"Updated product {p_name}" + (f" (active={req.active})" if req.active is not None else "")
    )

    return Product(
        product_id=product_id,
        sku=str(_get_val(merged, "sku", default="")),
        product_name=str(_get_val(merged, "product_name", default="")),
        category=str(_get_val(merged, "category", default="Papad")),
        variant=str(_get_val(merged, "variant", default="")),
        pack_weight_g=int(_get_val(merged, "pack_weight_g", default=500) or 500),
        selling_unit=str(_get_val(merged, "selling_unit", default="PACKET")),
        retail_pack_only=_parse_bool(_get_val(merged, "retail_pack_only"), default=False),
        active=_parse_bool(_get_val(merged, "active"), default=True),
        notes=str(_get_val(merged, "notes", default="")),
    )
