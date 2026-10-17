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
} from '../types';
import {
  apiRequest,
  getAuthToken,
  setAuthToken,
  getApiBaseUrl,
  setApiBaseUrl,
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
    user_id: string;
    full_name: string;
    username: string;
    password: string;
    role: string;
    mobile?: string;
    email?: string;
    active?: boolean;
    notes?: string;
  }) => Promise<void>;

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
  getTodayClosingMetrics: (salesmanId: string) => {
    opening_cash: number;
    cash_collected: number;
    approved_cash_expenses: number;
    expected_cash_return: number;
  };
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
  const [dashboardMetrics, setDashboardMetrics] = useState<DashboardMetrics | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const clearSyncError = () => setSyncError(null);

  const updateBackendUrl = (url: string) => {
    setApiBaseUrl(url);
    setBackendUrlState(getApiBaseUrl());
    refreshData();
  };

  const logout = useCallback(() => {
    setAuthToken('');
    if (typeof window !== 'undefined') {
      localStorage.removeItem('ks_user');
    }
    setCurrentUser(null);
  }, []);

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

  // Real Login via POST /api/auth/login with fallback to /auth/login
  const login = async (username: string, password: string): Promise<void> => {
    setIsLoading(true);
    try {
      let res: {
        access_token: string;
        token_type?: string;
        user?: { user_id: string; full_name?: string; role?: string };
        user_id?: string;
        full_name?: string;
        role?: string;
      };

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
          body: JSON.stringify({ username: username.trim(), password }),
          timeoutMs: 70000,
        });
      } catch (err: unknown) {
        if (err instanceof Error && err.message.includes('404')) {
          res = await apiRequest<{
            access_token: string;
            token_type?: string;
            user?: { user_id: string; full_name?: string; role?: string };
            user_id?: string;
            full_name?: string;
            role?: string;
          }>('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username: username.trim(), password }),
            timeoutMs: 70000,
          });
        } else {
          throw err;
        }
      }

      setAuthToken(res.access_token);
      const userPayload = res.user || {
        user_id: res.user_id || username.trim(),
        full_name: res.full_name || username.trim(),
        role: res.role || 'SALESMAN',
      };

      const newUser: User = {
        user_id: userPayload.user_id,
        full_name: userPayload.full_name || username.trim(),
        username: username.trim(),
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
      // Do not keep the user on the login screen while every Google Sheets
      // table is fetched. Authenticate first, then hydrate the workspace in
      // the background so the first successful login is not mistaken for a
      // failed login when Sheets or a sleeping Render instance is slow.
      setSyncError('Signed in. Loading your latest workspace data…');
      setIsRefreshing(true);
      void loadInitialData(userPayload.role).finally(() => setIsRefreshing(false));
    } finally {
      setIsLoading(false);
    }
  };

  // Load all live records from FastAPI backend
  const loadInitialData = useCallback(async (role?: string) => {
    const token = getAuthToken();
    if (!token) return;

    try {
      const activeRole = role || currentUser?.role;
      let hadSyncError = false;

      // Parallel fetch for all core tables
      const [
        prodsData,
        custsData,
        salesData,
        stockSummaryData,
        stockTxnsData,
        salariesData,
        auditData,
        closingsData,
        expensesData,
        visitsData,
        ownerData,
      ] = await Promise.all([
        apiRequest<Product[]>('/api/products').catch((err) => {
          console.error('Failed to load products:', err);
          hadSyncError = true;
          return [] as Product[];
        }),
        apiRequest<Customer[]>('/api/customers').catch((err) => {
          console.error('Failed to load customers:', err);
          hadSyncError = true;
          return [] as Customer[];
        }),
        apiRequest<Sale[]>('/api/sales').catch((err) => {
          console.error('Failed to load sales:', err);
          hadSyncError = true;
          return [] as Sale[];
        }),
        apiRequest<{ company_stock: CompanyStockItem[]; salesman_stock: SalesmanStockItem[] }>('/api/stock/summary').catch(() => ({ company_stock: [], salesman_stock: [] })),
        apiRequest<StockTransaction[]>('/api/stock/transactions?limit=250').catch(() => []),
        apiRequest<SalaryIncentive[]>('/api/salary').catch(() => []),
        apiRequest<AuditLog[]>('/api/audit-logs').catch(() => []),
        apiRequest<DailyClosing[]>('/api/closing').catch(() => []),
        apiRequest<Expense[]>('/api/expenses').catch(() => []),
        apiRequest<ShopVisit[]>('/api/visits').catch(() => []),
        (activeRole === 'OWNER' || activeRole === 'PA')
          ? Promise.all([
              apiRequest<DashboardMetrics>('/api/dashboard').catch(() => null),
              apiRequest<User[]>('/api/users').catch(() => [] as User[]),
            ]).then(([dashboard, userList]) => ({ dashboard, userList }))
          : Promise.resolve({ dashboard: null, userList: [] as User[] }),
      ]);

      if (hadSyncError) {
        setSyncError('Could not sync some records with the backend API. Please verify backend service and Google Sheets connection.');
      } else {
        setSyncError(null);
      }

      const cleanProds = (prodsData || []).map((p) => ({
        ...p,
        active: typeof p.active === 'string' ? (p.active as string).toLowerCase() === 'true' : Boolean(p.active),
        retail_pack_only: typeof p.retail_pack_only === 'string' ? (p.retail_pack_only as string).toLowerCase() === 'true' : Boolean(p.retail_pack_only),
      }));
      setProducts(cleanProds);
      setCustomers(custsData);
      setSales(salesData);
      setCompanyStockSummary(stockSummaryData.company_stock || []);
      setSalesmanStockSummary(stockSummaryData.salesman_stock || []);
      setStockTransactions(stockTxnsData);
      if (salariesData.length > 0) setSalaryIncentives(salariesData);
      if (auditData.length > 0) setAuditLogs(auditData);
      if (closingsData.length > 0) setDailyClosings(closingsData);

      setExpenses(expensesData);
      setShopVisits(visitsData);
      if (ownerData.dashboard) setDashboardMetrics(ownerData.dashboard);
      if (ownerData.userList) setUsers(ownerData.userList);

      setIsBackendConnected(true);
    } catch (err) {
      console.warn('Backend live sync warning:', err);
      setSyncError('Network error connecting to backend API.');
    }
  }, [currentUser?.role]);

  // Check existing session token on mount
  useEffect(() => {
    async function checkSession() {
      const token = getAuthToken();
      if (!token) {
        setIsLoading(false);
        setCurrentUser(null);
        return;
      }

      try {
        let me: { user_id: string; full_name?: string; role?: string };
        try {
          me = await apiRequest<{ user_id: string; full_name?: string; role?: string }>('/api/auth/me');
        } catch (err: unknown) {
          if (err instanceof Error && err.message.includes('404')) {
            me = await apiRequest<{ user_id: string; full_name?: string; role?: string }>('/auth/me');
          } else {
            throw err;
          }
        }

        const verifiedUser: User = {
          user_id: me.user_id,
          full_name: me.full_name || me.user_id,
          username: me.user_id,
          role: (me.role || 'SALESMAN') as User['role'],
          mobile: '',
          email: '',
          active: true,
          created_at: new Date().toISOString(),
          notes: '',
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
  }, [loadInitialData]);

  const refreshData = async () => {
    setIsRefreshing(true);
    try {
      await loadInitialData();
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
    setSales((prev) => {
      const existsIdx = prev.findIndex((s) => s.sale_id === newSale.sale_id);
      if (existsIdx >= 0) {
        const next = [...prev];
        next[existsIdx] = newSale;
        return next;
      }
      return [newSale, ...prev];
    });

    // Refresh stock balances and dashboard automatically after sale issue
    loadInitialData();

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
    return { sale, items: items.length > 0 ? items : (sale.lines || []) };
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
  const getTodayClosingMetrics = (salesmanId: string) => {
    const today = new Date().toISOString().slice(0, 10);

    const todaySales = sales.filter(
      (s) =>
        s.sale_datetime.slice(0, 10) === today &&
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
          e.expense_datetime.slice(0, 10) === today
      )
      .reduce((sum, e) => sum + e.amount, 0);

    const openingCash = 500;
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
    addAuditLog('CREATE', 'DailyClosing', saved.closing_id, `Submitted daily closing`);
    return saved;
  };

  const reviewDailyClosing = async (
    closing_id: string,
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED',
    notes: string = ''
  ) => {
    try {
      const updated = await apiRequest<DailyClosing>(`/api/closing/${encodeURIComponent(closing_id)}/review`, {
        method: 'POST',
        body: JSON.stringify({ confirmed: decision === 'CONFIRMED', notes }),
      });
      setDailyClosings((prev) =>
        prev.map((c) => (c.closing_id === closing_id ? { ...c, ...updated } : c))
      );
    } catch (err) {
      console.warn('Backend closing review warning:', err);
      setDailyClosings((prev) =>
        prev.map((c) =>
          c.closing_id === closing_id
            ? {
                ...c,
                closing_status: decision,
                reviewed_by_user_id: currentUser?.user_id || 'MANAGER',
                reviewed_at: new Date().toISOString(),
                notes: notes || c.notes,
              }
            : c
        )
      );
    }
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
        s.sale_datetime.slice(0, 10) >= params.period_start &&
        s.sale_datetime.slice(0, 10) <= params.period_end
    );

    const relevantSaleIds = new Set(relevantSales.map((s) => s.sale_id));
    const items = saleItems.filter((i) => relevantSaleIds.has(i.sale_id));

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

    setSalaryIncentives((prev) => {
      const existingKeys = new Set(
        prev.map((r) => `${r.period_start}_${r.period_end}_${r.salesman_user_id}_${r.record_type}`)
      );
      const newItems = results.filter(
        (r) => !existingKeys.has(`${r.period_start}_${r.period_end}_${r.salesman_user_id}_${r.record_type}`)
      );
      return [...newItems, ...prev];
    });

    // Asynchronously persist new proposed calculations to backend
    if (results.length > 0) {
      try {
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
        if (persisted && persisted.length > 0) {
          setSalaryIncentives((prev) => {
            const existingIds = new Set(prev.map((p) => p.record_id));
            const fresh = persisted.filter((p) => !existingIds.has(p.record_id));
            return [...fresh, ...prev];
          });
          return persisted;
        }
      } catch (err) {
        console.warn('Backend salary calculation sync warning:', err);
      }
    }

    return results;
  };

  const approveSalaryIncentive = async (record_id: string, approved_amount?: number) => {
    setSalaryIncentives((prev) =>
      prev.map((r) =>
        r.record_id === record_id
          ? {
              ...r,
              approval_status: 'APPROVED',
              approved_amount: approved_amount !== undefined ? approved_amount : r.calculated_amount,
              approved_by_user_id: currentUser?.user_id || 'OWNER',
            }
          : r
      )
    );
    try {
      const updated = await apiRequest<SalaryIncentive>(`/api/salary/${encodeURIComponent(record_id)}/approve`, {
        method: 'POST',
        body: JSON.stringify({ approved_amount, notes: 'Approved in management portal' }),
      });
      setSalaryIncentives((prev) =>
        prev.map((r) => (r.record_id === record_id ? { ...r, ...updated } : r))
      );
    } catch (err) {
      console.warn('Backend salary approval sync warning:', err);
    }
    addAuditLog('APPROVE', 'SalaryIncentive', record_id, 'Approved salary/incentive payment');
  };

  const markSalaryIncentivePaid = async (record_id: string, reference: string) => {
    setSalaryIncentives((prev) =>
      prev.map((r) =>
        r.record_id === record_id
          ? {
              ...r,
              paid_datetime: new Date().toISOString(),
              payment_reference: reference || 'PAID-BANK-TRANSFER',
            }
          : r
      )
    );
    try {
      const updated = await apiRequest<SalaryIncentive>(`/api/salary/${encodeURIComponent(record_id)}/pay`, {
        method: 'POST',
        body: JSON.stringify({ payment_reference: reference }),
      });
      setSalaryIncentives((prev) =>
        prev.map((r) => (r.record_id === record_id ? { ...r, ...updated } : r))
      );
    } catch (err) {
      console.warn('Backend salary pay sync warning:', err);
    }
    addAuditLog('PAY', 'SalaryIncentive', record_id, `Marked paid with ref: ${reference}`);
  };

  const createUser = async (userData: {
    user_id: string;
    full_name: string;
    username: string;
    password: string;
    role: string;
    mobile?: string;
    email?: string;
    active?: boolean;
    notes?: string;
  }) => {
    const saved = await apiRequest<User>('/api/users', {
      method: 'POST',
      body: JSON.stringify(userData),
    });
    setUsers((prev) => [...prev, saved]);
    addAuditLog('CREATE', 'User', saved.user_id, `Created team user ${saved.username}`);
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
        stockTransactions,
        recordStockMovement,
        companyStockSummary,
        salesmanStockSummary,
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
        auditLogs,
        syncError,
        clearSyncError,
        refreshData,
        isRefreshing,
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
