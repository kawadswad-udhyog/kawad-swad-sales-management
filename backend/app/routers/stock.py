from datetime import datetime
from typing import List, Dict
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from app.models import StockSummaryResponse, StockTransaction, StockIssueCreate, CompanyStockItem, SalesmanStockItem
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager
from app.stock_math import balances, salesman_available

router = APIRouter(prefix="/api/stock", tags=["Stock"])

@router.get("/summary", response_model=StockSummaryResponse)
async def get_stock_summary(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")

    products = db.get_records("Products", fresh=True)
    transactions = db.get_records("SalesmanStockLedger", fresh=True)
    users = {str(u.get("user_id")): str(u.get("full_name") or u.get("user_id")) for u in db.get_records("Users")}
    company_balances, salesman_pairs = balances(transactions)
    for prod in products:
        company_balances.setdefault(str(prod.get("product_id")), 0)
    prod_map = {str(p.get("product_id")): p for p in products}

    company_stock = []
    for p_id, bal in company_balances.items():
        p_info = prod_map.get(p_id, {})
        pack = int(float(p_info.get("pack_weight_g", 500) or 500))
        company_stock.append(CompanyStockItem(
            product_id=p_id,
            sku=str(p_info.get("sku", p_id)),
            product_name=str(p_info.get("product_name", "Papad")),
            current_stock=bal,
            company_quantity=bal,
            quantity=bal,
            pack_weight_g=pack,
            unit=str(p_info.get("selling_unit", "PACKET")),
        ))

    salesman_stock = []
    for (s_user, p_id), bal in salesman_pairs.items():
        if not is_manager(current_user) and s_user != user_id:
            continue
        p_info = prod_map.get(p_id, {})
        pack = int(float(p_info.get("pack_weight_g", 500) or 500))
        salesman_stock.append(SalesmanStockItem(
            salesman_user_id=s_user,
            salesman_name=users.get(s_user, s_user),
            product_id=p_id,
            sku=str(p_info.get("sku", p_id)),
            product_name=str(p_info.get("product_name", "Papad")),
            current_stock=bal,
            quantity=bal,
            pack_weight_g=pack,
            unit=str(p_info.get("selling_unit", "PACKET")),
        ))

    return StockSummaryResponse(
        company_stock=company_stock,
        salesman_stock=salesman_stock,
    )

@router.get("/transactions", response_model=List[StockTransaction])
async def list_stock_transactions(limit: int = 250, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = current_user.get("role", "").upper()

    txns = db.get_records("SalesmanStockLedger")
    result = []
    for r in txns[-limit:]:
        s_user = str(r.get("salesman_user_id", ""))
        if role not in ["OWNER", "OWNER_ADMIN", "PA"] and s_user != user_id:
            continue
        result.append(StockTransaction(
            stock_txn_id=str(r.get("stock_txn_id", "")),
            txn_datetime=str(r.get("txn_datetime", "")),
            salesman_user_id=s_user,
            product_id=str(r.get("product_id", "")),
            sku_snapshot=str(r.get("sku_snapshot", "")),
            txn_type=str(r.get("txn_type", "")),
            quantity=int(r.get("quantity", 0) or 0),
            unit=str(r.get("unit", "PACKET")),
            pack_weight_g=int(r.get("pack_weight_g", 500) or 500),
            related_sale_id=str(r.get("related_sale_id", "")),
            issued_by_user_id=str(r.get("issued_by_user_id", "")),
            received_by_user_id=str(r.get("received_by_user_id", "")),
            confirmed_by_user_id=str(r.get("confirmed_by_user_id", "")),
            reference_id=str(r.get("reference_id", "")),
            notes=str(r.get("notes", "")),
        ))
    result.reverse()
    return result

@router.post("/transactions", response_model=StockTransaction, dependencies=[Depends(require_sheets_connection)])
@router.post("/issue", response_model=StockTransaction, dependencies=[Depends(require_sheets_connection)])
async def record_stock_movement(req: StockIssueCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = str(current_user.get("role", "")).upper()
    if req.quantity <= 0:
        raise HTTPException(status_code=422, detail="Stock quantity must be greater than zero.")

    # Translate the labels used by the web screen into the canonical ledger vocabulary.
    aliases = {
        "COMPANY_RECEIPT": "COMPANY_RECEIPT",
        "ISSUED": "ISSUE_TO_SALESMAN",
        "ISSUE_TO_SALESMAN": "ISSUE_TO_SALESMAN",
        "RETURNED": "RETURN_FROM_SALESMAN",
        "RETURN_FROM_SALESMAN": "RETURN_FROM_SALESMAN",
        "COMPANY_ADJUSTMENT": "POSITIVE_ADJUSTMENT",
        "POSITIVE_ADJUSTMENT": "POSITIVE_ADJUSTMENT",
        "SALESMAN_ADJUSTMENT": "SALESMAN_POSITIVE_ADJUSTMENT",
        "SALESMAN_POSITIVE_ADJUSTMENT": "SALESMAN_POSITIVE_ADJUSTMENT",
    }
    requested_type = str(req.txn_type or "ISSUE_TO_SALESMAN").upper()
    txn_type = aliases.get(requested_type)
    if not txn_type:
        raise HTTPException(status_code=422, detail=f"Unsupported stock movement type: {requested_type}")
    if txn_type in {"COMPANY_RECEIPT", "POSITIVE_ADJUSTMENT"} and role not in {"OWNER", "OWNER_ADMIN", "PA"}:
        raise HTTPException(status_code=403, detail="Only Owner or PA can change company stock.")
    if txn_type in {"ISSUE_TO_SALESMAN", "RETURN_FROM_SALESMAN", "SALESMAN_POSITIVE_ADJUSTMENT"} and not req.salesman_user_id:
        raise HTTPException(status_code=422, detail="Select a salesman for this stock movement.")
    if role == "SALESMAN" and (txn_type != "RETURN_FROM_SALESMAN" or req.salesman_user_id != user_id):
        raise HTTPException(status_code=403, detail="Salesmen can only record returns for their own assigned stock.")

    now_iso = datetime.utcnow().isoformat()
    stock_txn_id = db.generate_id("SalesmanStockLedger")

    products = db.get_records("Products")
    p_info = next((p for p in products if str(p.get("product_id")) == req.product_id), {})

    if not p_info:
        raise HTTPException(status_code=404, detail="Product not found.")
    sku = str(p_info.get("sku", req.product_id))
    unit = str(p_info.get("selling_unit", "PACKET"))
    pack_weight_g = int(p_info.get("pack_weight_g", 500) or 500)
    ledger = db.get_records("SalesmanStockLedger", fresh=True)
    company_balances, _pairs = balances(ledger)
    if txn_type in {"ISSUE_TO_SALESMAN", "POSITIVE_ADJUSTMENT"} or txn_type == "COMPANY_RECEIPT":
        pass
    if txn_type == "ISSUE_TO_SALESMAN":
        available = company_balances.get(req.product_id, 0)
        if req.quantity > available:
            raise HTTPException(status_code=422, detail=f"Insufficient company stock. Available {available}, requested {req.quantity}.")
    if txn_type == "RETURN_FROM_SALESMAN":
        available = salesman_available(ledger, req.salesman_user_id, req.product_id)
        if req.quantity > available:
            raise HTTPException(status_code=422, detail=f"Insufficient salesman stock to return. Available {available}, requested {req.quantity}.")

    record = {
        "stock_txn_id": stock_txn_id,
        "txn_datetime": now_iso,
        "salesman_user_id": req.salesman_user_id,
        "product_id": req.product_id,
        "sku_snapshot": sku,
        "txn_type": txn_type,
        "quantity": req.quantity,
        "unit": unit,
        "pack_weight_g": pack_weight_g,
        "related_sale_id": "",
        "issued_by_user_id": user_id,
        "received_by_user_id": req.salesman_user_id,
        "confirmed_by_user_id": user_id,
        "reference_id": req.reference_id or "",
        "notes": req.notes or "",
    }
    if not db.append_record("SalesmanStockLedger", record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Stock movement was not saved. Check the Google Sheets connection and retry.")

    db.log_audit(
        actor=user_id,
        action="STOCK_MOVEMENT",
        entity_type="SalesmanStockLedger",
        entity_id=stock_txn_id,
        reason=f"Stock {txn_type}: {req.quantity} {unit} of {sku} for {req.salesman_user_id}"
    )

    return StockTransaction(**record)


class StockDiscrepancyCreate(BaseModel):
    location: str
    product_id: str
    expected_stock: int
    physical_count: int
    reason: str = ""


class StockDiscrepancyReview(BaseModel):
    action: str  # "APPROVE" or "REJECT"
    notes: str = ""


@router.get("/discrepancies")
async def list_stock_discrepancies(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    records = db.get_records("StockDiscrepancies", fresh=True)
    if not is_manager(current_user):
        records = [r for r in records if str(r.get("counted_by_user_id")) == user_id or str(r.get("location")) == user_id]
    return list(reversed(records))


@router.post("/discrepancies", dependencies=[Depends(require_sheets_connection)])
async def submit_stock_discrepancy(req: StockDiscrepancyCreate, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    products = {str(p.get("product_id")): p for p in db.get_records("Products", fresh=True)}
    product = products.get(req.product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {req.product_id} not found.")

    diff = req.physical_count - req.expected_stock
    now_iso = datetime.utcnow().isoformat()
    disc_id = db.generate_id("StockDiscrepancies")

    record = {
        "discrepancy_id": disc_id,
        "discrepancy_date": now_iso[:10],
        "location": req.location,
        "product_id": req.product_id,
        "product_name_snapshot": str(product.get("product_name", req.product_id)),
        "expected_stock": req.expected_stock,
        "physical_count": req.physical_count,
        "difference": diff,
        "reason": req.reason.strip(),
        "counted_by_user_id": user_id,
        "reviewed_by_user_id": "",
        "status": "PENDING_APPROVAL",
        "approved_adjustment": 0,
        "created_at": now_iso,
    }
    if not db.append_record("StockDiscrepancies", record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Could not save stock discrepancy record.")

    db.log_audit(
        user_id,
        "SUBMIT_STOCK_DISCREPANCY",
        "StockDiscrepancies",
        disc_id,
        reason=f"Reported discrepancy of {diff} for {product.get('product_name')} at {req.location}. Reason: {req.reason}",
    )
    return record


@router.post("/discrepancies/{discrepancy_id}/review", dependencies=[Depends(require_sheets_connection)])
async def review_stock_discrepancy(discrepancy_id: str, req: StockDiscrepancyReview, current_user: dict = Depends(get_current_user)):
    if not is_manager(current_user):
        raise HTTPException(status_code=403, detail="Only Owner or PA can approve stock discrepancy adjustments.")

    user_id = str(current_user.get("user_id", ""))
    records = db.get_records("StockDiscrepancies", fresh=True)
    match = next((r for r in records if str(r.get("discrepancy_id")) == discrepancy_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Discrepancy record not found.")

    action = req.action.strip().upper()
    if action not in {"APPROVE", "REJECT"}:
        raise HTTPException(status_code=422, detail="Action must be APPROVE or REJECT.")

    now_iso = datetime.utcnow().isoformat()
    diff = int(match.get("difference", 0) or 0)
    loc = str(match.get("location", ""))
    p_id = str(match.get("product_id", ""))

    if action == "APPROVE" and diff != 0:
        # Create corresponding ledger adjustment so the physical count becomes authoritative
        products = {str(p.get("product_id")): p for p in db.get_records("Products")}
        p_info = products.get(p_id, {})
        sku = str(p_info.get("sku", p_id))
        pack = int(p_info.get("pack_weight_g", 500) or 500)
        unit = str(p_info.get("selling_unit", "PACKET"))

        is_company = loc in {"COMPANY_WAREHOUSE", "FACTORY", "WAREHOUSE", ""}
        txn_type = "POSITIVE_ADJUSTMENT" if diff > 0 else "ISSUE_TO_SALESMAN"
        salesman_target = "" if is_company else loc

        adj_record = {
            "stock_txn_id": db.generate_id("SalesmanStockLedger"),
            "txn_datetime": now_iso,
            "salesman_user_id": salesman_target,
            "product_id": p_id,
            "sku_snapshot": sku,
            "txn_type": "POSITIVE_ADJUSTMENT" if diff > 0 else "RETURN_FROM_SALESMAN",
            "quantity": abs(diff) if diff > 0 else -abs(diff),
            "unit": unit,
            "pack_weight_g": pack,
            "related_sale_id": "",
            "issued_by_user_id": user_id,
            "received_by_user_id": salesman_target,
            "confirmed_by_user_id": user_id,
            "reference_id": f"DISC-{discrepancy_id}",
            "notes": f"Approved physical count adjustment for {discrepancy_id}: {req.notes}".strip(),
        }
        db.append_record("SalesmanStockLedger", adj_record, raise_on_error=True)

    status_str = "APPROVED" if action == "APPROVE" else "REJECTED"
    updated = db.update_record("StockDiscrepancies", "discrepancy_id", discrepancy_id, {
        "status": status_str,
        "reviewed_by_user_id": user_id,
        "approved_adjustment": diff if action == "APPROVE" else 0,
        "reason": f"{match.get('reason', '')} [REVIEW:{status_str}:{user_id}:{req.notes}]".strip(),
    }, raise_on_error=True)
    if not updated:
        raise HTTPException(status_code=503, detail="Could not update discrepancy status.")

    db.log_audit(
        user_id,
        f"{status_str}_STOCK_DISCREPANCY",
        "StockDiscrepancies",
        discrepancy_id,
        reason=f"{status_str} stock discrepancy {discrepancy_id}. Adjustment: {diff if action == 'APPROVE' else 0}. Notes: {req.notes}",
    )
    return {"ok": True, "status": status_str, "discrepancy_id": discrepancy_id}

