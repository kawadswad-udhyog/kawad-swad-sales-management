import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';

export const VisitsView: React.FC = () => {
  const { customers, shopVisits, addShopVisit, currentUser } = useStore();
  const activeCustomers = customers.filter((c) => c.active);

  const [customerId, setCustomerId] = useState(activeCustomers[0]?.customer_id || '');
  const [outcome, setOutcome] = useState('');
  const [orderTaken, setOrderTaken] = useState(false);
  const [followUpDate, setFollowUpDate] = useState('');
  const [nextAction, setNextAction] = useState('');
  const [notes, setNotes] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (!customerId) {
      setNotice({ msg: 'Please select a customer or shop.', error: true });
      return;
    }
    if (!outcome.trim()) {
      setNotice({ msg: 'Please describe the visit outcome.', error: true });
      return;
    }

    try {
      addShopVisit({
        customer_id: customerId,
        visit_outcome: outcome.trim(),
        order_taken: orderTaken,
        follow_up_date: followUpDate,
        next_action: nextAction.trim(),
        notes: notes.trim(),
      });

      setNotice({ msg: 'Shop visit recorded successfully.' });
      setOutcome('');
      setNextAction('');
      setFollowUpDate('');
      setOrderTaken(false);
      setNotes('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to record visit';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const visibleVisits = currentUser?.role === 'SALESMAN'
    ? shopVisits.filter((v) => v.salesman_user_id === currentUser.user_id)
    : shopVisits;

  return (
    <div>
      <h1>Shop Visits &amp; Follow-ups</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      <div className="card">
        <h2>Record shop visit</h2>
        <form className="inline" onSubmit={handleSubmit}>
          <label>
            Shop / customer
            <select
              required
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
            >
              {activeCustomers.map((c) => (
                <option key={c.customer_id} value={c.customer_id}>
                  {c.shop_name} ({c.locality_area || c.city})
                </option>
              ))}
            </select>
          </label>

          <label>
            Visit outcome
            <input
              required
              placeholder="Order placed / follow-up / shop closed / stock full"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            />
          </label>

          <label>
            Order taken?
            <select
              value={orderTaken ? 'true' : 'false'}
              onChange={(e) => setOrderTaken(e.target.value === 'true')}
            >
              <option value="false">No</option>
              <option value="true">Yes</option>
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

          <label style={{ gridColumn: 'span 2' }}>
            Next action
            <input
              placeholder="e.g. Bring marketing stand, deliver 500g family pack samples..."
              value={nextAction}
              onChange={(e) => setNextAction(e.target.value)}
            />
          </label>

          <label style={{ gridColumn: 'span 2' }}>
            Notes
            <input
              placeholder="Additional feedback or notes..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>

          <div style={{ gridColumn: 'span 2', marginTop: '6px' }}>
            <button type="submit">Save visit</button>
          </div>
        </form>
      </div>

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
                  <th>Date & Time</th>
                  <th>Shop</th>
                  <th>Outcome</th>
                  <th>Order Taken</th>
                  <th>Follow-up Date</th>
                  <th>Next Action</th>
                  <th>Salesman</th>
                </tr>
              </thead>
              <tbody>
                {visibleVisits.map((v) => (
                  <tr key={v.visit_id}>
                    <td>{new Date(v.visit_datetime).toLocaleString('en-IN')}</td>
                    <td>
                      <strong>{v.shop_name_snapshot}</strong>
                    </td>
                    <td>{v.visit_outcome}</td>
                    <td>
                      <span className={`badge ${v.order_taken ? 'on' : 'off'}`}>
                        {v.order_taken ? 'Yes' : 'No'}
                      </span>
                    </td>
                    <td>{v.follow_up_date || '—'}</td>
                    <td>{v.next_action || '—'}</td>
                    <td>{v.salesman_user_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No shop visits recorded yet.</p>
        )}
      </div>
    </div>
  );
};
