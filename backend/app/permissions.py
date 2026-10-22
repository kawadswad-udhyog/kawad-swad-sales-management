from typing import Any, Dict, List, Optional, Set, Tuple
from fastapi import HTTPException

OWNERS = {"OWNER", "OWNER_ADMIN", "ADMIN"}
MANAGERS = OWNERS | {"PA"}
SALESMEN = {"SALESMAN", "FIELD_SALESMAN"}
FACTORY_WORKERS = {"FACTORY_WORKER", "PRODUCTION_WORKER", "WORKER"}

CANONICAL_ROLE_MAP: Dict[str, str] = {
    "OWNER": "OWNER",
    "OWNER_ADMIN": "OWNER",
    "ADMIN": "OWNER",
    "PA": "PA",
    "PERSONAL_ASSISTANT": "PA",
    "SALESMAN": "SALESMAN",
    "FIELD_SALESMAN": "SALESMAN",
    "FACTORY_WORKER": "FACTORY_WORKER",
    "PRODUCTION_WORKER": "FACTORY_WORKER",
    "WORKER": "FACTORY_WORKER",
    "DISPATCH": "DISPATCH",
    "PRODUCTION": "PRODUCTION",
}

# Protected permissions that only the Owner can hold; custom roles cannot grant these
OWNER_ONLY_PERMISSIONS: Set[Tuple[str, str]] = {
    ("production", "approve"),
    ("packaging", "approve_discrepancy"),
    ("users", "manage_roles"),
    ("users", "create_owner"),
    ("approvals", "decide"),
}

DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, List[str]]] = {
    "OWNER": {
        "sales": ["view", "create", "export", "cancel"],
        "production": ["view", "create", "approve", "costing"],
        "packaging": ["view", "create", "approve_discrepancy"],
        "inventory": ["view", "transfer", "reconcile", "adjust"],
        "attendance": ["view", "mark", "manage_workers"],
        "users": ["view", "create", "update", "deactivate", "reset_password", "manage_roles"],
        "approvals": ["view", "decide"],
        "expenses": ["view", "create", "approve"],
    },
    "PA": {
        "sales": ["view", "create", "export"],
        "production": ["view", "create", "costing"],
        "packaging": ["view", "create"],
        "inventory": ["view", "transfer"],
        "attendance": ["view", "mark", "manage_workers"],
        "users": ["view", "request_create", "request_update", "request_deactivate", "request_reset_password"],
        "approvals": ["view"],
        "expenses": ["view", "create"],
    },
    "SALESMAN": {
        "sales": ["view", "create"],
        "inventory": ["view_own"],
        "attendance": [],
        "expenses": ["view_own", "create"],
    },
    "FACTORY_WORKER": {
        "production": ["view"],
    },
    "DISPATCH": {
        "inventory": ["view", "transfer"],
    },
    "PRODUCTION": {
        "production": ["view", "create"],
        "packaging": ["view", "create"],
    },
}


def canonical_role(role: str) -> str:
    r = str(role or "").strip().upper()
    return CANONICAL_ROLE_MAP.get(r, r)


def role_of(user: dict) -> str:
    return canonical_role(str((user or {}).get("role", "")).upper())


def raw_role_of(user: dict) -> str:
    return str((user or {}).get("role", "")).strip().upper()


def is_owner(user: dict) -> bool:
    return role_of(user) in OWNERS or raw_role_of(user) in OWNERS


def is_manager(user: dict) -> bool:
    return is_owner(user) or role_of(user) == "PA"


def is_salesman(user: dict) -> bool:
    return role_of(user) in {"SALESMAN"} or raw_role_of(user) in SALESMEN


def is_factory_worker(user: dict) -> bool:
    return role_of(user) in {"FACTORY_WORKER"} or raw_role_of(user) in FACTORY_WORKERS


def can_manage_production(user: dict) -> bool:
    return is_owner(user)


def require_manager(user: dict) -> tuple[str, str]:
    if not is_manager(user):
        raise HTTPException(status_code=403, detail="Owner or PA permission is required.")
    return str((user or {}).get("user_id", "")), role_of(user)


def require_owner(user: dict) -> tuple[str, str]:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Only the owner can do this.")
    return str((user or {}).get("user_id", "")), role_of(user)


def require_production_access(user: dict) -> tuple[str, str]:
    if not is_manager(user):
        raise HTTPException(status_code=403, detail="Only the Owner or PA can access production operations.")
    return str((user or {}).get("user_id", "")), role_of(user)


def has_permission(user: dict, module: str, action: str, custom_roles: Optional[List[dict]] = None) -> bool:
    """
    Check if user has permission to perform an action on a module.
    Owner always has full permissions.
    Standard roles check DEFAULT_ROLE_PERMISSIONS.
    Custom roles check their permissions_json payload.
    """
    if is_owner(user):
        return True

    # Owner-only actions can never be executed by non-owners
    if (module, action) in OWNER_ONLY_PERMISSIONS:
        return False

    c_role = role_of(user)
    raw_role = raw_role_of(user)

    # Check built-in permissions
    if c_role in DEFAULT_ROLE_PERMISSIONS:
        module_perms = DEFAULT_ROLE_PERMISSIONS[c_role].get(module, [])
        if action in module_perms or "*" in module_perms:
            return True

    # Check custom roles
    if custom_roles:
        for cr in custom_roles:
            cr_name = str(cr.get("role_name", "")).strip().upper()
            if cr_name in {c_role, raw_role}:
                perms_data = cr.get("permissions") or {}
                if isinstance(perms_data, str):
                    try:
                        import json
                        perms_data = json.loads(perms_data)
                    except Exception:
                        perms_data = {}
                actions = perms_data.get(module, [])
                if action in actions or "*" in actions:
                    return True

    return False


def validate_custom_role_permissions(permissions: Dict[str, List[str]]) -> None:
    """
    Ensures that custom roles do NOT grant themselves Owner-level permissions.
    """
    for module, actions in permissions.items():
        for action in actions:
            if (module, action) in OWNER_ONLY_PERMISSIONS:
                raise HTTPException(
                    status_code=403,
                    detail=f"Custom roles cannot be granted Owner-only permission: '{module}:{action}'."
                )


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
    return CANONICAL_ROLE_MAP.get(value, value or "SALESMAN")

