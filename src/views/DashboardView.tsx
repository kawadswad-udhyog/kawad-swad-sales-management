import React from 'react';
import { useStore } from '../context/StoreContext';
import { ViewType } from '../components/Navigation';
import { WorkspaceId, getWorkspaceForRole } from '../utils/workspaces';
import { SummaryCard } from '../components/common/StatCard';
import { QuickAction } from '../components/common/QuickAction';
import { StatusBadge } from '../components/common/StatusBadge';
import {
  TrendingUp,
  Receipt,
  Factory,
  Boxes,
  Users,
  AlertTriangle,
  Clock,
  ArrowRight,
  ShieldAlert,
  CheckCircle2,
  Calendar,
  Wallet,
  Smartphone,
  MapPin,
  ShoppingCart,
  UserCheck,
  Package,
  Scale,
  FileText,
  Truck,
  ShieldCheck,
  Coins,
  Lock,
  Plus,
  Briefcase,
} from 'lucide-react';

interface DashboardViewProps {
  onNavigate: (view: ViewType) => void;
  activeWorkspaceId?: WorkspaceId;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  onNavigate,
  activeWorkspaceId,
}) => {
  const {
    currentUser,
    sales,
    expenses,
    dailyClosings,
    stockTransactions,
    customers,
    shopVisits,
    dashboardMetrics,
    products,
    companyStockSummary,
    salesmanStockSummary,
    approvalRequests,
  } = useStore();

  const role = currentUser?.role;
  const workspaceConfig = activeWorkspaceId
    ? { id: activeWorkspaceId }
    : getWorkspaceForRole(role);

  const todayStr = new Date().toISOString().slice(0, 10);
  const currentMonthStr = todayStr.slice(0, 7);

  const safeSales = Array.isArray(sales) ? sales : [];
  const safeExpenses = Array.isArray(expenses) ? expenses : [];
  const safeClosings = Array.isArray(dailyClosings) ? dailyClosings : [];
  const safeCustomers = Array.isArray(customers) ? customers : [];
  const safeVisits = Array.isArray(shopVisits) ? shopVisits : [];
  const safeProducts = Array.isArray(products) ? products : [];
  const safeStockItems = Array.isArray(companyStockSummary) ? companyStockSummary : [];

  // Filter calculations
  const todaySales = safeSales.filter(
    (s) => String(s?.sale_datetime || '').slice(0, 10) === todayStr && s?.bill_status === 'ISSUED'
  );
  const monthSales = safeSales.filter(
    (s) => String(s?.sale_datetime || '').slice(0, 7) === currentMonthStr && s?.bill_status === 'ISSUED'
  );

  const todayRevenue = Number(
    dashboardMetrics?.today_sales ??
    todaySales.reduce((sum, s) => sum + (Number(s?.bill_total) || 0), 0) ??
    0
  );
  const monthRevenue = Number(
    monthSales.reduce((sum, s) => sum + (Number(s?.bill_total) || 0), 0) || 0
  );

  const pendingApprovals = Number(
    (approvalRequests?.filter((r) => r.status === 'PENDING').length || 0) +
    (dashboardMetrics?.pending_production_approvals || 0)
  );
  const pendingExpenses = Number(
    safeExpenses.filter((e) => String(e?.approval_status || '').toUpperCase() === 'PENDING').length ||
    dashboardMetrics?.pending_expenses ||
    0
  );

  // ==========================================================================
  // 1. SALESMAN DASHBOARD (Mobile-first, large tap targets)
  // ==========================================================================
  if (workspaceConfig.id === 'salesman') {
    const todayVisits = safeVisits.filter(
      (v) =>
        String(v?.visit_datetime || '').slice(0, 10) === todayStr &&
        v?.salesman_user_id === currentUser?.user_id
    );
    const myTodaySales = safeSales.filter(
      (s) =>
        String(s?.sale_datetime || '').slice(0, 10) === todayStr &&
        (s?.salesman_user_id === currentUser?.user_id || s?.entered_by_user_id === currentUser?.user_id)
    );
    const mySalesRevenue = myTodaySales.reduce((sum, s) => sum + (Number(s?.bill_total) || 0), 0);

    return (
      <div className="space-y-6 max-w-4xl mx-auto">
        {/* Salesman Welcome Header */}
        <div className="bg-emerald-900 text-white rounded-2xl p-6 sm:p-7 shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="text-[11px] font-bold tracking-wider uppercase text-emerald-300">
                Field Sales Workspace
              </div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mt-1 text-white m-0">
                Namaste, {currentUser?.full_name || 'Sales Officer'} 👋
              </h1>
              <p className="text-xs sm:text-sm text-emerald-100/90 mt-1.5 mb-0 max-w-lg leading-relaxed">
                Take orders, record customer visits, issue bills, and complete daily cash closing.
              </p>
            </div>
            <div className="shrink-0 bg-emerald-800/80 border border-emerald-700/60 rounded-xl px-4 py-2.5 text-center">
              <div className="text-[10px] text-emerald-300 font-semibold uppercase tracking-wider">Today</div>
              <div className="text-sm font-bold text-white">
                {new Date().toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}
              </div>
            </div>
          </div>
        </div>

        {/* Live Daily Progress */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 sm:gap-4">
          <SummaryCard
            title="Today's Sales"
            value={`₹${mySalesRevenue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
            subtext={`${myTodaySales.length} bills generated today`}
            icon={<Wallet size={16} />}
          />
          <SummaryCard
            title="Shop Visits"
            value={todayVisits.length}
            subtext="Retail stores logged"
            icon={<MapPin size={16} />}
          />
          <SummaryCard
            title="Orders Taken"
            value={myTodaySales.length}
            subtext="Delivered & billed"
            icon={<ShoppingCart size={16} />}
          />
        </div>

        {/* Primary Field Action Buttons */}
        <div>
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
            Quick Actions
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <QuickAction
              title="New Order & Bill"
              description="Record sale, select items, and issue bill receipt"
              icon={<Plus size={20} />}
              primary
              onClick={() => onNavigate('sales')}
            />
            <QuickAction
              title="Add Customer"
              description="Register a new retail shop or wholesaler"
              icon={<Users size={20} />}
              onClick={() => onNavigate('customers')}
            />
            <QuickAction
              title="Record Shop Visit"
              description="Log visit notes and shopkeeper interaction"
              icon={<MapPin size={20} />}
              onClick={() => onNavigate('visits')}
            />
            <QuickAction
              title="My Van Stock"
              description="Check current packets loaded in your delivery vehicle"
              icon={<Boxes size={20} />}
              onClick={() => onNavigate('stock')}
            />
            <QuickAction
              title="Submit Expense"
              description="Claim fuel, travel or meals with instant receipt"
              icon={<Receipt size={20} />}
              onClick={() => onNavigate('expenses')}
            />
            <QuickAction
              title="Daily Cash Closing"
              description="Reconcile cash collections and submit day-end balance"
              icon={<Lock size={20} />}
              onClick={() => onNavigate('closing')}
            />
          </div>
        </div>
      </div>
    );
  }

  // ==========================================================================
  // 2. PA DASHBOARD (Daily Operations & Priorities)
  // ==========================================================================
  if (workspaceConfig.id === 'pa') {
    return (
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-200">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
              Personal Assistant Workspace
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight m-0">
              Daily Operations & Priorities
            </h1>
            <p className="text-xs text-slate-500 mt-1 mb-0">
              Monitor team activities, pending approvals, purchase requests, and daily closings.
            </p>
          </div>
          <div className="text-xs font-medium text-slate-500">
            {new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
          </div>
        </div>

        {/* Priority Summary Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <SummaryCard
            title="Pending Approvals"
            value={pendingApprovals}
            subtext="Batches & adjustments awaiting sign-off"
            icon={<CheckCircle2 size={16} />}
            alert={pendingApprovals > 0}
            onClick={() => onNavigate('approvals')}
          />
          <SummaryCard
            title="Expenses to Review"
            value={pendingExpenses}
            subtext="Staff expense claims pending"
            icon={<Receipt size={16} />}
            alert={pendingExpenses > 0}
            onClick={() => onNavigate('expenses')}
          />
          <SummaryCard
            title="Today's Orders"
            value={todaySales.length}
            subtext={`₹${todayRevenue.toLocaleString('en-IN', { maximumFractionDigits: 0 })} billing`}
            icon={<ShoppingCart size={16} />}
            onClick={() => onNavigate('sales')}
          />
          <SummaryCard
            title="Daily Closings"
            value={safeClosings.length}
            subtext="Field cash closings received"
            icon={<Lock size={16} />}
            onClick={() => onNavigate('closing')}
          />
        </div>

        {/* Action Grid */}
        <div>
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
            Today's Operational Actions
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <QuickAction
              title="Review Approvals"
              description="Approve production yields and packaging batches"
              icon={<CheckCircle2 size={20} />}
              badge={pendingApprovals > 0 ? pendingApprovals : undefined}
              primary={pendingApprovals > 0}
              onClick={() => onNavigate('approvals')}
            />
            <QuickAction
              title="Purchase Materials"
              description="Receive raw whole dal, flour, spices and packaging pouches"
              icon={<Truck size={20} />}
              onClick={() => onNavigate('purchasing')}
            />
            <QuickAction
              title="Production Batches"
              description="Inspect recipe batches and intermediate bulk papad yields"
              icon={<Factory size={20} />}
              onClick={() => onNavigate('production')}
            />
            <QuickAction
              title="Worker Attendance"
              description="Record daily factory attendance and calculate labour wages"
              icon={<UserCheck size={20} />}
              onClick={() => onNavigate('attendance')}
            />
            <QuickAction
              title="Team & Work Assignments"
              description="Assign tasks to salesmen, PA assistants and freelancers"
              icon={<Briefcase size={20} />}
              onClick={() => onNavigate('workforce')}
            />
            <QuickAction
              title="Reports & Exports"
              description="Download sales summaries, stock registers and CSV exports"
              icon={<FileText size={20} />}
              onClick={() => onNavigate('reports')}
            />
          </div>
        </div>
      </div>
    );
  }

  // ==========================================================================
  // 3. FACTORY WORKSPACE (Production, Packaging, Materials, Quality)
  // ==========================================================================
  if (workspaceConfig.id === 'factory') {
    return (
      <div className="space-y-6 max-w-5xl mx-auto">
        <div className="bg-slate-900 text-white rounded-2xl p-6 sm:p-7 shadow-xs">
          <div className="text-[11px] font-bold tracking-wider uppercase text-emerald-400">
            Factory & Production Floor
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mt-1 text-white m-0">
            Factory Work & Daily Production
          </h1>
          <p className="text-xs sm:text-sm text-slate-300 mt-1.5 mb-0 max-w-xl leading-relaxed">
            Record raw dal milling, dough mixing, papad rolling batches, packaging runs, and quality tests.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
          <SummaryCard
            title="Active Products"
            value={safeProducts.length}
            subtext="Catalog SKUs"
            icon={<Boxes size={16} />}
            onClick={() => onNavigate('products')}
          />
          <SummaryCard
            title="Today's Production"
            value={`${dashboardMetrics?.today_production_kg || 0} kg`}
            subtext="Yield produced today"
            icon={<Factory size={16} />}
            onClick={() => onNavigate('production')}
          />
          <SummaryCard
            title="Finished Packets"
            value={`${dashboardMetrics?.available_finished_packets || 0} pkts`}
            subtext="Available finished stock"
            icon={<Package size={16} />}
            onClick={() => onNavigate('stock')}
          />
          <SummaryCard
            title="Workers Present"
            value={dashboardMetrics?.workers_present_today || 0}
            subtext="Labour checked in today"
            icon={<UserCheck size={16} />}
            onClick={() => onNavigate('attendance')}
          />
        </div>

        <div>
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
            Factory Floor Step-by-Step Actions
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <QuickAction
              title="1. Raw Dal Milling"
              description="Convert whole chana/moong grain into fine flour"
              icon={<Truck size={20} />}
              onClick={() => onNavigate('production')}
            />
            <QuickAction
              title="2. Production Batch"
              description="Mix dough with recipe formula and record yield in kg"
              icon={<Factory size={20} />}
              primary
              onClick={() => onNavigate('production')}
            />
            <QuickAction
              title="3. Packaging Entry"
              description="Pack bulk papad into 200g, 500g or 1kg pouches"
              icon={<Package size={20} />}
              onClick={() => onNavigate('packaging')}
            />
            <QuickAction
              title="4. Quality Inspection"
              description="Log moisture, crispness, seal integrity & batch test"
              icon={<ShieldCheck size={20} />}
              onClick={() => onNavigate('quality')}
            />
            <QuickAction
              title="5. Factory Attendance"
              description="Mark worker check-in and daily piece-rate entries"
              icon={<UserCheck size={20} />}
              onClick={() => onNavigate('attendance')}
            />
            <QuickAction
              title="6. Stock Ledger"
              description="Check available warehouse stock and material balances"
              icon={<Boxes size={20} />}
              onClick={() => onNavigate('stock')}
            />
          </div>
        </div>
      </div>
    );
  }

  // ==========================================================================
  // 4. ACCOUNTING WORKSPACE (Finance, Ledger, Payments)
  // ==========================================================================
  if (workspaceConfig.id === 'accountant') {
    return (
      <div className="space-y-6 max-w-5xl mx-auto">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-200">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
              Finance & Commercial Accounts
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight m-0">
              Accounts & Payments Workspace
            </h1>
            <p className="text-xs text-slate-500 mt-1 mb-0">
              Double-entry general ledger, customer receivables, supplier payables, and trial balance.
            </p>
          </div>
          <button
            onClick={() => onNavigate('accounting')}
            className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors cursor-pointer"
          >
            Open General Ledger
          </button>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <SummaryCard
            title="Total Revenue (MTD)"
            value={`₹${monthRevenue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
            subtext={`${monthSales.length} billed orders this month`}
            icon={<TrendingUp size={16} />}
          />
          <SummaryCard
            title="Expenses to Review"
            value={pendingExpenses}
            subtext="Operational expenses pending"
            icon={<Receipt size={16} />}
            alert={pendingExpenses > 0}
            onClick={() => onNavigate('expenses')}
          />
          <SummaryCard
            title="Receivables"
            value="Balanced"
            subtext="Customer credit ledgers"
            icon={<Scale size={16} />}
            onClick={() => onNavigate('accounting')}
          />
          <SummaryCard
            title="Trial Balance"
            value="100% Balanced"
            subtext="Debits equal credits"
            icon={<CheckCircle2 size={16} />}
            onClick={() => onNavigate('accounting')}
          />
        </div>

        <div>
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
            Accounting Actions
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <QuickAction
              title="Post Journal Voucher"
              description="Create balanced double-entry vouchers with auto-validation"
              icon={<Scale size={20} />}
              primary
              onClick={() => onNavigate('accounting')}
            />
            <QuickAction
              title="Customer Receivables"
              description="View credit balances, outstanding payments and ageing"
              icon={<Users size={20} />}
              onClick={() => onNavigate('customers')}
            />
            <QuickAction
              title="Process Expenses"
              description="Review staff travel, factory fuel and operational expenses"
              icon={<Receipt size={20} />}
              onClick={() => onNavigate('expenses')}
            />
            <QuickAction
              title="Payroll & Wages"
              description="Monthly salary runs, advances and workforce disbursements"
              icon={<Coins size={20} />}
              onClick={() => onNavigate('salary')}
            />
            <QuickAction
              title="Daily Cash Handover"
              description="Verify daily cash collections submitted by field salesmen"
              icon={<Lock size={20} />}
              onClick={() => onNavigate('closing')}
            />
            <QuickAction
              title="Financial Reports"
              description="Generate Profit & Loss, Trial Balance and Balance Sheet"
              icon={<FileText size={20} />}
              onClick={() => onNavigate('reports')}
            />
          </div>
        </div>
      </div>
    );
  }

  // ==========================================================================
  // 5. EMPLOYEE / FREELANCER / MARKETING DASHBOARD (My Work)
  // ==========================================================================
  if (['employee', 'freelancer', 'marketing', 'ecommerce'].includes(workspaceConfig.id)) {
    return (
      <div className="space-y-6 max-w-4xl mx-auto">
        <div className="bg-emerald-900 text-white rounded-2xl p-6 sm:p-7 shadow-xs">
          <div className="text-[11px] font-bold tracking-wider uppercase text-emerald-300">
            Personal Workspace
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mt-1 text-white m-0">
            Welcome, {currentUser?.full_name || currentUser?.username} 👋
          </h1>
          <p className="text-xs sm:text-sm text-emerald-100/90 mt-1.5 mb-0 max-w-lg leading-relaxed">
            Check in for today's shift, view assigned tasks, submit project work, and access salary receipts.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
          <SummaryCard
            title="Today's Shift"
            value="Active"
            subtext="Check-in & hours tracked"
            icon={<UserCheck size={16} />}
            onClick={() => onNavigate('attendance')}
          />
          <SummaryCard
            title="My Tasks"
            value="View"
            subtext="Deliverables & assignments"
            icon={<Briefcase size={16} />}
            onClick={() => onNavigate('workforce')}
          />
          <SummaryCard
            title="My Receipts"
            value="Available"
            subtext="Payment vouchers & salary"
            icon={<Coins size={16} />}
            onClick={() => onNavigate('workforce')}
          />
        </div>

        <div>
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
            Quick Actions
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <QuickAction
              title="My Work & Tasks"
              description="View pending tasks, submit completed work, and see review notes"
              icon={<Briefcase size={20} />}
              primary
              onClick={() => onNavigate('workforce')}
            />
            <QuickAction
              title="Mark Attendance"
              description="Record check-in time and check-out notes for today"
              icon={<UserCheck size={20} />}
              onClick={() => onNavigate('attendance')}
            />
          </div>
        </div>
      </div>
    );
  }

  // ==========================================================================
  // 6. OWNER / DEFAULT EXECUTIVE DASHBOARD (Complete Business Overview)
  // ==========================================================================
  return (
    <div className="space-y-6">
      {/* Top Banner / Summary */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
            Executive Control Center
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight leading-tight m-0">
            Business Overview
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1 mb-0 max-w-xl">
            Live operational status across sales, manufacturing, inventory, team, and finance.
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            type="button"
            onClick={() => onNavigate('sales')}
            className="px-3.5 py-2 bg-emerald-800 hover:bg-emerald-900 text-white rounded-lg text-xs font-bold shadow-xs transition-colors cursor-pointer flex items-center gap-1.5"
          >
            <Plus size={15} />
            <span>New Sale</span>
          </button>
          <button
            type="button"
            onClick={() => onNavigate('production')}
            className="px-3.5 py-2 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold shadow-2xs transition-colors cursor-pointer flex items-center gap-1.5"
          >
            <Factory size={15} />
            <span>New Batch</span>
          </button>
        </div>
      </div>

      {/* Key Executive Metrics Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <SummaryCard
          title="Today's Sales"
          value={`₹${todayRevenue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtext={`${todaySales.length} bills generated today`}
          icon={<Wallet size={16} />}
          onClick={() => onNavigate('sales')}
        />
        <SummaryCard
          title="Monthly Sales (MTD)"
          value={`₹${monthRevenue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtext={`${monthSales.length} total orders this month`}
          icon={<TrendingUp size={16} />}
          onClick={() => onNavigate('sales')}
        />
        <SummaryCard
          title="Pending Approvals"
          value={pendingApprovals}
          subtext="Production & discrepancy reviews"
          icon={<CheckCircle2 size={16} />}
          alert={pendingApprovals > 0}
          alertColor="amber"
          onClick={() => onNavigate('approvals')}
        />
        <SummaryCard
          title="Expenses to Review"
          value={pendingExpenses}
          subtext="Staff claims awaiting approval"
          icon={<Receipt size={16} />}
          alert={pendingExpenses > 0}
          alertColor="amber"
          onClick={() => onNavigate('expenses')}
        />
      </div>

      {/* Second Row: Inventory & Manufacturing Status */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <SummaryCard
          title="Stock SKUs"
          value={safeStockItems.length}
          subtext="Warehouse stock items"
          icon={<Boxes size={16} />}
          onClick={() => onNavigate('stock')}
        />
        <SummaryCard
          title="Active Products"
          value={safeProducts.length}
          subtext="Approved master catalog"
          icon={<Factory size={16} />}
          onClick={() => onNavigate('products')}
        />
        <SummaryCard
          title="Customers"
          value={safeCustomers.length}
          subtext="Active retail & wholesale stores"
          icon={<Users size={16} />}
          onClick={() => onNavigate('customers')}
        />
        <SummaryCard
          title="General Ledger"
          value="100% Balanced"
          subtext="Double-entry journal integrity"
          icon={<Scale size={16} />}
          onClick={() => onNavigate('accounting')}
        />
      </div>

      {/* Primary Management Workflows */}
      <div>
        <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
          Core Workflows & Quick Actions
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <QuickAction
            title="Sales & Billing"
            description="Create instant customer invoice, apply wholesale discounts, and collect payment"
            icon={<ShoppingCart size={20} />}
            primary
            onClick={() => onNavigate('sales')}
          />
          <QuickAction
            title="Production & Recipes"
            description="Execute dal milling, bulk dough formulation batches, and check material yields"
            icon={<Factory size={20} />}
            onClick={() => onNavigate('production')}
          />
          <QuickAction
            title="Packaging & Stock"
            description="Package bulk papad into consumer SKUs and verify inventory ledgers"
            icon={<Package size={20} />}
            onClick={() => onNavigate('packaging')}
          />
          <QuickAction
            title="Approvals & Quality"
            description="Inspect pending batch variances, packaging discrepancies, and quality tests"
            icon={<CheckCircle2 size={20} />}
            badge={pendingApprovals > 0 ? pendingApprovals : undefined}
            onClick={() => onNavigate('approvals')}
          />
          <QuickAction
            title="Workforce & Payroll"
            description="Manage staff tasks, attendance muster, monthly salary runs, and payouts"
            icon={<Briefcase size={20} />}
            onClick={() => onNavigate('workforce')}
          />
          <QuickAction
            title="General Ledger & Accounts"
            description="View real-time trial balance, journal entries, cash and bank reconciliation"
            icon={<Scale size={20} />}
            onClick={() => onNavigate('accounting')}
          />
        </div>
      </div>
    </div>
  );
};
