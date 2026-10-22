import React from 'react';
import { useStore } from '../context/StoreContext';
import { ViewType } from '../components/Navigation';

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
  const todayRevenue = Number(dashboardMetrics?.today_sales ?? todaySales.reduce((sum, s) => sum + (Number(s?.bill_total) || 0), 0) ?? 0);
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

  if (isSalesman) {
    // Stage 7: Mobile-first field salesman workspace
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
      <div>
        <div className="field-hero">
          <div>
            <p className="eyebrow">KAWAD SWAD · FIELD SALES</p>
            <h1>Namaste, {currentUser?.full_name || 'Salesman'} 👋</h1>
            <p>
              Today's work, in one place. Save each visit and record every sale and expense before closing
              your day.
            </p>
          </div>
          <span className="field-pill">
            {new Date().toLocaleDateString('en-IN', {
              weekday: 'short',
              day: 'numeric',
              month: 'short',
            })}
          </span>
        </div>

        {/* Salesman Live Progress Tracker for today */}
        <div className="grid" style={{ marginBottom: '16px' }}>
          <div className="metric">
            <span>Today's Visits</span>
            <strong>{todayVisits.length}</strong>
          </div>
          <div className="metric">
            <span>Today's Bills</span>
            <strong>{myTodaySales.length}</strong>
          </div>
          <div className="metric">
            <span>Today's Sales Total</span>
            <strong>₹{myTodaySalesRevenue.toFixed(2)}</strong>
          </div>
        </div>

        <div className="field-actions">
          <button className="field-action primary" onClick={() => onNavigate('sales')}>
            <span className="action-icon">₹</span>
            <strong>New sale</strong>
            <small>Create a bill and record payment</small>
          </button>

          <button className="field-action" onClick={() => onNavigate('visits')}>
            <span className="action-icon">⌖</span>
            <strong>Record shop visit</strong>
            <small>Log outcome and next follow-up</small>
          </button>

          <button className="field-action" onClick={() => onNavigate('customers')}>
            <span className="action-icon">＋</span>
            <strong>Add customer</strong>
            <small>Register a shop or retailer</small>
          </button>

          <button className="field-action" onClick={() => onNavigate('expenses')}>
            <span className="action-icon">▤</span>
            <strong>Submit expense</strong>
            <small>Send expense for approval</small>
          </button>

          <button className="field-action" onClick={() => onNavigate('stock')}>
            <span className="action-icon">▦</span>
            <strong>My stock</strong>
            <small>View available stock and movements</small>
          </button>

          <button className="field-action" onClick={() => onNavigate('closing')}>
            <span className="action-icon">✓</span>
            <strong>Daily closing</strong>
            <small>Reconcile cash & submit closing</small>
          </button>
        </div>

        <div className="card field-checklist">
          <h2>Daily field checklist</h2>

          <div className="check-row">
            <span>01</span>
            <div>
              <strong>Visit shops</strong>
              <small>Record the visit outcome and follow-up date for every retailer.</small>
            </div>
            <button className="secondary" onClick={() => onNavigate('visits')}>
              Open
            </button>
          </div>

          <div className="check-row">
            <span>02</span>
            <div>
              <strong>Record paid sales</strong>
              <small>Confirm the full payment before issuing each bill.</small>
            </div>
            <button className="secondary" onClick={() => onNavigate('sales')}>
              Open
            </button>
          </div>

          <div className="check-row">
            <span>03</span>
            <div>
              <strong>Submit expenses</strong>
              <small>Only approved cash expenses reduce cash due back at evening closing.</small>
            </div>
            <button className="secondary" onClick={() => onNavigate('expenses')}>
              Open
            </button>
          </div>

          <div className="check-row">
            <span>04</span>
            <div>
              <strong>Submit daily closing</strong>
              <small>Reconcile physical cash with expected collections before closing your shift.</small>
            </div>
            <button className="secondary" onClick={() => onNavigate('closing')}>
              Open
            </button>
          </div>

          <div className="field-note">
            Keep bills, payment references, stock movements and expenses accurate. Do not record the same
            sale twice.
          </div>
        </div>
      </div>
    );
  }

  // Owner / PA View
  return (
    <div>
      <div className="toolbar">
        <h1>Management Dashboard</h1>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="secondary" onClick={() => onNavigate('reports')}>
            View Monthly Reports
          </button>
          <button onClick={() => onNavigate('sales')}>+ New Bill</button>
        </div>
      </div>

      <div className="grid">
        <div className="metric">
          <span>Today’s bills</span>
          <strong>{todayBills}</strong>
        </div>
        <div className="metric">
          <span>Today’s revenue</span>
          <strong>₹{todayRevenue.toFixed(2)}</strong>
        </div>
        <div className="metric">
          <span>Today’s Papad Sold</span>
          <strong>{typeof dashboardMetrics?.today_kg_sold === 'number' ? `${dashboardMetrics.today_kg_sold.toFixed(1)} kg` : '0.0 kg'}</strong>
        </div>
        <div className="metric">
          <span>Today’s Production</span>
          <strong style={{ color: '#166534' }}>{(dashboardMetrics?.today_production_kg ?? 0).toFixed(1)} kg</strong>
        </div>
        <div className="metric">
          <span>Available Finished Stock</span>
          <strong style={{ color: '#0369a1' }}>{(dashboardMetrics?.available_finished_packets ?? 0).toLocaleString()} pkts</strong>
        </div>
        <div className="metric">
          <span>Floor Attendance Today</span>
          <strong>
            {dashboardMetrics?.workers_present_today ?? 0} / {dashboardMetrics?.active_workers_count ?? 0} Present
          </strong>
        </div>
        <div className="metric">
          <span>Month bills</span>
          <strong>{monthBills}</strong>
        </div>
        <div className="metric">
          <span>Month revenue</span>
          <strong>₹{monthRevenue.toFixed(2)}</strong>
        </div>
        <div className="metric">
          <span>Month Papad Sold</span>
          <strong>{typeof dashboardMetrics?.monthly_kg_sold === 'number' ? `${dashboardMetrics.monthly_kg_sold.toFixed(1)} kg` : '0.0 kg'}</strong>
        </div>
        <div className="metric">
          <span>Today's Cash Collected</span>
          <strong>₹{(dashboardMetrics?.today_cash || 0).toFixed(2)}</strong>
        </div>
        <div className="metric">
          <span>Today's Digital (UPI/Bank)</span>
          <strong>₹{(dashboardMetrics?.digital_collections_today || 0).toFixed(2)}</strong>
        </div>
        <div className="metric">
          <span>Pending expenses</span>
          <strong style={{ color: pendingExpensesCount > 0 ? '#b42318' : '#183b35' }}>
            {pendingExpensesCount}
          </strong>
        </div>
        <div className="metric">
          <span>Pending closings</span>
          <strong style={{ color: pendingClosingsCount > 0 ? '#b42318' : '#183b35' }}>
            {pendingClosingsCount}
          </strong>
        </div>
        {(dashboardMetrics?.pending_production_approvals || 0) > 0 && (
          <div className="metric" style={{ background: '#ecfdf5', borderColor: '#a7f3d0' }}>
            <span style={{ color: '#047857' }}>Production Approvals</span>
            <strong style={{ color: '#047857' }}>
              {dashboardMetrics?.pending_production_approvals} ({(dashboardMetrics?.pending_production_kg || 0).toFixed(1)} kg)
            </strong>
          </div>
        )}
        {(dashboardMetrics?.zero_stock_items_count || 0) > 0 && (
          <div className="metric" style={{ background: '#fef2f2', borderColor: '#fca5a5' }}>
            <span style={{ color: '#b91c1c' }}>Zero Stock SKUs</span>
            <strong style={{ color: '#b91c1c' }}>{dashboardMetrics?.zero_stock_items_count} items</strong>
          </div>
        )}
        {(dashboardMetrics?.pending_discrepancies || 0) > 0 && (
          <div className="metric" style={{ background: '#fef2f2', borderColor: '#fca5a5' }}>
            <span style={{ color: '#b91c1c' }}>Stock Discrepancies</span>
            <strong style={{ color: '#b91c1c' }}>{dashboardMetrics?.pending_discrepancies}</strong>
          </div>
        )}
        {(dashboardMetrics?.incomplete_transactions_count || 0) > 0 && (
          <div className="metric" style={{ background: '#fffbeb', borderColor: '#fcd34d' }}>
            <span style={{ color: '#b45309' }}>Incomplete Bills</span>
            <strong style={{ color: '#b45309' }}>{dashboardMetrics?.incomplete_transactions_count}</strong>
          </div>
        )}
      </div>

      {/* Summary cards for quick actions */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
        <div className="card">
          <h2>Quick Actions</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {(dashboardMetrics?.pending_production_approvals || 0) > 0 && (
              <button
                className="secondary"
                style={{ justifyContent: 'flex-start', padding: '12px', borderColor: '#10b981', background: '#ecfdf5', color: '#065f46', fontWeight: 600 }}
                onClick={() => onNavigate('approvals')}
              >
                🏭 Review Pending Production Batches ({dashboardMetrics?.pending_production_approvals})
              </button>
            )}
            <button
              className="secondary"
              style={{ justifyContent: 'flex-start', padding: '12px' }}
              onClick={() => onNavigate('production')}
            >
              🏭 Record Daily Production (Bulk Papad)
            </button>
            <button
              className="secondary"
              style={{ justifyContent: 'flex-start', padding: '12px' }}
              onClick={() => onNavigate('attendance')}
            >
              👥 Mark Floor Worker Attendance
            </button>
            <button
              className="secondary"
              style={{ justifyContent: 'flex-start', padding: '12px' }}
              onClick={() => onNavigate('packaging')}
            >
              📦 Record Packaging (Packets from Bulk)
            </button>
            <button
              className="secondary"
              style={{ justifyContent: 'flex-start', padding: '12px' }}
              onClick={() => onNavigate('sales')}
            >
              📄 Issue New Sale & Generate Bill
            </button>
            <button
              className="secondary"
              style={{ justifyContent: 'flex-start', padding: '12px' }}
              onClick={() => onNavigate('stock')}
            >
              📦 Finished Goods Register & Inventory
            </button>
            <button
              className="secondary"
              style={{ justifyContent: 'flex-start', padding: '12px' }}
              onClick={() => onNavigate('expenses')}
            >
              💰 Review Pending Expenses ({pendingExpensesCount})
            </button>
            <button
              className="secondary"
              style={{ justifyContent: 'flex-start', padding: '12px' }}
              onClick={() => onNavigate('closing')}
            >
              🔒 Review Salesman Daily Cash Closings ({pendingClosingsCount})
            </button>
          </div>
        </div>

        <div className="card">
          <h2>Today's Key Highlights</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.9rem' }}>
            <p>
              <strong>Date:</strong>{' '}
              {new Date().toLocaleDateString('en-IN', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric',
              })}
            </p>
            <p>
              <strong>Active Customers in Directory:</strong> {safeCustomers.filter((c) => c && (c.active === true || String(c.active).toLowerCase() === 'true')).length}
            </p>
            <p>
              <strong>Total Stock Ledger Movements:</strong> {safeTransactions.length}
            </p>
            <p className="muted" style={{ marginTop: '8px' }}>
              All sales transactions automatically reflect full payment verification. No partial credit is
              allowed per business rules.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
