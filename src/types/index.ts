export type UserRole = 'OWNER' | 'PA' | 'SALESMAN';

export interface User {
  user_id: string;
  full_name: string;
  username: string;
  role: UserRole;
  mobile: string;
  email: string;
  active: boolean;
  created_at: string;
  notes: string;
  password?: string;
  sync_warning?: string;
}

export interface Product {
  product_id: string;
  sku: string;
  product_name: string;
  category: 'Papad' | 'Masala' | 'Katran' | string;
  variant: string;
  pack_weight_g: number;
  selling_unit: 'packet' | 'kg';
  retail_pack_only: boolean;
  active: boolean;
  notes: string;
}

export type CustomerType = 'RETAIL' | 'RETAILER' | 'WHOLESALER' | 'DISTRIBUTOR';

export interface Customer {
  customer_id: string;
  customer_type: CustomerType;
  shop_name: string;
  shopkeeper_name?: string;
  mobile?: string;
  alternate_mobile?: string;
  address?: string;
  locality_area?: string;
  city?: string;
  gstin?: string;
  map_location?: string;
  active: boolean;
  created_at: string;
  notes?: string;
}

export interface SaleItem {
  sale_item_id: string;
  sale_id: string;
  product_id: string;
  product_name_snapshot: string;
  sku_snapshot: string;
  pack_weight_g: number;
  unit: string;
  quantity: number;
  actual_unit_price: number;
  discount_amount: number;
  line_total: number;
  qualifying_kg: number;
  created_at: string;
  notes?: string;
}

export interface Sale {
  sale_id: string;
  bill_number: string;
  idempotency_key?: string;
  sale_datetime: string;
  sales_type: CustomerType;
  customer_id?: string;
  customer_name_snapshot: string;
  customer_mobile?: string;
  customer_gstin?: string;
  entered_by_user_id: string;
  salesman_user_id: string;
  delivery_status: 'DELIVERED' | 'PENDING' | 'CANCELLED';
  payment_status: 'PAID' | 'UNPAID';
  subtotal: number;
  discount_amount: number;
  tax_amount: number;
  bill_total: number;
  bill_status: 'ISSUED' | 'CANCELLED';
  created_at: string;
  notes?: string;
  lines?: SaleItem[];
  items?: SaleItem[];
  payment_method?: 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER' | string;
  payment_reference?: string;
  txn_status?: string;
}

export interface Payment {
  payment_id: string;
  sale_id: string;
  payment_datetime: string;
  payment_method: 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER';
  amount: number;
  reference_number: string;
  received_by_user_id: string;
  payment_status: 'RECEIVED';
  notes: string;
}

export type StockTxnType =
  | 'COMPANY_RECEIPT'
  | 'COMPANY_ADJUSTMENT'
  | 'COMPANY_SOLD'
  | 'ISSUED'
  | 'RETURNED'
  | 'SOLD'
  | 'SALESMAN_ADJUSTMENT';

export interface StockTransaction {
  stock_txn_id: string;
  txn_datetime: string;
  salesman_user_id: string;
  product_id: string;
  sku_snapshot: string;
  txn_type: StockTxnType;
  quantity: number;
  unit: string;
  pack_weight_g: number;
  related_sale_id: string;
  issued_by_user_id: string;
  received_by_user_id: string;
  confirmed_by_user_id: string;
  reference_id: string;
  notes: string;
}

export interface Expense {
  expense_id: string;
  expense_datetime: string;
  submitted_by_user_id: string;
  salesman_user_id: string;
  category: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL';
  amount: number;
  description: string;
  receipt_link_or_file_ref: string;
  approval_status: 'PENDING' | 'APPROVED' | 'REJECTED';
  approved_by_user_id: string;
  approval_datetime: string;
  cash_reducing_expense: boolean;
  related_closing_id: string;
  notes: string;
}

export interface ShopVisit {
  visit_id: string;
  visit_datetime: string;
  salesman_user_id: string;
  customer_id: string;
  shop_name_snapshot: string;
  visit_outcome: string;
  order_taken: boolean;
  follow_up_date: string;
  next_action: string;
  created_at: string;
  notes: string;
}

export interface DailyClosing {
  closing_id: string;
  closing_date: string;
  salesman_user_id: string;
  opening_cash: number;
  cash_collected: number;
  approved_cash_expenses: number;
  expected_cash_return: number;
  physical_cash_returned: number;
  cash_difference: number;
  opening_stock_reference: string;
  stock_discrepancy_flag: boolean;
  closing_status: 'SUBMITTED' | 'CONFIRMED' | 'CORRECTION_REQUIRED';
  submitted_at: string;
  reviewed_by_user_id: string;
  reviewed_at: string;
  notes: string;
}

export interface SalaryIncentive {
  record_id: string;
  period_start: string;
  period_end: string;
  salesman_user_id: string;
  record_type: 'TRIAL_INCENTIVE' | 'MONTHLY_INCENTIVE' | 'BASE_SALARY';
  eligible_kg: number;
  completed_100kg_blocks: number;
  rate: number;
  calculated_amount: number;
  approved_amount: number;
  approval_status: 'PENDING' | 'PROPOSED' | 'APPROVED' | 'REJECTED';
  approved_by_user_id: string;
  paid_datetime: string;
  payment_reference: string;
  notes: string;
}

export interface AuditLog {
  audit_id: string;
  event_datetime: string;
  actor_user_id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  field_changed: string;
  old_value: string;
  new_value: string;
  reason: string;
  approved_by_user_id: string;
  related_record_id: string;
}

export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED' | 'EXECUTED' | 'EXECUTION_FAILED';

export interface ApprovalRequest {
  request_id: string;
  request_type: 'CREATE_USER' | 'UPDATE_USER' | 'DEACTIVATE_USER' | 'REACTIVATE_USER' | 'RESET_PASSWORD';
  target_user_id: string;
  requested_by: string;
  requested_by_name: string;
  requested_at: string;
  payload_json: string;
  status: ApprovalStatus;
  decided_by?: string;
  decided_at?: string;
  decision_notes?: string;
  execution_error?: string;
  executed_at?: string;
  temporary_credentials?: string;
}

export interface ReconciliationReport {
  timestamp: string;
  total_users_count: number;
  total_auth_users_count: number;
  healthy: boolean;
  total_issues_count: number;
  orphaned_profiles: Array<{
    user_id: string;
    full_name?: string;
    username?: string;
    role?: string;
    active?: string | boolean;
    issue: string;
  }>;
  orphaned_auth_accounts: Array<{
    user_id: string;
    username?: string;
    role?: string;
    active?: string | boolean;
    issue: string;
  }>;
  duplicate_users: Array<{ user_id: string; count: number }>;
  duplicate_auth_users: Array<{ user_id: string; count: number }>;
  duplicate_usernames: Array<{ username: string; user_ids: string[] }>;
  role_mismatches: Array<{
    user_id: string;
    username?: string;
    users_role: string;
    auth_role: string;
    issue: string;
  }>;
  status_mismatches: Array<{
    user_id: string;
    username?: string;
    users_active: boolean;
    auth_active: boolean;
    issue: string;
  }>;
  insecure_credentials: Array<{
    user_id: string;
    username?: string;
    issue: string;
  }>;
}

export interface FinishedGoodsRegisterItem {
  product_id: string;
  sku: string;
  product_name: string;
  category: string;
  pack_weight_g: number;
  selling_unit: string;
  active: boolean;
  factory_packets: number;
  warehouse_packets: number;
  salesmen_packets: number;
  channels_dispatched_packets: number;
  total_internal_on_hand_packets: number;
  stock_status: 'IN_STOCK' | 'LOW_STOCK' | 'ZERO_STOCK';
}

export interface FinishedGoodsRegisterSummary {
  total_skus: number;
  active_skus: number;
  active_with_stock: number;
  active_zero_stock: number;
  factory_packets: number;
  warehouse_packets: number;
  salesmen_packets: number;
  channels_dispatched_packets: number;
  total_internal_on_hand_packets: number;
}

