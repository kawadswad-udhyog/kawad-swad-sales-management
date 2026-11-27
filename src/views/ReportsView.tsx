import React, { useState, useEffect, useCallback } from 'react';
import { useStore } from '../context/StoreContext';
import { Payment, ReportTabPayload } from '../types';
import { fetchV2OfficialReport } from '../services/api';

type OfficialReportSlug = 'trial-balance' | 'stock-status' | 'sales-receivables';

export const ReportsView: React.FC = () => {
  const {
    sales,
    customers,
    products,
    expenses,
    dailyClosings,
    salaryIncentives,
    stockTransactions,
    auditLogs,
    payments,
  } = useStore();

  const currentYearMonth = new Date().toISOString().slice(0, 7);
  const [selectedMonth, setSelectedMonth] = useState(currentYearMonth);
  const [exportNotice, setExportNotice] = useState<string | null>(null);

  const [officialSlug, setOfficialSlug] = useState<OfficialReportSlug>('trial-balance');
  const [officialReport, setOfficialReport] = useState<ReportTabPayload | null>(null);
  const [officialLoading, setOfficialLoading] = useState(false);
  const [officialError, setOfficialError] = useState<string | null>(null);

  const loadOfficialReport = useCallback(async (slug: OfficialReportSlug) => {
    setOfficialLoading(true);
    setOfficialError(null);
    try {
      const payload = await fetchV2OfficialReport(slug);
      setOfficialReport(payload);
    } catch (err: unknown) {
      setOfficialReport(null);
      setOfficialError(err instanceof Error ? err.message : 'Unable to fetch official report.');
    } finally {
      setOfficialLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOfficialReport(officialSlug);
  }, [officialSlug, loadOfficialReport]);

  // Filter sales for the selected month
  const monthSales = sales.filter(
    (s) => String(s?.sale_datetime || '').slice(0, 7) === selectedMonth && s.bill_status === 'ISSUED'
  );

  const totalBills = monthSales.length;
  const totalRevenue = monthSales.reduce((sum, s) => sum + s.bill_total, 0);

  // Breakdown by sales type
  const bySalesType: Record<string, { bills: number; revenue: number }> = {};
  for (const s of monthSales) {
    const type = s.sales_type || 'UNKNOWN';
    if (!bySalesType[type]) {
      bySalesType[type] = { bills: 0, revenue: 0 };
    }
    bySalesType[type].bills += 1;
    bySalesType[type].revenue += s.bill_total;
  }

  // Payment methods breakdown for the month
  const monthSaleIds = new Set(monthSales.map((s) => s.sale_id));
  const monthPayments = payments.filter((p: Payment) => monthSaleIds.has(p.sale_id));
  const paymentBreakdown: Record<string, { count: number; total: number }> = {
    CASH: { count: 0, total: 0 },
    UPI: { count: 0, total: 0 },
    BANK_TRANSFER: { count: 0, total: 0 },
    OTHER: { count: 0, total: 0 },
  };
  for (const p of monthPayments) {
    const method = p.payment_method || 'OTHER';
    if (!paymentBreakdown[method]) {
      paymentBreakdown[method] = { count: 0, total: 0 };
    }
    paymentBreakdown[method].count += 1;
    paymentBreakdown[method].total += p.amount;
  }

  // Expense breakdown for the month
  const monthExpenses = expenses.filter((e) => String(e?.expense_datetime || '').slice(0, 7) === selectedMonth);
  const expenseStatusBreakdown: Record<string, { count: number; total: number }> = {
    APPROVED: { count: 0, total: 0 },
    PENDING: { count: 0, total: 0 },
    REJECTED: { count: 0, total: 0 },
  };
  for (const e of monthExpenses) {
    const status = e.approval_status || 'PENDING';
    if (!expenseStatusBreakdown[status]) {
      expenseStatusBreakdown[status] = { count: 0, total: 0 };
    }
    expenseStatusBreakdown[status].count += 1;
    expenseStatusBreakdown[status].total += e.amount;
  }

  // Product-wise breakdown from month sales lines
  const productBreakdown: Record<string, { sku: string; name: string; qty: number; qualifyingKg: number; revenue: number }> = {};
  for (const s of monthSales) {
    for (const item of s.lines || []) {
      const pid = item.product_id;
      if (!productBreakdown[pid]) {
        productBreakdown[pid] = {
          sku: item.sku_snapshot,
          name: item.product_name_snapshot,
          qty: 0,
          qualifyingKg: 0,
          revenue: 0,
        };
      }
      productBreakdown[pid].qty += item.quantity;
      productBreakdown[pid].qualifyingKg += item.qualifying_kg;
      productBreakdown[pid].revenue += item.line_total;
    }
  }

  // Salesman breakdown
  const salesmanBreakdown: Record<string, { bills: number; revenue: number }> = {};
  for (const s of monthSales) {
    const sm = s.salesman_user_id || s.entered_by_user_id || 'COMPANY';
    if (!salesmanBreakdown[sm]) {
      salesmanBreakdown[sm] = { bills: 0, revenue: 0 };
    }
    salesmanBreakdown[sm].bills += 1;
    salesmanBreakdown[sm].revenue += s.bill_total;
  }

  // Handle export actions
  const handleExport = async (sheet: string) => {
    try {
      const { exportSheetToExcel } = await import('../utils/exportToExcel');
      if (sheet === 'Sales') {
        const data = sales.map((s) => ({
          sale_id: s.sale_id,
          bill_number: s.bill_number,
          sale_datetime: s.sale_datetime,
          sales_type: s.sales_type,
          customer_id: s.customer_id || 'CUS-WALKIN',
          customer_name_snapshot: (s.customer_name_snapshot && s.customer_name_snapshot !== 'None')
            ? s.customer_name_snapshot
            : 'Walk-in Customer',
          entered_by_user_id: s.entered_by_user_id,
          salesman_user_id: s.salesman_user_id,
          delivery_status: s.delivery_status,
          payment_status: s.payment_status,
          subtotal: s.subtotal,
          discount_amount: s.discount_amount,
          tax_amount: s.tax_amount,
          bill_total: s.bill_total,
          bill_status: s.bill_status,
          created_at: s.created_at,
          notes: s.notes,
        }));
        await exportSheetToExcel('Sales', data);
      } else if (sheet === 'Products') {
        await exportSheetToExcel('Products', products);
      } else if (sheet === 'Customers') {
        await exportSheetToExcel('Customers', customers);
      } else if (sheet === 'Expenses') {
        await exportSheetToExcel('Expenses', expenses);
      } else if (sheet === 'SalesmanStockLedger') {
        await exportSheetToExcel('SalesmanStockLedger', stockTransactions);
      } else if (sheet === 'DailyClosing') {
        await exportSheetToExcel('DailyClosing', dailyClosings);
      } else if (sheet === 'SalaryIncentives') {
        await exportSheetToExcel('SalaryIncentives', salaryIncentives);
      } else if (sheet === 'AuditLog') {
        await exportSheetToExcel('AuditLog', auditLogs);
      }
      setExportNotice(`Successfully exported ${sheet}.xlsx`);
      setTimeout(() => setExportNotice(null), 3500);
    } catch (e: unknown) {
      setExportNotice(`Failed to export: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  };

  const sheetsToExport = [
    'Sales',
    'Products',
    'Customers',
    'Expenses',
    'SalesmanStockLedger',
    'DailyClosing',
    'SalaryIncentives',
    'AuditLog',
  ];

  return (
    <div>
      <h1>Reports &amp; Excel Exports</h1>

      {exportNotice && <div className="notice-success">{exportNotice}</div>}

      {/* OFFICIAL SHEET-BACKED REPORTS (RPT_TrialBalance, RPT_StockStatus, RPT_SalesAndReceivables) */}
      <div className="card" style={{ borderLeft: '4px solid #0f2c23' }}>
        <div className="toolbar">
          <div>
            <h2 style={{ margin: 0 }}>Official Sheet-Backed Reports (Authoritative)</h2>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Bound directly to <code>RPT_TrialBalance</code>, <code>RPT_StockStatus</code>, and <code>RPT_SalesAndReceivables</code> in Google Sheets.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
            {[
              { slug: 'trial-balance', label: 'RPT_TrialBalance' },
              { slug: 'stock-status', label: 'RPT_StockStatus' },
              { slug: 'sales-receivables', label: 'RPT_SalesAndReceivables' },
            ].map((item) => (
              <button
                key={item.slug}
                type="button"
                className={officialSlug === item.slug ? 'primary' : 'secondary'}
                onClick={() => setOfficialSlug(item.slug as OfficialReportSlug)}
                style={{ fontWeight: 600 }}
              >
                {item.label}
              </button>
            ))}
            <button
              type="button"
              className="secondary"
              disabled={officialLoading}
              onClick={() => loadOfficialReport(officialSlug)}
            >
              {officialLoading ? 'Loading…' : '↻ Reload Official Tab'}
            </button>
          </div>
        </div>

        {officialError && (
          <div className="notice-error" style={{ marginTop: '12px' }}>
            <strong>Official Report Unavailable:</strong> {officialError}
          </div>
        )}

        {officialReport && (() => {
          const officialRows = Array.isArray(officialReport.rows) ? officialReport.rows : [];
          const officialCols = officialRows.length > 0 && officialRows[0] && typeof officialRows[0] === 'object'
            ? Object.keys(officialRows[0]).slice(0, 8)
            : [];
          return (
          <div style={{ marginTop: '14px' }}>
            <div className="grid">
              <div className="metric">
                <span>Source Tab</span>
                <strong style={{ fontSize: '1rem' }}><code>{officialReport.source_tab || 'UNKNOWN'}</code></strong>
              </div>
              <div className="metric">
                <span>Period / Generated At</span>
                <strong style={{ fontSize: '0.95rem' }}>
                  {officialReport.period || 'CURRENT'} {officialReport.generated_at ? `· ${officialReport.generated_at}` : ''}
                </strong>
              </div>
              <div className="metric">
                <span>Balance / Status</span>
                <strong
                  style={{
                    color:
                      officialReport.balance_status === 'BALANCED'
                        ? '#15803d'
                        : officialReport.balance_status === 'UNBALANCED' || officialReport.status === 'UNAVAILABLE'
                        ? '#b91c1c'
                        : '#0f172a',
                  }}
                >
                  {officialReport.balance_status || officialReport.status || 'UNKNOWN'}
                </strong>
              </div>
              <div className="metric">
                <span>Rows ({officialReport.row_count ?? officialRows.length})</span>
                <strong style={{ fontSize: '0.95rem' }}>
                  {officialReport.total_debit != null || officialReport.total_credit != null
                    ? `Dr ${officialReport.total_debit || '0.00'} / Cr ${officialReport.total_credit || '0.00'}`
                    : officialReport.stale
                    ? 'STALE / EMPTY'
                    : 'LIVE SHEET ROWS'}
                </strong>
              </div>
            </div>

            {officialReport.unavailable_reason && (
              <div className="notice-error" style={{ marginTop: '12px' }}>
                <strong>Sheet State ({officialReport.status}):</strong> {officialReport.unavailable_reason}
              </div>
            )}

            {officialRows.length > 0 && officialCols.length > 0 && (
              <div className="table-wrap" style={{ marginTop: '14px' }}>
                <table>
                  <thead>
                    <tr>
                      {officialCols.map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {officialRows.map((r, idx) => (
                      <tr key={idx}>
                        {officialCols.map((col) => (
                          <td key={col}>{String((r && r[col]) ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          );
        })()}
      </div>

      <div className="card">
        <h2>Export Worksheets to Excel (.xlsx)</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Download clean Excel spreadsheets formatted with proper column widths.
        </p>
        <div className="actions" style={{ marginTop: '12px' }}>
          {sheetsToExport.map((name) => (
            <button
              key={name}
              className="secondary"
              onClick={() => handleExport(name)}
              style={{ fontWeight: 600 }}
            >
              📥 {name}.xlsx
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="toolbar">
          <div>
            <h2 style={{ margin: 0 }}>Monthly Performance Analysis — OPERATIONAL PREVIEW ONLY</h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '0.82rem' }}>
              Live Transaction Aggregation from operational collections. For official financial sign-off, use the Authoritative RPT_* tabs above.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <label style={{ margin: 0, fontSize: '0.88rem' }}>Select month:</label>
            <input
              type="month"
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              style={{ width: 'auto', margin: 0, padding: '6px 12px' }}
            />
          </div>
        </div>

        <div className="grid">
          <div className="metric">
            <span>Month Selected</span>
            <strong style={{ fontSize: '1.2rem' }}>{selectedMonth}</strong>
          </div>
          <div className="metric">
            <span>Total Issued Bills</span>
            <strong>{totalBills}</strong>
          </div>
          <div className="metric">
            <span>Total Verified Revenue</span>
            <strong style={{ color: '#176b52' }}>₹{totalRevenue.toFixed(2)}</strong>
          </div>
          <div className="metric">
            <span>Average Bill Size</span>
            <strong>
              ₹{totalBills > 0 ? (totalRevenue / totalBills).toFixed(2) : '0.00'}
            </strong>
          </div>
        </div>

        {/* Breakdown by Sales Type */}
        <h3 style={{ marginTop: '24px' }}>Breakdown by Sales Type</h3>
        <div className="table-wrap" style={{ marginBottom: '20px' }}>
          <table>
            <thead>
              <tr>
                <th>Channel / Type</th>
                <th>Bill Count</th>
                <th>Total Revenue</th>
                <th>Share of Sales</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(bySalesType).map(([type, data]) => (
                <tr key={type}>
                  <td>
                    <strong>{type}</strong>
                  </td>
                  <td>{data.bills}</td>
                  <td>₹{data.revenue.toFixed(2)}</td>
                  <td>
                    {totalRevenue > 0
                      ? `${((data.revenue / totalRevenue) * 100).toFixed(1)}%`
                      : '0%'}
                  </td>
                </tr>
              ))}
              {Object.keys(bySalesType).length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    No issued sales for {selectedMonth}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Breakdown by Product */}
        <h3>Product-wise Performance</h3>
        <div className="table-wrap" style={{ marginBottom: '20px' }}>
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Product Description</th>
                <th>Units Sold</th>
                <th>Qualifying kg</th>
                <th>Total Line Revenue</th>
              </tr>
            </thead>
            <tbody>
              {Object.values(productBreakdown).map((p) => (
                <tr key={p.sku}>
                  <td>
                    <code>{p.sku}</code>
                  </td>
                  <td>{p.name}</td>
                  <td>{p.qty}</td>
                  <td>{p.qualifyingKg.toFixed(2)} kg</td>
                  <td>
                    <strong>₹{p.revenue.toFixed(2)}</strong>
                  </td>
                </tr>
              ))}
              {Object.keys(productBreakdown).length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No product lines recorded for {selectedMonth}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Breakdown by Salesman */}
        <h3>Salesman Volume Breakdown</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Salesman / Submitter</th>
                <th>Bills Issued</th>
                <th>Total Revenue</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(salesmanBreakdown).map(([sm, data]) => (
                <tr key={sm}>
                  <td>
                    <strong>{sm}</strong>
                  </td>
                  <td>{data.bills}</td>
                  <td>₹{data.revenue.toFixed(2)}</td>
                </tr>
              ))}
              {Object.keys(salesmanBreakdown).length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    No sales recorded for {selectedMonth}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Breakdown by Payment Method */}
        <h3>Payment Method Collections</h3>
        <div className="table-wrap" style={{ marginBottom: '20px' }}>
          <table>
            <thead>
              <tr>
                <th>Payment Mode</th>
                <th>Payment Transactions</th>
                <th>Total Collected</th>
                <th>Share</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(paymentBreakdown).map(([method, data]) => (
                <tr key={method}>
                  <td>
                    <strong>{method}</strong>
                  </td>
                  <td>{data.count}</td>
                  <td>₹{data.total.toFixed(2)}</td>
                  <td>
                    {totalRevenue > 0
                      ? `${((data.total / totalRevenue) * 100).toFixed(1)}%`
                      : '0%'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Breakdown by Expense Status */}
        <h3>Field Expense Submissions</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Approval Status</th>
                <th>Expense Submissions</th>
                <th>Total Amount</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(expenseStatusBreakdown).map(([status, data]) => (
                <tr key={status}>
                  <td>
                    <span
                      className={`badge ${
                        status === 'APPROVED' ? 'approved' : status === 'REJECTED' ? 'rejected' : 'pending'
                      }`}
                    >
                      {status}
                    </span>
                  </td>
                  <td>{data.count}</td>
                  <td>
                    <strong>₹{data.total.toFixed(2)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
