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

  const needsSalesman = ['ISSUED', 'RETURNED', 'SOLD', 'SALESMAN_ADJUSTMENT'].includes(txnType);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (quantity <= 0) {
      setNotice({ msg: 'Quantity must be greater than 0.', error: true });
      return;
    }

    try {
      recordStockMovement({
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
                  <option value="SOLD">Record salesman sale movement</option>
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
