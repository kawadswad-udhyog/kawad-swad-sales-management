from datetime import datetime
from typing import List, Dict
from fastapi import APIRouter, HTTPException, status, Depends
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
