from typing import List, Any, Optional
from fastapi import APIRouter, HTTPException, Request, status, Depends
from app.apps_script_bridge import apps_script_bridge
from app.models import Product, ProductCreate, ProductUpdate
from app.sheets import db
from app.auth import get_current_user
from app.permissions import require_module_action, role_v2_of
from app.schema_registry import VALID_RETAIL_PACK_WEIGHTS_G, DISCONTINUED_RETAIL_PACK_WEIGHTS_G

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
            recipe_id=str(_get_val(r, "recipe_id", "master_recipe_id", default="")).strip(),
            active=_parse_bool(_get_val(r, "active"), default=True),
            notes=str(_get_val(r, "notes", default="")),
        ))
    return products

@router.post("", response_model=Product)
async def create_product(req: ProductCreate, request: Request, current_user: dict = Depends(get_current_user)):
    actor_id, actor_role = require_module_action(current_user, "catalogue", "create")

    if int(req.pack_weight_g) in DISCONTINUED_RETAIL_PACK_WEIGHTS_G or (
        (req.retail_pack_only or str(req.selling_unit or "PACKET").strip().upper() == "PACKET")
        and int(req.pack_weight_g) not in VALID_RETAIL_PACK_WEIGHTS_G
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Retail SKU pack weight must be 200g, 500g, or 1000g (received {req.pack_weight_g}g).",
        )

    record = {
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
    if req.recipe_id and req.recipe_id.strip():
        record["recipe_id"] = req.recipe_id.strip()

    res = apps_script_bridge.delegate_governed_write(
        action="CREATE_PRODUCT",
        target_tab="Products",
        payload=record,
        request=request,
        actor_user_id=actor_id,
        actor_role=actor_role,
        id_field="product_id",
        invalidate_tabs=["Products"],
    )
    product_id = str(res.get("allocated_id") or "")

    db.log_audit(
        actor=actor_id,
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
        recipe_id=(req.recipe_id or "").strip(),
        active=bool(req.active),
        notes=req.notes or "",
    )

@router.patch("/{product_id}", response_model=Product)
@router.put("/{product_id}", response_model=Product)
async def update_product(product_id: str, req: ProductUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    actor_id, actor_role = require_module_action(current_user, "catalogue", "update")

    records = db.get_records("Products")
    existing = next((r for r in records if str(_get_val(r, "product_id", default="")) == product_id), None)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if req.pack_weight_g is not None:
        w = int(req.pack_weight_g)
        eff_retail = req.retail_pack_only if req.retail_pack_only is not None else _parse_bool(_get_val(existing, "retail_pack_only"), default=False)
        eff_unit = str(req.selling_unit if req.selling_unit is not None else _get_val(existing, "selling_unit", default="PACKET")).strip().upper()
        if w in DISCONTINUED_RETAIL_PACK_WEIGHTS_G or ((eff_retail or eff_unit == "PACKET") and w not in VALID_RETAIL_PACK_WEIGHTS_G):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Retail SKU pack weight must be 200g, 500g, or 1000g (received {w}g).",
            )

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
    if req.recipe_id is not None:
        updates["recipe_id"] = req.recipe_id.strip()
    if req.active is not None:
        updates["active"] = "true" if req.active else "false"
    if req.notes is not None:
        updates["notes"] = req.notes.strip()

    if updates:
        apps_script_bridge.delegate_governed_write(
            action="UPDATE_PRODUCT",
            target_tab="Products",
            payload={"product_id": product_id, **updates},
            request=request,
            actor_user_id=actor_id,
            actor_role=actor_role,
            id_field="product_id",
            invalidate_tabs=["Products"],
        )

    merged = {**existing, **updates}
    p_name = merged.get("product_name") or product_id

    db.log_audit(
        actor=actor_id,
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
        recipe_id=str(_get_val(merged, "recipe_id", "master_recipe_id", default="")).strip(),
        active=_parse_bool(_get_val(merged, "active"), default=True),
        notes=str(_get_val(merged, "notes", default="")),
    )
