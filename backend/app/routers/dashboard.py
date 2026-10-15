from datetime import date
from fastapi import APIRouter, Depends
from app.models import DashboardMetrics
from app.sheets import db
from app.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("", response_model=DashboardMetrics)
async def get_dashboard_metrics(current_user: dict = Depends(get_current_user)):
    today_str = date.today().isoformat()

    sales = db.get_records("Sales")
    cash_ledger = db.get_records("CashLedger")
    expenses = db.get_records("Expenses")
    users = db.get_records("Users")
    stock_ledger = db.get_records("SalesmanStockLedger")

    today_sales_total = 0.0
    total_bills_today = 0
    for s in sales:
        if str(s.get("sale_datetime", "")).startswith(today_str):
            today_sales_total += float(s.get("bill_total", 0.0) or 0.0)
            total_bills_today += 1

    today_cash_total = 0.0
    for c in cash_ledger:
        if str(c.get("txn_datetime", "")).startswith(today_str):
            if str(c.get("txn_type", "")).upper() == "SALE_COLLECTION":
                today_cash_total += float(c.get("amount", 0.0) or 0.0)

    pending_expenses = sum(
        1 for e in expenses if str(e.get("approval_status", "")).upper() == "PENDING"
    )

    active_salesmen = sum(
        1 for u in users
        if str(u.get("role", "")).upper() == "SALESMAN" and str(u.get("active", "true")).lower() == "true"
    )

    # Calculate low stock count
    products = db.get_records("Products")
    company_stock = {}
    for p in products:
        company_stock[str(p.get("product_id"))] = 0

    for txn in stock_ledger:
        p_id = str(txn.get("product_id", ""))
        t_type = str(txn.get("txn_type", "")).upper()
        qty = int(txn.get("quantity", 0) or 0)
        if t_type in ["COMPANY_RECEIPT", "POSITIVE_ADJUSTMENT", "RETURN_FROM_SALESMAN"]:
            company_stock[p_id] = company_stock.get(p_id, 0) + abs(qty)
        elif t_type in ["ISSUE_TO_SALESMAN"]:
            company_stock[p_id] = company_stock.get(p_id, 0) - abs(qty)

    low_stock_items = sum(1 for p_id, bal in company_stock.items() if bal < 50)

    return DashboardMetrics(
        today_sales=today_sales_total,
        today_cash=today_cash_total,
        pending_expenses=pending_expenses,
        low_stock_items=low_stock_items,
        active_salesmen=active_salesmen,
        total_bills_today=total_bills_today,
    )
