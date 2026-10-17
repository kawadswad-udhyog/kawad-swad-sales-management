import asyncio
import re
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import Sale, SaleCreate, SaleItem
from app.sheets import db
from app.auth import get_current_user

router = APIRouter(prefix="/api/sales", tags=["Sales"])
_sales_lock = asyncio.Lock()

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
            notes="" if str(itm.get("notes", "")).lower() in ["none", "null", "undefined"] else str(itm.get("notes", "")),
        )
        items_by_sale.setdefault(s_id, []).append(item_obj)

    sales = []
    for r in sales_records:
        salesman_id = str(r.get("salesman_user_id", ""))
        # Filter if salesman role: can only view their own sales
        if role not in ["OWNER", "OWNER_ADMIN", "PA"] and salesman_id != user_id:
            continue

        sale_id = str(r.get("sale_id", ""))
        cust_name = str(r.get("customer_name_snapshot", "")).strip()
        if not cust_name or cust_name.lower() in ["none", "null", "undefined"]:
            cust_name = "Walk-in Customer"

        cust_id = str(r.get("customer_id", "")).strip()
        if cust_id.lower() in ["none", "null", "undefined"]:
            cust_id = "CUS-WALKIN"

        raw_key = str(r.get("idempotency_key", "")).strip()
        raw_note = str(r.get("notes", ""))
        if not raw_key:
            m = re.search(r"\[idemp:([^\]]+)\]", raw_note)
            if m:
                raw_key = m.group(1).strip()
        clean_note = re.sub(r"\[idemp:[^\]]+\]\s*", "", raw_note).strip()
        if clean_note.lower() in ["none", "null", "undefined"]:
            clean_note = ""

        sales.append(Sale(
            sale_id=sale_id,
            bill_number=str(r.get("bill_number", "")),
            idempotency_key=raw_key,
            sale_datetime=str(r.get("sale_datetime", "")),
            sales_type=str(r.get("sales_type", "Retailer Sale")),
            customer_id=cust_id,
            customer_name_snapshot=cust_name,
            customer_mobile="" if str(r.get("customer_mobile", "")).lower() in ["none", "null", "undefined"] else str(r.get("customer_mobile", "")),
            customer_gstin="" if str(r.get("customer_gstin", "")).lower() in ["none", "null", "undefined"] else str(r.get("customer_gstin", "")),
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
            notes=clean_note,
            items=items_by_sale.get(sale_id, []),
        ))
    return sales

@router.post("", response_model=Sale)
async def create_sale(req: SaleCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    salesman_id = (req.salesman_user_id or user_id).strip()

    # 1. Essential business validation: Line items
    raw_items = req.items or req.lines or []
    if not raw_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sale must contain at least one valid product line.",
        )

    # Validate idempotency_key format
    clean_idempotency_key = ""
    if req.idempotency_key is not None:
        clean_idempotency_key = str(req.idempotency_key).strip()
        if len(clean_idempotency_key) > 120:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="idempotency_key must not exceed 120 characters.",
            )
        if re.search(r"[\r\n\t]", clean_idempotency_key):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="idempotency_key contains invalid control characters.",
            )

    products_db = {str(p.get("product_id")): p for p in db.get_records("Products")}
    validated_items_data = []
    calc_subtotal = 0.0

    for idx, item in enumerate(raw_items):
        pid = (item.product_id or "").strip()
        if not pid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Line {idx+1}: Product selection is mandatory.",
            )
        if item.quantity is None or item.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Line {idx+1}: Quantity must be greater than zero.",
            )
        if item.actual_unit_price is None or item.actual_unit_price < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Line {idx+1}: Price cannot be negative.",
            )

        prd = products_db.get(pid, {})
        name_snapshot = (item.product_name_snapshot or prd.get("product_name") or prd.get("sku") or pid).strip()
        sku_snapshot = (item.sku_snapshot or prd.get("sku") or pid).strip()
        pack_weight_g = int(item.pack_weight_g or prd.get("pack_weight_g") or 500)
        unit = (item.unit or prd.get("selling_unit") or "PACKET").strip()
        qty = int(item.quantity)
        price = float(item.actual_unit_price)
        discount = float(item.discount_amount or 0.0)
        line_total = float(item.line_total if item.line_total is not None and item.line_total > 0 else (qty * price - discount))
        qualifying_kg = float(item.qualifying_kg or ((pack_weight_g * qty) / 1000.0 if "kg" not in unit.lower() else qty))

        calc_subtotal += line_total
        validated_items_data.append({
            "product_id": pid,
            "product_name_snapshot": name_snapshot,
            "sku_snapshot": sku_snapshot,
            "pack_weight_g": pack_weight_g,
            "unit": unit,
            "quantity": qty,
            "actual_unit_price": price,
            "discount_amount": discount,
            "line_total": line_total,
            "qualifying_kg": qualifying_kg,
            "notes": (item.notes or "").strip(),
        })

    subtotal = float(req.subtotal) if req.subtotal is not None and req.subtotal >= 0 else calc_subtotal
    discount_amount = float(req.discount_amount or 0.0)
    if discount_amount > subtotal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Discount cannot exceed subtotal.",
        )

    tax_amount = float(req.tax_amount or 0.0)
    calculated_total = max(0.0, subtotal - discount_amount + tax_amount)
    bill_total = float(req.bill_total) if req.bill_total is not None and req.bill_total >= 0 else calculated_total

    # 2. Payment method validation
    clean_payment_method = (req.payment_method or "CASH").upper().strip()
    if clean_payment_method not in ["CASH", "UPI", "BANK_TRANSFER", "OTHER"]:
        clean_payment_method = "CASH"

    # 3. Buyer info normalization (supports anonymous / quick retail sales)
    clean_cust_id = (req.customer_id or "").strip()
    clean_cust_name = (req.customer_name_snapshot or "").strip()

    if not clean_cust_id or clean_cust_id in ["WALK-IN", "CUS-WALKIN"]:
        clean_cust_id = "CUS-WALKIN"
        if not clean_cust_name or clean_cust_name.lower() in ["none", "null", "undefined"]:
            clean_cust_name = "Walk-in Customer"
    elif not clean_cust_name or clean_cust_name.lower() in ["none", "null", "undefined"]:
        # Find customer name by customer_id if available
        cust_records = db.get_records("Customers")
        match_c = next((c for c in cust_records if str(c.get("customer_id")) == clean_cust_id), None)
        if match_c:
            clean_cust_name = str(match_c.get("shop_name", "Walk-in Customer")).strip()
        else:
            clean_cust_name = "Walk-in Customer"

    clean_mobile = "" if str(req.customer_mobile or "").lower() in ["none", "null", "undefined"] else str(req.customer_mobile or "").strip()
    clean_gstin = "" if str(req.customer_gstin or "").lower() in ["none", "null", "undefined"] else str(req.customer_gstin or "").strip()
    clean_sales_type = (req.sales_type or "Retailer Sale").strip()

    # 4. Critical Section under _sales_lock for concurrent idempotency check and atomic persistence
    async with _sales_lock:
        # Check idempotency key: if matching sale already exists, return original sale immediately
        if clean_idempotency_key:
            all_sales = db.get_records("Sales")
            matched_sale = None
            for s in reversed(all_sales):
                k = str(s.get("idempotency_key", "")).strip()
                n = str(s.get("notes", ""))
                if (k and k == clean_idempotency_key) or f"[idemp:{clean_idempotency_key}]" in n:
                    matched_sale = s
                    break

            if matched_sale:
                matched_sale_id = str(matched_sale.get("sale_id", ""))
                all_items = db.get_records("SaleItems")
                s_items = [
                    SaleItem(
                        sale_item_id=str(it.get("sale_item_id", "")),
                        sale_id=str(it.get("sale_id", "")),
                        product_id=str(it.get("product_id", "")),
                        product_name_snapshot=str(it.get("product_name_snapshot", "")),
                        sku_snapshot=str(it.get("sku_snapshot", "")),
                        pack_weight_g=int(it.get("pack_weight_g", 500) or 500),
                        unit=str(it.get("unit", "PACKET")),
                        quantity=int(it.get("quantity", 1) or 1),
                        actual_unit_price=float(it.get("actual_unit_price", 0.0) or 0.0),
                        discount_amount=float(it.get("discount_amount", 0.0) or 0.0),
                        line_total=float(it.get("line_total", 0.0) or 0.0),
                        qualifying_kg=float(it.get("qualifying_kg", 0.0) or 0.0),
                        created_at=str(it.get("created_at", "")),
                        notes="" if str(it.get("notes", "")).lower() in ["none", "null", "undefined"] else str(it.get("notes", "")),
                    )
                    for it in all_items if str(it.get("sale_id")) == matched_sale_id
                ]
                raw_n = str(matched_sale.get("notes", ""))
                clean_n = re.sub(r"\[idemp:[^\]]+\]\s*", "", raw_n).strip()
                if clean_n.lower() in ["none", "null", "undefined"]:
                    clean_n = ""

                return Sale(
                    sale_id=matched_sale_id,
                    bill_number=str(matched_sale.get("bill_number", "")),
                    idempotency_key=clean_idempotency_key,
                    sale_datetime=str(matched_sale.get("sale_datetime", "")),
                    sales_type=str(matched_sale.get("sales_type", "Retailer Sale")),
                    customer_id=str(matched_sale.get("customer_id", "")),
                    customer_name_snapshot=str(matched_sale.get("customer_name_snapshot", "")),
                    customer_mobile="" if str(matched_sale.get("customer_mobile", "")).lower() in ["none", "null", "undefined"] else str(matched_sale.get("customer_mobile", "")),
                    customer_gstin="" if str(matched_sale.get("customer_gstin", "")).lower() in ["none", "null", "undefined"] else str(matched_sale.get("customer_gstin", "")),
                    entered_by_user_id=str(matched_sale.get("entered_by_user_id", "")),
                    salesman_user_id=str(matched_sale.get("salesman_user_id", "")),
                    delivery_status=str(matched_sale.get("delivery_status", "DELIVERED")),
                    payment_status=str(matched_sale.get("payment_status", "PAID")),
                    subtotal=float(matched_sale.get("subtotal", 0.0) or 0.0),
                    discount_amount=float(matched_sale.get("discount_amount", 0.0) or 0.0),
                    tax_amount=float(matched_sale.get("tax_amount", 0.0) or 0.0),
                    bill_total=float(matched_sale.get("bill_total", 0.0) or 0.0),
                    bill_status=str(matched_sale.get("bill_status", "ISSUED")),
                    created_at=str(matched_sale.get("created_at", "")),
                    notes=clean_n,
                    items=s_items,
                )

        # 4. Generate new identifiers and proceed with sale issuance
        sale_id = db.generate_id("Sales")
        now_iso = datetime.utcnow().isoformat()
        sales_count = len(db.get_records("Sales")) + 1
        bill_number = f"KS-BILL-{datetime.utcnow().strftime('%Y%m')}-{str(sales_count).zfill(5)}"

        # 5. Append Sale record
        stored_notes = (req.notes or "").strip()
        if clean_idempotency_key and f"[idemp:{clean_idempotency_key}]" not in stored_notes:
            stored_notes = f"[idemp:{clean_idempotency_key}] {stored_notes}".strip()

        sale_record = {
            "sale_id": sale_id,
            "bill_number": bill_number,
            "idempotency_key": clean_idempotency_key,
            "sale_datetime": now_iso,
            "sales_type": clean_sales_type,
            "customer_id": clean_cust_id,
            "customer_name_snapshot": clean_cust_name,
            "customer_mobile": clean_mobile,
            "customer_gstin": clean_gstin,
            "entered_by_user_id": user_id,
            "salesman_user_id": salesman_id,
            "delivery_status": req.delivery_status or "DELIVERED",
            "payment_status": req.payment_status or "PAID",
            "subtotal": subtotal,
            "discount_amount": discount_amount,
            "tax_amount": tax_amount,
            "bill_total": bill_total,
            "bill_status": "ISSUED",
            "created_at": now_iso,
            "notes": stored_notes,
        }
        db.append_record("Sales", sale_record, raise_on_error=True)

        # 6. Append SaleItems & create stock movements
        created_items: List[SaleItem] = []
        for it_data in validated_items_data:
            sale_item_id = db.generate_id("SaleItems")
            item_record = {
                "sale_item_id": sale_item_id,
                "sale_id": sale_id,
                "product_id": it_data["product_id"],
                "product_name_snapshot": it_data["product_name_snapshot"],
                "sku_snapshot": it_data["sku_snapshot"],
                "pack_weight_g": it_data["pack_weight_g"],
                "unit": it_data["unit"],
                "quantity": it_data["quantity"],
                "actual_unit_price": it_data["actual_unit_price"],
                "discount_amount": it_data["discount_amount"],
                "line_total": it_data["line_total"],
                "qualifying_kg": it_data["qualifying_kg"],
                "created_at": now_iso,
                "notes": it_data["notes"],
            }
            db.append_record("SaleItems", item_record, raise_on_error=True)
            created_items.append(SaleItem(**item_record))

            # Update Salesman Stock Ledger for sale delivery
            stock_txn_id = db.generate_id("SalesmanStockLedger")
            stock_record = {
                "stock_txn_id": stock_txn_id,
                "txn_datetime": now_iso,
                "salesman_user_id": salesman_id,
                "product_id": it_data["product_id"],
                "sku_snapshot": it_data["sku_snapshot"],
                "txn_type": "SOLD_DELIVERY",
                "quantity": -it_data["quantity"],
                "unit": it_data["unit"],
                "pack_weight_g": it_data["pack_weight_g"],
                "related_sale_id": sale_id,
                "issued_by_user_id": user_id,
                "received_by_user_id": clean_cust_id,
                "confirmed_by_user_id": salesman_id,
                "reference_id": bill_number,
                "notes": f"Sale delivery against bill {bill_number}",
            }
            db.append_record("SalesmanStockLedger", stock_record)

        # 7. Append Payments record
        payment_id = db.generate_id("Payments")
        payment_record = {
            "payment_id": payment_id,
            "sale_id": sale_id,
            "payment_datetime": now_iso,
            "payment_method": clean_payment_method,
            "amount": bill_total,
            "reference_number": bill_number,
            "received_by_user_id": salesman_id,
            "payment_status": "PAID",
            "notes": f"Full payment for bill {bill_number}",
        }
        db.append_record("Payments", payment_record)

        # 8. If cash payment, record in CashLedger
        if clean_payment_method == "CASH":
            csh_id = db.generate_id("CashLedger")
            cash_record = {
                "cash_txn_id": csh_id,
                "txn_datetime": now_iso,
                "salesman_user_id": salesman_id,
                "txn_type": "SALE_COLLECTION",
                "amount": bill_total,
                "payment_method": "CASH",
                "related_sale_id": sale_id,
                "related_expense_id": "",
                "issued_by_user_id": clean_cust_id,
                "received_by_user_id": salesman_id,
                "confirmed_by_user_id": salesman_id,
                "reference_id": bill_number,
                "notes": f"Cash collection for bill {bill_number}",
            }
            db.append_record("CashLedger", cash_record)

        # 9. Audit Log
        db.log_audit(
            actor=user_id,
            action="ISSUE_BILL",
            entity_type="Sales",
            entity_id=sale_id,
            reason=f"Issued bill {bill_number} for ₹{bill_total} to {clean_cust_name}"
        )

        return Sale(
            sale_id=sale_id,
            bill_number=bill_number,
            idempotency_key=clean_idempotency_key,
            sale_datetime=now_iso,
            sales_type=clean_sales_type,
            customer_id=clean_cust_id,
            customer_name_snapshot=clean_cust_name,
            customer_mobile=clean_mobile,
            customer_gstin=clean_gstin,
            entered_by_user_id=user_id,
            salesman_user_id=salesman_id,
            delivery_status=req.delivery_status or "DELIVERED",
            payment_status=req.payment_status or "PAID",
            subtotal=subtotal,
            discount_amount=discount_amount,
            tax_amount=tax_amount,
            bill_total=bill_total,
            bill_status="ISSUED",
            created_at=now_iso,
            notes=(req.notes or "").strip(),
            items=created_items,
        )
