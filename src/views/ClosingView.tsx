import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import { DailyClosing } from '../types';
import { PageHeader } from '../components/common/PageHeader';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';
import {
  createSubmissionNonce,
  extractUnknownOutcomeInfo,
  isUnknownOutcomeError,
  UNKNOWN_OUTCOME_STANDARD_MSG,
} from '../services/api';
import { UnknownOutcomeBanner } from '../components/common/UnknownOutcomeBanner';
import {
  useUnknownOutcomeGuard,
  shouldBlockDraftNonceReset,
} from '../utils/unknownOutcomeLock';
import {
  Lock,
  Wallet,
  Coins,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  X,
  FileText,
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

export const ClosingView: React.FC = () => {
  const {
    currentUser,
    dailyClosings,
    getTodayClosingMetrics,
    submitDailyClosing,
    reviewDailyClosing,
  } = useStore();

  const userRole = String(currentUser?.role || '').toUpperCase();
  const isManager = ['OWNER', 'OWNER_ADMIN', 'ADMIN', 'PA', 'PERSONAL_ASSISTANT', 'ACCOUNTS'].includes(userRole);
  const currentSalesmanId = currentUser?.user_id || '';

  const [openingCash, setOpeningCash] = useState<number>(0);
  const [physicalCashReturned, setPhysicalCashReturned] = useState<number>(0);
  const [notes, setNotes] = useState('');
  const [submissionNonce, setSubmissionNonce] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ msg: string; error?: boolean; unknownOutcome?: boolean } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Manager review modal state (no window.prompt!)
  const [reviewingClosing, setReviewingClosing] = useState<{
    closing: DailyClosing;
    decision: 'CONFIRMED' | 'CORRECTION_REQUIRED';
  } | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [reviewNonce, setReviewNonce] = useState<string | null>(null);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);

  // TX-FINAL-04 & 51B-1R-F: Persistent UNKNOWN-outcome lock, nonce & payload fingerprint enforcement
  const {
    unknownOutcome,
    isOutcomeLocked,
    setUnknownOutcome,
    clearAfterVerifiedResolution,
    fingerprintMismatchError,
    verifyPayloadMatchesLock,
  } = useUnknownOutcomeGuard('closing_view');
  const [unknownActionType, setUnknownActionType] = useState<'submit' | 'review'>('submit');

  useEffect(() => {
    if (unknownOutcome?.nonce && unknownActionType === 'submit' && !submissionNonce) {
      setSubmissionNonce(unknownOutcome.nonce);
    }
  }, [unknownOutcome?.nonce, unknownActionType, submissionNonce]);

  // Live metrics for today
  const metrics = getTodayClosingMetrics(currentSalesmanId, Number(openingCash));
  const liveExpectedReturn = Math.max(
    0,
    openingCash + metrics.cash_collected - metrics.approved_cash_expenses
  );
  const liveDifference = physicalCashReturned - liveExpectedReturn;

  const executeSubmitClosing = async (allowSameNonceRecoveryRetry = false) => {
    if (isSubmitting) return;
    if (isOutcomeLocked && !allowSameNonceRecoveryRetry) {
      setNotice({
        msg: UNKNOWN_OUTCOME_STANDARD_MSG,
        error: true,
        unknownOutcome: true,
      });
      return;
    }
    setNotice(null);

    const activeNonce =
      submissionNonce ||
      (unknownActionType === 'submit' ? unknownOutcome?.nonce : null) ||
      createSubmissionNonce('CLOSING');
    if (!submissionNonce) {
      setSubmissionNonce(activeNonce);
    }

    const payload = {
      opening_cash: Number(openingCash),
      physical_cash_returned: Number(physicalCashReturned),
      notes: notes.trim(),
      idempotency_key: activeNonce,
    };

    if (allowSameNonceRecoveryRetry) {
      const fpCheck = verifyPayloadMatchesLock(payload, activeNonce);
      if (!fpCheck.ok) {
        setNotice({ msg: fpCheck.error, error: true, unknownOutcome: true });
        return;
      }
    }

    try {
      setIsSubmitting(true);
      const closing = await submitDailyClosing(payload);

      setSubmissionNonce(null);
      clearAfterVerifiedResolution();
      setNotice({
        msg: `Daily closing #${closing.closing_id} confirmed with difference: ₹${closing.cash_difference.toFixed(2)}.`,
      });
      setNotes('');
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, 'Submit Daily Cash Closing');
      if (unknownInfo) {
        setUnknownActionType('submit');
        setUnknownOutcome(unknownInfo, payload);
        setNotice({
          msg: `${UNKNOWN_OUTCOME_STANDARD_MSG} (Preserved nonce: ${activeNonce})`,
          error: true,
          unknownOutcome: true,
        });
      } else if (isUnknownOutcomeError(err)) {
        setUnknownActionType('submit');
        setUnknownOutcome(
          {
            nonce: activeNonce,
            message: UNKNOWN_OUTCOME_STANDARD_MSG,
            actionLabel: 'Submit Daily Cash Closing',
          },
          payload
        );
        setNotice({
          msg: `${UNKNOWN_OUTCOME_STANDARD_MSG} (Preserved nonce: ${activeNonce})`,
          error: true,
          unknownOutcome: true,
        });
      } else {
        const errorMsg = err instanceof Error ? err.message : 'Failed to submit daily closing';
        setNotice({
          msg: `NOT SAVED: ${errorMsg}. Inputs and nonce (${activeNonce}) are preserved for retry.`,
          error: true,
        });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await executeSubmitClosing(false);
  };

  const handleConfirmReview = async (allowSameNonceRecoveryRetry = false) => {
    if (!reviewingClosing || reviewSubmitting) return;
    if (isOutcomeLocked && !allowSameNonceRecoveryRetry) {
      setNotice({
        msg: UNKNOWN_OUTCOME_STANDARD_MSG,
        error: true,
        unknownOutcome: true,
      });
      return;
    }
    const { closing, decision } = reviewingClosing;
    if (decision === 'CORRECTION_REQUIRED' && !reviewNote.trim()) {
      setNotice({ msg: 'A note explaining the discrepancy is required.', error: true });
      return;
    }
    const activeNonce =
      reviewNonce ||
      (unknownActionType === 'review' ? unknownOutcome?.nonce : null) ||
      createSubmissionNonce('CLSRVW');
    if (!reviewNonce) setReviewNonce(activeNonce);
    const reviewPayload = {
      closing_id: closing.closing_id,
      decision,
      reviewNote: reviewNote.trim(),
    };
    if (allowSameNonceRecoveryRetry) {
      const fpCheck = verifyPayloadMatchesLock(reviewPayload, activeNonce);
      if (!fpCheck.ok) {
        setNotice({ msg: fpCheck.error, error: true, unknownOutcome: true });
        return;
      }
    }
    setReviewSubmitting(true);
    try {
      await reviewDailyClosing(closing.closing_id, decision, reviewNote.trim(), activeNonce);
      setReviewNonce(null);
      clearAfterVerifiedResolution();
      setNotice({ msg: `Daily closing #${closing.closing_id} marked as ${decision}.` });
      setReviewingClosing(null);
      setReviewNote('');
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(
        err,
        activeNonce,
        `Review Daily Closing #${closing.closing_id}`
      );
      if (unknownInfo) {
        setUnknownActionType('review');
        setUnknownOutcome(unknownInfo, {
          closing_id: closing.closing_id,
          decision,
          reviewNote: reviewNote.trim(),
        });
        setNotice({
          msg: `${UNKNOWN_OUTCOME_STANDARD_MSG} (Preserved nonce: ${activeNonce})`,
          error: true,
          unknownOutcome: true,
        });
      } else if (isUnknownOutcomeError(err)) {
        setUnknownActionType('review');
        setUnknownOutcome(
          {
            nonce: activeNonce,
            message: UNKNOWN_OUTCOME_STANDARD_MSG,
            actionLabel: `Review Daily Closing #${closing.closing_id}`,
          },
          { closing_id: closing.closing_id, decision, reviewNote: reviewNote.trim() }
        );
        setNotice({
          msg: `${UNKNOWN_OUTCOME_STANDARD_MSG} (Preserved nonce: ${activeNonce})`,
          error: true,
          unknownOutcome: true,
        });
      } else {
        setNotice({ msg: err instanceof Error ? err.message : 'Closing review was not saved.', error: true });
      }
    } finally {
      setReviewSubmitting(false);
    }
  };

  const visibleClosings = ['SALESMAN', 'FIELD_SALESMAN'].includes(userRole)
    ? dailyClosings.filter((c) => c.salesman_user_id === currentUser?.user_id)
    : dailyClosings;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <PageHeader
        title="Daily Cash Handover"
        subtitle="End-of-day cash handover: Morning cash + Money received - Daily expenses = Cash to submit"
        icon={<Lock size={22} />}
      />

      <UnknownOutcomeBanner
        outcome={unknownOutcome}
        fingerprintMismatchError={fingerprintMismatchError}
        onRetry={() => {
          if (unknownActionType === 'review' && reviewingClosing) {
            handleConfirmReview(true);
          } else {
            executeSubmitClosing(true);
          }
        }}
        onConfirmedRecorded={() => {
          setSubmissionNonce(null);
          setReviewNonce(null);
          setReviewingClosing(null);
          setReviewNote('');
          clearAfterVerifiedResolution();
          setNotice({ msg: '✅ Daily closing transaction confirmed in Google Sheets. Form unlocked.' });
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

      {/* Live Calculation Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Morning Cash
          </span>
          <div className="text-2xl font-black text-slate-900 mt-1 font-mono">
            ₹{Number(openingCash).toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Starting cash float</div>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Money Received
          </span>
          <div className="text-2xl font-black text-emerald-800 mt-1 font-mono">
            +₹{metrics.cash_collected.toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Paid bills today</div>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Daily Expenses
          </span>
          <div className="text-2xl font-black text-red-700 mt-1 font-mono">
            -₹{metrics.approved_cash_expenses.toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Approved fuel & claims</div>
        </div>

        <div className="bg-emerald-50/80 border border-emerald-300 rounded-xl p-4 shadow-2xs">
          <span className="text-xs font-bold uppercase tracking-wider text-emerald-900">
            Money to Hand Over
          </span>
          <div className="text-2xl font-black text-emerald-950 mt-1 font-mono">
            ₹{liveExpectedReturn.toFixed(2)}
          </div>
          <div className="text-[11px] text-emerald-700 mt-1 font-semibold">Net cash to submit</div>
        </div>
      </div>

      {/* Submission Form using FormComponents */}
      <div className="bg-white border border-[#E7E2D6] rounded-2xl shadow-sm overflow-hidden">
        <div className="p-5 sm:p-6 border-b border-[#F0ECE1] bg-[#FAF8F5]">
          <h2 className="text-base sm:text-lg font-bold text-slate-900 m-0">
            Submit Day-End Cash Count
          </h2>
          <p className="text-xs text-slate-500 mt-1 m-0">
            Enter your morning cash float and physical cash returned to calculate live surplus or shortage before handover.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="p-5 sm:p-6 space-y-5">
          <fieldset
            disabled={isOutcomeLocked}
            data-tx-form-locked={isOutcomeLocked ? 'true' : 'false'}
            style={{ border: 0, padding: 0, margin: 0, minWidth: 0, opacity: isOutcomeLocked ? 0.72 : 1 }}
            className="space-y-5"
          >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FormField
              label="Morning Cash Float (₹)"
              required
              helpText="Starting cash balance issued at beginning of route"
            >
              <MoneyInput
                value={openingCash}
                disabled={isOutcomeLocked}
                onChange={(val) => {
                  if (shouldBlockDraftNonceReset(unknownOutcome)) return;
                  setSubmissionNonce(null);
                  setOpeningCash(val);
                }}
                placeholder="500.00"
                required
              />
            </FormField>

            <FormField
              label="Physical Cash Handed Over (₹)"
              required
              helpText="Actual cash collected and counted at end of day"
            >
              <MoneyInput
                value={physicalCashReturned}
                disabled={isOutcomeLocked}
                onChange={(val) => {
                  if (shouldBlockDraftNonceReset(unknownOutcome)) return;
                  setSubmissionNonce(null);
                  setPhysicalCashReturned(val);
                }}
                placeholder="0.00"
                required
              />
            </FormField>
          </div>

          <CalculationPreview
            title="Live Cash Reconciliation"
            items={[
              {
                label: 'Opening Float',
                value: `₹${Number(openingCash).toFixed(2)}`,
                subtitle: 'Morning start',
              },
              {
                label: 'Cash Sales',
                value: `+₹${metrics.cash_collected.toFixed(2)}`,
                subtitle: 'Route sales',
                variant: 'emerald',
              },
              {
                label: 'Approved Expenses',
                value: `-₹${metrics.approved_cash_expenses.toFixed(2)}`,
                subtitle: 'Fuel & cartage',
                variant: 'rose',
              },
              {
                label: 'Live Difference',
                value:
                  liveDifference > 0
                    ? `+₹${liveDifference.toFixed(2)} (Surplus)`
                    : liveDifference < 0
                    ? `-₹${Math.abs(liveDifference).toFixed(2)} (Shortage)`
                    : '₹0.00 (Match)',
                subtitle: liveDifference === 0 ? 'Balanced' : liveDifference > 0 ? 'Surplus cash' : 'Shortage cash',
                isHighlight: true,
                variant: liveDifference === 0 ? 'emerald' : liveDifference > 0 ? 'amber' : 'rose',
              },
            ]}
          />

          <FormField
            label="Closing Notes / Denominations (Optional)"
            helpText="Record currency note counts (e.g., 500x2, 200x5) or explanation for discrepancy"
          >
            <TextInput
              maxLength={500}
              disabled={isOutcomeLocked}
              placeholder="e.g. 500x3, 200x5, 100x10. Shortage due to credit approved for shopkeeper..."
              value={notes}
              onChange={(e) => {
                if (shouldBlockDraftNonceReset(unknownOutcome)) return;
                setSubmissionNonce(null);
                setNotes(e.target.value);
              }}
            />
          </FormField>

          <div className="pt-2 flex items-center justify-between gap-3 flex-wrap">
            {submissionNonce ? (
              <span className="text-[11px] font-mono text-amber-800 bg-amber-100 px-2.5 py-1 rounded font-semibold">
                Preserved Nonce: {submissionNonce}
              </span>
            ) : (
              <span />
            )}
            <SaveButton
              label={
                isOutcomeLocked
                  ? 'Locked — Check Status Above'
                  : submissionNonce
                  ? 'Retry Cash Closing (Same Nonce)'
                  : 'Submit Daily Cash Closing'
              }
              isLoading={isSubmitting}
              disabled={isOutcomeLocked}
              icon={<Coins size={14} />}
            />
          </div>
          </fieldset>
        </form>
      </div>

      {/* Closing History Table */}
      <div className="bg-white border border-slate-200 rounded-2xl p-5 sm:p-6 shadow-xs">
        <h2 className="text-base font-bold text-slate-900 mb-1">
          Closing Records ({visibleClosings.length})
        </h2>
        <p className="text-xs text-slate-500 mb-4">Historical daily cash closings and manager confirmations</p>

        {visibleClosings.length === 0 ? (
          <EmptyState
            title="No Closings Recorded"
            description="No daily cash closings submitted yet."
            icon={<Lock size={28} />}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/70 text-slate-500 uppercase tracking-wider text-[11px]">
                  <th className="py-2.5 px-3">Date</th>
                  <th className="py-2.5 px-3">Salesman</th>
                  <th className="py-2.5 px-3">Float</th>
                  <th className="py-2.5 px-3">Collected</th>
                  <th className="py-2.5 px-3">Expenses</th>
                  <th className="py-2.5 px-3">Expected</th>
                  <th className="py-2.5 px-3">Physical</th>
                  <th className="py-2.5 px-3">Diff</th>
                  <th className="py-2.5 px-3">Status</th>
                  {isManager && <th className="py-2.5 px-3 text-right">Review</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-mono">
                {visibleClosings.map((c) => (
                  <tr key={c.closing_id} className="hover:bg-slate-50/50">
                    <td className="py-3 px-3 text-slate-700 whitespace-nowrap font-sans font-medium">
                      {c.closing_date}
                    </td>
                    <td className="py-3 px-3 font-sans text-slate-800">
                      {c.salesman_user_id}
                    </td>
                    <td className="py-3 px-3 text-slate-600">₹{c.opening_cash.toFixed(2)}</td>
                    <td className="py-3 px-3 text-emerald-800 font-bold">+₹{c.cash_collected.toFixed(2)}</td>
                    <td className="py-3 px-3 text-red-700">-₹{c.approved_cash_expenses.toFixed(2)}</td>
                    <td className="py-3 px-3 font-bold text-slate-900">₹{c.expected_cash_return.toFixed(2)}</td>
                    <td className="py-3 px-3 font-bold text-slate-900">₹{c.physical_cash_returned.toFixed(2)}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`font-bold ${
                          c.cash_difference === 0
                            ? 'text-emerald-700'
                            : c.cash_difference > 0
                            ? 'text-sky-700'
                            : 'text-red-700'
                        }`}
                      >
                        ₹{c.cash_difference.toFixed(2)}
                      </span>
                    </td>
                    <td className="py-3 px-3 font-sans">
                      <StatusBadge status={c.closing_status} size="sm" />
                    </td>
                    {isManager && (
                      <td className="py-3 px-3 text-right font-sans">
                        {c.closing_status === 'SUBMITTED' ? (
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              type="button"
                              disabled={isOutcomeLocked}
                              onClick={() => {
                                if (isOutcomeLocked) return;
                                setReviewingClosing({ closing: c, decision: 'CONFIRMED' });
                              }}
                              className="px-2.5 py-1 text-xs font-semibold bg-emerald-50 hover:bg-emerald-100 disabled:opacity-50 text-emerald-800 rounded-md transition-colors cursor-pointer"
                            >
                              Confirm
                            </button>
                            <button
                              type="button"
                              disabled={isOutcomeLocked}
                              onClick={() => {
                                if (isOutcomeLocked) return;
                                setReviewingClosing({ closing: c, decision: 'CORRECTION_REQUIRED' });
                              }}
                              className="px-2.5 py-1 text-xs font-semibold bg-amber-50 hover:bg-amber-100 disabled:opacity-50 text-amber-800 rounded-md transition-colors cursor-pointer"
                            >
                              Correction
                            </button>
                          </div>
                        ) : (
                          <span className="text-[11px] text-slate-400">
                            {c.reviewed_by_user_id ? `By ${c.reviewed_by_user_id}` : 'Closed'}
                          </span>
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

      {/* Review Confirmation Modal using FormComponents */}
      {reviewingClosing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
          <FormLayout
            title={reviewingClosing.decision === 'CONFIRMED' ? 'Confirm Daily Closing' : 'Request Cash Correction'}
            subtitle={`Closing #${reviewingClosing.closing.closing_id} · Expected ₹${reviewingClosing.closing.expected_cash_return.toFixed(2)}, Physical Handover ₹${reviewingClosing.closing.physical_cash_returned.toFixed(2)}`}
            icon={reviewingClosing.decision === 'CONFIRMED' ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
            maxWidth="md"
            onSubmit={(e) => {
              e.preventDefault();
              handleConfirmReview(false);
            }}
            onCancel={
              isOutcomeLocked || reviewSubmitting
                ? undefined
                : () => {
                    setReviewingClosing(null);
                    setReviewNote('');
                  }
            }
            actions={
              <FormActions>
                <CancelButton
                  disabled={reviewSubmitting || isOutcomeLocked}
                  onClick={() => {
                    if (isOutcomeLocked || reviewSubmitting) return;
                    setReviewingClosing(null);
                    setReviewNote('');
                  }}
                  label="Cancel"
                />
                <SaveButton
                  label={
                    isOutcomeLocked
                      ? 'Locked — Check Status'
                      : reviewingClosing.decision === 'CONFIRMED'
                      ? 'Confirm Closing'
                      : 'Submit Correction'
                  }
                  isLoading={reviewSubmitting}
                  disabled={isOutcomeLocked}
                />
              </FormActions>
            }
          >
            {isOutcomeLocked && unknownActionType === 'review' && (
              <UnknownOutcomeBanner
                outcome={unknownOutcome}
                onRetry={() => handleConfirmReview(true)}
                onConfirmedRecorded={() => {
                  setReviewNonce(null);
                  setReviewingClosing(null);
                  setReviewNote('');
                  clearAfterVerifiedResolution();
                  setNotice({ msg: '✅ Daily closing review confirmed in Google Sheets.' });
                }}
                onDismiss={clearAfterVerifiedResolution}
              />
            )}
            <fieldset
              disabled={isOutcomeLocked || reviewSubmitting}
              style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
            >
              <FormField
                label={reviewingClosing.decision === 'CORRECTION_REQUIRED' ? 'Correction Reason (Required)' : 'Review Notes (Optional)'}
                required={reviewingClosing.decision === 'CORRECTION_REQUIRED'}
                helpText={reviewingClosing.decision === 'CORRECTION_REQUIRED' ? 'Explain the discrepancy to be rectified by the salesman' : 'Optional supervisory confirmation remarks'}
              >
                <TextArea
                  rows={3}
                  disabled={isOutcomeLocked || reviewSubmitting}
                  required={reviewingClosing.decision === 'CORRECTION_REQUIRED'}
                  value={reviewNote}
                  onChange={(e) => {
                    if (shouldBlockDraftNonceReset(unknownOutcome)) return;
                    setReviewNote(e.target.value);
                  }}
                  placeholder="Enter review explanation or reason..."
                />
              </FormField>
            </fieldset>
          </FormLayout>
        </div>
      )}
    </div>
  );
};
