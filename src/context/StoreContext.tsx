import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
  User,
  Product,
  Customer,
  Sale,
  SaleItem,
  Payment,
  StockTransaction,
  Expense,
  ShopVisit,
  DailyClosing,
  SalaryIncentive,
  AuditLog,
  StockTxnType,
  CustomerType,
  ApprovalRequest,
  StorageStatus,
  ErpCapabilitiesPayload,
} from '../types';
import {
  apiRequest,
  ApiHttpError,
  getAuthToken,
  setAuthToken,
  getApiBaseUrl,
  setApiBaseUrl,
  fetchBackendHealth,
  fetchV2Capabilities,
  fetchOwnerBootstrapStatus,
  submitOwnerBootstrap,
  createSubmissionNonce,
  OwnerBootstrapStatus,
  OwnerBootstrapResponse,
} from '../services/api';

export interface CompanyStockItem {
  product_id: string;
  sku: string;
  product_name: string;
  pack_weight_g: number;
  company_quantity: number;
}

export interface SalesmanStockItem {
  salesman_user_id: string;
  salesman_name: string;
  product_id: string;
  sku: string;
  product_name: string;
  quantity: number;
}

export interface CreateSaleInput {
  customer_id?: string;
  customer_name_snapshot?: string;
  customer_mobile?: string;
  customer_gstin?: string;
  sales_type: CustomerType;
  payment_method: 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER';
  payment_reference: string;
  discount_amount: number;
  notes: string;
  delivery_status?: 'DELIVERED' | 'PENDING' | 'CANCELLED';
  idempotency_key?: string;
  lines: Array<{
    product_id: string;
    quantity: number;
    actual_unit_price: number;
  }>;
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

export interface StoreContextType {
  currentUser: User | null;
  isLoading: boolean;
  isBackendConnected: boolean;
  backendUrl: string;
  updateBackendUrl: (url: string) => void;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  users: User[];
  createUser: (user: {
    user_id?: string;
    full_name: string;
    username: string;
    password: string;
    role: string;
    mobile?: string;
    email?: string;
    active?: boolean;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string }>;
  updateUser: (user_id: string, updates: Partial<User>, idempotencyKey?: string) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string; user?: User }>;
  setUserStatus: (user_id: string, active: boolean, reason?: string, idempotencyKey?: string) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string }>;
  resetUserPassword: (user_id: string, newPassword?: string, idempotencyKey?: string) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string }>;

  approvalRequests: ApprovalRequest[];
  loadApprovalRequests: () => Promise<void>;
  decideApprovalRequest: (requestId: string, decision: 'APPROVED' | 'REJECTED', notes?: string, initialPassword?: string, idempotencyKey?: string) => Promise<ApprovalRequest>;
  retryApprovalRequest: (requestId: string, idempotencyKey?: string) => Promise<void>;
  cancelApprovalRequest: (requestId: string, idempotencyKey?: string) => Promise<void>;

  products: Product[];
  addProduct: (product: Omit<Product, 'product_id'>, idempotencyKey?: string) => Promise<Product>;
  updateProduct: (product_id: string, updates: Partial<Product>, idempotencyKey?: string) => Promise<void>;
  toggleProductActive: (product_id: string, idempotencyKey?: string) => Promise<void>;

  customers: Customer[];
  addCustomer: (customer: Omit<Customer, 'customer_id' | 'created_at'>, idempotencyKey?: string) => Promise<Customer>;
  updateCustomer: (customer_id: string, updates: Partial<Customer>, idempotencyKey?: string) => Promise<void>;
  activeCustomerIdForBilling: string | null;
  setActiveCustomerIdForBilling: (id: string | null) => void;

  sales: Sale[];
  payments: Payment[];
  createSale: (input: CreateSaleInput, idempotencyKey?: string) => Promise<{ sale: Sale; paymentId?: string }>;
  getSaleWithItems: (sale_id: string) => { sale: Sale; items: SaleItem[] } | null;
  cancelSale: (sale_id: string, reason: string, idempotencyKey?: string) => Promise<void>;

  stockTransactions: StockTransaction[];
  recordStockMovement: (input: {
    txn_type: StockTxnType;
    product_id: string;
    salesman_user_id?: string;
    quantity: number;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => Promise<void>;
  companyStockSummary: CompanyStockItem[];
  salesmanStockSummary: SalesmanStockItem[];
  stockDiscrepancies: any[];
  submitStockDiscrepancy: (input: {
    location: string;
    product_id: string;
    expected_stock: number;
    physical_count: number;
    reason: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => Promise<void>;
  reviewStockDiscrepancy: (discrepancy_id: string, action: 'APPROVE' | 'REJECT', notes?: string, idempotencyKey?: string) => Promise<void>;

  expenses: Expense[];
  submitExpense: (input: {
    category: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL';
    amount: number;
    description: string;
    receipt_link_or_file_ref?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => Promise<void>;
  approveExpense: (expense_id: string, reason?: string, idempotencyKey?: string) => Promise<void>;
  rejectExpense: (expense_id: string, reason: string, idempotencyKey?: string) => Promise<void>;

  shopVisits: ShopVisit[];
  addShopVisit: (input: {
    customer_id: string;
    visit_outcome: string;
    order_taken: boolean;
    follow_up_date: string;
    next_action: string;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => Promise<void>;

  dailyClosings: DailyClosing[];
  getTodayClosingMetrics: (salesmanId: string, customOpeningCash?: number) => {
    opening_cash: number;
    cash_collected: number;
    approved_cash_expenses: number;
    expected_cash_return: number;
  };
  refreshDashboardMetrics: () => Promise<void>;
  submitDailyClosing: (input: {
    opening_cash: number;
    physical_cash_returned: number;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => Promise<DailyClosing>;
  reviewDailyClosing: (
    closing_id: string,
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED',
    notes?: string,
    idempotencyKey?: string
  ) => Promise<void>;

  salaryIncentives: SalaryIncentive[];
  calculatePayroll: (params: {
    period_start: string;
    period_end: string;
    salesman_user_id: string;
    trial_days: number;
    trial_rate_per_kg: number;
    monthly_rate_per_100kg: number;
    base_salary: number;
    idempotency_key?: string;
  }, idempotencyKey?: string) => Promise<SalaryIncentive[]> | SalaryIncentive[];
  approveSalaryIncentive: (record_id: string, approved_amount?: number, idempotencyKey?: string) => Promise<void>;
  markSalaryIncentivePaid: (record_id: string, reference: string, idempotencyKey?: string) => Promise<void>;

  dashboardMetrics: DashboardMetrics | null;
  auditLogs: AuditLog[];
  syncError: string | null;
  storageStatus: StorageStatus;
  capabilities: ErpCapabilitiesPayload | null;
  refreshCapabilities: () => Promise<void>;
  clearSyncError: () => void;
  refreshData: () => Promise<void>;
  isRefreshing: boolean;
  isGoogleSheetsConnected: boolean;
  persistentWritesEnabled: boolean;
  appsScriptBridgeConfigured: boolean;
  connectionError: string | null;
  checkHealth: () => Promise<{ backendConnected: boolean; sheetsConnected: boolean; persistentWrites: boolean; error?: string }>;
  reconnectGoogleSheets: () => Promise<{ success: boolean; message: string }>;
  verifyGoogleSheetsTabs: () => Promise<{ connected: boolean; all_tabs_accessible: boolean; error?: string; tabs?: Record<string, any> }>;
  bootstrapStatus: OwnerBootstrapStatus | null;
  refreshBootstrapStatus: () => Promise<OwnerBootstrapStatus | null>;
  bootstrapOwnerAccount: (input: {
    username: string;
    fullName: string;
    password: string;
    bootstrapToken: string;
    email?: string;
    mobile?: string;
    notes?: string;
    idempotencyKey?: string;
  }) => Promise<{
    success: boolean;
    message: string;
    errorCode?: string;
    data?: OwnerBootstrapResponse;
  }>;
}

const StoreContext = createContext<StoreContextType | null>(null);

export const StoreProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Never persist business profile data in localStorage['ks_user']; hydrate solely from authenticated /api/auth/me.
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return !!localStorage.getItem('ks_token');
    }
    return false;
  });
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isBackendConnected, setIsBackendConnected] = useState<boolean>(false);
  const [backendUrl, setBackendUrlState] = useState<string>(getApiBaseUrl());

  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [activeCustomerIdForBilling, setActiveCustomerIdForBilling] = useState<string | null>(null);
  const [sales, setSales] = useState<Sale[]>([]);
  const [saleItems, setSaleItems] = useState<SaleItem[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [stockTransactions, setStockTransactions] = useState<StockTransaction[]>([]);
  const [companyStockSummary, setCompanyStockSummary] = useState<CompanyStockItem[]>([]);
  const [salesmanStockSummary, setSalesmanStockSummary] = useState<SalesmanStockItem[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [shopVisits, setShopVisits] = useState<ShopVisit[]>([]);
  const [dailyClosings, setDailyClosings] = useState<DailyClosing[]>([]);
  const [salaryIncentives, setSalaryIncentives] = useState<SalaryIncentive[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequest[]>([]);
  const [dashboardMetrics, setDashboardMetrics] = useState<DashboardMetrics | null>(null);
  const [stockDiscrepancies, setStockDiscrepancies] = useState<any[]>([]);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [storageStatus, setStorageStatus] = useState<StorageStatus>('UNKNOWN');
  const [capabilities, setCapabilities] = useState<ErpCapabilitiesPayload | null>(null);
  const [isGoogleSheetsConnected, setIsGoogleSheetsConnected] = useState<boolean>(false);
  const [persistentWritesEnabled, setPersistentWritesEnabled] = useState<boolean>(false);
  const [appsScriptBridgeConfigured, setAppsScriptBridgeConfigured] = useState<boolean>(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [bootstrapStatus, setBootstrapStatus] = useState<OwnerBootstrapStatus | null>(null);

  const clearSyncError = () => setSyncError(null);

  const clearBusinessState = useCallback(() => {
    setProducts([]);
    setCustomers([]);
    setSales([]);
    setSaleItems([]);
    setPayments([]);
    setStockTransactions([]);
    setCompanyStockSummary([]);
    setSalesmanStockSummary([]);
    setExpenses([]);
    setShopVisits([]);
    setDailyClosings([]);
    setSalaryIncentives([]);
    setAuditLogs([]);
    setUsers([]);
    setApprovalRequests([]);
    setDashboardMetrics(null);
    setStockDiscrepancies([]);
  }, []);

  const refreshCapabilities = useCallback(async () => {
    const token = getAuthToken();
    if (!token || token.startsWith('ks-local-jwt-')) return;
    try {
      const caps = await fetchV2Capabilities();
      setCapabilities(caps);
      setAppsScriptBridgeConfigured(Boolean(caps.apps_script_bridge_configured));
    } catch {
      // Non-fatal if user role or backend unavailable
    }
  }, []);

  const checkHealth = useCallback(async (): Promise<{
    backendConnected: boolean;
    sheetsConnected: boolean;
    persistentWrites: boolean;
    error?: string;
  }> => {
    const res = await fetchBackendHealth();
    const isOnline = res.status === 'ok' || res.backend?.status === 'CONNECTED';
    const sheetsOk = res.google_sheets_connected ?? false;
    const writesOk = res.persistent_writes_enabled ?? false;
    setIsBackendConnected(isOnline);
    setIsGoogleSheetsConnected(sheetsOk);
    setPersistentWritesEnabled(writesOk);
    if (typeof res.apps_script_bridge_configured === 'boolean') {
      setAppsScriptBridgeConfigured(res.apps_script_bridge_configured);
    }
    setConnectionError(res.last_connection_error || null);
    if (!isOnline) {
      setStorageStatus('BACKEND_UNAVAILABLE');
    } else if (!sheetsOk || !writesOk) {
      setStorageStatus('SHEETS_DISCONNECTED');
    } else {
      setStorageStatus('ONLINE');
    }
    return {
      backendConnected: isOnline,
      sheetsConnected: sheetsOk,
      persistentWrites: writesOk,
      error: res.last_connection_error || undefined,
    };
  }, []);

  const reconnectGoogleSheets = useCallback(async (): Promise<{ success: boolean; message: string }> => {
    try {
      const res = await apiRequest<{
        success: boolean;
        google_sheets_connected: boolean;
        persistent_writes_enabled: boolean;
        message: string;
        error?: string;
      }>('/api/health/reconnect', { method: 'POST', timeoutMs: 40000 });
      setIsBackendConnected(true);
      setIsGoogleSheetsConnected(res.google_sheets_connected ?? false);
      setPersistentWritesEnabled(res.persistent_writes_enabled ?? false);
      setConnectionError(res.error || null);
      if (res.success) {
        setSyncError(null);
      }
      return { success: res.success, message: res.message };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Reconnection failed to reach backend.';
      return { success: false, message: msg };
    }
  }, []);

  const verifyGoogleSheetsTabs = useCallback(async () => {
    try {
      const res = await apiRequest<{
        connected: boolean;
        all_tabs_accessible: boolean;
        error?: string;
        tabs?: Record<string, { status: string; columns?: number; error?: string }>;
      }>('/api/health/verify-tabs', { timeoutMs: 35000 });
      return res;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to reach verification endpoint';
      return { connected: false, all_tabs_accessible: false, error: msg, tabs: {} };
    }
  }, []);

  const refreshBootstrapStatus = useCallback(async (): Promise<OwnerBootstrapStatus | null> => {
    const status = await fetchOwnerBootstrapStatus();
    if (status) {
      setBootstrapStatus(status);
    }
    return status;
  }, []);

  const bootstrapOwnerAccount = useCallback(
    async (input: {
      username: string;
      fullName: string;
      password: string;
      bootstrapToken: string;
      email?: string;
      mobile?: string;
      notes?: string;
      idempotencyKey?: string;
    }): Promise<{
      success: boolean;
      message: string;
      errorCode?: string;
      data?: OwnerBootstrapResponse;
    }> => {
      try {
        const nonce = input.idempotencyKey || createSubmissionNonce('BOOTSTRAP-OWNER');
        const res = await submitOwnerBootstrap(
          {
            username: input.username,
            full_name: input.fullName,
            password: input.password,
            email: input.email,
            mobile: input.mobile,
            notes: input.notes,
          },
          input.bootstrapToken,
          nonce
        );
        await refreshBootstrapStatus();
        return {
          success: true,
          message: res.message || 'First Owner account initialized successfully.',
          data: res,
        };
      } catch (err: unknown) {
        const errorCode = err instanceof ApiHttpError ? err.errorCode : undefined;
        const message =
          err instanceof Error
            ? err.message
            : 'First Owner initialization failed. Verify server configuration and bootstrap token.';
        if (errorCode === 'OWNER_ALREADY_INITIALIZED' || (err instanceof ApiHttpError && err.status === 409)) {
          void refreshBootstrapStatus();
        }
        return {
          success: false,
          message,
          errorCode,
        };
      }
    },
    [refreshBootstrapStatus]
  );

  const updateBackendUrl = (url: string) => {
    setApiBaseUrl(url);
    setBackendUrlState(getApiBaseUrl());
    refreshData();
  };

  const logout = useCallback(() => {
    const token = getAuthToken();
    if (token && !token.startsWith('ks-local-jwt-')) {
      apiRequest('/api/auth/logout', { method: 'POST', silent: true }).catch(() => {});
    }
    setAuthToken('');
    if (typeof window !== 'undefined') {
      try {
        localStorage.removeItem('ks_user');
        localStorage.removeItem('ks_token');
        sessionStorage.removeItem('ks_current_view');
      } catch {
        // Safe fallback if storage is restricted
      }
    }
    setCurrentUser(null);
    setCapabilities(null);
    setAppsScriptBridgeConfigured(false);
    setSyncError(null);
    clearBusinessState();
  }, [clearBusinessState]);

  // Multi-tab logout synchronization
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'ks_token' && !e.newValue) {
        logout();
      }
    };
    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [logout]);

  useEffect(() => {
    const handleAuthExpired = () => {
      logout();
    };
    window.addEventListener('ks_auth_expired', handleAuthExpired);
    return () => window.removeEventListener('ks_auth_expired', handleAuthExpired);
  }, [logout]);

  const addAuditLog = (
    action: string,
    entityType: string,
    entityId: string,
    reason: string = '',
    fieldChanged: string = '',
    oldValue: string = '',
    newValue: string = ''
  ) => {
    const log: AuditLog = {
      audit_id: `AUD-${Date.now()}-${Math.random().toString(36).substring(2, 6).toUpperCase()}`,
      event_datetime: new Date().toISOString(),
      actor_user_id: currentUser ? currentUser.user_id : 'SYSTEM',
      action,
      entity_type: entityType,
      entity_id: entityId,
      field_changed: fieldChanged,
      old_value: oldValue,
      new_value: newValue,
      reason,
      approved_by_user_id: currentUser ? currentUser.user_id : '',
      related_record_id: entityId,
    };
    setAuditLogs((prev) => [log, ...prev]);

    // This is a local UI activity hint only. Authoritative audit events are
    // written by trusted backend workflows after validating each business action.
  };

  // Secure Login: Authenticates exclusively with backend FastAPI server.
  // Fails closed on invalid credentials or connection issues; never creates fake local sessions.
  const login = async (username: string, password: string): Promise<void> => {
    const cleanUsername = username.trim();
    if (!cleanUsername || !password) {
      throw new Error('Please enter both username and password.');
    }

    let res: {
      access_token: string;
      token_type?: string;
      user?: { user_id: string; username?: string; full_name?: string; role?: string };
      user_id?: string;
      username?: string;
      full_name?: string;
      role?: string;
    } | null = null;

    try {
      res = await apiRequest<{
        access_token: string;
        token_type?: string;
        user?: { user_id: string; username?: string; full_name?: string; role?: string };
        user_id?: string;
        username?: string;
        full_name?: string;
        role?: string;
      }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: cleanUsername, password }),
        timeoutMs: 20000,
        silent: true,
      });
    } catch (err: unknown) {
      if (err instanceof ApiHttpError && err.status === 404) {
        res = await apiRequest<{
          access_token: string;
          token_type?: string;
          user?: { user_id: string; username?: string; full_name?: string; role?: string };
          user_id?: string;
          username?: string;
          full_name?: string;
          role?: string;
        }>('/auth/login', {
          method: 'POST',
          body: JSON.stringify({ username: cleanUsername, password }),
          timeoutMs: 20000,
          silent: true,
        });
      } else {
        throw err;
      }
    }

    if (!res || !res.access_token) {
      throw new Error('Authentication failed: No valid access token received from server.');
    }

    const authoritativeRole = String(res.user?.role || res.role || '').trim();
    const resolvedUserId = String(res.user?.user_id || res.user_id || '').trim();
    if (!authoritativeRole || !resolvedUserId) {
      setAuthToken('');
      throw new Error('Authentication failed: Server returned incomplete account role or identity.');
    }

    setAuthToken(res.access_token);
    const resolvedUsername = String(res.user?.username || res.username || cleanUsername).trim();
    const resolvedFullName = String(res.user?.full_name || res.full_name || resolvedUsername).trim();

    const newUser: User = {
      user_id: resolvedUserId,
      full_name: resolvedFullName,
      username: resolvedUsername,
      role: authoritativeRole as User['role'],
      mobile: '',
      email: '',
      active: true,
      created_at: new Date().toISOString(),
      notes: '',
    };

    setCurrentUser(newUser);
    if (typeof window !== 'undefined') {
      try {
        localStorage.removeItem('ks_user');
      } catch {
        // Safe fallback
      }
    }
    setIsBackendConnected(true);
    setSyncError(null);
    setIsRefreshing(true);
    void Promise.all([loadInitialData(authoritativeRole), refreshCapabilities()]).finally(() =>
      setIsRefreshing(false)
    );
  };

  // Load all live records from FastAPI backend
  const loadInitialData = useCallback(async (role?: string) => {
    const token = getAuthToken();
    if (!token || token.startsWith('ks-local-jwt-')) return;

    try {
      const _activeRole = role || currentUser?.role;
      // Parallel fetch for all core tables
      const workspace = await apiRequest<{
        products: Product[] | null;
        customers: Customer[] | null;
        sales: Sale[] | null;
        payments: Payment[] | null;
        stock: { company_stock: CompanyStockItem[]; salesman_stock: SalesmanStockItem[] } | null;
        stock_transactions: StockTransaction[] | null;
        expenses: Expense[] | null;
        visits: ShopVisit[] | null;
        closings: DailyClosing[] | null;
        salary: SalaryIncentive[] | null;
        dashboard: DashboardMetrics | null;
        users: User[] | null;
        stock_discrepancies?: any[] | null;
        audit_logs?: AuditLog[] | null;
        approval_requests?: ApprovalRequest[] | null;
        _sync_errors?: Array<{ resource: string; message: string }>;
        _failed_resources?: string[];
      }>('/api/workspace', { silent: true });

      const syncErrors = workspace._sync_errors || [];
      const failedResources = new Set(
        (workspace._failed_resources || []).concat(syncErrors.map((item) => item.resource))
      );

      if (syncErrors.length > 0) {
        const details = syncErrors
          .map((item) => `${item.resource}: ${item.message}`)
          .join('; ');
        setStorageStatus('PARTIAL_SYNC');
        setSyncError(`Partial data sync. Some records could not be retrieved from storage. ${details}`);
      } else {
        setSyncError(null);
      }

      // Safeguard against replacing verified tables with empty arrays on read failures:
      if (!failedResources.has('products') && workspace.products !== null && workspace.products !== undefined) {
        const cleanProds = (workspace.products || []).map((p) => ({
          ...p,
          active: typeof p.active === 'string' ? (p.active as string).toLowerCase() === 'true' : Boolean(p.active),
          retail_pack_only: typeof p.retail_pack_only === 'string' ? (p.retail_pack_only as string).toLowerCase() === 'true' : Boolean(p.retail_pack_only),
        }));
        setProducts(cleanProds);
      }

      if (!failedResources.has('customers') && workspace.customers !== null && workspace.customers !== undefined) {
        setCustomers(workspace.customers);
      }

      if (!failedResources.has('sales') && workspace.sales !== null && workspace.sales !== undefined) {
        const salesData = (workspace.sales || []).map((sale) => ({
          ...sale,
          lines: sale.lines && sale.lines.length ? sale.lines : sale.items || [],
        }));
        setSales(salesData);
        setSaleItems(salesData.flatMap((sale) => sale.lines || []));
      }

      if (!failedResources.has('payments') && workspace.payments !== null && workspace.payments !== undefined) {
        setPayments(workspace.payments);
      }

      if (!failedResources.has('stock') && workspace.stock !== null && workspace.stock !== undefined) {
        setCompanyStockSummary(workspace.stock.company_stock || []);
        setSalesmanStockSummary(workspace.stock.salesman_stock || []);
      }

      if (!failedResources.has('stock_transactions') && workspace.stock_transactions !== null && workspace.stock_transactions !== undefined) {
        setStockTransactions(workspace.stock_transactions);
      }

      if (!failedResources.has('expenses') && workspace.expenses !== null && workspace.expenses !== undefined) {
        setExpenses(workspace.expenses);
      }

      if (!failedResources.has('visits') && workspace.visits !== null && workspace.visits !== undefined) {
        setShopVisits(workspace.visits);
      }

      if (!failedResources.has('closings') && workspace.closings !== null && workspace.closings !== undefined) {
        setDailyClosings(workspace.closings);
      }

      if (!failedResources.has('salary') && workspace.salary !== null && workspace.salary !== undefined) {
        setSalaryIncentives(workspace.salary);
      }

      if (!failedResources.has('audit_logs') && workspace.audit_logs !== null && workspace.audit_logs !== undefined) {
        setAuditLogs(workspace.audit_logs);
      }

      if (!failedResources.has('stock_discrepancies') && workspace.stock_discrepancies !== null && workspace.stock_discrepancies !== undefined) {
        setStockDiscrepancies(workspace.stock_discrepancies);
      }

      if (workspace.approval_requests && !failedResources.has('approval_requests')) {
        setApprovalRequests(workspace.approval_requests);
      }

      if (workspace.dashboard && !failedResources.has('dashboard')) {
        setDashboardMetrics(workspace.dashboard);
      }

      if (workspace.users && !failedResources.has('users') && workspace.users.length > 0) {
        setUsers(workspace.users);
      }

      setIsBackendConnected(true);
    } catch (err) {
      console.warn('Backend live sync notice:', err);
    }
  }, [currentUser?.role]);

  const refreshDashboardMetrics = useCallback(async () => {
    try {
      const freshMetrics = await apiRequest<DashboardMetrics>('/api/dashboard', { silent: true });
      if (freshMetrics) {
        setDashboardMetrics(freshMetrics);
      }
    } catch (err) {
      console.warn('Dashboard metrics refresh non-fatal warning:', err);
    }
  }, []);

  // Check existing session token on mount
  useEffect(() => {
    async function checkSession() {
      const token = getAuthToken();
      if (!token || token.startsWith('ks-local-jwt-')) {
        if (token && token.startsWith('ks-local-jwt-')) {
          setAuthToken('');
          if (typeof window !== 'undefined') {
            localStorage.removeItem('ks_user');
          }
        }
        setIsLoading(false);
        setCurrentUser(null);
        return;
      }

      try {
        let me: { user_id: string; full_name?: string; username?: string; role?: string; must_change_password?: boolean };
        try {
          me = await apiRequest<{ user_id: string; full_name?: string; username?: string; role?: string; must_change_password?: boolean }>('/api/auth/me', { silent: true });
        } catch (err: unknown) {
          if (err instanceof ApiHttpError && err.status === 404) {
            me = await apiRequest<{ user_id: string; full_name?: string; username?: string; role?: string; must_change_password?: boolean }>('/auth/me', { silent: true });
          } else {
            throw err;
          }
        }

        const authoritativeRole = String(me?.role || '').trim();
        const verifiedUserId = String(me?.user_id || '').trim();
        if (!verifiedUserId || !authoritativeRole) {
          setAuthToken('');
          if (typeof window !== 'undefined') {
            try {
              localStorage.removeItem('ks_user');
              sessionStorage.removeItem('ks_current_view');
            } catch {
              // ignore
            }
          }
          setCurrentUser(null);
          clearBusinessState();
          return;
        }

        const realUsername = String(me.username || verifiedUserId).trim();
        const verifiedUser: User = {
          user_id: verifiedUserId,
          full_name: String(me.full_name || realUsername).trim(),
          username: realUsername,
          role: authoritativeRole as User['role'],
          mobile: '',
          email: '',
          active: true,
          created_at: new Date().toISOString(),
          notes: '',
        };
        setCurrentUser(verifiedUser);
        if (typeof window !== 'undefined') {
          try {
            localStorage.removeItem('ks_user');
          } catch {
            // ignore
          }
        }
        setIsBackendConnected(true);
        setSyncError(null);
        setIsRefreshing(true);
        void Promise.all([loadInitialData(authoritativeRole), refreshCapabilities()]).finally(() =>
          setIsRefreshing(false)
        );
      } catch (e: unknown) {
        console.warn('Session verification warning:', e);
        const msg = e instanceof Error ? e.message.toLowerCase() : '';
        const status = e instanceof ApiHttpError ? e.status : undefined;
        if (
          status === 401 ||
          status === 403 ||
          msg.includes('401') ||
          msg.includes('403') ||
          msg.includes('unauthorized') ||
          msg.includes('forbidden') ||
          msg.includes('deactivated') ||
          msg.includes('inactive') ||
          msg.includes('session expired')
        ) {
          setAuthToken('');
          if (typeof window !== 'undefined') {
            try {
              localStorage.removeItem('ks_user');
              sessionStorage.removeItem('ks_current_view');
            } catch {
              // ignore
            }
          }
          setCurrentUser(null);
          clearBusinessState();
        } else {
          setIsBackendConnected(false);
          setStorageStatus('BACKEND_UNAVAILABLE');
          setSyncError('Backend API is unavailable. Governed operations and unverified reads are locked.');
        }
      } finally {
        setIsLoading(false);
      }
    }

    checkSession();
    checkHealth();
  }, [loadInitialData, checkHealth, clearBusinessState, refreshCapabilities]);

  const refreshData = async () => {
    setIsRefreshing(true);
    try {
      const health = await checkHealth();
      if (!health.backendConnected) {
        setSyncError('Network error connecting to backend API. Service may be waking up from sleep or offline.');
        return;
      }
      if (!health.sheetsConnected) {
        const userRole = String(currentUser?.role || '').toUpperCase();
        const canReconnect = ['OWNER', 'OWNER_ADMIN', 'ADMIN', 'PA', 'PERSONAL_ASSISTANT'].includes(userRole);
        if (!canReconnect) {
          setSyncError('Google Sheets storage is currently disconnected. Ask the Owner or PA to reconnect.');
          return;
        }
        const reconn = await reconnectGoogleSheets();
        if (!reconn.success) {
          setSyncError(`Backend is reached, but Google Sheets reconnect failed: ${reconn.message}`);
          return;
        }
      }
      await loadInitialData();
      setSyncError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error syncing workspace data.';
      setSyncError(msg);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Products CRUD with backend
  const addProduct = async (
    prodData: Omit<Product, 'product_id'>,
    idempotencyKey?: string
  ): Promise<Product> => {
    const payload = {
      ...prodData,
      active: Boolean(prodData.active),
      retail_pack_only: Boolean(prodData.retail_pack_only),
    };
    const saved = await apiRequest<Product>('/api/products', {
      method: 'POST',
      body: JSON.stringify(payload),
      idempotencyKey,
    });
    const cleanSaved: Product = {
      ...saved,
      active: typeof saved.active === 'string' ? (saved.active as string).toLowerCase() === 'true' : Boolean(saved.active),
      retail_pack_only: typeof saved.retail_pack_only === 'string' ? (saved.retail_pack_only as string).toLowerCase() === 'true' : Boolean(saved.retail_pack_only),
    };
    setProducts((prev) => [cleanSaved, ...prev]);
    addAuditLog('CREATE', 'Product', cleanSaved.product_id, `Created product ${cleanSaved.sku}`);
    return cleanSaved;
  };

  const updateProduct = async (
    product_id: string,
    updates: Partial<Product>,
    idempotencyKey?: string
  ) => {
    const payload = {
      ...updates,
      active: updates.active !== undefined ? Boolean(updates.active) : undefined,
      retail_pack_only: updates.retail_pack_only !== undefined ? Boolean(updates.retail_pack_only) : undefined,
    };
    const updated = await apiRequest<Product>(`/api/products/${encodeURIComponent(product_id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
      idempotencyKey,
    });
    const cleanUpdated: Product = {
      ...updated,
      active: typeof updated.active === 'string' ? (updated.active as string).toLowerCase() === 'true' : Boolean(updated.active),
      retail_pack_only: typeof updated.retail_pack_only === 'string' ? (updated.retail_pack_only as string).toLowerCase() === 'true' : Boolean(updated.retail_pack_only),
    };
    setProducts((prev) => prev.map((p) => (p.product_id === product_id ? { ...p, ...cleanUpdated } : p)));
    addAuditLog('UPDATE', 'Product', product_id, 'Updated product details');
  };

  const toggleProductActive = async (product_id: string, idempotencyKey?: string) => {
    const p = products.find((x) => x.product_id === product_id);
    if (!p) return;
    const nextState = !p.active;
    // Wait for verified server confirmation before updating local product state (no optimistic mutation)
    await updateProduct(product_id, { active: nextState }, idempotencyKey);
  };

  // Customers CRUD with backend
  const addCustomer = async (
    custData: Omit<Customer, 'customer_id' | 'created_at'>,
    idempotencyKey?: string
  ): Promise<Customer> => {
    const saved = await apiRequest<Customer>('/api/customers', {
      method: 'POST',
      body: JSON.stringify(custData),
      idempotencyKey,
    });
    setCustomers((prev) => [saved, ...prev]);
    addAuditLog('CREATE', 'Customer', saved.customer_id, `Added customer ${saved.shop_name}`);
    return saved;
  };

  const updateCustomer = async (
    customer_id: string,
    updates: Partial<Customer>,
    idempotencyKey?: string
  ) => {
    const existing = customers.find((c) => c.customer_id === customer_id);
    if (!existing) throw new Error('Customer not found. Refresh the customer list and try again.');
    const payload = { ...existing, ...updates };
    const saved = await apiRequest<Customer>(`/api/customers/${encodeURIComponent(customer_id)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
      idempotencyKey,
    });
    setCustomers((prev) => prev.map((c) => (c.customer_id === customer_id ? saved : c)));
    addAuditLog('UPDATE', 'Customer', customer_id, 'Updated customer details');
  };

  // Sales creation connected to FastAPI backend
  const createSale = async (
    input: CreateSaleInput,
    idempotencyKey?: string
  ): Promise<{ sale: Sale; paymentId?: string }> => {
    const payload = {
      ...input,
      customer_id: input.customer_id || 'CUS-WALKIN',
      customer_name_snapshot: input.customer_name_snapshot || 'Walk-in Customer',
      customer_mobile: input.customer_mobile || '',
      customer_gstin: input.customer_gstin || '',
      items: input.lines.map((l) => ({
        product_id: l.product_id,
        quantity: l.quantity,
        actual_unit_price: l.actual_unit_price,
        line_total: l.quantity * l.actual_unit_price,
      })),
      lines: input.lines,
    };

    const res = await apiRequest<{
      sale?: Sale;
      payment_id?: string;
      message?: string;
    } & Sale>('/api/sales', {
      method: 'POST',
      body: JSON.stringify(payload),
      idempotencyKey: idempotencyKey || input.idempotency_key,
    });

    const newSale: Sale = res.sale || res;
    newSale.lines = newSale.lines && newSale.lines.length ? newSale.lines : newSale.items || input.lines.map((line, index) => ({
      sale_item_id: `${newSale.sale_id}-${index}`,
      sale_id: newSale.sale_id,
      product_id: line.product_id,
      product_name_snapshot: '',
      sku_snapshot: '',
      pack_weight_g: 0,
      unit: 'PACKET',
      quantity: line.quantity,
      actual_unit_price: line.actual_unit_price,
      discount_amount: 0,
      line_total: line.quantity * line.actual_unit_price,
      qualifying_kg: 0,
      created_at: newSale.created_at,
    }));
    newSale.payment_method = input.payment_method;
    newSale.payment_reference = input.payment_reference;
    setSales((prev) => {
      const existsIdx = prev.findIndex((s) => s.sale_id === newSale.sale_id);
      if (existsIdx >= 0) {
        const next = [...prev];
        next[existsIdx] = newSale;
        return next;
      }
      return [newSale, ...prev];
    });

    setSaleItems((prev) => [...(newSale.lines || []), ...prev.filter((item) => item.sale_id !== newSale.sale_id)]);
    if (input.payment_method) {
      setPayments((prev) => [{
        payment_id: res.payment_id || newSale.bill_number,
        sale_id: newSale.sale_id,
        payment_datetime: newSale.sale_datetime,
        payment_method: input.payment_method,
        amount: newSale.bill_total,
        reference_number: input.payment_reference || newSale.bill_number,
        received_by_user_id: newSale.salesman_user_id,
        payment_status: 'RECEIVED',
        notes: '',
      }, ...prev.filter((payment) => payment.sale_id !== newSale.sale_id)]);
    }
    apiRequest<{ company_stock: CompanyStockItem[]; salesman_stock: SalesmanStockItem[] }>('/api/stock/summary')
      .then((summary) => {
        setCompanyStockSummary(summary.company_stock || []);
        setSalesmanStockSummary(summary.salesman_stock || []);
      })
      .catch(() => undefined);

    refreshDashboardMetrics().catch(() => undefined);

    addAuditLog(
      'CREATE',
      'Sale',
      newSale.sale_id,
      `Issued bill ${newSale.bill_number} for ₹${newSale.bill_total} with full payment.`
    );

    return { sale: newSale, paymentId: res.payment_id || newSale.bill_number };
  };

  const getSaleWithItems = (sale_id: string): { sale: Sale; items: SaleItem[] } | null => {
    const sale = sales.find((s) => s.sale_id === sale_id || s.bill_number === sale_id);
    if (!sale) return null;
    const items = saleItems.filter((i) => i.sale_id === sale.sale_id);
    return { sale, items: items.length > 0 ? items : (sale.lines || sale.items || []) };
  };

  const cancelSale = async (sale_id: string, reason: string, idempotencyKey?: string): Promise<void> => {
    setIsLoading(true);
    try {
      await apiRequest(`/api/sales/${encodeURIComponent(sale_id)}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
        idempotencyKey,
      });
      await refreshData();
    } finally {
      setIsLoading(false);
    }
  };

  // Stock movement connected to FastAPI backend
  const recordStockMovement = async (input: {
    txn_type: StockTxnType;
    product_id: string;
    salesman_user_id?: string;
    quantity: number;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => {
    if (input.txn_type === 'SOLD' || input.txn_type === 'COMPANY_SOLD') {
      throw new Error(
        'Manual recording of sale deductions (SOLD / COMPANY_SOLD) is restricted. Stock is automatically deducted when bills are issued in the Sales screen.'
      );
    }

    const saved = await apiRequest<StockTransaction>('/api/stock/transactions', {
      method: 'POST',
      body: JSON.stringify({
        txn_type: input.txn_type,
        product_id: input.product_id,
        salesman_user_id: input.salesman_user_id || '',
        quantity: input.quantity,
        notes: input.notes || '',
      }),
      idempotencyKey: idempotencyKey || input.idempotency_key,
    });

    setStockTransactions((prev) => [saved, ...prev]);
    // Refresh derived stock summary
    const summary = await apiRequest<{
      company_stock: CompanyStockItem[];
      salesman_stock: SalesmanStockItem[];
    }>('/api/stock/summary').catch(() => null);
    if (summary) {
      setCompanyStockSummary(summary.company_stock);
      setSalesmanStockSummary(summary.salesman_stock);
    }

    addAuditLog('CREATE', 'StockTransaction', saved.stock_txn_id, `Movement: ${input.txn_type}`);
  };

  const submitStockDiscrepancy = async (input: {
    location: string;
    product_id: string;
    expected_stock: number;
    physical_count: number;
    reason: string;
    idempotency_key?: string;
  }, idempotencyKey?: string): Promise<void> => {
    setIsLoading(true);
    try {
      await apiRequest('/api/stock/discrepancies', {
        method: 'POST',
        body: JSON.stringify(input),
        idempotencyKey: idempotencyKey || input.idempotency_key,
      });
      await refreshData();
    } finally {
      setIsLoading(false);
    }
  };

  const reviewStockDiscrepancy = async (
    discrepancy_id: string,
    action: 'APPROVE' | 'REJECT',
    notes?: string,
    idempotencyKey?: string
  ): Promise<void> => {
    setIsLoading(true);
    try {
      await apiRequest(`/api/stock/discrepancies/${encodeURIComponent(discrepancy_id)}/review`, {
        method: 'POST',
        body: JSON.stringify({ action, notes: notes || '' }),
        idempotencyKey,
      });
      await refreshData();
    } finally {
      setIsLoading(false);
    }
  };

  // Expenses connected to FastAPI backend
  const submitExpense = async (input: {
    category: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL';
    amount: number;
    description: string;
    receipt_link_or_file_ref?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => {
    const saved = await apiRequest<Expense>('/api/expenses', {
      method: 'POST',
      body: JSON.stringify(input),
      idempotencyKey: idempotencyKey || input.idempotency_key,
    });
    setExpenses((prev) => [saved, ...prev]);
    addAuditLog('CREATE', 'Expense', saved.expense_id, `Submitted ₹${input.amount} expense`);
  };

  const approveExpense = async (
    expense_id: string,
    reason: string = 'Approved by manager',
    idempotencyKey?: string
  ) => {
    const updated = await apiRequest<Expense>(`/api/expenses/${encodeURIComponent(expense_id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved: true, notes: reason }),
      idempotencyKey,
    });
    setExpenses((prev) => prev.map((e) => (e.expense_id === expense_id ? { ...e, ...updated } : e)));
    addAuditLog('APPROVE', 'Expense', expense_id, reason);
  };

  const rejectExpense = async (expense_id: string, reason: string, idempotencyKey?: string) => {
    const updated = await apiRequest<Expense>(`/api/expenses/${encodeURIComponent(expense_id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved: false, notes: reason }),
      idempotencyKey,
    });
    setExpenses((prev) => prev.map((e) => (e.expense_id === expense_id ? { ...e, ...updated } : e)));
    addAuditLog('REJECT', 'Expense', expense_id, reason);
  };

  // Shop visits connected to FastAPI backend
  const addShopVisit = async (input: {
    customer_id: string;
    visit_outcome: string;
    order_taken: boolean;
    follow_up_date: string;
    next_action: string;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => {
    const saved = await apiRequest<ShopVisit>('/api/visits', {
      method: 'POST',
      body: JSON.stringify(input),
      idempotencyKey: idempotencyKey || input.idempotency_key,
    });
    setShopVisits((prev) => [saved, ...prev]);
    addAuditLog('CREATE', 'ShopVisit', saved.visit_id, `Recorded shop visit`);
  };

  // Daily Closing metrics calculation
  const getTodayClosingMetrics = (salesmanId: string, customOpeningCash?: number) => {
    // Authoritative Indian Standard Time (Asia/Kolkata) business date
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());

    const todaySales = sales.filter(
      (s) =>
        String(s?.sale_datetime || '').slice(0, 10) === today &&
        s.payment_status === 'PAID' &&
        (s.salesman_user_id === salesmanId || s.entered_by_user_id === salesmanId)
    );

    const saleIds = new Set(todaySales.map((s) => s.sale_id));
    const cashCollected = payments
      .filter((p) => saleIds.has(p.sale_id) && p.payment_method === 'CASH')
      .reduce((sum, p) => sum + p.amount, 0);

    const approvedExpenses = expenses
      .filter(
        (e) =>
          (e.submitted_by_user_id === salesmanId || e.salesman_user_id === salesmanId) &&
          e.approval_status === 'APPROVED' &&
          e.cash_reducing_expense &&
          String(e?.expense_datetime || '').slice(0, 10) === today
      )
      .reduce((sum, e) => sum + e.amount, 0);

    const openingCash = typeof customOpeningCash === 'number' ? customOpeningCash : 500;
    const expected = Math.max(0, openingCash + cashCollected - approvedExpenses);

    return {
      opening_cash: openingCash,
      cash_collected: cashCollected,
      approved_cash_expenses: approvedExpenses,
      expected_cash_return: expected,
    };
  };

  const submitDailyClosing = async (input: {
    opening_cash: number;
    physical_cash_returned: number;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string): Promise<DailyClosing> => {
    const saved = await apiRequest<DailyClosing>('/api/closing', {
      method: 'POST',
      body: JSON.stringify(input),
      idempotencyKey: idempotencyKey || input.idempotency_key,
    });
    setDailyClosings((prev) => [saved, ...prev]);
    refreshDashboardMetrics().catch(() => undefined);
    addAuditLog('CREATE', 'DailyClosing', saved.closing_id, `Submitted daily closing`);
    return saved;
  };

  const reviewDailyClosing = async (
    closing_id: string,
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED',
    notes: string = '',
    idempotencyKey?: string
  ) => {
    const updated = await apiRequest<DailyClosing>(`/api/closing/${encodeURIComponent(closing_id)}/review`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: decision === 'CONFIRMED', notes }),
      idempotencyKey,
    });
    setDailyClosings((prev) =>
      prev.map((c) => (c.closing_id === closing_id ? { ...c, ...updated } : c))
    );
    refreshDashboardMetrics().catch(() => undefined);
    addAuditLog('REVIEW', 'DailyClosing', closing_id, `Review decision: ${decision} - ${notes}`);
  };

  // Salary & Incentive calculations with backend persistence
  const calculatePayroll = async (params: {
    period_start: string;
    period_end: string;
    salesman_user_id: string;
    trial_days: number;
    trial_rate_per_kg: number;
    monthly_rate_per_100kg: number;
    base_salary: number;
    idempotency_key?: string;
  }, idempotencyKey?: string): Promise<SalaryIncentive[]> => {
    const salesman = users.find((u) => u.user_id === params.salesman_user_id);
    const joinDate = salesman ? new Date(salesman.created_at) : new Date(params.period_start);
    const trialEndDate = new Date(joinDate.getTime() + params.trial_days * 24 * 60 * 60 * 1000);

    const relevantSales = sales.filter(
      (s) =>
        s.salesman_user_id === params.salesman_user_id &&
        s.payment_status === 'PAID' &&
        s.delivery_status === 'DELIVERED' &&
        String(s?.sale_datetime || '').slice(0, 10) >= params.period_start &&
        String(s?.sale_datetime || '').slice(0, 10) <= params.period_end
    );

    const relevantSaleIds = new Set(relevantSales.map((s) => s.sale_id));
    const items = relevantSales.flatMap((sale) => sale.lines || sale.items || saleItems.filter((i) => i.sale_id === sale.sale_id));

    let trialKg = 0;
    let postTrialKg = 0;

    for (const item of items) {
      const saleDate = new Date(item.created_at);
      if (saleDate <= trialEndDate) {
        trialKg += item.qualifying_kg;
      } else {
        postTrialKg += item.qualifying_kg;
      }
    }

    const results: SalaryIncentive[] = [];
    const periodEnd = new Date(params.period_end);

    if (periodEnd >= trialEndDate && params.base_salary > 0) {
      results.push({
        record_id: `SAL-${Date.now()}-BASE`,
        period_start: params.period_start,
        period_end: params.period_end,
        salesman_user_id: params.salesman_user_id,
        record_type: 'BASE_SALARY',
        eligible_kg: 0,
        completed_100kg_blocks: 0,
        rate: params.base_salary,
        calculated_amount: params.base_salary,
        approved_amount: params.base_salary,
        approval_status: 'PENDING',
        approved_by_user_id: '',
        paid_datetime: '',
        payment_reference: '',
        notes: `Base salary for ${params.period_start.slice(0, 7)}`,
      });
    }

    if (trialKg > 0) {
      const trialAmount = Math.round(trialKg * params.trial_rate_per_kg * 100) / 100;
      results.push({
        record_id: `SAL-${Date.now()}-TRIAL`,
        period_start: params.period_start,
        period_end: params.period_end,
        salesman_user_id: params.salesman_user_id,
        record_type: 'TRIAL_INCENTIVE',
        eligible_kg: Math.round(trialKg * 100) / 100,
        completed_100kg_blocks: 0,
        rate: params.trial_rate_per_kg,
        calculated_amount: trialAmount,
        approved_amount: trialAmount,
        approval_status: 'PENDING',
        approved_by_user_id: '',
        paid_datetime: '',
        payment_reference: '',
        notes: `${trialKg.toFixed(1)} kg during trial period @ ₹${params.trial_rate_per_kg}/kg`,
      });
    }

    const completedBlocks = Math.floor(postTrialKg / 100);
    if (completedBlocks > 0) {
      const incentiveAmt = completedBlocks * params.monthly_rate_per_100kg;
      results.push({
        record_id: `SAL-${Date.now()}-VOL`,
        period_start: params.period_start,
        period_end: params.period_end,
        salesman_user_id: params.salesman_user_id,
        record_type: 'MONTHLY_INCENTIVE',
        eligible_kg: Math.round(postTrialKg * 100) / 100,
        completed_100kg_blocks: completedBlocks,
        rate: params.monthly_rate_per_100kg,
        calculated_amount: incentiveAmt,
        approved_amount: incentiveAmt,
        approval_status: 'PENDING',
        approved_by_user_id: '',
        paid_datetime: '',
        payment_reference: '',
        notes: `${completedBlocks} completed 100kg blocks @ ₹${params.monthly_rate_per_100kg}/block (${postTrialKg.toFixed(1)} kg eligible)`,
      });
    }

    if (results.length === 0) {
      return [];
    }

    // Server-confirmed persistence (Finding A):
    // Submit proposed calculations to backend FIRST and only update state with server-confirmed persisted records
    const payload = results.map((r) => ({
      period_start: r.period_start,
      period_end: r.period_end,
      salesman_user_id: r.salesman_user_id,
      record_type: r.record_type,
      eligible_kg: r.eligible_kg,
      completed_100kg_blocks: r.completed_100kg_blocks,
      rate: r.rate,
      calculated_amount: r.calculated_amount,
      approved_amount: r.approved_amount,
      notes: r.notes,
    }));

    const persisted = await apiRequest<SalaryIncentive[]>('/api/salary', {
      method: 'POST',
      body: JSON.stringify(payload),
      idempotencyKey: idempotencyKey || params.idempotency_key,
    });

    if (!persisted || persisted.length === 0) {
      throw new Error('Salary records were not saved by the server.');
    }

    setSalaryIncentives((prev) => {
      const existingIds = new Set(prev.map((p) => p.record_id));
      const fresh = persisted.filter((p) => !existingIds.has(p.record_id));
      return [...fresh, ...prev];
    });

    refreshDashboardMetrics().catch(() => undefined);
    return persisted;
  };

  const approveSalaryIncentive = async (
    record_id: string,
    approved_amount?: number,
    idempotencyKey?: string
  ) => {
    const updated = await apiRequest<SalaryIncentive>(`/api/salary/${encodeURIComponent(record_id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved_amount, notes: 'Approved in management portal' }),
      idempotencyKey,
    });
    setSalaryIncentives((prev) =>
      prev.map((r) => (r.record_id === record_id ? { ...r, ...updated, approval_status: 'APPROVED' } : r))
    );
    refreshDashboardMetrics().catch(() => undefined);
    addAuditLog('APPROVE', 'SalaryIncentive', record_id, 'Approved salary/incentive payment');
  };

  const markSalaryIncentivePaid = async (
    record_id: string,
    reference: string,
    idempotencyKey?: string
  ) => {
    const updated = await apiRequest<SalaryIncentive>(`/api/salary/${encodeURIComponent(record_id)}/pay`, {
      method: 'POST',
      body: JSON.stringify({ payment_reference: reference }),
      idempotencyKey,
    });
    setSalaryIncentives((prev) =>
      prev.map((r) => (r.record_id === record_id ? { ...r, ...updated } : r))
    );
    refreshDashboardMetrics().catch(() => undefined);
    addAuditLog('PAY', 'SalaryIncentive', record_id, `Marked paid with ref: ${reference}`);
  };

  const loadApprovalRequests = useCallback(async (): Promise<void> => {
    try {
      const list = await apiRequest<ApprovalRequest[]>('/api/approvals/requests');
      if (Array.isArray(list)) {
        setApprovalRequests(list);
      }
    } catch (err) {
      console.warn('Failed to load approval requests:', err);
      throw err;
    }
  }, []);

  const createUser = async (userData: {
    user_id?: string;
    full_name: string;
    username: string;
    password: string;
    role: string;
    mobile?: string;
    email?: string;
    active?: boolean;
    notes?: string;
    idempotency_key?: string;
  }, idempotencyKey?: string) => {
    const res = await apiRequest<any>('/api/users', {
      method: 'POST',
      body: JSON.stringify(userData),
      idempotencyKey: idempotencyKey || userData.idempotency_key,
    });
    if (res.user_id) {
      // Direct creation (Owner)
      setUsers((prev) => [...prev, res as User]);
      refreshDashboardMetrics().catch(() => undefined);
      addAuditLog('CREATE', 'User', res.user_id, `Created team user ${res.username}`);
    } else if (res.pending_approval) {
      // PA request
      await loadApprovalRequests();
    }
    return res;
  };

  const updateUser = async (userId: string, data: Partial<User>, idempotencyKey?: string) => {
    const res = await apiRequest<{ ok?: boolean; pending_approval?: boolean; message?: string; user?: User }>(`/api/users/${encodeURIComponent(userId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
      idempotencyKey,
    });
    if (res.user) {
      setUsers((prev) => prev.map((u) => (u.user_id === userId ? { ...u, ...res.user } : u)));
      addAuditLog('UPDATE', 'User', userId, `Updated user details for ${userId}`);
    }
    if (res.pending_approval) {
      await loadApprovalRequests();
    }
    return res;
  };

  const setUserStatus = async (
    userId: string,
    active: boolean,
    reason: string = '',
    idempotencyKey?: string
  ) => {
    const res = await apiRequest<{ ok?: boolean; pending_approval?: boolean; message?: string; active?: boolean }>(`/api/users/${encodeURIComponent(userId)}/status`, {
      method: 'POST',
      body: JSON.stringify({ active, reason }),
      idempotencyKey,
    });
    if (typeof res.active === 'boolean') {
      setUsers((prev) => prev.map((u) => (u.user_id === userId ? { ...u, active: res.active! } : u)));
      addAuditLog('STATUS_CHANGE', 'User', userId, `Changed status to ${active ? 'Active' : 'Inactive'}`);
    }
    if (res.pending_approval) {
      await loadApprovalRequests();
    }
    return res;
  };

  const resetUserPassword = async (
    userId: string,
    newPassword?: string,
    idempotencyKey?: string
  ) => {
    const res = await apiRequest<{ ok?: boolean; pending_approval?: boolean; message?: string }>(`/api/users/${encodeURIComponent(userId)}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword || '' }),
      idempotencyKey,
    });
    if (res.pending_approval) {
      await loadApprovalRequests();
    } else {
      addAuditLog('RESET_PASSWORD', 'User', userId, `Owner reset password and revoked sessions`);
    }
    return res;
  };

  const decideApprovalRequest = async (
    requestId: string,
    decision: 'APPROVED' | 'REJECTED',
    notes: string = '',
    initialPassword?: string,
    idempotencyKey?: string
  ): Promise<ApprovalRequest> => {
    const updated = await apiRequest<ApprovalRequest>(`/api/approvals/requests/${encodeURIComponent(requestId)}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes, initial_password: initialPassword }),
      idempotencyKey,
    });
    setApprovalRequests((prev) => prev.map((r) => (r.request_id === requestId ? updated : r)));
    // Synchronize users if approved
    try {
      const freshUsers = await apiRequest<User[]>('/api/users');
      if (Array.isArray(freshUsers)) setUsers(freshUsers);
    } catch {}
    refreshDashboardMetrics().catch(() => undefined);
    return updated;
  };

  const retryApprovalRequest = async (requestId: string, idempotencyKey?: string) => {
    const updated = await apiRequest<ApprovalRequest>(`/api/approvals/requests/${encodeURIComponent(requestId)}/retry`, {
      method: 'POST',
      idempotencyKey,
    });
    setApprovalRequests((prev) => prev.map((r) => (r.request_id === requestId ? updated : r)));
    try {
      const freshUsers = await apiRequest<User[]>('/api/users');
      if (Array.isArray(freshUsers)) setUsers(freshUsers);
    } catch {}
  };

  const cancelApprovalRequest = async (requestId: string, idempotencyKey?: string) => {
    const updated = await apiRequest<ApprovalRequest>(`/api/approvals/requests/${encodeURIComponent(requestId)}/cancel`, {
      method: 'POST',
      idempotencyKey,
    });
    setApprovalRequests((prev) => prev.map((r) => (r.request_id === requestId ? updated : r)));
  };

  return (
    <StoreContext.Provider
      value={{
        currentUser,
        isLoading,
        isBackendConnected,
        backendUrl,
        updateBackendUrl,
        login,
        logout,
        users,
        createUser,
        updateUser,
        setUserStatus,
        resetUserPassword,
        approvalRequests,
        loadApprovalRequests,
        decideApprovalRequest,
        retryApprovalRequest,
        cancelApprovalRequest,
        products,
        addProduct,
        updateProduct,
        toggleProductActive,
        customers,
        addCustomer,
        updateCustomer,
        activeCustomerIdForBilling,
        setActiveCustomerIdForBilling,
        sales,
        payments,
        createSale,
        getSaleWithItems,
        cancelSale,
        stockTransactions,
        recordStockMovement,
        companyStockSummary,
        salesmanStockSummary,
        stockDiscrepancies,
        submitStockDiscrepancy,
        reviewStockDiscrepancy,
        expenses,
        submitExpense,
        approveExpense,
        rejectExpense,
        shopVisits,
        addShopVisit,
        dailyClosings,
        getTodayClosingMetrics,
        submitDailyClosing,
        reviewDailyClosing,
        salaryIncentives,
        calculatePayroll,
        approveSalaryIncentive,
        markSalaryIncentivePaid,
        dashboardMetrics,
        refreshDashboardMetrics,
        auditLogs,
        syncError,
        storageStatus,
        capabilities,
        refreshCapabilities,
        clearSyncError,
        refreshData,
        isRefreshing,
        isGoogleSheetsConnected,
        persistentWritesEnabled,
        appsScriptBridgeConfigured,
        connectionError,
        checkHealth,
        reconnectGoogleSheets,
        verifyGoogleSheetsTabs,
        bootstrapStatus,
        refreshBootstrapStatus,
        bootstrapOwnerAccount,
      }}
    >
      {children}
    </StoreContext.Provider>
  );
};

export const useStore = () => {
  const context = useContext(StoreContext);
  if (!context) throw new Error('useStore must be used within StoreProvider');
  return context;
};
