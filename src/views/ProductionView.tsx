import React, { useEffect, useMemo, useState } from 'react';
import { apiRequest } from '../services/api';
import { useStore } from '../context/StoreContext';

type Product = { product_id: string; product_name: string; sku: string; active: boolean; pack_weight_g: number };
type Row = Record<string, any>;
const card: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, marginBottom: 16 };
const input: React.CSSProperties = { padding: '9px 10px', border: '1px solid #cbd5e1', borderRadius: 7, width: '100%', boxSizing: 'border-box' };
const btn: React.CSSProperties = { padding: '9px 13px', border: 0, borderRadius: 7, background: '#166534', color: 'white', fontWeight: 600, cursor: 'pointer' };
const today = new Date().toISOString().slice(0, 10);

export interface ProductionViewProps {
  initialTab?: string;
}

export const ProductionView: React.FC<ProductionViewProps> = ({ initialTab = 'production' }) => {
  const { currentUser, isGoogleSheetsConnected, persistentWritesEnabled } = useStore();
  const [products, setProducts] = useState<Product[]>([]);
  const [workers, setWorkers] = useState<Row[]>([]);
  const [attendance, setAttendance] = useState<Row[]>([]);
  const [attendanceForm, setAttendanceForm] = useState({ worker_id: '', attendance_date: today, status: 'PRESENT', notes: '' });
  const [editingAttendance, setEditingAttendance] = useState<Row | null>(null);
  const [editAttendanceStatus, setEditAttendanceStatus] = useState<string>('PRESENT');
  const [editAttendanceNotes, setEditAttendanceNotes] = useState<string>('');
  const [recipes, setRecipes] = useState<Row[]>([]);
  const [masterRecipes, setMasterRecipes] = useState<Row[]>([]);
  const [selectedFamily, setSelectedFamily] = useState<string>('ALL');
  const [batches, setBatches] = useState<Row[]>([]);
  const [packaging, setPackaging] = useState<Row[]>([]);
  const [dispatches, setDispatches] = useState<Row[]>([]);
  const [summary, setSummary] = useState<Row>({ bulk_stock: [], finished_stock: [], workers_active: 0, pending_production: 0 });
  const [tab, setTab] = useState(initialTab);
  const [batchSearch, setBatchSearch] = useState('');
  const [batchStatusFilter, setBatchStatusFilter] = useState('ALL');
  const [batchDateFilter, setBatchDateFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (initialTab) {
      setTab(initialTab);
    }
  }, [initialTab]);
  const [worker, setWorker] = useState({ worker_name: '', mobile: '', daily_wage: '', notes: '' });
  const [recipe, setRecipe] = useState({ product_id: '', ingredients: '', notes: '' });
  const [production, setProduction] = useState({ product_id: '', production_date: today, quantity_kg: '', wastage_kg: '0', flour_base_used_kg: '', recipe_id: '', notes: '' });
  const [pack, setPack] = useState({ product_id: '', packaging_date: today, bulk_kg_used: '', packets_200g: '0', packets_500g: '0', packets_1000g: '0', notes: '' });
  const [dispatch, setDispatch] = useState({ product_id: '', channel: 'ECOMMERCE', destination: '', quantity_packets: '', reference: '', notes: '' });
  
  const role = String(currentUser?.role || '').toUpperCase();
  const isOwner = role === 'OWNER';
  const canManage = ['OWNER', 'OWNER_ADMIN', 'PA'].includes(role);
  const activeProducts = useMemo(() => products.filter(p => p.active !== false && String(p.active).toLowerCase() !== 'false'), [products]);

  const isDuplicateAttendance = useMemo(() => {
    if (!attendanceForm.worker_id || !attendanceForm.attendance_date) return false;
    return attendance.some(
      a => String(a.worker_id || '').trim() === attendanceForm.worker_id.trim() &&
           String(a.attendance_date || '').trim() === attendanceForm.attendance_date.trim()
    );
  }, [attendance, attendanceForm.worker_id, attendanceForm.attendance_date]);

  const load = async () => {
    const results = await Promise.allSettled([
      apiRequest<Product[]>('/api/products'),
      apiRequest<Row[]>('/api/production/workers'),
      apiRequest<Row[]>('/api/production/recipes'),
      apiRequest<Row[]>('/api/production/recipes/master'),
      apiRequest<Row[]>('/api/production/batches'),
      apiRequest<Row[]>('/api/production/packaging'),
      apiRequest<Row[]>('/api/production/dispatches'),
      apiRequest<Row>('/api/production/summary'),
      apiRequest<Row[]>('/api/production/attendance'),
    ]);

    const [pRes, wRes, rRes, mrRes, bRes, pkRes, dRes, sRes, aRes] = results;

    if (pRes.status === 'fulfilled' && Array.isArray(pRes.value)) setProducts(pRes.value);
    if (wRes.status === 'fulfilled' && Array.isArray(wRes.value)) setWorkers(wRes.value);
    if (rRes.status === 'fulfilled' && Array.isArray(rRes.value)) setRecipes(rRes.value);
    if (mrRes.status === 'fulfilled' && Array.isArray(mrRes.value)) setMasterRecipes(mrRes.value);
    if (bRes.status === 'fulfilled' && Array.isArray(bRes.value)) setBatches([...bRes.value].reverse());
    if (pkRes.status === 'fulfilled' && Array.isArray(pkRes.value)) setPackaging([...pkRes.value].reverse());
    if (dRes.status === 'fulfilled' && Array.isArray(dRes.value)) setDispatches([...dRes.value].reverse());
    if (sRes.status === 'fulfilled' && sRes.value) setSummary(sRes.value);
    if (aRes.status === 'fulfilled' && Array.isArray(aRes.value)) setAttendance([...aRes.value].reverse());

    const anyFailed = results.some(r => r.status === 'rejected');
    if (anyFailed) {
      console.warn('Some production sub-resources could not be refreshed in background.');
    }
  };

  const refreshSummary = async () => {
    try {
      const s = await apiRequest<Row>('/api/production/summary');
      if (s) setSummary(s);
    } catch (e) {
      console.warn('Could not refresh summary', e);
    }
  };

  const refreshAttendance = async () => {
    const [aRes, sRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/attendance'),
      apiRequest<Row>('/api/production/summary'),
    ]);
    if (aRes.status === 'fulfilled' && Array.isArray(aRes.value)) setAttendance([...aRes.value].reverse());
    if (sRes.status === 'fulfilled' && sRes.value) setSummary(sRes.value);
  };

  const refreshBatches = async () => {
    const [bRes, sRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/batches'),
      apiRequest<Row>('/api/production/summary'),
    ]);
    if (bRes.status === 'fulfilled' && Array.isArray(bRes.value)) setBatches([...bRes.value].reverse());
    if (sRes.status === 'fulfilled' && sRes.value) setSummary(sRes.value);
  };

  const refreshPackaging = async () => {
    const [pkRes, sRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/packaging'),
      apiRequest<Row>('/api/production/summary'),
    ]);
    if (pkRes.status === 'fulfilled' && Array.isArray(pkRes.value)) setPackaging([...pkRes.value].reverse());
    if (sRes.status === 'fulfilled' && sRes.value) setSummary(sRes.value);
  };

  const refreshWorkers = async () => {
    const [wRes, sRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/workers'),
      apiRequest<Row>('/api/production/summary'),
    ]);
    if (wRes.status === 'fulfilled' && Array.isArray(wRes.value)) setWorkers(wRes.value);
    if (sRes.status === 'fulfilled' && sRes.value) setSummary(sRes.value);
  };

  const refreshDispatches = async () => {
    const [dRes, sRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/dispatches'),
      apiRequest<Row>('/api/production/summary'),
    ]);
    if (dRes.status === 'fulfilled' && Array.isArray(dRes.value)) setDispatches([...dRes.value].reverse());
    if (sRes.status === 'fulfilled' && sRes.value) setSummary(sRes.value);
  };

  const refreshRecipes = async () => {
    const rRes = await apiRequest<Row[]>('/api/production/recipes');
    if (Array.isArray(rRes)) setRecipes(rRes);
  };

  const refreshMasterRecipes = async () => {
    const [mrRes, rRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/recipes/master'),
      apiRequest<Row[]>('/api/production/recipes'),
    ]);
    if (mrRes.status === 'fulfilled' && Array.isArray(mrRes.value)) setMasterRecipes(mrRes.value);
    if (rRes.status === 'fulfilled' && Array.isArray(rRes.value)) setRecipes(rRes.value);
  };

  useEffect(() => {
    if (canManage) {
      load().catch(e => setMessage(e.message || 'Could not load production data.'));
    }
  }, [canManage]);

  const runAction = async (fn: () => Promise<unknown>, success: string, targetedRefresh?: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setMessage('');
    try {
      await fn();
      setMessage(success);
      try {
        if (targetedRefresh) {
          await targetedRefresh();
        } else {
          await load();
        }
      } catch (refreshErr: any) {
        console.warn('Post-action screen refresh warning:', refreshErr);
        setMessage(`${success} (Data saved, refreshing screen...)`);
      }
    } catch (e: any) {
      setMessage(e?.message || 'Action failed.');
    } finally {
      setBusy(false);
    }
  };

  // Backward-compatible run wrapper defaulting to full load
  const run = (fn: () => Promise<unknown>, success: string) => runAction(fn, success);

  if (!canManage) {
    return (
      <section style={{ padding: 24 }}>
        <h2>Production Management</h2>
        <p>Only Owner and authorised PA accounts can manage production.</p>
      </section>
    );
  }

  const productSelect = (value: string, onChange: (v: string) => void) => (
    <select style={input} value={value} onChange={e => onChange(e.target.value)} required>
      <option value="">Select product / variant</option>
      {activeProducts.map(p => (
        <option key={p.product_id} value={p.product_id}>
          {p.product_name} {p.sku ? `(${p.sku})` : ''}
        </option>
      ))}
    </select>
  );

  const sectionButton = (id: string, label: string) => (
    <button
      key={id}
      onClick={() => setTab(id)}
      style={{
        ...btn,
        background: tab === id ? '#166534' : '#64748b',
        marginRight: 7,
        marginBottom: 8,
      }}
    >
      {label}
    </button>
  );

  const rowsTable = (rows: Row[], columns: [string, string][]) => (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            {columns.map(([k, l]) => (
              <th key={k} style={{ textAlign: 'left', padding: 9, background: '#f1f5f9' }}>
                {l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={String(r.production_id || r.packaging_id || r.worker_id || r.dispatch_id || r.recipe_id || i)}>
              {columns.map(([k]) => (
                <td key={k} style={{ padding: 9, borderBottom: '1px solid #e2e8f0' }}>
                  {String(r[k] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <p style={{ color: '#64748b' }}>No records yet.</p>}
    </div>
  );

  const filteredMasterRecipes = masterRecipes.filter(r => {
    if (selectedFamily === 'ALL') return true;
    return String(r.product_family).toUpperCase() === selectedFamily;
  });

  // Calculate live benchmark yield for current production form input
  const flourBaseNum = parseFloat(production.flour_base_used_kg || '0');
  const liveBenchmarkYield = flourBaseNum > 0 ? (flourBaseNum * 1.2).toFixed(2) : null;
  const grossNum = parseFloat(production.quantity_kg || '0');
  const wastageNum = parseFloat(production.wastage_kg || '0');
  const liveNetYield = grossNum > wastageNum ? (grossNum - wastageNum).toFixed(2) : null;
  const liveVariance = liveBenchmarkYield && liveNetYield ? (parseFloat(liveNetYield) - parseFloat(liveBenchmarkYield)).toFixed(2) : null;

  return (
    <section style={{ padding: '18px 20px', maxWidth: 1250, margin: '0 auto' }}>
      <div style={{ marginBottom: 14 }}>
        <h2 style={{ margin: '0 0 5px', color: '#14532d' }}>🏭 Kawad Swad Production & Recipe Master</h2>
        <p style={{ margin: 0, color: '#64748b' }}>
          Version 2.0 Papad Formulas (Moong, Chana, Urad) → Factory Bulk Production → Packets → Channel Dispatch.
        </p>
      </div>

      {message && (
        <div
          role="status"
          style={{
            ...card,
            background:
              message.toLowerCase().includes('could not') ||
              message.toLowerCase().includes('insufficient') ||
              message.toLowerCase().includes('error')
                ? '#fef2f2'
                : '#f0fdf4',
            color: '#166534',
          }}
        >
          {message}
        </div>
      )}

      <div>
        {sectionButton('master_recipes', '📜 Papad Formula Master (v2.0)')}
        {sectionButton('overview', 'Overview & Stock')}
        {sectionButton('workers', 'Workers')}
        {sectionButton('recipes', 'Custom Recipes')}
        {sectionButton('production', 'Daily Production')}
        {sectionButton('packaging', 'Packaging')}
        {sectionButton('dispatch', 'Dispatch')}
      </div>

      {/* MASTER RECIPES TAB */}
      {tab === 'master_recipes' && (
        <>
          <div style={{ ...card, background: '#f8fafc', borderColor: '#cbd5e1' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h3 style={{ margin: '0 0 4px', color: '#1e293b' }}>Kawad Swad Papad Formula Master — Version 2.0</h3>
                <p style={{ margin: 0, fontSize: 13, color: '#475569' }}>
                  Official standard formulas: <b>Moong Family</b> (8 variants), <b>Chana Family</b> (5 variants), <b>Urad Family</b> (2 variants).
                </p>
              </div>
              <button
                style={{ ...btn, background: '#0284c7' }}
                disabled={busy}
                onClick={() =>
                  runAction(
                    () => apiRequest('/api/production/recipes/master/bootstrap', { method: 'POST' }),
                    'Version 2.0 Master Recipes and Raw Materials synchronized to system successfully.',
                    refreshMasterRecipes
                  )
                }
              >
                🔄 Sync Master Recipes & Raw Materials to System
              </button>
            </div>

            {/* Benchmark Highlights */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10, marginTop: 14 }}>
              <div style={{ background: '#ecfdf5', padding: 12, borderRadius: 8, border: '1px solid #a7f3d0' }}>
                <b style={{ color: '#065f46' }}>✓ Confirmed Moong Master Formula</b>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: '#047857' }}>
                  1,000 g Moong Dal Flour • 0 Sabudana • 0 Urad • ₹153.63 / batch • 1.2 kg yield • <b>₹128.03 / kg</b>
                </p>
              </div>
              <div style={{ background: '#fffbeb', padding: 12, borderRadius: 8, border: '1px solid #fde68a' }}>
                <b style={{ color: '#92400e' }}>⚠️ Chana Family (Proposed Base)</b>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: '#b45309' }}>
                  750 g Chana Dal Flour : 250 g Urad Dal Flour • 1 g SMOS (pending owner sign-off) • Unverified yield
                </p>
              </div>
              <div style={{ background: '#f5f3ff', padding: 12, borderRadius: 8, border: '1px solid #ddd6fe' }}>
                <b style={{ color: '#5b21b6' }}>⚠️ Urad Family (Proposed Base)</b>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: '#6d28d9' }}>
                  850 g Urad Dal Flour : 150 g Sabudana Flour • 1 g SMOS (pending owner sign-off) • Unverified yield
                </p>
              </div>
            </div>

            {/* Filter Chips */}
            <div style={{ marginTop: 14, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>Filter by Family:</span>
              {['ALL', 'MOONG', 'CHANA', 'URAD'].map(fam => (
                <button
                  key={fam}
                  onClick={() => setSelectedFamily(fam)}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 20,
                    border: '1px solid #cbd5e1',
                    background: selectedFamily === fam ? '#1e293b' : '#fff',
                    color: selectedFamily === fam ? '#fff' : '#334155',
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  {fam} ({masterRecipes.filter(r => fam === 'ALL' || String(r.product_family).toUpperCase() === fam).length})
                </button>
              ))}
            </div>
          </div>

          {/* RECIPES GRID */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
            {filteredMasterRecipes.map(r => {
              const isApproved = r.approved || String(r.status).toUpperCase() === 'APPROVED';
              const hasPendingRates = r.cost_status === 'PENDING_RATES';
              return (
                <div
                  key={r.recipe_id}
                  style={{
                    ...card,
                    border: isApproved ? '1.5px solid #22c55e' : '1.5px solid #e2e8f0',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                      <div>
                        <span
                          style={{
                            fontSize: 11,
                            fontWeight: 700,
                            padding: '2px 8px',
                            borderRadius: 6,
                            background:
                              r.product_family === 'MOONG' ? '#dcfce7' : r.product_family === 'CHANA' ? '#fef3c7' : '#ede9fe',
                            color:
                              r.product_family === 'MOONG' ? '#166534' : r.product_family === 'CHANA' ? '#92400e' : '#5b21b6',
                          }}
                        >
                          {r.product_family} FAMILY
                        </span>
                        <h3 style={{ margin: '6px 0 2px', fontSize: 17, color: '#0f172a' }}>{r.product_name_snapshot}</h3>
                        <small style={{ color: '#64748b' }}>
                          Variant: <b>{r.variant_name}</b> (v{r.version})
                        </small>
                      </div>

                      {isApproved ? (
                        <span
                          style={{
                            background: '#dcfce7',
                            color: '#15803d',
                            fontSize: 11,
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: 6,
                            border: '1px solid #86efac',
                          }}
                        >
                          ✓ CONFIRMED & APPROVED
                        </span>
                      ) : (
                        <span
                          style={{
                            background: '#fef3c7',
                            color: '#b45309',
                            fontSize: 11,
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: 6,
                            border: '1px solid #fde68a',
                          }}
                        >
                          PROPOSED / PENDING
                        </span>
                      )}
                    </div>

                    <p style={{ fontSize: 12, color: '#475569', margin: '4px 0 10px', fontStyle: 'italic' }}>
                      {r.change_notes}
                    </p>

                    {/* Cost & Yield summary box */}
                    <div
                      style={{
                        background: '#f8fafc',
                        border: '1px solid #e2e8f0',
                        borderRadius: 8,
                        padding: 10,
                        marginBottom: 12,
                        fontSize: 13,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span>Flour Base:</span>
                        <b>{r.batch_size} g</b>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span>Expected Dry Yield:</span>
                        <b>{r.expected_yield_kg} kg / batch</b>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span>Batch Ingredient Cost:</span>
                        {hasPendingRates ? (
                          <span style={{ color: '#dc2626', fontWeight: 600 }}>⚠️ Rate to confirm (Pending)</span>
                        ) : (
                          <b style={{ color: '#166534', fontSize: 14 }}>₹{r.cost_per_batch}</b>
                        )}
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Cost per kg:</span>
                        {hasPendingRates ? (
                          <span style={{ color: '#64748b', fontStyle: 'italic' }}>Pending supplier rates</span>
                        ) : (
                          <b style={{ color: '#166534', fontSize: 14 }}>₹{r.cost_per_kg} / kg</b>
                        )}
                      </div>
                      {hasPendingRates && (
                        <div style={{ marginTop: 6, fontSize: 11, color: '#b91c1c' }}>
                          * Notice: Rates for <b>{r.pending_ingredients?.join(', ')}</b> are pending. Total cost is not displayed
                          to avoid misleading projections.
                        </div>
                      )}
                    </div>

                    {/* Ingredients Table */}
                    <div style={{ overflowX: 'auto', marginBottom: 12 }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr style={{ background: '#f1f5f9', color: '#475569' }}>
                            <th style={{ textAlign: 'left', padding: '6px 8px' }}>Ingredient</th>
                            <th style={{ textAlign: 'right', padding: '6px 8px' }}>Batch Qty</th>
                            <th style={{ textAlign: 'right', padding: '6px 8px' }}>Rate</th>
                            <th style={{ textAlign: 'right', padding: '6px 8px' }}>Cost</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(r.items || []).map((item: any, idx: number) => (
                            <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                              <td style={{ padding: '5px 8px' }}>
                                {item.material_name}
                                {item.notes && <div style={{ fontSize: 10, color: '#64748b' }}>{item.notes}</div>}
                              </td>
                              <td style={{ textAlign: 'right', padding: '5px 8px' }}>
                                {item.quantity} {item.unit}
                              </td>
                              <td style={{ textAlign: 'right', padding: '5px 8px' }}>
                                {item.rate_status === 'CONFIRMED' && item.rate_per_unit != null ? (
                                  `₹${item.rate_per_unit}`
                                ) : (
                                  <span style={{ color: '#b45309', fontWeight: 600 }}>Pending</span>
                                )}
                              </td>
                              <td style={{ textAlign: 'right', padding: '5px 8px', fontWeight: 600 }}>
                                {item.ingredient_cost != null ? (
                                  `₹${item.ingredient_cost}`
                                ) : (
                                  <span style={{ color: '#64748b' }}>—</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Card Actions */}
                  <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      style={{ ...btn, flex: 1, padding: '7px 10px', fontSize: 12, background: '#3b82f6' }}
                      onClick={() => {
                        const targetProd = products.find(
                          p =>
                            p.product_id === r.product_id ||
                            p.product_name.toLowerCase().includes(r.product_name_snapshot.toLowerCase())
                        );
                        if (targetProd) {
                          setProduction(prev => ({
                            ...prev,
                            product_id: targetProd.product_id,
                            recipe_id: r.recipe_id,
                            notes: `Using ${r.product_name_snapshot} formula`,
                          }));
                          setTab('production');
                          setMessage(`Formula for ${r.product_name_snapshot} pre-selected in Daily Production.`);
                        } else {
                          setMessage(`No linked product found for ${r.product_name_snapshot}. Create product in Products master.`);
                        }
                      }}
                    >
                      📋 Use in Production
                    </button>

                    {isOwner && (
                      <button
                        type="button"
                        style={{
                          ...btn,
                          flex: 1,
                          padding: '7px 10px',
                          fontSize: 12,
                          background: isApproved ? '#047857' : '#d97706',
                        }}
                        disabled={busy}
                        onClick={() =>
                          runAction(
                            () =>
                              apiRequest(`/api/production/recipes/master/${encodeURIComponent(r.recipe_id)}/confirm`, {
                                method: 'POST',
                                body: JSON.stringify({ approved: !isApproved }),
                              }),
                            isApproved
                              ? `Formula ${r.product_name_snapshot} marked as draft.`
                              : `Formula ${r.product_name_snapshot} confirmed & approved by Owner.`,
                            refreshMasterRecipes
                          )
                        }
                      >
                        {isApproved ? '✓ Owner Approved' : '✅ Confirm as Owner'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* OVERVIEW TAB */}
      {tab === 'overview' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 16 }}>
            <div style={card}>
              <small>Active workers</small>
              <h2>{summary.workers_active ?? 0}</h2>
            </div>
            <div style={card}>
              <small>Production awaiting approval</small>
              <h2>{summary.pending_production ?? 0}</h2>
            </div>
            <div style={card}>
              <small>Bulk products tracked</small>
              <h2>{(summary.bulk_stock || []).length}</h2>
            </div>
            <div style={card}>
              <small>Finished products tracked</small>
              <h2>{(summary.finished_stock || []).length}</h2>
            </div>
          </div>
          <div style={card}>
            <h3>Unpackaged papad (kg)</h3>
            {rowsTable(summary.bulk_stock || [], [
              ['product_name', 'Product'],
              ['quantity_kg', 'Available kg'],
            ])}
          </div>
          <div style={card}>
            <h3>Finished packets at factory</h3>
            {rowsTable(summary.finished_stock || [], [
              ['product_name', 'Product'],
              ['quantity_packets', 'Available packets'],
            ])}
          </div>
          <div style={{ ...card, background: '#fffbeb', borderColor: '#fcd34d' }}>
            <b>Setup note:</b> Raw material deductions require an approved recipe and matching material rows in the{' '}
            <code>RawMaterials</code> sheet. Verify opening stock quantities and units before approving production. Any packaging
            difference is flagged for review and must be checked by the responsible person.
          </div>
        </>
      )}

      {/* WORKERS TAB */}
      {tab === 'workers' && (
        <>
          <div style={card}>
            <h3>Add factory worker</h3>
            <form
              onSubmit={e => {
                e.preventDefault();
                runAction(
                  () =>
                    apiRequest('/api/production/workers', {
                      method: 'POST',
                      body: JSON.stringify({
                        worker_name: worker.worker_name,
                        mobile: worker.mobile,
                        daily_wage: Number(worker.daily_wage),
                        notes: worker.notes,
                        active: true,
                      }),
                    }),
                  'Worker added.',
                  refreshWorkers
                );
                setWorker({ worker_name: '', mobile: '', daily_wage: '', notes: '' });
              }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}
            >
              <input
                style={input}
                placeholder="Worker full name"
                value={worker.worker_name}
                onChange={e => setWorker({ ...worker, worker_name: e.target.value })}
                required
              />
              <input
                style={input}
                placeholder="Mobile (optional)"
                value={worker.mobile}
                onChange={e => setWorker({ ...worker, mobile: e.target.value })}
              />
              <input
                style={input}
                type="number"
                min="0"
                step="0.01"
                placeholder="Daily wage ₹"
                value={worker.daily_wage}
                onChange={e => setWorker({ ...worker, daily_wage: e.target.value })}
                required
              />
              <input
                style={input}
                placeholder="Notes"
                value={worker.notes}
                onChange={e => setWorker({ ...worker, notes: e.target.value })}
              />
              <button style={btn} disabled={busy}>
                Add worker
              </button>
            </form>
          </div>
          <div style={card}>
            <h3>Workers and fixed daily wages</h3>
            {rowsTable(workers, [
              ['worker_name', 'Worker'],
              ['mobile', 'Mobile'],
              ['daily_wage', 'Daily wage ₹'],
              ['active', 'Active'],
              ['created_at', 'Added'],
            ])}
          </div>
          <div style={card}>
            <h3>Record daily attendance & wage accrual</h3>
            <form
              onSubmit={e => {
                e.preventDefault();
                if (isDuplicateAttendance) {
                  setMessage('Attendance is already recorded for this worker on this date.');
                  return;
                }
                runAction(
                  () => apiRequest('/api/production/attendance', { method: 'POST', body: JSON.stringify(attendanceForm) }),
                  'Attendance recorded and wage accrued.',
                  refreshAttendance
                );
                setAttendanceForm({ ...attendanceForm, notes: '' });
              }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10 }}
            >
              <select
                style={input}
                value={attendanceForm.worker_id}
                onChange={e => setAttendanceForm({ ...attendanceForm, worker_id: e.target.value })}
                required
              >
                <option value="">Select worker</option>
                {workers
                  .filter(w => String(w.active).toLowerCase() !== 'false')
                  .map(w => (
                    <option key={w.worker_id} value={w.worker_id}>
                      {w.worker_name} (₹{w.daily_wage}/day)
                    </option>
                  ))}
              </select>
              <input
                style={input}
                type="date"
                value={attendanceForm.attendance_date}
                onChange={e => setAttendanceForm({ ...attendanceForm, attendance_date: e.target.value })}
                required
              />
              <select
                style={input}
                value={attendanceForm.status}
                onChange={e => setAttendanceForm({ ...attendanceForm, status: e.target.value })}
              >
                <option value="PRESENT">Present (full wage)</option>
                <option value="HALF_DAY">Half day (half wage)</option>
                <option value="ABSENT">Absent (no wage)</option>
              </select>
              <input
                style={input}
                placeholder="Notes"
                value={attendanceForm.notes}
                onChange={e => setAttendanceForm({ ...attendanceForm, notes: e.target.value })}
              />
              <button
                style={{
                  ...btn,
                  background: isDuplicateAttendance ? '#94a3b8' : '#166534',
                  cursor: isDuplicateAttendance || busy ? 'not-allowed' : 'pointer',
                }}
                disabled={busy || isDuplicateAttendance || !attendanceForm.worker_id}
              >
                {busy ? 'Saving...' : 'Save attendance'}
              </button>

              {isDuplicateAttendance && (
                <div
                  style={{
                    gridColumn: '1 / -1',
                    background: '#fef2f2',
                    border: '1px solid #fecaca',
                    color: '#991b1b',
                    padding: '8px 12px',
                    borderRadius: 6,
                    fontSize: 13,
                    fontWeight: 500,
                  }}
                >
                  ⚠️ Attendance for this worker on <b>{attendanceForm.attendance_date}</b> is already recorded in the system. Duplicate submission is blocked.
                </div>
              )}
            </form>
            <p style={{ color: '#64748b', fontSize: 13, margin: '8px 0 0' }}>
              Attendance records accrue wages; they do not mark wages as paid. Duplicate attendance for the same worker/date is blocked.
            </p>
          </div>

          {/* Attendance Correction Modal for Owner */}
          {editingAttendance && (
            <div style={{ ...card, background: '#fffbeb', borderColor: '#fcd34d' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <h4 style={{ margin: 0, color: '#92400e' }}>
                  Audited Attendance Correction: {editingAttendance.worker_name_snapshot} ({editingAttendance.attendance_date})
                </h4>
                <button
                  type="button"
                  style={{ background: 'transparent', border: 0, cursor: 'pointer', fontSize: 16 }}
                  onClick={() => setEditingAttendance(null)}
                >
                  ✕
                </button>
              </div>
              <p style={{ fontSize: 12, color: '#b45309', margin: '0 0 10px' }}>
                Existing records are never deleted. Status changes update accrued wages and log an audit trail entry.
              </p>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <select
                  style={{ ...input, width: 180 }}
                  value={editAttendanceStatus}
                  onChange={e => setEditAttendanceStatus(e.target.value)}
                >
                  <option value="PRESENT">Present (full wage)</option>
                  <option value="HALF_DAY">Half day (half wage)</option>
                  <option value="ABSENT">Absent (no wage)</option>
                </select>
                <input
                  style={{ ...input, flex: 1 }}
                  placeholder="Reason for correction (required for audit log)"
                  value={editAttendanceNotes}
                  onChange={e => setEditAttendanceNotes(e.target.value)}
                />
                <button
                  style={{ ...btn, background: '#b45309' }}
                  disabled={busy || !editAttendanceNotes.trim()}
                  onClick={() => {
                    runAction(
                      () =>
                        apiRequest(`/api/production/attendance/${encodeURIComponent(editingAttendance.attendance_id)}`, {
                          method: 'PUT',
                          body: JSON.stringify({ status: editAttendanceStatus, notes: editAttendanceNotes }),
                        }),
                      'Attendance corrected successfully.',
                      refreshAttendance
                    );
                    setEditingAttendance(null);
                  }}
                >
                  Save correction
                </button>
                <button
                  type="button"
                  style={{ ...btn, background: '#64748b' }}
                  onClick={() => setEditingAttendance(null)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div style={card}>
            <h3>Attendance and accrued wages</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#f1f5f9' }}>
                    <th style={{ textAlign: 'left', padding: 9 }}>Date</th>
                    <th style={{ textAlign: 'left', padding: 9 }}>Worker</th>
                    <th style={{ textAlign: 'left', padding: 9 }}>Status</th>
                    <th style={{ textAlign: 'right', padding: 9 }}>Daily Wage ₹</th>
                    <th style={{ textAlign: 'right', padding: 9 }}>Accrued Wage ₹</th>
                    <th style={{ textAlign: 'left', padding: 9 }}>Notes</th>
                    <th style={{ textAlign: 'left', padding: 9 }}>Entered By</th>
                    {isOwner && <th style={{ textAlign: 'center', padding: 9 }}>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {attendance.map((a, idx) => {
                    const statusColor =
                      a.status === 'PRESENT' ? '#166534' : a.status === 'HALF_DAY' ? '#b45309' : '#64748b';
                    return (
                      <tr key={String(a.attendance_id || idx)} style={{ borderBottom: '1px solid #e2e8f0' }}>
                        <td style={{ padding: 9 }}>{String(a.attendance_date || '-')}</td>
                        <td style={{ padding: 9, fontWeight: 500 }}>
                          {String(a.worker_name_snapshot || a.worker_id || '-')}
                          {a.is_duplicate && (
                            <span
                              style={{
                                marginLeft: 6,
                                padding: '2px 6px',
                                background: '#fee2e2',
                                color: '#b91c1c',
                                borderRadius: 4,
                                fontSize: 11,
                                fontWeight: 600,
                              }}
                            >
                              Duplicate in Sheet
                            </span>
                          )}
                        </td>
                        <td style={{ padding: 9 }}>
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              fontSize: 12,
                              fontWeight: 600,
                              background: a.status === 'PRESENT' ? '#ecfdf5' : a.status === 'HALF_DAY' ? '#fffbeb' : '#f1f5f9',
                              color: statusColor,
                            }}
                          >
                            {String(a.status || '-')}
                          </span>
                        </td>
                        <td style={{ padding: 9, textAlign: 'right' }}>₹{String(a.daily_wage_snapshot ?? '-')}</td>
                        <td style={{ padding: 9, textAlign: 'right', fontWeight: 600 }}>₹{String(a.wage_accrued ?? '-')}</td>
                        <td style={{ padding: 9, color: '#64748b', fontSize: 12 }}>{String(a.notes || '-')}</td>
                        <td style={{ padding: 9, color: '#64748b', fontSize: 12 }}>{String(a.created_by || '-')}</td>
                        {isOwner && (
                          <td style={{ padding: 9, textAlign: 'center' }}>
                            <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                              <button
                                type="button"
                                style={{ ...btn, padding: '4px 8px', fontSize: 11, background: '#0284c7' }}
                                onClick={() => {
                                  setEditingAttendance(a);
                                  setEditAttendanceStatus(String(a.status || 'PRESENT'));
                                  setEditAttendanceNotes('');
                                }}
                              >
                                ✏️ Correct
                              </button>
                              {a.is_duplicate && (
                                <button
                                  type="button"
                                  style={{ ...btn, padding: '4px 8px', fontSize: 11, background: '#dc2626' }}
                                  disabled={busy}
                                  onClick={() => {
                                    runAction(
                                      () => apiRequest(`/api/production/attendance/${encodeURIComponent(a.attendance_id)}`, { method: 'DELETE' }),
                                      'Duplicate attendance record removed.',
                                      refreshAttendance
                                    );
                                  }}
                                >
                                  🗑️ Remove Duplicate
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!attendance.length && <p style={{ color: '#64748b', padding: 12 }}>No attendance records found.</p>}
            </div>
          </div>
        </>
      )}

      {/* CUSTOM RECIPES TAB */}
      {tab === 'recipes' && (
        <>
          <div style={card}>
            <h3>Custom Recipe Editor for Automatic Consumption</h3>
            <p style={{ color: '#64748b' }}>
              Enter one ingredient per line: <code>Material name | quantity per 1 kg papad | unit</code>. Example:{' '}
              <code>Moong Dal Flour | 0.833 | kg</code>. Use exact material names from RawMaterials.
            </p>
            <form
              onSubmit={e => {
                e.preventDefault();
                const items = recipe.ingredients
                  .split('\n')
                  .map(line => line.split('|').map(x => x.trim()))
                  .filter(x => x.length >= 2 && x[0] && Number(x[1]) > 0)
                  .map(x => ({ material_name: x[0], quantity_per_kg: Number(x[1]), unit: x[2] || 'kg' }));
                if (!items.length) {
                  setMessage('Enter at least one valid ingredient line.');
                  return;
                }
                runAction(
                  () =>
                    apiRequest('/api/production/recipes', {
                      method: 'POST',
                      body: JSON.stringify({ product_id: recipe.product_id, items, approved: true, notes: recipe.notes }),
                    }),
                  'Approved recipe saved.',
                  refreshRecipes
                );
                setRecipe({ product_id: '', ingredients: '', notes: '' });
              }}
            >
              <div style={{ display: 'grid', gap: 10 }}>
                {productSelect(recipe.product_id, v => setRecipe({ ...recipe, product_id: v }))}
                <textarea
                  style={{ ...input, minHeight: 110 }}
                  placeholder={'Moong Dal Flour | 0.833 | kg\nBlack Pepper | 0.0125 | kg\nHing | 0.0042 | kg\nSalt | 0.0417 | kg'}
                  value={recipe.ingredients}
                  onChange={e => setRecipe({ ...recipe, ingredients: e.target.value })}
                  required
                />
                <input
                  style={input}
                  placeholder="Recipe notes / version reason"
                  value={recipe.notes}
                  onChange={e => setRecipe({ ...recipe, notes: e.target.value })}
                />
                <button style={btn} disabled={busy}>
                  Save & approve recipe
                </button>
              </div>
            </form>
          </div>
          <div style={card}>
            <h3>Saved Recipe Versions</h3>
            {rowsTable(recipes, [
              ['product_name_snapshot', 'Product'],
              ['version', 'Version'],
              ['approved', 'Approved'],
              ['created_at', 'Created'],
              ['notes', 'Notes'],
            ])}
          </div>
        </>
      )}

      {/* DAILY PRODUCTION TAB */}
      {tab === 'production' && (
        <>
          <div style={card}>
            <h3>Record Daily Bulk Production Batch</h3>
            <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 12px' }}>
              Record flour base used and actual finished dry yield. Benchmark dry yield is automatically compared at{' '}
              <b>1.2 kg per 1.0 kg flour base</b>.
            </p>

            <form
              onSubmit={e => {
                e.preventDefault();
                runAction(
                  () =>
                    apiRequest('/api/production/batches', {
                      method: 'POST',
                      body: JSON.stringify({
                        ...production,
                        quantity_kg: Number(production.quantity_kg),
                        wastage_kg: Number(production.wastage_kg),
                        flour_base_used_kg: production.flour_base_used_kg ? Number(production.flour_base_used_kg) : undefined,
                      }),
                    }),
                  'Production batch recorded and sent for approval.',
                  refreshBatches
                );
                setProduction({ product_id: '', production_date: today, quantity_kg: '', wastage_kg: '0', flour_base_used_kg: '', recipe_id: '', notes: '' });
              }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}
            >
              {productSelect(production.product_id, v => setProduction({ ...production, product_id: v }))}
              <input
                style={input}
                type="date"
                value={production.production_date}
                onChange={e => setProduction({ ...production, production_date: e.target.value })}
                required
              />
              <input
                style={input}
                type="number"
                min="0.1"
                step="0.01"
                placeholder="Flour Base Used (kg)"
                value={production.flour_base_used_kg}
                onChange={e => setProduction({ ...production, flour_base_used_kg: e.target.value })}
              />
              <input
                style={input}
                type="number"
                min="0.001"
                step="0.001"
                placeholder="Gross produced kg"
                value={production.quantity_kg}
                onChange={e => setProduction({ ...production, quantity_kg: e.target.value })}
                required
              />
              <input
                style={input}
                type="number"
                min="0"
                step="0.001"
                placeholder="Rejected / wastage kg"
                value={production.wastage_kg}
                onChange={e => setProduction({ ...production, wastage_kg: e.target.value })}
              />
              <input
                style={input}
                placeholder="Notes / Batch shift"
                value={production.notes}
                onChange={e => setProduction({ ...production, notes: e.target.value })}
              />

              <div style={{ gridColumn: '1 / -1', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                {liveBenchmarkYield && (
                  <div style={{ fontSize: 13, color: '#334155' }}>
                    Benchmark Expected Yield: <b>{liveBenchmarkYield} kg</b> (1.2 ratio) | Actual Net Yield:{' '}
                    <b>{liveNetYield || 0} kg</b>{' '}
                    {liveVariance && (
                      <span
                        style={{
                          color: parseFloat(liveVariance) >= 0 ? '#166534' : '#b91c1c',
                          fontWeight: 600,
                        }}
                      >
                        (Variance: {parseFloat(liveVariance) >= 0 ? '+' : ''}
                        {liveVariance} kg)
                      </span>
                    )}
                  </div>
                )}
                <button
                  style={{
                    ...btn,
                    marginLeft: 'auto',
                    background: (!isGoogleSheetsConnected || !persistentWritesEnabled) ? '#64748b' : '#166534',
                    cursor: (busy || !isGoogleSheetsConnected || !persistentWritesEnabled) ? 'not-allowed' : 'pointer',
                  }}
                  disabled={busy || !isGoogleSheetsConnected || !persistentWritesEnabled}
                  title={(!isGoogleSheetsConnected || !persistentWritesEnabled) ? 'Google Sheets disconnected. Batch creation locked to prevent data loss.' : ''}
                >
                  {(!isGoogleSheetsConnected || !persistentWritesEnabled) ? '🔒 Locked (Sheets Disconnected)' : 'Save pending production'}
                </button>
              </div>
            </form>
          </div>

          <div style={card}>
            <h3>Production Batches & Yield Reconciliation</h3>
            {rowsTable(batches, [
              ['production_date', 'Date'],
              ['product_name_snapshot', 'Product'],
              ['flour_base_used_kg', 'Flour kg'],
              ['quantity_kg', 'Gross kg'],
              ['wastage_kg', 'Wastage kg'],
              ['net_quantity_kg', 'Net kg'],
              ['benchmark_yield_kg', 'Benchmark kg'],
              ['yield_variance_kg', 'Variance kg'],
              ['status', 'Status'],
              ['created_by', 'Entered by'],
            ])}

            {batches
              .filter(b => String(b.status).toUpperCase() === 'PENDING')
              .map(b => (
                <div
                  key={b.production_id}
                  style={{
                    padding: '10px 0',
                    borderTop: '1px solid #e2e8f0',
                    display: 'flex',
                    gap: 10,
                    alignItems: 'center',
                    flexWrap: 'wrap',
                  }}
                >
                  <b>{b.production_id}</b>
                  <span>
                    {b.product_name_snapshot}: <b>{b.net_quantity_kg} kg net</b>
                    {b.flour_base_used_kg && ` (Flour: ${b.flour_base_used_kg} kg)`}
                  </span>
                  {isOwner ? (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <button
                        style={{
                          ...btn,
                          background: (!isGoogleSheetsConnected || !persistentWritesEnabled) ? '#64748b' : '#166534',
                          cursor: (busy || !isGoogleSheetsConnected || !persistentWritesEnabled) ? 'not-allowed' : 'pointer',
                        }}
                        disabled={busy || !isGoogleSheetsConnected || !persistentWritesEnabled}
                        title={(!isGoogleSheetsConnected || !persistentWritesEnabled) ? 'Google Sheets disconnected. Batch approval locked.' : ''}
                        onClick={() =>
                          runAction(
                            () =>
                              apiRequest(`/api/production/batches/${encodeURIComponent(b.production_id)}/approval`, {
                                method: 'POST',
                                body: JSON.stringify({ approved: true, notes: 'Approved by Owner' }),
                              }),
                            'Production approved; recipe consumption and bulk stock recorded.',
                            refreshBatches
                          )
                        }
                      >
                        Approve & deduct recipe
                      </button>
                      <button
                        style={{
                          ...btn,
                          background: (!isGoogleSheetsConnected || !persistentWritesEnabled) ? '#64748b' : '#b91c1c',
                          cursor: (busy || !isGoogleSheetsConnected || !persistentWritesEnabled) ? 'not-allowed' : 'pointer',
                        }}
                        disabled={busy || !isGoogleSheetsConnected || !persistentWritesEnabled}
                        title={(!isGoogleSheetsConnected || !persistentWritesEnabled) ? 'Google Sheets disconnected. Batch rejection locked.' : ''}
                        onClick={() =>
                          runAction(
                            () =>
                              apiRequest(`/api/production/batches/${encodeURIComponent(b.production_id)}/approval`, {
                                method: 'POST',
                                body: JSON.stringify({ approved: false, notes: 'Rejected by Owner' }),
                              }),
                            'Production rejected.',
                            refreshBatches
                          )
                        }
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <span style={{ fontSize: 12, color: '#64748b', fontStyle: 'italic', background: '#f1f5f9', padding: '4px 8px', borderRadius: 4 }}>
                      ⏳ Awaiting Owner approval & recipe deduction
                    </span>
                  )}
                </div>
              ))}
          </div>
        </>
      )}

      {/* PACKAGING TAB */}
      {tab === 'packaging' && (
        <>
          <div style={card}>
            <h3>Convert Unpackaged Bulk Papad into Packets</h3>
            <form
              onSubmit={e => {
                e.preventDefault();
                runAction(
                  () =>
                    apiRequest('/api/production/packaging', {
                      method: 'POST',
                      body: JSON.stringify({
                        ...pack,
                        bulk_kg_used: Number(pack.bulk_kg_used),
                        packets_200g: Number(pack.packets_200g),
                        packets_500g: Number(pack.packets_500g),
                        packets_1000g: Number(pack.packets_1000g),
                      }),
                    }),
                  'Packaging recorded. Review any flagged kg difference.',
                  refreshPackaging
                );
                setPack({
                  product_id: '',
                  packaging_date: today,
                  bulk_kg_used: '',
                  packets_200g: '0',
                  packets_500g: '0',
                  packets_1000g: '0',
                  notes: '',
                });
              }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10 }}
            >
              {productSelect(pack.product_id, v => setPack({ ...pack, product_id: v }))}
              <input
                style={input}
                type="date"
                value={pack.packaging_date}
                onChange={e => setPack({ ...pack, packaging_date: e.target.value })}
              />
              <input
                style={input}
                type="number"
                min="0.001"
                step="0.001"
                placeholder="Bulk kg used"
                value={pack.bulk_kg_used}
                onChange={e => setPack({ ...pack, bulk_kg_used: e.target.value })}
                required
              />
              <input
                style={input}
                type="number"
                min="0"
                step="1"
                placeholder="200 g packets"
                value={pack.packets_200g}
                onChange={e => setPack({ ...pack, packets_200g: e.target.value })}
              />
              <input
                style={input}
                type="number"
                min="0"
                step="1"
                placeholder="500 g packets"
                value={pack.packets_500g}
                onChange={e => setPack({ ...pack, packets_500g: e.target.value })}
              />
              <input
                style={input}
                type="number"
                min="0"
                step="1"
                placeholder="1 kg packets"
                value={pack.packets_1000g}
                onChange={e => setPack({ ...pack, packets_1000g: e.target.value })}
              />
              <input
                style={input}
                placeholder="Notes"
                value={pack.notes}
                onChange={e => setPack({ ...pack, notes: e.target.value })}
              />
              <button style={btn} disabled={busy}>
                Record packaging
              </button>
            </form>
            <p style={{ color: '#64748b' }}>
              Expected kg = 200 g packets × 0.2 + 500 g packets × 0.5 + 1 kg packets × 1. The system records and flags the difference
              for review.
            </p>
          </div>
          <div style={card}>
            <h3>Packaging history</h3>
            {rowsTable(packaging, [
              ['packaging_date', 'Date'],
              ['product_name_snapshot', 'Product'],
              ['bulk_kg_used', 'Bulk kg used'],
              ['total_packets', 'Packets made'],
              ['expected_kg', 'Expected kg'],
              ['difference_kg', 'Difference kg'],
              ['difference_status', 'Review status'],
            ])}
          </div>
        </>
      )}

      {/* DISPATCH TAB */}
      {tab === 'dispatch' && (
        <>
          <div style={card}>
            <h3>Dispatch Finished Packets to Sales Channels</h3>
            <form
              onSubmit={e => {
                e.preventDefault();
                runAction(
                  () =>
                    apiRequest('/api/production/dispatch', {
                      method: 'POST',
                      body: JSON.stringify({
                        ...dispatch,
                        quantity_packets: Number(dispatch.quantity_packets),
                      }),
                    }),
                  'Dispatch recorded. It is a stock transfer, not a sale.',
                  refreshDispatches
                );
                setDispatch({ ...dispatch, quantity_packets: '', destination: '', reference: '', notes: '' });
              }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}
            >
              {productSelect(dispatch.product_id, v => setDispatch({ ...dispatch, product_id: v }))}
              <select style={input} value={dispatch.channel} onChange={e => setDispatch({ ...dispatch, channel: e.target.value })}>
                <option value="ECOMMERCE">E-commerce</option>
                <option value="RETAIL">Retail</option>
                <option value="SALESMAN">Salesman</option>
                <option value="WHOLESALE">Wholesale</option>
                <option value="DISTRIBUTOR">Distributor</option>
              </select>
              <input
                style={input}
                placeholder="Destination / person / warehouse"
                value={dispatch.destination}
                onChange={e => setDispatch({ ...dispatch, destination: e.target.value })}
                required
              />
              <input
                style={input}
                type="number"
                min="1"
                step="1"
                placeholder="Packets dispatched"
                value={dispatch.quantity_packets}
                onChange={e => setDispatch({ ...dispatch, quantity_packets: e.target.value })}
                required
              />
              <input
                style={input}
                placeholder="Reference / challan no."
                value={dispatch.reference}
                onChange={e => setDispatch({ ...dispatch, reference: e.target.value })}
              />
              <input
                style={input}
                placeholder="Notes"
                value={dispatch.notes}
                onChange={e => setDispatch({ ...dispatch, notes: e.target.value })}
              />
              <button style={btn} disabled={busy}>
                Record dispatch
              </button>
            </form>
          </div>
          <div style={card}>
            <h3>Dispatch history</h3>
            {rowsTable(dispatches, [
              ['dispatch_datetime', 'Date/time'],
              ['product_name_snapshot', 'Product'],
              ['channel', 'Channel'],
              ['destination', 'Destination'],
              ['quantity_packets', 'Packets'],
              ['status', 'Status'],
              ['reference', 'Reference'],
            ])}
          </div>
        </>
      )}
    </section>
  );
};
