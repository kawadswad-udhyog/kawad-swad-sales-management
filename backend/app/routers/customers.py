from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, HTTPException, Request, status, Depends
from app.apps_script_bridge import apps_script_bridge
from app.models import Customer, CustomerCreate
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import require_module_action, require_roles

router = APIRouter(prefix="/api/customers", tags=["Customers"])

@router.get("", response_model=List[Customer])
async def list_customers(current_user: dict = Depends(get_current_user)):
    require_roles(
        current_user,
        {"OWNER_ADMIN", "PA", "ACCOUNTS", "SALES", "FIELD_SALESMAN", "STORE", "AUDITOR"},
        detail="Access denied. Viewing customer records requires Sales, Store, Accounts, or Management permissions.",
    )
    records = db.get_records("Customers")
    customers = []
    for r in records:
        shop_name = str(r.get("shop_name", "")).strip()
        if not shop_name or shop_name.lower() in ["none", "null", "undefined"]:
            shop_name = "Unnamed Customer"
        customers.append(Customer(
            customer_id=str(r.get("customer_id", "")),
            customer_type=str(r.get("customer_type", "RETAILER")),
            shop_name=shop_name,
            shopkeeper_name="" if str(r.get("shopkeeper_name", "")).lower() in ["none", "null", "undefined"] else str(r.get("shopkeeper_name", "")),
            mobile="" if str(r.get("mobile", "")).lower() in ["none", "null", "undefined"] else str(r.get("mobile", "")),
            alternate_mobile="" if str(r.get("alternate_mobile", "")).lower() in ["none", "null", "undefined"] else str(r.get("alternate_mobile", "")),
            address="" if str(r.get("address", "")).lower() in ["none", "null", "undefined"] else str(r.get("address", "")),
            locality_area="" if str(r.get("locality_area", "")).lower() in ["none", "null", "undefined"] else str(r.get("locality_area", "")),
            city="" if str(r.get("city", "")).lower() in ["none", "null", "undefined"] else str(r.get("city", "")),
            gstin="" if str(r.get("gstin", "")).lower() in ["none", "null", "undefined"] else str(r.get("gstin", "")),
            map_location="" if str(r.get("map_location", "")).lower() in ["none", "null", "undefined"] else str(r.get("map_location", "")),
            active=str(r.get("active", "true")).lower() == "true",
            created_at=str(r.get("created_at", "")),
            notes="" if str(r.get("notes", "")).lower() in ["none", "null", "undefined"] else str(r.get("notes", "")),
        ))
    return customers

@router.post("", response_model=Customer, dependencies=[Depends(require_sheets_connection)])
async def create_customer(req: CustomerCreate, request: Request, current_user: dict = Depends(get_current_user)):
    actor_id, actor_role = require_module_action(current_user, "sales", "create")
    clean_shop_name = (req.shop_name or "").strip()
    if not clean_shop_name or len(clean_shop_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A meaningful customer or business name is required (minimum 2 characters).",
        )

    now_iso_str = datetime.now(timezone.utc).isoformat()
    record = {
        "customer_type": (req.customer_type or "RETAILER").strip(),
        "shop_name": clean_shop_name,
        "shopkeeper_name": (req.shopkeeper_name or "").strip(),
        "mobile": (req.mobile or "").strip(),
        "alternate_mobile": (req.alternate_mobile or "").strip(),
        "address": (req.address or "").strip(),
        "locality_area": (req.locality_area or "").strip(),
        "city": (req.city or "").strip(),
        "gstin": (req.gstin or "").strip(),
        "map_location": (req.map_location or "").strip(),
        "active": "true",
        "created_at": now_iso_str,
        "notes": (req.notes or "").strip(),
    }
    res = apps_script_bridge.delegate_governed_write(
        action="CREATE_CUSTOMER",
        target_tab="Customers",
        payload=record,
        request=request,
        actor_user_id=actor_id,
        actor_role=actor_role,
        id_field="customer_id",
        invalidate_tabs=["Customers"],
    )
    customer_id = str(res.get("allocated_id") or "")

    db.log_audit(
        actor=actor_id,
        action="CREATE_CUSTOMER",
        entity_type="Customers",
        entity_id=customer_id,
        reason=f"Registered customer {clean_shop_name}"
    )

    return Customer(
        customer_id=customer_id,
        customer_type=record["customer_type"],
        shop_name=clean_shop_name,
        shopkeeper_name=record["shopkeeper_name"],
        mobile=record["mobile"],
        alternate_mobile=record["alternate_mobile"],
        address=record["address"],
        locality_area=record["locality_area"],
        city=record["city"],
        gstin=record["gstin"],
        map_location=record["map_location"],
        active=True,
        created_at=now_iso_str,
        notes=record["notes"],
    )

@router.put("/{customer_id}", response_model=Customer, dependencies=[Depends(require_sheets_connection)])
async def update_customer(customer_id: str, req: CustomerCreate, request: Request, current_user: dict = Depends(get_current_user)):
    actor_id, actor_role = require_module_action(current_user, "sales", "create")
    clean_shop_name = (req.shop_name or "").strip()
    if not clean_shop_name or len(clean_shop_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A meaningful customer or business name is required.",
        )

    updates = {
        "customer_type": (req.customer_type or "RETAILER").strip(),
        "shop_name": clean_shop_name,
        "shopkeeper_name": (req.shopkeeper_name or "").strip(),
        "mobile": (req.mobile or "").strip(),
        "alternate_mobile": (req.alternate_mobile or "").strip(),
        "address": (req.address or "").strip(),
        "locality_area": (req.locality_area or "").strip(),
        "city": (req.city or "").strip(),
        "gstin": (req.gstin or "").strip(),
        "map_location": (req.map_location or "").strip(),
        "notes": (req.notes or "").strip(),
    }
    existing = next((r for r in db.get_records("Customers") if str(r.get("customer_id", "")) == customer_id), None)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    apps_script_bridge.delegate_governed_write(
        action="UPDATE_CUSTOMER",
        target_tab="Customers",
        payload={"customer_id": customer_id, **updates},
        request=request,
        actor_user_id=actor_id,
        actor_role=actor_role,
        id_field="customer_id",
        invalidate_tabs=["Customers"],
    )

    db.log_audit(
        actor=actor_id,
        action="UPDATE_CUSTOMER",
        entity_type="Customers",
        entity_id=customer_id,
        reason=f"Updated details for customer {clean_shop_name}"
    )

    return Customer(
        customer_id=customer_id,
        **updates,
        active=str(existing.get("active", "true")).lower() == "true",
        created_at=str(existing.get("created_at", "")),
    )
