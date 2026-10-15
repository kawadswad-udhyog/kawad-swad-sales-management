import React, { createContext, useContext, useState, useEffect } from 'react';
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
  INITIAL_USERS,
  INITIAL_PRODUCTS,
  INITIAL_CUSTOMERS,
  INITIAL_STOCK_TRANSACTIONS,
  INITIAL_SALES,
  INITIAL_PAYMENTS,
  INITIAL_EXPENSES,
  INITIAL_SHOP_VISITS,
  INITIAL_DAILY_CLOSINGS,
  INITIAL_SALARY_INCENTIVES,
  INITIAL_AUDIT_LOG,
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
  customer_id: string;
  sales_type: CustomerType;
  payment_method: 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER';
  payment_reference: string;
  discount_amount: number;
  notes: string;
  delivery_status?: 'DELIVERED' | 'PENDING' | 'CANCELLED';
  lines: Array<{
    product_id: string;
    quantity: number;
    actual_unit_price: number;
  }>;
}

export interface StoreContextType {
  currentUser: User | null;
  login: (username: string, role?: string) => Promise<boolean>;
  logout: () => void;
  users: User[];
  createUser: (user: Omit<User, 'created_at'>) => void;

  products: Product[];
  addProduct: (product: Omit<Product, 'product_id'>) => Product;
  updateProduct: (product_id: string, updates: Partial<Product>) => void;
  toggleProductActive: (product_id: string) => void;

  customers: Customer[];
  addCustomer: (customer: Omit<Customer, 'customer_id' | 'created_at'>) => Customer;
  updateCustomer: (customer_id: string, updates: Partial<Customer>) => void;

  sales: Sale[];
  createSale: (input: CreateSaleInput) => { sale: Sale; payment: Payment };
  getSaleWithItems: (sale_id: string) => { sale: Sale; items: SaleItem[] } | null;

  stockTransactions: StockTransaction[];
  recordStockMovement: (input: {
    txn_type: StockTxnType;
    product_id: string;
    salesman_user_id?: string;
    quantity: number;
    notes?: string;
  }) => void;
  companyStockSummary: CompanyStockItem[];
  salesmanStockSummary: SalesmanStockItem[];

  expenses: Expense[];
  submitExpense: (input: {
    category: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL';
    amount: number;
    description: string;
    receipt_link_or_file_ref?: string;
  }) => void;
  approveExpense: (expense_id: string, reason?: string) => void;
  rejectExpense: (expense_id: string, reason: string) => void;

  shopVisits: ShopVisit[];
  addShopVisit: (input: {
    customer_id: string;
    visit_outcome: string;
    order_taken: boolean;
    follow_up_date: string;
    next_action: string;
    notes?: string;
  }) => void;

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
  }) => DailyClosing;
  reviewDailyClosing: (
    closing_id: string,
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED',
    notes?: string
  ) => void;

  salaryIncentives: SalaryIncentive[];
  calculatePayroll: (params: {
    period_start: string;
    period_end: string;
    salesman_user_id: string;
    trial_days: number;
    trial_rate_per_kg: number;
    monthly_rate_per_100kg: number;
    base_salary: number;
  }) => SalaryIncentive[];
  approveSalaryIncentive: (record_id: string, approved_amount?: number) => void;
  markSalaryIncentivePaid: (record_id: string, reference: string) => void;

  auditLogs: AuditLog[];
  resetToSampleData: () => void;
}

const StoreContext = createContext<StoreContextType | null>(null);

function loadStorage<T>(key: string, defaultValue: T): T {
  try {
    const item = localStorage.getItem(`ks_${key}`);
    return item ? JSON.parse(item) : defaultValue;
  } catch (e) {
    console.error(`Failed to load ${key} from localStorage`, e);
    return defaultValue;
  }
}

function saveStorage<T>(key: string, value: T) {
  try {
    localStorage.setItem(`ks_${key}`, JSON.stringify(value));
  } catch (e) {
    console.error(`Failed to save ${key} to localStorage`, e);
  }
}

export const StoreProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [users, setUsers] = useState<User[]>(() => loadStorage('users', INITIAL_USERS));
  const [currentUser, setCurrentUser] = useState<User | null>(() => {
    const savedUserId = localStorage.getItem('ks_current_user_id');
    if (savedUserId) {
      const found = INITIAL_USERS.concat(loadStorage('users', [])).find(
        (u) => u.user_id === savedUserId
      );
      if (found) return found;
    }
    // Default to Owner for immediate access if no session
    return INITIAL_USERS[0];
  });

  const [products, setProducts] = useState<Product[]>(() =>
    loadStorage('products', INITIAL_PRODUCTS)
  );
  const [customers, setCustomers] = useState<Customer[]>(() =>
    loadStorage('customers', INITIAL_CUSTOMERS)
  );
  const [sales, setSales] = useState<Sale[]>(() => loadStorage('sales', INITIAL_SALES));
  const [saleItems, setSaleItems] = useState<SaleItem[]>(() => {
    const fromSales = INITIAL_SALES.flatMap((s) => s.lines || []);
    return loadStorage('sale_items', fromSales);
  });
  const [payments, setPayments] = useState<Payment[]>(() =>
    loadStorage('payments', INITIAL_PAYMENTS)
  );
  const [stockTransactions, setStockTransactions] = useState<StockTransaction[]>(() =>
    loadStorage('stock_txns', INITIAL_STOCK_TRANSACTIONS)
  );
  const [expenses, setExpenses] = useState<Expense[]>(() =>
    loadStorage('expenses', INITIAL_EXPENSES)
  );
  const [shopVisits, setShopVisits] = useState<ShopVisit[]>(() =>
    loadStorage('visits', INITIAL_SHOP_VISITS)
  );
  const [dailyClosings, setDailyClosings] = useState<DailyClosing[]>(() =>
    loadStorage('closings', INITIAL_DAILY_CLOSINGS)
  );
  const [salaryIncentives, setSalaryIncentives] = useState<SalaryIncentive[]>(() =>
    loadStorage('salary_incentives', INITIAL_SALARY_INCENTIVES)
  );
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>(() =>
    loadStorage('audit_log', INITIAL_AUDIT_LOG)
  );

  // Sync to localStorage
  useEffect(() => saveStorage('users', users), [users]);
  useEffect(() => saveStorage('products', products), [products]);
  useEffect(() => saveStorage('customers', customers), [customers]);
  useEffect(() => saveStorage('sales', sales), [sales]);
  useEffect(() => saveStorage('sale_items', saleItems), [saleItems]);
  useEffect(() => saveStorage('payments', payments), [payments]);
  useEffect(() => saveStorage('stock_txns', stockTransactions), [stockTransactions]);
  useEffect(() => saveStorage('expenses', expenses), [expenses]);
  useEffect(() => saveStorage('visits', shopVisits), [shopVisits]);
  useEffect(() => saveStorage('closings', dailyClosings), [dailyClosings]);
  useEffect(() => saveStorage('salary_incentives', salaryIncentives), [salaryIncentives]);
  useEffect(() => saveStorage('audit_log', auditLogs), [auditLogs]);

  useEffect(() => {
    if (currentUser) {
      localStorage.setItem('ks_current_user_id', currentUser.user_id);
    } else {
      localStorage.removeItem('ks_current_user_id');
    }
  }, [currentUser]);

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
  };

  const login = async (username: string, _role?: string): Promise<boolean> => {
    const clean = username.trim().toLowerCase();
    const user = users.find(
      (u) => u.username.toLowerCase() === clean && u.active !== false
    );
    if (user) {
      setCurrentUser(user);
      return true;
    }
    return false;
  };

  const logout = () => {
    setCurrentUser(null);
  };

  const createUser = (userData: Omit<User, 'created_at'>) => {
    const newUser: User = {
      ...userData,
      created_at: new Date().toISOString(),
      active: true,
    };
    setUsers((prev) => [...prev, newUser]);
    addAuditLog('CREATE', 'User', newUser.user_id, `Created user ${newUser.username}`);
  };

  const addProduct = (prodData: Omit<Product, 'product_id'>): Product => {
    const newId = `PRD-${Date.now().toString().slice(-4)}`;
    const newProd: Product = {
      ...prodData,
      product_id: newId,
    };
    setProducts((prev) => [...prev, newProd]);
    addAuditLog('CREATE', 'Product', newId, `Added product ${newProd.sku}`);
    return newProd;
  };

  const updateProduct = (product_id: string, updates: Partial<Product>) => {
    setProducts((prev) =>
      prev.map((p) => {
        if (p.product_id === product_id) {
          return { ...p, ...updates };
        }
        return p;
      })
    );
    addAuditLog('UPDATE', 'Product', product_id, 'Updated product catalogue details');
  };

  const toggleProductActive = (product_id: string) => {
    setProducts((prev) =>
      prev.map((p) => {
        if (p.product_id === product_id) {
          const next = !p.active;
          addAuditLog(
            'UPDATE',
            'Product',
            product_id,
            `Product status changed to ${next ? 'Active' : 'Inactive'}`,
            'active',
            String(p.active),
            String(next)
          );
          return { ...p, active: next };
        }
        return p;
      })
    );
  };

  const addCustomer = (custData: Omit<Customer, 'customer_id' | 'created_at'>): Customer => {
    const newId = `CUS-${Date.now().toString().slice(-4)}`;
    const newCust: Customer = {
      ...custData,
      customer_id: newId,
      created_at: new Date().toISOString(),
    };
    setCustomers((prev) => [...prev, newCust]);
    addAuditLog('CREATE', 'Customer', newId, `Registered customer ${newCust.shop_name}`);
    return newCust;
  };

  const updateCustomer = (customer_id: string, updates: Partial<Customer>) => {
    setCustomers((prev) =>
      prev.map((c) => (c.customer_id === customer_id ? { ...c, ...updates } : c))
    );
    addAuditLog('UPDATE', 'Customer', customer_id, 'Updated customer details');
  };

  // Stock summary calculation based on ledger rules
  const companyStockSummary: CompanyStockItem[] = products.map((prod) => {
    let companyQty = 0;
    for (const txn of stockTransactions) {
      if (txn.product_id === prod.product_id) {
        if (txn.txn_type === 'COMPANY_RECEIPT' || txn.txn_type === 'COMPANY_ADJUSTMENT') {
          companyQty += txn.quantity;
        } else if (txn.txn_type === 'ISSUED') {
          companyQty -= txn.quantity;
        } else if (txn.txn_type === 'RETURNED') {
          companyQty += txn.quantity;
        }
      }
    }
    return {
      product_id: prod.product_id,
      sku: prod.sku,
      product_name: prod.product_name,
      pack_weight_g: prod.pack_weight_g,
      company_quantity: Math.round(companyQty * 1000) / 1000,
    };
  });

  const salesmanStockSummary: SalesmanStockItem[] = [];
  const salesmanUsers = users.filter((u) => u.role === 'SALESMAN');
  for (const sm of salesmanUsers) {
    for (const prod of products) {
      let qty = 0;
      for (const txn of stockTransactions) {
        if (txn.product_id === prod.product_id && txn.salesman_user_id === sm.user_id) {
          if (txn.txn_type === 'ISSUED') {
            qty += txn.quantity;
          } else if (txn.txn_type === 'RETURNED' || txn.txn_type === 'SOLD') {
            qty -= txn.quantity;
          } else if (txn.txn_type === 'SALESMAN_ADJUSTMENT') {
            qty += txn.quantity;
          }
        }
      }
      if (qty > 0) {
        salesmanStockSummary.push({
          salesman_user_id: sm.user_id,
          salesman_name: sm.full_name,
          product_id: prod.product_id,
          sku: prod.sku,
          product_name: prod.product_name,
          quantity: Math.round(qty * 1000) / 1000,
        });
      }
    }
  }

  const recordStockMovement = (input: {
    txn_type: StockTxnType;
    product_id: string;
    salesman_user_id?: string;
    quantity: number;
    notes?: string;
  }) => {
    const product = products.find((p) => p.product_id === input.product_id);
    if (!product) throw new Error('Product not found');

    const companyItem = companyStockSummary.find((c) => c.product_id === input.product_id);
    const availableCompanyQty = companyItem ? companyItem.company_quantity : 0;

    let availableSalesmanQty = 0;
    if (input.salesman_user_id) {
      const smItem = salesmanStockSummary.find(
        (s) =>
          s.product_id === input.product_id &&
          s.salesman_user_id === input.salesman_user_id
      );
      availableSalesmanQty = smItem ? smItem.quantity : 0;
    }

    if (input.txn_type === 'ISSUED' && input.quantity > availableCompanyQty) {
      throw new Error(
        `Insufficient company stock. Available: ${availableCompanyQty} ${product.selling_unit}.`
      );
    }

    if (
      (input.txn_type === 'RETURNED' || input.txn_type === 'SOLD') &&
      input.quantity > availableSalesmanQty
    ) {
      throw new Error(
        `Insufficient salesman stock. Available: ${availableSalesmanQty} ${product.selling_unit}.`
      );
    }

    const txnId = `STK-${Date.now()}-${Math.random().toString(36).substring(2, 5).toUpperCase()}`;
    const newTxn: StockTransaction = {
      stock_txn_id: txnId,
      txn_datetime: new Date().toISOString(),
      salesman_user_id:
        input.txn_type === 'COMPANY_RECEIPT' || input.txn_type === 'COMPANY_ADJUSTMENT'
          ? ''
          : input.salesman_user_id || '',
      product_id: input.product_id,
      sku_snapshot: product.sku,
      txn_type: input.txn_type,
      quantity: input.quantity,
      unit: product.selling_unit,
      pack_weight_g: product.pack_weight_g,
      related_sale_id: '',
      issued_by_user_id: input.txn_type === 'ISSUED' ? (currentUser?.user_id || '') : '',
      received_by_user_id:
        input.txn_type === 'COMPANY_RECEIPT' || input.txn_type === 'RETURNED'
          ? (currentUser?.user_id || '')
          : '',
      confirmed_by_user_id: '',
      reference_id: '',
      notes: input.notes || '',
    };

    setStockTransactions((prev) => [newTxn, ...prev]);
    addAuditLog(
      'CREATE',
      'StockTransaction',
      txnId,
      `Movement: ${input.txn_type} ${input.quantity} of ${product.sku}`
    );
  };

  const createSale = (input: CreateSaleInput): { sale: Sale; payment: Payment } => {
    const customer = customers.find((c) => c.customer_id === input.customer_id);
    if (!customer) throw new Error('Customer not found');

    if (!input.lines || input.lines.length === 0) {
      throw new Error('Add at least one product line.');
    }

    let subtotal = 0;
    const saleId = `SALE-${Date.now()}-${Math.random().toString(36).substring(2, 5).toUpperCase()}`;
    const nowStamp = new Date().toISOString();
    const dateCode = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const billNumber = `KS-${dateCode}-${Math.random().toString(36).substring(2, 5).toUpperCase()}`;

    const items: SaleItem[] = [];

    for (const line of input.lines) {
      const prod = products.find((p) => p.product_id === line.product_id);
      if (!prod || !prod.active) {
        throw new Error(`Product ${line.product_id} is inactive or not found`);
      }
      if (prod.retail_pack_only && prod.selling_unit !== 'packet') {
        throw new Error('Retail packs must be sold by packet.');
      }
      const lineTotal = Math.round(line.quantity * line.actual_unit_price * 100) / 100;
      subtotal += lineTotal;

      const weight = prod.pack_weight_g || 0;
      const qualifyingKg =
        weight > 0 ? (line.quantity * weight) / 1000 : line.quantity;

      items.push({
        sale_item_id: `ITEM-${Date.now()}-${Math.random().toString(36).substring(2, 5).toUpperCase()}`,
        sale_id: saleId,
        product_id: prod.product_id,
        product_name_snapshot: prod.product_name,
        sku_snapshot: prod.sku,
        pack_weight_g: prod.pack_weight_g,
        unit: prod.selling_unit,
        quantity: line.quantity,
        actual_unit_price: line.actual_unit_price,
        discount_amount: 0,
        line_total: lineTotal,
        qualifying_kg: Math.round(qualifyingKg * 1000) / 1000,
        created_at: nowStamp,
        notes: '',
      });
    }

    const discount = Number(input.discount_amount || 0);
    if (discount > subtotal) {
      throw new Error('Discount cannot exceed subtotal.');
    }
    const billTotal = Math.max(0, Math.round((subtotal - discount) * 100) / 100);

    const newSale: Sale = {
      sale_id: saleId,
      bill_number: billNumber,
      sale_datetime: nowStamp,
      sales_type: input.sales_type,
      customer_id: input.customer_id,
      customer_name_snapshot: customer.shop_name,
      entered_by_user_id: currentUser?.user_id || 'SYSTEM',
      salesman_user_id:
        currentUser?.role === 'SALESMAN' ? currentUser.user_id : '',
      delivery_status: input.delivery_status || 'DELIVERED',
      payment_status: 'PAID',
      subtotal: Math.round(subtotal * 100) / 100,
      discount_amount: discount,
      tax_amount: 0,
      bill_total: billTotal,
      bill_status: 'ISSUED',
      created_at: nowStamp,
      notes: input.notes || '',
      lines: items,
    };

    const newPayment: Payment = {
      payment_id: `PAY-${Date.now()}-${Math.random().toString(36).substring(2, 5).toUpperCase()}`,
      sale_id: saleId,
      payment_datetime: nowStamp,
      payment_method: input.payment_method,
      amount: billTotal,
      reference_number: input.payment_reference || 'FULL-PAYMENT-RECEIVED',
      received_by_user_id: currentUser?.user_id || 'SYSTEM',
      payment_status: 'RECEIVED',
      notes: `Full payment recorded on bill ${billNumber}`,
    };

    setSales((prev) => [newSale, ...prev]);
    setSaleItems((prev) => [...items, ...prev]);
    setPayments((prev) => [newPayment, ...prev]);

    addAuditLog(
      'CREATE',
      'Sale',
      saleId,
      `Issued bill ${billNumber} for ₹${billTotal.toFixed(2)} to ${customer.shop_name}`
    );

    return { sale: newSale, payment: newPayment };
  };

  const getSaleWithItems = (sale_id: string) => {
    const sale = sales.find((s) => s.sale_id === sale_id || s.bill_number === sale_id);
    if (!sale) return null;
    const items = saleItems.filter((item) => item.sale_id === sale.sale_id);
    return { sale, items };
  };

  const submitExpense = (input: {
    category: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL';
    amount: number;
    description: string;
    receipt_link_or_file_ref?: string;
  }) => {
    const expenseId = `EXP-${Date.now()}-${Math.random().toString(36).substring(2, 5).toUpperCase()}`;
    const newExpense: Expense = {
      expense_id: expenseId,
      expense_datetime: new Date().toISOString(),
      submitted_by_user_id: currentUser?.user_id || 'SYSTEM',
      salesman_user_id:
        currentUser?.role === 'SALESMAN' ? currentUser.user_id : '',
      category: input.category,
      amount: input.amount,
      description: input.description,
      receipt_link_or_file_ref: input.receipt_link_or_file_ref || '',
      approval_status: 'PENDING',
      approved_by_user_id: '',
      approval_datetime: '',
      cash_reducing_expense: false,
      related_closing_id: '',
      notes: '',
    };
    setExpenses((prev) => [newExpense, ...prev]);
    addAuditLog('CREATE', 'Expense', expenseId, `Submitted expense of ₹${input.amount}`);
  };

  const approveExpense = (expense_id: string, reason: string = 'Approved') => {
    setExpenses((prev) =>
      prev.map((e) => {
        if (e.expense_id === expense_id) {
          const isCashReducing = e.category !== 'DIGITAL';
          return {
            ...e,
            approval_status: 'APPROVED',
            approved_by_user_id: currentUser?.user_id || 'MANAGER',
            approval_datetime: new Date().toISOString(),
            cash_reducing_expense: isCashReducing,
            notes: reason,
          };
        }
        return e;
      })
    );
    addAuditLog('APPROVE', 'Expense', expense_id, reason);
  };

  const rejectExpense = (expense_id: string, reason: string) => {
    setExpenses((prev) =>
      prev.map((e) => {
        if (e.expense_id === expense_id) {
          return {
            ...e,
            approval_status: 'REJECTED',
            approved_by_user_id: currentUser?.user_id || 'MANAGER',
            approval_datetime: new Date().toISOString(),
            cash_reducing_expense: false,
            notes: reason,
          };
        }
        return e;
      })
    );
    addAuditLog('REJECT', 'Expense', expense_id, reason);
  };

  const addShopVisit = (input: {
    customer_id: string;
    visit_outcome: string;
    order_taken: boolean;
    follow_up_date: string;
    next_action: string;
    notes?: string;
  }) => {
    const cust = customers.find((c) => c.customer_id === input.customer_id);
    const visitId = `VIS-${Date.now()}-${Math.random().toString(36).substring(2, 5).toUpperCase()}`;
    const newVisit: ShopVisit = {
      visit_id: visitId,
      visit_datetime: new Date().toISOString(),
      salesman_user_id: currentUser?.user_id || 'SYSTEM',
      customer_id: input.customer_id,
      shop_name_snapshot: cust ? cust.shop_name : '',
      visit_outcome: input.visit_outcome,
      order_taken: input.order_taken,
      follow_up_date: input.follow_up_date,
      next_action: input.next_action,
      created_at: new Date().toISOString(),
      notes: input.notes || '',
    };
    setShopVisits((prev) => [newVisit, ...prev]);
    addAuditLog('CREATE', 'ShopVisit', visitId, `Recorded shop visit to ${cust?.shop_name}`);
  };

  const getTodayClosingMetrics = (salesmanId: string) => {
    const today = new Date().toISOString().slice(0, 10);

    // Sales by this salesman today
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

    const openingCash = 500; // Standard default float or previous closing
    const expected = Math.max(0, openingCash + cashCollected - approvedExpenses);

    return {
      opening_cash: openingCash,
      cash_collected: cashCollected,
      approved_cash_expenses: approvedExpenses,
      expected_cash_return: expected,
    };
  };

  const submitDailyClosing = (input: {
    opening_cash: number;
    physical_cash_returned: number;
    notes?: string;
  }): DailyClosing => {
    const salesmanId = currentUser?.user_id || 'USR-SALES-001';
    const metrics = getTodayClosingMetrics(salesmanId);
    const expected = Math.round(
      (input.opening_cash + metrics.cash_collected - metrics.approved_cash_expenses) * 100
    ) / 100;
    const diff = Math.round((input.physical_cash_returned - expected) * 100) / 100;

    const closingId = `CLOSE-${Date.now().toString().slice(-4)}`;
    const newClosing: DailyClosing = {
      closing_id: closingId,
      closing_date: new Date().toISOString().slice(0, 10),
      salesman_user_id: salesmanId,
      opening_cash: input.opening_cash,
      cash_collected: metrics.cash_collected,
      approved_cash_expenses: metrics.approved_cash_expenses,
      expected_cash_return: expected,
      physical_cash_returned: input.physical_cash_returned,
      cash_difference: diff,
      opening_stock_reference: '',
      stock_discrepancy_flag: diff !== 0,
      closing_status: 'SUBMITTED',
      submitted_at: new Date().toISOString(),
      reviewed_by_user_id: '',
      reviewed_at: '',
      notes: input.notes || '',
    };

    setDailyClosings((prev) => [newClosing, ...prev]);
    addAuditLog('CREATE', 'DailyClosing', closingId, `Submitted daily cash closing`);
    return newClosing;
  };

  const reviewDailyClosing = (
    closing_id: string,
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED',
    notes: string = ''
  ) => {
    setDailyClosings((prev) =>
      prev.map((c) => {
        if (c.closing_id === closing_id) {
          return {
            ...c,
            closing_status: decision,
            reviewed_by_user_id: currentUser?.user_id || 'MANAGER',
            reviewed_at: new Date().toISOString(),
            notes: notes || c.notes,
          };
        }
        return c;
      })
    );
    addAuditLog('REVIEW', 'DailyClosing', closing_id, `Review decision: ${decision}`);
  };

  const calculatePayroll = (params: {
    period_start: string;
    period_end: string;
    salesman_user_id: string;
    trial_days: number;
    trial_rate_per_kg: number;
    monthly_rate_per_100kg: number;
    base_salary: number;
  }): SalaryIncentive[] => {
    const salesman = users.find((u) => u.user_id === params.salesman_user_id);
    const joinDate = salesman ? new Date(salesman.created_at) : new Date(params.period_start);
    const trialEndDate = new Date(joinDate.getTime() + params.trial_days * 24 * 60 * 60 * 1000);

    // Filter delivered, fully paid sales in the period
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

    // Base salary (if completed trial by period end)
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

    // Trial incentive
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

    // Monthly volume incentive (per completed 100kg block)
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

    // Merge into state avoiding duplicates
    setSalaryIncentives((prev) => {
      const existingKeys = new Set(
        prev.map((r) => `${r.period_start}_${r.period_end}_${r.salesman_user_id}_${r.record_type}`)
      );
      const newItems = results.filter(
        (r) => !existingKeys.has(`${r.period_start}_${r.period_end}_${r.salesman_user_id}_${r.record_type}`)
      );
      return [...newItems, ...prev];
    });

    return results;
  };

  const approveSalaryIncentive = (record_id: string, approved_amount?: number) => {
    setSalaryIncentives((prev) =>
      prev.map((r) => {
        if (r.record_id === record_id) {
          return {
            ...r,
            approval_status: 'APPROVED',
            approved_amount: approved_amount !== undefined ? approved_amount : r.calculated_amount,
            approved_by_user_id: currentUser?.user_id || 'OWNER',
          };
        }
        return r;
      })
    );
    addAuditLog('APPROVE', 'SalaryIncentive', record_id, 'Approved salary/incentive payment');
  };

  const markSalaryIncentivePaid = (record_id: string, reference: string) => {
    setSalaryIncentives((prev) =>
      prev.map((r) => {
        if (r.record_id === record_id) {
          return {
            ...r,
            paid_datetime: new Date().toISOString(),
            payment_reference: reference || 'PAID-BANK-TRANSFER',
          };
        }
        return r;
      })
    );
    addAuditLog('PAY', 'SalaryIncentive', record_id, `Marked paid with ref: ${reference}`);
  };

  const resetToSampleData = () => {
    setUsers(INITIAL_USERS);
    setProducts(INITIAL_PRODUCTS);
    setCustomers(INITIAL_CUSTOMERS);
    setSales(INITIAL_SALES);
    setSaleItems(INITIAL_SALES.flatMap((s) => s.lines || []));
    setPayments(INITIAL_PAYMENTS);
    setStockTransactions(INITIAL_STOCK_TRANSACTIONS);
    setExpenses(INITIAL_EXPENSES);
    setShopVisits(INITIAL_SHOP_VISITS);
    setDailyClosings(INITIAL_DAILY_CLOSINGS);
    setSalaryIncentives(INITIAL_SALARY_INCENTIVES);
    setAuditLogs(INITIAL_AUDIT_LOG);
    setCurrentUser(INITIAL_USERS[0]);
  };

  return (
    <StoreContext.Provider
      value={{
        currentUser,
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
        sales,
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
        auditLogs,
        resetToSampleData,
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
