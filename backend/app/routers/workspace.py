import asyncio
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.permissions import is_manager
from app.routers import sales as sales_router
from app.routers import stock as stock_router
from app.routers import products as products_router
from app.routers import customers as customers_router
from app.routers import expenses as expenses_router
from app.routers import visits as visits_router
from app.routers import closing as closing_router
from app.routers import salary as salary_router
from app.routers import dashboard as dashboard_router
from app.routers import users as users_router
from app.routers import audit as audit_router

router = APIRouter(prefix="/api/workspace", tags=["Workspace"])


@router.get("")
async def load_workspace(current_user: dict = Depends(get_current_user)):
    """Fast concurrent read for the signed-in screen so workspace hydrates immediately."""
    manager = is_manager(current_user)

    tasks = [
        products_router.list_products(current_user),
        customers_router.list_customers(current_user),
        sales_router.list_sales(current_user),
        sales_router.list_payments(current_user),
        stock_router.get_stock_summary(current_user),
        stock_router.list_stock_transactions(250, current_user),
        expenses_router.list_expenses(current_user),
        visits_router.list_shop_visits(current_user),
        closing_router.list_daily_closings(current_user),
        salary_router.list_salary_records(current_user),
        stock_router.list_stock_discrepancies(current_user),
    ]

    if manager:
        tasks.extend([
            dashboard_router.get_dashboard_metrics(current_user),
            users_router.list_users(current_user),
            audit_router.list_audit_logs(250, None, current_user),
        ])

    results = await asyncio.gather(*tasks)

    payload = {
        "products": results[0],
        "customers": results[1],
        "sales": results[2],
        "payments": results[3],
        "stock": results[4],
        "stock_transactions": results[5],
        "expenses": results[6],
        "visits": results[7],
        "closings": results[8],
        "salary": results[9],
        "stock_discrepancies": results[10],
    }

    if manager:
        payload["dashboard"] = results[11]
        payload["users"] = results[12]
        payload["audit_logs"] = results[13]
    else:
        payload["dashboard"] = None
        payload["users"] = []
        payload["audit_logs"] = []

    return payload
