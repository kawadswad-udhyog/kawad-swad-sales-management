from datetime import datetime
from typing import List, Dict
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import StockSummaryResponse, StockTransaction, StockIssueCreate, CompanyStockItem, SalesmanStockItem
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection

router = APIRouter(prefix="/api/stock", tags=["Stock"])

@router.get("/summary", response_model=StockSummaryResponse)
async def get_stock_summary(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = current_user.get("role", "").upper()

    products = db.get_records("Products")
    transactions = db.get_records("SalesmanStockLedger")

    # Company stock balance per product
    company_balances: Dict[str, int] = {}
    salesman_balances: Dict[str, Dict[str, int]] = {}

    for prod in products:
        p_id = str(prod.get("product_id"))
        company_balances[p_id] = 0

    for txn in transactions:
        p_id = str(txn.get("product_id", ""))
        s_user = str(txn.get("salesman_user_id", ""))
        t_type = str(txn.get("txn_type", "")).upper()
        qty = int(txn.get("quantity", 0) or 0)

        # Company movements
        if t_type == "COMPANY_RECEIPT":
            company_balances[p_id] = company_balances.get(p_id, 0) + abs(qty)
        elif t_type == "ISSUE_TO_SALESMAN":
            company_balances[p_id] = company_balances.get(p_id, 0) - abs(qty)
            salesman_balances.setdefault(s_user, {})[p_id] = salesman_balances.get(s_user, {}).get(p_id, 0) + abs(qty)
        elif t_type == "RETURN_FROM_SALESMAN":
            company_balances[p_id] = company_balances.get(p_id, 0) + abs(qty)
            salesman_balances.setdefault(s_user, {})[p_id] = salesman_balances.get(s_user, {}).get(p_id, 0) - abs(qty)
        elif t_type in ["SOLD_DELIVERY", "SALE_DELIVERY"]:
            salesman_balances.setdefault(s_user, {})[p_id] = salesman_balances.get(s_user, {}).get(p_id, 0) - abs(qty)
        elif t_type == "POSITIVE_ADJUSTMENT":
            company_balances[p_id] = company_balances.get(p_id, 0) + abs(qty)
        elif t_type == "SALESMAN_POSITIVE_ADJUSTMENT":
            salesman_balances.setdefault(s_user, {})[p_id] = salesman_balances.get(s_user, {}).get(p_id, 0) + abs(qty)

    prod_map = {str(p.get("product_id")): p for p in products}

    company_stock = []
    for p_id, bal in company_balances.items():
        p_info = prod_map.get(p_id, {})
        company_stock.append(CompanyStockItem(
            product_id=p_id,
            sku=str(p_info.get("sku", p_id)),
            product_name=str(p_info.get("product_name", "Papad")),
            current_stock=bal,
            unit=str(p_info.get("selling_unit", "PACKET")),
        ))

    salesman_stock = []
    for s_user, p_bals in salesman_balances.items():
        if role not in ["OWNER", "OWNER_ADMIN", "PA"] and s_user != user_id:
            continue
        for p_id, bal in p_bals.items():
            p_info = prod_map.get(p_id, {})
            salesman_stock.append(SalesmanStockItem(
                salesman_user_id=s_user,
                product_id=p_id,
                sku=str(p_info.get("sku", p_id)),
                product_name=str(p_info.get("product_name", "Papad")),
                current_stock=bal,
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
