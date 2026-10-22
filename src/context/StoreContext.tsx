const activeRole = role || currentUser?.role;

const workspace = await apiRequest<{
  products: Product[];
  customers: Customer[];
  sales: Sale[];
  payments: Payment[];
  stock: {
    company_stock: CompanyStockItem[];
    salesman_stock: SalesmanStockItem[];
  };
  stock_transactions: StockTransaction[];
  expenses: Expense[];
  visits: ShopVisit[];
  closings: DailyClosing[];
  salary: SalaryIncentive[];
  dashboard: DashboardMetrics | null;
  users: User[];
  stock_discrepancies?: any[];
  audit_logs?: AuditLog[];
  approval_requests?: ApprovalRequest[];
  _sync_errors?: Array<{
    resource: string;
    message: string;
  }>;
}>('/api/workspace');

const prodsData = workspace.products || [];
const custsData = workspace.customers || [];

const salesData = (workspace.sales || []).map((sale) => ({
  ...sale,
  lines:
    sale.lines && sale.lines.length
      ? sale.lines
      : sale.items || [],
}));

const stockSummaryData = workspace.stock || {
  company_stock: [],
  salesman_stock: [],
};

const stockTxnsData = workspace.stock_transactions || [];
const salariesData = workspace.salary || [];
const auditData: AuditLog[] = workspace.audit_logs || [];
const closingsData = workspace.closings || [];
const expensesData = workspace.expenses || [];
const visitsData = workspace.visits || [];

const ownerData = {
  dashboard: workspace.dashboard,
  userList: workspace.users || [],
};

const discData = workspace.stock_discrepancies || [];

setPayments(workspace.payments || []);
setSaleItems(salesData.flatMap((sale) => sale.lines || []));
setStockDiscrepancies(discData);

if (workspace.approval_requests) {
  setApprovalRequests(workspace.approval_requests);
}

const syncErrors = workspace._sync_errors || [];

if (syncErrors.length > 0) {
  const resources = syncErrors
    .map((item) => item.resource)
    .join(', ');

  setSyncError(
    `Partial data sync: could not load ${resources}. ` +
      'Displayed tables may be incomplete. Check backend logs ' +
      'and Google Sheets access, then retry sync.'
  );
} else {
  setSyncError(null);
}
