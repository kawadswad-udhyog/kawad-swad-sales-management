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
  request_type: 'CREATE_USER' | 'UPDATE_USER' | 'DEACTIVATE_USER' | 'REACTIVATE_USER' | 'RESET_PASSWORD' | 'PRODUCTION_BATCH' | string;
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
  factory_packets?: number;
  warehouse_packets?: number;
  salesmen_packets?: number;
  factory_stock?: number;
  warehouse_stock?: number;
  salesmen_stock?: number;
  total_internal_on_hand?: number;
  available_to_sell?: number;
  channels_dispatched_packets?: number;
  total_internal_on_hand_packets?: number;
  stock_status?: 'IN_STOCK' | 'LOW_STOCK' | 'ZERO_STOCK';
  status?: string;
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

export interface DashboardMetrics {
  today_sales: number;
  today_cash: number;
  total_bills_today: number;
  pending_expenses: number;
  low_stock_items: number;
  active_salesmen: number;
  monthly_sales?: number;
  today_kg_sold?: number;
  monthly_kg_sold?: number;
  digital_collections_today?: number;
  incomplete_transactions_count?: number;
  pending_discrepancies?: number;
  pending_production_approvals?: number;
  today_production_kg?: number;
  pending_production_kg?: number;
  available_finished_packets?: number;
  active_workers_count?: number;
  workers_present_today?: number;
  zero_stock_items_count?: number;
  role?: string;
  salesman_user_id?: string | null;
}

// -------------------------------------------------------------
// Purchasing & Supplier Types
// -------------------------------------------------------------

export interface Supplier {
  supplier_id: string;
  supplier_code?: string;
  supplier_name: string;
  contact_person?: string;
  mobile?: string;
  email?: string;
  address?: string;
  city?: string;
  gstin?: string;
  payment_terms_days?: number;
  active: boolean | string;
  created_at: string;
  created_by?: string;
  notes?: string;
}

export interface PurchaseOrderItem {
  po_item_id: string;
  po_id: string;
  raw_material_id: string;
  material_name: string;
  ordered_quantity: number;
  received_quantity: number;
  unit: string;
  unit_price: number;
  tax_amount: number;
  line_total: number;
  notes?: string;
}

export interface PurchaseOrder {
  po_id: string;
  po_number: string;
  supplier_id: string;
  supplier_name: string;
  order_date: string;
  expected_delivery_date?: string;
  total_amount: number;
  status: 'DRAFT' | 'APPROVED' | 'PARTIALLY_RECEIVED' | 'COMPLETED' | 'CANCELLED' | 'CONFIRMED' | 'FULFILLED' | string;
  created_by: string;
  created_at: string;
  approved_by?: string;
  approved_at?: string;
  notes?: string;
  items?: PurchaseOrderItem[];
}

export interface GoodsReceiptItem {
  receipt_item_id: string;
  receipt_id: string;
  po_item_id?: string;
  raw_material_id: string;
  material_name: string;
  delivered_quantity: number;
  accepted_quantity: number;
  rejected_quantity: number;
  unit: string;
  unit_rate: number;
  rejection_reason?: string;
  stock_movement_id?: string;
  notes?: string;
}

export interface GoodsReceipt {
  receipt_id: string;
  grn_id?: string;
  receipt_number: string;
  grn_number?: string;
  po_id?: string;
  supplier_id: string;
  supplier_name: string;
  receipt_date: string;
  invoice_reference: string;
  delivery_challan?: string;
  vendor_delivery_challan?: string;
  vehicle_number?: string;
  total_accepted_qty: number;
  total_rejected_qty: number;
  quality_status: 'ACCEPTED' | 'REJECTED' | 'CONDITIONAL';
  status: string;
  received_by: string;
  created_at: string;
  notes?: string;
  items?: GoodsReceiptItem[];
}

export interface SupplierBill {
  bill_id: string;
  bill_number: string;
  supplier_id: string;
  supplier_name: string;
  receipt_id?: string;
  po_id?: string;
  bill_date: string;
  due_date: string;
  subtotal: number;
  tax_amount: number;
  total_amount: number;
  paid_amount: number;
  balance_amount: number;
  payment_status: 'UNPAID' | 'PARTIALLY_PAID' | 'PAID';
  status: string;
  created_by: string;
  created_at: string;
  notes?: string;
}

export interface SupplierPayment {
  payment_id: string;
  payment_number?: string;
  bill_id: string;
  supplier_id: string;
  supplier_name: string;
  payment_date: string;
  amount: number;
  payment_method: string;
  payment_mode?: string;
  reference_number: string;
  reference_no?: string;
  status: string;
  paid_by: string;
  created_at: string;
  notes?: string;
}

export interface SupplierReturnItem {
  return_item_id: string;
  return_id: string;
  raw_material_id: string;
  material_name: string;
  quantity: number;
  unit: string;
  unit_rate: number;
  return_amount: number;
  reason: string;
  stock_movement_id?: string;
  notes?: string;
}

export interface SupplierReturn {
  return_id: string;
  return_number: string;
  receipt_id?: string;
  supplier_id: string;
  supplier_name: string;
  return_date: string;
  reason?: string;
  total_amount?: number;
  status: string;
  approved_by?: string;
  approved_at?: string;
  created_by: string;
  created_at: string;
  notes?: string;
  items?: SupplierReturnItem[];
}

// -------------------------------------------------------------
// Quality, Lots & Returns Types
// -------------------------------------------------------------

export interface QualityCheck {
  qc_id: string;
  check_id?: string;
  check_number?: string;
  check_date: string;
  check_type: string;
  reference_type: string;
  reference_id: string;
  product_or_material_id: string;
  item_name: string;
  inspector_user_id: string;
  status: string;
  decision: 'PASS' | 'FAIL' | 'HOLD';
  parameters_json?: string;
  defect_details?: string;
  corrective_action?: string;
  created_at: string;
  notes?: string;
}

export interface ProductLot {
  lot_id: string;
  lot_number: string;
  product_id: string;
  product_name: string;
  production_id?: string;
  packaging_id?: string;
  creation_date: string;
  expiry_date?: string;
  initial_quantity: number;
  current_quantity: number;
  unit: string;
  quality_status: 'RELEASED' | 'QUARANTINE' | 'REJECTED' | 'RECALLED';
  hold_reason?: string;
  status: string;
  created_at: string;
  created_by?: string;
  notes?: string;
}

export interface LotMovement {
  movement_id: string;
  lot_id: string;
  movement_type: string;
  movement_date: string;
  quantity: number;
  unit: string;
  reference_type: string;
  reference_id: string;
  performed_by?: string;
  notes?: string;
  created_at: string;
}

export interface CustomerReturnItem {
  return_item_id: string;
  return_id: string;
  product_id: string;
  sku: string;
  product_name: string;
  quantity: number;
  unit: string;
  unit_price: number;
  refund_amount: number;
  reason: string;
  inspection_notes?: string;
  stock_movement_id?: string;
  notes?: string;
}

export interface CustomerReturn {
  return_id: string;
  return_number: string;
  sale_id: string;
  bill_number?: string;
  customer_id: string;
  customer_name: string;
  return_date: string;
  status: string;
  inspection_status: string;
  disposition: 'SCRAP' | 'RESTOCK' | 'PENDING_INSPECTION';
  approved_by?: string;
  approved_at?: string;
  created_by: string;
  created_at: string;
  notes?: string;
  items?: CustomerReturnItem[];
}

export interface ComplaintRecall {
  complaint_id: string;
  report_date: string;
  report_type: 'COMPLAINT' | 'RECALL';
  customer_id?: string;
  customer_name?: string;
  product_id: string;
  lot_id?: string;
  quantity_affected: number;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: 'OPEN' | 'IN_INVESTIGATION' | 'CLOSED';
  description: string;
  investigation?: string;
  corrective_action?: string;
  responsible_user_id?: string;
  closure_date?: string;
  created_at: string;
  notes?: string;
}

// -------------------------------------------------------------
// Milling Batch Types
// -------------------------------------------------------------

export interface MillingBatch {
  milling_batch_id: string;
  batch_date: string;
  source_material_id: string;
  source_material_name: string;
  input_quantity_kg: number;
  target_flour_id: string;
  target_flour_name: string;
  flour_output_kg: number;
  processing_loss_kg: number;
  yield_ratio: number;
  source_unit_rate: number;
  milling_expenses: number;
  total_flour_cost: number;
  flour_unit_cost: number;
  status: string;
  created_by: string;
  created_at: string;
  notes?: string;
}

// -------------------------------------------------------------
// Extended Accounting & Debtors / Creditors Types
// -------------------------------------------------------------

export interface DebtorItem {
  customer_id: string;
  customer_name: string;
  city?: string;
  total_invoiced: number;
  total_collected: number;
  outstanding_balance: number;
  unpaid_invoices_count: number;
}

export interface CreditorItem {
  supplier_id: string;
  supplier_name: string;
  total_billed: number;
  total_paid: number;
  outstanding_payable: number;
  open_bills_count: number;
}

export interface CashBankReport {
  factory_safe_cash: number;
  salesman_van_float: number;
  bank_account_balance: number;
  total_liquid_funds: number;
}

export interface GstSummaryReport {
  period: { start_date: string; end_date: string };
  output_cgst_payable: number;
  output_sgst_payable: number;
  total_output_gst: number;
  input_cgst_itc: number;
  input_sgst_itc: number;
  total_input_itc: number;
  net_gst_payable: number;
  excess_itc_credit: number;
}

export interface AccountingPeriod {
  period_id: string;
  period_name: string;
  start_date: string;
  end_date: string;
  is_closed: boolean | string;
  closed_by?: string;
  closed_at?: string;
}

