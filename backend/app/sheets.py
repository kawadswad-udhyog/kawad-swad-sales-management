import os
import json
import logging
import re
import threading
import time
import uuid
from typing import Dict, List, Any, Optional

try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

from app.config import (
    SALES_GOOGLE_SPREADSHEET_ID,
    SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
    SALES_GOOGLE_SERVICE_ACCOUNT_JSON,
)
from app.schema_registry import (
    CONFIDENTIAL_TABS_NO_CACHE,
    is_forbidden_scratch_tab,
)
from app.timeutil import now_iso

logger = logging.getLogger("kawad_swad.sheets")


class StorageCorruptionError(RuntimeError):
    """Raised when shared persistent storage data is corrupted or invalid."""
    pass


class StorageIOError(RuntimeError):
    """Raised when shared persistent storage encounters an I/O or permission error."""
    pass

ID_PREFIXES = {
    "Users": "USR",
    "Products": "PRD",
    "Customers": "CUS",
    "Sales": "SALE",
    "SaleItems": "ITEM",
    "Payments": "PAY",
    "SalesmanStockLedger": "STK",
    "CashLedger": "CSH",
    "Expenses": "EXP",
    "ShopVisits": "VIS",
    "DailyClosing": "CLOSE",
    "SalaryIncentives": "SAL",
    "AuditLog": "AUD",
    "AuthUsers": "AUTH",
    "Workers": "WRK",
    "WorkerAttendance": "ATT",
    "Recipes": "RCP",
    "ProductionBatches": "PRB",
    "PackagingBatches": "PKG",
    "ProductionStockLedger": "PST",
    "ProductionDispatches": "DSP",
    "RawMaterialLedger": "RML",
    "RawMaterials": "RWM",
    "IdAllocations": "ALC",
    "StockDiscrepancies": "DSC",
    "IncompleteTransactions": "TXN",
    "RevokedTokens": "RVK",
    "ApprovalRequests": "REQ",
    "CustomRoles": "ROL",
    "ChartOfAccounts": "ACC",
    "JournalHeaders": "JRN",
    "JournalLines": "JLN",
    "AccountingPeriods": "PER",
    "MillingBatches": "MIL",
    "Suppliers": "SUP",
    "PurchaseOrders": "PO",
    "PurchaseOrderItems": "POI",
    "GoodsReceipts": "GRN",
    "GoodsReceiptItems": "GRI",
    "SupplierBills": "BIL",
    "SupplierPayments": "SPAY",
    "SupplierReturns": "SRET",
    "SupplierReturnItems": "SRI",
    "CustomerReturns": "CRET",
    "CustomerReturnItems": "CRI",
    "QualityChecks": "QC",
    "ProductLots": "LOT",
    "LotMovements": "LMV",
    "ComplaintsRecalls": "CMP",
    "EmployeeDocuments": "EDOC",
    "EmployeeAttendance": "EATT",
    "WorkAssignments": "TSK",
    "WorkActivityLogs": "ACT",
    "SalaryStructures": "SST",
    "PayrollRuns": "PRUN",
    "PayrollItems": "PITM",
    "FreelancerProjects": "FPJ",
    "FreelancerMilestones": "FMS",
    "LabourMaster": "LBR",
    "LabourAttendance": "LATT",
    "LabourWorkEntries": "LWK",
    "LabourWageRecords": "LWR",
    "WorkforcePayments": "WPAY",
    "SalaryReceipts": "RCPT",
    "WorkforceAuditLogs": "WAUD",
    "VanLoadingPasses": "VLP",
}

REQUIRED_TABS = {
    "ChartOfAccounts": ["account_code", "account_name", "account_type", "parent_code", "normal_balance", "is_reconciled", "active", "description"],
    "JournalHeaders": ["journal_id", "journal_date", "voucher_type", "reference_type", "reference_id", "narration", "total_debit", "total_credit", "posted_by", "posted_at", "status", "reversal_of_id"],
    "JournalLines": ["line_id", "journal_id", "line_no", "account_code", "account_name", "debit_amount", "credit_amount", "entity_type", "entity_id", "notes"],
    "AccountingPeriods": ["period_id", "period_name", "start_date", "end_date", "is_closed", "closed_by", "closed_at"],
    "CustomRoles": ["role_id", "role_name", "description", "permissions_json", "created_by", "created_at", "updated_at"],
    "IdAllocations": ["allocation_id", "tab_name", "allocated_id", "nonce", "created_at"],
    "RevokedTokens": ["token_id", "jti", "user_id", "revoked_at", "expires_at", "reason"],
    "ApprovalRequests": ["request_id", "request_type", "target_user_id", "requested_by", "requested_by_name", "requested_at", "payload_json", "status", "decided_by", "decided_at", "decision_notes", "execution_error", "executed_at"],
    "AuthUsers": ["auth_id", "user_id", "username", "password_hash", "role", "active", "created_at", "must_change_password", "sessions_revoked_at"],
    "Users": [
        "user_id", "full_name", "username", "role", "mobile", "email", "active", "created_at", "notes",
        "employment_type", "designation", "department", "reporting_manager_id", "joining_date",
        "employment_status", "salary_frequency", "salary_structure_id", "address", "emergency_contact",
        "bank_details", "document_references", "updated_at", "created_by", "effective_from", "effective_to",
    ],
    "Products": ["product_id", "sku", "product_name", "category", "variant", "pack_weight_g", "selling_unit", "retail_pack_only", "active", "notes"],
    "Customers": ["customer_id", "customer_type", "shop_name", "shopkeeper_name", "mobile", "alternate_mobile", "address", "locality_area", "city", "gstin", "map_location", "active", "created_at"],
    "Sales": [
        "sale_id", "bill_number", "idempotency_key", "txn_status", "sale_datetime", "sales_type",
        "customer_id", "customer_name_snapshot", "customer_mobile", "customer_gstin",
        "entered_by_user_id", "salesman_user_id", "delivery_status", "payment_status",
        "payment_method", "payment_reference", "subtotal", "discount_amount", "tax_amount",
        "bill_total", "bill_status", "created_at", "notes",
    ],
    "SaleItems": [
        "sale_item_id", "sale_id", "product_id", "product_name_snapshot", "sku_snapshot",
        "pack_weight_g", "unit", "quantity", "actual_unit_price", "discount_amount",
        "line_total", "qualifying_kg", "created_at", "notes",
    ],
    "Payments": [
        "payment_id", "sale_id", "payment_datetime", "payment_method", "amount",
        "reference_number", "received_by_user_id", "payment_status", "notes",
    ],
    "SalesmanStockLedger": [
        "stock_txn_id", "txn_datetime", "salesman_user_id", "product_id", "sku_snapshot",
        "txn_type", "quantity", "unit", "pack_weight_g", "related_sale_id",
        "issued_by_user_id", "received_by_user_id", "confirmed_by_user_id", "reference_id", "notes",
    ],
    "CashLedger": [
        "cash_txn_id", "txn_datetime", "salesman_user_id", "txn_type", "amount",
        "payment_method", "related_sale_id", "related_expense_id", "issued_by_user_id",
        "received_by_user_id", "confirmed_by_user_id", "reference_id", "notes",
    ],
    "Expenses": [
        "expense_id", "expense_datetime", "salesman_user_id", "submitted_by_user_id", "category", "amount",
        "payment_mode", "description", "receipt_image_url", "receipt_link_or_file_ref", "approval_status",
        "approved_by_user_id", "approval_datetime", "approved_datetime", "cash_reducing_expense", "related_closing_id",
        "rejection_reason", "created_at", "notes",
    ],
    "ShopVisits": [
        "visit_id", "visit_datetime", "salesman_user_id", "customer_id", "customer_name_snapshot",
        "purpose", "outcome", "notes", "created_at",
    ],
    "DailyClosing": [
        "closing_id", "closing_date", "salesman_user_id", "opening_cash", "cash_collected",
        "approved_cash_expenses", "expected_cash_return", "physical_cash_returned", "cash_difference",
        "opening_stock_reference", "stock_discrepancy_flag", "closing_status", "submitted_at",
        "reviewed_by_user_id", "reviewed_at", "notes", "upi_collected", "bank_collected", "other_collected",
    ],
    "SalaryIncentives": [
        "incentive_id", "period_month", "salesman_user_id", "salesman_name", "qualifying_kg_sold",
        "base_rate_per_kg", "incentive_amount", "approved_by_user_id", "status", "paid_at", "notes", "created_at",
    ],
    "AuditLog": [
        "audit_id", "event_datetime", "actor_user_id", "action", "entity_type", "entity_id",
        "field_changed", "old_value", "new_value", "reason", "approved_by_user_id", "related_record_id",
    ],
    "Recipes": [
        "recipe_id", "product_id", "product_name_snapshot", "product_family", "version",
        "approved", "expected_yield_kg", "items_json", "notes", "created_at", "created_by",
        "approved_by", "approved_at",
    ],
    "RawMaterials": [
        "raw_material_id", "material_name", "current_stock", "unit", "rate_per_unit",
        "rate_status", "category", "created_at", "created_by",
    ],
    "ProductionBatches": [
        "production_id", "production_date", "product_id", "product_name_snapshot",
        "quantity_kg", "wastage_kg", "net_quantity_kg", "flour_base_used_kg",
        "benchmark_yield_kg", "actual_yield_ratio", "yield_variance_kg", "recipe_id",
        "status", "notes", "created_at", "created_by", "approved_by", "approved_at",
        "approval_notes", "materials_issued", "material_issue_txn_id", "recipe_version",
    ],
    "PackagingBatches": [
        "packaging_id", "packaging_date", "product_id", "product_name_snapshot",
        "bulk_kg_used", "packets_200g", "packets_500g", "packets_1000g", "total_packets",
        "expected_kg", "difference_kg", "difference_status", "status", "notes",
        "created_at", "created_by",
        "batch_allocations_json", "bulk_cost", "bulk_cost_per_kg", "packaging_material_cost", "packaging_labor_cost", "total_finished_cost",
        "packing_loss_kg", "loss_reason", "discrepancy_approved", "discrepancy_explanation", "discrepancy_approved_by", "discrepancy_approved_at", "reference", "cost_status",
    ],
    "ProductionStockLedger": [
        "movement_id", "txn_datetime", "movement_type", "product_id", "bulk_product_key",
        "product_name_snapshot", "sku_snapshot", "pack_weight_g", "quantity_kg",
        "quantity_packets", "channel", "reference_id", "destination", "created_by", "notes",
        "production_batch_id", "unit_cost_per_kg", "total_cost",
    ],
    "ProductionDispatches": [
        "dispatch_id", "dispatch_datetime", "product_id", "product_name_snapshot",
        "channel", "destination", "quantity_packets", "reference", "status",
        "created_by", "notes",
    ],
    "RawMaterialLedger": [
        "raw_material_txn_id", "txn_datetime", "material_name", "raw_material_id",
        "movement_type", "quantity", "unit", "rate_per_unit", "production_id", "issue_txn_id", "created_by", "notes",
    ],
    "Workers": [
        "worker_id", "worker_name", "mobile", "daily_wage", "active", "notes", "created_at",
    ],
    "WorkerAttendance": [
        "attendance_id", "worker_id", "worker_name_snapshot", "attendance_date",
        "status", "daily_wage_snapshot", "wage_accrued", "notes", "created_at", "created_by",
    ],
    "StockDiscrepancies": [
        "discrepancy_id", "discrepancy_date", "location", "product_id", "product_name_snapshot",
        "expected_stock", "physical_count", "difference", "reason", "counted_by_user_id",
        "reviewed_by_user_id", "status", "approved_adjustment", "created_at",
    ],
    "IncompleteTransactions": [
        "transaction_id", "transaction_type", "idempotency_key", "status", "payload_json",
        "error_details", "created_at", "updated_at", "resolved_by", "resolved_at",
    ],
    "MillingBatches": [
        "milling_batch_id", "batch_date", "source_material_id", "source_material_name", "input_quantity_kg",
        "target_flour_id", "target_flour_name", "flour_output_kg", "processing_loss_kg", "yield_ratio",
        "source_unit_rate", "milling_expenses", "total_flour_cost", "flour_unit_cost", "status",
        "created_by", "created_at", "notes",
    ],
    "Suppliers": [
        "supplier_id", "supplier_name", "contact_person", "mobile", "email", "address",
        "city", "gstin", "active", "created_at", "created_by", "notes",
    ],
    "PurchaseOrders": [
        "po_id", "po_number", "supplier_id", "supplier_name", "order_date", "expected_delivery_date",
        "total_amount", "status", "created_by", "created_at", "approved_by", "approved_at", "notes",
    ],
    "PurchaseOrderItems": [
        "po_item_id", "po_id", "raw_material_id", "material_name", "ordered_quantity",
        "received_quantity", "unit", "unit_price", "tax_amount", "line_total", "notes",
    ],
    "GoodsReceipts": [
        "receipt_id", "receipt_number", "po_id", "supplier_id", "supplier_name", "receipt_date",
        "invoice_reference", "delivery_challan", "total_accepted_qty", "total_rejected_qty",
        "quality_status", "status", "received_by", "created_at", "notes",
    ],
    "GoodsReceiptItems": [
        "receipt_item_id", "receipt_id", "po_item_id", "raw_material_id", "material_name",
        "delivered_quantity", "accepted_quantity", "rejected_quantity", "unit", "unit_rate",
        "rejection_reason", "stock_movement_id", "notes",
    ],
    "SupplierBills": [
        "bill_id", "bill_number", "supplier_id", "supplier_name", "receipt_id", "po_id",
        "bill_date", "due_date", "subtotal", "tax_amount", "total_amount", "paid_amount",
        "balance_amount", "payment_status", "status", "created_by", "created_at", "notes",
    ],
    "SupplierPayments": [
        "payment_id", "bill_id", "supplier_id", "supplier_name", "payment_date",
        "amount", "payment_method", "reference_number", "status", "paid_by", "created_at", "notes",
        "payment_type", "allocated_amount", "unallocated_amount", "allocations_json", "idempotency_key",
    ],
    "SupplierReturns": [
        "return_id", "return_number", "receipt_id", "supplier_id", "supplier_name",
        "return_date", "status", "approved_by", "approved_at", "created_by", "created_at", "notes",
    ],
    "SupplierReturnItems": [
        "return_item_id", "return_id", "raw_material_id", "material_name", "quantity",
        "unit", "unit_rate", "return_amount", "reason", "stock_movement_id", "notes",
    ],
    "CustomerReturns": [
        "return_id", "return_number", "sale_id", "bill_number", "customer_id", "customer_name",
        "return_date", "status", "inspection_status", "disposition", "approved_by", "approved_at",
        "created_by", "created_at", "notes",
    ],
    "CustomerReturnItems": [
        "return_item_id", "return_id", "product_id", "sku", "product_name", "quantity",
        "unit", "unit_price", "refund_amount", "reason", "inspection_notes", "stock_movement_id", "notes",
    ],
    "QualityChecks": [
        "qc_id", "check_date", "check_type", "reference_type", "reference_id",
        "product_or_material_id", "item_name", "inspector_user_id", "status", "decision",
        "parameters_json", "defect_details", "corrective_action", "created_at", "notes",
    ],
    "ProductLots": [
        "lot_id", "lot_number", "product_id", "product_name", "production_id", "packaging_id",
        "creation_date", "expiry_date", "initial_quantity", "current_quantity", "unit",
        "quality_status", "hold_reason", "status", "created_at", "created_by", "notes",
    ],
    "LotMovements": [
        "movement_id", "movement_date", "lot_id", "source_type", "source_id",
        "movement_type", "quantity", "unit", "actor_user_id", "created_at", "notes",
    ],
    "ComplaintsRecalls": [
        "complaint_id", "report_date", "report_type", "customer_id", "customer_name",
        "product_id", "lot_id", "quantity_affected", "severity", "status", "description",
        "investigation", "corrective_action", "responsible_user_id", "closure_date", "created_at", "notes",
    ],
    "EmployeeDocuments": [
        "doc_id", "user_id", "document_type", "title", "file_url", "verification_status", "verified_by", "verified_at", "expiry_date", "notes", "created_at",
    ],
    "EmployeeAttendance": [
        "attendance_id", "employee_id", "employee_name", "attendance_date", "check_in_time", "check_out_time", "total_hours", "status", "notes", "verified_by", "created_at",
    ],
    "WorkAssignments": [
        "task_id", "title", "description", "assigned_to_user_id", "assigned_to_name", "role", "priority", "status", "due_date", "created_by", "submission_notes", "proof_url", "review_notes", "created_at", "completed_at",
    ],
    "WorkActivityLogs": [
        "activity_id", "user_id", "activity_date", "activity_type", "description", "hours_spent", "task_id", "created_at",
    ],
    "SalaryStructures": [
        "structure_id", "user_id", "basic_salary", "hra", "transport_allowance", "special_allowance", "sales_commission_rate", "pf_deduction", "tds_deduction", "other_deductions", "payment_mode", "effective_from", "notes", "created_at",
    ],
    "PayrollRuns": [
        "payroll_run_id", "month", "run_date", "total_employees", "total_gross", "total_deductions", "total_net", "status", "created_by", "approved_by", "notes", "created_at",
    ],
    "PayrollItems": [
        "item_id", "payroll_run_id", "user_id", "employee_name", "role", "base_salary", "working_days", "present_days", "earned_basic", "allowances", "incentive_amount", "bonus_amount", "deductions", "adjustment_amount", "gross_amount", "net_amount", "payment_status", "payment_id", "notes",
    ],
    "FreelancerProjects": [
        "project_id", "title", "description", "freelancer_user_id", "freelancer_name", "total_budget", "currency", "start_date", "target_completion_date", "status", "deliverables_summary", "notes", "created_at",
    ],
    "FreelancerMilestones": [
        "milestone_id", "project_id", "title", "description", "amount", "due_date", "status", "submission_notes", "submission_link", "review_notes", "approved_at", "payment_id", "created_at",
    ],
    "LabourMaster": [
        "labour_id", "full_name", "category", "wage_type", "base_rate", "daily_expected_hours", "mobile", "emergency_contact", "address", "bank_account_no", "bank_ifsc", "active", "notes", "created_at",
    ],
    "LabourAttendance": [
        "attendance_id", "labour_id", "labour_name", "attendance_date", "status", "hours_worked", "overtime_hours", "wage_type", "daily_rate", "earned_wage", "verified_by", "notes", "created_at",
    ],
    "LabourWorkEntries": [
        "entry_id", "labour_id", "labour_name", "entry_date", "category", "activity_name", "batch_id", "units_completed", "unit_of_measure", "piece_rate", "total_amount", "hours_logged", "approved_by", "notes", "created_at",
    ],
    "LabourWageRecords": [
        "wage_record_id", "labour_id", "labour_name", "period_start", "period_end", "work_days", "total_hours", "piece_work_total", "gross_wage", "advances_deducted", "net_payable", "paid_amount", "payment_status", "paid_at", "payment_reference", "receipt_id", "status", "notes", "created_at",
    ],
    "WorkforcePayments": [
        "payment_id", "reference_id", "payment_type", "recipient_id", "recipient_name", "amount", "payment_method", "payment_reference", "payment_date", "bank_account_credited", "recorded_by", "accounting_journal_ref", "notes", "created_at",
    ],
    "SalaryReceipts": [
        "receipt_id", "receipt_number", "payment_id", "recipient_id", "recipient_name", "recipient_type", "role_or_category", "period_start", "period_end", "payment_date", "payment_method", "payment_reference", "gross_earnings", "total_deductions", "net_paid", "notes", "created_at",
    ],
    "WorkforceAuditLogs": [
        "audit_id", "action", "entity_type", "entity_id", "actor_id", "details", "created_at",
    ],
    "VanLoadingPasses": [
        "pass_id", "pass_number", "loading_date", "van_number", "salesman_user_id",
        "salesman_name", "created_by_user_id", "created_by_name", "status",
        "total_skus", "total_packets", "total_weight_kg", "items_json",
        "created_at", "accepted_at", "accepted_by_user_id", "discrepancy_notes",
        "idempotency_key", "notes",
    ],
    "Settings": [
        "setting_key", "setting_value", "description",
    ],
}


DEFAULT_GSPREAD_TIMEOUT = (5.0, 15.0)


class SheetsDatabase:
    """Google Sheets adapter with persistent write enforcement and isolated testing support."""

    def __init__(self, connect_on_init: bool = False):
        self.client = None
        self.spreadsheet = None
        self.is_connected = False
        self.last_connection_error: Optional[str] = None
        self.allow_in_memory_fallback = os.getenv("SALES_TESTING", "").strip() == "1"
        self._records_cache: Dict[str, tuple] = {}
        self._records_cache_ttl_seconds = 30.0
        self._diagnostic_headers_cache: Optional[Dict[str, Any]] = None
        self._diagnostic_cache_ttl_seconds = 60.0
        self._diagnostic_scan_lock = threading.Lock()
        self._worksheets: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._connect_state_lock = threading.Lock()
        self._connect_exec_lock = threading.Lock()
        self._connect_in_progress = False
        self._connect_done_event = threading.Event()
        self._background_thread: Optional[threading.Thread] = None
        self._request_timeout = DEFAULT_GSPREAD_TIMEOUT
        self._reconnect_cooldown_seconds = 15.0
        self._max_auto_backoff_seconds = 120.0
        self._consecutive_failures = 0
        self._inflight: Dict[str, threading.Event] = {}
        self._fail_once: Dict[str, int] = {}
        self.shared_file_dir: Optional[str] = os.getenv("SALES_SHARED_TEST_DIR") or None
        self.memory_store: Dict[str, List[Dict[str, Any]]] = {name: [] for name in list(ID_PREFIXES) + ["Settings"]}
        self._last_conn_attempt_time: float = 0.0
        if connect_on_init:
            self.init_connection()

    def enable_shared_file_store(self, directory_path: str) -> None:
        """Enables multi-process shared persistent file storage for testing."""
        self.shared_file_dir = directory_path
        os.environ["SALES_SHARED_TEST_DIR"] = directory_path
        os.makedirs(directory_path, exist_ok=True)
        # Flush current memory store to disk if not already existing
        for tab_name, rows in self.memory_store.items():
            path = self._tab_file_path(tab_name)
            if not os.path.exists(path) and rows:
                self._write_shared_records(tab_name, [dict(r) for r in rows])

    def disable_shared_file_store(self) -> None:
        """Disables shared persistent file storage, returning to standard in-memory test store."""
        self.shared_file_dir = None
        os.environ.pop("SALES_SHARED_TEST_DIR", None)

    def _tab_file_path(self, tab_name: str) -> str:
        s_dir = self.shared_file_dir or os.getenv("SALES_SHARED_TEST_DIR") or "/tmp"
        return os.path.join(s_dir, f"{tab_name}.json")

    def _tab_file_lock_path(self, tab_name: str) -> str:
        s_dir = self.shared_file_dir or os.getenv("SALES_SHARED_TEST_DIR") or "/tmp"
        return os.path.join(s_dir, f"{tab_name}.lock")

    def _read_shared_records(self, tab_name: str) -> List[Dict[str, Any]]:
        path = self._tab_file_path(tab_name)
        if not os.path.exists(path):
            return []

        last_exc: Optional[Exception] = None
        for _ in range(5):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, list):
                        raise StorageCorruptionError(
                            f"Corrupted storage data for tab '{tab_name}' at {path}: expected list, got {type(data).__name__}"
                        )
                    return data
            except FileNotFoundError as exc:
                last_exc = exc
                if not os.path.exists(path):
                    return []
                time.sleep(0.005)
            except json.JSONDecodeError as exc:
                last_exc = exc
                # Transient retry in case file was being atomically replaced
                time.sleep(0.005)
            except PermissionError as exc:
                logger.error("Permission denied reading shared storage file %s: %s", path, exc)
                raise StorageIOError(f"Permission denied reading storage file for tab '{tab_name}' at {path}: {exc}") from exc
            except OSError as exc:
                last_exc = exc
                time.sleep(0.005)

        if isinstance(last_exc, json.JSONDecodeError):
            logger.error("Corrupted JSON in shared storage file %s: %s", path, last_exc)
            raise StorageCorruptionError(
                f"Corrupted JSON in storage file for tab '{tab_name}' at {path}: {last_exc}"
            ) from last_exc
        if isinstance(last_exc, FileNotFoundError):
            if not os.path.exists(path):
                return []
            raise StorageIOError(f"File unavailable for tab '{tab_name}' at {path}: {last_exc}") from last_exc
        if last_exc is not None:
            raise StorageIOError(f"I/O error reading storage file for tab '{tab_name}' at {path}: {last_exc}") from last_exc
        return []

    def _write_shared_records(self, tab_name: str, records: List[Dict[str, Any]]) -> None:
        path = self._tab_file_path(tab_name)
        s_dir = os.path.dirname(path) or "."
        try:
            os.makedirs(s_dir, exist_ok=True)
        except PermissionError as exc:
            raise StorageIOError(f"Permission denied creating storage directory {s_dir}: {exc}") from exc
        except OSError as exc:
            raise StorageIOError(f"Failed creating storage directory {s_dir}: {exc}") from exc

        tmp_path = f"{path}.tmp.{os.getpid()}_{time.time_ns()}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(records, f)
                f.flush()
                os.fsync(f.fileno())
        except PermissionError as exc:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            raise StorageIOError(f"Permission denied writing temporary storage file {tmp_path}: {exc}") from exc
        except OSError as exc:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            raise StorageIOError(f"I/O or disk failure writing temporary storage file {tmp_path}: {exc}") from exc
        except Exception as exc:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            raise StorageIOError(f"Unexpected error writing temporary storage file {tmp_path}: {exc}") from exc

        try:
            os.replace(tmp_path, path)
        except PermissionError as exc:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            raise StorageIOError(f"Permission denied replacing storage file {path}: {exc}") from exc
        except OSError as exc:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            raise StorageIOError(f"Atomic replacement failed for storage file {path}: {exc}") from exc

    @staticmethod
    def _validate_timeout(timeout: Any) -> tuple:
        """Ensure gspread connect/read timeouts are strictly finite and never None."""
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and float(timeout) > 0:
            val = float(timeout)
            return (val, val)
        if (
            isinstance(timeout, (tuple, list))
            and len(timeout) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0 for v in timeout)
        ):
            return (float(timeout[0]), float(timeout[1]))
        return DEFAULT_GSPREAD_TIMEOUT

    def _configure_client_timeouts(self, client: Any) -> tuple:
        """Apply finite connect/read timeouts to a gspread client; never allow timeout=None."""
        timeout = self._validate_timeout(getattr(self, "_request_timeout", DEFAULT_GSPREAD_TIMEOUT))
        if hasattr(client, "set_timeout"):
            client.set_timeout(timeout)
        http_client = getattr(client, "http_client", None)
        if http_client is not None:
            current = getattr(http_client, "timeout", None)
            if current is None or current != timeout:
                http_client.timeout = timeout
        return timeout

    def _auto_reconnect_cooldown_seconds(self) -> float:
        """Compute bounded exponential backoff cooldown for automatic reconnect attempts."""
        if self._consecutive_failures <= 0:
            return self._reconnect_cooldown_seconds
        exponent = min(self._consecutive_failures - 1, 3)
        return min(self._reconnect_cooldown_seconds * (2 ** exponent), self._max_auto_backoff_seconds)

    def start_background_init(self) -> bool:
        """Start Google Sheets initialization on a single background daemon thread after port bind."""
        if self.is_connected and self.spreadsheet is not None:
            return False
        if not SALES_GOOGLE_SPREADSHEET_ID:
            with self._connect_state_lock:
                self._last_conn_attempt_time = time.monotonic()
                self.is_connected = False
                self.spreadsheet = None
                self.last_connection_error = (
                    "SALES_GOOGLE_SPREADSHEET_ID is not configured in environment. "
                    "Persistent storage cannot initialize."
                )
            if self.allow_in_memory_fallback:
                logger.warning("%s Operating in-memory for testing.", self.last_connection_error)
            else:
                logger.error("%s Business writes are disabled to prevent data loss.", self.last_connection_error)
            return False

        with self._connect_state_lock:
            if self._connect_in_progress or (self._background_thread is not None and self._background_thread.is_alive()):
                return False
            self._connect_in_progress = True
            self._connect_done_event.clear()
            self._last_conn_attempt_time = time.monotonic()

            def _worker() -> None:
                try:
                    with self._connect_exec_lock:
                        self._run_init_connection_impl()
                finally:
                    with self._connect_state_lock:
                        self._connect_in_progress = False
                        self._connect_done_event.set()

            thread = threading.Thread(target=_worker, name="sheets-init", daemon=True)
            self._background_thread = thread
            thread.start()
            return True

    def attempt_auto_reconnect(self) -> bool:
        """
        Safely attempt a single-flight automatic reconnection respecting bounded backoff.
        Concurrent callers never trigger duplicate network storms and fail closed immediately.
        """
        if self.is_connected and self.spreadsheet is not None:
            return True
        if not SALES_GOOGLE_SPREADSHEET_ID or self.allow_in_memory_fallback:
            return False

        now = time.monotonic()
        with self._connect_state_lock:
            if self.is_connected and self.spreadsheet is not None:
                return True
            if self._connect_in_progress:
                return False
            cooldown = self._auto_reconnect_cooldown_seconds()
            if self._last_conn_attempt_time > 0.0 and (now - self._last_conn_attempt_time) < cooldown:
                return False
            self._connect_in_progress = True
            self._connect_done_event.clear()
            self._last_conn_attempt_time = now

        try:
            if not self._connect_exec_lock.acquire(blocking=False):
                return False
            try:
                return self._run_init_connection_impl()
            finally:
                self._connect_exec_lock.release()
        finally:
            with self._connect_state_lock:
                self._connect_in_progress = False
                self._connect_done_event.set()

    def init_connection(self) -> bool:
        """Attempt to connect to Google Sheets using configured service account credentials."""
        acquired = self._connect_exec_lock.acquire(timeout=20.0)
        if not acquired:
            logger.warning("Timed out waiting for in-flight Google Sheets connection attempt.")
            return False
        try:
            with self._connect_state_lock:
                self._last_conn_attempt_time = time.monotonic()
                self._connect_in_progress = True
                self._connect_done_event.clear()
            return self._run_init_connection_impl()
        finally:
            with self._connect_state_lock:
                self._connect_in_progress = False
                self._connect_done_event.set()
            self._connect_exec_lock.release()

    def _run_init_connection_impl(self) -> bool:
        """Serialized implementation of Google Sheets connection and tab discovery."""
        with self._connect_state_lock:
            self._last_conn_attempt_time = time.monotonic()
        self.is_connected = False
        self.spreadsheet = None
        self.last_connection_error = None
        self.invalidate_diagnostic_cache()

        if not SALES_GOOGLE_SPREADSHEET_ID:
            self.last_connection_error = (
                "SALES_GOOGLE_SPREADSHEET_ID is not configured in environment. "
                "Persistent storage cannot initialize."
            )
            if self.allow_in_memory_fallback:
                logger.warning("%s Operating in-memory for testing.", self.last_connection_error)
            else:
                logger.error("%s Business writes are disabled to prevent data loss.", self.last_connection_error)
            return False

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.file",
            ]
            creds = None
            if SALES_GOOGLE_SERVICE_ACCOUNT_JSON:
                try:
                    info = json.loads(SALES_GOOGLE_SERVICE_ACCOUNT_JSON)
                    creds = Credentials.from_service_account_info(info, scopes=scopes)
                except Exception as exc:
                    self.last_connection_error = f"Invalid SALES_GOOGLE_SERVICE_ACCOUNT_JSON format: {exc}"
                    logger.error(self.last_connection_error)
                    with self._connect_state_lock:
                        self._consecutive_failures += 1
                    return False

            if not creds and os.path.exists(SALES_GOOGLE_SERVICE_ACCOUNT_FILE):
                try:
                    creds = Credentials.from_service_account_file(SALES_GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
                except Exception as exc:
                    self.last_connection_error = f"Failed to load service account file {SALES_GOOGLE_SERVICE_ACCOUNT_FILE}: {exc}"
                    logger.error(self.last_connection_error)
                    with self._connect_state_lock:
                        self._consecutive_failures += 1
                    return False

            if not creds:
                self.last_connection_error = (
                    "No Google service account credentials found. "
                    "Configure SALES_GOOGLE_SERVICE_ACCOUNT_JSON or SALES_GOOGLE_SERVICE_ACCOUNT_FILE."
                )
                if self.allow_in_memory_fallback:
                    logger.warning("%s Operating in-memory for testing.", self.last_connection_error)
                else:
                    logger.error("%s Business writes are disabled to prevent data loss.", self.last_connection_error)
                with self._connect_state_lock:
                    self._consecutive_failures += 1
                return False

            client = gspread.authorize(creds)
            self._configure_client_timeouts(client)
            self.client = client
            spreadsheet = client.open_by_key(SALES_GOOGLE_SPREADSHEET_ID)
            if not self.ensure_required_tabs(spreadsheet=spreadsheet):
                self.is_connected = False
                self.spreadsheet = None
                self.last_connection_error = (
                    "Google Sheets worksheet discovery failed during startup verification; "
                    "persistent storage remains disconnected to avoid unsafe tab creation."
                )
                logger.error("%s Persistent writes disabled.", self.last_connection_error)
                with self._connect_state_lock:
                    self._consecutive_failures += 1
                return False

            self.spreadsheet = spreadsheet
            self.is_connected = True
            self.last_connection_error = None
            with self._connect_state_lock:
                self._consecutive_failures = 0
            logger.info("Connected to configured Google Spreadsheet.")
            return True
        except Exception as exc:
            self.is_connected = False
            self.spreadsheet = None
            self.last_connection_error = f"Failed to connect to Google Sheets: {exc}"
            logger.error("%s. Persistent writes disabled.", self.last_connection_error)
            with self._connect_state_lock:
                self._consecutive_failures += 1
            return False

    def invalidate_diagnostic_cache(self) -> None:
        """Clear cached diagnostic tab/schema header snapshot."""
        with self._lock:
            self._diagnostic_headers_cache = None

    @staticmethod
    def _sheet_header_range(tab_name: str) -> str:
        escaped = str(tab_name).replace("'", "''")
        return f"'{escaped}'!1:1"

    def _read_all_tab_headers_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Read row-1 headers for all REQUIRED_TABS in a strictly read-only manner.
        Uses batch Google Sheets API calls (worksheets() + values_batch_get()) when available,
        caches completed scans safely within TTL, and never treats unreadable/429 errors as empty headers.
        """
        if not (self.is_connected and self.spreadsheet):
            return {
                "connected": False,
                "mode": "DISCONNECTED",
                "verification_completed": False,
                "error_type": "DISCONNECTED",
                "error": self.last_connection_error or "Google Sheets not connected",
                "tab_headers": {},
                "missing_tabs": [],
                "unreadable_tabs": {},
                "cached": False,
            }

        now = time.monotonic()
        if not force_refresh:
            with self._lock:
                cached = self._diagnostic_headers_cache
                if (
                    cached is not None
                    and cached.get("spreadsheet") is self.spreadsheet
                    and (now - float(cached.get("timestamp", 0.0))) < self._diagnostic_cache_ttl_seconds
                ):
                    snap = dict(cached["snapshot"])
                    snap["tab_headers"] = {k: list(v) for k, v in snap.get("tab_headers", {}).items()}
                    snap["missing_tabs"] = list(snap.get("missing_tabs", []))
                    snap["unreadable_tabs"] = dict(snap.get("unreadable_tabs", {}))
                    snap["cached"] = True
                    return snap

        with self._diagnostic_scan_lock:
            now = time.monotonic()
            if not force_refresh:
                with self._lock:
                    cached = self._diagnostic_headers_cache
                    if (
                        cached is not None
                        and cached.get("spreadsheet") is self.spreadsheet
                        and (now - float(cached.get("timestamp", 0.0))) < self._diagnostic_cache_ttl_seconds
                    ):
                        snap = dict(cached["snapshot"])
                        snap["tab_headers"] = {k: list(v) for k, v in snap.get("tab_headers", {}).items()}
                        snap["missing_tabs"] = list(snap.get("missing_tabs", []))
                        snap["unreadable_tabs"] = dict(snap.get("unreadable_tabs", {}))
                        snap["cached"] = True
                        return snap

            tab_headers: Dict[str, List[str]] = {}
            missing_tabs: List[str] = []
            unreadable_tabs: Dict[str, Dict[str, str]] = {}

            # Fast batch path used for real gspread.Spreadsheet and batch-capable mocks
            if hasattr(self.spreadsheet, "values_batch_get"):
                ws_map: Optional[Dict[str, Any]] = None
                if hasattr(self.spreadsheet, "worksheets"):
                    try:
                        ws_list = self.spreadsheet.worksheets()
                        ws_map = {ws.title: ws for ws in ws_list}
                        with self._lock:
                            for title, ws in ws_map.items():
                                self._worksheets[title] = ws
                    except Exception as exc:
                        err_type = self._classify_sheets_exception(exc)
                        logger.warning("Diagnostic worksheets() list failed (%s): %s", err_type, exc)
                        return {
                            "connected": True,
                            "mode": "GOOGLE_SHEETS_LIVE_READONLY",
                            "verification_completed": False,
                            "error_type": err_type,
                            "error": str(exc),
                            "tab_headers": {},
                            "missing_tabs": [],
                            "unreadable_tabs": {
                                tab: {"error_type": err_type, "error": str(exc)}
                                for tab in REQUIRED_TABS
                            },
                            "cached": False,
                        }

                if ws_map is not None:
                    existing_tabs = [tab for tab in REQUIRED_TABS if tab in ws_map]
                    missing_tabs = [tab for tab in REQUIRED_TABS if tab not in ws_map]
                else:
                    existing_tabs = list(REQUIRED_TABS.keys())

                chunk_size = 35
                for start_idx in range(0, len(existing_tabs), chunk_size):
                    chunk = existing_tabs[start_idx : start_idx + chunk_size]
                    ranges = [self._sheet_header_range(tab) for tab in chunk]
                    try:
                        resp = self.spreadsheet.values_batch_get(ranges)
                        value_ranges = resp.get("valueRanges") if isinstance(resp, dict) else None
                        if not isinstance(value_ranges, list) or len(value_ranges) != len(chunk):
                            raise ValueError(
                                f"Incomplete values_batch_get response: expected {len(chunk)} ranges, got {len(value_ranges) if isinstance(value_ranges, list) else type(value_ranges).__name__}"
                            )
                        for tab, vr in zip(chunk, value_ranges):
                            rows = vr.get("values") or [] if isinstance(vr, dict) else []
                            row1 = rows[0] if rows and isinstance(rows[0], list) else []
                            tab_headers[tab] = [str(h).strip() for h in row1 if str(h).strip()]
                    except Exception as exc:
                        err_type = self._classify_sheets_exception(exc)
                        logger.warning(
                            "Diagnostic values_batch_get failed (%s) on chunk starting with %s: %s",
                            err_type,
                            chunk[0] if chunk else "",
                            exc,
                        )
                        for remaining_tab in existing_tabs[start_idx:]:
                            unreadable_tabs[remaining_tab] = {
                                "error_type": err_type,
                                "error": str(exc),
                            }
                        return {
                            "connected": True,
                            "mode": "GOOGLE_SHEETS_LIVE_READONLY",
                            "verification_completed": False,
                            "error_type": err_type,
                            "error": str(exc),
                            "tab_headers": tab_headers,
                            "missing_tabs": missing_tabs,
                            "unreadable_tabs": unreadable_tabs,
                            "cached": False,
                        }

                snapshot = {
                    "connected": True,
                    "mode": "GOOGLE_SHEETS_LIVE_READONLY",
                    "verification_completed": True,
                    "error_type": None,
                    "error": None,
                    "tab_headers": tab_headers,
                    "missing_tabs": missing_tabs,
                    "unreadable_tabs": {},
                    "cached": False,
                }
                with self._lock:
                    self._diagnostic_headers_cache = {
                        "spreadsheet": self.spreadsheet,
                        "timestamp": time.monotonic(),
                        "snapshot": {
                            **snapshot,
                            "tab_headers": {k: list(v) for k, v in tab_headers.items()},
                            "missing_tabs": list(missing_tabs),
                            "unreadable_tabs": {},
                        },
                    }
                return snapshot

            # Per-tab read-only fallback path (e.g., legacy test mocks without values_batch_get)
            ws_map_fallback: Dict[str, Any] = {}
            if hasattr(self.spreadsheet, "worksheets"):
                try:
                    ws_map_fallback = {ws.title: ws for ws in self.spreadsheet.worksheets()}
                except Exception as exc:
                    err_type = self._classify_sheets_exception(exc)
                    logger.warning("Diagnostic worksheets() fallback list failed (%s): %s", err_type, exc)
                    return {
                        "connected": True,
                        "mode": "GOOGLE_SHEETS_LIVE_READONLY",
                        "verification_completed": False,
                        "error_type": err_type,
                        "error": str(exc),
                        "tab_headers": {},
                        "missing_tabs": [],
                        "unreadable_tabs": {
                            tab: {"error_type": err_type, "error": str(exc)}
                            for tab in REQUIRED_TABS
                        },
                        "cached": False,
                    }

            aborted_err_type: Optional[str] = None
            aborted_err_msg: Optional[str] = None
            for idx, tab in enumerate(REQUIRED_TABS):
                ws = ws_map_fallback.get(tab)
                if ws is None:
                    try:
                        ws = self.spreadsheet.worksheet(tab)
                    except Exception as exc:
                        err_type = self._classify_sheets_exception(exc)
                        if err_type == "TAB_NOT_FOUND":
                            missing_tabs.append(tab)
                            continue
                        unreadable_tabs[tab] = {"error_type": err_type, "error": str(exc)}
                        if err_type == "QUOTA_EXCEEDED":
                            aborted_err_type = err_type
                            aborted_err_msg = str(exc)
                            for rem in list(REQUIRED_TABS.keys())[idx + 1 :]:
                                unreadable_tabs[rem] = {"error_type": err_type, "error": str(exc)}
                            break
                        continue
                try:
                    row1 = ws.row_values(1)
                    tab_headers[tab] = [str(h).strip() for h in row1 if str(h).strip()]
                except Exception as exc:
                    err_type = self._classify_sheets_exception(exc)
                    unreadable_tabs[tab] = {"error_type": err_type, "error": str(exc)}
                    if err_type == "QUOTA_EXCEEDED":
                        aborted_err_type = err_type
                        aborted_err_msg = str(exc)
                        for rem in list(REQUIRED_TABS.keys())[idx + 1 :]:
                            unreadable_tabs[rem] = {"error_type": err_type, "error": str(exc)}
                        break

            if unreadable_tabs:
                err_types = [info["error_type"] for info in unreadable_tabs.values()]
                dominant_err = aborted_err_type or (
                    "QUOTA_EXCEEDED"
                    if "QUOTA_EXCEEDED" in err_types
                    else ("NETWORK_ERROR" if "NETWORK_ERROR" in err_types else err_types[0])
                )
                first_msg = aborted_err_msg or next(iter(unreadable_tabs.values()))["error"]
                return {
                    "connected": True,
                    "mode": "GOOGLE_SHEETS_LIVE_READONLY",
                    "verification_completed": False,
                    "error_type": dominant_err,
                    "error": first_msg,
                    "tab_headers": tab_headers,
                    "missing_tabs": missing_tabs,
                    "unreadable_tabs": unreadable_tabs,
                    "cached": False,
                }

            snapshot = {
                "connected": True,
                "mode": "GOOGLE_SHEETS_LIVE_READONLY",
                "verification_completed": True,
                "error_type": None,
                "error": None,
                "tab_headers": tab_headers,
                "missing_tabs": missing_tabs,
                "unreadable_tabs": {},
                "cached": False,
            }
            with self._lock:
                self._diagnostic_headers_cache = {
                    "spreadsheet": self.spreadsheet,
                    "timestamp": time.monotonic(),
                    "snapshot": {
                        **snapshot,
                        "tab_headers": {k: list(v) for k, v in tab_headers.items()},
                        "missing_tabs": list(missing_tabs),
                        "unreadable_tabs": {},
                    },
                }
            return snapshot

    def reconnect(self) -> bool:
        """Trigger re-initialization of Google Sheets connection and clear caches."""
        with self._lock:
            self._worksheets.clear()
            self._records_cache.clear()
            self._diagnostic_headers_cache = None
        return self.init_connection()

    def verify_tabs_accessibility(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Verify that every required sheet can be read successfully using batch header reads and safe caching."""
        snapshot = self._read_all_tab_headers_snapshot(force_refresh=force_refresh)
        if not snapshot.get("connected"):
            return {
                "connected": False,
                "all_tabs_accessible": False,
                "status": "CHECK_FAILED",
                "error_type": "DISCONNECTED",
                "verification_completed": False,
                "quota_exceeded": False,
                "cached": False,
                "error": snapshot.get("error") or "Google Sheets not connected",
                "tabs": {},
            }

        tab_headers = snapshot.get("tab_headers", {})
        missing_tabs = set(snapshot.get("missing_tabs", []))
        unreadable_tabs = snapshot.get("unreadable_tabs", {})

        results: Dict[str, Any] = {}
        for tab in REQUIRED_TABS:
            if tab in tab_headers:
                results[tab] = {"status": "ok", "columns": len(tab_headers[tab])}
            elif tab in unreadable_tabs:
                err_info = unreadable_tabs[tab]
                results[tab] = {
                    "status": "error",
                    "error_type": err_info.get("error_type", "API_ERROR"),
                    "error": err_info.get("error", "Unreadable worksheet"),
                }
            elif tab in missing_tabs:
                results[tab] = {
                    "status": "error",
                    "error_type": "TAB_NOT_FOUND",
                    "error": f"Worksheet '{tab}' not found",
                }
            else:
                results[tab] = {
                    "status": "error",
                    "error_type": snapshot.get("error_type") or "API_ERROR",
                    "error": snapshot.get("error") or "Verification did not complete",
                }

        all_ok = bool(
            snapshot.get("verification_completed")
            and not missing_tabs
            and not unreadable_tabs
            and all(r.get("status") == "ok" for r in results.values())
        )
        err_type = snapshot.get("error_type")
        if err_type == "QUOTA_EXCEEDED":
            status = "TEMPORARILY_UNAVAILABLE"
        elif not snapshot.get("verification_completed") or unreadable_tabs or missing_tabs:
            status = "CHECK_FAILED"
        else:
            status = "OK"

        return {
            "connected": True,
            "all_tabs_accessible": all_ok,
            "status": status,
            "verification_completed": bool(snapshot.get("verification_completed")),
            "error_type": err_type,
            "quota_exceeded": err_type == "QUOTA_EXCEEDED",
            "cached": bool(snapshot.get("cached", False)),
            "error": snapshot.get("error"),
            "tabs": results,
        }

    def ensure_required_tabs(self, spreadsheet: Any = None) -> bool:
        """Read-only worksheet discovery on startup. Never creates tabs or mutates headers under Single-Write-Owner."""
        ss = spreadsheet if spreadsheet is not None else self.spreadsheet
        if ss is None or (spreadsheet is None and not self.is_connected):
            return False
        try:
            # Single API call to retrieve all existing worksheets at once (strictly read-only)
            existing_ws = {ws.title: ws for ws in ss.worksheets()}
            with self._lock:
                for title, ws in existing_ws.items():
                    self._worksheets[title] = ws
        except Exception as exc:
            logger.error(
                "Worksheet discovery failed; aborting ensure_required_tabs safely: %s",
                exc,
            )
            return False

        missing_tabs = [tab for tab in REQUIRED_TABS if tab not in existing_ws]
        if missing_tabs:
            logger.warning(
                "Startup read-only discovery found %d missing tab(s) (not auto-created under Single-Write-Owner): %s",
                len(missing_tabs),
                missing_tabs[:10],
            )
        return True

    def _ensure_headers(self, worksheet, headers: List[str]):
        self._assert_direct_mutation_allowed("_ensure_headers", str(getattr(worksheet, "title", "")))
        current = worksheet.row_values(1)
        if not current:
            worksheet.update("A1", [headers])
            self.invalidate_diagnostic_cache()
            return
        missing = [h for h in headers if h not in current]
        if missing:
            start = len(current) + 1
            end = start + len(missing) - 1
            worksheet.update(self._a1(start, 1, end), [missing])
            self.invalidate_diagnostic_cache()

    @staticmethod
    def _a1(start_col: int, row: int, end_col: int) -> str:
        def col_name(index: int) -> str:
            name = ""
            while index:
                index, rem = divmod(index - 1, 26)
                name = chr(65 + rem) + name
            return name
        return f"{col_name(start_col)}{row}:{col_name(end_col)}{row}"

    def _invalidate_records_cache(self, tab_name: str) -> None:
        with self._lock:
            self._records_cache.pop(tab_name, None)

    def invalidate_tab_cache(self, tab_name: str) -> None:
        """Immediately invalidate cached rows and diagnostic cache for a tab."""
        self._invalidate_records_cache(tab_name)
        self.invalidate_diagnostic_cache()

    def invalidate_all_read_caches(self) -> None:
        """Clear all shared non-confidential read caches."""
        with self._lock:
            self._records_cache.clear()
            self._diagnostic_headers_cache = None

    def _get_worksheet(self, tab_name: str):
        if is_forbidden_scratch_tab(tab_name):
            raise RuntimeError(
                f"Access denied: legacy scratch tab '{tab_name}' is forbidden and must never be recreated or queried."
            )
        with self._lock:
            ws = self._worksheets.get(tab_name)
        if ws is not None:
            return ws
        # Strictly read-only lookup: never auto-create worksheets or mutate headers on read paths
        ws = self.spreadsheet.worksheet(tab_name)
        with self._lock:
            self._worksheets[tab_name] = ws
        return ws

    @staticmethod
    def _is_quota_exception(exc: Exception) -> bool:
        code = getattr(exc, "code", None)
        if code == 429:
            return True
        resp = getattr(exc, "response", None)
        if getattr(resp, "status_code", None) == 429:
            return True
        err_obj = getattr(exc, "error", None)
        if isinstance(err_obj, dict):
            if err_obj.get("code") == 429 or "RESOURCE_EXHAUSTED" in str(err_obj.get("status", "")).upper():
                return True
        err_str = str(exc).lower()
        return (
            "429" in err_str
            or "quota" in err_str
            or "rate limit" in err_str
            or "resource_exhausted" in err_str
            or "too many requests" in err_str
        )

    @classmethod
    def _classify_sheets_exception(cls, exc: Exception) -> str:
        if cls._is_quota_exception(exc):
            return "QUOTA_EXCEEDED"
        cls_name = exc.__class__.__name__
        err_str = str(exc).lower()
        if cls_name == "WorksheetNotFound" or (
            "worksheet" in err_str
            and ("not found" in err_str or "does not exist" in err_str or "missing" in err_str)
        ):
            return "TAB_NOT_FOUND"
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
            tok in err_str
            for tok in (
                "timed out",
                "timeout",
                "connection",
                "network",
                "unreachable",
                "name resolution",
                "dns",
                "ssl",
                "eof",
                "502",
                "503",
                "504",
            )
        ):
            return "NETWORK_ERROR"
        return "API_ERROR"

    def _safe_read_worksheet_records(self, worksheet, tab_name: str) -> List[Dict[str, Any]]:
        """Read records safely, tolerating legacy duplicate headers, blank trailing columns, and extra columns."""
        try:
            records = worksheet.get_all_records()
            return [dict(row) for row in records]
        except Exception as exc:
            if self._is_quota_exception(exc) or not hasattr(worksheet, "get_all_values"):
                raise
            logger.warning(
                "Falling back to raw row parsing for '%s' after get_all_records() header warning: %s",
                tab_name,
                exc,
            )
            values = worksheet.get_all_values()
            if not values or len(values) < 2:
                return []
            raw_headers = list(values[0])
            data_rows = values[1:]
            # Determine last column containing either header text or non-empty cell data
            max_col = len(raw_headers)
            for row in data_rows:
                for idx in range(len(row) - 1, -1, -1):
                    if str(row[idx]).strip() != "":
                        max_col = max(max_col, idx + 1)
                        break

            seen_counts: Dict[str, int] = {}
            resolved_headers: List[Optional[str]] = []
            for idx in range(max_col):
                h_raw = str(raw_headers[idx]).strip() if idx < len(raw_headers) else ""
                if not h_raw:
                    has_data = any(idx < len(r) and str(r[idx]).strip() != "" for r in data_rows)
                    resolved_headers.append(f"_extra_col_{idx + 1}" if has_data else None)
                    continue
                count = seen_counts.get(h_raw, 0) + 1
                seen_counts[h_raw] = count
                resolved_headers.append(h_raw if count == 1 else f"{h_raw}__dup_{count}")

            parsed: List[Dict[str, Any]] = []
            for row in data_rows:
                if not any(str(c).strip() != "" for c in row):
                    continue
                item: Dict[str, Any] = {}
                for idx, header_name in enumerate(resolved_headers):
                    if header_name is None:
                        continue
                    item[header_name] = row[idx] if idx < len(row) else ""
                parsed.append(item)
            return parsed

    def get_records(self, tab_name: str, fresh: bool = False) -> List[Dict[str, Any]]:
        if is_forbidden_scratch_tab(tab_name):
            raise RuntimeError(
                f"Access denied: legacy scratch tab '{tab_name}' is forbidden and must never be recreated or queried."
            )
        is_confidential_tab = tab_name in CONFIDENTIAL_TABS_NO_CACHE
        effective_fresh = bool(fresh or is_confidential_tab)

        # If disconnected but configured, attempt single-flight self-healing reconnect with bounded backoff
        if not (self.is_connected and self.spreadsheet) and SALES_GOOGLE_SPREADSHEET_ID:
            if not self.allow_in_memory_fallback:
                self.attempt_auto_reconnect()

        if not (self.is_connected and self.spreadsheet):
            shared_dir = self.shared_file_dir or os.getenv("SALES_SHARED_TEST_DIR")
            if shared_dir:
                rows = self._read_shared_records(tab_name)
                self.memory_store[tab_name] = rows
                return [dict(row) for row in rows]
            if self.allow_in_memory_fallback:
                return [dict(row) for row in self.memory_store.get(tab_name, [])]
            err_msg = (
                f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
                f"Cannot retrieve records for '{tab_name}'."
            )
            logger.error(err_msg)
            raise RuntimeError(err_msg)

        import time
        now = time.monotonic()
        with self._lock:
            cached = None if is_confidential_tab else self._records_cache.get(tab_name)
        if not effective_fresh:
            if cached and now - cached[0] < self._records_cache_ttl_seconds:
                return [dict(row) for row in cached[1]]
            with self._lock:
                event = self._inflight.get(tab_name)
                if event is None:
                    event = threading.Event()
                    self._inflight[tab_name] = event
                    leader = True
                else:
                    leader = False
            if not leader:
                event.wait(timeout=30)
                with self._lock:
                    cached = None if is_confidential_tab else self._records_cache.get(tab_name)
                    if cached:
                        return [dict(row) for row in cached[1]]

        # Read from Google Sheets with retry on 429 quota errors
        max_retries = 3
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                worksheet = self._get_worksheet(tab_name)
                safe_records = self._safe_read_worksheet_records(worksheet, tab_name)
                with self._lock:
                    if is_confidential_tab:
                        # Guarantee confidential payroll/bank/personal tables are NEVER held in shared cache
                        self._records_cache.pop(tab_name, None)
                    else:
                        self._records_cache[tab_name] = (time.monotonic(), safe_records)
                return [dict(row) for row in safe_records]
            except Exception as exc:
                last_exc = exc
                is_quota_error = self._is_quota_exception(exc)
                if is_quota_error:
                    logger.warning(
                        "Google Sheets rate limit/429 for %s (attempt %d/%d): %s",
                        tab_name, attempt + 1, max_retries + 1, exc
                    )
                    # ONLY serve cached data when fresh=False was requested and tab is non-confidential
                    if not effective_fresh and cached and cached[1]:
                        logger.info("Serving stale cached records for %s due to Google Sheets rate limit", tab_name)
                        return [dict(row) for row in cached[1]]
                    if attempt < max_retries:
                        sleep_time = 0.01 if os.getenv("SALES_TESTING", "").strip() == "1" else (2 ** attempt) * 1.5 + 0.5
                        time.sleep(sleep_time)
                        continue
                else:
                    with self._lock:
                        self._worksheets.pop(tab_name, None)
                    break
            finally:
                if not effective_fresh:
                    with self._lock:
                        event = self._inflight.pop(tab_name, None)
                        if event:
                            event.set()

        err_str = str(last_exc).lower() if last_exc else ""
        if "429" in err_str or "quota" in err_str:
            if not fresh and cached and cached[1]:
                return [dict(row) for row in cached[1]]
            logger.error("Exhausted retries on 429 quota error for %s: %s", tab_name, last_exc)
            raise RuntimeError(f"Google Sheets API quota temporarily exceeded for {tab_name}. Please retry in a few seconds.") from last_exc

        logger.warning("Error reading %s from sheet: %s", tab_name, last_exc)
        raise RuntimeError(f"Could not read {tab_name} from Google Sheets.") from last_exc

    get_all_records = get_records

    def query_records(
        self,
        tab_name: str,
        *,
        fresh: bool = False,
        search: str = "",
        filters: Optional[Dict[str, Any]] = None,
        date_field: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        """Server-side filtered, searched, date-ranged, and paginated sheet read."""
        rows = self.get_records(tab_name, fresh=fresh)

        if filters:
            for fk, fv in filters.items():
                if fv is None or str(fv).strip() == "":
                    continue
                target_val = str(fv).strip().lower()
                rows = [r for r in rows if str(r.get(fk, "")).strip().lower() == target_val]

        if date_field and (date_from or date_to):
            filtered_date_rows = []
            d_from = str(date_from or "").strip()[:10]
            d_to = str(date_to or "").strip()[:10]
            for r in rows:
                d_val = str(r.get(date_field, "")).strip()[:10]
                if not d_val:
                    continue
                if d_from and d_val < d_from:
                    continue
                if d_to and d_val > d_to:
                    continue
                filtered_date_rows.append(r)
            rows = filtered_date_rows

        q = str(search or "").strip().lower()
        if q:
            rows = [r for r in rows if any(q in str(v).lower() for v in r.values())]

        if sort_desc:
            rows = list(reversed(rows))

        safe_page = max(1, int(page or 1))
        safe_size = max(1, min(int(page_size or 25), 200))
        total = len(rows)
        total_pages = max(1, (total + safe_size - 1) // safe_size)
        start = (safe_page - 1) * safe_size
        return {
            "source_tab": tab_name,
            "items": rows[start : start + safe_size],
            "total": total,
            "page": safe_page,
            "page_size": safe_size,
            "total_pages": total_pages,
        }

    def inject_failure_once(self, tab_name: str, count: int = 1) -> None:
        with self._lock:
            self._fail_once[tab_name] = count

    def _assert_direct_mutation_allowed(self, op: str, tab_name: str) -> None:
        """
        Single-Write-Owner enforcement: FastAPI may never mutate live Google Sheets directly.
        All runtime state changes must go through AppsScriptBridge. Direct store helpers only run
        when SALES_TESTING=1 in-memory/shared-file fallback is explicitly active and disconnected.
        """
        if (self.is_connected and self.spreadsheet) or not self.allow_in_memory_fallback:
            raise RuntimeError(
                f"BLOCKED_PENDING_OWNER_SETUP: Direct Google Sheets mutation '{op}' on '{tab_name}' is disabled "
                "under Blueprint v2.1 Single-Write-Owner architecture. Delegate through AppsScriptBridge."
            )

    def append_record(
        self,
        tab_name: str,
        record: Dict[str, Any],
        raise_on_error: bool = False,
        authorize_header_update: bool = False,
    ) -> bool:
        self._assert_direct_mutation_allowed("append_record", tab_name)
        if is_forbidden_scratch_tab(tab_name):
            err_msg = f"Write blocked: legacy scratch tab '{tab_name}' is forbidden."
            if raise_on_error:
                raise RuntimeError(err_msg)
            return False
        self._invalidate_records_cache(tab_name)
        failures = self._fail_once.get(tab_name, 0)
        if failures > 0:
            self._fail_once[tab_name] = failures - 1
            logger.error("Injected write failure for %s", tab_name)
            if raise_on_error:
                raise RuntimeError(f"Injected failure writing {tab_name}")
            return False

        if self.is_connected and self.spreadsheet:
            try:
                worksheet = self._get_worksheet(tab_name)
                headers = worksheet.row_values(1)
                if not headers:
                    headers = list(record.keys())
                    worksheet.update("A1", [headers])
                else:
                    lower_headers = {str(h).strip().lower(): h for h in headers if str(h).strip()}
                    missing = [
                        k for k in record.keys()
                        if k not in headers and str(k).strip().lower() not in lower_headers
                    ]
                    if missing:
                        if authorize_header_update:
                            self._ensure_headers(worksheet, headers + missing)
                            headers = headers + missing
                        else:
                            logger.warning(
                                "Preserving existing sheet headers for '%s'; omitting unmapped write fields %s",
                                tab_name,
                                missing,
                            )
                record_lower = {str(k).strip().lower(): v for k, v in record.items()}
                row = []
                for h in headers:
                    if h in record:
                        row.append(record[h])
                    elif str(h).strip() in record:
                        row.append(record[str(h).strip()])
                    elif str(h).strip().lower() in record_lower:
                        row.append(record_lower[str(h).strip().lower()])
                    else:
                        row.append("")
                worksheet.append_row(row, value_input_option="USER_ENTERED")
                self.memory_store.setdefault(tab_name, []).append(dict(record))
                return True
            except Exception as exc:
                logger.error("Error appending to %s in Google Sheet: %s", tab_name, exc)
                if raise_on_error:
                    raise RuntimeError(f"Persistent write failed for {tab_name}: {exc}") from exc
                return False

        # Disconnected state:
        shared_dir = self.shared_file_dir or os.getenv("SALES_SHARED_TEST_DIR")
        if shared_dir:
            lock_path = self._tab_file_lock_path(tab_name)
            with open(lock_path, "a") as lk:
                if HAS_FCNTL:
                    fcntl.flock(lk, fcntl.LOCK_EX)
                try:
                    rows = self._read_shared_records(tab_name)
                    rows.append(dict(record))
                    self._write_shared_records(tab_name, rows)
                    self.memory_store[tab_name] = rows
                    return True
                except Exception as exc:
                    logger.error("Error in shared file append for %s: %s", tab_name, exc)
                    if raise_on_error:
                        raise
                    return False
                finally:
                    if HAS_FCNTL:
                        fcntl.flock(lk, fcntl.LOCK_UN)

        if self.allow_in_memory_fallback:
            self.memory_store.setdefault(tab_name, []).append(dict(record))
            return True

        err_msg = (
            f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
            f"Business write for '{tab_name}' was blocked to prevent data loss."
        )
        logger.error(err_msg)
        if raise_on_error:
            raise RuntimeError(err_msg)
        return False

    @staticmethod
    def _matches_conditions(row: Dict[str, Any], conditions: Dict[str, Any]) -> bool:
        for k, expected in conditions.items():
            curr = row.get(k)
            if expected is None or expected == "":
                if str(curr or "").strip() not in {"", "0", "false", "none", "null"}:
                    return False
            elif expected is False:
                if str(curr or "").strip().lower() in {"true", "1", "yes"}:
                    return False
            elif expected is True:
                if str(curr or "").strip().lower() not in {"true", "1", "yes"}:
                    return False
            else:
                if str(curr or "").strip() != str(expected).strip():
                    return False
        return True

    def update_record(
        self,
        tab_name: str,
        id_field: str,
        id_value: str,
        updates: Dict[str, Any],
        raise_on_error: bool = False,
        expected_conditions: Optional[Dict[str, Any]] = None,
        authorize_header_update: bool = False,
    ) -> bool:
        """
        Updates an existing record matching id_field == id_value.
        
        CONCURRENCY & STORAGE ARCHITECTURE NOTICE:
        1. Single-Process / Thread Safety:
           Protected by `self._lock` (threading.RLock). Within this process, condition
           evaluation and updates to in-memory state are serialized and thread-safe.
        2. Google Sheets Storage Limitations:
           Google Sheets API is an HTTP REST service that does NOT support native ACID
           transactions, database row locks, or distributed Compare-And-Swap (CAS).
           Reading rows followed by batch_update introduces an inevitable TOCTOU window
           across independent OS worker processes or cloud replicas.
        3. Distributed Production Requirement:
           In multi-worker deployments (e.g. multiple Gunicorn/Uvicorn workers or containers),
           true distributed atomicity requires PostgreSQL with row locks (`SELECT ... FOR UPDATE`
           or conditional `UPDATE ... WHERE`) or Redis distributed locks (Redlock).
           Financial authorization remains fail-closed to prevent unverified updates.
        """
        with self._lock:
            self._assert_direct_mutation_allowed("update_record", tab_name)
            if is_forbidden_scratch_tab(tab_name):
                err_msg = f"Update blocked: legacy scratch tab '{tab_name}' is forbidden."
                if raise_on_error:
                    raise RuntimeError(err_msg)
                return False
            self._invalidate_records_cache(tab_name)
            failures = self._fail_once.get(tab_name, 0)
            if failures > 0:
                self._fail_once[tab_name] = failures - 1
                logger.error("Injected update failure for %s", tab_name)
                if raise_on_error:
                    raise RuntimeError(f"Injected failure updating {tab_name}")
                return False
            if not (self.is_connected and self.spreadsheet):
                shared_dir = self.shared_file_dir or os.getenv("SALES_SHARED_TEST_DIR")
                if shared_dir:
                    lock_path = self._tab_file_lock_path(tab_name)
                    with open(lock_path, "a") as lk:
                        if HAS_FCNTL:
                            fcntl.flock(lk, fcntl.LOCK_EX)
                        try:
                            rows = self._read_shared_records(tab_name)
                            found = False
                            for item in rows:
                                if str(item.get(id_field)) == str(id_value):
                                    if expected_conditions and not self._matches_conditions(item, expected_conditions):
                                        return False
                                    item.update(updates)
                                    found = True
                                    break
                            if found:
                                self._write_shared_records(tab_name, rows)
                                self.memory_store[tab_name] = rows
                            return found
                        except Exception as exc:
                            logger.error("Error in shared file update for %s: %s", tab_name, exc)
                            if raise_on_error:
                                raise
                            return False
                        finally:
                            if HAS_FCNTL:
                                fcntl.flock(lk, fcntl.LOCK_UN)

                if self.allow_in_memory_fallback:
                    found = False
                    for item in self.memory_store.get(tab_name, []):
                        if str(item.get(id_field)) == str(id_value):
                            if expected_conditions and not self._matches_conditions(item, expected_conditions):
                                return False
                            item.update(updates)
                            found = True
                            break
                    return found
                err_msg = (
                    f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
                    f"Business update for '{tab_name}' record {id_value} was blocked to prevent data loss."
                )
                logger.error(err_msg)
                if raise_on_error:
                    raise RuntimeError(err_msg)
                return False

            try:
                worksheet = self._get_worksheet(tab_name)
                records = self._safe_read_worksheet_records(worksheet, tab_name)
                headers = worksheet.row_values(1)
                header_map = {str(h).strip(): i + 1 for i, h in enumerate(headers) if str(h).strip()}
                lower_header_map = {str(h).strip().lower(): i + 1 for i, h in enumerate(headers) if str(h).strip()}
                missing = [
                    k for k in updates
                    if str(k).strip() not in header_map and str(k).strip().lower() not in lower_header_map
                ]
                if missing:
                    if authorize_header_update:
                        self._ensure_headers(worksheet, headers + missing)
                        headers = headers + missing
                        header_map = {str(h).strip(): i + 1 for i, h in enumerate(headers) if str(h).strip()}
                        lower_header_map = {str(h).strip().lower(): i + 1 for i, h in enumerate(headers) if str(h).strip()}
                    else:
                        logger.warning(
                            "Preserving existing sheet headers for '%s'; skipping unmapped update fields %s",
                            tab_name,
                            missing,
                        )
                for idx, row in enumerate(records, start=2):
                    if str(row.get(id_field)) != str(id_value):
                        continue
                    if expected_conditions and not self._matches_conditions(row, expected_conditions):
                        return False
                    cells = []
                    for key, value in updates.items():
                        col = header_map.get(str(key).strip()) or lower_header_map.get(str(key).strip().lower())
                        if col:
                            cells.append({"range": self._a1(col, idx, col), "values": [[value]]})
                    if cells:
                        worksheet.batch_update([{"range": c["range"], "values": c["values"]} for c in cells])
                    for item in self.memory_store.get(tab_name, []):
                        if str(item.get(id_field)) == str(id_value):
                            item.update(updates)
                            break
                    return True
                return False
            except Exception as exc:
                logger.error("Error updating record in %s: %s", tab_name, exc)
                if raise_on_error:
                    raise RuntimeError(f"Persistent update failed for {tab_name}: {exc}") from exc
                return False

    def delete_record(self, tab_name: str, id_field: str, id_value: str, raise_on_error: bool = False) -> bool:
        self._assert_direct_mutation_allowed("delete_record", tab_name)
        if is_forbidden_scratch_tab(tab_name):
            err_msg = f"Delete blocked: legacy scratch tab '{tab_name}' is forbidden."
            if raise_on_error:
                raise RuntimeError(err_msg)
            return False
        self._invalidate_records_cache(tab_name)
        if not (self.is_connected and self.spreadsheet):
            shared_dir = self.shared_file_dir or os.getenv("SALES_SHARED_TEST_DIR")
            if shared_dir:
                lock_path = self._tab_file_lock_path(tab_name)
                with open(lock_path, "a") as lk:
                    if HAS_FCNTL:
                        fcntl.flock(lk, fcntl.LOCK_EX)
                    try:
                        rows = self._read_shared_records(tab_name)
                        prev_len = len(rows)
                        rows = [item for item in rows if str(item.get(id_field)) != str(id_value)]
                        if len(rows) < prev_len:
                            self._write_shared_records(tab_name, rows)
                            self.memory_store[tab_name] = rows
                            return True
                        return False
                    except Exception as exc:
                        logger.error("Error in shared file delete for %s: %s", tab_name, exc)
                        if raise_on_error:
                            raise
                        return False
                    finally:
                        if HAS_FCNTL:
                            fcntl.flock(lk, fcntl.LOCK_UN)

            if self.allow_in_memory_fallback:
                prev_len = len(self.memory_store.get(tab_name, []))
                self.memory_store[tab_name] = [item for item in self.memory_store.get(tab_name, []) if str(item.get(id_field)) != str(id_value)]
                return len(self.memory_store[tab_name]) < prev_len
            err_msg = (
                f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
                f"Business delete for '{tab_name}' record {id_value} was blocked to prevent data loss."
            )
            logger.error(err_msg)
            if raise_on_error:
                raise RuntimeError(err_msg)
            return False

        try:
            worksheet = self._get_worksheet(tab_name)
            records = self._safe_read_worksheet_records(worksheet, tab_name)
            for idx, row in enumerate(records, start=2):
                if str(row.get(id_field)) == str(id_value):
                    worksheet.delete_rows(idx)
                    self.memory_store[tab_name] = [item for item in self.memory_store.get(tab_name, []) if str(item.get(id_field)) != str(id_value)]
                    return True
            return False
        except Exception as exc:
            logger.error("Error deleting record in %s: %s", tab_name, exc)
            if raise_on_error:
                raise RuntimeError(f"Persistent delete failed for {tab_name}: {exc}") from exc
            return False

    def _max_sequence(self, tab_name: str, prefix: str) -> int:
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        highest = 0
        sources = list(self.get_records(tab_name, fresh=True))
        try:
            sources.extend(self.get_records("IdAllocations", fresh=True))
        except Exception:
            sources.extend(self.memory_store.get("IdAllocations", []))
        for row in sources:
            values = [row.get("allocated_id", "")] if row.get("tab_name") else row.values()
            if row.get("tab_name") and str(row.get("tab_name")) != tab_name:
                continue
            for value in values:
                match = pattern.match(str(value).strip())
                if match:
                    highest = max(highest, int(match.group(1)))
        return highest

    def generate_id(self, tab_name: str) -> str:
        """Allocate PREFIX-000001 from the highest existing value, claimed before use.

        Under Blueprint v2.1 Single-Write-Owner, runtime ID allocation happens inside Apps Script.
        """
        self._assert_direct_mutation_allowed("generate_id", tab_name)
        prefix = ID_PREFIXES.get(tab_name, "ID")
        for _ in range(12):
            candidate = f"{prefix}-{self._max_sequence(tab_name, prefix) + 1:06d}"
            nonce = uuid.uuid4().hex
            claim = {
                "allocation_id": f"ALC-{nonce[:12]}",
                "tab_name": tab_name,
                "allocated_id": candidate,
                "nonce": nonce,
                "created_at": now_iso(),
            }
            if not self.append_record("IdAllocations", claim, raise_on_error=True):
                raise RuntimeError("Could not record an id allocation.")
            claims = [
                row for row in self.get_records("IdAllocations", fresh=True)
                if str(row.get("tab_name")) == tab_name and str(row.get("allocated_id")) == candidate
            ]
            if claims and str(claims[0].get("nonce")) == nonce:
                return candidate
        raise RuntimeError(f"Could not allocate a unique id for {tab_name}.")

    def get_next_id(self, tab_name: str) -> str:
        """Alias for generate_id for backwards and modular compatibility."""
        return self.generate_id(tab_name)

    def allocate_bill_number(self) -> str:
        self._assert_direct_mutation_allowed("allocate_bill_number", "Sales")
        from app.timeutil import business_month
        month = business_month()
        prefix = f"KS-BILL-{month}"
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        highest = 0
        for row in self.get_records("Sales", fresh=True):
            match = pattern.match(str(row.get("bill_number", "")).strip())
            if match:
                highest = max(highest, int(match.group(1)))
        for _ in range(12):
            candidate = f"{prefix}-{highest + 1:05d}"
            nonce = uuid.uuid4().hex
            claim = {
                "allocation_id": f"ALC-{nonce[:12]}",
                "tab_name": "BillNumbers",
                "allocated_id": candidate,
                "nonce": nonce,
                "created_at": now_iso(),
            }
            if not self.append_record("IdAllocations", claim, raise_on_error=True):
                raise RuntimeError("Could not allocate a bill number.")
            claims = [
                row for row in self.get_records("IdAllocations", fresh=True)
                if str(row.get("allocated_id")) == candidate
            ]
            if claims and str(claims[0].get("nonce")) == nonce:
                return candidate
            highest += 1
        raise RuntimeError("Could not allocate a unique bill number.")

    def log_audit(self, actor: str, action: str, entity_type: str, entity_id: str,
                  field_changed: str = "", old_val: str = "", new_val: str = "",
                  reason: str = "", approved_by: str = "", related_id: str = ""):
        # AuditLog sheet writes happen atomically inside Apps Script governed writes.
        # In non-testing runtime, record structured Python audit telemetry without mutating Google Sheets.
        if (self.is_connected and self.spreadsheet) or not self.allow_in_memory_fallback:
            logger.info(
                "AUDIT actor=%s action=%s entity=%s:%s reason=%s",
                actor,
                action,
                entity_type,
                entity_id,
                reason,
            )
            return
        try:
            audit_id = self.generate_id("AuditLog")
        except Exception:
            audit_id = f"AUD-{uuid.uuid4().hex[:12]}"
        record = {
            "audit_id": audit_id,
            "event_datetime": now_iso(),
            "actor_user_id": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_changed": field_changed,
            "old_value": str(old_val),
            "new_value": str(new_val),
            "reason": reason,
            "approved_by_user_id": approved_by,
            "related_record_id": related_id,
        }
        try:
            self.append_record("AuditLog", record, raise_on_error=False)
        except Exception as exc:
            logger.error("Audit log write failed: %s", exc)

    def inspect_schema_compatibility(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Read-only compatibility diagnostic comparing live or active sheet tabs/columns
        against REQUIRED_TABS without altering any headers, rows, or sheet structure.
        Explicitly separates HTTP 429 quota limits and network/API errors from genuine incompatibility.
        """
        core_columns: Dict[str, List[str]] = {
            "Users": ["user_id", "username", "role", "active"],
            "AuthUsers": ["auth_id", "user_id", "username", "password_hash", "role", "active"],
            "Products": ["product_id", "sku", "product_name", "pack_weight_g", "active"],
            "Customers": ["customer_id", "shop_name", "active"],
            "Sales": ["sale_id", "bill_number", "customer_id", "salesman_user_id", "bill_total"],
            "SaleItems": ["sale_item_id", "sale_id", "product_id", "quantity", "line_total"],
            "SalesmanStockLedger": ["stock_txn_id", "salesman_user_id", "product_id", "txn_type", "quantity"],
            "Recipes": ["recipe_id", "product_id", "product_name_snapshot", "approved", "items_json"],
            "RawMaterials": ["raw_material_id", "material_name", "current_stock", "unit"],
            "RawMaterialLedger": ["raw_material_txn_id", "material_name", "raw_material_id", "movement_type", "quantity"],
            "ProductionBatches": ["production_id", "product_id", "product_name_snapshot", "quantity_kg", "status"],
            "PackagingBatches": ["packaging_id", "product_id", "bulk_kg_used", "total_packets", "status"],
            "ProductionStockLedger": ["movement_id", "movement_type", "product_id"],
            "VanLoadingPasses": ["pass_id", "pass_number", "salesman_user_id", "status"],
            "AuditLog": ["audit_id", "event_datetime", "actor_user_id", "action"],
        }

        missing_tabs: List[str] = []
        missing_required_columns: Dict[str, List[str]] = {}
        missing_optional_columns: Dict[str, List[str]] = {}
        extra_columns_detected: Dict[str, List[str]] = {}
        checked_tabs = 0

        if self.is_connected and self.spreadsheet:
            snapshot = self._read_all_tab_headers_snapshot(force_refresh=force_refresh)
            tab_headers = snapshot.get("tab_headers", {})
            missing_tabs = list(snapshot.get("missing_tabs", []))
            unreadable_tabs = dict(snapshot.get("unreadable_tabs", {}))
            verification_completed = bool(snapshot.get("verification_completed"))
            error_type = snapshot.get("error_type")

            for tab, expected_cols in REQUIRED_TABS.items():
                if tab not in tab_headers:
                    continue
                checked_tabs += 1
                actual_headers = tab_headers[tab]
                actual_lower = {h.lower() for h in actual_headers}
                expected_lower = {c.lower() for c in expected_cols}
                required_set = core_columns.get(tab, expected_cols[:3])

                req_miss = [c for c in required_set if c.lower() not in actual_lower]
                opt_miss = [c for c in expected_cols if c not in required_set and c.lower() not in actual_lower]
                extras = [h for h in actual_headers if h.lower() not in expected_lower]

                if req_miss:
                    missing_required_columns[tab] = req_miss
                if opt_miss:
                    missing_optional_columns[tab] = opt_miss
                if extras:
                    extra_columns_detected[tab] = extras

            if error_type == "QUOTA_EXCEEDED":
                status = "TEMPORARILY_UNAVAILABLE"
                diagnostics = (
                    "Google Sheets API read quota temporarily exceeded (HTTP 429). "
                    "Verification could not complete; retry in a few moments."
                )
            elif not verification_completed or unreadable_tabs:
                status = "CHECK_FAILED"
                diagnostics = (
                    f"Schema verification could not complete ({error_type or 'API_ERROR'}): "
                    f"{snapshot.get('error') or 'One or more sheets could not be read.'}"
                )
            elif missing_tabs or missing_required_columns:
                status = "INCOMPATIBLE"
                diagnostics = "Required tabs or core columns are missing; inspect missing_tabs/missing_required_columns before writes."
            elif missing_optional_columns:
                status = "COMPATIBLE_WITH_OPTIONAL_GAPS"
                diagnostics = "Core tabs/columns satisfied; optional extension columns absent and handled safely in read/write mode."
            else:
                status = "COMPATIBLE"
                diagnostics = "All core schema requirements satisfied."

            return {
                "status": status,
                "mode": "GOOGLE_SHEETS_LIVE_READONLY",
                "mutated": False,
                "verification_completed": verification_completed,
                "error_type": error_type,
                "quota_exceeded": error_type == "QUOTA_EXCEEDED",
                "cached": bool(snapshot.get("cached", False)),
                "total_expected_tabs": len(REQUIRED_TABS),
                "checked_tabs": checked_tabs,
                "missing_tabs": missing_tabs,
                "unreadable_tabs": unreadable_tabs,
                "missing_required_columns": missing_required_columns,
                "missing_optional_columns": missing_optional_columns,
                "extra_columns_preserved": extra_columns_detected,
                "diagnostics": diagnostics,
            }

        if not self.allow_in_memory_fallback:
            return {
                "status": "CHECK_FAILED",
                "mode": "DISCONNECTED",
                "mutated": False,
                "verification_completed": False,
                "error_type": "DISCONNECTED",
                "quota_exceeded": False,
                "cached": False,
                "total_expected_tabs": len(REQUIRED_TABS),
                "checked_tabs": 0,
                "missing_tabs": [],
                "unreadable_tabs": {},
                "missing_required_columns": {},
                "missing_optional_columns": {},
                "extra_columns_preserved": {},
                "diagnostics": "Google Sheets is currently disconnected; schema verification could not complete.",
            }

        # Disconnected / test mode inspection over memory_store without mutations
        for tab, expected_cols in REQUIRED_TABS.items():
            rows = self.memory_store.get(tab, [])
            if not rows:
                continue
            checked_tabs += 1
            actual_keys = {str(k).strip() for r in rows for k in r.keys() if str(k).strip()}
            actual_lower = {k.lower() for k in actual_keys}
            expected_lower = {c.lower() for c in expected_cols}
            required_set = core_columns.get(tab, expected_cols[:3])
            req_miss = [c for c in required_set if c.lower() not in actual_lower]
            opt_miss = [c for c in expected_cols if c not in required_set and c.lower() not in actual_lower]
            extras = sorted(h for h in actual_keys if h.lower() not in expected_lower)
            if req_miss:
                missing_required_columns[tab] = req_miss
            if opt_miss:
                missing_optional_columns[tab] = opt_miss
            if extras:
                extra_columns_detected[tab] = extras

        return {
            "status": "TEST_OR_OFFLINE_COMPATIBLE" if not missing_required_columns else "INCOMPATIBLE",
            "mode": "MEMORY_STORE_READONLY",
            "mutated": False,
            "verification_completed": True,
            "error_type": None,
            "quota_exceeded": False,
            "cached": False,
            "total_expected_tabs": len(REQUIRED_TABS),
            "checked_tabs": checked_tabs,
            "missing_tabs": [],
            "unreadable_tabs": {},
            "missing_required_columns": missing_required_columns,
            "missing_optional_columns": missing_optional_columns,
            "extra_columns_preserved": extra_columns_detected,
            "diagnostics": "Read-only schema inspection completed without modifying spreadsheets.",
        }


db = SheetsDatabase()
