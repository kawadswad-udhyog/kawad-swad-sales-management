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
from app.routers import approvals as approvals_router

router = APIRouter(prefix="/api/workspace", tags=["Workspace"])


@router.get("")
async def load_workspace(
    current_user: dict = Depends(get_current_user),
):
    """Load workspace data and expose individual synchronization failures."""

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
            approvals_router.list_approval_requests(current_user),
        ])

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    task_names = [
        "products",
        "customers",
        "sales",
        "payments",
        "stock",
        "stock_transactions",
        "expenses",
        "visits",
        "closings",
        "salary",
        "stock_discrepancies",
    ]

    if manager:
        task_names.extend([
            "dashboard",
            "users",
            "audit_logs",
            "approval_requests",
        ])

    sync_errors = [
        {
            "resource": task_names[index],
            "message": str(result),
        }
        for index, result in enumerate(results)
        if isinstance(result, Exception)
    ]

    def safe_value(index, default_value):
        result = results[index]

        if isinstance(result, Exception):
            return default_value

        return result

    payload = {
        "_sync_errors": sync_errors,
        "products": safe_value(0, []),
        "customers": safe_value(1, []),
        "sales": safe_value(2, []),
        "payments": safe_value(3, []),
        "stock": safe_value(
            4,
            {
                "company_stock": [],
                "salesman_stock": [],
            },
        ),
        "stock_transactions": safe_value(5, []),
        "expenses": safe_value(6, []),
        "visits": safe_value(7, []),
        "closings": safe_value(8, []),
        "salary": safe_value(9, []),
        "stock_discrepancies": safe_value(10, []),
    }

    if manager:
        payload.update({
            "dashboard": safe_value(11, None),
            "users": safe_value(12, []),
            "audit_logs": safe_value(13, []),
            "approval_requests": safe_value(14, []),
        })
    else:
        payload.update({
            "dashboard": None,
            "users": [],
            "audit_logs": [],
            "approval_requests": [],
        })

    return payload
