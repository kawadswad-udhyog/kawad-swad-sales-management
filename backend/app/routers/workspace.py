import asyncio
from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.permissions import is_manager, is_owner, role_v2_of
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
async def load_workspace(current_user: dict = Depends(get_current_user)):
    """Fast concurrent read for the signed-in screen so workspace hydrates immediately."""
    manager = is_manager(current_user)
    can_view_audit = is_owner(current_user) or role_v2_of(current_user) == "AUDITOR"

    named_tasks = [
        ("products", products_router.list_products(current_user)),
        ("customers", customers_router.list_customers(current_user)),
        ("sales", sales_router.list_sales(current_user)),
        ("payments", sales_router.list_payments(current_user)),
        ("stock", stock_router.get_stock_summary(current_user)),
        ("stock_transactions", stock_router.list_stock_transactions(250, current_user)),
        ("expenses", expenses_router.list_expenses(current_user)),
        ("visits", visits_router.list_shop_visits(current_user)),
        ("closings", closing_router.list_daily_closings(current_user)),
        ("salary", salary_router.list_salary_records(current_user)),
        ("stock_discrepancies", stock_router.list_stock_discrepancies(current_user)),
        ("dashboard", dashboard_router.get_dashboard_metrics(current_user)),
    ]

    if manager:
        named_tasks.append(("users", users_router.list_users(current_user)))
        named_tasks.append(("approval_requests", approvals_router.list_approval_requests(current_user)))

    if can_view_audit:
        named_tasks.append(("audit_logs", audit_router.list_audit_logs(250, None, current_user)))

    results = await asyncio.gather(*(coro for _, coro in named_tasks), return_exceptions=True)

    sync_errors = []
    values: dict = {
        "products": [],
        "customers": [],
        "sales": [],
        "payments": [],
        "stock": None,
        "stock_transactions": [],
        "expenses": [],
        "visits": [],
        "closings": [],
        "salary": [],
        "stock_discrepancies": [],
        "dashboard": None,
        "users": [],
        "audit_logs": [],
        "approval_requests": [],
    }

    for (resource, _), result in zip(named_tasks, results):
        if isinstance(result, HTTPException) and result.status_code == 403:
            # Expected least-privilege RBAC boundary for this role: do not pollute _sync_errors
            # or trigger a false PARTIAL_SYNC storage error banner.
            values[resource] = None if resource in {"stock", "dashboard"} else []
            continue
        if isinstance(result, BaseException):
            sync_errors.append({
                "resource": resource,
                "message": str(result) or result.__class__.__name__,
            })
            values[resource] = None
            continue
        values[resource] = result

    failed_resources = [e["resource"] for e in sync_errors]

    return {
        "_sync_errors": sync_errors,
        "_failed_resources": failed_resources,
        **values,
    }
