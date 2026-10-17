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

router = APIRouter(prefix="/api/workspace", tags=["Workspace"])


@router.get("")
async def load_workspace(current_user: dict = Depends(get_current_user)):
    """One read for the signed-in screen so login does not fan out into a dozen sheet downloads."""
    payload = {
        "products": await products_router.list_products(current_user),
        "customers": await customers_router.list_customers(current_user),
        "sales": await sales_router.list_sales(current_user),
        "payments": await sales_router.list_payments(current_user),
        "stock": await stock_router.get_stock_summary(current_user),
        "stock_transactions": await stock_router.list_stock_transactions(250, current_user),
        "expenses": await expenses_router.list_expenses(current_user),
        "visits": await visits_router.list_shop_visits(current_user),
        "closings": await closing_router.list_daily_closings(current_user),
        "salary": await salary_router.list_salary_records(current_user),
    }
    if is_manager(current_user):
        payload["dashboard"] = await dashboard_router.get_dashboard_metrics(current_user)
        payload["users"] = await users_router.list_users(current_user)
    else:
        payload["dashboard"] = None
        payload["users"] = []
    return payload
