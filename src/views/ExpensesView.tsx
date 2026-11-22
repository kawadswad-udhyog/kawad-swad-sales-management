import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { resolveCanonical12Role } from '../utils/permissions';
import {
  createSubmissionNonce,
  extractUnknownOutcomeInfo,
  isUnknownOutcomeError,
  UNKNOWN_OUTCOME_STANDARD_MSG,
} from '../services/api';
import { Expense } from '../types';
import { UnknownOutcomeBanner } from '../components/common/UnknownOutcomeBanner';
import { shouldBlockDraftNonceReset, useUnknownOutcomeGuard } from '../utils/unknownOutcomeLock';
import { PageHeader } from '../components/common/PageHeader';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';
import {
  Receipt,
  Plus,
  CheckCircle2,
  XCircle,
  AlertCircle,
  X,
  Fuel,
  Package,
  FileText,
  CreditCard,
} from 'lucide-react';
import {
  FormLayout,
  FormSection,
  FormField,
  MoneyInput,
  TextInput,
  TextArea,
  CalculationPreview,
  FormActions,
  SaveButton,
  CancelButton,
} from '../components/common/FormComponents';

const COMMON_EXPENSE_DESCRIPTIONS = [
  'Motorcycle Petrol / Fuel',
  'Vehicle Puncture / Repair',
  'Lunch / Refreshment',
  'Cartage / Auto Delivery',
  'Packing Tape & Stationery',
  'Mobile Calls / Data',
];

const CATEGORIES: Array<{ key: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL'; label: string; icon: React.ReactNode }> = [
  { key: 'TRAVEL', label: 'Travel / Fuel', icon: <Fuel size={16} /> },
  { key: 'DELIVERY', label: 'Delivery', icon: <Package size={16} /> },
  { key: 'OTHER', label: 'Other', icon: <FileText size={16} /> },
  { key: 'DIGITAL', label: 'Digital', icon: <CreditCard size={16} /> },
];

export const ExpensesView: React.FC = () => {
  const {
    expenses,
    submitExpense,
    approveExpense,
    rejectExpense,
    currentUser,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
  } = useStore();
  const canonicalRole = resolveCanonical12Role(currentUser?.role);
  const isAuditor = canonicalRole === 'AUDITOR';
  const isManager = !isAuditor && (canonicalRole === 'OWNER_ADMIN' || canonicalRole === 'PA');
  const writesLocked = isAuditor || !isBackendConnected || !isGoogleSheetsConnected || !persistentWritesEnabled;

  const [category, setCategory] = useState<'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL'>('TRAVEL');
  const [amount, setAmount] = useState<number>(100);
  const [description, setDescription] = useState('');
  const [receiptRef, setReceiptRef] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('ALL');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Reject dialog state (avoiding window.prompt)
  const [rejectingExpense, setRejectingExpense] = useState<Expense | null>(null);
  const [rejectionReason, setRejectionReason] = useState('');
  const [expenseNonce, setExpenseNonce] = useState<string | null>(null);
  const {
    unknownOutcome,
    isOutcomeLocked,
    lockWithUnknownOutcome,
    clearAfterVerifiedResolution,
  } = useUnknownOutcomeGuard('expenses_view');
  const effectiveWritesLocked = writesLocked || isOutcomeLocked;

  const clearActionNonce = (key: string) => {
    if (shouldBlockDraftNonceReset(unknownOutcome)) return;
    setActionNonces((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const [actionNonces, setActionNonces] = useState<Record<string, string>>({});

  const executeSubmit = async (allowSameNonceRecoveryRetry = false) => {
    if (isSubmitting || writesLocked || (isOutcomeLocked && !allowSameNonceRecoveryRetry)) return;
    setNotice(null);

    if (amount <= 0) {
      setNotice({ msg: 'Expense amount must be greater than 0.', error: true });
      return;
    }
    if (!description.trim()) {
      setNotice({ msg: 'Please enter a description for the expense.', error: true });
      return;
    }

    const activeNonce = expenseNonce || createSubmissionNonce('EXP');
    if (!expenseNonce) setExpenseNonce(activeNonce);

    try {
      setIsSubmitting(true);
      await submitExpense({
        category,
        amount: Number(amount),
        description: description.trim(),
        receipt_link_or_file_ref: receiptRef.trim(),
        idempotency_key: activeNonce,
      }, activeNonce);
      setNotice({ msg: `Expense of ₹${amount} submitted for approval.` });
      setExpenseNonce(null);
      clearAfterVerifiedResolution();
      setDescription('');
      setReceiptRef('');
      setAmount(100);
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, 'Submit Expense Claim');
      if (unknownInfo) lockWithUnknownOutcome(unknownInfo);
      const errorMsg = isUnknownOutcomeError(err)
        ? UNKNOWN_OUTCOME_STANDARD_MSG
        : err instanceof Error
        ? err.message
        : 'Failed to submit expense';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await executeSubmit(false);
  };

  const handleApprove = async (e: Expense) => {
    if (effectiveWritesLocked || isSubmitting) return;
    const key = `approve:${e.expense_id}`;
    const activeNonce = actionNonces[key] || createSubmissionNonce('EXPAPP');
    if (!actionNonces[key]) setActionNonces((prev) => ({ ...prev, [key]: activeNonce }));
    try {
      await approveExpense(e.expense_id, 'Approved by manager', activeNonce);
      clearAfterVerifiedResolution();
      setActionNonces((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setNotice({ msg: `Expense ${e.expense_id} approved. Marked as cash-reducing.` });
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, `Approve Expense ${e.expense_id}`);
      if (unknownInfo) lockWithUnknownOutcome(unknownInfo);
      const msg = isUnknownOutcomeError(err)
        ? UNKNOWN_OUTCOME_STANDARD_MSG
        : err instanceof Error
        ? err.message
        : 'Failed to approve';
      setNotice({ msg, error: true });
    }
  };

  const handleConfirmReject = async () => {
    if (!rejectingExpense || effectiveWritesLocked || isSubmitting) return;
    if (!rejectionReason.trim()) {
      setNotice({ msg: 'A reason is required to reject an expense.', error: true });
      return;
    }
    const key = `reject:${rejectingExpense.expense_id}`;
    const activeNonce = actionNonces[key] || createSubmissionNonce('EXPREJ');
    if (!actionNonces[key]) setActionNonces((prev) => ({ ...prev, [key]: activeNonce }));
    try {
      await rejectExpense(rejectingExpense.expense_id, rejectionReason.trim(), activeNonce);
      clearAfterVerifiedResolution();
      setActionNonces((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setNotice({ msg: `Expense ${rejectingExpense.expense_id} rejected.` });
      setRejectingExpense(null);
      setRejectionReason('');
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, `Reject Expense ${rejectingExpense.expense_id}`);
      if (unknownInfo) lockWithUnknownOutcome(unknownInfo);
      const msg = isUnknownOutcomeError(err)
        ? UNKNOWN_OUTCOME_STANDARD_MSG
        : err instanceof Error
        ? err.message
        : 'Failed to reject';
      setNotice({ msg, error: true });
    }
  };

  // Filter based on user role
  const userExpenses = canonicalRole === 'FIELD_SALESMAN'
    ? expenses.filter(
        (e) =>
          e.submitted_by_user_id === currentUser?.user_id ||
          e.salesman_user_id === currentUser?.user_id
      )
    : expenses;

  const filteredExpenses = userExpenses.filter((e) => {
    if (filterStatus === 'ALL') return true;
    return e.approval_status === filterStatus;
  });

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <PageHeader
        title="Daily Expenses"
        subtitle="Submit travel fuel, tea, delivery cartage, and record daily operational expense claims"
        icon={<Receipt size={22} />}
      />

      <UnknownOutcomeBanner
        outcome={unknownOutcome}
        onRetry={expenseNonce && unknownOutcome?.nonce === expenseNonce ? () => executeSubmit(true) : undefined}
        onConfirmedRecorded={() => {
          setExpenseNonce(null);
          clearAfterVerifiedResolution();
        }}
        onDismiss={clearAfterVerifiedResolution}
      />

      {notice && (
        <div
          className={`p-3.5 rounded-xl text-xs flex items-center justify-between border ${
            notice.error
              ? 'bg-red-50 border-red-200 text-red-900'
              : 'bg-emerald-50 border-emerald-200 text-emerald-900'
          }`}
        >
          <div className="flex items-center gap-2">
            {notice.error ? <AlertCircle size={16} className="text-red-600" /> : <CheckCircle2 size={16} className="text-emerald-600" />}
            <span className="font-medium">{notice.msg}</span>
          </div>
          <button onClick={() => setNotice(null)} className="p-1 text-slate-400 hover:text-slate-600">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Expense Submission Form using FormComponents */}
      {!isAuditor && (
      <div className="bg-white border border-[#E7E2D6] rounded-2xl shadow-sm overflow-hidden">
        <div className="p-5 sm:p-6 border-b border-[#F0ECE1] bg-[#FAF8F5]">
          <h2 className="text-base sm:text-lg font-bold text-slate-900 m-0">Record Expense Claim</h2>
          <p className="text-xs text-slate-500 mt-1 m-0">
            Approved cash claims automatically reduce cash due back during evening closing.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="p-5 sm:p-6 space-y-5">
          <fieldset
            disabled={isOutcomeLocked}
            data-tx-form-locked={isOutcomeLocked ? 'true' : 'false'}
            style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
            className="space-y-5"
          >
          {/* Category Selector */}
          <FormField label="Expense Category" required>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {CATEGORIES.map((c) => {
                const isSelected = category === c.key;
                return (
                  <button
                    key={c.key}
                    type="button"
                    onClick={() => setCategory(c.key)}
                    className={`p-3 rounded-xl border text-left transition-all cursor-pointer flex items-center gap-2.5 ${
                      isSelected
                        ? 'bg-[#0F2C23] text-white font-bold shadow-xs border-[#0F2C23]'
                        : 'bg-white border-slate-200 hover:border-slate-300 text-slate-700'
                    }`}
                  >
                    <span className={isSelected ? 'text-white' : 'text-slate-400'}>
                      {c.icon}
                    </span>
                    <span className="text-xs">{c.label}</span>
                  </button>
                );
              })}
            </div>
          </FormField>

          {/* Amount & Quick Buttons */}
          <FormField
            label="Amount (₹)"
            required
            helpText="Enter claimed amount or tap a preset chip"
          >
            <div className="space-y-2">
              <MoneyInput
                value={amount}
                onChange={(val) => setAmount(val)}
                placeholder="100.00"
                required
              />
              <div className="flex items-center gap-1.5 flex-wrap">
                {[50, 100, 200, 500].map((quick) => (
                  <button
                    key={quick}
                    type="button"
                    onClick={() => setAmount(quick)}
                    className="px-2.5 py-1 text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg transition-colors cursor-pointer"
                  >
                    ₹{quick}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setAmount((prev) => prev + 50)}
                  className="px-2.5 py-1 text-xs font-semibold bg-emerald-50 hover:bg-emerald-100 text-emerald-800 rounded-lg transition-colors cursor-pointer"
                >
                  +₹50
                </button>
              </div>
            </div>
          </FormField>

          {/* Shortcuts & Description */}
          <FormField
            label="Description"
            required
            helpText="Click a common description or type a custom remark"
          >
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {COMMON_EXPENSE_DESCRIPTIONS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDescription(d)}
                    className={`px-2.5 py-1 text-xs rounded-md transition-colors cursor-pointer ${
                      description === d
                        ? 'bg-[#0F2C23] text-white font-semibold'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-600'
                    }`}
                  >
                    {d}
                  </button>
                ))}
              </div>
              <TextInput
                required
                placeholder="e.g. Motorcycle petrol, Bus cartage slip, packing tape..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </FormField>

          {/* Reference / Slip number */}
          <FormField
            label="Receipt / Bill Slip Number (Optional)"
            helpText="Reference number on the physical cash voucher, petrol bill, or UTR"
          >
            <TextInput
              placeholder="e.g. SLIP-1029, Fuel bill invoice number..."
              value={receiptRef}
              onChange={(e) => setReceiptRef(e.target.value)}
            />
          </FormField>

          <div className="pt-2 flex justify-end">
            <SaveButton
              label={effectiveWritesLocked ? (isOutcomeLocked ? 'Form Locked — Check Status' : 'Writes Locked') : 'Submit Expense Claim'}
              isLoading={isSubmitting}
              disabled={effectiveWritesLocked}
              icon={<Receipt size={14} />}
            />
          </div>
          </fieldset>
        </form>
      </div>
      )}

      {/* Expenses Register Table */}
      <div className="bg-white border border-slate-200 rounded-2xl p-5 sm:p-6 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 mb-4 border-b border-slate-100">
          <div>
            <h2 className="text-base font-bold text-slate-900 m-0">
              Expenses History ({filteredExpenses.length})
            </h2>
            <p className="text-xs text-slate-500 m-0">Recent expense records and verification status</p>
          </div>

          <div className="flex items-center gap-1 p-1 bg-slate-100 rounded-lg border border-slate-200/60 shrink-0">
            {['ALL', 'PENDING', 'APPROVED', 'REJECTED'].map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setFilterStatus(st)}
                className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors cursor-pointer ${
                  filterStatus === st ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {st}
              </button>
            ))}
          </div>
        </div>

        {filteredExpenses.length === 0 ? (
          <EmptyState
            title="No Expenses Recorded"
            description="No expense claims match the selected filter."
            icon={<Receipt size={28} />}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/70 text-slate-500 uppercase tracking-wider text-[11px]">
                  <th className="py-2.5 px-3">Date</th>
                  <th className="py-2.5 px-3">Category</th>
                  <th className="py-2.5 px-3">Amount</th>
                  <th className="py-2.5 px-3">Description</th>
                  <th className="py-2.5 px-3">Status</th>
                  {isManager && <th className="py-2.5 px-3 text-right">Action</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredExpenses.map((exp) => (
                  <tr key={exp.expense_id} className="hover:bg-slate-50/50">
                    <td className="py-3 px-3 font-medium text-slate-700 whitespace-nowrap">
                      {new Date(exp.expense_datetime).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                    </td>
                    <td className="py-3 px-3 font-semibold text-slate-800">
                      {exp.category}
                    </td>
                    <td className="py-3 px-3 font-extrabold text-slate-900 font-mono">
                      ₹{exp.amount.toFixed(2)}
                    </td>
                    <td className="py-3 px-3 text-slate-700 max-w-xs">
                      <div>{exp.description}</div>
                      {exp.receipt_link_or_file_ref && (
                        <div className="text-[10px] text-slate-400 font-mono">
                          Ref: {exp.receipt_link_or_file_ref}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <StatusBadge status={exp.approval_status} size="sm" />
                    </td>
                    {isManager && (
                      <td className="py-3 px-3 text-right">
                        {exp.approval_status === 'PENDING' && (
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              type="button"
                              disabled={effectiveWritesLocked}
                              onClick={() => handleApprove(exp)}
                              className="px-2.5 py-1 text-xs font-semibold bg-emerald-50 hover:bg-emerald-100 text-emerald-800 rounded-md transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              disabled={effectiveWritesLocked}
                              onClick={() => setRejectingExpense(exp)}
                              className="px-2.5 py-1 text-xs font-semibold bg-red-50 hover:bg-red-100 text-red-800 rounded-md transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              Reject
                            </button>
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Rejection Modal using FormComponents */}
      {rejectingExpense && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
          <FormLayout
            title="Reject Expense Claim"
            subtitle={`Expense #${rejectingExpense.expense_id} · Claimed ₹${rejectingExpense.amount.toFixed(2)} (${rejectingExpense.description})`}
            icon={<XCircle size={18} />}
            maxWidth="md"
            onSubmit={(e) => {
              e.preventDefault();
              handleConfirmReject();
            }}
            onCancel={
              isOutcomeLocked
                ? undefined
                : () => {
                    if (rejectingExpense) clearActionNonce(`reject:${rejectingExpense.expense_id}`);
                    setRejectingExpense(null);
                    setRejectionReason('');
                  }
            }
            actions={
              <FormActions>
                <CancelButton
                  disabled={isOutcomeLocked}
                  onClick={() => {
                    if (shouldBlockDraftNonceReset(unknownOutcome)) return;
                    if (rejectingExpense) clearActionNonce(`reject:${rejectingExpense.expense_id}`);
                    setRejectingExpense(null);
                    setRejectionReason('');
                  }}
                />
                <SaveButton
                  label={isOutcomeLocked ? 'Form Locked' : 'Confirm Rejection'}
                  disabled={effectiveWritesLocked}
                />
              </FormActions>
            }
          >
            <UnknownOutcomeBanner
              outcome={unknownOutcome}
              onConfirmedRecorded={() => {
                clearAfterVerifiedResolution();
                setRejectingExpense(null);
                setRejectionReason('');
              }}
              onDismiss={clearAfterVerifiedResolution}
            />
            <fieldset
              disabled={isOutcomeLocked}
              data-tx-form-locked={isOutcomeLocked ? 'true' : 'false'}
              style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
            >
              <FormField
                label="Rejection Reason (Required)"
                required
                helpText="Specify why this operational claim cannot be reimbursed"
              >
                <TextArea
                  required
                  rows={3}
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  placeholder="e.g. Duplicate claim, missing receipt, exceeds allowable daily limit..."
                />
              </FormField>
            </fieldset>
          </FormLayout>
        </div>
      )}
    </div>
  );
};
