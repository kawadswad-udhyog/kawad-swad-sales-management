import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { Expense } from '../types';

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

    try {
      submitExpense({
        category,
        amount: Number(amount),
        description: description.trim(),
        receipt_link_or_file_ref: receiptRef.trim(),
      });

      setNotice({ msg: 'Expense submitted for review and approval.' });
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
      <h1>Expenses & Approval Register</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      <div className="card">
        <h2>Submit field expense</h2>
        <form className="inline" onSubmit={handleSubmit}>
          <label>
            Category
            <select
              value={category}
              onChange={(e) =>
                setCategory(e.target.value as 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL')
              }
            >
              <option value="TRAVEL">TRAVEL</option>
              <option value="DELIVERY">DELIVERY</option>
              <option value="OTHER">OTHER</option>
              <option value="DIGITAL">DIGITAL (Non-cash)</option>
            </select>
          </label>

          <label>
            Amount ₹
            <input
              type="number"
              min="0.01"
              step="0.01"
              required
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
            />
          </label>

          <label style={{ gridColumn: 'span 2' }}>
            Description
            <input
              required
              placeholder="e.g. Motorcycle petrol, Bus cartage slip, packing tape..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <label style={{ gridColumn: 'span 2' }}>
            Receipt link / file ref
            <input
              placeholder="e.g. SLIP-1029, Fuel bill link..."
              value={receiptRef}
              onChange={(e) => setReceiptRef(e.target.value)}
            />
          </label>

          <div style={{ gridColumn: 'span 2', marginTop: '6px' }}>
            <button type="submit">Submit expense for approval</button>
          </div>
        </form>
        <p className="muted">
          New submissions start as PENDING. Only approved cash expenses reduce physical cash due back
          during evening closing.
        </p>
      </div>

      <div className="card">
        <div className="toolbar">
          <h2>
            Expense Register <span className="count">{filteredExpenses.length}</span>
          </h2>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', color: '#66746f' }}>Filter:</span>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              style={{ width: 'auto', margin: 0, padding: '6px 10px' }}
            >
              <option value="ALL">All Statuses</option>
              <option value="PENDING">Pending Approval</option>
              <option value="APPROVED">Approved</option>
              <option value="REJECTED">Rejected</option>
            </select>
          </div>
        </div>

        {filteredExpenses.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Date</th>
                  <th>Submitter</th>
                  <th>Category</th>
                  <th>Amount</th>
                  <th>Description</th>
                  <th>Receipt Ref</th>
                  <th>Status</th>
                  <th>Cash-reducing?</th>
                  {isManager && <th>Review Actions</th>}
                </tr>
              </thead>
              <tbody>
                {filteredExpenses.map((exp) => (
                  <tr key={exp.expense_id}>
                    <td>
                      <code>{exp.expense_id}</code>
                    </td>
                    <td>{new Date(exp.expense_datetime).toLocaleDateString('en-IN')}</td>
                    <td>{exp.salesman_user_id || exp.submitted_by_user_id}</td>
                    <td>{exp.category}</td>
                    <td>
                      <strong>₹{Number(exp.amount).toFixed(2)}</strong>
                    </td>
                    <td>{exp.description}</td>
                    <td className="muted">{exp.receipt_link_or_file_ref || '—'}</td>
                    <td>
                      <span
                        className={`badge ${
                          exp.approval_status === 'APPROVED'
                            ? 'approved'
                            : exp.approval_status === 'REJECTED'
                            ? 'rejected'
                            : 'pending'
                        }`}
                      >
                        {exp.approval_status}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                        {exp.cash_reducing_expense ? '✓ Yes' : '✗ No'}
                      </span>
                    </td>
                    {isManager && (
                      <td>
                        {exp.approval_status === 'PENDING' ? (
                          <div className="actions">
                            <button
                              className="secondary"
                              style={{ padding: '3px 8px', fontSize: '0.78rem', background: '#dcfce7', color: '#166534' }}
                              onClick={() => handleApprove(exp)}
                            >
                              Approve
                            </button>
                            <button
                              className="secondary"
                              style={{ padding: '3px 8px', fontSize: '0.78rem', background: '#fee2e2', color: '#991b1b' }}
                              onClick={() => handleReject(exp)}
                            >
                              Reject
                            </button>
                          </div>
                        ) : (
                          <div>
                            <span className="muted" style={{ fontSize: '0.8rem' }}>
                              {exp.approved_by_user_id ? `By ${exp.approved_by_user_id}` : 'Closed'}
                            </span>
                            {exp.notes && (
                              <div style={{ fontSize: '0.75rem', color: '#66746f' }}>
                                Reason: {exp.notes}
                              </div>
                            )}
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
          <p className="muted">No expenses found matching this filter.</p>
        )}
      </div>
    </div>
  );
};
