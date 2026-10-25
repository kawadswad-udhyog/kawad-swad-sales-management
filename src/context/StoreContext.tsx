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
} from '../types';
import {
  apiRequest,
  getAuthToken,
  setAuthToken,
  getApiBaseUrl,
  setApiBaseUrl,
  fetchBackendHealth,
} from '../services/api';
import {
  INITIAL_USERS,
  INITIAL_PRODUCTS,
  INITIAL_CUSTOMERS,
  INITIAL_SALES,
  INITIAL_PAYMENTS,
  INITIAL_STOCK_TRANSACTIONS,
  INITIAL_EXPENSES,
  INITIAL_SHOP_VISITS,
  INITIAL_DAILY_CLOSINGS,
  INITIAL_SALARY_INCENTIVES,
  INITIAL_AUDIT_LOGS,
  INITIAL_DASHBOARD_METRICS,
} from '../data/initialData';

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
  }) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string }>;
  updateUser: (user_id: string, updates: Partial<User>) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string; user?: User }>;
  setUserStatus: (user_id: string, active: boolean, reason?: string) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string }>;
  resetUserPassword: (user_id: string, newPassword?: string) => Promise<{ ok?: boolean; pending_approval?: boolean; message?: string }>;

  approvalRequests: ApprovalRequest[];
  loadApprovalRequests: () => Promise<void>;
  decideApprovalRequest: (requestId: string, decision: 'APPROVED' | 'REJECTED', notes?: string, initialPassword?: string) => Promise<ApprovalRequest>;
  retryApprovalRequest: (requestId: string) => Promise<void>;
  cancelApprovalRequest: (requestId: string) => Promise<void>;

  products: Product[];
  addProduct: (product: Omit<Product, 'product_id'>) => Promise<Product>;
  updateProduct: (product_id: string, updates: Partial<Product>) => Promise<void>;
  toggleProductActive: (product_id: string) => Promise<void>;

  customers: Customer[];
  addCustomer: (customer: Omit<Customer, 'customer_id' | 'created_at'>) => Promise<Customer>;
  updateCustomer: (customer_id: string, updates: Partial<Customer>) => Promise<void>;
  activeCustomerIdForBilling: string | null;
  setActiveCustomerIdForBilling: (id: string | null) => void;

  sales: Sale[];
  payments: Payment[];
  createSale: (input: CreateSaleInput) => Promise<{ sale: Sale; paymentId?: string }>;
  getSaleWithItems: (sale_id: string) => { sale: Sale; items: SaleItem[] } | null;
  cancelSale: (sale_id: string, reason: string) => Promise<void>;

  stockTransactions: StockTransaction[];
  recordStockMovement: (input: {
    txn_type: StockTxnType;
    product_id: string;
    salesman_user_id?: string;
    quantity: number;
    notes?: string;
  }) => Promise<void>;
  companyStockSummary: CompanyStockItem[];
  salesmanStockSummary: SalesmanStockItem[];
  stockDiscrepancies: any[];
  submitStockDiscrepancy: (input: {
    location: string;
    product_id: string;
    expected_stock: number;
    physical_count: number;
    reason: string;
  }) => Promise<void>;
  reviewStockDiscrepancy: (discrepancy_id: string, action: 'APPROVE' | 'REJECT', notes?: string) => Promise<void>;

  expenses: Expense[];
  submitExpense: (input: {
    category: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL';
    amount: number;
    description: string;
    receipt_link_or_file_ref?: string;
  }) => Promise<void>;
  approveExpense: (expense_id: string, reason?: string) => Promise<void>;
  rejectExpense: (expense_id: string, reason: string) => Promise<void>;

  shopVisits: ShopVisit[];
  addShopVisit: (input: {
    customer_id: string;
    visit_outcome: string;
    order_taken: boolean;
    follow_up_date: string;
    next_action: string;
    notes?: string;
  }) => Promise<void>;

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
  }) => Promise<DailyClosing>;
  reviewDailyClosing: (
    closing_id: string,
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED',
    notes?: string
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
  }) => Promise<SalaryIncentive[]> | SalaryIncentive[];
  approveSalaryIncentive: (record_id: string, approved_amount?: number) => Promise<void>;
  markSalaryIncentivePaid: (record_id: string, reference: string) => Promise<void>;

  dashboardMetrics: DashboardMetrics | null;
  auditLogs: AuditLog[];
  syncError: string | null;
  clearSyncError: () => void;
  refreshData: () => Promise<void>;
  isRefreshing: boolean;
  isGoogleSheetsConnected: boolean;
  persistentWritesEnabled: boolean;
  connectionError: string | null;
  checkHealth: () => Promise<{ backendConnected: boolean; sheetsConnected: boolean; persistentWrites: boolean; error?: string }>;
  reconnectGoogleSheets: () => Promise<{ success: boolean; message: string }>;
  verifyGoogleSheetsTabs: () => Promise<{ connected: boolean; all_tabs_accessible: boolean; error?: string; tabs?: Record<string, any> }>;
  bootstrapOwnerAccount: (username: string, password: string, fullName?: string) => Promise<{ success: boolean; message: string }>;
}

const StoreContext = createContext<StoreContextType | null>(null);

export const StoreProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentUser, setCurrentUser] = useState<User | null>(() => {
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem('ks_user');
        if (saved) return JSON.parse(saved);
      } catch {
        // ignore
      }
    }
    return null;
  });
  const [isLoading, setIsLoading] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return !localStorage.getItem('ks_user') && !!localStorage.getItem('ks_token');
    }
    return false;
  });
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isBackendConnected, setIsBackendConnected] = useState<boolean>(false);
  const [backendUrl, setBackendUrlState] = useState<string>(getApiBaseUrl());

  const [products, setProducts] = useState<Product[]>(INITIAL_PRODUCTS);
  const [customers, setCustomers] = useState<Customer[]>(INITIAL_CUSTOMERS);
  const [activeCustomerIdForBilling, setActiveCustomerIdForBilling] = useState<string | null>(null);
  const [sales, setSales] = useState<Sale[]>(INITIAL_SALES);
  const [saleItems, setSaleItems] = useState<SaleItem[]>(INITIAL_SALES.flatMap((s) => s.lines || []));
  const [payments, setPayments] = useState<Payment[]>(INITIAL_PAYMENTS);
  const [stockTransactions, setStockTransactions] = useState<StockTransaction[]>(INITIAL_STOCK_TRANSACTIONS);
  const [companyStockSummary, setCompanyStockSummary] = useState<CompanyStockItem[]>([
    { product_id: 'PRD-MOONG-200', sku: 'MOONG-200G', product_name: 'Moong Special Papad (200g)', pack_weight_g: 200, company_quantity: 400 },
    { product_id: 'PRD-CHANA-250', sku: 'CHANA-250G', product_name: 'Chana Masala Papad (250g)', pack_weight_g: 250, company_quantity: 350 },
    { product_id: 'PRD-URAD-200', sku: 'URAD-200G', product_name: 'Urad Punjabi Tadka Papad (200g)', pack_weight_g: 200, company_quantity: 250 },
  ]);
  const [salesmanStockSummary, setSalesmanStockSummary] = useState<SalesmanStockItem[]>([
    { salesman_user_id: 'USR-SALES-01', salesman_name: 'Ramesh Patidar', product_id: 'PRD-MOONG-200', sku: 'MOONG-200G', product_name: 'Moong Special Papad (200g)', quantity: 80 },
    { salesman_user_id: 'USR-SALES-01', salesman_name: 'Ramesh Patidar', product_id: 'PRD-CHANA-250', sku: 'CHANA-250G', product_name: 'Chana Masala Papad (250g)', quantity: 60 },
  ]);
  const [expenses, setExpenses] = useState<Expense[]>(INITIAL_EXPENSES);
  const [shopVisits, setShopVisits] = useState<ShopVisit[]>(INITIAL_SHOP_VISITS);
  const [dailyClosings, setDailyClosings] = useState<DailyClosing[]>(INITIAL_DAILY_CLOSINGS);
  const [salaryIncentives, setSalaryIncentives] = useState<SalaryIncentive[]>(INITIAL_SALARY_INCENTIVES);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>(INITIAL_AUDIT_LOGS);
  const [users, setUsers] = useState<User[]>(INITIAL_USERS);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequest[]>([]);
  const [dashboardMetrics, setDashboardMetrics] = useState<DashboardMetrics | null>(INITIAL_DASHBOARD_METRICS);
  const [stockDiscrepancies, setStockDiscrepancies] = useState<any[]>([]);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [isGoogleSheetsConnected, setIsGoogleSheetsConnected] = useState<boolean>(false);
  const [persistentWritesEnabled, setPersistentWritesEnabled] = useState<boolean>(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const clearSyncError = () => setSyncError(null);

  const checkHealth = useCallback(async (): Promise<{
    backendConnected: boolean;
    sheetsConnected: boolean;
    persistentWrites: boolean;
    error?: string;
  }> => {
    const res = await fetchBackendHealth();
    const isOnline = res.status === 'ok' || res.backend?.status === 'CONNECTED';
    setIsBackendConnected(isOnline);
    setIsGoogleSheetsConnected(res.google_sheets_connected ?? false);
    setPersistentWritesEnabled(res.persistent_writes_enabled ?? false);
    setConnectionError(res.last_connection_error || null);
    return {
      backendConnected: isOnline,
      sheetsConnected: res.google_sheets_connected ?? false,
      persistentWrites: res.persistent_writes_enabled ?? false,
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

  const bootstrapOwnerAccount = useCallback(async (username: string, password: string, fullName?: string) => {
    try {
      const res = await apiRequest<{
        success: boolean;
        message: string;
        user_id?: string;
        username?: string;
      }>('/api/auth/bootstrap-owner', {
        method: 'POST',
        body: JSON.stringify({ username, password, full_name: fullName }),
        timeoutMs: 25000,
      });
      return { success: res.success ?? true, message: res.message || 'Owner account created successfully in Google Sheets!' };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to bootstrap owner account.';
      return { success: false, message: msg };
    }
  }, []);

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
      localStorage.removeItem('ks_user');
      localStorage.removeItem('ks_token');
    }
    setCurrentUser(null);
  }, []);

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

    // Asynchronously persist to backend audit router and Google Sheets
    apiRequest<AuditLog>('/api/audit-logs', {
      method: 'POST',
      body: JSON.stringify({
        action,
        entity_type: entityType,
        entity_id: entityId,
        field_changed: fieldChanged,
        old_value: oldValue,
        new_value: newValue,
        reason,
        related_record_id: entityId,
      }),
    }).catch((err) => {
      console.warn('Backend audit log sync warning:', err);
    });
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
      user?: { user_id: string; full_name?: string; role?: string };
      user_id?: string;
      full_name?: string;
      role?: string;
    } | null = null;

    try {
      res = await apiRequest<{
        access_token: string;
        token_type?: string;
        user?: { user_id: string; full_name?: string; role?: string };
        user_id?: string;
        full_name?: string;
        role?: string;
      }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: cleanUsername, password }),
        timeoutMs: 20000,
        silent: true,
      });
    } catch (err: unknown) {
      if (err instanceof Error && err.message.includes('404')) {
        try {
          res = await apiRequest<{
            access_token: string;
            token_type?: string;
            user?: { user_id: string; full_name?: string; role?: string };
            user_id?: string;
            full_name?: string;
            role?: string;
          }>('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username: cleanUsername, password }),
            timeoutMs: 20000,
            silent: true,
          });
        } catch (fallbackErr) {
          throw fallbackErr;
        }
      } else {
        throw err;
      }
    }

    if (!res || !res.access_token) {
      throw new Error('Authentication failed: No valid access token received from server.');
    }

    setAuthToken(res.access_token);
    const userPayload = res.user || {
      user_id: res.user_id || cleanUsername,
      full_name: res.full_name || cleanUsername,
      role: res.role || 'SALESMAN',
    };

    const newUser: User = {
      user_id: userPayload.user_id || cleanUsername,
      full_name: userPayload.full_name || cleanUsername,
      username: cleanUsername,
      role: (userPayload.role || 'SALESMAN') as User['role'],
      mobile: '',
      email: '',
      active: true,
      created_at: new Date().toISOString(),
      notes: '',
    };

    setCurrentUser(newUser);
    if (typeof window !== 'undefined') {
      localStorage.setItem('ks_user', JSON.stringify(newUser));
    }
    setIsBackendConnected(true);
    setSyncError('Signed in. Loading your latest workspace data…');
    setIsRefreshing(true);
    void loadInitialData(userPayload.role).finally(() => setIsRefreshing(false));
  };

  // Load all live records from FastAPI backend
  const loadInitialData = useCallback(async (role?: string) => {
    const token = getAuthToken();
    if (!token || token.startsWith('ks-local-jwt-')) return;

    try {
      const activeRole = role || currentUser?.role;
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
        let cachedUser: User | null = null;
        if (typeof window !== 'undefined') {
          try {
            const raw = localStorage.getItem('ks_user');
            if (raw) cachedUser = JSON.parse(raw);
          } catch {
            // ignore
          }
        }

        let me: { user_id: string; full_name?: string; username?: string; role?: string; must_change_password?: boolean };
        try {
          me = await apiRequest<{ user_id: string; full_name?: string; username?: string; role?: string; must_change_password?: boolean }>('/api/auth/me', { silent: true });
        } catch (err: unknown) {
          if (err instanceof Error && err.message.includes('404')) {
            me = await apiRequest<{ user_id: string; full_name?: string; username?: string; role?: string; must_change_password?: boolean }>('/auth/me', { silent: true });
          } else {
            throw err;
          }
        }

        const realUsername = me.username || cachedUser?.username || me.user_id;
        const verifiedUser: User = {
          user_id: me.user_id,
          full_name: me.full_name || cachedUser?.full_name || realUsername,
          username: realUsername,
          role: (me.role || cachedUser?.role || 'SALESMAN') as User['role'],
          mobile: cachedUser?.mobile || '',
          email: cachedUser?.email || '',
          active: true,
          created_at: cachedUser?.created_at || new Date().toISOString(),
          notes: cachedUser?.notes || '',
        };
        setCurrentUser(verifiedUser);
        if (typeof window !== 'undefined') {
          localStorage.setItem('ks_user', JSON.stringify(verifiedUser));
        }
        setIsBackendConnected(true);
        // Restore the cached session immediately. Fetch live records after
        // rendering so browser refresh does not wait on all Sheets requests.
        setSyncError('Session restored. Loading your latest workspace data…');
        setIsRefreshing(true);
        void loadInitialData(me.role).finally(() => setIsRefreshing(false));
      } catch (e: unknown) {
        console.warn('Session verification warning:', e);
        const msg = e instanceof Error ? e.message.toLowerCase() : '';
        if (msg.includes('401') || msg.includes('unauthorized') || msg.includes('session expired')) {
          setAuthToken('');
          if (typeof window !== 'undefined') {
            localStorage.removeItem('ks_user');
          }
          setCurrentUser(null);
        } else {
          // If network / Render waking up, preserve user session so page refresh doesn't log them out!
          setIsBackendConnected(false);
          setSyncError('Connecting to backend API... (Backend may be spinning up).');
          loadInitialData().catch(() => {});
        }
      } finally {
        setIsLoading(false);
      }
    }

    checkSession();
    checkHealth();
  }, [loadInitialData, checkHealth]);

  const refreshData = async () => {
    setIsRefreshing(true);
    try {
      const health = await checkHealth();
      if (!health.backendConnected) {
        setSyncError('Network error connecting to backend API. Service may be waking up from sleep or offline.');
        return;
      }
      if (!health.sheetsConnected) {
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
  const addProduct = async (prodData: Omit<Product, 'product_id'>): Promise<Product> => {
    const payload = {
      ...prodData,
      active: Boolean(prodData.active),
      retail_pack_only: Boolean(prodData.retail_pack_only),
    };
    const saved = await apiRequest<Product>('/api/products', {
      method: 'POST',
      body: JSON.stringify(payload),
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

  const updateProduct = async (product_id: string, updates: Partial<Product>) => {
    const payload = {
      ...updates,
      active: updates.active !== undefined ? Boolean(updates.active) : undefined,
      retail_pack_only: updates.retail_pack_only !== undefined ? Boolean(updates.retail_pack_only) : undefined,
    };
    const updated = await apiRequest<Product>(`/api/products/${encodeURIComponent(product_id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    const cleanUpdated: Product = {
      ...updated,
      active: typeof updated.active === 'string' ? (updated.active as string).toLowerCase() === 'true' : Boolean(updated.active),
      retail_pack_only: typeof updated.retail_pack_only === 'string' ? (updated.retail_pack_only as string).toLowerCase() === 'true' : Boolean(updated.retail_pack_only),
    };
    setProducts((prev) => prev.map((p) => (p.product_id === product_id ? { ...p, ...cleanUpdated } : p)));
    addAuditLog('UPDATE', 'Product', product_id, 'Updated product details');
  };

  const toggleProductActive = async (product_id: string) => {
    const p = products.find((x) => x.product_id === product_id);
    if (!p) return;
    const nextState = !p.active;
    // Optimistic toggle in local state for instant UI response
    setProducts((prev) =>
      prev.map((item) => (item.product_id === product_id ? { ...item, active: nextState } : item))
    );
    try {
      await updateProduct(product_id, { active: nextState });
    } catch (err) {
      // Revert if API fails
      setProducts((prev) =>
        prev.map((item) => (item.product_id === product_id ? { ...item, active: p.active } : item))
      );
      throw err;
    }
  };

  // Customers CRUD with backend
  const addCustomer = async (custData: Omit<Customer, 'customer_id' | 'created_at'>): Promise<Customer> => {
    const saved = await apiRequest<Customer>('/api/customers', {
      method: 'POST',
      body: JSON.stringify(custData),
    });
    setCustomers((prev) => [saved, ...prev]);
    addAuditLog('CREATE', 'Customer', saved.customer_id, `Added customer ${saved.shop_name}`);
    return saved;
  };

  const updateCustomer = async (customer_id: string, updates: Partial<Customer>) => {
    const existing = customers.find((c) => c.customer_id === customer_id);
    if (!existing) throw new Error('Customer not found. Refresh the customer list and try again.');
    const payload = { ...existing, ...updates };
    const saved = await apiRequest<Customer>(`/api/customers/${encodeURIComponent(customer_id)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    setCustomers((prev) => prev.map((c) => (c.customer_id === customer_id ? saved : c)));
    addAuditLog('UPDATE', 'Customer', customer_id, 'Updated customer details');
  };

  // Sales creation connected to FastAPI backend
  const createSale = async (input: CreateSaleInput): Promise<{ sale: Sale; paymentId?: string }> => {
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

  const cancelSale = async (sale_id: string, reason: string): Promise<void> => {
    setIsLoading(true);
    try {
      await apiRequest(`/api/sales/${encodeURIComponent(sale_id)}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
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
  }) => {
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
  }): Promise<void> => {
    setIsLoading(true);
    try {
      await apiRequest('/api/stock/discrepancies', {
        method: 'POST',
        body: JSON.stringify(input),
      });
      await refreshData();
    } finally {
      setIsLoading(false);
    }
  };

  const reviewStockDiscrepancy = async (
    discrepancy_id: string,
    action: 'APPROVE' | 'REJECT',
    notes?: string
  ): Promise<void> => {
    setIsLoading(true);
    try {
      await apiRequest(`/api/stock/discrepancies/${encodeURIComponent(discrepancy_id)}/review`, {
        method: 'POST',
        body: JSON.stringify({ action, notes: notes || '' }),
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
  }) => {
    const saved = await apiRequest<Expense>('/api/expenses', {
      method: 'POST',
      body: JSON.stringify(input),
    });
    setExpenses((prev) => [saved, ...prev]);
    addAuditLog('CREATE', 'Expense', saved.expense_id, `Submitted ₹${input.amount} expense`);
  };

  const approveExpense = async (expense_id: string, reason: string = 'Approved by manager') => {
    const updated = await apiRequest<Expense>(`/api/expenses/${encodeURIComponent(expense_id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved: true, notes: reason }),
    });
    setExpenses((prev) => prev.map((e) => (e.expense_id === expense_id ? { ...e, ...updated } : e)));
    addAuditLog('APPROVE', 'Expense', expense_id, reason);
  };

  const rejectExpense = async (expense_id: string, reason: string) => {
    const updated = await apiRequest<Expense>(`/api/expenses/${encodeURIComponent(expense_id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved: false, notes: reason }),
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
  }) => {
    const saved = await apiRequest<ShopVisit>('/api/visits', {
      method: 'POST',
      body: JSON.stringify(input),
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
  }): Promise<DailyClosing> => {
    const saved = await apiRequest<DailyClosing>('/api/closing', {
      method: 'POST',
      body: JSON.stringify(input),
    });
    setDailyClosings((prev) => [saved, ...prev]);
    refreshDashboardMetrics().catch(() => undefined);
    addAuditLog('CREATE', 'DailyClosing', saved.closing_id, `Submitted daily closing`);
    return saved;
  };

  const reviewDailyClosing = async (
    closing_id: string,
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED',
    notes: string = ''
  ) => {
    const updated = await apiRequest<DailyClosing>(`/api/closing/${encodeURIComponent(closing_id)}/review`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: decision === 'CONFIRMED', notes }),
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
  }): Promise<SalaryIncentive[]> => {
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

  const approveSalaryIncentive = async (record_id: string, approved_amount?: number) => {
    const updated = await apiRequest<SalaryIncentive>(`/api/salary/${encodeURIComponent(record_id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved_amount, notes: 'Approved in management portal' }),
    });
    setSalaryIncentives((prev) =>
      prev.map((r) => (r.record_id === record_id ? { ...r, ...updated, approval_status: 'APPROVED' } : r))
    );
    refreshDashboardMetrics().catch(() => undefined);
    addAuditLog('APPROVE', 'SalaryIncentive', record_id, 'Approved salary/incentive payment');
  };

  const markSalaryIncentivePaid = async (record_id: string, reference: string) => {
    const updated = await apiRequest<SalaryIncentive>(`/api/salary/${encodeURIComponent(record_id)}/pay`, {
      method: 'POST',
      body: JSON.stringify({ payment_reference: reference }),
    });
    setSalaryIncentives((prev) =>
      prev.map((r) => (r.record_id === record_id ? { ...r, ...updated } : r))
    );
    refreshDashboardMetrics().catch(() => undefined);
    addAuditLog('PAY', 'SalaryIncentive', record_id, `Marked paid with ref: ${reference}`);
  };

  const loadApprovalRequests = useCallback(async () => {
    try {
      const list = await apiRequest<ApprovalRequest[]>('/api/approvals/requests');
      if (Array.isArray(list)) {
        setApprovalRequests(list);
      }
    } catch (err) {
      console.warn('Failed to load approval requests:', err);
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
  }) => {
    const res = await apiRequest<any>('/api/users', {
      method: 'POST',
      body: JSON.stringify(userData),
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

  const updateUser = async (userId: string, data: Partial<User>) => {
    const res = await apiRequest<{ ok?: boolean; pending_approval?: boolean; message?: string; user?: User }>(`/api/users/${encodeURIComponent(userId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
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

  const setUserStatus = async (userId: string, active: boolean, reason: string = '') => {
    const res = await apiRequest<{ ok?: boolean; pending_approval?: boolean; message?: string; active?: boolean }>(`/api/users/${encodeURIComponent(userId)}/status`, {
      method: 'POST',
      body: JSON.stringify({ active, reason }),
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

  const resetUserPassword = async (userId: string, newPassword?: string) => {
    const res = await apiRequest<{ ok?: boolean; pending_approval?: boolean; message?: string }>(`/api/users/${encodeURIComponent(userId)}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword || '' }),
    });
    if (res.pending_approval) {
      await loadApprovalRequests();
    } else {
      addAuditLog('RESET_PASSWORD', 'User', userId, `Owner reset password and revoked sessions`);
    }
    return res;
  };

  const decideApprovalRequest = async (requestId: string, decision: 'APPROVED' | 'REJECTED', notes: string = '', initialPassword?: string): Promise<ApprovalRequest> => {
    const updated = await apiRequest<ApprovalRequest>(`/api/approvals/requests/${encodeURIComponent(requestId)}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes, initial_password: initialPassword }),
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

  const retryApprovalRequest = async (requestId: string) => {
    const updated = await apiRequest<ApprovalRequest>(`/api/approvals/requests/${encodeURIComponent(requestId)}/retry`, {
      method: 'POST',
    });
    setApprovalRequests((prev) => prev.map((r) => (r.request_id === requestId ? updated : r)));
    try {
      const freshUsers = await apiRequest<User[]>('/api/users');
      if (Array.isArray(freshUsers)) setUsers(freshUsers);
    } catch {}
  };

  const cancelApprovalRequest = async (requestId: string) => {
    const updated = await apiRequest<ApprovalRequest>(`/api/approvals/requests/${encodeURIComponent(requestId)}/cancel`, {
      method: 'POST',
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
        clearSyncError,
        refreshData,
        isRefreshing,
        isGoogleSheetsConnected,
        persistentWritesEnabled,
        connectionError,
        checkHealth,
        reconnectGoogleSheets,
        verifyGoogleSheetsTabs,
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
