import React, { useState, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { createSubmissionNonce, extractUnknownOutcomeInfo, isUnknownOutcomeError } from '../services/api';
import { UnknownOutcomeBanner } from '../components/common/UnknownOutcomeBanner';
import { useUnknownOutcomeGuard } from '../utils/unknownOutcomeLock';
import { resolveCanonical12Role } from '../utils/permissions';

const COMMON_OUTCOMES = [
  'Order Placed',
  'Stock Full / No Requirement',
  'Payment Follow-up',
  'Shop Closed / Owner Absent',
  'Sample Given / Rate Inquiry',
];

const COMMON_NEXT_ACTIONS = [
  'Visit next week',
  'Call tomorrow',
  'Send delivery order',
  'No action required',
];

export const VisitsView: React.FC = () => {
  const {
    customers,
    shopVisits,
    addShopVisit,
    currentUser,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
  } = useStore();
  const {
    unknownOutcome,
    isOutcomeLocked,
    lockWithUnknownOutcome,
    clearAfterVerifiedResolution,
  } = useUnknownOutcomeGuard('visits_view');
  const canonicalRole = resolveCanonical12Role(currentUser?.role);
  const isAuditor = canonicalRole === 'AUDITOR';
  const writesLocked = isAuditor || isOutcomeLocked || !isBackendConnected || !isGoogleSheetsConnected || !persistentWritesEnabled;
  const activeCustomers = useMemo(() => customers.filter((c) => c.active), [customers]);

  const [customerFilter, setCustomerFilter] = useState('');
  const [customerId, setCustomerId] = useState(activeCustomers[0]?.customer_id || '');
  const [outcome, setOutcome] = useState('');
  const [orderTaken, setOrderTaken] = useState(false);
  const [followUpDate, setFollowUpDate] = useState('');
  const [nextAction, setNextAction] = useState('');
  const [notes, setNotes] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);
  const [visitNonce, setVisitNonce] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const filteredCustomers = useMemo(() => {
    if (!customerFilter.trim()) return activeCustomers;
    const q = customerFilter.toLowerCase();
    return activeCustomers.filter(
      (c) =>
        c.shop_name.toLowerCase().includes(q) ||
        (c.locality_area && c.locality_area.toLowerCase().includes(q)) ||
        (c.city && c.city.toLowerCase().includes(q))
    );
  }, [activeCustomers, customerFilter]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isOutcomeLocked) return;
    setNotice(null);

    if (!customerId) {
      setNotice({ msg: 'Please select a customer or shop.', error: true });
      return;
    }
    if (!outcome.trim()) {
      setNotice({ msg: 'Please describe or select the visit outcome.', error: true });
      return;
    }

    const activeNonce = visitNonce || createSubmissionNonce('VST');
    if (!visitNonce) setVisitNonce(activeNonce);
    setIsSubmitting(true);

    try {
      await addShopVisit({
        customer_id: customerId,
        visit_outcome: outcome.trim(),
        order_taken: orderTaken,
        follow_up_date: followUpDate,
        next_action: nextAction.trim(),
        notes: notes.trim(),
        idempotency_key: activeNonce,
      }, activeNonce);

      clearAfterVerifiedResolution();
      setNotice({ msg: 'Shop visit recorded successfully.' });
      setVisitNonce(null);
      setOutcome('');
      setNextAction('');
      setFollowUpDate('');
      setOrderTaken(false);
      setNotes('');
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, 'Record Shop Visit');
      if (unknownInfo) {
        lockWithUnknownOutcome(unknownInfo);
      }
      const errorMsg = isUnknownOutcomeError(err)
        ? 'Status not confirmed; do not submit a new transaction. Your inputs and retry key are preserved—verify status before retrying.'
        : err instanceof Error
        ? err.message
        : 'Failed to record visit';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const visibleVisits = canonicalRole === 'FIELD_SALESMAN'
    ? shopVisits.filter((v) => v.salesman_user_id === currentUser?.user_id)
    : shopVisits;

  return (
    <div>
      <h1>Shop Visits &amp; Field Follow-ups</h1>

      <UnknownOutcomeBanner
        outcome={unknownOutcome}
        onConfirmedRecorded={() => {
          clearAfterVerifiedResolution();
          setVisitNonce(null);
        }}
        onDismiss={clearAfterVerifiedResolution}
      />

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      {!isAuditor && (
      <div className="card">
        <h2>Record shop visit</h2>
        <fieldset
          disabled={isOutcomeLocked}
          data-tx-form-locked={isOutcomeLocked ? 'true' : 'false'}
          style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
        >
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '14px' }}>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '0.85rem', fontWeight: 600 }}>
              Shop / Customer
            </label>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '6px' }}>
              <input
                type="text"
                placeholder="🔍 Search shop by name or locality..."
                value={customerFilter}
                onChange={(e) => setCustomerFilter(e.target.value)}
                style={{ flex: 1, padding: '7px 10px', fontSize: '0.9rem' }}
              />
            </div>
            <select
              required
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              style={{ width: '100%', padding: '8px' }}
            >
              {filteredCustomers.map((c) => (
                <option key={c.customer_id} value={c.customer_id}>
                  {c.shop_name} ({c.locality_area || c.city})
                </option>
              ))}
            </select>
          </div>

          {/* Quick Outcome Chips */}
          <div style={{ marginBottom: '14px' }}>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '0.85rem', fontWeight: 600 }}>
              Visit Outcome (One-Tap Shortcuts)
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
              {COMMON_OUTCOMES.map((txt) => (
                <button
                  key={txt}
                  type="button"
                  onClick={() => {
                    setOutcome(txt);
                    if (txt === 'Order Placed') setOrderTaken(true);
                  }}
                  style={{
                    padding: '5px 12px',
                    fontSize: '0.82rem',
                    borderRadius: '16px',
                    border: outcome === txt ? '2px solid #0f766e' : '1px solid #cbd5e1',
                    background: outcome === txt ? '#ccfbf1' : '#f8fafc',
                    color: outcome === txt ? '#115e59' : '#334155',
                    fontWeight: outcome === txt ? 700 : 500,
                    cursor: 'pointer',
                  }}
                >
                  {txt}
                </button>
              ))}
            </div>
            <input
              required
              placeholder="Or type custom outcome (e.g. Rate inquiry, new store opened)..."
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>

          <div className="inline" style={{ marginBottom: '14px' }}>
            <label>
              Order taken?
              <select
                value={orderTaken ? 'true' : 'false'}
                onChange={(e) => setOrderTaken(e.target.value === 'true')}
              >
                <option value="false">No (Visit / Discussion only)</option>
                <option value="true">Yes (Order captured)</option>
              </select>
            </label>

            <label>
              Follow-up date
              <input
                type="date"
                value={followUpDate}
                onChange={(e) => setFollowUpDate(e.target.value)}
              />
            </label>
          </div>

          {/* Quick Next Action Chips */}
          <div style={{ marginBottom: '14px' }}>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '0.85rem', fontWeight: 600 }}>
              Next Action
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
              {COMMON_NEXT_ACTIONS.map((act) => (
                <button
                  key={act}
                  type="button"
                  onClick={() => setNextAction(act)}
                  style={{
                    padding: '4px 10px',
                    fontSize: '0.78rem',
                    borderRadius: '14px',
                    border: nextAction === act ? '1px solid #0f766e' : '1px solid #cbd5e1',
                    background: nextAction === act ? '#e0f2fe' : '#f1f5f9',
                    color: nextAction === act ? '#0369a1' : '#475569',
                    cursor: 'pointer',
                  }}
                >
                  {act}
                </button>
              ))}
            </div>
            <input
              placeholder="e.g. Bring marketing stand, deliver 500g family pack samples..."
              value={nextAction}
              onChange={(e) => setNextAction(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: '4px' }}>
                Notes / Feedback (Optional)
              </span>
              <input
                placeholder="Additional feedback, shopkeeper comments, competitor pricing..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                style={{ width: '100%' }}
              />
            </label>
          </div>

          <button type="submit" disabled={writesLocked || isSubmitting} style={{ padding: '10px 20px', fontSize: '0.95rem' }}>
            {writesLocked ? '🔒 Writes Locked' : isSubmitting ? 'Saving Visit…' : '💾 Save Visit Record'}
          </button>
        </form>
        </fieldset>
      </div>
      )}

      <div className="card">
        <div className="toolbar">
          <h2>
            Visit Log <span className="count">{visibleVisits.length}</span>
          </h2>
        </div>

        {visibleVisits.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Customer</th>
                  <th>Outcome</th>
                  <th>Order Taken</th>
                  <th>Next Action</th>
                  <th>Follow-up</th>
                </tr>
              </thead>
              <tbody>
                {visibleVisits.map((v) => {
                  const cust = customers.find((c) => c.customer_id === v.customer_id);
                  return (
                    <tr key={v.visit_id}>
                      <td>{new Date(v.visit_datetime).toLocaleDateString('en-IN')}</td>
                      <td>
                        <strong>{cust?.shop_name || v.customer_id}</strong>
                      </td>
                      <td>{v.visit_outcome}</td>
                      <td>
                        <span className={`badge ${v.order_taken ? 'on' : ''}`}>
                          {v.order_taken ? 'YES' : 'NO'}
                        </span>
                      </td>
                      <td>{v.next_action || '-'}</td>
                      <td>{v.follow_up_date || '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No visits recorded.</p>
        )}
      </div>
    </div>
  );
};
