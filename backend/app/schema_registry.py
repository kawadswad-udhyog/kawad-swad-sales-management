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

from app.config import (
    SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON,
    SALES_CA_POLICY_CONFIG_JSON,
)

WORKBOOK_TARGET_TAB_COUNT: int = 255


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

_TAB_TO_LOCKED_PREFIX: Dict[str, str] = {tab: pfx for pfx, tab in LOCKED_32_ID_PREFIXES.items()}

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
            "'PKG' -> PackagingMaterials and 'PKB' -> PackagingBatches. New PackagingBatches governed allocations "
            "strictly require 'PKB-*' (PKG-* is rejected on new PackagingBatches writes to prevent collision with "
            "PackagingMaterials) while historical PKG-* rows remain readable on legacy reads."
        ),
    },
    "RCPT_PREFIX_COLLISION": {
        "canonical_prefix": "RCPT",
        "snapshot_tab": "Payments",
        "draft_tab": "SalaryReceipts",
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "notes": (
            "Legacy sheets.ID_PREFIXES assigns 'RCPT' to SalaryReceipts and 'PAY' to Payments, while "
            "LOCKED_32_ID_PREFIXES assigns 'RCPT' to Payments. Reconcile SalaryReceipts prefix with Owner "
            "and Apps Script allocator during prefix cutover."
        ),
    },
    "SAL_PREFIX_COLLISION": {
        "canonical_prefix": "SAL",
        "snapshot_tab": "SalaryPayments",
        "draft_tab": "SalaryIncentives",
        "status": "CONFLICT_RECONCILIATION_REQUIRED",
        "notes": (
            "Legacy sheets.ID_PREFIXES assigns 'SAL' to SalaryIncentives while LOCKED_32_ID_PREFIXES assigns "
            "'SAL' to SalaryPayments. Reconcile SalaryIncentives vs SalaryPayments allocation sequence with Owner."
        ),
    },
}

LEGACY_TO_LOCKED_ID_PREFIX_ALIASES: Dict[str, Dict[str, Any]] = {
    "Customers": {
        "legacy_prefix": "CUS",
        "locked_prefix": "CUST",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "JournalHeaders": {
        "legacy_prefix": "JRN",
        "locked_prefix": "JV",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "JournalLines": {
        "legacy_prefix": "JLN",
        "locked_prefix": "JVL",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "PackagingBatches": {
        "legacy_prefix": "PKG",
        "locked_prefix": "PKB",
        "allow_on_read": True,
        "allow_on_new_allocation": False,
        "collides_with_locked_tab": "PackagingMaterials",
        "migration_status": "PKG_BLOCKED_ON_NEW_ALLOCATION_PKB_REQUIRED",
    },
    "Payments": {
        "legacy_prefix": "PAY",
        "locked_prefix": "RCPT",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "ProductionBatches": {
        "legacy_prefix": "PRB",
        "locked_prefix": "PB",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "ProductionStockLedger": {
        "legacy_prefix": "PST",
        "locked_prefix": "MOV",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "RawMaterials": {
        "legacy_prefix": "RWM",
        "locked_prefix": "RM",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "SaleItems": {
        "legacy_prefix": "ITEM",
        "locked_prefix": "INVI",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
    "Sales": {
        "legacy_prefix": "SALE",
        "locked_prefix": "INV",
        "allow_on_read": True,
        "allow_on_new_allocation": True,
        "collides_with_locked_tab": None,
        "migration_status": "TRANSITIONAL_LEGACY_ALIAS_PENDING_CUTOVER",
    },
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


def get_locked_prefix_for_tab(tab_name: str) -> Optional[str]:
    clean_tab = str(tab_name or "").strip()
    return _TAB_TO_LOCKED_PREFIX.get(clean_tab)


def get_allowed_id_prefixes_for_tab(
    tab_name: str,
    *,
    for_new_allocation: bool = True,
    explicit_locked_prefix: Optional[str] = None,
) -> Tuple[str, ...]:
    """
    Return the centrally governed tuple of allowed ID prefixes for a table.
    - Always includes the table's canonical locked prefix (or explicit_locked_prefix when supplied).
    - Includes a transitional legacy prefix ONLY when registered in LEGACY_TO_LOCKED_ID_PREFIX_ALIASES
      and permitted for the requested mode (`allow_on_new_allocation` vs `allow_on_read`).
    - For `PackagingBatches`, `PKG` collides with `PackagingMaterials`, so `PKG` is permitted on
      historical reads (`for_new_allocation=False`) and strictly rejected on new governed allocations
      (`for_new_allocation=True`), where only `PKB` is valid.
    """
    clean_tab = str(tab_name or "").strip()
    canonical = (str(explicit_locked_prefix or "").strip().upper() or _TAB_TO_LOCKED_PREFIX.get(clean_tab, ""))
    allowed: List[str] = []
    if canonical:
        allowed.append(canonical)
    alias_info = LEGACY_TO_LOCKED_ID_PREFIX_ALIASES.get(clean_tab)
    if alias_info:
        legacy_prefix = str(alias_info.get("legacy_prefix") or "").strip().upper()
        permit_legacy = bool(
            alias_info.get("allow_on_new_allocation", False)
            if for_new_allocation
            else alias_info.get("allow_on_read", True)
        )
        if legacy_prefix and permit_legacy and legacy_prefix not in allowed:
            allowed.append(legacy_prefix)
    return tuple(allowed)


def validate_table_id_prefix(
    tab_name: str,
    identifier: str,
    *,
    for_new_allocation: bool = True,
    explicit_locked_prefix: Optional[str] = None,
) -> bool:
    """
    Validate an identifier against the centralized table prefix contract.
    Rejects malformed IDs, wrong-table prefixes, and colliding legacy prefixes (e.g. PKG-* on new
    PackagingBatches allocations).
    """
    clean = str(identifier or "").strip().upper()
    if not clean:
        return False
    allowed = get_allowed_id_prefixes_for_tab(
        tab_name,
        for_new_allocation=for_new_allocation,
        explicit_locked_prefix=explicit_locked_prefix,
    )
    if not allowed:
        return True
    m = _ID_FORMAT_RE.match(clean)
    if not m:
        return False
    prefix = m.group(1)
    return prefix in allowed


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
            "ComplaintsRecalls",
        ],
        # Canonical ownership of ProductLots resides in Group 03 (Inventory & Warehousing);
        # Group 05 references ProductLots for QC release/hold/recall workflows without duplicate placement.
        "referenced_tabs": ["ProductLots"],
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

# Unverified / conflicting extended tabs that must FAIL CLOSED on writes until Owner supplies canonical Row-1 headers.
PENDING_OWNER_MAPPING_TABS: Set[str] = {
    tab for tab, meta in EXTENDED_V2_TAB_CONTRACTS.items()
    if meta.get("header_status") in {"PENDING_OWNER_MAPPING", "CONFLICT_RECONCILIATION_REQUIRED"}
}

# Core REQUIRED_TABS tables with unresolved Row-1 header conflicts (12 tables / 46 declared missing fields).
# Writes MUST FAIL CLOSED until Owner confirms physical Row-1 headers and an approved mapping.
CONFLICTING_CORE_SCHEMA_TABS: Set[str] = {
    tab for tab, meta in SCHEMA_HEADER_VARIANCES.items()
    if str(meta.get("status", "")).upper() == "CONFLICT_RECONCILIATION_REQUIRED"
}

WRITE_BLOCKED_SCHEMA_TABS: Set[str] = PENDING_OWNER_MAPPING_TABS | CONFLICTING_CORE_SCHEMA_TABS

_RUNTIME_CORE_SCHEMA_RECONCILIATIONS: Dict[str, Dict[str, Any]] = {}


def get_approved_core_schema_reconciliations() -> Dict[str, Dict[str, Any]]:
    """
    Return Owner-approved core schema reconciliations (default EMPTY — fail-closed).
    Only entries with status == 'RECONCILED_OWNER_APPROVED', non-empty approved_by, and non-empty
    verified physical headers list are accepted.
    """
    approved: Dict[str, Dict[str, Any]] = {}
    if SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON:
        try:
            raw = json.loads(SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON)
            if isinstance(raw, dict):
                for tab, entry in raw.items():
                    if (
                        tab in CONFLICTING_CORE_SCHEMA_TABS
                        and isinstance(entry, dict)
                        and str(entry.get("status", "")).strip().upper() == "RECONCILED_OWNER_APPROVED"
                        and str(entry.get("approved_by", "")).strip()
                        and isinstance(entry.get("headers"), list)
                        and len(entry["headers"]) > 0
                    ):
                        approved[tab] = dict(entry)
        except Exception:
            pass
    for tab, entry in _RUNTIME_CORE_SCHEMA_RECONCILIATIONS.items():
        if (
            tab in CONFLICTING_CORE_SCHEMA_TABS
            and str(entry.get("status", "")).strip().upper() == "RECONCILED_OWNER_APPROVED"
            and str(entry.get("approved_by", "")).strip()
            and isinstance(entry.get("headers"), list)
            and len(entry["headers"]) > 0
        ):
            approved[tab] = dict(entry)
    return approved


def approve_core_schema_reconciliation(
    tab_name: str,
    *,
    headers: List[str],
    approved_by: str,
    notes: str = "",
) -> Dict[str, Any]:
    """Register an explicit Owner-approved reconciliation for a conflicting core tab."""
    clean_tab = str(tab_name or "").strip()
    if clean_tab not in CONFLICTING_CORE_SCHEMA_TABS:
        raise ValueError(f"Tab '{clean_tab}' is not in CONFLICTING_CORE_SCHEMA_TABS.")
    clean_approver = str(approved_by or "").strip()
    if not clean_approver:
        raise ValueError("approved_by is required to approve core schema reconciliation.")
    clean_headers = [str(h or "").strip() for h in (headers or []) if str(h or "").strip()]
    if not clean_headers or len(clean_headers) != len(set(clean_headers)):
        raise ValueError("Verified non-empty unique physical Row-1 headers are required.")
    entry = {
        "tab_name": clean_tab,
        "status": "RECONCILED_OWNER_APPROVED",
        "headers": clean_headers,
        "approved_by": clean_approver,
        "notes": notes or f"Owner-approved physical Row-1 header reconciliation for {clean_tab}.",
    }
    _RUNTIME_CORE_SCHEMA_RECONCILIATIONS[clean_tab] = entry
    return dict(entry)


def clear_runtime_core_schema_reconciliations() -> None:
    """Reset in-process Owner core schema reconciliation overrides (used by tests / resets)."""
    _RUNTIME_CORE_SCHEMA_RECONCILIATIONS.clear()


def get_schema_write_block_reason(tab_name: str) -> Optional[Dict[str, Any]]:
    """
    Fail-closed write gate for both:
    1. Unmapped extended Blueprint v2.1 tabs (PENDING_OWNER_MAPPING_TABS — 24 tabs).
    2. Unreconciled conflicting core tabs (CONFLICTING_CORE_SCHEMA_TABS — 12 tabs in SCHEMA_HEADER_VARIANCES).
    Returns None ONLY when the tab's schema contract is reconciled and write-eligible.
    """
    clean_tab = str(tab_name or "").strip()
    if clean_tab in PENDING_OWNER_MAPPING_TABS:
        conflict = next(
            (
                c for c in TAB_RECONCILIATION_CONFLICTS.values()
                if clean_tab in {c.get("snapshot_tab"), c.get("draft_tab"), c.get("canonical_tab")}
            ),
            None,
        )
        error_code = str((conflict or {}).get("status") or "PENDING_OWNER_MAPPING")
        return {
            "tab_name": clean_tab,
            "error_code": error_code,
            "dependency": "OWNER_SCHEMA_MAPPING_DEPENDENCY",
            "message": (
                f"Governed write blocked for '{clean_tab}' ({error_code}): "
                "Canonical Row-1 workbook headers have not been supplied or reconciled by Owner. Data was NOT SAVED."
            ),
        }

    if clean_tab in CONFLICTING_CORE_SCHEMA_TABS:
        approved = get_approved_core_schema_reconciliations()
        if clean_tab not in approved:
            variance = SCHEMA_HEADER_VARIANCES.get(clean_tab) or {}
            missing_fields = list(variance.get("missing_from_required_tabs") or [])
            missing_preview = ", ".join(missing_fields) if missing_fields else "unreconciled columns"
            return {
                "tab_name": clean_tab,
                "error_code": "CORE_SCHEMA_CONFLICT_UNRECONCILED",
                "dependency": "OWNER_SCHEMA_RECONCILIATION_DEPENDENCY",
                "missing_from_required_tabs": missing_fields,
                "message": (
                    f"Governed write blocked for '{clean_tab}' (CONFLICT_RECONCILIATION_REQUIRED): "
                    f"Schema conflict on {len(missing_fields)} field(s) [{missing_preview}] between router payload "
                    "and REQUIRED_TABS Row-1 headers. Owner-confirmed physical workbook headers and an approved "
                    "mapping are required before writes are permitted. Data was NOT SAVED."
                ),
            }

    return None


def is_tab_write_blocked_by_schema(tab_name: str) -> bool:
    return get_schema_write_block_reason(tab_name) is not None


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

    approved_reconciliations = get_approved_core_schema_reconciliations()

    registry: Dict[str, Dict[str, Any]] = {}
    for tab_name, headers in required_tabs.items():
        alias_info = LEGACY_TO_LOCKED_ID_PREFIX_ALIASES.get(tab_name)
        variance_info = SCHEMA_HEADER_VARIANCES.get(tab_name)
        reconciled_entry = approved_reconciliations.get(tab_name)
        effective_status = (
            "RECONCILED_OWNER_APPROVED"
            if reconciled_entry is not None
            else (variance_info or {}).get("status", "VERIFIED_CORE")
        )
        effective_headers = list(reconciled_entry["headers"]) if reconciled_entry is not None else list(headers)
        block_reason = get_schema_write_block_reason(tab_name)
        registry[tab_name] = {
            "tab_name": tab_name,
            "group_code": group_lookup.get(tab_name, "00"),
            "status": effective_status,
            "headers": effective_headers,
            "header_count": len(effective_headers),
            "locked_id_prefix": _TAB_TO_LOCKED_PREFIX.get(tab_name),
            "legacy_id_prefix": (alias_info or {}).get("legacy_prefix"),
            "allowed_new_allocation_prefixes": list(get_allowed_id_prefixes_for_tab(tab_name, for_new_allocation=True)),
            "allowed_read_prefixes": list(get_allowed_id_prefixes_for_tab(tab_name, for_new_allocation=False)),
            "id_prefix_reconciled": alias_info is None,
            "header_variance": variance_info,
            "write_blocked": block_reason is not None,
            "write_block_code": (block_reason or {}).get("error_code"),
            "confidential": tab_name in CONFIDENTIAL_TABS_NO_CACHE,
            "auto_create": False,
        }

    for tab_name, contract in EXTENDED_V2_TAB_CONTRACTS.items():
        if tab_name in registry:
            continue
        block_reason = get_schema_write_block_reason(tab_name)
        registry[tab_name] = {
            "tab_name": tab_name,
            "group_code": contract.get("group_code", group_lookup.get(tab_name, "00")),
            "status": contract.get("header_status", "PENDING_OWNER_MAPPING"),
            "headers": None,
            "header_count": 0,
            "locked_id_prefix": contract.get("prefix"),
            "prefix_status": contract.get("prefix_status", "PENDING_OWNER_MAPPING"),
            "allowed_new_allocation_prefixes": list(
                get_allowed_id_prefixes_for_tab(
                    tab_name,
                    for_new_allocation=True,
                    explicit_locked_prefix=contract.get("prefix"),
                )
            ),
            "write_blocked": block_reason is not None,
            "write_block_code": (block_reason or {}).get("error_code"),
            "confidential": tab_name in CONFIDENTIAL_TABS_NO_CACHE,
            "auto_create": False,
        }

    return registry


def get_table_schema_registry() -> Dict[str, Dict[str, Any]]:
    from app.sheets import REQUIRED_TABS
    return build_table_schema_registry(REQUIRED_TABS)


def get_schema_coverage_summary() -> Dict[str, Any]:
    """
    Compute honest, live schema-registry coverage counts against the 255-tab cleaned workbook baseline.
    Never fabricates unmapped tabs or headers; reports exact counts of verified, conflicting, pending,
    write-blocked, and unmapped tabs remaining until the authoritative 255-tab workbook export is supplied.
    """
    from app.sheets import REQUIRED_TABS

    table_registry = build_table_schema_registry(REQUIRED_TABS)
    seen_group_tabs: Dict[str, List[str]] = {}
    total_group_tab_refs = 0
    for g in DATABASE_GROUPS_15:
        code = str(g.get("group_code", ""))
        for tab in g.get("workbook_tabs", []):
            total_group_tab_refs += 1
            seen_group_tabs.setdefault(tab, []).append(code)

    duplicate_group_placements = {
        tab: codes for tab, codes in seen_group_tabs.items() if len(codes) > 1
    }
    approved_core = get_approved_core_schema_reconciliations()
    active_conflicting_core = sorted(CONFLICTING_CORE_SCHEMA_TABS - set(approved_core.keys()))
    active_pending_extended = sorted(PENDING_OWNER_MAPPING_TABS)
    active_write_blocked = sorted(set(active_pending_extended) | set(active_conflicting_core))

    unique_catalogued = len(table_registry)
    unmapped_remaining = max(0, WORKBOOK_TARGET_TAB_COUNT - unique_catalogued)

    return {
        "cleaned_tab_baseline": WORKBOOK_TARGET_TAB_COUNT,
        "declared_database_groups": len(DATABASE_GROUPS_15),
        "group_tab_references_total": total_group_tab_refs,
        "core_required_tabs_count": len(REQUIRED_TABS),
        "extended_v2_contracts_count": len(EXTENDED_V2_TAB_CONTRACTS),
        "unique_catalogued_workbook_tabs": unique_catalogued,
        "unmapped_workbook_tabs_remaining": unmapped_remaining,
        "pending_owner_mapping_tabs_count": len(active_pending_extended),
        "conflicting_core_schema_tabs_count": len(active_conflicting_core),
        "approved_core_schema_reconciliations_count": len(approved_core),
        "write_blocked_schema_tabs_count": len(active_write_blocked),
        "duplicate_group_placements": duplicate_group_placements,
        "coverage_complete": unmapped_remaining == 0 and len(active_write_blocked) == 0,
        "coverage_status": (
            "COMPLETE_VERIFIED"
            if (unmapped_remaining == 0 and len(active_write_blocked) == 0)
            else "INCOMPLETE_PENDING_AUTHORITATIVE_WORKBOOK_EXPORT"
        ),
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
