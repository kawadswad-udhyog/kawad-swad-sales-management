import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { Expense } from '../types';

const COMMON_EXPENSE_DESCRIPTIONS = [
  'Motorcycle Petrol / Fuel',
  'Vehicle Puncture / Repair',
  'Lunch / Refreshment',
  'Cartage / Auto Delivery',
  'Packing Tape & Stationery',
  'Mobile Calls / Data',
];

const CATEGORIES: Array<{ key: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL'; label: string; icon: string }> = [
  { key: 'TRAVEL', label: 'Travel / Fuel', icon: '⛽' },
  { key: 'DELIVERY', label: 'Delivery', icon: '📦' },
  { key: 'OTHER', label: 'Other', icon: '📝' },
  { key: 'DIGITAL', label: 'Digital (Non-cash)', icon: '💳' },
];

export const ExpensesView: React.FC = () => {
  const { expenses, submitExpense, approveExpense, rejectExpense, currentUser } = useStore();
  const isManager = currentUser?.role === 'OWNER' || currentUser?.role === 'PA';

  const [category, setCategory] = useState<'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL'>('TRAVEL');
  const [amount, setAmount] = useState<number>(100);
  const [description, setDescription] = useState('');
  const [receiptRef, setReceiptRef] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('ALL');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (amount <= 0) {
      setNotice({ msg: 'Expense amount must be greater than 0.', error: true });
      return;
    }
    if (!description.trim()) {
      setNotice({ msg: 'Please enter a description for the expense.', error: true });
      return;
    }

    try {
      submitExpense({
        category,
        amount: Number(amount),
        description: description.trim(),
        receipt_link_or_file_ref: receiptRef.trim(),
      });

      setNotice({ msg: `✅ Expense of ₹${amount} submitted for manager review and approval.` });
      setDescription('');
      setReceiptRef('');
      setAmount(100);
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to submit expense';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleApprove = (e: Expense) => {
    approveExpense(e.expense_id, 'Approved by manager');
    setNotice({ msg: `Expense ${e.expense_id} approved. Marked as cash-reducing.` });
  };

  const handleReject = (e: Expense) => {
    const reason = window.prompt('Please provide a reason for rejecting this expense:');
    if (!reason || !reason.trim()) {
      setNotice({ msg: 'A reason is required to reject an expense.', error: true });
      return;
    }
    rejectExpense(e.expense_id, reason.trim());
    setNotice({ msg: `Expense ${e.expense_id} rejected.` });
  };

  // Filter based on user role
  const userExpenses = currentUser?.role === 'SALESMAN'
    ? expenses.filter(
        (e) =>
          e.submitted_by_user_id === currentUser.user_id ||
          e.salesman_user_id === currentUser.user_id
      )
    : expenses;

  const filteredExpenses = userExpenses.filter((e) => {
    if (filterStatus === 'ALL') return true;
    return e.approval_status === filterStatus;
  });

  return (
    <div>
      <h1>Expenses &amp; Approval Register</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      <div className="card">
        <h2>Submit Field Expense</h2>

        {/* Category Buttons */}
        <div style={{ marginBottom: '14px' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px' }}>
            Category
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px' }}>
            {CATEGORIES.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => setCategory(c.key)}
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: category === c.key ? '2px solid #0f766e' : '1px solid #cbd5e1',
                  background: category === c.key ? '#f0fdfa' : '#ffffff',
                  color: category === c.key ? '#115e59' : '#334155',
                  fontWeight: category === c.key ? 700 : 500,
                  cursor: 'pointer',
                  textAlign: 'center',
                }}
              >
                <span style={{ fontSize: '1.2rem', display: 'block', marginBottom: '2px' }}>{c.icon}</span>
                {c.label}
              </button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Quick Amount Selector */}
          <div style={{ marginBottom: '14px' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px' }}>
              Amount ₹
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '6px' }}>
              <input
                type="number"
                min="1"
                step="1"
                required
                value={amount || ''}
                onChange={(e) => setAmount(Number(e.target.value))}
                style={{ width: '130px', fontSize: '1.1rem', fontWeight: 700, padding: '7px 10px' }}
              />
              <button
                type="button"
                className="secondary"
                onClick={() => setAmount(50)}
                style={{ padding: '6px 12px', fontSize: '0.82rem' }}
              >
                ₹50
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setAmount(100)}
                style={{ padding: '6px 12px', fontSize: '0.82rem' }}
              >
                ₹100
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setAmount(200)}
                style={{ padding: '6px 12px', fontSize: '0.82rem' }}
              >
                ₹200
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setAmount(500)}
                style={{ padding: '6px 12px', fontSize: '0.82rem' }}
              >
                ₹500
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setAmount((prev) => prev + 50)}
                style={{ padding: '6px 10px', fontSize: '0.82rem' }}
              >
                +₹50
              </button>
            </div>
          </div>

          {/* Common Description Shortcuts */}
          <div style={{ marginBottom: '14px' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px' }}>
              Description (One-Tap Shortcuts)
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
              {COMMON_EXPENSE_DESCRIPTIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDescription(d)}
                  style={{
                    padding: '4px 10px',
                    fontSize: '0.78rem',
                    borderRadius: '14px',
                    border: description === d ? '1px solid #0f766e' : '1px solid #cbd5e1',
                    background: description === d ? '#ccfbf1' : '#f8fafc',
                    color: description === d ? '#115e59' : '#475569',
                    cursor: 'pointer',
                  }}
                >
                  {d}
                </button>
              ))}
            </div>
            <input
              required
              placeholder="e.g. Motorcycle petrol, Bus cartage slip, packing tape..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: '4px' }}>
                Receipt Link / File Ref / Slip Number (Optional)
              </span>
              <input
                placeholder="e.g. SLIP-1029, Fuel bill link, receipt note..."
                value={receiptRef}
                onChange={(e) => setReceiptRef(e.target.value)}
                style={{ width: '100%' }}
              />
            </label>
          </div>

          <button type="submit" style={{ padding: '10px 20px', fontSize: '0.95rem' }}>
            📤 Submit Expense for Approval
          </button>
        </form>

        <p className="muted" style={{ marginTop: '12px' }}>
          New submissions start as PENDING. Approved cash expenses automatically reduce physical cash due back
          during evening closing.
        </p>
      </div>

      <div className="card">
        <div className="toolbar" style={{ flexWrap: 'wrap', gap: '8px' }}>
          <h2>
            Expenses Register <span className="count">{filteredExpenses.length}</span>
          </h2>
          <div className="actions">
            <button
              type="button"
              className={filterStatus === 'ALL' ? '' : 'secondary'}
              onClick={() => setFilterStatus('ALL')}
              style={{ padding: '4px 10px', fontSize: '0.8rem' }}
            >
              All
            </button>
            <button
              type="button"
              className={filterStatus === 'PENDING' ? '' : 'secondary'}
              onClick={() => setFilterStatus('PENDING')}
              style={{ padding: '4px 10px', fontSize: '0.8rem' }}
            >
              Pending
            </button>
            <button
              type="button"
              className={filterStatus === 'APPROVED' ? '' : 'secondary'}
              onClick={() => setFilterStatus('APPROVED')}
              style={{ padding: '4px 10px', fontSize: '0.8rem' }}
            >
              Approved
            </button>
          </div>
        </div>

        {filteredExpenses.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Salesman</th>
                  <th>Category</th>
                  <th>Amount</th>
                  <th>Description</th>
                  <th>Status</th>
                  {isManager && <th>Review Action</th>}
                </tr>
              </thead>
              <tbody>
                {filteredExpenses.map((exp) => (
                  <tr key={exp.expense_id}>
                    <td>{new Date(exp.expense_datetime).toLocaleDateString('en-IN')}</td>
                    <td>{exp.salesman_user_id}</td>
                    <td>
                      <span style={{ fontSize: '0.8rem', background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>
                        {exp.category}
                      </span>
                    </td>
                    <td>
                      <strong style={{ color: '#b91c1c' }}>₹{exp.amount.toFixed(2)}</strong>
                    </td>
                    <td>
                      {exp.description}
                      {exp.receipt_link_or_file_ref && (
                        <div className="muted" style={{ fontSize: '0.75rem' }}>
                          Ref: {exp.receipt_link_or_file_ref}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${exp.approval_status === 'APPROVED' ? 'on' : ''}`}>
                        {exp.approval_status}
                      </span>
                    </td>
                    {isManager && (
                      <td>
                        {exp.approval_status === 'PENDING' && (
                          <div className="actions">
                            <button
                              type="button"
                              onClick={() => handleApprove(exp)}
                              style={{ padding: '3px 8px', fontSize: '0.78rem', background: '#16a34a', color: '#fff' }}
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => handleReject(exp)}
                              style={{ padding: '3px 8px', fontSize: '0.78rem', color: '#dc2626' }}
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
        ) : (
          <p className="muted">No expenses recorded for this filter.</p>
        )}
      </div>
    </div>
  );
};
