from fastapi import HTTPException

OWNERS = {"OWNER", "OWNER_ADMIN", "ADMIN"}
MANAGERS = OWNERS | {"PA"}
SALESMEN = {"SALESMAN", "FIELD_SALESMAN"}
FACTORY_WORKERS = {"FACTORY_WORKER", "PRODUCTION_WORKER", "WORKER"}


def role_of(user: dict) -> str:
    return str((user or {}).get("role", "")).upper()


def is_owner(user: dict) -> bool:
    return role_of(user) in OWNERS


def is_manager(user: dict) -> bool:
    return role_of(user) in MANAGERS


def is_salesman(user: dict) -> bool:
    return role_of(user) in SALESMEN


def is_factory_worker(user: dict) -> bool:
    return role_of(user) in FACTORY_WORKERS


def can_manage_production(user: dict) -> bool:
    return is_owner(user)


def require_manager(user: dict) -> None:
    if not is_manager(user):
        raise HTTPException(status_code=403, detail="Owner or PA permission is required.")


def require_owner(user: dict) -> None:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Only the owner can do this.")


def require_production_access(user: dict) -> None:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Only the Owner can access production operations.")


def ui_role(role: str) -> str:
    value = str(role or "").upper()
    if value in OWNERS:
        return "OWNER"
    if value == "PA":
        return "PA"
    if value in SALESMEN:
        return "SALESMAN"
    if value in FACTORY_WORKERS:
        return "FACTORY_WORKER"
    return value or "SALESMAN"

