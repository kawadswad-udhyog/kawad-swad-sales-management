import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { SalaryIncentive } from '../types';
import { createSubmissionNonce, isUnknownOutcomeError } from '../services/api';
import { resolveCanonical12Role } from '../utils/permissions';

export const SalaryView: React.FC = () => {
  const {
    currentUser,
    users,
    salaryIncentives,
    calculatePayroll,
    approveSalaryIncentive,
    markSalaryIncentivePaid,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
  } = useStore();

  const canonicalRole = resolveCanonical12Role(currentUser?.role);
  const isOwnerAdmin = canonicalRole === 'OWNER_ADMIN';
  const isAuditor = canonicalRole === 'AUDITOR';
  const writesLocked =
    isAuditor || !isOwnerAdmin || !isBackendConnected || !isGoogleSheetsConnected || !persistentWritesEnabled;

  const activeSalesmen = users.filter(
    (u) => resolveCanonical12Role(u.role) === 'FIELD_SALESMAN' && u.active
  );

  const [salesmanId, setSalesmanId] = useState(activeSalesmen[0]?.user_id || '');
  const [periodStart, setPeriodStart] = useState('2026-10-01');
  const [periodEnd, setPeriodEnd] = useState('2026-10-31');
  const [trialDays, setTrialDays] = useState(7);
  const [trialRate, setTrialRate] = useState(10);
  const [blockRate, setBlockRate] = useState(150);
  const [baseSalary, setBaseSalary] = useState(7000);
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);
  const [payingRecord, setPayingRecord] = useState<SalaryIncentive | null>(null);
  const [paymentRefInput, setPaymentRefInput] = useState('');
  const [payrollNonce, setPayrollNonce] = useState<string | null>(null);
  const [payNonce, setPayNonce] = useState<string | null>(null);
  const [approveNonces, setApproveNonces] = useState<Record<string, string>>({});

  if (!isOwnerAdmin && !isAuditor) {
    return (
      <div className="card notice-error">
        Access restricted: Confidential payroll &amp; salary records are restricted to Owner Admin (read-only audit permitted for Auditor).
      </div>
    );
  }

  const handleCalculate = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (writesLocked) {
      setNotice({ msg: 'Payroll calculation is locked until Owner authorization and storage gateway are active.', error: true });
      return;
    }

    if (!salesmanId) {
      setNotice({ msg: 'Please select a salesman.', error: true });
      return;
    }

    const activeNonce = payrollNonce || createSubmissionNonce('PAYCALC');
    if (!payrollNonce) setPayrollNonce(activeNonce);

    try {
      const generated = await calculatePayroll({
        period_start: periodStart,
        period_end: periodEnd,
        salesman_user_id: salesmanId,
        trial_days: Number(trialDays),
        trial_rate_per_kg: Number(trialRate),
        monthly_rate_per_100kg: Number(blockRate),
        base_salary: Number(baseSalary),
        idempotency_key: activeNonce,
      }, activeNonce);

      setPayrollNonce(null);
      if (!generated || generated.length === 0) {
        setNotice({
          msg: 'No new calculations were needed, or records for this period already exist.',
        });
      } else {
        setNotice({
          msg: `Calculated and saved ${generated.length} payroll item(s) successfully for period ${periodStart} to ${periodEnd}.`,
        });
      }
    } catch (err: unknown) {
      const errorMsg = isUnknownOutcomeError(err)
        ? 'Status not confirmed; do not submit a new transaction. Your inputs and retry key are preserved—retry Calculate payroll safely.'
        : err instanceof Error
        ? err.message
        : 'Calculation failed';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleApprove = async (item: SalaryIncentive) => {
    if (writesLocked) return;
    const activeNonce = approveNonces[item.record_id] || createSubmissionNonce('SALAPP');
    if (!approveNonces[item.record_id]) {
      setApproveNonces((prev) => ({ ...prev, [item.record_id]: activeNonce }));
    }
    try {
      await approveSalaryIncentive(item.record_id, undefined, activeNonce);
      setApproveNonces((prev) => {
        const next = { ...prev };
        delete next[item.record_id];
        return next;
      });
      setNotice({ msg: `Approved ${item.record_type} for ₹${item.calculated_amount}. Persisted to records.` });
    } catch (err: unknown) {
      const errorMsg = isUnknownOutcomeError(err)
        ? `Status not confirmed for ${item.record_id}; retry Approve safely with preserved key.`
        : err instanceof Error
        ? err.message
        : 'Approval failed';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const openPayDialog = (item: SalaryIncentive) => {
    setPayNonce(null);
    setPayingRecord(item);
    setPaymentRefInput(`NEFT-${new Date().toISOString().slice(2, 10).replace(/-/g, '')}-01`);
  };

  const handleConfirmPay = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!payingRecord || writesLocked) return;
    const cleanRef = paymentRefInput.trim();
    if (!cleanRef) {
      setNotice({ msg: 'Payment reference number is required.', error: true });
      return;
    }
    const activeNonce = payNonce || createSubmissionNonce('SALPAY');
    if (!payNonce) setPayNonce(activeNonce);
    try {
      await markSalaryIncentivePaid(payingRecord.record_id, cleanRef, activeNonce);
      setNotice({ msg: `Marked paid with reference: ${cleanRef}. Persisted to records.` });
      setPayNonce(null);
      setPayingRecord(null);
      setPaymentRefInput('');
    } catch (err: unknown) {
      const errorMsg = isUnknownOutcomeError(err)
        ? 'Status not confirmed; do not resubmit new payment. Retry Confirm Payment safely with preserved key.'
        : err instanceof Error
        ? err.message
        : 'Payment update failed';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  return (
    <div>
      <h1>Salary &amp; Sales Incentives Management</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      {isOwnerAdmin && (
        <div className="card">
          <h2>Calculate Salesman Payroll &amp; Incentives</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Rules include only issued, delivered, and fully paid sales with qualifying kilograms.
            Defaults: 7 trial days, ₹10/kg trial incentive, ₹150 per completed 100 kg volume block,
            ₹7,000 base salary.
          </p>

          <form className="inline" onSubmit={handleCalculate}>
            <label>
              Salesman
              <select
                required
                value={salesmanId}
                onChange={(e) => setSalesmanId(e.target.value)}
              >
                {activeSalesmen.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.full_name} ({u.user_id})
                  </option>
                ))}
              </select>
            </label>

            <label>
              Period start
              <input
                type="date"
                required
                value={periodStart}
                onChange={(e) => setPeriodStart(e.target.value)}
              />
            </label>

            <label>
              Period end
              <input
                type="date"
                required
                value={periodEnd}
                onChange={(e) => setPeriodEnd(e.target.value)}
              />
            </label>

            <label>
              Trial window (days)
              <input
                type="number"
                min="0"
                value={trialDays}
                onChange={(e) => setTrialDays(Number(e.target.value))}
              />
            </label>

            <label>
              Trial rate (₹/kg)
              <input
                type="number"
                min="0"
                step="0.5"
                value={trialRate}
                onChange={(e) => setTrialRate(Number(e.target.value))}
              />
            </label>

            <label>
              100kg block rate (₹)
              <input
                type="number"
                min="0"
                value={blockRate}
                onChange={(e) => setBlockRate(Number(e.target.value))}
              />
            </label>

            <label>
              Base monthly salary (₹)
              <input
                type="number"
                min="0"
                value={baseSalary}
                onChange={(e) => setBaseSalary(Number(e.target.value))}
              />
            </label>

            <div style={{ marginTop: '6px' }}>
              <button type="submit" disabled={writesLocked}>
                {writesLocked ? 'Writes Locked' : 'Calculate payroll'}
              </button>
            </div>
          </form>
        </div>
      )}

      {payingRecord && isOwnerAdmin && (
        <div className="card" style={{ border: '1px solid #166534', background: '#f0fdf4' }}>
          <h3 style={{ marginTop: 0 }}>
            Disburse Salary / Incentive: <code>{payingRecord.record_id}</code> (₹
            {Number(payingRecord.approved_amount || payingRecord.calculated_amount).toFixed(2)})
          </h3>
          <form className="inline" onSubmit={handleConfirmPay}>
            <label>
              Bank Transfer / NEFT / UPI Reference
              <input
                type="text"
                required
                value={paymentRefInput}
                onChange={(e) => setPaymentRefInput(e.target.value)}
                placeholder="e.g. NEFT-261119-01"
              />
            </label>
            <button type="submit" disabled={writesLocked}>
              Confirm Payment
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setPayNonce(null);
                setPayingRecord(null);
                setPaymentRefInput('');
              }}
            >
              Cancel
            </button>
          </form>
        </div>
      )}

      <div className="card">
        <div className="toolbar">
          <h2>
            Salary &amp; Incentive Register <span className="count">{salaryIncentives.length}</span>
          </h2>
        </div>

        {salaryIncentives.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Record ID</th>
                  <th>Period</th>
                  <th>Salesman</th>
                  <th>Type</th>
                  <th>Eligible kg</th>
                  <th>100kg Blocks</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Payment Ref</th>
                  {isOwnerAdmin && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {salaryIncentives.map((r) => (
                  <tr key={r.record_id}>
                    <td>
                      <code>{r.record_id}</code>
                    </td>
                    <td>
                      {r.period_start} to {r.period_end}
                    </td>
                    <td>{r.salesman_user_id}</td>
                    <td>
                      <span
                        style={{
                          fontSize: '0.8rem',
                          padding: '3px 7px',
                          borderRadius: '4px',
                          fontWeight: 700,
                          background:
                            r.record_type === 'BASE_SALARY'
                              ? '#dbeafe'
                              : r.record_type === 'TRIAL_INCENTIVE'
                              ? '#fef3c7'
                              : '#dcfce7',
                          color:
                            r.record_type === 'BASE_SALARY'
                              ? '#1e40af'
                              : r.record_type === 'TRIAL_INCENTIVE'
                              ? '#b45309'
                              : '#15803d',
                        }}
                      >
                        {r.record_type}
                      </span>
                    </td>
                    <td>{r.eligible_kg ? `${r.eligible_kg} kg` : '—'}</td>
                    <td>{r.completed_100kg_blocks || '—'}</td>
                    <td>
                      <strong>₹{Number(r.approved_amount || r.calculated_amount).toFixed(2)}</strong>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          r.paid_datetime
                            ? 'approved'
                            : r.approval_status === 'APPROVED'
                            ? 'on'
                            : 'pending'
                        }`}
                      >
                        {r.paid_datetime ? 'PAID' : r.approval_status}
                      </span>
                    </td>
                    <td className="muted">{r.payment_reference || '—'}</td>
                    {isOwnerAdmin && (
                      <td>
                        <div className="actions">
                          {(r.approval_status === 'PENDING' || r.approval_status === 'PROPOSED') && (
                            <button
                              className="secondary"
                              disabled={writesLocked}
                              style={{ padding: '3px 8px', fontSize: '0.78rem', background: '#dcfce7', color: '#166534' }}
                              onClick={() => handleApprove(r)}
                            >
                              Approve
                            </button>
                          )}
                          {r.approval_status === 'APPROVED' && !r.paid_datetime && (
                            <button
                              disabled={writesLocked}
                              style={{ padding: '3px 8px', fontSize: '0.78rem' }}
                              onClick={() => openPayDialog(r)}
                            >
                              Mark Paid
                            </button>
                          )}
                          {r.paid_datetime && (
                            <span style={{ fontSize: '0.8rem', color: '#166534', fontWeight: 600 }}>
                              ✓ Disbursed
                            </span>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No payroll records generated yet.</p>
        )}
      </div>
    </div>
  );
};
