from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import Customer, CustomerCreate
from app.sheets import db
from app.auth import get_current_user

router = APIRouter(prefix="/api/customers", tags=["Customers"])

@router.get("", response_model=List[Customer])
async def list_customers(current_user: dict = Depends(get_current_user)):
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
            city=str(r.get("city", "Bhilwara") or "Bhilwara"),
            gstin="" if str(r.get("gstin", "")).lower() in ["none", "null", "undefined"] else str(r.get("gstin", "")),
            map_location="" if str(r.get("map_location", "")).lower() in ["none", "null", "undefined"] else str(r.get("map_location", "")),
            active=str(r.get("active", "true")).lower() == "true",
            created_at=str(r.get("created_at", "")),
            notes="" if str(r.get("notes", "")).lower() in ["none", "null", "undefined"] else str(r.get("notes", "")),
        ))
    return customers

@router.post("", response_model=Customer)
async def create_customer(req: CustomerCreate, current_user: dict = Depends(get_current_user)):
    clean_shop_name = (req.shop_name or "").strip()
    if not clean_shop_name or len(clean_shop_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A meaningful customer or business name is required (minimum 2 characters).",
        )

    customer_id = db.generate_id("Customers")
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "customer_id": customer_id,
        "customer_type": (req.customer_type or "RETAILER").strip(),
        "shop_name": clean_shop_name,
        "shopkeeper_name": (req.shopkeeper_name or "").strip(),
        "mobile": (req.mobile or "").strip(),
        "alternate_mobile": (req.alternate_mobile or "").strip(),
        "address": (req.address or "").strip(),
        "locality_area": (req.locality_area or "").strip(),
        "city": (req.city or "Bhilwara").strip(),
        "gstin": (req.gstin or "").strip(),
        "map_location": (req.map_location or "").strip(),
        "active": "true",
        "created_at": now_iso,
        "notes": (req.notes or "").strip(),
    }
    if not db.append_record("Customers", record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Could not save customer to persistent storage.")

    db.log_audit(
        actor=current_user.get("user_id"),
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
        created_at=now_iso,
        notes=record["notes"],
    )

@router.put("/{customer_id}", response_model=Customer)
async def update_customer(customer_id: str, req: CustomerCreate, current_user: dict = Depends(get_current_user)):
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
        "city": (req.city or "Bhilwara").strip(),
        "gstin": (req.gstin or "").strip(),
        "map_location": (req.map_location or "").strip(),
        "notes": (req.notes or "").strip(),
    }
    existing = next((r for r in db.get_records("Customers") if str(r.get("customer_id", "")) == customer_id), None)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    if not db.update_record("Customers", "customer_id", customer_id, updates, raise_on_error=True):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Customer could not be saved. Check the Google Sheets connection and retry.")

    db.log_audit(
        actor=current_user.get("user_id"),
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
