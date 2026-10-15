from datetime import datetime
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
        customers.append(Customer(
            customer_id=str(r.get("customer_id", "")),
            customer_type=str(r.get("customer_type", "RETAILER")),
            shop_name=str(r.get("shop_name", "")),
            shopkeeper_name=str(r.get("shopkeeper_name", "")),
            mobile=str(r.get("mobile", "")),
            alternate_mobile=str(r.get("alternate_mobile", "")),
            address=str(r.get("address", "")),
            locality_area=str(r.get("locality_area", "")),
            city=str(r.get("city", "Bhilwara")),
            map_location=str(r.get("map_location", "")),
            active=str(r.get("active", "true")).lower() == "true",
            created_at=str(r.get("created_at", "")),
            notes=str(r.get("notes", "")),
        ))
    return customers

@router.post("", response_model=Customer)
async def create_customer(req: CustomerCreate, current_user: dict = Depends(get_current_user)):
    customer_id = db.generate_id("Customers")
    now_iso = datetime.utcnow().isoformat()
    record = {
        "customer_id": customer_id,
        "customer_type": req.customer_type or "RETAILER",
        "shop_name": req.shop_name,
        "shopkeeper_name": req.shopkeeper_name,
        "mobile": req.mobile,
        "alternate_mobile": req.alternate_mobile or "",
        "address": req.address,
        "locality_area": req.locality_area or "",
        "city": req.city or "Bhilwara",
        "map_location": req.map_location or "",
        "active": "true",
        "created_at": now_iso,
        "notes": req.notes or "",
    }
    db.append_record("Customers", record)

    db.log_audit(
        actor=current_user.get("user_id"),
        action="CREATE_CUSTOMER",
        entity_type="Customers",
        entity_id=customer_id,
        reason=f"Registered customer {req.shop_name}"
    )

    return Customer(**record, active=True)

@router.put("/{customer_id}", response_model=Customer)
async def update_customer(customer_id: str, req: CustomerCreate, current_user: dict = Depends(get_current_user)):
    updates = {
        "customer_type": req.customer_type or "RETAILER",
        "shop_name": req.shop_name,
        "shopkeeper_name": req.shopkeeper_name,
        "mobile": req.mobile,
        "alternate_mobile": req.alternate_mobile or "",
        "address": req.address,
        "locality_area": req.locality_area or "",
        "city": req.city or "Bhilwara",
        "map_location": req.map_location or "",
        "notes": req.notes or "",
    }
    db.update_record("Customers", "customer_id", customer_id, updates)

    db.log_audit(
        actor=current_user.get("user_id"),
        action="UPDATE_CUSTOMER",
        entity_type="Customers",
        entity_id=customer_id,
        reason=f"Updated details for customer {req.shop_name}"
    )

    return Customer(
        customer_id=customer_id,
        **updates,
        active=True,
    )
