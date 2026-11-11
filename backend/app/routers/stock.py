import json
import collections
import contextlib
from datetime import datetime, timezone
from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel
from app.models import (
    StockSummaryResponse, StockTransaction, StockIssueCreate, CompanyStockItem, SalesmanStockItem,
    VanLoadingItem, VanLoadingPassCreate, VanLoadingPassAccept, VanLoadingPassDiscrepancy, VanLoadingPass,
)
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import is_manager, is_owner, role_of
from app.stock_math import balances, salesman_available
from app.timeutil import business_today, now_iso
from app.accounting.customer_ledger import CrossProcessLock
from app.calculations import (
    calculate_consolidated_finished_goods_register,
    calculate_finished_stock_balance,
)

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
    qty = req.quantity if req.quantity is not None else (req.quantity_packets or 0)
    req.quantity = qty
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

    now_iso = datetime.now(timezone.utc).isoformat()
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
            # Check factory/warehouse finished stock in ProductionStockLedger / PackagingBatches
            prod_stock = sum(int(float(p.get("quantity_packets", 0) or 0)) for p in db.get_records("ProductionStockLedger", fresh=False) if str(p.get("product_id")) == req.product_id and str(p.get("movement_type")).upper() == "PACKETS_PACKAGED")
            pack_stock = sum(int(float(p.get("packets_produced") or p.get("packets_200g") or p.get("total_packets") or 0)) for p in db.get_records("PackagingBatches", fresh=False) if str(p.get("product_id")) == req.product_id and str(p.get("status", "")).upper() not in {"INCOMPLETE", "FAILED", "REJECTED"})
            total_avail = max(available, prod_stock, pack_stock)
            if req.quantity > total_avail:
                raise HTTPException(status_code=422, detail=f"Insufficient company stock. Available {total_avail}, requested {req.quantity}.")
    if txn_type == "RETURN_FROM_SALESMAN":
        available = salesman_available(ledger, req.salesman_user_id, req.product_id)
        if req.quantity > available:
            raise HTTPException(status_code=422, detail=f"Insufficient salesman stock to return. Available {available}, requested {req.quantity}.")

    record = {
        "stock_txn_id": stock_txn_id,
        "movement_id": stock_txn_id,
        "txn_datetime": now_iso,
        "salesman_user_id": req.salesman_user_id,
        "product_id": req.product_id,
        "sku_snapshot": sku,
        "txn_type": txn_type,
        "quantity": req.quantity,
        "quantity_packets": req.quantity,
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

    # Also sync StockMovements sheet for canonical movement tracking
    try:
        mvt_record = {
            "movement_id": stock_txn_id,
            "txn_datetime": now_iso,
            "salesman_user_id": req.salesman_user_id,
            "product_id": req.product_id,
            "sku_snapshot": sku,
            "movement_type": txn_type,
            "txn_type": txn_type,
            "quantity": req.quantity,
            "quantity_packets": req.quantity,
            "unit": unit,
            "pack_weight_g": pack_weight_g,
            "reference_id": req.reference_id or "",
            "notes": req.notes or "",
        }
        db.append_record("StockMovements", mvt_record)
    except Exception:
        pass

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
    now_iso = datetime.now(timezone.utc).isoformat()
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

    now_iso = datetime.now(timezone.utc).isoformat()
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


class PhysicalStockReconcile(BaseModel):
    product_id: str
    location: str  # "FACTORY", "WAREHOUSE", or a salesman user_id like "USR-SALES-01"
    physical_count: int
    reason: str
    notes: str = ""


@router.get("/finished-goods-register")
async def get_stock_finished_goods_register(current_user: dict = Depends(get_current_user)):
    """
    Consolidated Finished Goods Stock Register across Factory, Warehouse, and Salesmen.
    """
    if not is_manager(current_user):
        raise HTTPException(status_code=403, detail="Only Owner or PA can view the Finished Goods Stock Register.")
    products_records = db.get_records("Products", fresh=True)
    production_ledger = db.get_records("ProductionStockLedger", fresh=True)
    salesman_ledger = db.get_records("SalesmanStockLedger", fresh=True)
    users_records = db.get_records("Users", fresh=True)
    sale_items = db.get_records("SaleItems", fresh=True)

    return calculate_consolidated_finished_goods_register(
        products_master=products_records,
        production_stock_ledger=production_ledger,
        salesman_stock_ledger=salesman_ledger,
        users_master=users_records,
        sale_items_records=sale_items,
    )


@router.post("/reconcile-opening", dependencies=[Depends(require_sheets_connection)])
async def reconcile_physical_stock(req: PhysicalStockReconcile, current_user: dict = Depends(get_current_user)):
    """
    Authorized Physical Stock Reconciliation & Opening Balance Entry.
    Compares physical count against recorded ledger balance for the selected location
    (Factory, Warehouse, or Salesman) and writes an audited adjustment without duplicate entries.
    """
    if not is_manager(current_user):
        raise HTTPException(status_code=403, detail="Only Owner or PA can perform physical stock reconciliation.")

    actor = str(current_user.get("user_id", ""))
    products = {str(p.get("product_id")): p for p in db.get_records("Products", fresh=True)}
    product = products.get(req.product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {req.product_id} not found.")

    if req.physical_count < 0:
        raise HTTPException(status_code=422, detail="Physical count cannot be negative.")
    if not req.reason.strip():
        raise HTTPException(status_code=422, detail="An explanation/reason is required for physical stock reconciliation.")

    sku = str(product.get("sku", req.product_id))
    p_name = str(product.get("product_name", req.product_id))
    pack_weight = int(float(product.get("pack_weight_g", 0) or 0))
    loc = req.location.strip().upper()
    now_iso = datetime.now(timezone.utc).isoformat()

    if loc == "FACTORY":
        prod_ledger = db.get_records("ProductionStockLedger", fresh=True)
        current_factory = calculate_finished_stock_balance(prod_ledger, req.product_id).get(req.product_id, 0)
        diff = req.physical_count - current_factory
        if diff == 0:
            return {
                "ok": True,
                "message": f"Physical count matches recorded factory stock ({current_factory} packets). No adjustment needed.",
                "adjusted": 0,
                "current_stock": current_factory,
            }

        mvt_id = db.generate_id("ProductionStockLedger")
        row = {
            "movement_id": mvt_id,
            "txn_datetime": now_iso,
            "movement_type": "PACKET_ADJUSTMENT",
            "quantity_kg": 0,
            "quantity_packets": diff,
            "channel": "FACTORY_FINISHED",
            "product_id": req.product_id,
            "bulk_product_key": p_name.strip().lower(),
            "product_name_snapshot": p_name,
            "sku_snapshot": sku,
            "pack_weight_g": pack_weight,
            "reference_id": f"PHYS_REC_{now_iso[:10].replace('-', '')}",
            "created_by": actor,
            "notes": f"Physical reconciliation by {actor}: {req.reason}. {req.notes}".strip(),
        }
        if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
            raise HTTPException(status_code=503, detail="Could not record factory stock adjustment.")

        db.log_audit(
            actor,
            "RECONCILE_FACTORY_STOCK",
            "ProductionStockLedger",
            mvt_id,
            reason=f"Factory {sku} reconciled from {current_factory} to {req.physical_count} ({diff:+d}). Reason: {req.reason}",
        )
        return {
            "ok": True,
            "location": "FACTORY",
            "product_id": req.product_id,
            "sku": sku,
            "expected_balance": current_factory,
            "previous_stock": current_factory,
            "physical_count": req.physical_count,
            "new_stock": req.physical_count,
            "variance": diff,
            "adjustment": diff,
            "adjustment_txn_id": mvt_id,
            "final_balance": req.physical_count,
            "reason": req.reason,
            "reconciled_by": actor,
            "message": f"Factory stock reconciled to {req.physical_count} packets ({diff:+d} packets adjustment).",
        }

    # Warehouse or Salesman
    salesman_ledger = db.get_records("SalesmanStockLedger", fresh=True)
    company_bal, salesman_bal = balances(salesman_ledger)

    if loc in {"WAREHOUSE", "COMPANY_WAREHOUSE", "COMPANY"}:
        current_wh = company_bal.get(req.product_id, 0)
        diff = req.physical_count - current_wh
        if diff == 0:
            return {
                "ok": True,
                "message": f"Physical count matches recorded warehouse stock ({current_wh} packets). No adjustment needed.",
                "adjusted": 0,
                "current_stock": current_wh,
            }

        txn_type = "POSITIVE_ADJUSTMENT" if diff > 0 else "NEGATIVE_ADJUSTMENT"
        txn_id = db.generate_id("SalesmanStockLedger")
        row = {
            "stock_txn_id": txn_id,
            "txn_datetime": now_iso,
            "salesman_user_id": "",
            "product_id": req.product_id,
            "sku_snapshot": sku,
            "txn_type": txn_type,
            "quantity": abs(diff),
            "unit": str(product.get("selling_unit", "PACKET")),
            "pack_weight_g": pack_weight,
            "related_sale_id": "",
            "issued_by_user_id": actor,
            "received_by_user_id": "WAREHOUSE",
            "confirmed_by_user_id": actor,
            "reference_id": f"PHYS_REC_{now_iso[:10].replace('-', '')}",
            "notes": f"Warehouse physical reconciliation: {req.reason}. {req.notes}".strip(),
        }
        if not db.append_record("SalesmanStockLedger", row, raise_on_error=True):
            raise HTTPException(status_code=503, detail="Could not record warehouse stock adjustment.")

        db.log_audit(
            actor,
            "RECONCILE_WAREHOUSE_STOCK",
            "SalesmanStockLedger",
            txn_id,
            reason=f"Warehouse {sku} reconciled from {current_wh} to {req.physical_count} ({diff:+d}). Reason: {req.reason}",
        )
        return {
            "ok": True,
            "location": "WAREHOUSE",
            "product_id": req.product_id,
            "sku": sku,
            "expected_balance": current_wh,
            "previous_stock": current_wh,
            "physical_count": req.physical_count,
            "new_stock": req.physical_count,
            "variance": diff,
            "adjustment": diff,
            "adjustment_txn_id": txn_id,
            "final_balance": req.physical_count,
            "reason": req.reason,
            "reconciled_by": actor,
            "message": f"Warehouse stock reconciled to {req.physical_count} packets ({diff:+d} packets adjustment).",
        }

    # Otherwise, loc is salesman_user_id (e.g. USR-SALES-01)
    salesman_id = req.location.strip()
    current_s = salesman_available(salesman_ledger, salesman_id, req.product_id)
    diff = req.physical_count - current_s
    if diff == 0:
        return {
            "ok": True,
            "message": f"Physical count matches recorded salesman stock ({current_s} packets). No adjustment needed.",
            "adjusted": 0,
            "current_stock": current_s,
        }

    txn_type = "SALESMAN_POSITIVE_ADJUSTMENT" if diff > 0 else "SALESMAN_NEGATIVE_ADJUSTMENT"
    txn_id = db.generate_id("SalesmanStockLedger")
    row = {
        "stock_txn_id": txn_id,
        "txn_datetime": now_iso,
        "salesman_user_id": salesman_id,
        "product_id": req.product_id,
        "sku_snapshot": sku,
        "txn_type": txn_type,
        "quantity": abs(diff),
        "unit": str(product.get("selling_unit", "PACKET")),
        "pack_weight_g": pack_weight,
        "related_sale_id": "",
        "issued_by_user_id": actor,
        "received_by_user_id": salesman_id,
        "confirmed_by_user_id": actor,
        "reference_id": f"PHYS_REC_{now_iso[:10].replace('-', '')}",
        "notes": f"Salesman {salesman_id} physical reconciliation: {req.reason}. {req.notes}".strip(),
    }
    if not db.append_record("SalesmanStockLedger", row, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Could not record salesman stock adjustment.")

    db.log_audit(
        actor,
        "RECONCILE_SALESMAN_STOCK",
        "SalesmanStockLedger",
        txn_id,
        reason=f"Salesman {salesman_id} {sku} reconciled from {current_s} to {req.physical_count} ({diff:+d}). Reason: {req.reason}",
    )
    return {
        "ok": True,
        "location": salesman_id,
        "product_id": req.product_id,
        "sku": sku,
        "expected_balance": current_s,
        "previous_stock": current_s,
        "physical_count": req.physical_count,
        "new_stock": req.physical_count,
        "variance": diff,
        "adjustment": diff,
        "adjustment_txn_id": txn_id,
        "final_balance": req.physical_count,
        "reason": req.reason,
        "reconciled_by": actor,
        "message": f"Salesman {salesman_id} stock reconciled to {req.physical_count} packets ({diff:+d} packets adjustment).",
    }


@router.get("/bulk-batches")
async def get_bulk_batch_tracking(product_id: str = None, current_user: dict = Depends(get_current_user)):
    """
    Get detailed breakdown of available bulk stock by production batch ID,
    including original production date, remaining quantity, unit cost, and cost status.
    """
    from app.calculations.inventory import calculate_batch_bulk_balances
    ledger = db.get_records("ProductionStockLedger", fresh=True)
    batches_data = db.get_records("ProductionBatches", fresh=True)
    return calculate_batch_bulk_balances(ledger, batches_data, product_id)


# Compatibility alias for acceptance tests
issue_stock = record_stock_movement


# ==============================================================================
# PHASE 2A.1: MORNING VAN LOADING PASS WORKFLOW
# ==============================================================================

def _to_van_loading_pass(record: dict) -> VanLoadingPass:
    items_raw = record.get("items_json") or "[]"
    try:
        items_data = json.loads(items_raw) if isinstance(items_raw, str) else (items_raw or [])
    except Exception:
        items_data = []
    items = [VanLoadingItem(**it) for it in items_data]
    return VanLoadingPass(
        pass_id=str(record.get("pass_id", "")),
        pass_number=str(record.get("pass_number", "")),
        loading_date=str(record.get("loading_date", "")),
        van_number=str(record.get("van_number", "")),
        salesman_user_id=str(record.get("salesman_user_id", "")),
        salesman_name=str(record.get("salesman_name", "")),
        created_by_user_id=str(record.get("created_by_user_id", "")),
        created_by_name=str(record.get("created_by_name", "")),
        status=str(record.get("status", "PENDING_ACCEPTANCE")),
        total_skus=int(record.get("total_skus", 0) or len(items)),
        total_packets=int(record.get("total_packets", 0) or sum(i.quantity for i in items)),
        total_weight_kg=float(record.get("total_weight_kg", 0.0) or sum(i.weight_kg or 0.0 for i in items)),
        items=items,
        created_at=str(record.get("created_at", "")),
        accepted_at=str(record.get("accepted_at", "")),
        accepted_by_user_id=str(record.get("accepted_by_user_id", "")),
        discrepancy_notes=str(record.get("discrepancy_notes", "")),
        idempotency_key=str(record.get("idempotency_key", "")),
        notes=str(record.get("notes", "")),
    )


def _get_available_warehouse_stock(product_id: str, company_balances: dict) -> int:
    """
    Authoritative transferable finished-goods warehouse stock.
    Strictly derived from the canonical SalesmanStockLedger company balance.
    Production and packaging totals do NOT silently override the canonical ledger.
    """
    return int(company_balances.get(str(product_id), 0) or 0)


@router.post("/loading-passes", response_model=VanLoadingPass, dependencies=[Depends(require_sheets_connection)])
async def create_van_loading_pass(req: VanLoadingPassCreate, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    role = role_of(current_user)

    # Rule 1: Only authorized users can create loading passes (Owner, PA, Manager, Storekeeper, Dispatch)
    allowed_creators = {"OWNER", "OWNER_ADMIN", "ADMIN", "PA", "DISPATCH", "STOREKEEPER", "WAREHOUSE", "MANAGER"}
    if not is_manager(current_user) and role not in allowed_creators:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to create van loading passes. Contact the warehouse manager or owner."
        )

    if not req.items:
        raise HTTPException(status_code=422, detail="At least one product item must be loaded.")

    van_num = req.van_number.strip().upper()
    salesman_uid = req.salesman_user_id.strip()

    # Block 5: Creation Idempotency
    # If idempotency key provided, check across processes
    idem_key = req.idempotency_key.strip() if req.idempotency_key else None
    if idem_key:
        with CrossProcessLock("van_loading_create", idem_key):
            existing_passes = db.get_records("VanLoadingPasses", fresh=True)
            for ep in existing_passes:
                if str(ep.get("idempotency_key", "")).strip() == idem_key:
                    # Compare payload parameters:
                    ep_van = str(ep.get("van_number", "")).strip().upper()
                    req_van = van_num
                    ep_salesman = str(ep.get("salesman_user_id", "")).strip()
                    req_salesman = salesman_uid

                    try:
                        ep_items_raw = ep.get("items_json") or "[]"
                        ep_items_data = json.loads(ep_items_raw) if isinstance(ep_items_raw, str) else ep_items_raw
                    except Exception:
                        ep_items_data = []

                    ep_item_map = {str(it.get("product_id")): int(it.get("quantity", 0)) for it in ep_items_data}
                    req_item_map = collections.defaultdict(int)
                    for it in req.items:
                        req_item_map[str(it.product_id)] += int(it.quantity)

                    if ep_van != req_van or ep_salesman != req_salesman or ep_item_map != dict(req_item_map):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Conflict: Idempotency key reused with conflicting request payload parameters."
                        )
                    return _to_van_loading_pass(ep)

    # Verify salesman user exists
    users = {str(u.get("user_id")): u for u in db.get_records("Users", fresh=True)}
    salesman_user = users.get(salesman_uid)
    if not salesman_user:
        raise HTTPException(status_code=404, detail=f"Assigned salesman {salesman_uid} not found in system.")
    salesman_name = str(salesman_user.get("full_name") or salesman_uid)

    # Verify products and check canonical warehouse stock availability
    products = {str(p.get("product_id")): p for p in db.get_records("Products", fresh=True)}
    ledger = db.get_records("SalesmanStockLedger", fresh=True)
    company_balances, _ = balances(ledger)

    # Consolidate items by product_id
    consolidated_items: Dict[str, VanLoadingItem] = {}
    for itm in req.items:
        p_info = products.get(itm.product_id)
        if not p_info:
            raise HTTPException(status_code=404, detail=f"Product {itm.product_id} not found.")

        if itm.quantity <= 0:
            raise HTTPException(status_code=422, detail=f"Quantity for {p_info.get('product_name')} must be greater than zero.")

        sku = str(p_info.get("sku", itm.product_id))
        p_name = str(p_info.get("product_name", sku))
        pack_weight_g = int(float(p_info.get("pack_weight_g", 500) or 500))
        weight_kg = round(itm.quantity * pack_weight_g / 1000.0, 3)

        if itm.product_id in consolidated_items:
            existing = consolidated_items[itm.product_id]
            existing.quantity += itm.quantity
            existing.weight_kg = round(existing.weight_kg + weight_kg, 3)
            if itm.notes:
                existing.notes = f"{existing.notes}; {itm.notes}".strip("; ")
        else:
            consolidated_items[itm.product_id] = VanLoadingItem(
                product_id=itm.product_id,
                product_name=p_name,
                sku=sku,
                pack_weight_g=pack_weight_g,
                quantity=itm.quantity,
                weight_kg=weight_kg,
                notes=itm.notes or "",
            )

    hydrated_items = list(consolidated_items.values())
    total_packets = 0
    total_weight_kg = 0.0

    # Rule 3: Authoritative stock check; warehouse stock cannot become negative
    for itm in hydrated_items:
        available_wh = _get_available_warehouse_stock(itm.product_id, company_balances)
        if itm.quantity > available_wh:
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient warehouse stock for {itm.product_name} ({itm.sku}). Available: {available_wh} packets, Requested: {itm.quantity} packets."
            )
        total_packets += itm.quantity
        total_weight_kg += itm.weight_kg

    loading_date = (req.loading_date or business_today()).strip()
    date_compact = loading_date.replace("-", "")

    # Atomic sequential pass number generation
    creator_name = str(current_user.get("full_name") or user_id)
    now = now_iso()

    with CrossProcessLock("van_loading_seq", date_compact):
        pass_id = db.generate_id("VanLoadingPasses")
        existing_passes = db.get_records("VanLoadingPasses", fresh=True)
        today_passes = [p for p in existing_passes if str(p.get("loading_date", "")).replace("-", "") == date_compact]
        seq = len(today_passes) + 1
        pass_number = f"LP-{date_compact}-{seq:03d}"

        record = {
            "pass_id": pass_id,
            "pass_number": pass_number,
            "loading_date": loading_date,
            "van_number": van_num,
            "salesman_user_id": salesman_uid,
            "salesman_name": salesman_name,
            "created_by_user_id": user_id,
            "created_by_name": creator_name,
            "status": "PENDING_ACCEPTANCE",
            "total_skus": len(hydrated_items),
            "total_packets": total_packets,
            "total_weight_kg": round(total_weight_kg, 3),
            "items_json": json.dumps([i.dict() for i in hydrated_items]),
            "created_at": now,
            "accepted_at": "",
            "accepted_by_user_id": "",
            "discrepancy_notes": "",
            "idempotency_key": req.idempotency_key or "",
            "notes": req.notes or "",
        }

        if not db.append_record("VanLoadingPasses", record, raise_on_error=True):
            raise HTTPException(status_code=503, detail="Failed to save Van Loading Pass to persistent storage.")

    db.log_audit(
        actor=user_id,
        action="CREATE_VAN_LOADING_PASS",
        entity_type="VanLoadingPasses",
        entity_id=pass_id,
        reason=f"Created morning loading pass {pass_number} for Van {van_num} ({total_packets} pkts, {round(total_weight_kg, 2)} kg) assigned to {salesman_name} ({salesman_uid})."
    )

    return _to_van_loading_pass(record)


@router.get("/loading-passes", response_model=List[VanLoadingPass])
async def list_van_loading_passes(
    salesman_id: Optional[str] = None,
    date: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: dict = Depends(get_current_user)
):
    user_id = str(current_user.get("user_id", ""))
    role = role_of(current_user)
    is_sales_role = role in {"SALESMAN", "FIELD_SALESMAN"}

    records = db.get_records("VanLoadingPasses", fresh=True)
    results = []

    for r in records:
        s_user = str(r.get("salesman_user_id", "")).strip()
        # Salesmen can only view their own loading passes
        if is_sales_role and s_user != user_id:
            continue
        if salesman_id and s_user != salesman_id.strip():
            continue
        if date and str(r.get("loading_date", "")).strip() != date.strip():
            continue
        if status_filter and str(r.get("status", "")).strip().upper() != status_filter.strip().upper():
            continue

        results.append(_to_van_loading_pass(r))

    results.reverse()
    return results


@router.get("/loading-passes/{pass_id_or_number}", response_model=VanLoadingPass)
async def get_van_loading_pass(pass_id_or_number: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    role = role_of(current_user)
    is_sales_role = role in {"SALESMAN", "FIELD_SALESMAN"}

    target = pass_id_or_number.strip()
    records = db.get_records("VanLoadingPasses", fresh=True)
    match = next((r for r in records if str(r.get("pass_id", "")).strip() == target or str(r.get("pass_number", "")).strip() == target), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Van loading pass '{target}' not found.")

    s_user = str(match.get("salesman_user_id", "")).strip()
    if is_sales_role and s_user != user_id:
        raise HTTPException(status_code=403, detail="You can only view loading passes assigned to your own van.")

    return _to_van_loading_pass(match)


class LoadingPassActionReq(BaseModel):
    notes: Optional[str] = ""
    discrepancy_notes: Optional[str] = ""
    idempotency_key: Optional[str] = None


@router.post("/loading-passes/{pass_id_or_number}/accept", response_model=VanLoadingPass, dependencies=[Depends(require_sheets_connection)])
async def accept_van_loading_pass(pass_id_or_number: str, req: Optional[LoadingPassActionReq] = None, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    role = role_of(current_user)
    is_sales_role = role in {"SALESMAN", "FIELD_SALESMAN"}

    target = pass_id_or_number.strip()
    records = db.get_records("VanLoadingPasses", fresh=True)
    match = next((r for r in records if str(r.get("pass_id", "")).strip() == target or str(r.get("pass_number", "")).strip() == target), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Van loading pass '{target}' not found.")

    pass_id = str(match.get("pass_id"))
    assigned_salesman = str(match.get("salesman_user_id", "")).strip()

    # Rule 2 & 10: Salesmen can accept only their assigned van's loading pass
    if is_sales_role and assigned_salesman != user_id:
        raise HTTPException(
            status_code=403,
            detail=f"Unauthorized: You cannot accept a loading pass assigned to another salesman ({assigned_salesman})."
        )

    # Decode items to determine products for safe per-product isolation and ordered locking
    items_raw = match.get("items_json") or "[]"
    try:
        items_data = json.loads(items_raw) if isinstance(items_raw, str) else (items_raw or [])
    except Exception:
        items_data = []
    items = [VanLoadingItem(**it) for it in items_data]
    sorted_pids = sorted(list({str(it.product_id) for it in items}))

    # Multi-resource locking:
    # 1. Shared pass-level state-transition lock ("van_loading_pass", pass_id)
    # 2. Per-product stock locks in strictly sorted order ("stock_product", pid) to prevent inter-pass race conditions & deadlocks
    with contextlib.ExitStack() as stack:
        stack.enter_context(CrossProcessLock("van_loading_pass", pass_id))
        for pid in sorted_pids:
            stack.enter_context(CrossProcessLock("stock_product", pid))

        # Refresh state inside the lock
        fresh_passes = db.get_records("VanLoadingPasses", fresh=True)
        curr = next((p for p in fresh_passes if str(p.get("pass_id")) == pass_id), None)
        if not curr:
            raise HTTPException(status_code=404, detail="Van loading pass not found.")

        current_status = str(curr.get("status", "")).strip().upper()

        # Rule 4 & 5: Duplicate requests must be idempotent; van stock cannot be credited twice
        if current_status == "ACCEPTED":
            return _to_van_loading_pass(curr)

        # Rule 6 & 9: Completed, cancelled, or discrepant loading passes cannot be accepted
        if current_status == "CANCELLED":
            raise HTTPException(status_code=422, detail="Cannot accept a cancelled loading pass.")

        if current_status == "DISCREPANCY_REPORTED":
            raise HTTPException(
                status_code=422,
                detail="Cannot accept a loading pass with a reported discrepancy. Discrepancy must be resolved first."
            )

        pass_num = str(curr.get("pass_number"))
        van_num = str(curr.get("van_number"))
        creator_uid = str(curr.get("created_by_user_id"))

        # Refresh canonical SalesmanStockLedger inside the lock
        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        transferred_by_prod = collections.defaultdict(int)
        for tx in ledger:
            if str(tx.get("reference_id", "")).strip() == pass_num and str(tx.get("txn_type", "")).upper() == "ISSUE_TO_SALESMAN":
                transferred_by_prod[str(tx.get("product_id"))] += int(float(tx.get("quantity", 0) or 0))

        # Track movement completion per product
        untransferred_items = []
        for itm in items:
            already = transferred_by_prod.get(itm.product_id, 0)
            if already < itm.quantity:
                remaining = itm.quantity - already
                untransferred_items.append((itm, remaining))

        if untransferred_items:
            # Re-verify authoritative warehouse stock availability for untransferred items
            company_balances, _ = balances(ledger)
            for itm, remaining_qty in untransferred_items:
                avail_wh = _get_available_warehouse_stock(itm.product_id, company_balances)
                if remaining_qty > avail_wh:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Cannot complete transfer: Warehouse stock for {itm.product_name or itm.sku} is no longer sufficient (Available: {avail_wh}, Required: {remaining_qty})."
                    )

            now = now_iso()
            for itm, qty_to_transfer in untransferred_items:
                stk_id = db.generate_id("SalesmanStockLedger")
                stk_record = {
                    "stock_txn_id": stk_id,
                    "movement_id": stk_id,
                    "txn_datetime": now,
                    "salesman_user_id": assigned_salesman,
                    "product_id": itm.product_id,
                    "sku_snapshot": itm.sku or itm.product_id,
                    "txn_type": "ISSUE_TO_SALESMAN",
                    "quantity": qty_to_transfer,
                    "quantity_packets": qty_to_transfer,
                    "unit": "PACKET",
                    "pack_weight_g": itm.pack_weight_g or 500,
                    "related_sale_id": "",
                    "issued_by_user_id": creator_uid,
                    "received_by_user_id": assigned_salesman,
                    "confirmed_by_user_id": user_id,
                    "reference_id": pass_num,
                    "notes": f"Van Loading Pass {pass_num} for Van {van_num}",
                }
                try:
                    if not db.append_record("SalesmanStockLedger", stk_record, raise_on_error=True):
                        raise HTTPException(status_code=503, detail=f"Failed to record stock movement for {itm.product_name} in SalesmanStockLedger.")
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(status_code=503, detail=f"Failed to record stock movement for {itm.product_name} in SalesmanStockLedger: {exc}")

        # Post-transfer complete verification: Every expected product movement must be verified
        verified_ledger = db.get_records("SalesmanStockLedger", fresh=True)
        verified_by_prod = collections.defaultdict(int)
        for tx in verified_ledger:
            if str(tx.get("reference_id", "")).strip() == pass_num and str(tx.get("txn_type", "")).upper() == "ISSUE_TO_SALESMAN":
                verified_by_prod[str(tx.get("product_id"))] += int(float(tx.get("quantity", 0) or 0))

        for itm in items:
            total_done = verified_by_prod.get(itm.product_id, 0)
            if total_done < itm.quantity:
                raise HTTPException(
                    status_code=503,
                    detail=f"Incomplete transfer: Verified {total_done} of {itm.quantity} packets for {itm.product_name}. Pass remains pending."
                )

        # Update VanLoadingPasses status to ACCEPTED
        action_notes = (req.notes if req else "") or ""
        now = now_iso()
        update_payload = {
            "status": "ACCEPTED",
            "accepted_at": now,
            "accepted_by_user_id": user_id,
            "notes": f"{curr.get('notes', '')} [Accepted by {user_id} at {now}{': ' + action_notes if action_notes else ''}]".strip(),
        }
        try:
            if not db.update_record("VanLoadingPasses", "pass_id", pass_id, update_payload, raise_on_error=True):
                raise HTTPException(status_code=503, detail="Failed to update loading pass status to ACCEPTED.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Failed to update loading pass status to ACCEPTED: {exc}")

        curr.update(update_payload)

        db.log_audit(
            actor=user_id,
            action="ACCEPT_VAN_LOADING_PASS",
            entity_type="VanLoadingPasses",
            entity_id=pass_id,
            reason=f"Salesman {assigned_salesman} accepted van loading pass {pass_num} ({curr.get('total_packets')} packets) for Van {van_num}."
        )

        return _to_van_loading_pass(curr)


@router.post("/loading-passes/{pass_id_or_number}/discrepancy", response_model=VanLoadingPass, dependencies=[Depends(require_sheets_connection)])
async def report_van_loading_discrepancy(pass_id_or_number: str, req: VanLoadingPassDiscrepancy, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    role = role_of(current_user)
    is_sales_role = role in {"SALESMAN", "FIELD_SALESMAN"}

    target = pass_id_or_number.strip()
    records = db.get_records("VanLoadingPasses", fresh=True)
    match = next((r for r in records if str(r.get("pass_id", "")).strip() == target or str(r.get("pass_number", "")).strip() == target), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Van loading pass '{target}' not found.")

    assigned_salesman = str(match.get("salesman_user_id", "")).strip()
    if is_sales_role and assigned_salesman != user_id:
        raise HTTPException(status_code=403, detail="You can only report discrepancies on your assigned van's loading pass.")

    pass_id = str(match.get("pass_id"))

    # Shared pass-level state-transition lock
    with CrossProcessLock("van_loading_pass", pass_id):
        fresh_passes = db.get_records("VanLoadingPasses", fresh=True)
        curr = next((p for p in fresh_passes if str(p.get("pass_id")) == pass_id), None)
        if not curr:
            raise HTTPException(status_code=404, detail="Van loading pass not found.")

        curr_status = str(curr.get("status", "")).strip().upper()
        if curr_status == "ACCEPTED":
            raise HTTPException(
                status_code=422,
                detail="Loading pass has already been accepted and stock transferred. Cannot report loading discrepancy."
            )
        if curr_status == "CANCELLED":
            raise HTTPException(
                status_code=422,
                detail="Cannot report discrepancy on a cancelled loading pass."
            )
        if curr_status == "DISCREPANCY_REPORTED":
            return _to_van_loading_pass(curr)

        discrepancy_text = req.discrepancy_notes.strip()
        if not discrepancy_text:
            raise HTTPException(status_code=422, detail="Discrepancy notes are required.")

        now = now_iso()
        pass_num = str(curr.get("pass_number"))
        van_num = str(curr.get("van_number"))

        # Durable discrepancy persistence: Record in StockDiscrepancies FIRST
        disc_id = db.generate_id("StockDiscrepancies")
        disc_row = {
            "discrepancy_id": disc_id,
            "discrepancy_date": business_today(),
            "location": f"VAN_{van_num}",
            "product_id": "",
            "product_name_snapshot": f"Van Loading Discrepancy - {pass_num}",
            "expected_stock": curr.get("total_packets", 0),
            "physical_count": 0,
            "difference": 0,
            "reason": f"Discrepancy on {pass_num} for Van {van_num}: {discrepancy_text}",
            "counted_by_user_id": user_id,
            "reviewed_by_user_id": "",
            "status": "PENDING_APPROVAL",
            "approved_adjustment": 0,
            "created_at": now,
        }
        try:
            if not db.append_record("StockDiscrepancies", disc_row, raise_on_error=True):
                raise HTTPException(status_code=503, detail="Failed to persist stock discrepancy record.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Failed to persist stock discrepancy record: {exc}")

        update_payload = {
            "status": "DISCREPANCY_REPORTED",
            "discrepancy_notes": discrepancy_text,
            "notes": f"{curr.get('notes', '')} [Discrepancy reported by {user_id} at {now}: {discrepancy_text}]".strip(),
        }
        try:
            if not db.update_record("VanLoadingPasses", "pass_id", pass_id, update_payload, raise_on_error=True):
                raise HTTPException(status_code=503, detail="Failed to update loading pass status to DISCREPANCY_REPORTED.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Failed to update loading pass status to DISCREPANCY_REPORTED: {exc}")

        curr.update(update_payload)

        db.log_audit(
            actor=user_id,
            action="REPORT_VAN_LOADING_DISCREPANCY",
            entity_type="VanLoadingPasses",
            entity_id=pass_id,
            reason=f"Discrepancy on loading pass {pass_num} reported by {user_id}: {discrepancy_text}"
        )

        return _to_van_loading_pass(curr)


@router.post("/loading-passes/{pass_id_or_number}/cancel", response_model=VanLoadingPass, dependencies=[Depends(require_sheets_connection)])
async def cancel_van_loading_pass(pass_id_or_number: str, req: Optional[LoadingPassActionReq] = None, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))

    target = pass_id_or_number.strip()
    records = db.get_records("VanLoadingPasses", fresh=True)
    match = next((r for r in records if str(r.get("pass_id", "")).strip() == target or str(r.get("pass_number", "")).strip() == target), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Van loading pass '{target}' not found.")

    creator_uid = str(match.get("created_by_user_id", "")).strip()
    if not is_manager(current_user) and creator_uid != user_id:
        raise HTTPException(status_code=403, detail="Only the creator or a manager can cancel this loading pass.")

    pass_id = str(match.get("pass_id"))

    # Shared pass-level state-transition lock
    with CrossProcessLock("van_loading_pass", pass_id):
        fresh_passes = db.get_records("VanLoadingPasses", fresh=True)
        curr = next((p for p in fresh_passes if str(p.get("pass_id")) == pass_id), None)
        if not curr:
            raise HTTPException(status_code=404, detail="Van loading pass not found.")

        curr_status = str(curr.get("status", "")).strip().upper()
        if curr_status == "ACCEPTED":
            raise HTTPException(
                status_code=422,
                detail="Cannot cancel an accepted loading pass. Stock has already been transferred; an authorized return is required."
            )
        if curr_status == "CANCELLED":
            return _to_van_loading_pass(curr)

        cancel_reason = (req.notes if req else "") or "Cancelled by user"
        now = now_iso()
        update_payload = {
            "status": "CANCELLED",
            "notes": f"{curr.get('notes', '')} [Cancelled by {user_id} at {now}: {cancel_reason}]".strip(),
        }
        try:
            if not db.update_record("VanLoadingPasses", "pass_id", pass_id, update_payload, raise_on_error=True):
                raise HTTPException(status_code=503, detail="Failed to update loading pass status to CANCELLED.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Failed to update loading pass status to CANCELLED: {exc}")

        curr.update(update_payload)

        db.log_audit(
            actor=user_id,
            action="CANCEL_VAN_LOADING_PASS",
            entity_type="VanLoadingPasses",
            entity_id=pass_id,
            reason=f"Cancelled van loading pass {curr.get('pass_number')}: {cancel_reason}"
        )

        return _to_van_loading_pass(curr)




