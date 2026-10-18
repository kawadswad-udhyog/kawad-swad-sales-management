import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { StockTxnType } from '../types';

export const StockView: React.FC = () => {
  const {
    currentUser,
    users,
    products,
    companyStockSummary,
    salesmanStockSummary,
    stockTransactions,
    recordStockMovement,
    stockDiscrepancies,
    submitStockDiscrepancy,
    reviewStockDiscrepancy,
  } = useStore();

  const isManager = currentUser?.role === 'OWNER' || currentUser?.role === 'PA';
  const activeProducts = products.filter((p) => p.active);
  const activeSalesmen = users.filter((u) => u.role === 'SALESMAN' && u.active);

  const [txnType, setTxnType] = useState<StockTxnType>('COMPANY_RECEIPT');
  const [productId, setProductId] = useState(activeProducts[0]?.product_id || '');
  const [salesmanId, setSalesmanId] = useState(activeSalesmen[0]?.user_id || '');
  const [quantity, setQuantity] = useState<number>(10);
  const [notes, setNotes] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  // Stock Discrepancy Form State
  const [discLocation, setDiscLocation] = useState('COMPANY_WAREHOUSE');
  const [discProductId, setDiscProductId] = useState(activeProducts[0]?.product_id || '');
  const [discExpected, setDiscExpected] = useState<number>(0);
  const [discPhysical, setDiscPhysical] = useState<number>(0);
  const [discReason, setDiscReason] = useState('');

  const needsSalesman = ['ISSUED', 'RETURNED', 'SOLD', 'SALESMAN_ADJUSTMENT'].includes(txnType);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (quantity <= 0) {
      setNotice({ msg: 'Quantity must be greater than 0.', error: true });
      return;
    }

    try {
      await recordStockMovement({
        txn_type: txnType,
        product_id: productId,
        salesman_user_id: needsSalesman ? salesmanId : '',
        quantity: Number(quantity),
        notes: notes.trim(),
      });

      setNotice({ msg: `Stock movement "${txnType}" recorded successfully.` });
      setNotes('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to record stock movement';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleDiscrepancySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);
    if (!discProductId) {
      setNotice({ msg: 'Select a product for audit discrepancy check.', error: true });
      return;
    }
    try {
      await submitStockDiscrepancy({
        location: discLocation,
        product_id: discProductId,
        expected_stock: Number(discExpected),
        physical_count: Number(discPhysical),
        reason: discReason.trim() || 'Physical stock audit reconciliation',
      });
      setNotice({ msg: 'Stock physical count submitted for review. Unexplained differences are preserved for verification and not treated as automatic losses.' });
      setDiscReason('');
    } catch (err: unknown) {
      const errStr = err instanceof Error ? err.message : String(err);
      setNotice({ msg: `Failed to submit discrepancy: ${errStr}`, error: true });
    }
  };

  const handleReview = async (discrepancyId: string, action: 'APPROVE' | 'REJECT') => {
    try {
      await reviewStockDiscrepancy(discrepancyId, action, action === 'APPROVE' ? 'Approved in physical audit' : 'Rejected');
      setNotice({ msg: `Discrepancy ${action === 'APPROVE' ? 'approved and stock adjusted' : 'rejected'}.` });
    } catch (err: unknown) {
      const errStr = err instanceof Error ? err.message : String(err);
      setNotice({ msg: `Review failed: ${errStr}`, error: true });
    }
  };

  // Filter salesman stock & ledger for salesman role
  const visibleSalesmanStock = currentUser?.role === 'SALESMAN'
    ? salesmanStockSummary.filter((s) => s.salesman_user_id === currentUser.user_id)
    : salesmanStockSummary;

  const visibleTransactions = currentUser?.role === 'SALESMAN'
    ? stockTransactions.filter((t) => t.salesman_user_id === currentUser.user_id)
    : stockTransactions;

  return (
    <div>
      <h1>Company &amp; Salesman Stock</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      <div className="card">
        <p className="muted" style={{ marginTop: 0 }}>
          Stock is calculated strictly from the immutable stock ledger. Enter an opening quantity as a
          Company receipt before issuing stock to salesmen. All quantities use the product's configured
          selling unit.
        </p>

        {isManager ? (
          <>
            <h2>Record stock movement</h2>
            <form className="inline" onSubmit={handleSubmit}>
              <label>
                Movement
                <select
                  value={txnType}
                  onChange={(e) => setTxnType(e.target.value as StockTxnType)}
                >
                  <option value="COMPANY_RECEIPT">Company stock received / opening</option>
                  <option value="ISSUED">Issue to salesman</option>
                  <option value="RETURNED">Return from salesman</option>
                  <option value="COMPANY_ADJUSTMENT">Company stock positive adjustment</option>
                  <option value="SALESMAN_ADJUSTMENT">Salesman stock positive adjustment</option>
                </select>
              </label>

              <label>
                Product
                <select
                  required
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                >
                  {activeProducts.map((p) => (
                    <option key={p.product_id} value={p.product_id}>
                      {p.sku} · {p.product_name} ({p.pack_weight_g}g)
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Salesman
                <select
                  value={salesmanId}
                  onChange={(e) => setSalesmanId(e.target.value)}
                  disabled={!needsSalesman}
                  required={needsSalesman}
                >
                  {activeSalesmen.map((u) => (
                    <option key={u.user_id} value={u.user_id}>
                      {u.full_name} ({u.user_id})
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Quantity
                <input
                  type="number"
                  min="0.001"
                  step="0.001"
                  required
                  value={quantity}
                  onChange={(e) => setQuantity(Number(e.target.value))}
                />
              </label>

              <label style={{ gridColumn: 'span 2' }}>
                Notes / reference
                <input
                  maxLength={500}
                  placeholder="Opening stock, challan #, return voucher note..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </label>

              <div style={{ marginTop: '6px' }}>
                <button type="submit">Record movement</button>
              </div>
            </form>
          </>
        ) : (
          <p className="muted">
            You are logged in as a Field Salesman. You can view your currently assigned stock balance and
            recent transactions below.
          </p>
        )}
      </div>

      <div className="card">
        <h2>Company Stock</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Product</th>
                <th>Pack Weight</th>
                <th>Available Company Stock</th>
              </tr>
            </thead>
            <tbody>
              {companyStockSummary.map((item) => (
                <tr key={item.product_id}>
                  <td>
                    <strong>{item.sku}</strong>
                  </td>
                  <td>{item.product_name}</td>
                  <td>{item.pack_weight_g}g</td>
                  <td>
                    <span
                      style={{
                        fontWeight: 700,
                        color: item.company_quantity > 0 ? '#176b52' : '#b42318',
                      }}
                    >
                      {item.company_quantity}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Salesman Stock In-Hand</h2>
        {visibleSalesmanStock.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Salesman</th>
                  <th>SKU</th>
                  <th>Product</th>
                  <th>Balance</th>
                </tr>
              </thead>
              <tbody>
                {visibleSalesmanStock.map((s, idx) => (
                  <tr key={idx}>
                    <td>
                      <strong>{s.salesman_name}</strong>
                    </td>
                    <td>{s.sku}</td>
                    <td>{s.product_name}</td>
                    <td>
                      <span className="badge on">{s.quantity} pkts</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No current salesman stock balances assigned.</p>
        )}
      </div>

      {/* Physical Stock Audit & Discrepancies Section */}
      <div className="card">
        <h2>Physical Stock Audit &amp; Discrepancy Workflow</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Reconcile physical inventory counts against expected ledger balances. Differences remain pending review and are never automatically marked as losses without Owner/PA approval.
        </p>

        <form className="inline" onSubmit={handleDiscrepancySubmit} style={{ marginBottom: '16px' }}>
          <label>
            Location
            <select value={discLocation} onChange={(e) => setDiscLocation(e.target.value)}>
              <option value="COMPANY_WAREHOUSE">Company Central Warehouse</option>
              {activeSalesmen.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  Salesman: {u.full_name} ({u.user_id})
                </option>
              ))}
            </select>
          </label>

          <label>
            Product
            <select value={discProductId} onChange={(e) => setDiscProductId(e.target.value)}>
              {activeProducts.map((p) => (
                <option key={p.product_id} value={p.product_id}>
                  {p.sku} - {p.product_name} ({p.pack_weight_g}g)
                </option>
              ))}
            </select>
          </label>

          <label>
            Expected Count
            <input
              type="number"
              value={discExpected}
              onChange={(e) => setDiscExpected(Number(e.target.value))}
              placeholder="System expected"
            />
          </label>

          <label>
            Physical Count
            <input
              type="number"
              value={discPhysical}
              onChange={(e) => setDiscPhysical(Number(e.target.value))}
              placeholder="Actual counted"
            />
          </label>

          <label style={{ flex: '1 1 200px' }}>
            Explanation / Reason
            <input
              type="text"
              value={discReason}
              onChange={(e) => setDiscReason(e.target.value)}
              placeholder="e.g. Physical count post-market, batch recount"
            />
          </label>

          <button type="submit" style={{ alignSelf: 'flex-end', padding: '9px 18px' }}>
            📝 Record Physical Count
          </button>
        </form>

        {stockDiscrepancies && stockDiscrepancies.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Location</th>
                  <th>Product</th>
                  <th>Expected</th>
                  <th>Physical</th>
                  <th>Difference</th>
                  <th>Reason</th>
                  <th>Counted By</th>
                  <th>Status</th>
                  {isManager && <th>Action</th>}
                </tr>
              </thead>
              <tbody>
                {stockDiscrepancies.map((d: any) => {
                  const diff = Number(d.difference || 0);
                  const isPending = d.status === 'PENDING_APPROVAL';
                  return (
                    <tr key={d.discrepancy_id}>
                      <td>{d.discrepancy_date}</td>
                      <td>{d.location}</td>
                      <td>{d.product_name_snapshot}</td>
                      <td>{d.expected_stock}</td>
                      <td>{d.physical_count}</td>
                      <td>
                        <strong style={{ color: diff < 0 ? '#dc2626' : diff > 0 ? '#16a34a' : '#475569' }}>
                          {diff > 0 ? `+${diff}` : diff}
                        </strong>
                      </td>
                      <td className="muted">{d.reason || '—'}</td>
                      <td>{d.counted_by_user_id}</td>
                      <td>
                        <span
                          className={`badge ${d.status === 'APPROVED' ? 'on' : d.status === 'REJECTED' ? 'off' : ''}`}
                          style={{
                            background: isPending ? '#fef3c7' : undefined,
                            color: isPending ? '#b45309' : undefined,
                          }}
                        >
                          {d.status}
                        </span>
                      </td>
                      {isManager && (
                        <td>
                          {isPending ? (
                            <div className="actions" style={{ gap: '4px' }}>
                              <button
                                type="button"
                                style={{ padding: '3px 8px', fontSize: '0.75rem', background: '#16a34a', color: '#fff' }}
                                onClick={() => handleReview(d.discrepancy_id, 'APPROVE')}
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                className="secondary"
                                style={{ padding: '3px 8px', fontSize: '0.75rem', color: '#dc2626' }}
                                onClick={() => handleReview(d.discrepancy_id, 'REJECT')}
                              >
                                Reject
                              </button>
                            </div>
                          ) : (
                            <span className="muted" style={{ fontSize: '0.75rem' }}>Reviewed</span>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ padding: '8px 0' }}>No stock discrepancies reported yet. Expected counts match physical audit.</p>
        )}
      </div>

      <div className="card">
        <h2>Recent Stock Movements Ledger</h2>
        {visibleTransactions.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date/Time</th>
                  <th>Movement</th>
                  <th>SKU</th>
                  <th>Salesman</th>
                  <th>Quantity</th>
                  <th>Unit</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {visibleTransactions.slice(0, 50).map((t) => (
                  <tr key={t.stock_txn_id}>
                    <td>{new Date(t.txn_datetime).toLocaleString('en-IN')}</td>
                    <td>
                      <span
                        style={{
                          fontSize: '0.8rem',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontWeight: 700,
                          background:
                            t.txn_type === 'ISSUED'
                              ? '#e0f2fe'
                              : t.txn_type === 'COMPANY_RECEIPT'
                              ? '#dcfce7'
                              : '#fef3c7',
                          color:
                            t.txn_type === 'ISSUED'
                              ? '#0369a1'
                              : t.txn_type === 'COMPANY_RECEIPT'
                              ? '#15803d'
                              : '#b45309',
                        }}
                      >
                        {t.txn_type}
                      </span>
                    </td>
                    <td>{t.sku_snapshot}</td>
                    <td>{t.salesman_user_id || '—'}</td>
                    <td>
                      <strong>{t.quantity}</strong>
                    </td>
                    <td>{t.unit}</td>
                    <td className="muted">{t.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No stock transactions recorded yet.</p>
        )}
      </div>
    </div>
  );
};
