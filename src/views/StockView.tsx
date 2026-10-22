import React, { useState, useEffect, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { StockTxnType, FinishedGoodsRegisterItem, FinishedGoodsRegisterSummary } from '../types';
import { apiRequest } from '../services/api';
import { exportSheetToExcel } from '../utils/exportToExcel';

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
    refreshData,
  } = useStore();

  const isManager = currentUser?.role === 'OWNER' || currentUser?.role === 'PA';
  const activeProducts = products.filter((p) => p.active);
  const activeSalesmen = users.filter((u) => u.role === 'SALESMAN' && u.active);

  const [stockTab, setStockTab] = useState<'register' | 'movements' | 'physical'>('register');
  const [registerItems, setRegisterItems] = useState<FinishedGoodsRegisterItem[]>([]);
  const [registerSummary, setRegisterSummary] = useState<FinishedGoodsRegisterSummary | null>(null);
  const [registerLoading, setRegisterLoading] = useState(false);
  const [registerSearch, setRegisterSearch] = useState('');
  const [registerFamily, setRegisterFamily] = useState('ALL');
  const [registerPackWeight, setRegisterPackWeight] = useState('ALL');
  const [hideZeroStock, setHideZeroStock] = useState(false);

  // Opening / Physical Reconciliation State
  const [reconLocation, setReconLocation] = useState<'FACTORY' | 'WAREHOUSE' | string>('WAREHOUSE');
  const [reconProductId, setReconProductId] = useState(activeProducts[0]?.product_id || '');
  const [reconPhysicalCount, setReconPhysicalCount] = useState<number>(0);
  const [reconReason, setReconReason] = useState('');
  const [reconReference, setReconReference] = useState('');
  const [reconLoading, setReconLoading] = useState(false);
  const [reconNotice, setReconNotice] = useState<{ msg: string; error?: boolean } | null>(null);

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

  const loadRegister = async () => {
    try {
      setRegisterLoading(true);
      const res = await apiRequest<{ register: FinishedGoodsRegisterItem[]; summary: FinishedGoodsRegisterSummary }>(
        '/api/stock/finished-goods-register'
      );
      if (res?.register) setRegisterItems(res.register);
      if (res?.summary) setRegisterSummary(res.summary);
    } catch (err) {
      console.warn('Could not load register in StockView', err);
    } finally {
      setRegisterLoading(false);
    }
  };

  useEffect(() => {
    loadRegister();
  }, []);

  const currentExpectedCount = useMemo(() => {
    if (!reconProductId) return 0;
    if (reconLocation === 'FACTORY') {
      const reg = registerItems.find(r => r.product_id === reconProductId);
      return reg ? reg.factory_packets : 0;
    }
    if (reconLocation === 'WAREHOUSE') {
      const reg = registerItems.find(r => r.product_id === reconProductId);
      if (reg) return reg.warehouse_packets;
      const comp = companyStockSummary.find(c => c.product_id === reconProductId);
      return comp ? comp.company_quantity : 0;
    }
    const sm = salesmanStockSummary.find(s => s.salesman_user_id === reconLocation && s.product_id === reconProductId);
    return sm ? sm.quantity : 0;
  }, [reconLocation, reconProductId, registerItems, companyStockSummary, salesmanStockSummary]);

  const liveAdjustmentDiff = Number(reconPhysicalCount) - currentExpectedCount;

  const handleReconcileOpening = async (e: React.FormEvent) => {
    e.preventDefault();
    setReconNotice(null);
    if (!reconProductId) {
      setReconNotice({ msg: 'Please select a product SKU.', error: true });
      return;
    }
    if (Number(reconPhysicalCount) < 0) {
      setReconNotice({ msg: 'Physical count cannot be negative.', error: true });
      return;
    }
    try {
      setReconLoading(true);
      const res = await apiRequest<{ message: string; adjustment: any }>('/api/stock/reconcile-opening', {
        method: 'POST',
        body: JSON.stringify({
          product_id: reconProductId,
          location: reconLocation,
          physical_count: Number(reconPhysicalCount),
          reason: reconReason.trim() || 'Physical inventory audit reconciliation',
          reference: reconReference.trim() || `RECON-${Date.now()}`,
        }),
      });
      setReconNotice({ msg: res.message || 'Physical stock reconciled and ledger balance updated successfully.' });
      setReconReason('');
      setReconReference('');
      await Promise.allSettled([loadRegister(), refreshData()]);
    } catch (err: any) {
      setReconNotice({ msg: err.message || 'Reconciliation failed', error: true });
    } finally {
      setReconLoading(false);
    }
  };

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
      loadRegister();
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
      loadRegister();
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

  const filteredRegister = registerItems.filter((item) => {
    if (hideZeroStock && item.total_internal_on_hand_packets <= 0 && item.channels_dispatched_packets <= 0) {
      return false;
    }
    if (registerFamily !== 'ALL') {
      const cat = String(item.category || '').toUpperCase();
      if (!cat.includes(registerFamily)) return false;
    }
    if (registerPackWeight !== 'ALL') {
      if (String(item.pack_weight_g) !== registerPackWeight) return false;
    }
    if (registerSearch.trim()) {
      const q = registerSearch.trim().toLowerCase();
      const skuMatch = String(item.sku || '').toLowerCase().includes(q);
      const nameMatch = String(item.product_name || '').toLowerCase().includes(q);
      if (!skuMatch && !nameMatch) return false;
    }
    return true;
  });

  const handleExportRegisterExcel = () => {
    const exportRows = filteredRegister.map((item) => ({
      'SKU': item.sku,
      'Product Name': item.product_name,
      'Category': item.category,
      'Pack Weight (g)': item.pack_weight_g,
      'Selling Unit': item.selling_unit,
      'Factory Packets': item.factory_packets,
      'Warehouse Packets': item.warehouse_packets,
      'Salesmen In-Hand Packets': item.salesmen_packets,
      'Total Internal On-Hand': item.total_internal_on_hand_packets,
      'External Channels Dispatched': item.channels_dispatched_packets,
      'Stock Status': item.stock_status,
      'Active': item.active ? 'YES' : 'NO',
    }));
    exportSheetToExcel('Finished_Goods_Stock_Register', exportRows);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
        <div>
          <h1 style={{ margin: 0 }}>Stock &amp; Ready-Packet Register</h1>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            Authoritative ready-to-sell packet inventory across Factory, Warehouse, Field Salesmen, and Channels.
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={() => setStockTab('register')}
          className={stockTab === 'register' ? '' : 'secondary'}
          style={{ fontWeight: 600 }}
        >
          📦 Finished Goods Register
        </button>
        <button
          type="button"
          onClick={() => setStockTab('movements')}
          className={stockTab === 'movements' ? '' : 'secondary'}
          style={{ fontWeight: 600 }}
        >
          🔄 Stock Movements &amp; Ledgers
        </button>
        {isManager && (
          <button
            type="button"
            onClick={() => setStockTab('physical')}
            className={stockTab === 'physical' ? '' : 'secondary'}
            style={{ fontWeight: 600 }}
          >
            ⚖️ Physical Count &amp; Reconciliation
          </button>
        )}
      </div>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      {/* FINISHED GOODS REGISTER TAB */}
      {stockTab === 'register' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginBottom: 16 }}>
            <div className="card" style={{ marginBottom: 0, background: '#f8fafc' }}>
              <small className="muted">Active Packet SKUs</small>
              <h2 style={{ margin: '4px 0 0' }}>{registerSummary?.active_skus ?? registerItems.length}</h2>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                {registerSummary?.active_with_stock ?? 0} with stock · {registerSummary?.active_zero_stock ?? 0} zero stock
              </span>
            </div>
            <div className="card" style={{ marginBottom: 0, background: '#f0fdf4' }}>
              <small style={{ color: '#166534' }}>Factory Finished</small>
              <h2 style={{ margin: '4px 0 0', color: '#15803d' }}>{registerSummary?.factory_packets ?? 0}</h2>
              <span style={{ fontSize: '0.75rem', color: '#166534' }}>Packaged at factory</span>
            </div>
            <div className="card" style={{ marginBottom: 0, background: '#eff6ff' }}>
              <small style={{ color: '#1e40af' }}>Central Warehouse</small>
              <h2 style={{ margin: '4px 0 0', color: '#1d4ed8' }}>{registerSummary?.warehouse_packets ?? 0}</h2>
              <span style={{ fontSize: '0.75rem', color: '#1e40af' }}>Company stock</span>
            </div>
            <div className="card" style={{ marginBottom: 0, background: '#fdf4ff' }}>
              <small style={{ color: '#86198f' }}>Salesmen In-Hand</small>
              <h2 style={{ margin: '4px 0 0', color: '#a21caf' }}>{registerSummary?.salesmen_packets ?? 0}</h2>
              <span style={{ fontSize: '0.75rem', color: '#86198f' }}>Field inventory</span>
            </div>
            <div className="card" style={{ marginBottom: 0, background: '#fefce8' }}>
              <small style={{ color: '#854d0e', fontWeight: 700 }}>Total Internal On-Hand</small>
              <h2 style={{ margin: '4px 0 0', color: '#a16207' }}>{registerSummary?.total_internal_on_hand_packets ?? 0}</h2>
              <span style={{ fontSize: '0.75rem', color: '#854d0e' }}>Physical on hand</span>
            </div>
            <div className="card" style={{ marginBottom: 0, background: '#f8fafc' }}>
              <small className="muted">Channels Dispatched</small>
              <h2 style={{ margin: '4px 0 0', color: '#334155' }}>{registerSummary?.channels_dispatched_packets ?? 0}</h2>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>E-com / Retail / Wholesalers</span>
            </div>
          </div>

          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
              <div>
                <h2 style={{ margin: 0 }}>Consolidated Finished Goods Register</h2>
                <p className="muted" style={{ margin: '2px 0 0', fontSize: '0.85rem' }}>
                  Complete ready-packet register showing physical location balances. Zero-stock SKUs remain visible.
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="secondary"
                  onClick={loadRegister}
                  disabled={registerLoading}
                  style={{ fontSize: '0.85rem' }}
                >
                  🔄 {registerLoading ? 'Refreshing...' : 'Refresh'}
                </button>
                <button
                  type="button"
                  onClick={handleExportRegisterExcel}
                  style={{ fontSize: '0.85rem', background: '#176b52' }}
                >
                  📥 Export Register (.xlsx)
                </button>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginBottom: 14, alignItems: 'center' }}>
              <input
                placeholder="🔍 Search SKU or Product..."
                value={registerSearch}
                onChange={(e) => setRegisterSearch(e.target.value)}
              />
              <select value={registerFamily} onChange={(e) => setRegisterFamily(e.target.value)}>
                <option value="ALL">All Categories / Families</option>
                <option value="MOONG">Moong Papad</option>
                <option value="CHANA">Chana Papad</option>
                <option value="URAD">Urad Papad</option>
                <option value="MASALA">Masala</option>
                <option value="KATRAN">Katran</option>
              </select>
              <select value={registerPackWeight} onChange={(e) => setRegisterPackWeight(e.target.value)}>
                <option value="ALL">All Pack Sizes</option>
                <option value="200">200 g</option>
                <option value="500">500 g</option>
                <option value="1000">1,000 g (1 kg)</option>
              </select>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.85rem', cursor: 'pointer', margin: 0 }}>
                <input
                  type="checkbox"
                  checked={hideZeroStock}
                  onChange={(e) => setHideZeroStock(e.target.checked)}
                />
                <span>Hide Zero Stock SKUs</span>
              </label>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Product</th>
                    <th>Category</th>
                    <th style={{ textAlign: 'center' }}>Pack Size</th>
                    <th style={{ textAlign: 'right', color: '#15803d' }}>Factory</th>
                    <th style={{ textAlign: 'right', color: '#1d4ed8' }}>Warehouse</th>
                    <th style={{ textAlign: 'right', color: '#a21caf' }}>Salesmen</th>
                    <th style={{ textAlign: 'right', background: '#fefce8', color: '#854d0e', fontWeight: 700 }}>
                      Total On-Hand
                    </th>
                    <th style={{ textAlign: 'right', color: '#475569' }}>Channels</th>
                    <th style={{ textAlign: 'center' }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRegister.map((item) => {
                    const isZero = item.total_internal_on_hand_packets <= 0;
                    const isLow = item.total_internal_on_hand_packets > 0 && item.total_internal_on_hand_packets < 20;
                    return (
                      <tr key={item.product_id} style={{ background: isZero ? '#fafafa' : undefined }}>
                        <td><strong>{item.sku}</strong></td>
                        <td>{item.product_name}</td>
                        <td className="muted">{item.category || 'Papad'}</td>
                        <td style={{ textAlign: 'center' }}>{item.pack_weight_g} g</td>
                        <td style={{ textAlign: 'right', fontWeight: item.factory_packets > 0 ? 700 : 400, color: item.factory_packets > 0 ? '#15803d' : '#94a3b8' }}>
                          {item.factory_packets}
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: item.warehouse_packets > 0 ? 700 : 400, color: item.warehouse_packets > 0 ? '#1d4ed8' : '#94a3b8' }}>
                          {item.warehouse_packets}
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: item.salesmen_packets > 0 ? 700 : 400, color: item.salesmen_packets > 0 ? '#a21caf' : '#94a3b8' }}>
                          {item.salesmen_packets}
                        </td>
                        <td style={{ textAlign: 'right', background: isZero ? '#fef2f2' : '#fefce8', color: isZero ? '#b91c1c' : '#854d0e', fontWeight: 700 }}>
                          {item.total_internal_on_hand_packets}
                        </td>
                        <td style={{ textAlign: 'right', color: '#475569' }}>
                          {item.channels_dispatched_packets}
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span
                            className={`badge ${isZero ? 'off' : isLow ? '' : 'on'}`}
                            style={{
                              background: isLow ? '#fef3c7' : undefined,
                              color: isLow ? '#b45309' : undefined,
                            }}
                          >
                            {isZero ? 'ZERO STOCK' : isLow ? 'LOW STOCK' : 'IN STOCK'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                  {filteredRegister.length === 0 && (
                    <tr>
                      <td colSpan={10} style={{ textAlign: 'center', padding: '16px' }} className="muted">
                        No finished goods match the filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* PHYSICAL COUNT & OPENING RECONCILIATION TAB */}
      {stockTab === 'physical' && isManager && (
        <>
          <div className="card">
            <h2>Audited Physical Opening Stock &amp; Reconciliation</h2>
            <p className="muted" style={{ marginTop: 0 }}>
              Directly reconcile actual physical count at the Factory, Central Warehouse, or a specific Salesman.
              The system calculates the exact difference from the ledger and creates an immutable balancing transaction with full audit reference.
            </p>

            {reconNotice && (
              <div className={reconNotice.error ? 'notice-error' : 'notice-success'} style={{ marginBottom: 14 }}>
                {reconNotice.msg}
              </div>
            )}

            <form onSubmit={handleReconcileOpening} className="inline" style={{ marginBottom: 12 }}>
              <label>
                Location / Node
                <select
                  value={reconLocation}
                  onChange={(e) => setReconLocation(e.target.value)}
                >
                  <option value="WAREHOUSE">🏢 Central Warehouse (Company Stock)</option>
                  <option value="FACTORY">🏭 Factory Finished Goods Storage</option>
                  {activeSalesmen.map((u) => (
                    <option key={u.user_id} value={u.user_id}>
                      🚶 Salesman: {u.full_name} ({u.user_id})
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Product SKU
                <select
                  required
                  value={reconProductId}
                  onChange={(e) => setReconProductId(e.target.value)}
                >
                  {activeProducts.map((p) => (
                    <option key={p.product_id} value={p.product_id}>
                      {p.sku} · {p.product_name} ({p.pack_weight_g}g)
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Actual Physical Count
                <input
                  type="number"
                  min="0"
                  step="1"
                  required
                  value={reconPhysicalCount}
                  onChange={(e) => setReconPhysicalCount(Number(e.target.value))}
                />
              </label>

              <label>
                Audit Reference / Verification Tag
                <input
                  placeholder="e.g. AUDIT-2026-COUNT, Physical stock audit"
                  value={reconReference}
                  onChange={(e) => setReconReference(e.target.value)}
                />
              </label>

              <label style={{ gridColumn: 'span 2' }}>
                Reason / Investigation Note
                <input
                  placeholder="Explanation of variance or opening balance setup..."
                  value={reconReason}
                  onChange={(e) => setReconReason(e.target.value)}
                />
              </label>

              <div style={{ gridColumn: '1 / -1', background: '#f8fafc', padding: 10, borderRadius: 6, border: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                <div>
                  Current Ledger Expected: <b>{currentExpectedCount} pkts</b> | Physical Count: <b>{reconPhysicalCount} pkts</b> |
                  Balancing Adjustment:{' '}
                  <b style={{ color: liveAdjustmentDiff >= 0 ? '#15803d' : '#b91c1c' }}>
                    {liveAdjustmentDiff > 0 ? `+${liveAdjustmentDiff}` : liveAdjustmentDiff} pkts
                  </b>
                </div>
                <button type="submit" disabled={reconLoading} style={{ background: '#176b52' }}>
                  {reconLoading ? 'Reconciling...' : '✓ Submit Audited Reconciliation'}
                </button>
              </div>
            </form>
          </div>
        </>
      )}

      {/* MOVEMENTS & BALANCES TAB */}
      {stockTab === 'movements' && (
        <>
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
        </>
      )}
    </div>
  );
};

