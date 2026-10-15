from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import Sale, SaleCreate, SaleItem
from app.sheets import db
from app.auth import get_current_user

router = APIRouter(prefix="/api/sales", tags=["Sales"])

@router.get("", response_model=List[Sale])
async def list_sales(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = current_user.get("role", "").upper()

    sales_records = db.get_records("Sales")
    items_records = db.get_records("SaleItems")

    items_by_sale = {}
    for itm in items_records:
        s_id = str(itm.get("sale_id", ""))
        item_obj = SaleItem(
            sale_item_id=str(itm.get("sale_item_id", "")),
            sale_id=s_id,
            product_id=str(itm.get("product_id", "")),
            product_name_snapshot=str(itm.get("product_name_snapshot", "")),
            sku_snapshot=str(itm.get("sku_snapshot", "")),
            pack_weight_g=int(itm.get("pack_weight_g", 500) or 500),
            unit=str(itm.get("unit", "PACKET")),
            quantity=int(itm.get("quantity", 1) or 1),
            actual_unit_price=float(itm.get("actual_unit_price", 0.0) or 0.0),
            discount_amount=float(itm.get("discount_amount", 0.0) or 0.0),
            line_total=float(itm.get("line_total", 0.0) or 0.0),
            qualifying_kg=float(itm.get("qualifying_kg", 0.0) or 0.0),
            created_at=str(itm.get("created_at", "")),
            notes=str(itm.get("notes", "")),
        )
        items_by_sale.setdefault(s_id, []).append(item_obj)

    sales = []
    for r in sales_records:
        salesman_id = str(r.get("salesman_user_id", ""))
        # Filter if salesman role: can only view their own sales
        if role not in ["OWNER", "OWNER_ADMIN", "PA"] and salesman_id != user_id:
            continue

        sale_id = str(r.get("sale_id", ""))
        sales.append(Sale(
            sale_id=sale_id,
            bill_number=str(r.get("bill_number", "")),
            sale_datetime=str(r.get("sale_datetime", "")),
            sales_type=str(r.get("sales_type", "Retailer Sale")),
            customer_id=str(r.get("customer_id", "")),
            customer_name_snapshot=str(r.get("customer_name_snapshot", "")),
            entered_by_user_id=str(r.get("entered_by_user_id", "")),
            salesman_user_id=salesman_id,
            delivery_status=str(r.get("delivery_status", "DELIVERED")),
            payment_status=str(r.get("payment_status", "PAID")),
            subtotal=float(r.get("subtotal", 0.0) or 0.0),
            discount_amount=float(r.get("discount_amount", 0.0) or 0.0),
            tax_amount=float(r.get("tax_amount", 0.0) or 0.0),
            bill_total=float(r.get("bill_total", 0.0) or 0.0),
            bill_status=str(r.get("bill_status", "ISSUED")),
            created_at=str(r.get("created_at", "")),
            notes=str(r.get("notes", "")),
            items=items_by_sale.get(sale_id, []),
        ))
    return sales

@router.post("", response_model=Sale)
async def create_sale(req: SaleCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    salesman_id = req.salesman_user_id or user_id

    sale_id = db.generate_id("Sales")
    now_iso = datetime.utcnow().isoformat()
    sales_count = len(db.get_records("Sales")) + 1
    bill_number = f"KS-BILL-{datetime.utcnow().strftime('%Y%m')}-{str(sales_count).zfill(5)}"

    # 1. Append Sale record
    sale_record = {
        "sale_id": sale_id,
        "bill_number": bill_number,
        "sale_datetime": now_iso,
        "sales_type": req.sales_type or "Retailer Sale",
        "customer_id": req.customer_id,
        "customer_name_snapshot": req.customer_name_snapshot,
        "entered_by_user_id": user_id,
        "salesman_user_id": salesman_id,
        "delivery_status": req.delivery_status or "DELIVERED",
        "payment_status": req.payment_status or "PAID",
        "subtotal": req.subtotal,
        "discount_amount": req.discount_amount or 0.0,
        "tax_amount": req.tax_amount or 0.0,
        "bill_total": req.bill_total,
        "bill_status": "ISSUED",
        "created_at": now_iso,
        "notes": req.notes or "",
    }
    db.append_record("Sales", sale_record)

    # 2. Append SaleItems & create stock movements
    created_items: List[SaleItem] = []
    for item in req.items:
        sale_item_id = db.generate_id("SaleItems")
        item_record = {
            "sale_item_id": sale_item_id,
            "sale_id": sale_id,
            "product_id": item.product_id,
            "product_name_snapshot": item.product_name_snapshot or "",
            "sku_snapshot": item.sku_snapshot or "",
            "pack_weight_g": item.pack_weight_g,
            "unit": item.unit,
            "quantity": item.quantity,
            "actual_unit_price": item.actual_unit_price,
            "discount_amount": item.discount_amount,
            "line_total": item.line_total,
            "qualifying_kg": item.qualifying_kg,
            "created_at": now_iso,
            "notes": item.notes or "",
        }
        db.append_record("SaleItems", item_record)
        created_items.append(SaleItem(**item_record))

        # Update Salesman Stock Ledger for sale delivery
        stock_txn_id = db.generate_id("SalesmanStockLedger")
        stock_record = {
            "stock_txn_id": stock_txn_id,
            "txn_datetime": now_iso,
            "salesman_user_id": salesman_id,
            "product_id": item.product_id,
            "sku_snapshot": item.sku_snapshot or "",
            "txn_type": "SOLD_DELIVERY",
            "quantity": -item.quantity,
            "unit": item.unit,
            "pack_weight_g": item.pack_weight_g,
            "related_sale_id": sale_id,
            "issued_by_user_id": user_id,
            "received_by_user_id": req.customer_id,
            "confirmed_by_user_id": salesman_id,
            "reference_id": bill_number,
            "notes": f"Sale delivery against bill {bill_number}",
        }
        db.append_record("SalesmanStockLedger", stock_record)

    # 3. Append Payments record
    payment_id = db.generate_id("Payments")
    payment_record = {
        "payment_id": payment_id,
        "sale_id": sale_id,
        "payment_datetime": now_iso,
        "payment_method": req.payment_method or "CASH",
        "amount": req.bill_total,
        "reference_number": bill_number,
        "received_by_user_id": salesman_id,
        "payment_status": "PAID",
        "notes": f"Full payment for bill {bill_number}",
    }
    db.append_record("Payments", payment_record)

    # 4. If cash payment, record in CashLedger
    if req.payment_method == "CASH":
        csh_id = db.generate_id("CashLedger")
        cash_record = {
            "cash_txn_id": csh_id,
            "txn_datetime": now_iso,
            "salesman_user_id": salesman_id,
            "txn_type": "SALE_COLLECTION",
            "amount": req.bill_total,
            "payment_method": "CASH",
            "related_sale_id": sale_id,
            "related_expense_id": "",
            "issued_by_user_id": req.customer_id,
            "received_by_user_id": salesman_id,
            "confirmed_by_user_id": salesman_id,
            "reference_id": bill_number,
            "notes": f"Cash collection for bill {bill_number}",
        }
        db.append_record("CashLedger", cash_record)

    # 5. Audit Log
    db.log_audit(
        actor=user_id,
        action="ISSUE_BILL",
        entity_type="Sales",
        entity_id=sale_id,
        reason=f"Issued bill {bill_number} for ₹{req.bill_total} to {req.customer_name_snapshot}"
    )

    return Sale(
        sale_id=sale_id,
        bill_number=bill_number,
        sale_datetime=now_iso,
        sales_type=req.sales_type,
        customer_id=req.customer_id,
        customer_name_snapshot=req.customer_name_snapshot,
        entered_by_user_id=user_id,
        salesman_user_id=salesman_id,
        delivery_status=req.delivery_status,
        payment_status=req.payment_status,
        subtotal=req.subtotal,
        discount_amount=req.discount_amount,
        tax_amount=req.tax_amount,
        bill_total=req.bill_total,
        bill_status="ISSUED",
        created_at=now_iso,
        notes=req.notes or "",
        items=created_items,
    )
