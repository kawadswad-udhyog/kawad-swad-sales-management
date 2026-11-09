from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# Auth Models
class LoginRequest(BaseModel):
    username: str
    password: str

class OwnerSetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Owner username (alphanumeric, min 3 chars)")
    full_name: str = Field(..., min_length=2, max_length=100, description="Owner full name")
    password: str = Field(..., min_length=12, max_length=128, description="Strong password, at least 12 characters")

class OwnerSetupResponse(BaseModel):
    success: bool = True
    message: str
    user_id: str
    username: str
    full_name: str
    role: str = "OWNER"
    created_at: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    full_name: str
    role: str
    must_change_password: bool = False

class UserProfile(BaseModel):
    user_id: str
    full_name: str
    username: Optional[str] = None
    role: str
    mobile: Optional[str] = ""
    email: Optional[str] = ""
    employment_type: Optional[str] = "SALARIED"
    designation: Optional[str] = ""
    department: Optional[str] = ""
    reporting_manager_id: Optional[str] = ""
    joining_date: Optional[str] = ""
    employment_status: Optional[str] = "ACTIVE"
    salary_frequency: Optional[str] = "MONTHLY"
    salary_structure_id: Optional[str] = ""
    address: Optional[str] = ""
    emergency_contact: Optional[str] = ""
    bank_details: Optional[str] = ""
    active: bool = True
    created_at: Optional[str] = ""
    notes: Optional[str] = ""

class UserCreate(BaseModel):
    username: str
    full_name: str
    role: str = "SALESMAN"
    mobile: Optional[str] = ""
    email: Optional[str] = ""
    employment_type: Optional[str] = "SALARIED"
    designation: Optional[str] = ""
    department: Optional[str] = ""
    reporting_manager_id: Optional[str] = ""
    joining_date: Optional[str] = ""
    employment_status: Optional[str] = "ACTIVE"
    salary_frequency: Optional[str] = "MONTHLY"
    salary_structure_id: Optional[str] = ""
    address: Optional[str] = ""
    emergency_contact: Optional[str] = ""
    bank_details: Optional[str] = ""
    notes: Optional[str] = ""
    password: Optional[str] = ""

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    employment_type: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    reporting_manager_id: Optional[str] = None
    joining_date: Optional[str] = None
    employment_status: Optional[str] = None
    salary_frequency: Optional[str] = None
    salary_structure_id: Optional[str] = None
    address: Optional[str] = None
    emergency_contact: Optional[str] = None
    bank_details: Optional[str] = None
    notes: Optional[str] = None

class UserStatusUpdate(BaseModel):
    active: bool
    reason: Optional[str] = ""

class CustomRoleCreate(BaseModel):
    role_name: str
    description: Optional[str] = ""
    permissions: Dict[str, List[str]]

class CustomRoleResponse(BaseModel):
    role_id: str
    role_name: str
    description: str = ""
    permissions: Dict[str, List[str]]
    created_at: str = ""
    created_by: str = ""

class ApprovalRequestModel(BaseModel):
    request_id: str
    request_type: str  # CREATE_USER, UPDATE_USER, DEACTIVATE_USER, REACTIVATE_USER, RESET_PASSWORD
    target_user_id: Optional[str] = ""
    requested_by: str
    requested_by_name: Optional[str] = ""
    requested_at: str
    payload_json: str
    status: str  # PENDING, APPROVED, REJECTED, CANCELLED, EXECUTED, EXECUTION_FAILED
    decided_by: Optional[str] = ""
    decided_at: Optional[str] = ""
    decision_notes: Optional[str] = ""
    execution_error: Optional[str] = ""
    executed_at: Optional[str] = ""
    temporary_credentials: Optional[str] = ""

class ApprovalDecisionRequest(BaseModel):
    decision: str  # APPROVED, REJECTED
    notes: Optional[str] = ""
    initial_password: Optional[str] = None

# Product Models
class Product(BaseModel):
    product_id: str
    sku: str
    product_name: str
    category: Optional[str] = "Papad"
    variant: Optional[str] = ""
    pack_weight_g: int = 500
    selling_unit: Optional[str] = "PACKET"
    retail_pack_only: bool = False
    active: bool = True
    notes: Optional[str] = ""

class ProductCreate(BaseModel):
    sku: str
    product_name: str
    category: Optional[str] = "Papad"
    variant: Optional[str] = ""
    pack_weight_g: int = 500
    selling_unit: Optional[str] = "PACKET"
    retail_pack_only: bool = False
    active: bool = True
    notes: Optional[str] = ""

class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    product_name: Optional[str] = None
    category: Optional[str] = None
    variant: Optional[str] = None
    pack_weight_g: Optional[int] = None
    selling_unit: Optional[str] = None
    retail_pack_only: Optional[bool] = None
    active: Optional[bool] = None
    notes: Optional[str] = None

# Customer Models
class Customer(BaseModel):
    customer_id: str
    customer_type: str = "RETAILER"
    shop_name: str
    shopkeeper_name: Optional[str] = ""
    mobile: Optional[str] = ""
    alternate_mobile: Optional[str] = ""
    address: Optional[str] = ""
    locality_area: Optional[str] = ""
    city: Optional[str] = "Bhilwara"
    gstin: Optional[str] = ""
    map_location: Optional[str] = ""
    active: bool = True
    created_at: Optional[str] = ""
    notes: Optional[str] = ""

class CustomerCreate(BaseModel):
    customer_type: Optional[str] = "RETAILER"
    shop_name: str
    shopkeeper_name: Optional[str] = ""
    mobile: Optional[str] = ""
    alternate_mobile: Optional[str] = ""
    address: Optional[str] = ""
    locality_area: Optional[str] = ""
    city: Optional[str] = "Bhilwara"
    gstin: Optional[str] = ""
    map_location: Optional[str] = ""
    notes: Optional[str] = ""

# Sales Models
class SaleItemCreate(BaseModel):
    product_id: str
    product_name_snapshot: Optional[str] = ""
    product_name: Optional[str] = ""
    sku_snapshot: Optional[str] = ""
    pack_weight_g: Optional[int] = 500
    unit: Optional[str] = "PACKET"
    quantity: int = 1
    actual_unit_price: Optional[float] = None
    unit_price: Optional[float] = None
    discount_amount: Optional[float] = 0.0
    line_total: Optional[float] = None
    total_amount: Optional[float] = None
    qualifying_kg: Optional[float] = 0.0
    notes: Optional[str] = ""

    def __init__(self, **data):
        if "unit_price" in data and ("actual_unit_price" not in data or data["actual_unit_price"] is None):
            data["actual_unit_price"] = data["unit_price"]
        if "total_amount" in data and ("line_total" not in data or data["line_total"] is None):
            data["line_total"] = data["total_amount"]
        if "product_name" in data and not data.get("product_name_snapshot"):
            data["product_name_snapshot"] = data["product_name"]
        super().__init__(**data)

class SaleCreate(BaseModel):
    idempotency_key: Optional[str] = Field(None, description="Client idempotency key for preventing duplicate billing")
    sales_type: Optional[str] = "Retailer Sale"
    customer_id: Optional[str] = ""
    customer_name_snapshot: Optional[str] = ""
    customer_mobile: Optional[str] = ""
    customer_email: Optional[str] = ""
    customer_address: Optional[str] = ""
    customer_gstin: Optional[str] = ""
    salesman_user_id: Optional[str] = ""
    delivery_status: Optional[str] = "DELIVERED"
    payment_method: Optional[str] = "CASH"
    payment_mode: Optional[str] = None
    payment_status: Optional[str] = "PAID"
    cash_collected: Optional[float] = None
    credit_amount: Optional[float] = None
    sale_date: Optional[str] = None
    subtotal: Optional[float] = None
    discount_amount: Optional[float] = 0.0
    tax_amount: Optional[float] = 0.0
    bill_total: Optional[float] = None
    notes: Optional[str] = ""
    payment_reference: Optional[str] = ""
    items: Optional[List[SaleItemCreate]] = None
    lines: Optional[List[SaleItemCreate]] = None

class SaleItem(BaseModel):
    sale_item_id: str
    sale_id: str
    product_id: str
    product_name_snapshot: str
    sku_snapshot: str
    pack_weight_g: int
    unit: str
    quantity: int
    actual_unit_price: float
    discount_amount: float
    line_total: float
    qualifying_kg: float
    created_at: str
    notes: Optional[str] = ""

class Sale(BaseModel):
    sale_id: str
    bill_number: str
    idempotency_key: Optional[str] = ""
    sale_datetime: str
    sales_type: str
    customer_id: Optional[str] = ""
    customer_name_snapshot: Optional[str] = ""
    customer_mobile: Optional[str] = ""
    customer_gstin: Optional[str] = ""
    entered_by_user_id: str
    salesman_user_id: str
    delivery_status: str
    payment_status: str
    subtotal: float
    discount_amount: float
    tax_amount: float
    bill_total: float
    bill_status: str
    created_at: str
    notes: Optional[str] = ""
    items: Optional[List[SaleItem]] = []
    lines: Optional[List[SaleItem]] = None
    txn_status: Optional[str] = "COMPLETE"
    payment_method: Optional[str] = ""
    payment_reference: Optional[str] = ""
    total_amount: Optional[float] = None
    cash_collected: Optional[float] = None
    credit_amount: Optional[float] = None

class SalePaymentCreate(BaseModel):
    amount: float = Field(..., gt=0)
    payment_method: str = "CASH"
    reference_number: Optional[str] = ""
    notes: Optional[str] = ""
    idempotency_key: Optional[str] = None

# Stock Models
class CompanyStockItem(BaseModel):
    product_id: str
    sku: str
    product_name: str
    current_stock: int
    unit: str = "PACKET"
    company_quantity: int = 0
    quantity: int = 0
    pack_weight_g: int = 500

class SalesmanStockItem(BaseModel):
    salesman_user_id: str
    product_id: str
    sku: str
    product_name: str
    current_stock: int
    unit: str = "PACKET"
    quantity: int = 0
    salesman_name: str = ""
    pack_weight_g: int = 500

class StockSummaryResponse(BaseModel):
    company_stock: List[CompanyStockItem]
    salesman_stock: List[SalesmanStockItem]

class StockTransaction(BaseModel):
    stock_txn_id: str
    txn_datetime: str
    salesman_user_id: str
    product_id: str
    sku_snapshot: str
    txn_type: str
    quantity: int
    unit: str
    pack_weight_g: int
    movement_id: Optional[str] = None
    quantity_packets: Optional[int] = None
    related_sale_id: Optional[str] = ""
    issued_by_user_id: Optional[str] = ""
    received_by_user_id: Optional[str] = ""
    confirmed_by_user_id: Optional[str] = ""
    reference_id: Optional[str] = ""
    notes: Optional[str] = ""

    def __init__(self, **data):
        if "movement_id" not in data or not data["movement_id"]:
            data["movement_id"] = data.get("stock_txn_id")
        if "quantity_packets" not in data or data["quantity_packets"] is None:
            data["quantity_packets"] = data.get("quantity")
        super().__init__(**data)

class StockIssueCreate(BaseModel):
    product_id: str
    salesman_user_id: str
    txn_type: str = "ISSUE_TO_SALESMAN"
    quantity: Optional[int] = None
    quantity_packets: Optional[int] = None
    issue_date: Optional[str] = None
    notes: Optional[str] = ""
    reference_id: Optional[str] = ""

    def __init__(self, **data):
        if ("quantity" not in data or data["quantity"] is None) and "quantity_packets" in data:
            data["quantity"] = data["quantity_packets"]
        super().__init__(**data)

# Expense Models
class Expense(BaseModel):
    expense_id: str
    expense_datetime: str
    submitted_by_user_id: str
    salesman_user_id: str
    category: str
    amount: float
    description: str
    receipt_link_or_file_ref: Optional[str] = ""
    approval_status: str = "PENDING"
    approved_by_user_id: Optional[str] = ""
    approval_datetime: Optional[str] = ""
    cash_reducing_expense: bool = False
    related_closing_id: Optional[str] = ""
    notes: Optional[str] = ""

class ExpenseCreate(BaseModel):
    category: str
    amount: float
    description: str
    receipt_link_or_file_ref: Optional[str] = ""
    salesman_user_id: Optional[str] = ""
    notes: Optional[str] = ""

class ExpenseApproveRequest(BaseModel):
    approved: bool
    notes: Optional[str] = ""
    cash_reducing: Optional[bool] = None

# Shop Visit Models
class ShopVisit(BaseModel):
    visit_id: str
    visit_datetime: str
    salesman_user_id: str
    customer_id: str
    shop_name_snapshot: str
    visit_outcome: str
    order_taken: bool = False
    follow_up_date: Optional[str] = ""
    next_action: Optional[str] = ""
    created_at: str
    notes: Optional[str] = ""

class ShopVisitCreate(BaseModel):
    customer_id: str
    shop_name_snapshot: str
    visit_outcome: str
    order_taken: bool = False
    follow_up_date: Optional[str] = ""
    next_action: Optional[str] = ""
    notes: Optional[str] = ""

# Daily Closing Models
class DailyClosing(BaseModel):
    closing_id: str
    closing_date: str
    salesman_user_id: str
    opening_cash: float
    cash_collected: float
    approved_cash_expenses: float
    expected_cash_return: float
    physical_cash_returned: float
    cash_difference: float
    opening_stock_reference: Optional[str] = ""
    stock_discrepancy_flag: bool = False
    closing_status: str = "SUBMITTED"
    submitted_at: str
    reviewed_by_user_id: Optional[str] = ""
    reviewed_at: Optional[str] = ""
    notes: Optional[str] = ""
    upi_collected: float = 0
    bank_collected: float = 0
    other_collected: float = 0

class DailyClosingCreate(BaseModel):
    opening_cash: float
    physical_cash_returned: float
    opening_stock_reference: Optional[str] = ""
    notes: Optional[str] = ""
    idempotency_key: Optional[str] = ""
    physical_stock: Optional[List[Dict[str, Any]]] = None

class ClosingReviewRequest(BaseModel):
    confirmed: bool
    notes: Optional[str] = ""

# Salary Models
class SalaryRecord(BaseModel):
    record_id: str
    period_start: str
    period_end: str
    salesman_user_id: str
    record_type: str
    eligible_kg: float
    completed_100kg_blocks: int
    rate: float
    calculated_amount: float
    approved_amount: float
    approval_status: str
    approved_by_user_id: Optional[str] = ""
    paid_datetime: Optional[str] = ""
    payment_reference: Optional[str] = ""
    notes: Optional[str] = ""

class SalaryCreateRequest(BaseModel):
    period_start: str
    period_end: str
    salesman_user_id: str
    record_type: str
    eligible_kg: float = 0.0
    completed_100kg_blocks: int = 0
    rate: float = 0.0
    calculated_amount: float
    approved_amount: Optional[float] = None
    notes: Optional[str] = ""

class SalaryApproveRequest(BaseModel):
    approved_amount: Optional[float] = None
    notes: Optional[str] = ""

class SalaryPayRequest(BaseModel):
    payment_reference: str
    notes: Optional[str] = ""

# Audit Log Models
class AuditLogItem(BaseModel):
    audit_id: str
    event_datetime: str
    actor_user_id: str
    action: str
    entity_type: str
    entity_id: str
    field_changed: Optional[str] = ""
    old_value: Optional[str] = ""
    new_value: Optional[str] = ""
    reason: Optional[str] = ""
    approved_by_user_id: Optional[str] = ""
    related_record_id: Optional[str] = ""

class AuditLogCreate(BaseModel):
    action: str
    entity_type: str
    entity_id: str
    field_changed: Optional[str] = ""
    old_value: Optional[str] = ""
    new_value: Optional[str] = ""
    reason: Optional[str] = ""
    related_record_id: Optional[str] = ""

# Attendance Models
class BulkAttendanceItem(BaseModel):
    worker_id: str
    status: str = "PRESENT"
    notes: Optional[str] = ""

class BulkAttendanceCreate(BaseModel):
    attendance_date: str
    records: List[BulkAttendanceItem]

class BulkAttendanceResponse(BaseModel):
    status: str
    attendance_date: str
    saved_count: int
    skipped_count: int
    saved_records: List[Dict[str, Any]] = []
    skipped_workers: List[Dict[str, Any]] = []
    message: str

# Dashboard Models
class DashboardMetrics(BaseModel):
    today_sales: float = 0.0
    today_cash: float = 0.0
    pending_expenses: int = 0
    low_stock_items: int = 0
    zero_stock_items_count: int = 0
    active_salesmen: int = 0
    total_bills_today: int = 0
    monthly_sales: float = 0.0
    today_kg_sold: float = 0.0
    monthly_kg_sold: float = 0.0
    digital_collections_today: float = 0.0
    incomplete_transactions_count: int = 0
    pending_discrepancies: int = 0
    pending_production_approvals: int = 0
    today_production_kg: float = 0.0
    pending_production_kg: float = 0.0
    available_finished_packets: int = 0
    active_workers_count: int = 0
    workers_present_today: int = 0
    role: str = "OWNER"
    salesman_user_id: Optional[str] = None


# ============================================================================
# WORKFORCE, LABOUR, PAYROLL & TASK MODELS
# ============================================================================

class EmployeeAttendanceRecord(BaseModel):
    attendance_id: Optional[str] = ""
    employee_id: str
    employee_name: Optional[str] = ""
    attendance_date: str
    check_in_time: Optional[str] = ""
    check_out_time: Optional[str] = ""
    total_hours: float = 0.0
    status: str = "PRESENT"
    notes: Optional[str] = ""
    verified_by: Optional[str] = ""
    created_at: Optional[str] = ""

class EmployeeAttendanceCheckIn(BaseModel):
    notes: Optional[str] = ""

class EmployeeAttendanceCheckOut(BaseModel):
    notes: Optional[str] = ""

class WorkAssignmentModel(BaseModel):
    task_id: Optional[str] = ""
    title: str
    description: Optional[str] = ""
    assigned_to_user_id: str
    assigned_to_name: Optional[str] = ""
    role: Optional[str] = ""
    priority: str = "MEDIUM"
    status: str = "PENDING"
    due_date: Optional[str] = ""
    created_by: Optional[str] = ""
    submission_notes: Optional[str] = ""
    proof_url: Optional[str] = ""
    review_notes: Optional[str] = ""
    created_at: Optional[str] = ""
    completed_at: Optional[str] = ""

class WorkAssignmentCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    assigned_to_user_id: str
    role: Optional[str] = ""
    priority: str = "MEDIUM"
    due_date: Optional[str] = ""

class WorkAssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None

class WorkAssignmentSubmit(BaseModel):
    submission_notes: str
    proof_url: Optional[str] = ""

class WorkAssignmentReview(BaseModel):
    status: str
    review_notes: Optional[str] = ""

class FreelancerProjectModel(BaseModel):
    project_id: Optional[str] = ""
    title: str
    description: Optional[str] = ""
    freelancer_user_id: str
    freelancer_name: Optional[str] = ""
    total_budget: float = 0.0
    currency: str = "INR"
    start_date: Optional[str] = ""
    target_completion_date: Optional[str] = ""
    status: str = "IN_PROGRESS"
    deliverables_summary: Optional[str] = ""
    notes: Optional[str] = ""
    created_at: Optional[str] = ""

class FreelancerProjectCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    freelancer_user_id: str
    total_budget: float = 0.0
    start_date: Optional[str] = ""
    target_completion_date: Optional[str] = ""
    deliverables_summary: Optional[str] = ""
    notes: Optional[str] = ""

class FreelancerMilestoneModel(BaseModel):
    milestone_id: Optional[str] = ""
    project_id: str
    title: str
    description: Optional[str] = ""
    amount: float = 0.0
    due_date: Optional[str] = ""
    status: str = "PENDING"
    submission_notes: Optional[str] = ""
    submission_link: Optional[str] = ""
    review_notes: Optional[str] = ""
    approved_at: Optional[str] = ""
    created_at: Optional[str] = ""

class FreelancerMilestoneCreate(BaseModel):
    project_id: str
    title: str
    description: Optional[str] = ""
    amount: float
    due_date: Optional[str] = ""

class FreelancerMilestoneSubmit(BaseModel):
    submission_notes: str
    submission_link: Optional[str] = ""

class FreelancerMilestoneReview(BaseModel):
    status: str
    review_notes: Optional[str] = ""

class LabourMasterModel(BaseModel):
    labour_id: Optional[str] = ""
    full_name: str
    category: str = "GENERAL"
    wage_type: str = "DAILY"
    base_rate: float = 0.0
    daily_expected_hours: float = 8.0
    mobile: Optional[str] = ""
    emergency_contact: Optional[str] = ""
    address: Optional[str] = ""
    bank_account_no: Optional[str] = ""
    bank_ifsc: Optional[str] = ""
    active: bool = True
    notes: Optional[str] = ""
    created_at: Optional[str] = ""

class LabourCreate(BaseModel):
    full_name: str
    category: str = "GENERAL"
    wage_type: str = "DAILY"
    base_rate: float = 0.0
    daily_expected_hours: float = 8.0
    mobile: Optional[str] = ""
    emergency_contact: Optional[str] = ""
    address: Optional[str] = ""
    bank_account_no: Optional[str] = ""
    bank_ifsc: Optional[str] = ""
    notes: Optional[str] = ""

class LabourUpdate(BaseModel):
    full_name: Optional[str] = None
    category: Optional[str] = None
    wage_type: Optional[str] = None
    base_rate: Optional[float] = None
    daily_expected_hours: Optional[float] = None
    mobile: Optional[str] = None
    emergency_contact: Optional[str] = None
    address: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    active: Optional[bool] = None
    notes: Optional[str] = None

class LabourAttendanceItem(BaseModel):
    labour_id: str
    attendance_date: str
    status: str = "PRESENT"
    hours_worked: float = 8.0
    overtime_hours: float = 0.0
    notes: Optional[str] = ""

class LabourAttendanceBulk(BaseModel):
    attendance_date: str
    records: List[LabourAttendanceItem]

class LabourWorkEntryCreate(BaseModel):
    labour_id: str
    entry_date: str
    category: Optional[str] = ""
    activity_name: str
    batch_id: Optional[str] = ""
    units_completed: float = 0.0
    unit_of_measure: str = "KG"
    piece_rate: float = 0.0
    hours_logged: float = 0.0
    notes: Optional[str] = ""

class SalaryStructureModel(BaseModel):
    structure_id: Optional[str] = ""
    user_id: str
    basic_salary: float = 0.0
    hra: float = 0.0
    transport_allowance: float = 0.0
    special_allowance: float = 0.0
    sales_commission_rate: float = 0.0
    pf_deduction: float = 0.0
    tds_deduction: float = 0.0
    other_deductions: float = 0.0
    payment_mode: str = "BANK_TRANSFER"
    effective_from: Optional[str] = ""
    notes: Optional[str] = ""

class SalaryStructureCreate(BaseModel):
    user_id: str
    basic_salary: float = 0.0
    hra: float = 0.0
    transport_allowance: float = 0.0
    special_allowance: float = 0.0
    sales_commission_rate: float = 0.0
    pf_deduction: float = 0.0
    tds_deduction: float = 0.0
    other_deductions: float = 0.0
    payment_mode: str = "BANK_TRANSFER"
    effective_from: Optional[str] = ""
    notes: Optional[str] = ""

class PayrollRunCreate(BaseModel):
    month: str  # YYYY-MM
    run_date: Optional[str] = ""
    notes: Optional[str] = ""

class PayrollItemUpdate(BaseModel):
    deductions: Optional[float] = None
    incentive_amount: Optional[float] = None
    bonus_amount: Optional[float] = None
    adjustment_amount: Optional[float] = None
    notes: Optional[str] = None

class WorkforcePaymentCreate(BaseModel):
    reference_id: str
    payment_type: str  # SALARY, LABOUR_WAGE, FREELANCER_MILESTONE, INCENTIVE
    recipient_id: str
    recipient_name: str
    amount: float
    payment_method: str = "BANK_TRANSFER"
    payment_reference: Optional[str] = ""
    payment_date: Optional[str] = ""
    bank_account_credited: Optional[str] = ""
    notes: Optional[str] = ""

class SalaryReceiptModel(BaseModel):
    receipt_id: str
    receipt_number: str
    recipient_id: str
    recipient_name: str
    recipient_type: str
    role_or_category: str
    period_start: str
    period_end: str
    payment_date: str
    payment_method: str
    payment_reference: str
    gross_earnings: float
    total_deductions: float
    net_paid: float
    notes: str
