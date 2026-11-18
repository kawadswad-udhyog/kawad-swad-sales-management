"""
Kawad Swad ERP — Blueprint v2.1 Schema, Governance, ID & Policy Registry.

Authoritative code-level catalog for:
- 15 functional database groups (255-tab cleaned workbook architecture)
- 46 forbidden legacy scratch tab prefixes (never recreate)
- 32 locked ID prefixes & format validation
- Confidential tables and restricted columns (RBAC field filtering contract)
- Pending CA/Owner financial & tax policies (fail-closed until approved)
- Discontinued retail pack weights (strictly {200, 500, 1000} grams)
- Lot quality release state machine (PENDING_QC -> RELEASED / ON_HOLD / REJECTED)
"""

import json
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import SALES_CA_POLICY_CONFIG_JSON


# ---------------------------------------------------------------------------
# 1. Retail Pack Weights & Quality Lifecycle Constants
# ---------------------------------------------------------------------------
VALID_RETAIL_PACK_WEIGHTS_G: Tuple[int, ...] = (200, 500, 1000)
DISCONTINUED_RETAIL_PACK_WEIGHTS_G: Tuple[int, ...] = (250, 400)

LOT_QUALITY_STATES: Tuple[str, ...] = (
    "PENDING_QC",
    "RELEASED",
    "ON_HOLD",
    "REJECTED",
)
# Legacy read compatibility (QUARANTINE maps conceptually to PENDING_QC / ON_HOLD for release blocking)
LOT_BLOCKED_STATES: Set[str] = {"PENDING_QC", "ON_HOLD", "REJECTED", "QUARANTINE", "RECALLED", ""}

GIG_WORKER_STATUSES: Tuple[str, ...] = ("SUBMITTED", "VERIFIED", "PAID")
EMPLOYEE_EMPLOYMENT_CLASSES: Tuple[str, ...] = ("FIXED_EMPLOYEE", "GIG_WORKER")


# ---------------------------------------------------------------------------
# 2. Forbidden Legacy Scratch Tabs (46 post-cleanup prefixes — NEVER RECREATE)
# ---------------------------------------------------------------------------
FORBIDDEN_SCRATCH_PREFIXES: Tuple[str, ...] = (
    "KS_P1_",
    "KS_P2_",
    "KS_P3_",
    "DBV5_",
    "DB_",
)
AUTHORIZED_NON_PREFIX_DICTIONARY_TAB = "DBV5_FIELD_DICTIONARY_3074"


def is_forbidden_scratch_tab(tab_name: str) -> bool:
    clean = str(tab_name or "").strip()
    if not clean:
        return True
    if clean == AUTHORIZED_NON_PREFIX_DICTIONARY_TAB:
        return False
    upper = clean.upper()
    return any(upper.startswith(prefix) for prefix in FORBIDDEN_SCRATCH_PREFIXES)


# ---------------------------------------------------------------------------
# 3. Locked 32 Official Business ID Prefixes
# ---------------------------------------------------------------------------
LOCKED_32_ID_PREFIXES: Dict[str, str] = {
    "PRD": "Products",
    "SKU": "ProductSKUs",
    "RM": "RawMaterials",
    "PKG": "PackagingMaterials",
    "CUST": "Customers",
    "SUP": "Suppliers",
    "USR": "Users",
    "EMP": "Employees",
    "LOT": "ProductLots",
    "MOV": "ProductionStockLedger",
    "PO": "PurchaseOrders",
    "PB": "ProductionBatches",
    "MCON": "MaterialConsumptions",
    "POUT": "ProductionOutputs",
    "PLOSS": "ProductionLosses",
    "PWE": "ProductionWorkEntries",
    "IPQC": "QualityChecks_IPQC",
    "FGQC": "QualityChecks_FGQC",
    "PKB": "PackagingBatches",
    "PKOUT": "PackagingOutputs",
    "SO": "SalesOrders",
    "SOI": "SalesOrderItems",
    "INV": "Sales",
    "INVI": "SaleItems",
    "RCPT": "Payments",
    "RCPTA": "PaymentAllocations",
    "JV": "JournalHeaders",
    "JVL": "JournalLines",
    "SAL": "SalaryPayments",
    "EADV": "EmployeeAdvances",
    "AUD": "AuditLog",
    "EXC": "ExceptionLogs",
}

_ID_FORMAT_RE = re.compile(r"^([A-Z]{2,6})-[A-Z0-9_-]{3,}$")


def is_valid_locked_id_prefix(identifier: str, expected_prefix: Optional[str] = None) -> bool:
    clean = str(identifier or "").strip().upper()
    m = _ID_FORMAT_RE.match(clean)
    if not m:
        return False
    prefix = m.group(1)
    if expected_prefix:
        return prefix == expected_prefix.upper()
    return prefix in LOCKED_32_ID_PREFIXES


# ---------------------------------------------------------------------------
# 4. Confidential Tables & Restricted Columns Contract
# ---------------------------------------------------------------------------
CONFIDENTIAL_TABS_NO_CACHE: Set[str] = {
    "SalaryStructures",
    "PayrollRuns",
    "PayrollItems",
    "WorkforcePayments",
    "SalaryReceipts",
    "SalaryIncentives",
    "LabourMaster",
    "SalaryPayments",
    "EmployeeAdvances",
    "Employees",
}

CONFIDENTIAL_PERSONAL_FIELDS: Set[str] = {
    "bank_details_reference",
    "bank_details",
    "bank_account_no",
    "bank_ifsc",
    "bank_account_credited",
    "ifsc_code",
    "account_number",
    "aadhaar",
    "aadhaar_no",
    "aadhaar_number",
    "pan",
    "pan_no",
    "pan_number",
    "passport",
    "passport_no",
    "document_references",
    "salary_structure_id",
    "basic_salary",
    "hra",
    "transport_allowance",
    "special_allowance",
    "pf_deduction",
    "tds_deduction",
    "net_amount",
    "gross_amount",
    "earned_basic",
    "base_salary",
    "net_paid",
    "gross_earnings",
    "address",
    "emergency_contact",
}

ACCOUNTS_ADVANCE_DISBURSEMENT_ALLOWED_FIELDS: Set[str] = {
    "advance_id",
    "payment_id",
    "reference_id",
    "employee_id",
    "recipient_id",
    "user_id",
    "employee_name",
    "recipient_name",
    "full_name",
    "payment_type",
    "amount",
    "approved_amount",
    "payment_method",
    "payment_reference",
    "payment_date",
    "status",
    "approved_by",
    "approved_at",
    "accounting_journal_ref",
    "notes",
    "created_at",
}


# ---------------------------------------------------------------------------
# 5. 15 Functional Database Groups & Header Governance
# ---------------------------------------------------------------------------
DATABASE_GROUPS_15: List[Dict[str, Any]] = [
    {
        "group_code": "00",
        "group_name": "Control & Setup",
        "module": "control",
        "workbook_tabs": ["Settings", "ApprovalRequests", "AccountingPeriods", "AuditLog", "ExceptionLogs", "IdAllocations", "DBV5_FIELD_DICTIONARY_3074"],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_XLSX",
    },
    {
        "group_code": "01",
        "group_name": "Identity, Roles & Security",
        "module": "security",
        "workbook_tabs": ["Users", "AuthUsers", "CustomRoles", "RevokedTokens"],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "02",
        "group_name": "Master Catalogue & Recipes",
        "module": "catalogue",
        "workbook_tabs": ["Products", "RawMaterials", "Recipes", "Suppliers", "Customers"],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "03",
        "group_name": "Procurement & Mill Intake",
        "module": "procurement",
        "workbook_tabs": ["PurchaseOrders", "PurchaseOrderItems", "GoodsReceipts", "GoodsReceiptItems", "SupplierReturns", "SupplierReturnItems", "MillingBatches"],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "04",
        "group_name": "Warehouse, Store & Raw Material Ledger",
        "module": "store",
        "workbook_tabs": ["RawMaterialLedger", "ProductionStockLedger", "ProductLots", "LotMovements", "StockDiscrepancies"],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "05",
        "group_name": "Production Manufacturing",
        "module": "production",
        "workbook_tabs": ["ProductionBatches", "MaterialConsumptions", "ProductionOutputs", "ProductionLosses", "ProductionWorkEntries"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "06",
        "group_name": "Packaging & Retail SKUs",
        "module": "packaging",
        "workbook_tabs": ["PackagingBatches", "PackagingOutputs"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "07",
        "group_name": "Quality Control & Food Safety",
        "module": "quality",
        "workbook_tabs": ["QualityChecks", "ProductLots", "ComplaintsRecalls"],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "08",
        "group_name": "Sales Orders, Invoicing & Field Route",
        "module": "sales",
        "workbook_tabs": ["Sales", "SaleItems", "Payments", "SalesmanStockLedger", "ShopVisits", "DailyClosing", "CustomerReturns", "CustomerReturnItems"],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "09",
        "group_name": "Distribution, Van Loading & Logistics",
        "module": "logistics",
        "workbook_tabs": ["VanLoadingPasses", "ProductionDispatches", "DistributionDispatches"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "10",
        "group_name": "E-Commerce & Marketplace Settlements",
        "module": "channels",
        "workbook_tabs": ["MarketplaceSettlements"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "11",
        "group_name": "General Ledger & Accounting",
        "module": "accounting",
        "workbook_tabs": ["ChartOfAccounts", "JournalHeaders", "JournalLines", "SupplierBills", "SupplierPayments", "Expenses", "CashLedger"],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "12",
        "group_name": "Workforce, Attendance, Gig Wages & Confidential Payroll",
        "module": "workforce",
        "workbook_tabs": ["Employees", "EmployeeAttendance", "SalaryStructures", "PayrollRuns", "PayrollItems", "SalaryPayments", "EmployeeAdvances", "WorkforcePayments", "SalaryReceipts", "LabourMaster", "LabourAttendance", "LabourWorkEntries", "LabourWageRecords", "Workers", "WorkerAttendance", "WorkAssignments"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "13",
        "group_name": "Compliance, Statutory, Assets & Maintenance",
        "module": "compliance_assets",
        "workbook_tabs": ["ComplianceRecords", "AssetsMaintenance"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "14",
        "group_name": "Official Reports, Closings & Planning",
        "module": "reports",
        "workbook_tabs": ["RPT_TrialBalance", "RPT_StockStatus", "RPT_SalesAndReceivables"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
]

# Tab mapping for extended v2 tables whose exact .xlsx column names were not supplied in workspace
EXTENDED_V2_TAB_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "Employees": {"prefix": "EMP", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "SalaryPayments": {"prefix": "SAL", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "EmployeeAdvances": {"prefix": "EADV", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "DistributionDispatches": {"prefix": "DSP", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "MarketplaceSettlements": {"prefix": "CHN", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "ComplianceRecords": {"prefix": "CMP", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "AssetsMaintenance": {"prefix": "AST", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "ExceptionLogs": {"prefix": "EXC", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "RPT_TrialBalance": {"prefix": "RPT", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "RPT_StockStatus": {"prefix": "RPT", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
    "RPT_SalesAndReceivables": {"prefix": "RPT", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False},
}


# ---------------------------------------------------------------------------
# 6. Pending CA / Owner Policy Registry (Fail-Closed Automation Gate)
# ---------------------------------------------------------------------------
DEFAULT_CA_POLICIES: Dict[str, Dict[str, Any]] = {
    "hsn_gst_tax_rates": {
        "policy_key": "hsn_gst_tax_rates",
        "label": "HSN & GST Tax Rate Schedule",
        "status": "PENDING_CA_APPROVAL",
        "value": None,
        "allowed_values": ["EXEMPT_0", "GST_5", "GST_12", "GST_18", "CUSTOM_BY_HSN"],
        "blocks_automated_posting": True,
        "notes": "Requires CA sign-off on HSN classification and GST rates per SKU before automated GST posting.",
    },
    "inventory_valuation_method": {
        "policy_key": "inventory_valuation_method",
        "label": "Inventory Valuation Method",
        "status": "PENDING_CA_APPROVAL",
        "value": None,
        "allowed_values": ["FIFO", "WEIGHTED_AVERAGE"],
        "blocks_automated_posting": True,
        "notes": "Requires CA choice between FIFO and WEIGHTED_AVERAGE for authoritative stock & COGS valuation.",
    },
    "overhead_and_labour_allocation_basis": {
        "policy_key": "overhead_and_labour_allocation_basis",
        "label": "Production Overhead & Labour Allocation Basis",
        "status": "PENDING_CA_APPROVAL",
        "value": None,
        "allowed_values": ["DIRECT_KG", "BATCH_HOURS", "STANDARD_ABSORPTION"],
        "blocks_automated_posting": True,
        "notes": "Requires CA approval for factory overhead & labour capitalization rules.",
    },
    "depreciation_policy": {
        "policy_key": "depreciation_policy",
        "label": "Fixed Assets Depreciation Policy",
        "status": "PENDING_CA_APPROVAL",
        "value": None,
        "allowed_values": ["WDV_INCOME_TAX", "SLM_COMPANIES_ACT"],
        "blocks_automated_posting": True,
        "notes": "Requires CA approval for WDV/SLM asset block schedules before automated depreciation journals.",
    },
}

_RUNTIME_POLICY_OVERRIDES: Dict[str, Dict[str, Any]] = {}


def get_ca_policies() -> Dict[str, Dict[str, Any]]:
    """Return merged CA/Owner policy configuration. Never hardcodes unapproved tax/accounting choices."""
    policies = {k: dict(v) for k, v in DEFAULT_CA_POLICIES.items()}
    if SALES_CA_POLICY_CONFIG_JSON:
        try:
            env_overrides = json.loads(SALES_CA_POLICY_CONFIG_JSON)
            if isinstance(env_overrides, dict):
                for key, override in env_overrides.items():
                    if key in policies and isinstance(override, dict):
                        policies[key].update(override)
        except Exception:
            pass
    for key, override in _RUNTIME_POLICY_OVERRIDES.items():
        if key in policies:
            policies[key].update(override)
    return policies


def set_ca_policy_override(policy_key: str, *, status: str, value: Any, approved_by: str, notes: str = "") -> Dict[str, Any]:
    if policy_key not in DEFAULT_CA_POLICIES:
        raise ValueError(f"Unknown policy_key: {policy_key}")
    clean_status = str(status or "").strip().upper()
    if clean_status not in {"APPROVED", "PENDING_CA_APPROVAL"}:
        raise ValueError("Policy status must be APPROVED or PENDING_CA_APPROVAL")
    allowed = DEFAULT_CA_POLICIES[policy_key]["allowed_values"]
    if clean_status == "APPROVED" and value not in allowed:
        raise ValueError(f"Approved value for {policy_key} must be one of {allowed}")
    _RUNTIME_POLICY_OVERRIDES[policy_key] = {
        "status": clean_status,
        "value": value,
        "approved_by": approved_by,
        "notes": notes or DEFAULT_CA_POLICIES[policy_key]["notes"],
    }
    return get_ca_policies()[policy_key]


def assert_ca_policy_approved(policy_key: str) -> Dict[str, Any]:
    """Fail-closed gate blocking automated tax/valuation/depreciation posting while PENDING_CA_APPROVAL."""
    policies = get_ca_policies()
    if policy_key not in policies:
        raise ValueError(f"Unknown CA policy '{policy_key}'.")
    policy = policies[policy_key]
    if str(policy.get("status", "")).upper() != "APPROVED" or not policy.get("value"):
        raise PermissionError(
            f"Automated posting blocked: Policy '{policy_key}' is {policy.get('status', 'PENDING_CA_APPROVAL')}."
        )
    return policy


def quantize_money(val: Any) -> Decimal:
    return Decimal(str(val or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def quantize_weight_kg(val: Any) -> Decimal:
    return Decimal(str(val or "0")).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
