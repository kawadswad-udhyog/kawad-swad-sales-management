from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# Auth Models
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    full_name: str
    role: str

class UserProfile(BaseModel):
    user_id: str
    full_name: str
    username: Optional[str] = None
    role: str
    mobile: Optional[str] = ""
    email: Optional[str] = ""
    active: bool = True
    created_at: Optional[str] = ""
    notes: Optional[str] = ""

class UserCreate(BaseModel):
    username: str
    full_name: str
    role: str = "SALESMAN"
    mobile: Optional[str] = ""
    email: Optional[str] = ""
    notes: Optional[str] = ""
    password: str

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

# Customer Models
class Customer(BaseModel):
    customer_id: str
    customer_type: str = "RETAILER"
    shop_name: str
    shopkeeper_name: str
    mobile: str
    alternate_mobile: Optional[str] = ""
    address: str
    locality_area: Optional[str] = ""
    city: Optional[str] = "Bhilwara"
    map_location: Optional[str] = ""
    active: bool = True
    created_at: Optional[str] = ""
    notes: Optional[str] = ""

class CustomerCreate(BaseModel):
    customer_type: str = "RETAILER"
    shop_name: str
    shopkeeper_name: str
    mobile: str
    alternate_mobile: Optional[str] = ""
    address: str
    locality_area: Optional[str] = ""
    city: Optional[str] = "Bhilwara"
    map_location: Optional[str] = ""
    notes: Optional[str] = ""

# Sales Models
class SaleItemCreate(BaseModel):
    product_id: str
    product_name_snapshot: Optional[str] = ""
    sku_snapshot: Optional[str] = ""
    pack_weight_g: int = 500
    unit: str = "PACKET"
    quantity: int = 1
    actual_unit_price: float
    discount_amount: float = 0.0
    line_total: float
    qualifying_kg: float = 0.0
    notes: Optional[str] = ""

class SaleCreate(BaseModel):
    sales_type: str = "Retailer Sale"
    customer_id: str
    customer_name_snapshot: str
    salesman_user_id: Optional[str] = ""
    delivery_status: str = "DELIVERED"
    payment_method: str = "CASH"
    payment_status: str = "PAID"
    subtotal: float
    discount_amount: float = 0.0
    tax_amount: float = 0.0
    bill_total: float
    notes: Optional[str] = ""
    items: List[SaleItemCreate]

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
    sale_datetime: str
    sales_type: str
    customer_id: str
    customer_name_snapshot: str
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

# Stock Models
class CompanyStockItem(BaseModel):
    product_id: str
    sku: str
    product_name: str
    current_stock: int
    unit: str = "PACKET"

class SalesmanStockItem(BaseModel):
    salesman_user_id: str
    product_id: str
    sku: str
    product_name: str
    current_stock: int
    unit: str = "PACKET"

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
    related_sale_id: Optional[str] = ""
    issued_by_user_id: Optional[str] = ""
    received_by_user_id: Optional[str] = ""
    confirmed_by_user_id: Optional[str] = ""
    reference_id: Optional[str] = ""
    notes: Optional[str] = ""

class StockIssueCreate(BaseModel):
    product_id: str
    salesman_user_id: str
    txn_type: str = "ISSUE_TO_SALESMAN"
    quantity: int
    notes: Optional[str] = ""
    reference_id: Optional[str] = ""

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

class DailyClosingCreate(BaseModel):
    opening_cash: float
    physical_cash_returned: float
    opening_stock_reference: Optional[str] = ""
    notes: Optional[str] = ""

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

# Dashboard Models
class DashboardMetrics(BaseModel):
    today_sales: float = 0.0
    today_cash: float = 0.0
    pending_expenses: int = 0
    low_stock_items: int = 0
    active_salesmen: int = 0
    total_bills_today: int = 0
