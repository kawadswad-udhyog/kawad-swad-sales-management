import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { DailyClosing } from '../types';

export const ClosingView: React.FC = () => {
  const {
    currentUser,
    dailyClosings,
    getTodayClosingMetrics,
    submitDailyClosing,
    reviewDailyClosing,
  } = useStore();

  const isManager = currentUser?.role === 'OWNER' || currentUser?.role === 'PA';
  const currentSalesmanId = currentUser?.user_id || 'USR-SALES-001';

  const [openingCash, setOpeningCash] = useState<number>(500);
  const [physicalCashReturned, setPhysicalCashReturned] = useState<number>(500);
  const [notes, setNotes] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  // Live metrics for today
  const metrics = getTodayClosingMetrics(currentSalesmanId);
  const liveExpectedReturn = Math.max(
    0,
    openingCash + metrics.cash_collected - metrics.approved_cash_expenses
  );
  const liveDifference = physicalCashReturned - liveExpectedReturn;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    try {
      const closing = await submitDailyClosing({
        opening_cash: Number(openingCash),
        physical_cash_returned: Number(physicalCashReturned),
        notes: notes.trim(),
      });

      setNotice({
        msg: `Daily closing #${closing.closing_id} submitted with difference: ₹${closing.cash_difference.toFixed(2)}.`,
      });
      setNotes('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to submit daily closing';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleReview = async (closing: DailyClosing, decision: 'CONFIRMED' | 'CORRECTION_REQUIRED') => {
    const reviewNote = window.prompt(
      decision === 'CONFIRMED'
        ? 'Confirm daily closing? (Optional notes):'
        : 'Please enter details of the required correction:'
    );
    if (decision === 'CORRECTION_REQUIRED' && !reviewNote) {
      setNotice({ msg: 'A note explaining the discrepancy is required.', error: true });
      return;
    }
    try {
      await reviewDailyClosing(closing.closing_id, decision, reviewNote || '');
      setNotice({ msg: `Daily closing #${closing.closing_id} marked as ${decision}.` });
    } catch (err: unknown) {
      setNotice({ msg: err instanceof Error ? err.message : 'Closing review was not saved.', error: true });
    }
  };

  const visibleClosings = currentUser?.role === 'SALESMAN'
    ? dailyClosings.filter((c) => c.salesman_user_id === currentUser.user_id)
    : dailyClosings;

  return (
    <div>
      <h1>Daily Cash Closing &amp; Shift Reconciliation</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      <div className="card">
        <h2>Submit Day-End Cash Closing</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Cash due back is automatically calculated: <strong>Opening Cash + Today's Paid Cash Collections - Approved Cash Expenses</strong>.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="grid" style={{ marginBottom: '16px' }}>
            <div className="metric">
              <span>Opening Cash (Float)</span>
              <strong style={{ fontSize: '1.2rem' }}>₹{Number(openingCash).toFixed(2)}</strong>
            </div>
            <div className="metric">
              <span>Today's Cash Collected</span>
              <strong style={{ fontSize: '1.2rem' }}>₹{metrics.cash_collected.toFixed(2)}</strong>
            </div>
            <div className="metric">
              <span>Approved Cash Expenses</span>
              <strong style={{ fontSize: '1.2rem', color: '#b42318' }}>
                -₹{metrics.approved_cash_expenses.toFixed(2)}
              </strong>
            </div>
            <div className="metric" style={{ background: '#edf4f1' }}>
              <span>Expected Cash Return</span>
              <strong style={{ fontSize: '1.4rem', color: '#176b52' }}>
                ₹{liveExpectedReturn.toFixed(2)}
              </strong>
            </div>
          </div>

          <div className="inline">
            <label>
              Opening cash ₹
              <input
                type="number"
                min="0"
                step="0.01"
                required
                value={openingCash}
                onChange={(e) => setOpeningCash(Number(e.target.value))}
              />
            </label>

            <label>
              Physical cash returned ₹
              <input
                type="number"
                min="0"
                step="0.01"
                required
                value={physicalCashReturned}
                onChange={(e) => setPhysicalCashReturned(Number(e.target.value))}
              />
            </label>

            <div className="metric" style={{ margin: 0, padding: '10px 14px' }}>
              <span>Calculated Difference</span>
              <strong
                style={{
                  fontSize: '1.2rem',
                  color: liveDifference === 0 ? '#176b52' : liveDifference > 0 ? '#0369a1' : '#b42318',
                }}
              >
                {liveDifference > 0 ? `+₹${liveDifference.toFixed(2)} (Surplus)` : liveDifference < 0 ? `-₹${Math.abs(liveDifference).toFixed(2)} (Shortage)` : '₹0.00 (Exact Match)'}
              </strong>
            </div>
          </div>

          <div style={{ marginTop: '14px' }}>
            <label>
              Closing notes
              <input
                maxLength={500}
                placeholder="Denomination details, explanation for discrepancy (if any)..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </label>
          </div>

          <div style={{ marginTop: '16px' }}>
            <button type="submit">Submit daily cash closing</button>
          </div>
        </form>
      </div>

      <div className="card">
        <div className="toolbar">
          <h2>
            Closing History <span className="count">{visibleClosings.length}</span>
          </h2>
        </div>

        {visibleClosings.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Closing ID</th>
                  <th>Date</th>
                  <th>Salesman</th>
                  <th>Opening</th>
                  <th>Cash Collected</th>
                  <th>Approved Exp</th>
                  <th>Expected Return</th>
                  <th>Physical Cash</th>
                  <th>Difference</th>
                  <th>Status</th>
                  {isManager && <th>Manager Review</th>}
                </tr>
              </thead>
              <tbody>
                {visibleClosings.map((c) => (
                  <tr key={c.closing_id}>
                    <td>
                      <code>{c.closing_id}</code>
                    </td>
                    <td>{c.closing_date}</td>
                    <td>{c.salesman_user_id}</td>
                    <td>₹{c.opening_cash.toFixed(2)}</td>
                    <td>₹{c.cash_collected.toFixed(2)}</td>
                    <td>₹{c.approved_cash_expenses.toFixed(2)}</td>
                    <td>
                      <strong>₹{c.expected_cash_return.toFixed(2)}</strong>
                    </td>
                    <td>
                      <strong>₹{c.physical_cash_returned.toFixed(2)}</strong>
                    </td>
                    <td>
                      <span
                        style={{
                          fontWeight: 700,
                          color: c.cash_difference === 0 ? '#176b52' : '#b42318',
                        }}
                      >
                        ₹{c.cash_difference.toFixed(2)}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          c.closing_status === 'CONFIRMED'
                            ? 'approved'
                            : c.closing_status === 'CORRECTION_REQUIRED'
                            ? 'rejected'
                            : 'pending'
                        }`}
                      >
                        {c.closing_status}
                      </span>
                    </td>
                    {isManager && (
                      <td>
                        {c.closing_status === 'SUBMITTED' ? (
                          <div className="actions">
                            <button
                              className="secondary"
                              style={{ padding: '3px 8px', fontSize: '0.78rem', background: '#dcfce7', color: '#166534' }}
                              onClick={() => handleReview(c, 'CONFIRMED')}
                            >
                              Confirm
                            </button>
                            <button
                              className="secondary"
                              style={{ padding: '3px 8px', fontSize: '0.78rem', background: '#fee2e2', color: '#991b1b' }}
                              onClick={() => handleReview(c, 'CORRECTION_REQUIRED')}
                            >
                              Needs Correction
                            </button>
                          </div>
                        ) : (
                          <span className="muted" style={{ fontSize: '0.8rem' }}>
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
        ) : (
          <p className="muted">No daily closing records submitted yet.</p>
        )}
      </div>
    </div>
  );
};
