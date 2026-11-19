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
    # Reconciled to canonical 'ExceptionRegister' matching AuditAndExceptions.gs in the 255-tab workbook.
    "EXC": "ExceptionRegister",
}

DEPRECATED_TAB_ALIASES: Dict[str, str] = {
    "ExceptionLogs": "ExceptionRegister",
}

TAB_RECONCILIATION_CONFLICTS: Dict[str, Dict[str, Any]] = {
    "EXC": {
        "canonical_prefix": "EXC",
        "canonical_tab": "ExceptionRegister",
        "snapshot_tab": "ExceptionRegister",
        "draft_tab": "ExceptionLogs",
        "status": "RECONCILED_TO_EXCEPTION_REGISTER",
        "header_status": "PENDING_OWNER_MAPPING",
        "reconciled_source": "AuditAndExceptions.gs (verified 255-tab workbook)",
        "notes": (
            "Tab name conflict reconciled to canonical 'ExceptionRegister' matching AuditAndExceptions.gs "
            "in the verified 255-tab workbook (legacy draft alias 'ExceptionLogs' deprecated). "
            "Physical Row-1 column headers remain PENDING_OWNER_MAPPING until supplied by Owner."
        ),
    },
    "PKG_PREFIX_COLLISION": {
        "canonical_prefix": "PKG",
        "snapshot_tab": "PackagingMaterials",
        "draft_tab": "PackagingBatches",
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "notes": (
            "Legacy sheets.ID_PREFIXES uses 'PKG' for PackagingBatches while LOCKED_32_ID_PREFIXES assigns "
            "'PKG' -> PackagingMaterials and 'PKB' -> PackagingBatches. Apps Script single-write-owner "
            "allocates canonical v2 PKB-* / PKG-* prefixes while legacy reads accept existing historical IDs."
        ),
    },
}

LEGACY_TO_LOCKED_ID_PREFIX_ALIASES: Dict[str, Dict[str, str]] = {
    "Customers": {"legacy_prefix": "CUS", "locked_prefix": "CUST"},
    "JournalHeaders": {"legacy_prefix": "JRN", "locked_prefix": "JV"},
    "JournalLines": {"legacy_prefix": "JLN", "locked_prefix": "JVL"},
    "PackagingBatches": {"legacy_prefix": "PKG", "locked_prefix": "PKB"},
    "Payments": {"legacy_prefix": "PAY", "locked_prefix": "RCPT"},
    "ProductionBatches": {"legacy_prefix": "PRB", "locked_prefix": "PB"},
    "ProductionStockLedger": {"legacy_prefix": "PST", "locked_prefix": "MOV"},
    "RawMaterials": {"legacy_prefix": "RWM", "locked_prefix": "RM"},
    "SaleItems": {"legacy_prefix": "ITEM", "locked_prefix": "INVI"},
    "Sales": {"legacy_prefix": "SALE", "locked_prefix": "INV"},
}

SCHEMA_HEADER_VARIANCES: Dict[str, Dict[str, Any]] = {
    "Settings": {
        "status": "VERIFIED_CORE",
        "source": "docs/SALES_MANAGEMENT_SCHEMA.md",
        "headers": ["setting_key", "setting_value", "description"],
        "id_exception": (
            "Settings is keyed by logical 'setting_key' and intentionally has no numeric sequence prefix "
            "in sheets.ID_PREFIXES (all 66 other REQUIRED_TABS entries have sequential prefixes)."
        ),
    },
    "Suppliers": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "required_tabs_columns": 12,
        "physical_router_fields": 14,
        "missing_from_required_tabs": ["payment_terms", "opening_balance"],
        "notes": (
            "purchasing.py create/update supplier writes 14 logical fields including payment_terms and "
            "opening_balance whereas REQUIRED_TABS['Suppliers'] has 12 columns. Reconcile physical Row-1 "
            "headers against workbook before strict header pruning."
        ),
    },
    "CustomRoles": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": ["deleted", "active"],
        "notes": "users.py DELETE_CUSTOM_ROLE transmits soft-delete flags deleted/active which are omitted from REQUIRED_TABS['CustomRoles'].",
    },
    "SalaryIncentives": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": [
            "record_id", "period_start", "period_end", "record_type", "eligible_kg",
            "completed_100kg_blocks", "rate", "calculated_amount", "approved_amount",
            "approval_status", "paid_datetime", "payment_reference",
        ],
        "notes": "salary.py reads/writes record_id, period_start/period_end, calculated_amount/approved_amount whereas REQUIRED_TABS['SalaryIncentives'] lists legacy columns (incentive_id, period_month, incentive_amount).",
    },
    "RawMaterials": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": [
            "active", "notes", "opening_stock", "opening_stock_verified",
            "verification_status", "verified_physical_stock", "verified_by", "verified_at",
        ],
        "notes": "production.py writes active/notes and opening-stock verification metadata beyond the 9 columns in REQUIRED_TABS['RawMaterials'].",
    },
    "Products": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": ["recipe_id"],
        "notes": "products.py accepts/writes optional recipe_id linkage omitted from REQUIRED_TABS['Products'].",
    },
    "Workers": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": ["created_by"],
        "notes": "production.py CREATE_WORKER records created_by which is omitted from REQUIRED_TABS['Workers'].",
    },
    "Customers": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": ["notes"],
        "notes": "customers.py reads/writes notes which is omitted from REQUIRED_TABS['Customers'].",
    },
    "Sales": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": ["cash_collected", "credit_amount", "owner_credit_approval_id"],
        "notes": "sales.py writes cash_collected, credit_amount, and owner_credit_approval_id beyond REQUIRED_TABS['Sales'].",
    },
    "ProductionBatches": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": [
            "gross_output_kg", "process_loss_kg", "loss_reason",
            "saleable_output_kg", "unexplained_variance_kg", "ingredients",
        ],
        "notes": "production.py CREATE_PRODUCTION_BATCH includes extended reconciliation & ingredient columns omitted from REQUIRED_TABS['ProductionBatches'].",
    },
    "PackagingBatches": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": [
            "recipe_id", "bulk_batch_id", "bulk_product_key", "bulk_quantity_consumed_kg",
        ],
        "notes": "production.py RECORD_PACKAGING_BATCH writes recipe/bulk linkage fields omitted from REQUIRED_TABS['PackagingBatches'].",
    },
    "Expenses": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": ["post_accounting_journal"],
        "notes": "expenses.py passes governance flag post_accounting_journal inside REVIEW_EXPENSE update payload.",
    },
    "ShopVisits": {
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "missing_from_required_tabs": ["shop_name_snapshot", "visit_outcome", "order_taken", "follow_up_date", "next_action"],
        "notes": "visits.py uses shop_name_snapshot/visit_outcome/order_taken/follow_up_date/next_action whereas REQUIRED_TABS['ShopVisits'] lists customer_name_snapshot/purpose/outcome.",
    },
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
    "bank_name",
    "bank_account_no",
    "bank_ifsc",
    "bank_account_credited",
    "ifsc_code",
    "account_number",
    "upi_id",
    "aadhaar",
    "aadhaar_no",
    "aadhaar_number",
    "aadhar",
    "aadhar_no",
    "pan",
    "pan_no",
    "pan_number",
    "passport",
    "passport_no",
    "gov_id",
    "id_proof",
    "personal_id",
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
# 5. Official 15 Blueprint v2.1 Database Groups & 255-Tab Governance
# ---------------------------------------------------------------------------
DATABASE_GROUPS_15: List[Dict[str, Any]] = [
    {
        "group_code": "00",
        "group_name": "Control & Setup",
        "module": "control",
        "workbook_tabs": [
            "Settings", "ApprovalRequests", "IdAllocations",
            "RevokedTokens", "AuthUsers", "CustomRoles", "DBV5_FIELD_DICTIONARY_3074",
        ],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_XLSX",
    },
    {
        "group_code": "01",
        "group_name": "Business & Master Data",
        "module": "catalogue",
        "workbook_tabs": ["Users", "Products", "ProductSKUs", "RawMaterials", "PackagingMaterials", "Recipes"],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "02",
        "group_name": "Procurement & Supplier",
        "module": "procurement",
        "workbook_tabs": [
            "Suppliers", "PurchaseOrders", "PurchaseOrderItems",
            "GoodsReceipts", "GoodsReceiptItems", "SupplierBills",
            "SupplierPayments", "SupplierReturns", "SupplierReturnItems",
        ],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "03",
        "group_name": "Inventory & Warehousing",
        "module": "store",
        "workbook_tabs": [
            "RawMaterialLedger", "ProductionStockLedger", "ProductLots",
            "LotMovements", "StockDiscrepancies", "IncompleteTransactions",
        ],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "04",
        "group_name": "Milling & Production",
        "module": "production",
        "workbook_tabs": [
            "MillingBatches", "ProductionBatches", "MaterialConsumptions",
            "ProductionOutputs", "ProductionLosses", "ProductionWorkEntries",
        ],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "05",
        "group_name": "Quality & Food Safety",
        "module": "quality",
        "workbook_tabs": [
            "QualityChecks", "QualityChecks_IPQC", "QualityChecks_FGQC",
            "ProductLots", "ComplaintsRecalls",
        ],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "06",
        "group_name": "Packaging & Finished Goods",
        "module": "packaging",
        "workbook_tabs": ["PackagingBatches", "PackagingOutputs"],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "07",
        "group_name": "Sales & Customer",
        "module": "sales",
        "workbook_tabs": [
            "Customers", "SalesOrders", "SalesOrderItems", "Sales", "SaleItems",
            "Payments", "PaymentAllocations", "SalesmanStockLedger",
            "ShopVisits", "DailyClosing", "CustomerReturns", "CustomerReturnItems",
        ],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "08",
        "group_name": "Channel, Marketplace & Marketing",
        "module": "channels",
        "workbook_tabs": ["MarketplaceSettlements"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "09",
        "group_name": "Distribution & Logistics",
        "module": "logistics",
        "workbook_tabs": ["VanLoadingPasses", "ProductionDispatches", "DistributionDispatches"],
        "header_mapping_status": "VERIFIED_CORE_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "10",
        "group_name": "Finance & Accounting",
        "module": "accounting",
        "workbook_tabs": [
            "ChartOfAccounts", "JournalHeaders", "JournalLines",
            "AccountingPeriods", "Expenses", "CashLedger",
        ],
        "header_mapping_status": "VERIFIED_CORE",
    },
    {
        "group_code": "11",
        "group_name": "Workforce & Payroll",
        "module": "workforce",
        "workbook_tabs": [
            "Employees", "EmployeeDocuments", "EmployeeAttendance",
            "WorkAssignments", "WorkActivityLogs", "SalaryStructures",
            "PayrollRuns", "PayrollItems", "SalaryPayments", "SalaryIncentives",
            "EmployeeAdvances", "WorkforcePayments", "SalaryReceipts",
            "FreelancerProjects", "FreelancerMilestones",
            "LabourMaster", "LabourAttendance", "LabourWorkEntries",
            "LabourWageRecords", "Workers", "WorkerAttendance", "WorkforceAuditLogs",
        ],
        "header_mapping_status": "VERIFIED_WORKFORCE_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "12",
        "group_name": "Governance, Compliance & Audit",
        "module": "compliance_assets",
        "workbook_tabs": ["AuditLog", "ExceptionRegister", "ComplianceRecords"],
        "header_mapping_status": "VERIFIED_AUDIT_AND_PENDING_EXTENDED",
    },
    {
        "group_code": "13",
        "group_name": "Assets, Environment & Risk",
        "module": "compliance_assets",
        "workbook_tabs": ["AssetsMaintenance"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
    {
        "group_code": "14",
        "group_name": "Reports & Planning",
        "module": "reports",
        "workbook_tabs": ["RPT_TrialBalance", "RPT_StockStatus", "RPT_SalesAndReceivables"],
        "header_mapping_status": "PENDING_OWNER_MAPPING",
    },
]

# Extended / unverified Blueprint v2.1 tabs whose exact .xlsx Row-1 headers have NOT been supplied in repo.
# NEVER invent prefixes or auto-create these tabs; mark PENDING_OWNER_MAPPING or CONFLICT_RECONCILIATION_REQUIRED.
EXTENDED_V2_TAB_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "ProductSKUs": {"prefix": "SKU", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "01"},
    "PackagingMaterials": {"prefix": "PKG", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "01"},
    "MaterialConsumptions": {"prefix": "MCON", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "04"},
    "ProductionOutputs": {"prefix": "POUT", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "04"},
    "ProductionLosses": {"prefix": "PLOSS", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "04"},
    "ProductionWorkEntries": {"prefix": "PWE", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "04"},
    "QualityChecks_IPQC": {"prefix": "IPQC", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "05"},
    "QualityChecks_FGQC": {"prefix": "FGQC", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "05"},
    "PackagingOutputs": {"prefix": "PKOUT", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "06"},
    "SalesOrders": {"prefix": "SO", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "07"},
    "SalesOrderItems": {"prefix": "SOI", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "07"},
    "PaymentAllocations": {"prefix": "RCPTA", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "07"},
    "Employees": {"prefix": "EMP", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "11"},
    "SalaryPayments": {"prefix": "SAL", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "11"},
    "EmployeeAdvances": {"prefix": "EADV", "prefix_status": "LOCKED", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "11"},
    "DistributionDispatches": {"prefix": None, "prefix_status": "PENDING_OWNER_MAPPING", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "09"},
    "MarketplaceSettlements": {"prefix": None, "prefix_status": "PENDING_OWNER_MAPPING", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "08"},
    "ComplianceRecords": {"prefix": None, "prefix_status": "PENDING_OWNER_MAPPING", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "12"},
    "AssetsMaintenance": {"prefix": None, "prefix_status": "PENDING_OWNER_MAPPING", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "13"},
    "ExceptionRegister": {
        "prefix": "EXC",
        "prefix_status": "LOCKED",
        "header_status": "PENDING_OWNER_MAPPING",
        "tab_name_reconciled": True,
        "reconciled_from": "AuditAndExceptions.gs",
        "auto_create": False,
        "group_code": "12",
    },
    "RPT_TrialBalance": {"prefix": None, "prefix_status": "PENDING_OWNER_MAPPING", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "14"},
    "RPT_StockStatus": {"prefix": None, "prefix_status": "PENDING_OWNER_MAPPING", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "14"},
    "RPT_SalesAndReceivables": {"prefix": None, "prefix_status": "PENDING_OWNER_MAPPING", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "14"},
    "DBV5_FIELD_DICTIONARY_3074": {"prefix": None, "prefix_status": "NOT_APPLICABLE", "header_status": "PENDING_OWNER_MAPPING", "auto_create": False, "group_code": "00"},
}

# Unverified / conflicting tabs that must FAIL CLOSED on writes until Owner supplies canonical Row-1 headers.
PENDING_OWNER_MAPPING_TABS: Set[str] = {
    tab for tab, meta in EXTENDED_V2_TAB_CONTRACTS.items()
    if meta.get("header_status") in {"PENDING_OWNER_MAPPING", "CONFLICT_RECONCILIATION_REQUIRED"}
}

_TAB_TO_LOCKED_PREFIX: Dict[str, str] = {tab: pfx for pfx, tab in LOCKED_32_ID_PREFIXES.items()}


def build_table_schema_registry(required_tabs: Dict[str, List[str]]) -> Dict[str, Dict[str, Any]]:
    """
    Machine-readable Schema Registry merging:
    - All verified core + workforce tables from REQUIRED_TABS / workforceSchemaUpgrade_2026-11-03-v1.gs
    - All extended 255-tab Blueprint v2.1 entries marked PENDING_OWNER_MAPPING / CONFLICT_RECONCILIATION_REQUIRED
    Never fabricates Row-1 headers for tables missing from repo truth.
    """
    group_lookup: Dict[str, str] = {}
    for g in DATABASE_GROUPS_15:
        for t in g.get("workbook_tabs", []):
            group_lookup.setdefault(t, g["group_code"])

    registry: Dict[str, Dict[str, Any]] = {}
    for tab_name, headers in required_tabs.items():
        alias_info = LEGACY_TO_LOCKED_ID_PREFIX_ALIASES.get(tab_name)
        variance_info = SCHEMA_HEADER_VARIANCES.get(tab_name)
        registry[tab_name] = {
            "tab_name": tab_name,
            "group_code": group_lookup.get(tab_name, "00"),
            "status": (variance_info or {}).get("status", "VERIFIED_CORE"),
            "headers": list(headers),
            "header_count": len(headers),
            "locked_id_prefix": _TAB_TO_LOCKED_PREFIX.get(tab_name),
            "legacy_id_prefix": (alias_info or {}).get("legacy_prefix"),
            "id_prefix_reconciled": alias_info is None,
            "header_variance": variance_info,
            "confidential": tab_name in CONFIDENTIAL_TABS_NO_CACHE,
            "auto_create": False,
        }

    for tab_name, contract in EXTENDED_V2_TAB_CONTRACTS.items():
        if tab_name in registry:
            continue
        registry[tab_name] = {
            "tab_name": tab_name,
            "group_code": contract.get("group_code", group_lookup.get(tab_name, "00")),
            "status": contract.get("header_status", "PENDING_OWNER_MAPPING"),
            "headers": None,
            "header_count": 0,
            "locked_id_prefix": contract.get("prefix"),
            "prefix_status": contract.get("prefix_status", "PENDING_OWNER_MAPPING"),
            "confidential": tab_name in CONFIDENTIAL_TABS_NO_CACHE,
            "auto_create": False,
        }

    return registry


def get_table_schema_registry() -> Dict[str, Dict[str, Any]]:
    from app.sheets import REQUIRED_TABS
    return build_table_schema_registry(REQUIRED_TABS)


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
