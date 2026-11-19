from fastapi import APIRouter, Depends
from app.models import DashboardMetrics
from app.sheets import db
from app.auth import get_current_user
from app.permissions import is_manager, is_salesman, role_v2_of, ui_role
from app.timeutil import business_today, business_date_of
from app.calculations.units import parse_currency_amount
from app.stock_math import balances

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("", response_model=DashboardMetrics)
@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id", ""))
    role_name = ui_role(str(current_user.get("role", "")))
    v2_role = role_v2_of(current_user)
    manager_view = is_manager(current_user) or v2_role == "AUDITOR"
    today_str = business_today()
    current_month_str = today_str[:7]  # YYYY-MM

    sales = db.get_records("Sales", fresh=False)
    sale_items = db.get_records("SaleItems", fresh=False)
    cash_ledger = db.get_records("CashLedger", fresh=False)
    payments = db.get_records("Payments", fresh=False)
    expenses = db.get_records("Expenses", fresh=False)
    users = db.get_records("Users", fresh=False)
    stock_ledger = db.get_records("SalesmanStockLedger", fresh=False)
    discrepancies = db.get_records("StockDiscrepancies", fresh=False)
    production_batches = db.get_records("ProductionBatches", fresh=False)

    # Filter items by sale
    items_by_sale = {}
    for item in sale_items:
        items_by_sale.setdefault(str(item.get("sale_id", "")), []).append(item)

    today_sales_total = 0.0
    monthly_sales_total = 0.0
    total_bills_today = 0
    today_kg_sold = 0.0
    monthly_kg_sold = 0.0

    for s in sales:
        salesman_id = str(s.get("salesman_user_id", ""))
        if not manager_view and salesman_id != user_id and str(s.get("entered_by_user_id", "")) != user_id:
            continue
        if str(s.get("txn_status", "COMPLETE")).upper() == "INCOMPLETE" or str(s.get("bill_status", "")).upper() == "CANCELLED":
            continue

        sale_date = business_date_of(str(s.get("sale_datetime", "")))
        amount = parse_currency_amount(s.get("bill_total", 0.0))
        sale_id = str(s.get("sale_id", ""))

        # Calculate kg sold for this bill
        bill_kg = sum(float(i.get("qualifying_kg", 0) or 0) for i in items_by_sale.get(sale_id, []))

        if sale_date == today_str:
            today_sales_total += amount
            total_bills_today += 1
            today_kg_sold += bill_kg

        if sale_date.startswith(current_month_str):
            monthly_sales_total += amount
            monthly_kg_sold += bill_kg

    # Cash and Digital collections today
    today_cash_total = 0.0
    today_digital_total = 0.0

    for c in cash_ledger:
        if not manager_view and str(c.get("salesman_user_id", "")) != user_id:
            continue
        if business_date_of(str(c.get("txn_datetime", ""))) == today_str:
            if str(c.get("txn_type", "")).upper() == "SALE_COLLECTION":
                today_cash_total += parse_currency_amount(c.get("amount", 0.0))

    visible_sale_ids = {
        str(s.get("sale_id", ""))
        for s in sales
        if manager_view
        or str(s.get("salesman_user_id", "")) == user_id
        or str(s.get("entered_by_user_id", "")) == user_id
    }
    for p in payments:
        if not manager_view:
            p_sale_id = str(p.get("sale_id", ""))
            p_collector = str(p.get("collected_by_user_id") or p.get("salesman_user_id") or "")
            if p_sale_id not in visible_sale_ids and p_collector != user_id:
                continue
        if business_date_of(str(p.get("payment_datetime", ""))) == today_str:
            method = str(p.get("payment_method", "")).upper()
            if method in {"UPI", "BANK_TRANSFER"}:
                today_digital_total += parse_currency_amount(p.get("amount", 0.0))

    pending_expenses = sum(
        1 for e in expenses
        if str(e.get("approval_status", "")).upper() in {"PENDING", "PENDING_APPROVAL", "SUBMITTED"}
        and (manager_view or str(e.get("salesman_user_id", "")) == user_id)
    )

    active_salesmen = sum(
        1 for u in users
        if str(u.get("role", "")).upper() in {"SALESMAN", "FIELD_SALESMAN"} and str(u.get("active", "true")).lower() == "true"
    ) if manager_view else 0

    # Incomplete transactions count
    incomplete_count = sum(
        1 for s in sales
        if str(s.get("txn_status", "")).upper() == "INCOMPLETE"
        and (manager_view or str(s.get("salesman_user_id", "")) == user_id)
    )

    # Pending discrepancies
    pending_disc = sum(
        1 for d in discrepancies
        if str(d.get("status", "")).upper() == "PENDING_APPROVAL"
        and (manager_view or str(d.get("counted_by_user_id", "")) == user_id)
    )

    # Pending production batches (match all pending variants)
    pending_prod = sum(
        1 for b in production_batches
        if str(b.get("status", "")).upper() in {"PENDING", "PENDING_APPROVAL", "PENDING APPROVAL", "SUBMITTED"}
    ) if manager_view else 0

    # Low stock items calculation via canonical stock_math balances
    products = db.get_records("Products")
    company_bal, salesman_bal = balances(stock_ledger)
    if manager_view:
        company_stock = {str(p.get("product_id")): int(company_bal.get(str(p.get("product_id")), 0) or 0) for p in products}
        for p_id, bal in company_bal.items():
            company_stock.setdefault(p_id, int(bal or 0))
    else:
        company_stock = {
            str(p.get("product_id")): int(salesman_bal.get((user_id, str(p.get("product_id"))), 0) or 0)
            for p in products
        }

    low_stock_items = sum(1 for p_id, bal in company_stock.items() if 0 < bal < 50)
    zero_stock_items = sum(1 for p_id, bal in company_stock.items() if bal <= 0)

    # Production metrics
    today_prod_kg = sum(
        float(b.get("net_quantity_kg") or b.get("saleable_output_kg") or b.get("quantity_kg") or 0.0)
        for b in production_batches
        if str(b.get("status", "")).upper() == "APPROVED" and str(b.get("production_date", "")).strip() == today_str
    ) if manager_view else 0.0

    pending_prod_kg = sum(
        float(b.get("net_quantity_kg") or b.get("saleable_output_kg") or b.get("quantity_kg") or 0.0)
        for b in production_batches
        if str(b.get("status", "")).upper() == "PENDING"
    ) if manager_view else 0.0

    # Attendance & factory stock metrics restricted to managers/auditors (and HR/PRODUCTION_SUPERVISOR for workforce)
    can_view_workforce_counts = manager_view or v2_role in {"HR", "PRODUCTION_SUPERVISOR"}
    if can_view_workforce_counts:
        workers = db.get_records("Workers", fresh=False) or []
        worker_attendance = db.get_records("WorkerAttendance", fresh=False) or []
        labour_master = db.get_records("LabourMaster", fresh=False) or []
        labour_attendance = db.get_records("LabourAttendance", fresh=False) or []

        active_legacy = sum(1 for w in workers if str(w.get("active", "true")).lower() in {"true", "1"})
        active_labour = sum(1 for l in labour_master if str(l.get("active", "true")).lower() in {"true", "1"})
        active_workers_count = active_legacy + active_labour

        present_legacy = sum(
            1 for a in worker_attendance
            if str(a.get("attendance_date", "")).strip() == today_str and str(a.get("status", "")).upper() in {"PRESENT", "HALF_DAY"}
        )
        present_labour = sum(
            1 for a in labour_attendance
            if str(a.get("attendance_date", "")).strip() == today_str and str(a.get("status", "")).upper() in {"PRESENT", "HALF_DAY"}
        )
        workers_present_today = present_legacy + present_labour
    else:
        active_workers_count = 0
        workers_present_today = 0

    # Finished stock available across factory and warehouse
    can_view_factory_stock = manager_view or v2_role in {"STORE", "PRODUCTION_SUPERVISOR", "PACKAGING", "QUALITY", "LOGISTICS"}
    factory_pkts = 0
    if can_view_factory_stock:
        prod_stock_ledger = db.get_records("ProductionStockLedger", fresh=False)
        for p_txn in prod_stock_ledger:
            m_type = str(p_txn.get("movement_type", "")).upper()
            pkts = int(float(p_txn.get("quantity_packets", 0) or 0))
            if m_type in {"PACKED", "POSITIVE_ADJUSTMENT", "PACKAGING_RECOVERY", "FACTORY_RECONCILIATION"}:
                factory_pkts += pkts
            elif m_type in {"DISPATCH", "NEGATIVE_ADJUSTMENT"}:
                factory_pkts -= pkts
        factory_pkts = max(0, factory_pkts)
    warehouse_pkts = sum(max(0, bal) for bal in company_stock.values()) if manager_view else sum(max(0, bal) for p_id, bal in company_stock.items())
    total_finished_pkts = factory_pkts + warehouse_pkts

    return DashboardMetrics(
        today_sales=round(today_sales_total, 2),
        today_cash=round(today_cash_total, 2),
        pending_expenses=pending_expenses,
        low_stock_items=low_stock_items,
        zero_stock_items_count=zero_stock_items,
        active_salesmen=active_salesmen,
        total_bills_today=total_bills_today,
        monthly_sales=round(monthly_sales_total, 2),
        today_kg_sold=round(today_kg_sold, 3),
        monthly_kg_sold=round(monthly_kg_sold, 3),
        digital_collections_today=round(today_digital_total, 2),
        incomplete_transactions_count=incomplete_count,
        pending_discrepancies=pending_disc,
        pending_production_approvals=pending_prod,
        today_production_kg=round(today_prod_kg, 2),
        pending_production_kg=round(pending_prod_kg, 2),
        available_finished_packets=total_finished_pkts,
        active_workers_count=active_workers_count,
        workers_present_today=workers_present_today,
        role=role_name,
        salesman_user_id=user_id if not manager_view else None,
    )

