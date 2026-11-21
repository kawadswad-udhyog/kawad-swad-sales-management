"""
Kawad Swad ERP — Blueprint v2.1 Role-Based & Field-Level Permissions Contract.

Enforces:
- 12 exact role codes:
  OWNER_ADMIN, PA, ACCOUNTS, PROCUREMENT, STORE, PRODUCTION,
  QUALITY, PACKAGING, SALES, FIELD_SALESMAN, HR, AUDITOR
- Legacy backward-compatibility aliases (OWNER -> OWNER_ADMIN, SALESMAN -> FIELD_SALESMAN, etc.)
- Strict default-deny RBAC check for module/action permissions
- Confidentiality contract:
  - SalaryPayments, EmployeeAdvances, SalaryStructures, Employees.bank_details_reference,
    bank_details, bank_account_no, bank_ifsc, personal IDs (aadhaar, pan, passport, doc refs):
    * OWNER_ADMIN: full access
    * ACCOUNTS: minimum fields & actions ONLY inside approved advance-disbursement flows
    * PA and all other roles: absent (key-stripped before HTTP response)
"""

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from fastapi import HTTPException

from app.schema_registry import (
    ACCOUNTS_ADVANCE_DISBURSEMENT_ALLOWED_FIELDS,
    CONFIDENTIAL_PERSONAL_FIELDS,
    CONFIDENTIAL_TABS_NO_CACHE,
    NEVER_EXPOSE_CREDENTIAL_FIELDS,
)

# Exact 12 Blueprint v2.1 Roles
TWELVE_ROLES: Tuple[str, ...] = (
    "OWNER_ADMIN",
    "PA",
    "ACCOUNTS",
    "PROCUREMENT",
    "STORE",
    "PRODUCTION",
    "QUALITY",
    "PACKAGING",
    "SALES",
    "FIELD_SALESMAN",
    "HR",
    "AUDITOR",
)

OWNERS: Set[str] = {"OWNER", "OWNER_ADMIN", "ADMIN"}
MANAGERS: Set[str] = OWNERS | {"PA"}
SALESMEN: Set[str] = {"SALESMAN", "FIELD_SALESMAN"}
FACTORY_WORKERS: Set[str] = {"FACTORY_WORKER", "PRODUCTION_WORKER", "WORKER"}

EMPLOYEE_ROLES: Set[str] = {
    "SALESMAN",
    "FIELD_SALESMAN",
    "FREELANCER",
    "PA",
    "PERSONAL_ASSISTANT",
    "ACCOUNTANT",
    "ACCOUNTS",
    "PROCUREMENT",
    "STORE",
    "PRODUCTION",
    "QUALITY",
    "PACKAGING",
    "SALES",
    "HR",
    "AUDITOR",
    "SOCIAL_MEDIA_ECOMMERCE_MANAGER",
    "SOCIAL_MEDIA_MANAGER",
    "ECOMMERCE_MANAGER",
}

# Exact Blueprint v2.1 role normalization map
CANONICAL_ROLE_V2_MAP: Dict[str, str] = {
    "OWNER_ADMIN": "OWNER_ADMIN",
    "OWNER": "OWNER_ADMIN",
    "ADMIN": "OWNER_ADMIN",
    "PA": "PA",
    "PERSONAL_ASSISTANT": "PA",
    "ACCOUNTS": "ACCOUNTS",
    "ACCOUNTANT": "ACCOUNTS",
    "PROCUREMENT": "PROCUREMENT",
    "STORE": "STORE",
    "PRODUCTION": "PRODUCTION",
    "FACTORY_WORKER": "PRODUCTION",
    "PRODUCTION_WORKER": "PRODUCTION",
    "WORKER": "PRODUCTION",
    "QUALITY": "QUALITY",
    "PACKAGING": "PACKAGING",
    "SALES": "SALES",
    "DISPATCH": "SALES",
    "FIELD_SALESMAN": "FIELD_SALESMAN",
    "SALESMAN": "FIELD_SALESMAN",
    "HR": "HR",
    "AUDITOR": "AUDITOR",
}

# Legacy alias map kept for existing v1 callers that inspect legacy strings
CANONICAL_ROLE_MAP: Dict[str, str] = {
    "OWNER": "OWNER",
    "OWNER_ADMIN": "OWNER",
    "ADMIN": "OWNER",
    "PA": "PA",
    "PERSONAL_ASSISTANT": "PA",
    "SALESMAN": "SALESMAN",
    "FIELD_SALESMAN": "SALESMAN",
    "FREELANCER": "FREELANCER",
    "ACCOUNTANT": "ACCOUNTANT",
    "ACCOUNTS": "ACCOUNTANT",
    "SOCIAL_MEDIA_ECOMMERCE_MANAGER": "SOCIAL_MEDIA_ECOMMERCE_MANAGER",
    "SOCIAL_MEDIA_MANAGER": "SOCIAL_MEDIA_ECOMMERCE_MANAGER",
    "ECOMMERCE_MANAGER": "SOCIAL_MEDIA_ECOMMERCE_MANAGER",
    "FACTORY_WORKER": "FACTORY_WORKER",
    "PRODUCTION_WORKER": "FACTORY_WORKER",
    "WORKER": "FACTORY_WORKER",
    "DISPATCH": "DISPATCH",
    "PRODUCTION": "PRODUCTION",
    "PROCUREMENT": "PROCUREMENT",
    "STORE": "STORE",
    "QUALITY": "QUALITY",
    "PACKAGING": "PACKAGING",
    "SALES": "SALES",
    "HR": "HR",
    "AUDITOR": "AUDITOR",
}

# Complete set of recognized built-in canonical + legacy system role tokens.
# Any role outside this set requires an explicitly active CustomRoles entry.
KNOWN_SYSTEM_ROLES: Set[str] = (
    set(TWELVE_ROLES)
    | set(CANONICAL_ROLE_V2_MAP.keys())
    | set(CANONICAL_ROLE_MAP.keys())
)

_EXPLICIT_ACTIVE_VALUES: Set[str] = {"true", "1", "yes", "active"}


def is_active_custom_role(row: Any) -> bool:
    """
    Fail-closed custom role active check.
    Rejects non-dict rows, blank role_name, soft-deleted rows, and any explicit
    non-active status value (only explicit truthy active values are accepted when set).
    """
    if not isinstance(row, dict):
        return False
    role_name = str(row.get("role_name") or "").strip().upper()
    if not role_name:
        return False
    if str(row.get("deleted") or "").strip().lower() in {"true", "1", "yes"}:
        return False
    if "active" in row:
        active_val = row.get("active")
        if isinstance(active_val, bool):
            return active_val
        if isinstance(active_val, int):
            return active_val == 1
        if active_val is not None:
            active_str = str(active_val).strip().lower()
            if active_str != "" and active_str not in _EXPLICIT_ACTIVE_VALUES:
                return False
    return True


def is_recognized_role(role: Any, custom_roles: Optional[List[dict]] = None) -> bool:
    """
    Fail-closed role validator.
    Returns True ONLY for a recognized canonical/legacy system role or an explicitly
    active, non-colliding CustomRoles entry. Blank, None, and unknown roles return False.
    """
    clean = str(role or "").strip().upper()
    if not clean:
        return False
    if clean in KNOWN_SYSTEM_ROLES:
        return True
    if custom_roles:
        for cr in custom_roles:
            if not is_active_custom_role(cr):
                continue
            cr_name = str(cr.get("role_name") or "").strip().upper()
            if cr_name and cr_name not in KNOWN_SYSTEM_ROLES and cr_name == clean:
                return True
    return False


def resolve_authorized_role(raw_role: Any, custom_roles: Optional[List[dict]] = None) -> Optional[str]:
    """
    Resolve an authoritative role string without any implicit default assignment.
    Returns None when role is missing, blank, or unrecognized.
    """
    clean = str(raw_role or "").strip().upper()
    if not is_recognized_role(clean, custom_roles=custom_roles):
        return None
    return CANONICAL_ROLE_V2_MAP.get(clean, clean)

# Protected permissions that ONLY OWNER_ADMIN can hold; custom roles cannot grant these
OWNER_ONLY_PERMISSIONS: Set[Tuple[str, str]] = {
    ("production", "approve"),
    ("packaging", "approve_discrepancy"),
    ("users", "manage_roles"),
    ("users", "create_owner"),
    ("approvals", "decide"),
    ("workforce", "approve_payroll"),
    ("workforce", "modify_salary_structures"),
    ("workforce", "view_confidential_payroll"),
    ("control", "approve_ca_policy"),
    ("accounting", "close_period"),
}

# Authoritative 12-role capability matrix across 15 database modules
V2_ROLE_PERMISSIONS: Dict[str, Dict[str, List[str]]] = {
    "OWNER_ADMIN": {
        "control": ["*"],
        "security": ["*"],
        "catalogue": ["*"],
        "procurement": ["*"],
        "store": ["*"],
        "production": ["*"],
        "packaging": ["*"],
        "quality": ["*"],
        "sales": ["*"],
        "logistics": ["*"],
        "channels": ["*"],
        "accounting": ["*"],
        "workforce": ["*"],
        "compliance_assets": ["*"],
        "reports": ["*"],
        "users": ["*"],
        "approvals": ["*"],
        "expenses": ["*"],
        "inventory": ["*"],
        "attendance": ["*"],
        "employee_portal": ["*"],
    },
    "PA": {
        "control": ["view"],
        "catalogue": ["view", "create", "update"],
        "procurement": ["view", "create"],
        "store": ["view", "transfer"],
        "production": ["view", "create", "costing"],
        "packaging": ["view", "create"],
        "quality": ["view"],
        "sales": ["view", "create", "export"],
        "logistics": ["view", "create", "dispatch"],
        "channels": ["view"],
        "accounting": ["view"],
        "workforce": ["view_own_tasks", "update_own_tasks", "manage_tasks_assigned", "view_directory", "view_labour", "mark_attendance"],
        "compliance_assets": ["view"],
        "reports": ["view"],
        "users": ["view", "request_create", "request_update", "request_deactivate", "request_reset_password"],
        "approvals": ["view"],
        "expenses": ["view", "create"],
        "inventory": ["view", "transfer"],
        "attendance": ["view", "mark", "manage_workers"],
    },
    "ACCOUNTS": {
        "catalogue": ["view"],
        "procurement": ["view", "record_bill", "record_payment"],
        "store": ["view"],
        "production": ["view"],
        "packaging": ["view"],
        "quality": ["view"],
        "sales": ["view", "record_payment"],
        "logistics": ["view"],
        "channels": ["view", "create", "reconcile"],
        "accounting": ["view", "create_vouchers", "reconcile_read"],
        "workforce": ["view_own_tasks", "update_own_tasks", "disburse_approved_advance"],
        "compliance_assets": ["view"],
        "reports": ["view"],
        "expenses": ["view", "create"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "PROCUREMENT": {
        "catalogue": ["view", "create", "update"],
        "procurement": ["view", "create", "update", "receive", "return"],
        "store": ["view"],
        "quality": ["view"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "STORE": {
        "catalogue": ["view"],
        "procurement": ["view", "receive"],
        "store": ["view", "issue", "transfer", "adjust_request"],
        "inventory": ["view", "transfer"],
        "production": ["view"],
        "packaging": ["view"],
        "quality": ["view"],
        "logistics": ["view", "create", "dispatch"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "PRODUCTION": {
        "catalogue": ["view"],
        "store": ["view"],
        "production": ["view", "create", "record_consumption", "record_output", "record_loss", "record_gig_work"],
        "packaging": ["view"],
        "quality": ["view", "submit_qc"],
        "compliance_assets": ["view"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "QUALITY": {
        "catalogue": ["view"],
        "procurement": ["view"],
        "store": ["view"],
        "production": ["view"],
        "packaging": ["view"],
        "quality": ["view", "create", "inspect", "release_lot", "hold_lot", "reject_lot", "manage_complaints"],
        "compliance_assets": ["view", "create"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "PACKAGING": {
        "catalogue": ["view"],
        "store": ["view"],
        "production": ["view"],
        "packaging": ["view", "create", "record_output"],
        "quality": ["view"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "SALES": {
        "catalogue": ["view"],
        "store": ["view"],
        "quality": ["view"],
        "sales": ["view", "create", "export"],
        "logistics": ["view", "create", "dispatch"],
        "channels": ["view", "create"],
        "inventory": ["view", "transfer"],
        "expenses": ["view", "create"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "FIELD_SALESMAN": {
        "catalogue": ["view"],
        "sales": ["view", "create"],
        "logistics": ["view_own", "accept_loading_pass"],
        "inventory": ["view_own"],
        "attendance": ["view_own", "check_in", "check_out"],
        "expenses": ["view_own", "create"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "HR": {
        "workforce": ["view_directory", "manage_attendance", "verify_gig_work", "manage_tasks"],
        "attendance": ["view", "mark", "manage_workers"],
        "compliance_assets": ["view"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "AUDITOR": {
        "control": ["view"],
        "catalogue": ["view"],
        "procurement": ["view"],
        "store": ["view"],
        "production": ["view"],
        "packaging": ["view"],
        "quality": ["view"],
        "sales": ["view"],
        "logistics": ["view"],
        "channels": ["view"],
        "accounting": ["view"],
        "compliance_assets": ["view"],
        "reports": ["view"],
        "inventory": ["view"],
    },
}

DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, List[str]]] = {
    "OWNER": V2_ROLE_PERMISSIONS["OWNER_ADMIN"],
    "OWNER_ADMIN": V2_ROLE_PERMISSIONS["OWNER_ADMIN"],
    "PA": V2_ROLE_PERMISSIONS["PA"],
    "SALESMAN": V2_ROLE_PERMISSIONS["FIELD_SALESMAN"],
    "FIELD_SALESMAN": V2_ROLE_PERMISSIONS["FIELD_SALESMAN"],
    "FREELANCER": {
        "employee_portal": ["view_dashboard", "view_own_projects", "view_own_tasks", "update_own_tasks", "submit_work", "view_own_profile"],
    },
    "ACCOUNTANT": V2_ROLE_PERMISSIONS["ACCOUNTS"],
    "ACCOUNTS": V2_ROLE_PERMISSIONS["ACCOUNTS"],
    "PROCUREMENT": V2_ROLE_PERMISSIONS["PROCUREMENT"],
    "STORE": V2_ROLE_PERMISSIONS["STORE"],
    "PRODUCTION": V2_ROLE_PERMISSIONS["PRODUCTION"],
    "QUALITY": V2_ROLE_PERMISSIONS["QUALITY"],
    "PACKAGING": V2_ROLE_PERMISSIONS["PACKAGING"],
    "SALES": V2_ROLE_PERMISSIONS["SALES"],
    "HR": V2_ROLE_PERMISSIONS["HR"],
    "AUDITOR": V2_ROLE_PERMISSIONS["AUDITOR"],
    "SOCIAL_MEDIA_ECOMMERCE_MANAGER": {
        "catalogue": ["view"],
        "channels": ["view", "create"],
        "employee_portal": ["view_dashboard", "view_own_tasks", "update_own_tasks", "view_own_profile"],
    },
    "FACTORY_WORKER": {"production": ["view"]},
    "DISPATCH": V2_ROLE_PERMISSIONS["STORE"],
}


def canonical_role(role: str) -> str:
    r = str(role or "").strip().upper()
    return CANONICAL_ROLE_MAP.get(r, r)


def canonical_role_v2(role: str) -> str:
    """Normalize role string onto one of the exact 12 Blueprint v2.1 roles when mapped."""
    r = str(role or "").strip().upper()
    return CANONICAL_ROLE_V2_MAP.get(r, r)


def role_of(user: dict) -> str:
    return canonical_role(str((user or {}).get("role", "")).upper())


def role_v2_of(user: dict) -> str:
    return canonical_role_v2(str((user or {}).get("role", "")).upper())


def raw_role_of(user: dict) -> str:
    return str((user or {}).get("role", "")).strip().upper()


def is_owner(user: dict) -> bool:
    return role_v2_of(user) == "OWNER_ADMIN" or role_of(user) in OWNERS or raw_role_of(user) in OWNERS


def is_manager(user: dict) -> bool:
    return is_owner(user) or role_v2_of(user) == "PA"


def is_salesman(user: dict) -> bool:
    return role_v2_of(user) == "FIELD_SALESMAN" or role_of(user) in {"SALESMAN"} or raw_role_of(user) in SALESMEN


def is_factory_worker(user: dict) -> bool:
    return role_of(user) in {"FACTORY_WORKER"} or raw_role_of(user) in FACTORY_WORKERS


def can_manage_production(user: dict) -> bool:
    return is_owner(user)


def require_manager(user: dict) -> tuple[str, str]:
    if not is_manager(user):
        raise HTTPException(status_code=403, detail="Owner or PA permission is required.")
    return str((user or {}).get("user_id", "")), role_v2_of(user)


def require_owner(user: dict) -> tuple[str, str]:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Only OWNER_ADMIN can perform this action.")
    return str((user or {}).get("user_id", "")), role_v2_of(user)


def require_production_access(user: dict) -> tuple[str, str]:
    if not (is_manager(user) or role_v2_of(user) in {"PRODUCTION", "PACKAGING"}):
        raise HTTPException(status_code=403, detail="Production or Packaging manager permission is required.")
    return str((user or {}).get("user_id", "")), role_v2_of(user)


def require_roles(user: dict, allowed_roles: Iterable[str], detail: Optional[str] = None) -> tuple[str, str]:
    """Fail-closed exact v2 role enforcement."""
    v2_role = role_v2_of(user)
    normalized_allowed = {canonical_role_v2(r) for r in allowed_roles if str(r or "").strip()}
    if not v2_role or (v2_role not in normalized_allowed and not is_owner(user)):
        raise HTTPException(
            status_code=403,
            detail=detail or f"Role '{v2_role or 'UNASSIGNED'}' is not authorized for this resource.",
        )
    return str((user or {}).get("user_id", "")), v2_role


def has_permission(user: dict, module: str, action: str, custom_roles: Optional[List[dict]] = None) -> bool:
    """
    Default-deny permission evaluation.
    OWNER_ADMIN always passes; protected owner-only permissions are never bypassed.
    Blank or unrecognized roles are always denied.
    """
    raw_role = raw_role_of(user)
    if not raw_role:
        return False

    if is_owner(user):
        return True

    if (module, action) in OWNER_ONLY_PERMISSIONS:
        return False

    v2_role = role_v2_of(user)
    c_role = role_of(user)

    for candidate in (v2_role, c_role, raw_role):
        if not candidate:
            continue
        matrix = V2_ROLE_PERMISSIONS.get(candidate) or DEFAULT_ROLE_PERMISSIONS.get(candidate)
        if matrix:
            module_perms = matrix.get(module, [])
            if action in module_perms or "*" in module_perms:
                return True

    if custom_roles and raw_role not in KNOWN_SYSTEM_ROLES:
        owner_protected_modules = {m for m, _ in OWNER_ONLY_PERMISSIONS} | {"security"}
        for cr in custom_roles:
            if not is_active_custom_role(cr):
                continue
            cr_name = str(cr.get("role_name") or "").strip().upper()
            if not cr_name or cr_name in KNOWN_SYSTEM_ROLES:
                continue
            if cr_name in {v2_role, c_role, raw_role}:
                perms_data = cr.get("permissions")
                if perms_data is None:
                    perms_data = cr.get("permissions_json") or {}
                if isinstance(perms_data, str):
                    try:
                        import json
                        perms_data = json.loads(perms_data)
                    except Exception:
                        perms_data = {}
                if not isinstance(perms_data, dict):
                    continue
                actions = perms_data.get(module, [])
                if not isinstance(actions, list):
                    continue
                if action in actions:
                    return True
                if "*" in actions and module not in owner_protected_modules:
                    return True

    return False


def require_module_action(user: dict, module: str, action: str, custom_roles: Optional[List[dict]] = None) -> tuple[str, str]:
    if not has_permission(user, module, action, custom_roles=custom_roles):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied for '{module}:{action}' under role '{role_v2_of(user) or 'UNASSIGNED'}'.",
        )
    return str((user or {}).get("user_id", "")), role_v2_of(user)


def validate_custom_role_permissions(permissions: Dict[str, List[str]]) -> None:
    """Ensures custom roles do NOT grant Owner-only, security, wildcard, or confidential payroll/bank permissions."""
    if not isinstance(permissions, dict):
        raise HTTPException(status_code=422, detail="Custom role permissions must be a module-to-actions mapping.")
    for module, actions in permissions.items():
        clean_mod = str(module or "").strip().lower()
        if clean_mod in {"*", "security"}:
            raise HTTPException(
                status_code=403,
                detail=f"Custom roles cannot be granted access to protected module: '{module}'.",
            )
        if not isinstance(actions, list):
            raise HTTPException(status_code=422, detail=f"Actions for module '{module}' must be a list.")
        for action in actions:
            clean_act = str(action or "").strip().lower()
            if clean_act == "*":
                raise HTTPException(
                    status_code=403,
                    detail=f"Custom roles cannot use wildcard '*' permissions on module '{module}'.",
                )
            if (clean_mod, clean_act) in OWNER_ONLY_PERMISSIONS:
                raise HTTPException(
                    status_code=403,
                    detail=f"Custom roles cannot be granted Owner-only permission: '{module}:{action}'.",
                )


def can_access_confidential_tab(user: dict, tab_name: str, workflow_context: str = "GENERAL") -> bool:
    if is_owner(user):
        return True
    if tab_name in {"EmployeeAdvances", "WorkforcePayments"} and role_v2_of(user) == "ACCOUNTS" and workflow_context == "APPROVED_ADVANCE_DISBURSEMENT":
        return True
    return tab_name not in CONFIDENTIAL_TABS_NO_CACHE


def filter_confidential_record(
    record: Dict[str, Any],
    user: dict,
    *,
    tab_name: str = "",
    workflow_context: str = "GENERAL",
) -> Optional[Dict[str, Any]]:
    """
    Enforce field-level confidentiality on server responses.
    Returns None if the user has zero row-level access to a confidential table.
    Otherwise returns a copy with restricted keys absent (never merely UI-hidden).
    Credential/secret fields (password_hash, pin_hash, etc.) are ALWAYS stripped for every role.
    """
    stripped_creds = {
        k: v for k, v in record.items()
        if str(k).strip().lower() not in NEVER_EXPOSE_CREDENTIAL_FIELDS
    }
    if is_owner(user):
        return stripped_creds

    v2_role = role_v2_of(user)
    if tab_name in CONFIDENTIAL_TABS_NO_CACHE:
        if tab_name in {"EmployeeAdvances", "WorkforcePayments"} and v2_role == "ACCOUNTS" and workflow_context == "APPROVED_ADVANCE_DISBURSEMENT":
            return {
                k: v for k, v in stripped_creds.items()
                if str(k).strip().lower() in ACCOUNTS_ADVANCE_DISBURSEMENT_ALLOWED_FIELDS
            }
        if tab_name in {"Employees", "LabourMaster"}:
            # Non-owners (including PA, HR) never receive bank details or personal IDs
            return {
                k: v for k, v in stripped_creds.items()
                if str(k).strip().lower() not in CONFIDENTIAL_PERSONAL_FIELDS
            }
        # SalaryStructures, SalaryPayments, PayrollRuns, PayrollItems, SalaryReceipts: absent for PA and all non-owners
        return None

    return {
        k: v for k, v in stripped_creds.items()
        if str(k).strip().lower() not in CONFIDENTIAL_PERSONAL_FIELDS
    }


def filter_confidential_records(
    records: List[Dict[str, Any]],
    user: dict,
    *,
    tab_name: str = "",
    workflow_context: str = "GENERAL",
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for rec in records:
        clean = filter_confidential_record(rec, user, tab_name=tab_name, workflow_context=workflow_context)
        if clean is not None:
            filtered.append(clean)
    return filtered


def ui_role(role: str) -> str:
    """
    Preserve exact 12 Blueprint v2.1 roles when explicitly assigned, while maintaining
    legacy return strings only for purely legacy v1 role tokens when no v2 token is used.
    """
    value = str(role or "").strip().upper()
    if value in TWELVE_ROLES:
        return value
    if value in OWNERS:
        return "OWNER_ADMIN"
    if value == "PERSONAL_ASSISTANT":
        return "PA"
    if value == "ACCOUNTANT":
        return "ACCOUNTS"
    if value == "SALESMAN":
        return "FIELD_SALESMAN"
    if value in FACTORY_WORKERS:
        return "PRODUCTION"
    if value == "DISPATCH":
        return "SALES"
    if value in {"FREELANCER"}:
        return "FREELANCER"
    if value in {"SOCIAL_MEDIA_ECOMMERCE_MANAGER", "SOCIAL_MEDIA_MANAGER", "ECOMMERCE_MANAGER"}:
        return "SOCIAL_MEDIA_ECOMMERCE_MANAGER"
    if not value:
        return ""
    return CANONICAL_ROLE_V2_MAP.get(value, value)


def is_employee(user: dict) -> bool:
    return role_v2_of(user) in EMPLOYEE_ROLES or role_of(user) in EMPLOYEE_ROLES or raw_role_of(user) in EMPLOYEE_ROLES


def is_freelancer(user: dict) -> bool:
    return role_of(user) == "FREELANCER"


def is_accountant(user: dict) -> bool:
    return role_v2_of(user) == "ACCOUNTS" or role_of(user) == "ACCOUNTANT"


def is_social_media_manager(user: dict) -> bool:
    return role_of(user) == "SOCIAL_MEDIA_ECOMMERCE_MANAGER"


def portal_experience_for(user: dict) -> str:
    if is_owner(user):
        return "OWNER_ADMIN"
    return role_v2_of(user)
