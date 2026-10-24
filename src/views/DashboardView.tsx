import React from 'react';
import { useStore } from '../context/StoreContext';
import { ViewType } from '../components/Navigation';
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
} from 'lucide-react';

interface DashboardViewProps {
  onNavigate: (view: ViewType) => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({ onNavigate }) => {
  const {
    currentUser,
    sales,
    expenses,
    dailyClosings,
    stockTransactions,
    customers,
    shopVisits,
    dashboardMetrics,
    isLoading,
    isRefreshing,
  } = useStore();

  const isSalesman = currentUser?.role === 'SALESMAN';
  const todayStr = new Date().toISOString().slice(0, 10);
  const currentMonthStr = todayStr.slice(0, 7);

  const safeSales = Array.isArray(sales) ? sales : [];
  const safeExpenses = Array.isArray(expenses) ? expenses : [];
  const safeClosings = Array.isArray(dailyClosings) ? dailyClosings : [];
  const safeCustomers = Array.isArray(customers) ? customers : [];
  const safeTransactions = Array.isArray(stockTransactions) ? stockTransactions : [];
  const safeVisits = Array.isArray(shopVisits) ? shopVisits : [];

  // Metrics for Owner/PA using backend dashboard data or live ledger records
  const todaySales = safeSales.filter(
    (s) => String(s?.sale_datetime || '').slice(0, 10) === todayStr && s?.bill_status === 'ISSUED'
  );
  const monthSales = safeSales.filter(
    (s) => String(s?.sale_datetime || '').slice(0, 7) === currentMonthStr && s?.bill_status === 'ISSUED'
  );

  const todayBills = Number(dashboardMetrics?.total_bills_today ?? todaySales.length ?? 0);
  const todayRevenue = Number(
    dashboardMetrics?.today_sales ??
    todaySales.reduce((sum, s) => sum + (Number(s?.bill_total) || 0), 0) ??
    0
  );
  const monthBills = Number(monthSales.length || 0);
  const monthRevenue = Number(monthSales.reduce((sum, s) => sum + (Number(s?.bill_total) || 0), 0) || 0);

  const pendingExpensesCount = Number(
    dashboardMetrics?.pending_expenses ??
    safeExpenses.filter((e) => e && String(e.approval_status || '').toUpperCase() === 'PENDING').length ??
    0
  );
  const pendingClosingsCount = Number(
    safeClosings.filter((c) => c && String(c.closing_status || '').toUpperCase() === 'SUBMITTED').length ??
    0
  );

  const pendingApprovals = Number(dashboardMetrics?.pending_production_approvals || 0);
  const zeroStockCount = Number(dashboardMetrics?.zero_stock_items_count || 0);
  const pendingDiscrepancies = Number(dashboardMetrics?.pending_discrepancies || 0);

  if (isSalesman) {
    // Mobile-first field salesman workspace
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
    const myTodaySalesRevenue = myTodaySales.reduce((sum, s) => sum + (Number(s?.bill_total) || 0), 0);

    return (
      <div className="space-y-6">
        {/* Salesman Hero Banner */}
        <div className="bg-gradient-to-br from-emerald-900 to-emerald-800 text-white rounded-2xl p-6 sm:p-8 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="text-[11px] font-bold tracking-widest uppercase text-emerald-300">
                Kawad Swad · Field Operations
              </div>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight mt-1 mb-2">
                Namaste, {currentUser?.full_name || 'Salesman'} 👋
              </h1>
              <p className="text-xs sm:text-sm text-emerald-100/90 max-w-xl leading-relaxed m-0">
                Record each shop visit, generate verified sales bills with instant payments, and reconcile cash before day-end closing.
              </p>
            </div>
            <div className="shrink-0 bg-white/10 backdrop-blur-xs border border-white/20 rounded-xl px-4 py-2.5 text-center sm:text-right">
              <div className="text-[11px] text-emerald-200 font-semibold uppercase tracking-wider">Today's Date</div>
              <div className="text-sm font-bold text-white">
                {new Date().toLocaleDateString('en-IN', {
                  weekday: 'short',
                  day: 'numeric',
                  month: 'short',
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Live Daily Progress Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
            <div className="flex items-center justify-between text-slate-500 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider">Shops Visited Today</span>
              <MapPin size={16} className="text-emerald-700" />
            </div>
            <div className="text-2xl font-black text-slate-900">{todayVisits.length}</div>
            <div className="text-[11px] text-slate-500 mt-1">Retail outlets visited & logged</div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
            <div className="flex items-center justify-between text-slate-500 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider">Bills Issued</span>
              <Receipt size={16} className="text-emerald-700" />
            </div>
            <div className="text-2xl font-black text-slate-900">{myTodaySales.length}</div>
            <div className="text-[11px] text-slate-500 mt-1">Sales completed today</div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
            <div className="flex items-center justify-between text-slate-500 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider">Sales Revenue</span>
              <Wallet size={16} className="text-emerald-700" />
            </div>
            <div className="text-2xl font-black text-emerald-800">₹{myTodaySalesRevenue.toFixed(2)}</div>
            <div className="text-[11px] text-slate-500 mt-1">Total billing value</div>
          </div>
        </div>

        {/* Quick Action Tap Targets */}
        <div>
          <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider mb-3">Field Actions</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <button
              onClick={() => onNavigate('sales')}
              className="flex flex-col items-start p-4 bg-emerald-50/80 hover:bg-emerald-100/80 border border-emerald-200 rounded-xl text-left transition-all shadow-xs cursor-pointer group"
            >
              <div className="w-10 h-10 rounded-lg bg-emerald-700 text-white flex items-center justify-center font-bold text-base mb-2 group-hover:scale-105 transition-transform">
                ₹
              </div>
              <strong className="text-sm font-bold text-emerald-950">New Sale</strong>
              <small className="text-xs text-emerald-800/80 mt-0.5">Generate bill & record payment</small>
            </button>

            <button
              onClick={() => onNavigate('visits')}
              className="flex flex-col items-start p-4 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-left transition-all shadow-xs cursor-pointer group"
            >
              <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-base mb-2 group-hover:scale-105 transition-transform">
                <MapPin size={20} />
              </div>
              <strong className="text-sm font-bold text-slate-900">Record Visit</strong>
              <small className="text-xs text-slate-500 mt-0.5">Log shop interaction & notes</small>
            </button>

            <button
              onClick={() => onNavigate('customers')}
              className="flex flex-col items-start p-4 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-left transition-all shadow-xs cursor-pointer group"
            >
              <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-base mb-2 group-hover:scale-105 transition-transform">
                <Users size={20} />
              </div>
              <strong className="text-sm font-bold text-slate-900">Add Customer</strong>
              <small className="text-xs text-slate-500 mt-0.5">Register a new retail shop</small>
            </button>

            <button
              onClick={() => onNavigate('stock')}
              className="flex flex-col items-start p-4 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-left transition-all shadow-xs cursor-pointer group"
            >
              <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-base mb-2 group-hover:scale-105 transition-transform">
                <Boxes size={20} />
              </div>
              <strong className="text-sm font-bold text-slate-900">My Stock</strong>
              <small className="text-xs text-slate-500 mt-0.5">View packets in your vehicle</small>
            </button>

            <button
              onClick={() => onNavigate('expenses')}
              className="flex flex-col items-start p-4 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-left transition-all shadow-xs cursor-pointer group"
            >
              <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-base mb-2 group-hover:scale-105 transition-transform">
                <Receipt size={20} />
              </div>
              <strong className="text-sm font-bold text-slate-900">Submit Expense</strong>
              <small className="text-xs text-slate-500 mt-0.5">Fuel, meals, transport claims</small>
            </button>

            <button
              onClick={() => onNavigate('closing')}
              className="flex flex-col items-start p-4 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl text-left transition-all shadow-xs cursor-pointer group"
            >
              <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-base mb-2 group-hover:scale-105 transition-transform">
                <CheckCircle2 size={20} />
              </div>
              <strong className="text-sm font-bold text-slate-900">Daily Closing</strong>
              <small className="text-xs text-slate-500 mt-0.5">Reconcile cash & day-end handover</small>
            </button>
          </div>
        </div>

        {/* Daily Checklist Card */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <div>
              <h2 className="text-base font-bold text-slate-900 m-0">Daily Shift Checklist</h2>
              <p className="text-xs text-slate-500 m-0">Follow standard sequence to ensure balanced ledger accounts.</p>
            </div>
          </div>

          <div className="divide-y divide-slate-100">
            <div className="py-3 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-emerald-100 text-emerald-800 text-xs font-bold flex items-center justify-center shrink-0">
                  1
                </div>
                <div>
                  <div className="text-xs font-bold text-slate-900">Visit Retail Outlets</div>
                  <div className="text-[11px] text-slate-500">Record visit status and orders for each store.</div>
                </div>
              </div>
              <button
                onClick={() => onNavigate('visits')}
                className="px-3 py-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 hover:bg-emerald-100 rounded-lg transition-colors cursor-pointer"
              >
                Open
              </button>
            </div>

            <div className="py-3 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-emerald-100 text-emerald-800 text-xs font-bold flex items-center justify-center shrink-0">
                  2
                </div>
                <div>
                  <div className="text-xs font-bold text-slate-900">Collect Full Payments</div>
                  <div className="text-[11px] text-slate-500">Verify Cash or UPI reference before handing over goods.</div>
                </div>
              </div>
              <button
                onClick={() => onNavigate('sales')}
                className="px-3 py-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 hover:bg-emerald-100 rounded-lg transition-colors cursor-pointer"
              >
                Open
              </button>
            </div>

            <div className="py-3 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-emerald-100 text-emerald-800 text-xs font-bold flex items-center justify-center shrink-0">
                  3
                </div>
                <div>
                  <div className="text-xs font-bold text-slate-900">Submit Approved Expenses</div>
                  <div className="text-[11px] text-slate-500">Approved cash expenses safely offset cash due back.</div>
                </div>
              </div>
              <button
                onClick={() => onNavigate('expenses')}
                className="px-3 py-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 hover:bg-emerald-100 rounded-lg transition-colors cursor-pointer"
              >
                Open
              </button>
            </div>

            <div className="py-3 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-emerald-100 text-emerald-800 text-xs font-bold flex items-center justify-center shrink-0">
                  4
                </div>
                <div>
                  <div className="text-xs font-bold text-slate-900">Submit Daily Closing</div>
                  <div className="text-[11px] text-slate-500">Enter cash in hand and submit for owner review.</div>
                </div>
              </div>
              <button
                onClick={() => onNavigate('closing')}
                className="px-3 py-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 hover:bg-emerald-100 rounded-lg transition-colors cursor-pointer"
              >
                Open
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Management / Owner / PA Overview View
  return (
    <div className="space-y-6">
      {/* Header Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight m-0">
            Operations & Performance Dashboard
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Real-time sales, production yield, stock levels, and factory attendance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onNavigate('reports')}
            className="px-3.5 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition-colors shadow-2xs"
          >
            Monthly Reports
          </button>
          <button
            onClick={() => onNavigate('sales')}
            className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-white bg-emerald-800 hover:bg-emerald-900 rounded-lg transition-colors shadow-2xs"
          >
            <ShoppingCart size={14} />
            <span>+ New Bill</span>
          </button>
        </div>
      </div>

      {/* Critical Attention Banners (if pending items exist) */}
      {(pendingApprovals > 0 || zeroStockCount > 0 || pendingDiscrepancies > 0 || pendingExpensesCount > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {pendingApprovals > 0 && (
            <div
              onClick={() => onNavigate('approvals')}
              className="p-3 bg-amber-50 border border-amber-200 rounded-xl flex items-center justify-between cursor-pointer hover:bg-amber-100/70 transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <Clock size={16} className="text-amber-700" />
                <div>
                  <div className="text-xs font-bold text-amber-900">Production Batches</div>
                  <div className="text-[11px] text-amber-700">{pendingApprovals} awaiting approval</div>
                </div>
              </div>
              <ArrowRight size={14} className="text-amber-700" />
            </div>
          )}

          {pendingExpensesCount > 0 && (
            <div
              onClick={() => onNavigate('expenses')}
              className="p-3 bg-amber-50 border border-amber-200 rounded-xl flex items-center justify-between cursor-pointer hover:bg-amber-100/70 transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <Receipt size={16} className="text-amber-700" />
                <div>
                  <div className="text-xs font-bold text-amber-900">Pending Expenses</div>
                  <div className="text-[11px] text-amber-700">{pendingExpensesCount} claims to review</div>
                </div>
              </div>
              <ArrowRight size={14} className="text-amber-700" />
            </div>
          )}

          {zeroStockCount > 0 && (
            <div
              onClick={() => onNavigate('stock')}
              className="p-3 bg-red-50 border border-red-200 rounded-xl flex items-center justify-between cursor-pointer hover:bg-red-100/70 transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <AlertTriangle size={16} className="text-red-700" />
                <div>
                  <div className="text-xs font-bold text-red-900">Zero Stock SKUs</div>
                  <div className="text-[11px] text-red-700">{zeroStockCount} items out of stock</div>
                </div>
              </div>
              <ArrowRight size={14} className="text-red-700" />
            </div>
          )}

          {pendingDiscrepancies > 0 && (
            <div
              onClick={() => onNavigate('stock')}
              className="p-3 bg-red-50 border border-red-200 rounded-xl flex items-center justify-between cursor-pointer hover:bg-red-100/70 transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <ShieldAlert size={16} className="text-red-700" />
                <div>
                  <div className="text-xs font-bold text-red-900">Stock Discrepancies</div>
                  <div className="text-[11px] text-red-700">{pendingDiscrepancies} variance audits</div>
                </div>
              </div>
              <ArrowRight size={14} className="text-red-700" />
            </div>
          )}
        </div>
      )}

      {/* Primary KPI Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Today's Revenue */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">Today's Revenue</span>
            <TrendingUp size={16} className="text-emerald-700" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-slate-900">
            ₹{todayRevenue.toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            {todayBills} bill{todayBills === 1 ? '' : 's'} issued today
          </div>
        </div>

        {/* Today's Production Yield */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">Today's Production</span>
            <Factory size={16} className="text-emerald-700" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-emerald-800">
            {(dashboardMetrics?.today_production_kg ?? 0).toFixed(1)} kg
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Bulk dried papad output
          </div>
        </div>

        {/* Finished Goods Packets */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">Available Finished Goods</span>
            <Boxes size={16} className="text-blue-700" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-slate-900">
            {(dashboardMetrics?.available_finished_packets ?? 0).toLocaleString()} pkts
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Across factory & warehouse
          </div>
        </div>

        {/* Floor Attendance */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">Factory Attendance</span>
            <UserCheck size={16} className="text-emerald-700" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-slate-900">
            {dashboardMetrics?.workers_present_today ?? 0} / {dashboardMetrics?.active_workers_count ?? 0}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Workers on floor today
          </div>
        </div>

        {/* Month Revenue */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">Month Revenue</span>
            <Calendar size={16} className="text-slate-500" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-slate-900">
            ₹{monthRevenue.toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            {monthBills} bills this month
          </div>
        </div>

        {/* Month Papad Sold (kg) */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">Month Volume Sold</span>
            <TrendingUp size={16} className="text-slate-500" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-slate-900">
            {typeof dashboardMetrics?.monthly_kg_sold === 'number'
              ? `${dashboardMetrics.monthly_kg_sold.toFixed(1)} kg`
              : '0.0 kg'}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Total commercial volume
          </div>
        </div>

        {/* Today's Cash Collections */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">Cash Collected Today</span>
            <Wallet size={16} className="text-amber-700" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-slate-900">
            ₹{(dashboardMetrics?.today_cash || 0).toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Physical currency received
          </div>
        </div>

        {/* Today's Digital Collections */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">UPI / Bank Collected</span>
            <Smartphone size={16} className="text-blue-700" />
          </div>
          <div className="text-xl sm:text-2xl font-black text-slate-900">
            ₹{(dashboardMetrics?.digital_collections_today || 0).toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Direct account transfers
          </div>
        </div>
      </div>

      {/* Two Column Section: Quick Actions & Operational Context */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Quick Operations Matrix */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <h2 className="text-base font-bold text-slate-900 m-0">Core Factory Workflows</h2>
            <span className="text-xs text-slate-400 font-medium">Quick Routes</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <button
              onClick={() => onNavigate('production')}
              className="flex items-center gap-3 p-3 text-left rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/50 transition-colors group cursor-pointer"
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0">
                <Factory size={16} />
              </div>
              <div>
                <div className="text-xs font-bold text-slate-900 group-hover:text-emerald-900">Daily Production</div>
                <div className="text-[10px] text-slate-500">Record raw batches & yields</div>
              </div>
            </button>

            <button
              onClick={() => onNavigate('attendance')}
              className="flex items-center gap-3 p-3 text-left rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/50 transition-colors group cursor-pointer"
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0">
                <Users size={16} />
              </div>
              <div>
                <div className="text-xs font-bold text-slate-900 group-hover:text-emerald-900">Floor Attendance</div>
                <div className="text-[10px] text-slate-500">Mark workers & wages</div>
              </div>
            </button>

            <button
              onClick={() => onNavigate('packaging')}
              className="flex items-center gap-3 p-3 text-left rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/50 transition-colors group cursor-pointer"
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0">
                <Boxes size={16} />
              </div>
              <div>
                <div className="text-xs font-bold text-slate-900 group-hover:text-emerald-900">Packaging Register</div>
                <div className="text-[10px] text-slate-500">Bulk to packet conversion</div>
              </div>
            </button>

            <button
              onClick={() => onNavigate('stock')}
              className="flex items-center gap-3 p-3 text-left rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/50 transition-colors group cursor-pointer"
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0">
                <TrendingUp size={16} />
              </div>
              <div>
                <div className="text-xs font-bold text-slate-900 group-hover:text-emerald-900">Finished Goods</div>
                <div className="text-[10px] text-slate-500">Stock audit & transfers</div>
              </div>
            </button>

            <button
              onClick={() => onNavigate('sales')}
              className="flex items-center gap-3 p-3 text-left rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/50 transition-colors group cursor-pointer"
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0">
                <ShoppingCart size={16} />
              </div>
              <div>
                <div className="text-xs font-bold text-slate-900 group-hover:text-emerald-900">Sales Invoicing</div>
                <div className="text-[10px] text-slate-500">Issue bills & PDF exports</div>
              </div>
            </button>

            <button
              onClick={() => onNavigate('closing')}
              className="flex items-center gap-3 p-3 text-left rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/50 transition-colors group cursor-pointer"
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0">
                <CheckCircle2 size={16} />
              </div>
              <div>
                <div className="text-xs font-bold text-slate-900 group-hover:text-emerald-900">Daily Cash Closing</div>
                <div className="text-[10px] text-slate-500">Reconcile field cash</div>
              </div>
            </button>
          </div>
        </div>

        {/* Operational Context Card */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <h2 className="text-base font-bold text-slate-900 m-0">Business Directory & Health</h2>
            <span className="text-xs text-slate-400 font-medium">Master Ledger</span>
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between py-2 border-b border-slate-100">
              <span className="text-slate-600 font-medium">Active Retail Customers:</span>
              <span className="font-bold text-slate-900">
                {safeCustomers.filter((c) => c && (c.active === true || String(c.active).toLowerCase() === 'true')).length} shops
              </span>
            </div>

            <div className="flex items-center justify-between py-2 border-b border-slate-100">
              <span className="text-slate-600 font-medium">Recorded Stock Movements:</span>
              <span className="font-bold text-slate-900">{safeTransactions.length} movements</span>
            </div>

            <div className="flex items-center justify-between py-2 border-b border-slate-100">
              <span className="text-slate-600 font-medium">Payment Verification Rule:</span>
              <span className="font-semibold text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded-md">
                100% Cash / Digital Settled
              </span>
            </div>

            <div className="p-3 bg-slate-50 rounded-xl text-slate-500 text-[11px] leading-relaxed">
              Every production batch, packaging conversion, and sale movement is persistently logged to Google Sheets with automated audit trails.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
