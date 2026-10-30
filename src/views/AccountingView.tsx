import React, { useState, useEffect, useCallback } from 'react';
import {
  fetchChartOfAccounts,
  fetchTrialBalance,
  fetchProfitAndLoss,
  fetchBalanceSheet,
  fetchJournalVouchers,
  reverseJournalVoucherApi,
  fetchReconciliationReport,
  executeReconciliation,
  fetchOpeningBalanceProposal,
  getDebtorsBalances,
  getCreditorsBalances,
  getCashBankReport,
  getGstSummaryReport,
  AccountMaster,
  TrialBalanceResult,
  ProfitAndLossResult,
  BalanceSheetResult,
  JournalVoucherItem,
  ReconcileResult,
  OpeningBalanceProposal,
} from '../services/api';
import type {
  DebtorItem,
  CreditorItem,
  CashBankReport,
  GstSummaryReport,
} from '../types';
import { useStore } from '../context/StoreContext';
import {
  Scale,
  TrendingUp,
  Landmark,
  BookOpen,
  FileText,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Search,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  Users,
  Building,
  Coins,
  Receipt,
} from 'lucide-react';

type AccountingTab =
  | 'trial-balance'
  | 'pnl'
  | 'balance-sheet'
  | 'vouchers'
  | 'chart'
  | 'debtors'
  | 'creditors'
  | 'cash-bank'
  | 'gst-summary'
  | 'reconciliation';

export const AccountingView: React.FC = () => {
  const { currentUser } = useStore();
  const isOwnerOrAdmin = currentUser?.role === 'OWNER';

  const [activeTab, setActiveTab] = useState<AccountingTab>('trial-balance');
  const [asOfDate, setAsOfDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [startDate, setStartDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(1);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState<string>(() => new Date().toISOString().slice(0, 10));

  // Data states
  const [trialBalance, setTrialBalance] = useState<TrialBalanceResult | null>(null);
  const [pnl, setPnl] = useState<ProfitAndLossResult | null>(null);
  const [balanceSheet, setBalanceSheet] = useState<BalanceSheetResult | null>(null);
  const [vouchers, setVouchers] = useState<JournalVoucherItem[]>([]);
  const [chartOfAccounts, setChartOfAccounts] = useState<AccountMaster[]>([]);
  const [reconcileReport, setReconcileReport] = useState<ReconcileResult | null>(null);
  const [openingProposal, setOpeningProposal] = useState<OpeningBalanceProposal | null>(null);
  const [debtors, setDebtors] = useState<DebtorItem[]>([]);
  const [creditors, setCreditors] = useState<CreditorItem[]>([]);
  const [cashBank, setCashBank] = useState<CashBankReport | null>(null);
  const [gstSummary, setGstSummary] = useState<GstSummaryReport | null>(null);

  // UI state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedVoucherId, setExpandedVoucherId] = useState<string | null>(null);
  const [voucherSearch, setVoucherSearch] = useState('');
  const [voucherTypeFilter, setVoucherTypeFilter] = useState('');
  const [reconciling, setReconciling] = useState(false);
  const [reconcileSuccess, setReconcileSuccess] = useState<string | null>(null);

  // Reversal modal state
  const [reversalTarget, setReversalTarget] = useState<JournalVoucherItem | null>(null);
  const [reversalReason, setReversalReason] = useState('');
  const [reversing, setReversing] = useState(false);
  const [actionNotice, setActionNotice] = useState<{ text: string; ok: boolean } | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (activeTab === 'trial-balance') {
        const data = await fetchTrialBalance(asOfDate);
        setTrialBalance(data);
      } else if (activeTab === 'pnl') {
        const data = await fetchProfitAndLoss(startDate, endDate);
        setPnl(data);
      } else if (activeTab === 'balance-sheet') {
        const data = await fetchBalanceSheet(asOfDate);
        setBalanceSheet(data);
      } else if (activeTab === 'vouchers') {
        const data = await fetchJournalVouchers(voucherTypeFilter || undefined, 60);
        setVouchers(data);
      } else if (activeTab === 'chart') {
        const data = await fetchChartOfAccounts();
        setChartOfAccounts(data);
      } else if (activeTab === 'debtors') {
        const data = await getDebtorsBalances();
        setDebtors(data.debtors || []);
      } else if (activeTab === 'creditors') {
        const data = await getCreditorsBalances();
        setCreditors(data.creditors || []);
      } else if (activeTab === 'cash-bank') {
        const data = await getCashBankReport();
        setCashBank(data);
      } else if (activeTab === 'gst-summary') {
        const data = await getGstSummaryReport(startDate, endDate);
        setGstSummary(data);
      } else if (activeTab === 'reconciliation') {
        const [rec, op] = await Promise.all([
          fetchReconciliationReport(),
          fetchOpeningBalanceProposal(),
        ]);
        setReconcileReport(rec);
        setOpeningProposal(op);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch accounting records';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [activeTab, asOfDate, startDate, endDate, voucherTypeFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleReverseVoucher = async () => {
    if (!reversalTarget || !reversalReason.trim()) return;
    setReversing(true);
    try {
      await reverseJournalVoucherApi(reversalTarget.journal_id, reversalReason.trim());
      setActionNotice({
        text: `Journal voucher ${reversalTarget.journal_id} reversed successfully with compensating voucher.`,
        ok: true,
      });
      setReversalTarget(null);
      setReversalReason('');
      loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Reversal failed';
      setActionNotice({ text: msg, ok: false });
    } finally {
      setReversing(false);
    }
  };

  const formatCurrency = (amount: number | undefined | null) => {
    const val = Number(amount || 0);
    return `₹${val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  return (
    <div className="space-y-6">
      {/* Top Header Card */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-800 text-white flex items-center justify-center font-bold shadow-sm">
              <Scale size={20} />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900 tracking-tight">
                General Ledger & Financial Accounts
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">
                Authoritative double-entry bookkeeping, balanced trial balance, and real-time financial statements
              </p>
            </div>
          </div>
        </div>

        {/* Global Controls & Status */}
        <div className="flex items-center gap-2 self-stretch sm:self-auto flex-wrap">
          <button
            onClick={() => loadData()}
            disabled={loading}
            className="px-3.5 py-2 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors flex items-center gap-2 disabled:opacity-50"
            title="Refresh Ledger"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {actionNotice && (
        <div
          className={`p-4 rounded-xl text-xs font-semibold flex items-center justify-between border ${
            actionNotice.ok
              ? 'bg-emerald-50 text-emerald-900 border-emerald-200'
              : 'bg-rose-50 text-rose-900 border-rose-200'
          }`}
        >
          <span>{actionNotice.text}</span>
          <button
            onClick={() => setActionNotice(null)}
            className="text-slate-500 hover:text-slate-800 ml-4 font-bold"
          >
            ✕
          </button>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-center gap-3">
          <AlertTriangle size={16} className="text-amber-600 shrink-0" />
          <div className="flex-1">
            <span className="font-bold">Accounting Sync Notice:</span> {error}
          </div>
          <button
            onClick={() => loadData()}
            className="px-2.5 py-1 bg-amber-200 hover:bg-amber-300 text-amber-900 rounded-lg text-xs font-bold"
          >
            Retry
          </button>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-2 flex flex-wrap gap-1">
        <button
          onClick={() => setActiveTab('trial-balance')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'trial-balance'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <Scale size={15} />
          Trial Balance
        </button>
        <button
          onClick={() => setActiveTab('pnl')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'pnl'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <TrendingUp size={15} />
          Profit & Loss (P&L)
        </button>
        <button
          onClick={() => setActiveTab('balance-sheet')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'balance-sheet'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <Landmark size={15} />
          Balance Sheet
        </button>
        <button
          onClick={() => setActiveTab('vouchers')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'vouchers'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <BookOpen size={15} />
          Journal Vouchers
        </button>
        <button
          onClick={() => setActiveTab('chart')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'chart'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <FileText size={15} />
          Chart of Accounts
        </button>
        <button
          onClick={() => setActiveTab('debtors')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'debtors'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <Users size={15} />
          Debtors (AR)
        </button>
        <button
          onClick={() => setActiveTab('creditors')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'creditors'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <Building size={15} />
          Creditors (AP)
        </button>
        <button
          onClick={() => setActiveTab('cash-bank')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'cash-bank'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <Coins size={15} />
          Cash & Bank
        </button>
        <button
          onClick={() => setActiveTab('gst-summary')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'gst-summary'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <Receipt size={15} />
          GST Summary
        </button>
        <button
          onClick={() => setActiveTab('reconciliation')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
            activeTab === 'reconciliation'
              ? 'bg-emerald-800 text-white shadow-sm'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <RotateCcw size={15} />
          Audit & Reconciliation
        </button>
      </div>

      {/* TAB 1: TRIAL BALANCE */}
      {activeTab === 'trial-balance' && (
        <div className="space-y-4">
          {/* Controls Bar */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <label className="text-xs font-bold text-slate-700">As of Date:</label>
              <input
                type="date"
                value={asOfDate}
                onChange={(e) => setAsOfDate(e.target.value)}
                className="px-3 py-1.5 border border-slate-300 rounded-xl text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-600"
              />
            </div>

            {trialBalance && (
              <div className="flex items-center gap-2">
                {trialBalance.is_balanced ? (
                  <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-100 text-emerald-800 rounded-full text-xs font-bold border border-emerald-300">
                    <CheckCircle2 size={14} className="text-emerald-700" />
                    Trial Balance Equal (Debits == Credits)
                  </div>
                ) : (
                  <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-rose-100 text-rose-800 rounded-full text-xs font-bold border border-rose-300 animate-pulse">
                    <AlertTriangle size={14} className="text-rose-700" />
                    Unbalanced: Diff {formatCurrency(trialBalance.difference)}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Metric Cards */}
          {trialBalance && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  Total Debit Volume
                </span>
                <div className="text-xl font-extrabold text-slate-900 mt-1">
                  {formatCurrency(trialBalance.grand_total_debit)}
                </div>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  Total Credit Volume
                </span>
                <div className="text-xl font-extrabold text-slate-900 mt-1">
                  {formatCurrency(trialBalance.grand_total_credit)}
                </div>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  Net Balance Variance
                </span>
                <div
                  className={`text-xl font-extrabold mt-1 ${
                    trialBalance.difference === 0 ? 'text-emerald-700' : 'text-rose-600'
                  }`}
                >
                  {formatCurrency(trialBalance.difference)}
                </div>
              </div>
            </div>
          )}

          {/* Trial Balance Table */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-100 border-b border-slate-200 text-slate-700 font-bold uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Code</th>
                    <th className="px-4 py-3">Account Title</th>
                    <th className="px-4 py-3">Category</th>
                    <th className="px-4 py-3 text-right">Debit (₹)</th>
                    <th className="px-4 py-3 text-right">Credit (₹)</th>
                    <th className="px-4 py-3 text-right">Net Debit (₹)</th>
                    <th className="px-4 py-3 text-right">Net Credit (₹)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-medium text-slate-800">
                  {trialBalance?.rows && trialBalance.rows.length > 0 ? (
                    trialBalance.rows.map((row) => (
                      <tr key={row.account_code} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-2.5 font-mono font-bold text-slate-600">
                          {row.account_code}
                        </td>
                        <td className="px-4 py-2.5 font-semibold text-slate-900">
                          {row.account_name}
                        </td>
                        <td className="px-4 py-2.5">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              row.account_type === 'ASSET'
                                ? 'bg-sky-100 text-sky-800'
                                : row.account_type === 'LIABILITY'
                                ? 'bg-amber-100 text-amber-800'
                                : row.account_type === 'EQUITY'
                                ? 'bg-purple-100 text-purple-800'
                                : row.account_type === 'REVENUE'
                                ? 'bg-emerald-100 text-emerald-800'
                                : 'bg-rose-100 text-rose-800'
                            }`}
                          >
                            {row.account_type}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-slate-600">
                          {row.total_debit > 0 ? formatCurrency(row.total_debit) : '—'}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-slate-600">
                          {row.total_credit > 0 ? formatCurrency(row.total_credit) : '—'}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold text-slate-900">
                          {row.net_debit > 0 ? formatCurrency(row.net_debit) : '—'}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold text-slate-900">
                          {row.net_credit > 0 ? formatCurrency(row.net_credit) : '—'}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-slate-500 italic">
                        {loading ? 'Compiling general ledger balances…' : 'No posted journal vouchers recorded yet.'}
                      </td>
                    </tr>
                  )}
                </tbody>
                {trialBalance && (
                  <tfoot className="bg-slate-50 border-t-2 border-slate-300 font-extrabold text-slate-900">
                    <tr>
                      <td colSpan={3} className="px-4 py-3 text-right uppercase tracking-wider">
                        Grand Totals
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-700">
                        {formatCurrency(
                          trialBalance.rows.reduce((sum, r) => sum + r.total_debit, 0)
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-700">
                        {formatCurrency(
                          trialBalance.rows.reduce((sum, r) => sum + r.total_credit, 0)
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-900 bg-emerald-50">
                        {formatCurrency(trialBalance.grand_total_debit)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-900 bg-emerald-50">
                        {formatCurrency(trialBalance.grand_total_credit)}
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: PROFIT & LOSS */}
      {activeTab === 'pnl' && (
        <div className="space-y-4">
          {/* Date Range Selector */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 flex flex-col sm:flex-row items-start sm:items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs font-bold text-slate-700">Period From:</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="px-3 py-1.5 border border-slate-300 rounded-xl text-xs font-semibold"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs font-bold text-slate-700">To:</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="px-3 py-1.5 border border-slate-300 rounded-xl text-xs font-semibold"
              />
            </div>
          </div>

          {pnl && (
            <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
              <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                <span className="text-[11px] font-bold text-slate-500 uppercase">Gross Revenue</span>
                <div className="text-xl font-extrabold text-slate-900 mt-1">
                  {formatCurrency(pnl.total_revenue)}
                </div>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                <span className="text-[11px] font-bold text-slate-500 uppercase">Cost of Goods Sold</span>
                <div className="text-xl font-extrabold text-rose-700 mt-1">
                  {formatCurrency(pnl.total_cogs)}
                </div>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                <span className="text-[11px] font-bold text-slate-500 uppercase">Gross Profit</span>
                <div className="text-xl font-extrabold text-emerald-800 mt-1">
                  {formatCurrency(pnl.gross_profit)}
                  <span className="text-xs font-semibold text-slate-500 ml-2">
                    ({pnl.gross_margin_percentage}%)
                  </span>
                </div>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                <span className="text-[11px] font-bold text-slate-500 uppercase">Net Operating Profit</span>
                <div
                  className={`text-xl font-extrabold mt-1 ${
                    pnl.net_operating_profit >= 0 ? 'text-emerald-800' : 'text-rose-700'
                  }`}
                >
                  {formatCurrency(pnl.net_operating_profit)}
                  <span className="text-xs font-semibold text-slate-500 ml-2">
                    ({pnl.net_margin_percentage}%)
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Detailed Statement Table */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-6">
            <div>
              <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider mb-2 border-b pb-1">
                1. Operating Revenue
              </h3>
              <div className="space-y-1 text-xs">
                {pnl?.revenue_breakdown?.map((r) => (
                  <div key={r.account_code} className="flex justify-between py-1">
                    <span className="text-slate-700 font-medium">
                      {r.account_code} - {r.account_name}
                    </span>
                    <span className="font-mono font-bold text-slate-900">
                      {formatCurrency(r.net_credit)}
                    </span>
                  </div>
                ))}
                <div className="flex justify-between py-1.5 font-bold border-t border-slate-200 text-slate-900">
                  <span>Total Operating Revenue</span>
                  <span>{formatCurrency(pnl?.total_revenue)}</span>
                </div>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider mb-2 border-b pb-1">
                2. Direct Cost of Goods Sold (COGS)
              </h3>
              <div className="space-y-1 text-xs">
                {pnl?.cogs_breakdown?.map((r) => (
                  <div key={r.account_code} className="flex justify-between py-1">
                    <span className="text-slate-700 font-medium">
                      {r.account_code} - {r.account_name}
                    </span>
                    <span className="font-mono font-bold text-rose-700">
                      {formatCurrency(r.net_debit)}
                    </span>
                  </div>
                ))}
                <div className="flex justify-between py-1.5 font-bold border-t border-slate-200 text-slate-900">
                  <span>Total Cost of Goods Sold</span>
                  <span className="text-rose-700">{formatCurrency(pnl?.total_cogs)}</span>
                </div>
              </div>
            </div>

            <div className="p-3 bg-emerald-50 rounded-xl flex justify-between items-center text-sm font-extrabold text-emerald-900">
              <span>GROSS PROFIT (Revenue − COGS)</span>
              <span>{formatCurrency(pnl?.gross_profit)} ({pnl?.gross_margin_percentage}%)</span>
            </div>

            <div>
              <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider mb-2 border-b pb-1">
                3. Operating Expenses
              </h3>
              <div className="space-y-1 text-xs">
                {pnl?.operating_expenses_breakdown && pnl.operating_expenses_breakdown.length > 0 ? (
                  pnl.operating_expenses_breakdown.map((r) => (
                    <div key={r.account_code} className="flex justify-between py-1">
                      <span className="text-slate-700 font-medium">
                        {r.account_code} - {r.account_name}
                      </span>
                      <span className="font-mono font-bold text-slate-800">
                        {formatCurrency(r.net_debit)}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="text-slate-400 italic py-1">No operating expenses posted for this period.</div>
                )}
                <div className="flex justify-between py-1.5 font-bold border-t border-slate-200 text-slate-900">
                  <span>Total Operating Expenses</span>
                  <span>{formatCurrency(pnl?.total_operating_expenses)}</span>
                </div>
              </div>
            </div>

            <div className="p-4 bg-slate-900 rounded-xl flex justify-between items-center text-sm font-extrabold text-white">
              <span>NET OPERATING PROFIT (Gross Profit − Expenses)</span>
              <span className="text-emerald-400">{formatCurrency(pnl?.net_operating_profit)}</span>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: BALANCE SHEET */}
      {activeTab === 'balance-sheet' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <label className="text-xs font-bold text-slate-700">As of Date:</label>
              <input
                type="date"
                value={asOfDate}
                onChange={(e) => setAsOfDate(e.target.value)}
                className="px-3 py-1.5 border border-slate-300 rounded-xl text-xs font-semibold"
              />
            </div>

            {balanceSheet && (
              <div className="flex items-center gap-2">
                {balanceSheet.is_balanced ? (
                  <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-100 text-emerald-800 rounded-full text-xs font-bold border border-emerald-300">
                    <CheckCircle2 size={14} className="text-emerald-700" />
                    Balance Sheet Balanced: Assets == Liabilities + Equity
                  </div>
                ) : (
                  <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-rose-100 text-rose-800 rounded-full text-xs font-bold border border-rose-300">
                    <AlertTriangle size={14} className="text-rose-700" />
                    Difference: {formatCurrency(balanceSheet.balance_difference)}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left: Assets */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-4">
              <div className="flex justify-between items-center border-b pb-2">
                <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                  Assets (1000 - 1999)
                </h3>
                <span className="text-xs font-mono font-extrabold text-emerald-800">
                  {formatCurrency(balanceSheet?.total_assets)}
                </span>
              </div>
              <div className="space-y-2 text-xs">
                {balanceSheet?.assets_breakdown?.map((r) => (
                  <div key={r.account_code} className="flex justify-between py-1 border-b border-slate-50">
                    <div>
                      <span className="font-mono text-slate-500 mr-2">{r.account_code}</span>
                      <span className="text-slate-800 font-medium">{r.account_name}</span>
                    </div>
                    <span className="font-mono font-bold text-slate-900">
                      {formatCurrency(r.net_debit || r.total_debit - r.total_credit)}
                    </span>
                  </div>
                ))}
              </div>
              <div className="p-3 bg-slate-50 rounded-xl flex justify-between items-center text-xs font-extrabold text-slate-900">
                <span>TOTAL ASSETS</span>
                <span className="font-mono">{formatCurrency(balanceSheet?.total_assets)}</span>
              </div>
            </div>

            {/* Right: Liabilities & Equity */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-6">
              {/* Liabilities */}
              <div>
                <div className="flex justify-between items-center border-b pb-2 mb-2">
                  <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                    Liabilities (2000 - 2999)
                  </h3>
                  <span className="text-xs font-mono font-extrabold text-amber-800">
                    {formatCurrency(balanceSheet?.total_liabilities)}
                  </span>
                </div>
                <div className="space-y-2 text-xs">
                  {balanceSheet?.liabilities_breakdown?.map((r) => (
                    <div key={r.account_code} className="flex justify-between py-1 border-b border-slate-50">
                      <div>
                        <span className="font-mono text-slate-500 mr-2">{r.account_code}</span>
                        <span className="text-slate-800 font-medium">{r.account_name}</span>
                      </div>
                      <span className="font-mono font-bold text-slate-900">
                        {formatCurrency(r.net_credit || r.total_credit - r.total_debit)}
                      </span>
                    </div>
                  ))}
                  <div className="flex justify-between py-1 font-bold text-slate-800">
                    <span>Total Liabilities</span>
                    <span>{formatCurrency(balanceSheet?.total_liabilities)}</span>
                  </div>
                </div>
              </div>

              {/* Equity */}
              <div>
                <div className="flex justify-between items-center border-b pb-2 mb-2">
                  <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                    Owner Equity (3000 - 3999)
                  </h3>
                  <span className="text-xs font-mono font-extrabold text-purple-800">
                    {formatCurrency(
                      (balanceSheet?.total_equity || 0) + (balanceSheet?.current_period_net_profit || 0)
                    )}
                  </span>
                </div>
                <div className="space-y-2 text-xs">
                  {balanceSheet?.equity_breakdown?.map((r) => (
                    <div key={r.account_code} className="flex justify-between py-1 border-b border-slate-50">
                      <div>
                        <span className="font-mono text-slate-500 mr-2">{r.account_code}</span>
                        <span className="text-slate-800 font-medium">{r.account_name}</span>
                      </div>
                      <span className="font-mono font-bold text-slate-900">
                        {formatCurrency(r.net_credit || r.total_credit - r.total_debit)}
                      </span>
                    </div>
                  ))}
                  <div className="flex justify-between py-1 text-emerald-800 font-semibold">
                    <span>Current Operating Surplus / Net Profit</span>
                    <span className="font-mono font-bold">
                      {formatCurrency(balanceSheet?.current_period_net_profit)}
                    </span>
                  </div>
                </div>
              </div>

              <div className="p-3 bg-slate-900 text-white rounded-xl flex justify-between items-center text-xs font-extrabold">
                <span>TOTAL LIABILITIES & EQUITY</span>
                <span className="font-mono text-emerald-400">
                  {formatCurrency(balanceSheet?.total_liabilities_and_equity)}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: JOURNAL VOUCHERS */}
      {activeTab === 'vouchers' && (
        <div className="space-y-4">
          {/* Filter Bar */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 flex flex-col sm:flex-row gap-3 items-center justify-between">
            <div className="flex items-center gap-3 w-full sm:w-auto">
              <div className="relative flex-1 sm:w-64">
                <Search size={14} className="absolute left-3 top-3 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search voucher ID or narration..."
                  value={voucherSearch}
                  onChange={(e) => setVoucherSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 border border-slate-300 rounded-xl text-xs font-semibold"
                />
              </div>
              <select
                value={voucherTypeFilter}
                onChange={(e) => setVoucherTypeFilter(e.target.value)}
                className="px-3 py-2 border border-slate-300 rounded-xl text-xs font-semibold"
              >
                <option value="">All Voucher Types</option>
                <option value="PURCHASE">PURCHASE</option>
                <option value="MANUFACTURING">MANUFACTURING</option>
                <option value="SALES">SALES</option>
                <option value="RECEIPT">RECEIPT</option>
                <option value="PAYMENT">PAYMENT</option>
                <option value="REVERSAL">REVERSAL</option>
              </select>
            </div>

            <div className="text-xs text-slate-500 font-medium">
              Showing {vouchers.length} vouchers
            </div>
          </div>

          {/* Vouchers List */}
          <div className="space-y-3">
            {vouchers
              .filter((v) => {
                const q = voucherSearch.toLowerCase();
                return (
                  !q ||
                  v.journal_id.toLowerCase().includes(q) ||
                  v.narration.toLowerCase().includes(q) ||
                  v.reference_id.toLowerCase().includes(q)
                );
              })
              .map((v) => {
                const isExpanded = expandedVoucherId === v.journal_id;
                const isReversed = v.status === 'REVERSED';
                return (
                  <div
                    key={v.journal_id}
                    className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden"
                  >
                    <div
                      onClick={() => setExpandedVoucherId(isExpanded ? null : v.journal_id)}
                      className="p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 cursor-pointer hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <button className="text-slate-400">
                          {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        </button>
                        <div>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono font-bold text-slate-900 text-xs">
                              {v.journal_id}
                            </span>
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                v.voucher_type === 'PURCHASE'
                                  ? 'bg-blue-100 text-blue-800'
                                  : v.voucher_type === 'MANUFACTURING'
                                  ? 'bg-purple-100 text-purple-800'
                                  : v.voucher_type === 'SALES'
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : v.voucher_type === 'RECEIPT'
                                  ? 'bg-cyan-100 text-cyan-800'
                                  : v.voucher_type === 'REVERSAL'
                                  ? 'bg-rose-100 text-rose-800'
                                  : 'bg-amber-100 text-amber-800'
                              }`}
                            >
                              {v.voucher_type}
                            </span>
                            {isReversed && (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-200 text-slate-700">
                                REVERSED
                              </span>
                            )}
                            <span className="text-[11px] text-slate-500 font-medium">
                              Ref: {v.reference_type} #{v.reference_id}
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 mt-1 font-medium">{v.narration}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-4 self-end sm:self-center">
                        <div className="text-right">
                          <span className="text-[10px] font-bold text-slate-400 block uppercase">
                            Balanced Volume
                          </span>
                          <span className="font-mono font-bold text-slate-900 text-xs">
                            {formatCurrency(v.total_debit)}
                          </span>
                        </div>
                        {isOwnerOrAdmin && !isReversed && v.voucher_type !== 'REVERSAL' && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setReversalTarget(v);
                            }}
                            className="px-2.5 py-1 text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 rounded-lg transition-colors flex items-center gap-1 border border-rose-200"
                            title="Generate compensating reversal voucher"
                          >
                            <RotateCcw size={12} />
                            Reverse
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Expanded Lines */}
                    {isExpanded && (
                      <div className="border-t border-slate-100 bg-slate-50 p-4">
                        <table className="w-full text-xs">
                          <thead className="text-[10px] font-bold text-slate-500 uppercase tracking-wider text-left border-b border-slate-200">
                            <tr>
                              <th className="py-2">Line</th>
                              <th className="py-2">Account Code & Title</th>
                              <th className="py-2 text-right">Debit</th>
                              <th className="py-2 text-right">Credit</th>
                              <th className="py-2 pl-4">Narration / Notes</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100 font-medium text-slate-800">
                            {v.lines?.map((line) => (
                              <tr key={line.line_id}>
                                <td className="py-2 text-slate-400 font-mono">#{line.line_no}</td>
                                <td className="py-2 font-semibold">
                                  <span className="font-mono text-slate-500 mr-2">
                                    {line.account_code}
                                  </span>
                                  {line.account_name}
                                </td>
                                <td className="py-2 text-right font-mono">
                                  {line.debit_amount > 0 ? formatCurrency(line.debit_amount) : '—'}
                                </td>
                                <td className="py-2 text-right font-mono">
                                  {line.credit_amount > 0 ? formatCurrency(line.credit_amount) : '—'}
                                </td>
                                <td className="py-2 pl-4 text-slate-500">{line.notes || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="mt-3 text-[11px] text-slate-400 flex justify-between">
                          <span>Posted by: {v.posted_by}</span>
                          <span>Timestamp: {v.posted_at}</span>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* TAB 5: CHART OF ACCOUNTS MASTER */}
      {activeTab === 'chart' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <div className="p-4 border-b border-slate-100">
            <h2 className="text-sm font-bold text-slate-900">Standard 23-Account Chart of Accounts</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Standardized 4-digit accounting structure governing all Kawad Swad industrial production and trade
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-100 border-b border-slate-200 text-slate-700 font-bold uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-3">Code</th>
                  <th className="px-4 py-3">Account Title</th>
                  <th className="px-4 py-3">Category</th>
                  <th className="px-4 py-3">Normal Balance</th>
                  <th className="px-4 py-3">Description & Operational Role</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-800">
                {chartOfAccounts.map((acc) => (
                  <tr key={acc.account_code} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-mono font-bold text-slate-700">
                      {acc.account_code}
                    </td>
                    <td className="px-4 py-2.5 font-semibold text-slate-900">
                      {acc.account_name}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          acc.account_type === 'ASSET'
                            ? 'bg-sky-100 text-sky-800'
                            : acc.account_type === 'LIABILITY'
                            ? 'bg-amber-100 text-amber-800'
                            : acc.account_type === 'EQUITY'
                            ? 'bg-purple-100 text-purple-800'
                            : acc.account_type === 'REVENUE'
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {acc.account_type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-bold font-mono text-slate-600">
                      {acc.normal_balance}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 max-w-md">
                      {acc.description}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 6: RECONCILIATION & AUDIT */}
      {activeTab === 'reconciliation' && (
        <div className="space-y-6">
          {/* Top Actions */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <RotateCcw className="text-emerald-800" size={18} />
                Operational vs General Ledger Reconciliation
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Audits raw materials, production batches, packaging, sales invoices, and collections against double-entry journal vouchers.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  setReconciling(true);
                  fetchReconciliationReport()
                    .then(setReconcileReport)
                    .catch((err) => setError(err.message))
                    .finally(() => setReconciling(false));
                }}
                disabled={reconciling || loading}
                className="px-4 py-2 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors disabled:opacity-50"
              >
                {reconciling ? 'Auditing…' : 'Run Dry-Run Audit'}
              </button>
              <button
                onClick={async () => {
                  try {
                    setReconciling(true);
                    setError(null);
                    setReconcileSuccess(null);
                    const res = await executeReconciliation(false);
                    setReconcileReport(res);
                    setReconcileSuccess(`Reconciled ${res.reconciled_count} operational events successfully.`);
                  } catch (err: unknown) {
                    setError(err instanceof Error ? err.message : 'Reconciliation failed.');
                  } finally {
                    setReconciling(false);
                  }
                }}
                disabled={reconciling || loading}
                className="px-4 py-2 text-xs font-bold text-white bg-emerald-800 hover:bg-emerald-900 rounded-xl transition-colors disabled:opacity-50 flex items-center gap-1.5 shadow-sm"
              >
                <CheckCircle2 size={14} />
                {reconciling ? 'Backfilling…' : 'Execute Backfill'}
              </button>
            </div>
          </div>

          {reconcileSuccess && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-900 text-xs rounded-xl flex items-center gap-2">
              <CheckCircle2 size={16} className="text-emerald-700" />
              <span>{reconcileSuccess}</span>
            </div>
          )}

          {/* Metrics Overview */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-white p-4 rounded-2xl shadow-sm border border-slate-200">
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block">
                Unposted Operational Events
              </span>
              <span className="text-2xl font-black text-slate-900 mt-1 block">
                {reconcileReport?.missing_count ?? 0}
              </span>
              <span className="text-[11px] text-slate-500 mt-0.5 block">
                Transactions without journal vouchers
              </span>
            </div>
            <div className="bg-white p-4 rounded-2xl shadow-sm border border-slate-200">
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block">
                Reconciled Vouchers
              </span>
              <span className="text-2xl font-black text-emerald-800 mt-1 block">
                {reconcileReport?.reconciled_count ?? 0}
              </span>
              <span className="text-[11px] text-slate-500 mt-0.5 block">
                Successfully posted this session
              </span>
            </div>
            <div className="bg-white p-4 rounded-2xl shadow-sm border border-slate-200">
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block">
                Audit Discrepancies
              </span>
              <span className="text-2xl font-black text-rose-700 mt-1 block">
                {reconcileReport?.error_count ?? 0}
              </span>
              <span className="text-[11px] text-slate-500 mt-0.5 block">
                Processing exceptions / errors
              </span>
            </div>
          </div>

          {/* Unposted Events List */}
          {reconcileReport?.missing_events && reconcileReport.missing_events.length > 0 && (
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
              <div className="p-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
                <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                  Unposted Events Queue ({reconcileReport.missing_events.length})
                </h3>
              </div>
              <div className="divide-y divide-slate-100">
                {reconcileReport.missing_events.map((evt, idx) => (
                  <div key={idx} className="p-3.5 flex items-center justify-between text-xs hover:bg-slate-50">
                    <div>
                      <div className="font-semibold text-slate-900">{evt.description}</div>
                      <div className="text-[11px] text-slate-500 font-mono mt-0.5">
                        Table: {evt.source_table} | Ref: {evt.reference_type}:{evt.reference_id} | Date: {evt.date}
                      </div>
                    </div>
                    <span className="px-2 py-0.5 bg-amber-100 text-amber-900 rounded text-[10px] font-bold">
                      Pending Voucher
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Opening Balance Proposal Section */}
          {openingProposal && (
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 space-y-4">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 border-b border-slate-100 pb-3">
                <div>
                  <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                    <Landmark className="text-purple-700" size={16} />
                    Opening Balance Derived Proposal (Assets = Liabilities + Equity)
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {openingProposal.note}
                  </p>
                </div>
                <span
                  className={`px-3 py-1 rounded-full text-xs font-black ${
                    openingProposal.balance_check === 'BALANCED'
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-rose-100 text-rose-800'
                  }`}
                >
                  {openingProposal.balance_check}
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 bg-slate-50 p-3 rounded-xl text-xs">
                <div>
                  <span className="text-slate-500 block font-semibold">Derived Total Assets</span>
                  <span className="font-mono font-bold text-slate-900 text-base">
                    {formatCurrency(openingProposal.total_assets)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block font-semibold">Derived Total Liabilities</span>
                  <span className="font-mono font-bold text-slate-900 text-base">
                    {formatCurrency(openingProposal.total_liabilities)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block font-semibold">Balancing Owner Equity</span>
                  <span className="font-mono font-bold text-emerald-800 text-base">
                    {formatCurrency(openingProposal.owner_equity)}
                  </span>
                </div>
              </div>

              <div className="overflow-x-auto border border-slate-200 rounded-xl">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 border-b border-slate-200 font-bold text-slate-700">
                    <tr>
                      <th className="px-4 py-2.5">Code</th>
                      <th className="px-4 py-2.5">Account Name</th>
                      <th className="px-4 py-2.5 text-right">Debit (₹)</th>
                      <th className="px-4 py-2.5 text-right">Credit (₹)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-medium text-slate-800">
                    {openingProposal.proposed_lines.map((line) => (
                      <tr key={line.account_code}>
                        <td className="px-4 py-2 font-mono font-bold text-slate-600">{line.account_code}</td>
                        <td className="px-4 py-2">{line.account_name}</td>
                        <td className="px-4 py-2 text-right font-mono text-slate-900">
                          {line.debit > 0 ? formatCurrency(line.debit) : '—'}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-slate-900">
                          {line.credit > 0 ? formatCurrency(line.credit) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-slate-50 border-t border-slate-200 font-bold">
                    <tr>
                      <td colSpan={2} className="px-4 py-2.5 text-right text-slate-700 uppercase tracking-wider text-[11px]">
                        Totals
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-slate-900">
                        {formatCurrency(openingProposal.total_debits)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-slate-900">
                        {formatCurrency(openingProposal.total_credits)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB: DEBTORS (ACCOUNTS RECEIVABLE) */}
      {activeTab === 'debtors' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
              <h2 className="text-base font-bold text-slate-900">Accounts Receivable (Debtors Ledger)</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Outstanding balances due from shopkeepers, retailers, and distributors.
              </p>
            </div>
            <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-right">
              <span className="text-xs text-red-600 font-semibold block">Total Receivables Outstanding</span>
              <span className="text-xl font-bold font-mono text-red-700">
                {formatCurrency(debtors.reduce((acc, d) => acc + (d.outstanding_balance || 0), 0))}
              </span>
            </div>
          </div>

          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 font-bold text-slate-700">
                  <tr>
                    <th className="px-4 py-3">Customer / Shop Name</th>
                    <th className="px-4 py-3">City</th>
                    <th className="px-4 py-3 text-right">Total Invoiced</th>
                    <th className="px-4 py-3 text-right">Total Paid</th>
                    <th className="px-4 py-3 text-right">Outstanding Balance</th>
                    <th className="px-4 py-3 text-center">Unpaid Bills</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-medium text-slate-800">
                  {debtors.map((d) => (
                    <tr key={d.customer_id} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3 font-semibold text-slate-900">{d.customer_name}</td>
                      <td className="px-4 py-3 text-slate-500">{d.city || 'Bikaner'}</td>
                      <td className="px-4 py-3 text-right font-mono">{formatCurrency(d.total_invoiced)}</td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-700">{formatCurrency(d.total_collected)}</td>
                      <td className="px-4 py-3 text-right font-mono font-bold text-red-700">
                        {formatCurrency(d.outstanding_balance)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-block px-2 py-0.5 rounded-full text-2xs font-bold bg-amber-100 text-amber-800">
                          {d.unpaid_invoices_count} bill(s)
                        </span>
                      </td>
                    </tr>
                  ))}
                  {debtors.length === 0 && (
                    <tr>
                      <td colSpan={6} className="text-center py-8 text-slate-400">
                        No customer accounts receivable found or all balances are cleared.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB: CREDITORS (ACCOUNTS PAYABLE) */}
      {activeTab === 'creditors' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
              <h2 className="text-base font-bold text-slate-900">Accounts Payable (Creditors Ledger)</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Outstanding liabilities due to raw material mandi suppliers, grain merchants, and packaging vendors.
              </p>
            </div>
            <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-right">
              <span className="text-xs text-red-600 font-semibold block">Total Payables Outstanding</span>
              <span className="text-xl font-bold font-mono text-red-700">
                {formatCurrency(creditors.reduce((acc, c) => acc + (c.outstanding_payable || 0), 0))}
              </span>
            </div>
          </div>

          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 font-bold text-slate-700">
                  <tr>
                    <th className="px-4 py-3">Supplier / Mandi Merchant</th>
                    <th className="px-4 py-3 text-right">Total Invoiced</th>
                    <th className="px-4 py-3 text-right">Total Disbursed</th>
                    <th className="px-4 py-3 text-right">Outstanding Payable</th>
                    <th className="px-4 py-3 text-center">Open Bills</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-medium text-slate-800">
                  {creditors.map((c) => (
                    <tr key={c.supplier_id} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3 font-semibold text-slate-900">{c.supplier_name}</td>
                      <td className="px-4 py-3 text-right font-mono">{formatCurrency(c.total_billed)}</td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-700">{formatCurrency(c.total_paid)}</td>
                      <td className="px-4 py-3 text-right font-mono font-bold text-red-700">
                        {formatCurrency(c.outstanding_payable)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-block px-2 py-0.5 rounded-full text-2xs font-bold bg-amber-100 text-amber-800">
                          {c.open_bills_count} bill(s)
                        </span>
                      </td>
                    </tr>
                  ))}
                  {creditors.length === 0 && (
                    <tr>
                      <td colSpan={5} className="text-center py-8 text-slate-400">
                        No outstanding supplier creditors found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB: CASH & BANK REPORT */}
      {activeTab === 'cash-bank' && (
        <div className="space-y-6">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
            <h2 className="text-base font-bold text-slate-900">Cash & Liquid Bank Funds Position</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Consolidated position of factory safe, salesman van floats, and official bank accounts.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 text-xs font-semibold">
                <span>Factory Safe Cash</span>
                <Coins size={18} className="text-emerald-700" />
              </div>
              <div className="mt-3 text-2xl font-bold font-mono text-slate-900">
                {formatCurrency(cashBank?.factory_safe_cash || 0)}
              </div>
              <p className="text-2xs text-slate-400 mt-1">Physical cash retained at factory premises</p>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 text-xs font-semibold">
                <span>Salesman Van Float</span>
                <Coins size={18} className="text-blue-600" />
              </div>
              <div className="mt-3 text-2xl font-bold font-mono text-blue-900">
                {formatCurrency(cashBank?.salesman_van_float || 0)}
              </div>
              <p className="text-2xs text-slate-400 mt-1">Operating route float held by field sales team</p>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 text-xs font-semibold">
                <span>Bank Accounts (Operating)</span>
                <Landmark size={18} className="text-indigo-600" />
              </div>
              <div className="mt-3 text-2xl font-bold font-mono text-indigo-900">
                {formatCurrency(cashBank?.bank_account_balance || 0)}
              </div>
              <p className="text-2xs text-slate-400 mt-1">Current accounts and verified bank deposits</p>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-emerald-300 shadow-sm bg-emerald-50/40">
              <div className="flex items-center justify-between text-emerald-800 text-xs font-bold">
                <span>Total Liquid Funds</span>
                <Scale size={18} className="text-emerald-800" />
              </div>
              <div className="mt-3 text-2xl font-bold font-mono text-emerald-900">
                {formatCurrency(cashBank?.total_liquid_funds || 0)}
              </div>
              <p className="text-2xs text-emerald-700 mt-1">Total immediate liquidity available for operations</p>
            </div>
          </div>
        </div>
      )}

      {/* TAB: GST SUMMARY */}
      {activeTab === 'gst-summary' && (
        <div className="space-y-6">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
              <h2 className="text-base font-bold text-slate-900">GST Monthly Summary (GSTR-3B Computation)</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Output CGST/SGST collected from sales vs. Input ITC available on purchases & freight.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="text-xs p-2 border border-slate-300 rounded-xl font-medium"
              />
              <span className="text-xs text-slate-400">to</span>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="text-xs p-2 border border-slate-300 rounded-xl font-medium"
              />
              <button
                onClick={() => loadData()}
                className="px-3 py-2 bg-emerald-800 text-white rounded-xl text-xs font-semibold hover:bg-emerald-900"
              >
                Apply
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
              <div className="text-xs font-bold uppercase tracking-wider text-slate-600">
                1. Output Tax Liability (Sales)
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-600">Output CGST (Central Tax)</span>
                <span className="font-mono font-semibold">{formatCurrency(gstSummary?.output_cgst_payable || 0)}</span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-600">Output SGST (State Tax)</span>
                <span className="font-mono font-semibold">{formatCurrency(gstSummary?.output_sgst_payable || 0)}</span>
              </div>
              <div className="pt-2 border-t flex justify-between items-center font-bold text-xs text-slate-900">
                <span>Total Output Tax Payable</span>
                <span className="font-mono text-sm">{formatCurrency(gstSummary?.total_output_gst || 0)}</span>
              </div>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
              <div className="text-xs font-bold uppercase tracking-wider text-slate-600">
                2. Input Tax Credit (ITC)
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-600">Input CGST Available</span>
                <span className="font-mono font-semibold text-emerald-700">{formatCurrency(gstSummary?.input_cgst_itc || 0)}</span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-600">Input SGST Available</span>
                <span className="font-mono font-semibold text-emerald-700">{formatCurrency(gstSummary?.input_sgst_itc || 0)}</span>
              </div>
              <div className="pt-2 border-t flex justify-between items-center font-bold text-xs text-slate-900">
                <span>Total Eligible ITC</span>
                <span className="font-mono text-sm text-emerald-800">{formatCurrency(gstSummary?.total_input_itc || 0)}</span>
              </div>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
              <div className="text-xs font-bold uppercase tracking-wider text-slate-600">
                3. Net Government Settlement
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-600">Net Cash Payable to Govt</span>
                <span className="font-mono font-bold text-red-700">{formatCurrency(gstSummary?.net_gst_payable || 0)}</span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-600">Excess ITC Credit (C/F)</span>
                <span className="font-mono font-bold text-emerald-700">{formatCurrency(gstSummary?.excess_itc_credit || 0)}</span>
              </div>
              <div className="p-2.5 bg-slate-50 rounded-xl text-2xs text-slate-500 mt-2">
                Eligible ITC automatically offsets output liability under GST Section 49 rules.
              </div>
            </div>
          </div>
        </div>
      )}


      {/* Reversal Confirmation Modal */}
      {reversalTarget && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-200 space-y-4">
            <div className="flex items-center gap-3 text-rose-700">
              <ShieldAlert size={24} />
              <h3 className="text-base font-bold text-slate-900">
                Post Compensating Reversal Voucher
              </h3>
            </div>
            <p className="text-xs text-slate-600">
              You are about to reverse voucher <strong className="font-mono">{reversalTarget.journal_id}</strong> ({reversalTarget.narration}) totaling {formatCurrency(reversalTarget.total_debit)}.
            </p>
            <div className="p-3 bg-amber-50 rounded-xl text-amber-900 text-xs border border-amber-200">
              In strict double-entry accounting, posted entries cannot be deleted. An equal and opposite compensating voucher will be permanently posted to nullify the financial impact.
            </div>
            <div>
              <label className="text-xs font-bold text-slate-700 block mb-1">
                Reason for Reversal <span className="text-rose-600">*</span>
              </label>
              <textarea
                value={reversalReason}
                onChange={(e) => setReversalReason(e.target.value)}
                placeholder="e.g. Authorized customer order cancellation / duplicate entry correction"
                className="w-full p-2.5 border border-slate-300 rounded-xl text-xs font-medium focus:ring-2 focus:ring-rose-500 focus:outline-none"
                rows={3}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setReversalTarget(null)}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition-colors"
                disabled={reversing}
              >
                Cancel
              </button>
              <button
                onClick={handleReverseVoucher}
                disabled={reversing || !reversalReason.trim()}
                className="px-4 py-2 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-xl transition-colors disabled:opacity-50"
              >
                {reversing ? 'Reversing…' : 'Confirm Reversal'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
