import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { SalaryIncentive } from '../types';

export const SalaryView: React.FC = () => {
  const {
    users,
    salaryIncentives,
    calculatePayroll,
    approveSalaryIncentive,
    markSalaryIncentivePaid,
  } = useStore();

  const activeSalesmen = users.filter((u) => u.role === 'SALESMAN' && u.active);

  const [salesmanId, setSalesmanId] = useState(activeSalesmen[0]?.user_id || '');
  const [periodStart, setPeriodStart] = useState('2026-10-01');
  const [periodEnd, setPeriodEnd] = useState('2026-10-31');
  const [trialDays, setTrialDays] = useState(7);
  const [trialRate, setTrialRate] = useState(10);
  const [blockRate, setBlockRate] = useState(150);
  const [baseSalary, setBaseSalary] = useState(7000);
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  const handleCalculate = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (!salesmanId) {
      setNotice({ msg: 'Please select a salesman.', error: true });
      return;
    }

    try {
      const generated = await calculatePayroll({
        period_start: periodStart,
        period_end: periodEnd,
        salesman_user_id: salesmanId,
        trial_days: Number(trialDays),
        trial_rate_per_kg: Number(trialRate),
        monthly_rate_per_100kg: Number(blockRate),
        base_salary: Number(baseSalary),
      });

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
      const errorMsg = err instanceof Error ? err.message : 'Calculation failed';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleApprove = async (item: SalaryIncentive) => {
    await approveSalaryIncentive(item.record_id);
    setNotice({ msg: `Approved ${item.record_type} for ₹${item.calculated_amount}. Persisted to records.` });
  };

  const handlePay = async (item: SalaryIncentive) => {
    const ref = window.prompt(
      'Enter bank transfer / NEFT / UPI payment reference:',
      `NEFT-${new Date().toISOString().slice(2, 10).replace(/-/g, '')}-01`
    );
    if (!ref || !ref.trim()) return;

    await markSalaryIncentivePaid(item.record_id, ref.trim());
    setNotice({ msg: `Marked paid with reference: ${ref.trim()}. Persisted to records.` });
  };

  return (
    <div>
      <h1>Salary &amp; Sales Incentives Management</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

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
            <button type="submit">Calculate payroll</button>
          </div>
        </form>
      </div>

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
                  <th>Actions</th>
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
                    <td>
                      <div className="actions">
                        {r.approval_status === 'PENDING' && (
                          <button
                            className="secondary"
                            style={{ padding: '3px 8px', fontSize: '0.78rem', background: '#dcfce7', color: '#166534' }}
                            onClick={() => handleApprove(r)}
                          >
                            Approve
                          </button>
                        )}
                        {r.approval_status === 'APPROVED' && !r.paid_datetime && (
                          <button
                            style={{ padding: '3px 8px', fontSize: '0.78rem' }}
                            onClick={() => handlePay(r)}
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
