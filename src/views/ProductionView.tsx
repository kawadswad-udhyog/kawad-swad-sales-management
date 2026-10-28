import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  apiRequest,
  getRawMaterials,
  receiveRawMaterial,
  RawMaterialSummary,
  RawMaterialReceiveInput,
  recordMillingBatch,
  getMillingHistory,
  DalMillingInput,
  DalMillingResult,
  DalMillingHistoryItem,
} from '../services/api';
import { useStore } from '../context/StoreContext';
import { exportSheetToExcel } from '../utils/exportToExcel';
import { FinishedGoodsRegisterItem, FinishedGoodsRegisterSummary } from '../types';

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
  const [registerItems, setRegisterItems] = useState<FinishedGoodsRegisterItem[]>([]);
  const [registerSummary, setRegisterSummary] = useState<FinishedGoodsRegisterSummary | null>(null);
  const [registerFamilyFilter, setRegisterFamilyFilter] = useState<string>('ALL');
  const [registerWeightFilter, setRegisterWeightFilter] = useState<string>('ALL');
  const [registerSearch, setRegisterSearch] = useState<string>('');
  const [hideZeroStock, setHideZeroStock] = useState<boolean>(false);
  const [recoveringBatchId, setRecoveringBatchId] = useState<string | null>(null);
  const [tab, setTab] = useState(initialTab);
  const [batchSearch, setBatchSearch] = useState('');
  const [batchStatusFilter, setBatchStatusFilter] = useState('ALL');
  const [batchDateFilter, setBatchDateFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'success' | 'error' | null>(null);
  const actionMessageRef = useRef<string | null>(null);

  const showSuccess = (text: string) => {
    setMessageType('success');
    actionMessageRef.current = text;
    setMessage(text);
  };

  const showError = (text: string) => {
    setMessageType('error');
    actionMessageRef.current = null;
    setMessage(text);
  };

  const isError = useMemo(() => {
    if (!message) return false;
    if (messageType === 'error') return true;
    if (messageType === 'success') return false;
    const lower = message.toLowerCase();
    return (
      lower.includes('conflict') ||
      lower.includes('error') ||
      lower.includes('fail') ||
      lower.includes('could not') ||
      lower.includes('insufficient') ||
      lower.includes('cannot') ||
      lower.includes('invalid') ||
      lower.includes('required') ||
      lower.includes('must be') ||
      lower.includes('already recorded for this worker') ||
      lower.includes('no linked product') ||
      lower.includes('enter at least') ||
      lower.includes('rejected') ||
      lower.includes('blocked')
    );
  }, [message, messageType]);

  // Raw Materials Inward Receiving & Balance State (Stage 1)
  const [rawMaterials, setRawMaterials] = useState<RawMaterialSummary[]>([]);
  const [rmCategoryFilter, setRmCategoryFilter] = useState<string>('ALL');
  const [rmSearch, setRmSearch] = useState<string>('');
  const [receiveForm, setReceiveForm] = useState<{
    material_id: string;
    quantity: string;
    unit: string;
    purchase_rate: string;
    receipt_date: string;
    supplier_name: string;
    invoice_reference: string;
    line_number: string;
    freight_amount: string;
    other_expenses: string;
    gst_amount: string;
    gst_treatment: 'RECOVERABLE_ITC' | 'CAPITALIZED_TO_COST' | 'EXEMPT_NIL_RATED';
    notes: string;
  }>({
    material_id: 'RM-WHOLE-MOONG-DAL',
    quantity: '',
    unit: 'kg',
    purchase_rate: '',
    receipt_date: today,
    supplier_name: '',
    invoice_reference: '',
    line_number: '1',
    freight_amount: '0',
    other_expenses: '0',
    gst_amount: '0',
    gst_treatment: 'RECOVERABLE_ITC',
    notes: '',
  });

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

  const refreshRawMaterials = async () => {
    try {
      const data = await getRawMaterials();
      if (Array.isArray(data)) setRawMaterials(data);
    } catch (e) {
      console.warn('Could not refresh raw materials', e);
    }
  };

  // Stage 2: Dal Milling State
  const DAL_MILLING_CONFIG = [
    {
      id: 'RM-WHOLE-MOONG-DAL',
      name: 'Whole Moong Dal',
      flourId: 'RM-MOONG-FLOUR',
      flourName: 'Moong Dal Flour',
      badgeColor: '#166534',
      bgColor: '#dcfce7',
      borderColor: '#86efac',
      expectedLoss: '2.0% typical loss (skin/bran removal)',
    },
    {
      id: 'RM-WHOLE-URAD-DAL',
      name: 'Whole Urad Dal',
      flourId: 'RM-URAD-FLOUR',
      flourName: 'Urad Dal Flour',
      badgeColor: '#581c87',
      bgColor: '#f3e8ff',
      borderColor: '#d8b4fe',
      expectedLoss: '2.0% typical loss (skin/bran removal)',
    },
    {
      id: 'RM-WHOLE-CHANA-DAL',
      name: 'Whole Chana Dal',
      flourId: 'RM-CHANA-FLOUR',
      flourName: 'Chana Dal Flour',
      badgeColor: '#854d0e',
      bgColor: '#fef9c3',
      borderColor: '#fde047',
      expectedLoss: '2.5% typical loss (skin/bran removal)',
    },
  ];

  const [millingHistory, setMillingHistory] = useState<DalMillingHistoryItem[]>([]);
  const [millingForm, setMillingForm] = useState<{
    source_material_id: string;
    input_quantity_kg: string;
    flour_output_kg: string;
    milling_expenses: string;
    milling_date: string;
    batch_reference: string;
    notes: string;
  }>({
    source_material_id: 'RM-WHOLE-MOONG-DAL',
    input_quantity_kg: '',
    flour_output_kg: '',
    milling_expenses: '0',
    milling_date: today,
    batch_reference: '',
    notes: '',
  });

  const refreshMillingHistory = async () => {
    try {
      const history = await getMillingHistory();
      if (Array.isArray(history)) setMillingHistory(history);
    } catch (e) {
      console.warn('Could not refresh milling history', e);
    }
  };

  const load = async () => {
    const results = await Promise.allSettled([
      apiRequest<Product[]>('/api/products', { silent: true }),
      apiRequest<Row[]>('/api/production/workers', { silent: true }),
      apiRequest<Row[]>('/api/production/recipes', { silent: true }),
      apiRequest<Row[]>('/api/production/recipes/master', { silent: true }),
      apiRequest<Row[]>('/api/production/batches', { silent: true }),
      apiRequest<Row[]>('/api/production/packaging', { silent: true }),
      apiRequest<Row[]>('/api/production/dispatches', { silent: true }),
      apiRequest<Row>('/api/production/summary', { silent: true }),
      apiRequest<Row[]>('/api/production/attendance', { silent: true }),
      apiRequest<{ register: FinishedGoodsRegisterItem[]; summary: FinishedGoodsRegisterSummary }>('/api/production/finished-goods-register', { silent: true }),
      getRawMaterials(),
      getMillingHistory(),
    ]);

    const [pRes, wRes, rRes, mrRes, bRes, pkRes, dRes, sRes, aRes, regRes, rmRes, milRes] = results;

    if (pRes.status === 'fulfilled' && Array.isArray(pRes.value)) setProducts(pRes.value);
    if (wRes.status === 'fulfilled' && Array.isArray(wRes.value)) setWorkers(wRes.value);
    if (rRes.status === 'fulfilled' && Array.isArray(rRes.value)) setRecipes(rRes.value);
    if (mrRes.status === 'fulfilled' && Array.isArray(mrRes.value)) setMasterRecipes(mrRes.value);
    if (bRes.status === 'fulfilled' && Array.isArray(bRes.value)) setBatches([...bRes.value].reverse());
    if (pkRes.status === 'fulfilled' && Array.isArray(pkRes.value)) setPackaging([...pkRes.value].reverse());
    if (dRes.status === 'fulfilled' && Array.isArray(dRes.value)) setDispatches([...dRes.value].reverse());
    if (sRes.status === 'fulfilled' && sRes.value) {
      setSummary(sRes.value);
      if (sRes.value.finished_goods_register && Array.isArray(sRes.value.finished_goods_register)) {
        setRegisterItems(sRes.value.finished_goods_register);
      }
      if (sRes.value.register_summary) {
        setRegisterSummary(sRes.value.register_summary);
      }
    }
    if (regRes.status === 'fulfilled' && regRes.value) {
      if (Array.isArray(regRes.value.register)) setRegisterItems(regRes.value.register);
      if (regRes.value.summary) setRegisterSummary(regRes.value.summary);
    }
    if (aRes.status === 'fulfilled' && Array.isArray(aRes.value)) setAttendance([...aRes.value].reverse());
    if (rmRes.status === 'fulfilled' && Array.isArray(rmRes.value)) setRawMaterials(rmRes.value);
    if (milRes.status === 'fulfilled' && Array.isArray(milRes.value)) setMillingHistory(milRes.value);

    const anyFailed = results.some(r => r.status === 'rejected');
    if (anyFailed) {
      console.warn('Some production sub-resources could not be refreshed in background.');
    }
  };

  const refreshSummary = async () => {
    try {
      const s = await apiRequest<Row>('/api/production/summary', { silent: true });
      if (s) {
        setSummary(s);
        if (s.finished_goods_register && Array.isArray(s.finished_goods_register)) {
          setRegisterItems(s.finished_goods_register);
        }
        if (s.register_summary) {
          setRegisterSummary(s.register_summary);
        }
      }
    } catch (e) {
      console.warn('Could not refresh summary', e);
    }
  };

  const refreshAttendance = async () => {
    const [aRes, sRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/attendance', { silent: true }),
      apiRequest<Row>('/api/production/summary', { silent: true }),
    ]);
    if (aRes.status === 'fulfilled' && Array.isArray(aRes.value)) setAttendance([...aRes.value].reverse());
    if (sRes.status === 'fulfilled' && sRes.value) setSummary(sRes.value);
  };

  const refreshBatches = async () => {
    const [bRes, sRes] = await Promise.allSettled([
      apiRequest<Row[]>('/api/production/batches', { silent: true }),
      apiRequest<Row>('/api/production/summary', { silent: true }),
    ]);
    if (bRes.status === 'fulfilled' && Array.isArray(bRes.value)) {
      const normalized = bRes.value.map((b) => {
        const id = String(b.production_id || b.batch_id || '').trim();
        return {
          ...b,
          production_id: id,
          batch_id: id,
        };
      });
      setBatches([...normalized].reverse());
    }
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

  const refreshRegister = async () => {
    try {
      const res = await apiRequest<{ register: FinishedGoodsRegisterItem[]; summary: FinishedGoodsRegisterSummary }>(
        '/api/production/finished-goods-register'
      );
      if (res?.register) setRegisterItems(res.register);
      if (res?.summary) setRegisterSummary(res.summary);
    } catch (e) {
      console.warn('Could not refresh finished goods register', e);
    }
  };

  const handleRecoverPackaging = async (packagingId: string) => {
    if (busy || !packagingId) return;
    setRecoveringBatchId(packagingId);
    await runAction(
      () => apiRequest(`/api/production/packaging/${encodeURIComponent(packagingId)}/recover`, { method: 'POST' }),
      `Packaging batch ${packagingId} recovered successfully. Stock ledger movements posted.`,
      async () => {
        await refreshPackaging();
        await refreshRegister();
      }
    );
    setRecoveringBatchId(null);
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
      load().catch(e => showError(e.message || 'Could not load production data.'));
    }
  }, [canManage]);

  const runAction = async (
    fn: () => Promise<unknown>,
    defaultSuccess: string,
    targetedRefresh?: () => Promise<void>
  ): Promise<boolean> => {
    if (busy) return false;
    setBusy(true);
    setMessage('');
    setMessageType(null);
    actionMessageRef.current = null;
    try {
      const result = await fn();
      const customMsg = typeof result === 'string' && result.trim() ? result.trim() : null;
      const finalMsg = customMsg || actionMessageRef.current || defaultSuccess;
      showSuccess(finalMsg);
      try {
        if (targetedRefresh) {
          await targetedRefresh();
        } else {
          await load();
        }
      } catch (refreshErr: any) {
        console.warn('Post-action screen refresh warning:', refreshErr);
        showSuccess(`${finalMsg} (Data saved, refreshing screen...)`);
      }
      return true;
    } catch (e: any) {
      showError(e?.message || 'Action failed.');
      return false;
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
            background: isError ? '#fef2f2' : '#f0fdf4',
            borderColor: isError ? '#fca5a5' : '#86efac',
            color: isError ? '#991b1b' : '#166534',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            boxShadow: isError ? '0 1px 3px rgba(239, 68, 68, 0.1)' : '0 1px 3px rgba(34, 197, 94, 0.1)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18 }}>{isError ? '⚠️' : '✓'}</span>
            <span style={{ fontWeight: 600, fontSize: 14 }}>{message}</span>
          </div>
          <button
            type="button"
            onClick={() => {
              setMessage('');
              setMessageType(null);
            }}
            style={{
              background: 'transparent',
              border: 0,
              cursor: 'pointer',
              color: isError ? '#991b1b' : '#166534',
              fontSize: 18,
              fontWeight: 'bold',
              padding: '0 6px',
              lineHeight: 1,
            }}
            title="Dismiss message"
            aria-label="Dismiss message"
          >
            ×
          </button>
        </div>
      )}

      <div>
        {sectionButton('finished_goods', '📦 Finished Goods Register')}
        {sectionButton('master_recipes', '📜 Papad Formula Master (v2.0)')}
        {sectionButton('raw_materials', '🌾 Raw Materials Inward')}
        {sectionButton('milling', '🥣 Dal Milling (Flour Prep)')}
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
                          showSuccess(`Formula for ${r.product_name_snapshot} pre-selected in Daily Production.`);
                        } else {
                          showError(`No linked product found for ${r.product_name_snapshot}. Create product in Products master.`);
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

      {/* RAW MATERIALS INWARD RECEIVING & INVENTORY TAB (STAGE 1) */}
      {tab === 'raw_materials' && (
        <>
          {/* Header Card */}
          <div style={{ ...card, background: '#f8fafc', borderColor: '#cbd5e1' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h3 style={{ margin: '0 0 4px', color: '#1e293b' }}>🌾 Raw Material Procurement & Inward Receiving</h3>
                <p style={{ margin: 0, fontSize: 13, color: '#475569' }}>
                  Procure whole grain dal (Whole Moong Dal, Whole Urad Dal, Whole Chana Dal), flours, spices & packaging.
                  Landed cost incorporates supplier purchase rate, freight, and incidental expenses. GST treatment distinguishes recoverable ITC from capitalized material cost.
                </p>
              </div>
              <button
                type="button"
                style={{ ...btn, background: '#0284c7' }}
                disabled={busy}
                onClick={() => refreshRawMaterials()}
              >
                🔄 Refresh Inventory Balances
              </button>
            </div>
          </div>

          {/* Quick Stock KPI Cards */}
          {(() => {
            const wholeDalStock = rawMaterials
              .filter(m => m.category === 'WHOLE_GRAIN' || m.material_id.includes('WHOLE'))
              .reduce((acc, m) => acc + (m.available_stock || 0), 0);
            const flourStock = rawMaterials
              .filter(m => m.category === 'FLOUR' || m.material_name.toLowerCase().includes('flour'))
              .reduce((acc, m) => acc + (m.available_stock || 0), 0);
            const spiceCount = rawMaterials.filter(m => m.category === 'SPICE').length;
            const packagingCount = rawMaterials.filter(m => m.category === 'PACKAGING').length;

            return (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 16 }}>
                <div style={{ ...card, background: '#ecfdf5', borderColor: '#a7f3d0' }}>
                  <small style={{ color: '#065f46', fontWeight: 600 }}>🌾 Whole Dal Inventory (Factory Godown)</small>
                  <h2 style={{ margin: '6px 0 0', color: '#047857' }}>{wholeDalStock.toFixed(2)} kg</h2>
                  <div style={{ fontSize: 12, color: '#065f46', marginTop: 4 }}>
                    Moong, Urad, and Chana Whole Dal for internal milling
                  </div>
                </div>
                <div style={{ ...card, background: '#f0fdf4', borderColor: '#bbf7d0' }}>
                  <small style={{ color: '#166534', fontWeight: 600 }}>🥣 Milled Flour Inventory (Production Stock)</small>
                  <h2 style={{ margin: '6px 0 0', color: '#15803d' }}>{flourStock.toFixed(2)} kg</h2>
                  <div style={{ fontSize: 12, color: '#166534', marginTop: 4 }}>
                    Ready for Version 2.0 papad dough batching
                  </div>
                </div>
                <div style={{ ...card, background: '#f8fafc', borderColor: '#e2e8f0' }}>
                  <small style={{ color: '#475569', fontWeight: 600 }}>🌶️ Spices & Seasoning Materials</small>
                  <h2 style={{ margin: '6px 0 0', color: '#334155' }}>{spiceCount} Active Items</h2>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                    Hing, Black Pepper, Jeera, Sajji, Salt, etc.
                  </div>
                </div>
                <div style={{ ...card, background: '#f8fafc', borderColor: '#e2e8f0' }}>
                  <small style={{ color: '#475569', fontWeight: 600 }}>📦 Packaging Supplies</small>
                  <h2 style={{ margin: '6px 0 0', color: '#334155' }}>{packagingCount} Active Types</h2>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                    200g, 500g, 1000g printed pouches & cartons
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Inward Consignment Receiving Form */}
          <div style={{ ...card, borderColor: '#cbd5e1' }}>
            <h3 style={{ margin: '0 0 8px', color: '#14532d' }}>📥 Record Inward Consignment / Supplier Goods Receipt</h3>
            <p style={{ margin: '0 0 16px', fontSize: 13, color: '#64748b' }}>
              Appends an authoritative <code>PURCHASE_RECEIPT</code> row into <code>RawMaterialLedger</code>. Does not mutate the static opening baseline.
              Composite line idempotency ensures duplicate clicks or retries never inflate inventory.
            </p>

            {/* Calculations for live landed cost card */}
            {(() => {
              const qty = Math.max(0, parseFloat(receiveForm.quantity || '0'));
              const rate = Math.max(0, parseFloat(receiveForm.purchase_rate || '0'));
              const freight = Math.max(0, parseFloat(receiveForm.freight_amount || '0'));
              const other = Math.max(0, parseFloat(receiveForm.other_expenses || '0'));
              const gst = Math.max(0, parseFloat(receiveForm.gst_amount || '0'));
              const isCapitalized = receiveForm.gst_treatment === 'CAPITALIZED_TO_COST';
              const isRecoverable = receiveForm.gst_treatment === 'RECOVERABLE_ITC';

              const baseVal = Math.round(qty * rate * 100) / 100;
              const capGst = isCapitalized ? gst : 0;
              const totalLandedCost = Math.round((baseVal + freight + other + capGst) * 100) / 100;
              const landedRatePerUnit = qty > 0 ? Math.round((totalLandedCost / qty) * 100) / 100 : 0;

              return (
                <form
                  onSubmit={async e => {
                    e.preventDefault();
                    if (!receiveForm.material_id) {
                      showError('Please select a raw material.');
                      return;
                    }
                    if (qty <= 0) {
                      showError('Received quantity must be greater than 0.');
                      return;
                    }
                    if (rate <= 0) {
                      showError('Purchase rate must be greater than 0.');
                      return;
                    }
                    if (!receiveForm.supplier_name.trim()) {
                      showError('Supplier name is required.');
                      return;
                    }
                    if (!receiveForm.invoice_reference.trim()) {
                      showError('Invoice reference is required.');
                      return;
                    }

                    const selectedMat = rawMaterials.find(m => m.material_id === receiveForm.material_id);
                    const matName = selectedMat ? selectedMat.material_name : undefined;

                    await runAction(
                      async () => {
                        const payload: RawMaterialReceiveInput = {
                          material_id: receiveForm.material_id,
                          material_name: matName,
                          quantity: qty,
                          unit: receiveForm.unit || 'kg',
                          purchase_rate: rate,
                          receipt_date: receiveForm.receipt_date || today,
                          supplier_name: receiveForm.supplier_name.trim(),
                          invoice_reference: receiveForm.invoice_reference.trim(),
                          line_number: parseInt(receiveForm.line_number || '1', 10) || 1,
                          freight_amount: freight,
                          other_expenses: other,
                          gst_amount: gst,
                          gst_treatment: receiveForm.gst_treatment,
                          notes: receiveForm.notes.trim() || undefined,
                        };
                        const res = await receiveRawMaterial(payload);
                        const txnId = res.transaction_id || (res as any).raw_material_txn_id || '';
                        if (res.is_replay || (res as any).status === 'ALREADY_RECORDED') {
                          const replayMsg = `[Idempotent Replay] Receipt already recorded (${txnId}). Stock balance intact.`;
                          showSuccess(replayMsg);
                          return replayMsg;
                        }
                        const successMsg = `✓ Received ${res.quantity} ${res.unit} of ${res.material_name} (Tx: ${txnId}). Landed rate: ₹${res.landed_rate_per_unit}/${res.unit}. New Stock: ${res.new_available_stock} ${res.unit}.`;
                        showSuccess(successMsg);
                        return successMsg;
                      },
                      'Raw material receipt recorded successfully.',
                      refreshRawMaterials
                    );
                  }}
                >
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14, marginBottom: 14 }}>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Raw Material *
                      </label>
                      <select
                        style={input}
                        value={receiveForm.material_id}
                        onChange={e => {
                          const matId = e.target.value;
                          const mat = rawMaterials.find(m => m.material_id === matId);
                          setReceiveForm(prev => ({
                            ...prev,
                            material_id: matId,
                            unit: mat ? mat.unit : prev.unit,
                          }));
                        }}
                        required
                      >
                        <option value="">Select Raw Material</option>
                        <optgroup label="🌾 Whole Grain Dal (Factory Milling)">
                          {rawMaterials
                            .filter(m => m.category === 'WHOLE_GRAIN' || m.material_id.includes('WHOLE'))
                            .map(m => (
                              <option key={m.material_id} value={m.material_id}>
                                {m.material_name} ({m.material_id}) — Avail: {m.available_stock} {m.unit}
                              </option>
                            ))}
                        </optgroup>
                        <optgroup label="🥣 Milled Flours">
                          {rawMaterials
                            .filter(m => m.category === 'FLOUR')
                            .map(m => (
                              <option key={m.material_id} value={m.material_id}>
                                {m.material_name} ({m.material_id}) — Avail: {m.available_stock} {m.unit}
                              </option>
                            ))}
                        </optgroup>
                        <optgroup label="🌶️ Spices & Seasonings">
                          {rawMaterials
                            .filter(m => m.category === 'SPICE')
                            .map(m => (
                              <option key={m.material_id} value={m.material_id}>
                                {m.material_name} ({m.material_id})
                              </option>
                            ))}
                        </optgroup>
                        <optgroup label="📦 Packaging & Other">
                          {rawMaterials
                            .filter(m => m.category !== 'WHOLE_GRAIN' && m.category !== 'FLOUR' && m.category !== 'SPICE' && !m.material_id.includes('WHOLE'))
                            .map(m => (
                              <option key={m.material_id} value={m.material_id}>
                                {m.material_name} ({m.material_id})
                              </option>
                            ))}
                        </optgroup>
                      </select>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Received Quantity *
                      </label>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <input
                          type="number"
                          step="0.01"
                          min="0.01"
                          style={{ ...input, flex: 1 }}
                          placeholder="e.g. 100.00"
                          value={receiveForm.quantity}
                          onChange={e => setReceiveForm(prev => ({ ...prev, quantity: e.target.value }))}
                          required
                        />
                        <select
                          style={{ ...input, width: 90 }}
                          value={receiveForm.unit}
                          onChange={e => setReceiveForm(prev => ({ ...prev, unit: e.target.value }))}
                        >
                          <option value="kg">kg</option>
                          <option value="litre">litre</option>
                          <option value="g">g</option>
                          <option value="pcs">pcs</option>
                        </select>
                      </div>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Purchase Rate (₹ per unit) *
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        style={input}
                        placeholder="e.g. 110.00"
                        value={receiveForm.purchase_rate}
                        onChange={e => setReceiveForm(prev => ({ ...prev, purchase_rate: e.target.value }))}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Receipt Date *
                      </label>
                      <input
                        type="date"
                        style={input}
                        value={receiveForm.receipt_date}
                        onChange={e => setReceiveForm(prev => ({ ...prev, receipt_date: e.target.value }))}
                        required
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14, marginBottom: 14 }}>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Supplier / Mandi Trader *
                      </label>
                      <input
                        type="text"
                        style={input}
                        placeholder="e.g. Nimar Krishi Upaj Mandi, Barwani"
                        value={receiveForm.supplier_name}
                        onChange={e => setReceiveForm(prev => ({ ...prev, supplier_name: e.target.value }))}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Invoice / Bilty Reference *
                      </label>
                      <input
                        type="text"
                        style={input}
                        placeholder="e.g. INV-2025-884"
                        value={receiveForm.invoice_reference}
                        onChange={e => setReceiveForm(prev => ({ ...prev, invoice_reference: e.target.value }))}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Line Item No. on Invoice
                      </label>
                      <input
                        type="number"
                        min="1"
                        style={input}
                        placeholder="1"
                        value={receiveForm.line_number}
                        onChange={e => setReceiveForm(prev => ({ ...prev, line_number: e.target.value }))}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginBottom: 14 }}>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Freight / Transport (₹)
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        style={input}
                        placeholder="0.00"
                        value={receiveForm.freight_amount}
                        onChange={e => setReceiveForm(prev => ({ ...prev, freight_amount: e.target.value }))}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Loading / Unloading / Other (₹)
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        style={input}
                        placeholder="0.00"
                        value={receiveForm.other_expenses}
                        onChange={e => setReceiveForm(prev => ({ ...prev, other_expenses: e.target.value }))}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        GST Treatment *
                      </label>
                      <select
                        style={input}
                        value={receiveForm.gst_treatment}
                        onChange={e => setReceiveForm(prev => ({ ...prev, gst_treatment: e.target.value as any }))}
                      >
                        <option value="RECOVERABLE_ITC">Recoverable ITC (Excluded from cost)</option>
                        <option value="CAPITALIZED_TO_COST">Capitalized to Cost (Ineligible / Unreg)</option>
                        <option value="EXEMPT_NIL_RATED">Exempt / Nil Rated (No GST)</option>
                      </select>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        GST Tax Amount (₹)
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        style={input}
                        placeholder="0.00"
                        value={receiveForm.gst_amount}
                        onChange={e => setReceiveForm(prev => ({ ...prev, gst_amount: e.target.value }))}
                      />
                    </div>
                  </div>

                  <div style={{ marginBottom: 14 }}>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                      Consignment Notes / Quality Check
                    </label>
                    <input
                      type="text"
                      style={input}
                      placeholder="e.g. Moisture 11%, Premium Nimar harvest, gunny bags intact"
                      value={receiveForm.notes}
                      onChange={e => setReceiveForm(prev => ({ ...prev, notes: e.target.value }))}
                    />
                  </div>

                  {/* Landed Cost Preview Card */}
                  <div
                    style={{
                      background: '#f8fafc',
                      border: '1px solid #cbd5e1',
                      borderRadius: 8,
                      padding: 14,
                      marginBottom: 16,
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                      gap: 12,
                      alignItems: 'center',
                    }}
                  >
                    <div>
                      <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                        Base Value
                      </span>
                      <div style={{ fontSize: 16, fontWeight: 700, color: '#1e293b' }}>₹{baseVal.toFixed(2)}</div>
                      <small style={{ color: '#64748b' }}>({qty} × ₹{rate})</small>
                    </div>

                    <div>
                      <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                        Additional Expenses
                      </span>
                      <div style={{ fontSize: 16, fontWeight: 700, color: '#1e293b' }}>
                        ₹{(freight + other).toFixed(2)}
                      </div>
                      <small style={{ color: '#64748b' }}>Freight + Handling</small>
                    </div>

                    <div>
                      <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                        GST Cost Treatment
                      </span>
                      <div style={{ fontSize: 14, fontWeight: 700, color: isCapitalized ? '#b45309' : '#047857' }}>
                        {isCapitalized ? `+₹${capGst.toFixed(2)} (Capitalized)` : `₹0 in Cost (ITC Claimed)`}
                      </div>
                      <small style={{ color: isRecoverable ? '#047857' : '#64748b' }}>
                        {isRecoverable ? `₹${gst.toFixed(2)} Recoverable via GSTR-2B` : receiveForm.gst_treatment}
                      </small>
                    </div>

                    <div style={{ borderLeft: '2px solid #cbd5e1', paddingLeft: 12 }}>
                      <span style={{ fontSize: 11, color: '#14532d', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 700 }}>
                        Effective Landed Cost / Rate
                      </span>
                      <div style={{ fontSize: 20, fontWeight: 800, color: '#14532d' }}>
                        ₹{landedRatePerUnit.toFixed(2)} <span style={{ fontSize: 12, fontWeight: 500 }}>/ {receiveForm.unit}</span>
                      </div>
                      <small style={{ color: '#475569' }}>Total Batch: ₹{totalLandedCost.toFixed(2)}</small>
                    </div>
                  </div>

                  <button
                    type="submit"
                    style={{ ...btn, background: '#166534', width: '100%', padding: '12px 16px', fontSize: 15 }}
                    disabled={busy || !receiveForm.material_id || qty <= 0 || rate <= 0}
                  >
                    📥 {busy ? 'Saving Receipt to Inventory...' : 'Confirm & Record Inward Consignment Receipt'}
                  </button>
                </form>
              );
            })()}
          </div>

          {/* Raw Material Inventory Table */}
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
              <div>
                <h3 style={{ margin: '0 0 4px', color: '#1e293b' }}>📊 Factory Raw Material Balances & Valuation</h3>
                <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>
                  Computed dynamically from opening baseline + inward receipts (RawMaterialLedger) - production issuances.
                </p>
              </div>

              {/* Filters */}
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  placeholder="🔍 Search material..."
                  style={{ ...input, width: 180, padding: '6px 10px', fontSize: 12 }}
                  value={rmSearch}
                  onChange={e => setRmSearch(e.target.value)}
                />
                <select
                  style={{ ...input, width: 160, padding: '6px 10px', fontSize: 12 }}
                  value={rmCategoryFilter}
                  onChange={e => setRmCategoryFilter(e.target.value)}
                >
                  <option value="ALL">All Categories</option>
                  <option value="WHOLE_GRAIN">🌾 Whole Grain Dal</option>
                  <option value="FLOUR">🥣 Flours</option>
                  <option value="SPICE">🌶️ Spices</option>
                  <option value="PACKAGING">📦 Packaging</option>
                </select>
              </div>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#f1f5f9', color: '#475569' }}>
                    <th style={{ textAlign: 'left', padding: '8px 10px' }}>Material ID</th>
                    <th style={{ textAlign: 'left', padding: '8px 10px' }}>Material Name</th>
                    <th style={{ textAlign: 'left', padding: '8px 10px' }}>Category</th>
                    <th style={{ textAlign: 'right', padding: '8px 10px' }}>Baseline Opening</th>
                    <th style={{ textAlign: 'right', padding: '8px 10px' }}>Inward Received</th>
                    <th style={{ textAlign: 'right', padding: '8px 10px' }}>Issued / Consumed</th>
                    <th style={{ textAlign: 'right', padding: '8px 10px' }}>Available Stock</th>
                    <th style={{ textAlign: 'right', padding: '8px 10px' }}>Latest Landed Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {rawMaterials
                    .filter(m => {
                      if (rmCategoryFilter !== 'ALL' && m.category !== rmCategoryFilter) {
                        if (rmCategoryFilter === 'WHOLE_GRAIN' && !m.material_id.includes('WHOLE')) return false;
                        if (rmCategoryFilter !== 'WHOLE_GRAIN') return false;
                      }
                      if (rmSearch.trim()) {
                        const q = rmSearch.toLowerCase();
                        return (
                          m.material_id.toLowerCase().includes(q) ||
                          m.material_name.toLowerCase().includes(q) ||
                          m.category.toLowerCase().includes(q)
                        );
                      }
                      return true;
                    })
                    .map(m => {
                      const isWhole = m.category === 'WHOLE_GRAIN' || m.material_id.includes('WHOLE');
                      return (
                        <tr
                          key={m.material_id}
                          style={{
                            borderBottom: '1px solid #e2e8f0',
                            background: isWhole ? '#f0fdf4' : 'transparent',
                          }}
                        >
                          <td style={{ padding: '8px 10px', fontFamily: 'monospace', fontWeight: 600 }}>
                            {m.material_id}
                          </td>
                          <td style={{ padding: '8px 10px', fontWeight: 600, color: '#1e293b' }}>
                            {isWhole ? '🌾 ' : ''}{m.material_name}
                          </td>
                          <td style={{ padding: '8px 10px' }}>
                            <span
                              style={{
                                fontSize: 11,
                                padding: '2px 6px',
                                borderRadius: 4,
                                background: isWhole ? '#bbf7d0' : '#e2e8f0',
                                color: isWhole ? '#14532d' : '#334155',
                                fontWeight: 600,
                              }}
                            >
                              {m.category}
                            </span>
                          </td>
                          <td style={{ textAlign: 'right', padding: '8px 10px', color: '#64748b' }}>
                            {m.baseline_stock} {m.unit}
                          </td>
                          <td style={{ textAlign: 'right', padding: '8px 10px', color: '#047857', fontWeight: 600 }}>
                            +{m.total_received} {m.unit}
                          </td>
                          <td style={{ textAlign: 'right', padding: '8px 10px', color: '#dc2626' }}>
                            -{m.total_consumed} {m.unit}
                          </td>
                          <td style={{ textAlign: 'right', padding: '8px 10px' }}>
                            <span
                              style={{
                                padding: '3px 8px',
                                borderRadius: 6,
                                fontWeight: 700,
                                background: (m.available_stock || 0) > 0 ? '#dcfce7' : '#fee2e2',
                                color: (m.available_stock || 0) > 0 ? '#166534' : '#991b1b',
                              }}
                            >
                              {m.available_stock} {m.unit}
                            </span>
                          </td>
                          <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 600, color: '#1e293b' }}>
                            {m.latest_landed_rate > 0 ? `₹${m.latest_landed_rate.toFixed(2)} / ${m.unit}` : '—'}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
              {!rawMaterials.length && <p style={{ color: '#64748b', padding: 12 }}>No raw materials found.</p>}
            </div>
          </div>
        </>
      )}

      {/* DAL MILLING TAB (STAGE 2) */}
      {tab === 'milling' && (
        <>
          {/* Header & Controls */}
          <div style={{ ...card, background: '#f8fafc', borderColor: '#cbd5e1' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h3 style={{ margin: '0 0 4px', color: '#1e293b' }}>
                  🥣 Internal Factory Dal Milling (Flour Preparation)
                </h3>
                <p style={{ margin: 0, fontSize: 13, color: '#475569' }}>
                  Converts purchased Whole Dal into pure Milled Flour for papad production. Grinding expenses and milling loss are absorbed directly into the landed flour cost per kg.
                </p>
              </div>
              <button
                type="button"
                style={{ ...btn, background: '#0f766e', display: 'flex', alignItems: 'center', gap: 6 }}
                disabled={busy}
                onClick={async () => {
                  await runAction(
                    async () => {
                      await Promise.all([refreshRawMaterials(), refreshMillingHistory()]);
                    },
                    'Milling stock and history refreshed successfully.'
                  );
                }}
              >
                🔄 Refresh Stock & Milling Batches
              </button>
            </div>

            {/* Live Conversion Pipeline Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14, marginTop: 16 }}>
              {DAL_MILLING_CONFIG.map(cfg => {
                const wholeMat = rawMaterials.find(m => m.material_id === cfg.id);
                const flourMat = rawMaterials.find(m => m.material_id === cfg.flourId);
                const wholeAvail = wholeMat ? wholeMat.available_stock : 0;
                const wholeRate = wholeMat?.latest_landed_rate || 0;
                const flourAvail = flourMat ? flourMat.available_stock : 0;
                const flourRate = flourMat?.latest_landed_rate || 0;

                return (
                  <div
                    key={cfg.id}
                    style={{
                      background: cfg.bgColor,
                      border: `1.5px solid ${cfg.borderColor}`,
                      borderRadius: 10,
                      padding: 14,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ fontWeight: 700, fontSize: 14, color: cfg.badgeColor }}>
                        {cfg.name} ➔ {cfg.flourName}
                      </span>
                      <span style={{ fontSize: 11, background: '#fff', color: '#475569', padding: '2px 8px', borderRadius: 12, border: '1px solid #cbd5e1' }}>
                        {cfg.expectedLoss}
                      </span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 8, alignItems: 'center', background: '#ffffffcc', padding: 10, borderRadius: 8 }}>
                      <div>
                        <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>Whole Dal Stock</div>
                        <div style={{ fontSize: 16, fontWeight: 800, color: '#0f172a' }}>
                          {wholeAvail} <span style={{ fontSize: 11, fontWeight: 500 }}>kg</span>
                        </div>
                        <small style={{ color: '#047857', fontWeight: 600 }}>
                          {wholeRate > 0 ? `₹${wholeRate.toFixed(2)}/kg` : 'No rate'}
                        </small>
                      </div>

                      <div style={{ fontSize: 18, color: cfg.badgeColor, fontWeight: 800 }}>➔</div>

                      <div>
                        <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>Milled Flour Stock</div>
                        <div style={{ fontSize: 16, fontWeight: 800, color: '#0f172a' }}>
                          {flourAvail} <span style={{ fontSize: 11, fontWeight: 500 }}>kg</span>
                        </div>
                        <small style={{ color: '#047857', fontWeight: 600 }}>
                          {flourRate > 0 ? `₹${flourRate.toFixed(2)}/kg` : 'No rate'}
                        </small>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* New Milling Batch Form */}
          <div style={card}>
            <h3 style={{ margin: '0 0 4px', color: '#14532d' }}>⚙️ Record New Factory Milling Batch</h3>
            <p style={{ margin: '0 0 16px', fontSize: 12, color: '#64748b' }}>
              Appends a consumption record for Whole Dal and a production receipt record for Milled Flour in RawMaterialLedger.
            </p>

            {(() => {
              const activeDalCfg = DAL_MILLING_CONFIG.find(c => c.id === millingForm.source_material_id) || DAL_MILLING_CONFIG[0];
              const wholeMat = rawMaterials.find(m => m.material_id === activeDalCfg.id);
              const wholeAvail = wholeMat ? wholeMat.available_stock : 0;
              const wholeRate = wholeMat?.latest_landed_rate || 0;

              const flourMat = rawMaterials.find(m => m.material_id === activeDalCfg.flourId);
              const flourAvail = flourMat ? flourMat.available_stock : 0;

              const inQty = parseFloat(millingForm.input_quantity_kg || '0') || 0;
              const outQty = parseFloat(millingForm.flour_output_kg || '0') || 0;
              const expVal = parseFloat(millingForm.milling_expenses || '0') || 0;

              const dalCost = inQty * wholeRate;
              const totalMilledCost = dalCost + expVal;
              const lossKg = inQty > 0 && outQty > 0 ? inQty - outQty : 0;
              const lossPct = inQty > 0 ? (lossKg / inQty) * 100 : 0;
              const unitFlourCost = outQty > 0 ? totalMilledCost / outQty : 0;

              const isOverStock = inQty > wholeAvail;
              const isInvalidOutput = outQty > inQty && inQty > 0;

              return (
                <form
                  onSubmit={async e => {
                    e.preventDefault();
                    if (!millingForm.source_material_id) {
                      showError('Please select a source whole dal.');
                      return;
                    }
                    if (inQty <= 0) {
                      showError('Whole dal input quantity must be greater than zero.');
                      return;
                    }
                    if (outQty <= 0) {
                      showError('Flour output quantity must be greater than zero.');
                      return;
                    }
                    if (outQty > inQty) {
                      showError(`Flour output (${outQty} kg) cannot exceed whole dal input (${inQty} kg).`);
                      return;
                    }
                    if (isOverStock) {
                      showError(`Insufficient whole dal stock: requested ${inQty} kg but only ${wholeAvail} kg available.`);
                      return;
                    }

                    await runAction(
                      async () => {
                        const payload: DalMillingInput = {
                          source_material_id: millingForm.source_material_id,
                          input_quantity_kg: inQty,
                          flour_output_kg: outQty,
                          milling_expenses: expVal,
                          milling_date: millingForm.milling_date || today,
                          batch_reference: millingForm.batch_reference.trim() || undefined,
                          notes: millingForm.notes.trim() || undefined,
                        };

                        const res = await recordMillingBatch(payload);
                        if (res.is_replay || (res as any).status === 'ALREADY_RECORDED') {
                          const msg = `[Idempotent Replay] Milling batch ${res.milling_batch_id} already recorded. Stock balance intact.`;
                          showSuccess(msg);
                          return msg;
                        }

                        const msg = `✓ Milled ${res.input_quantity_kg} kg ${res.source_material_name} → ${res.flour_output_kg} kg ${res.target_flour_name} (Batch ${res.milling_batch_id}). Landed Flour Rate: ₹${res.flour_unit_cost.toFixed(2)}/kg (Loss: ${res.loss_percentage}%).`;
                        showSuccess(msg);

                        // Reset non-date form fields
                        setMillingForm(prev => ({
                          ...prev,
                          input_quantity_kg: '',
                          flour_output_kg: '',
                          milling_expenses: '0',
                          batch_reference: '',
                          notes: '',
                        }));

                        return msg;
                      },
                      'Dal milling batch recorded successfully.',
                      async () => {
                        await Promise.all([refreshRawMaterials(), refreshMillingHistory()]);
                      }
                    );
                  }}
                >
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14, marginBottom: 14 }}>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Source Whole Dal *
                      </label>
                      <select
                        style={input}
                        value={millingForm.source_material_id}
                        onChange={e => setMillingForm(prev => ({ ...prev, source_material_id: e.target.value }))}
                        required
                      >
                        {DAL_MILLING_CONFIG.map(cfg => {
                          const m = rawMaterials.find(rm => rm.material_id === cfg.id);
                          const avail = m ? m.available_stock : 0;
                          return (
                            <option key={cfg.id} value={cfg.id}>
                              {cfg.name} ➔ produces {cfg.flourName} (Available: {avail} kg)
                            </option>
                          );
                        })}
                      </select>
                      <small style={{ color: isOverStock ? '#dc2626' : '#64748b', fontWeight: isOverStock ? 700 : 400 }}>
                        Current available stock: <b>{wholeAvail} kg</b> {wholeRate > 0 ? `(@ ₹${wholeRate.toFixed(2)}/kg)` : ''}
                      </small>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Whole Dal Input Quantity (kg) *
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        max={wholeAvail > 0 ? wholeAvail : undefined}
                        style={{
                          ...input,
                          borderColor: isOverStock ? '#ef4444' : '#cbd5e1',
                          background: isOverStock ? '#fef2f2' : '#fff',
                        }}
                        placeholder="e.g. 100.00"
                        value={millingForm.input_quantity_kg}
                        onChange={e => setMillingForm(prev => ({ ...prev, input_quantity_kg: e.target.value }))}
                        required
                      />
                      {isOverStock && (
                        <small style={{ color: '#dc2626', fontWeight: 600 }}>
                          ⚠️ Exceeds available whole dal stock ({wholeAvail} kg)
                        </small>
                      )}
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Flour Output Produced (kg) *
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        style={{
                          ...input,
                          borderColor: isInvalidOutput ? '#ef4444' : '#cbd5e1',
                          background: isInvalidOutput ? '#fef2f2' : '#fff',
                        }}
                        placeholder="e.g. 98.00"
                        value={millingForm.flour_output_kg}
                        onChange={e => setMillingForm(prev => ({ ...prev, flour_output_kg: e.target.value }))}
                        required
                      />
                      {isInvalidOutput && (
                        <small style={{ color: '#dc2626', fontWeight: 600 }}>
                          ⚠️ Output cannot exceed input quantity ({inQty} kg)
                        </small>
                      )}
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Milling / Grinding Expenses (₹)
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        style={input}
                        placeholder="e.g. 300.00 (electricity, labor, milling charge)"
                        value={millingForm.milling_expenses}
                        onChange={e => setMillingForm(prev => ({ ...prev, milling_expenses: e.target.value }))}
                      />
                      <small style={{ color: '#64748b' }}>Absorbed into flour landed rate per kg</small>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Milling Run Date *
                      </label>
                      <input
                        type="date"
                        style={input}
                        value={millingForm.milling_date}
                        onChange={e => setMillingForm(prev => ({ ...prev, milling_date: e.target.value }))}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                        Machine / Batch Reference (Optional)
                      </label>
                      <input
                        type="text"
                        style={input}
                        placeholder="e.g. MILL-RUN-01 or Machine #2"
                        value={millingForm.batch_reference}
                        onChange={e => setMillingForm(prev => ({ ...prev, batch_reference: e.target.value }))}
                      />
                    </div>
                  </div>

                  <div style={{ marginBottom: 14 }}>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: '#334155' }}>
                      Operator / Process Notes (Optional)
                    </label>
                    <input
                      type="text"
                      style={input}
                      placeholder="e.g. Grade A clean moong, stone ground, 2% moisture loss"
                      value={millingForm.notes}
                      onChange={e => setMillingForm(prev => ({ ...prev, notes: e.target.value }))}
                    />
                  </div>

                  {/* Real-time Calculation Summary Box */}
                  <div
                    style={{
                      background: '#f8fafc',
                      border: '1.5px solid #cbd5e1',
                      borderRadius: 10,
                      padding: 14,
                      marginBottom: 16,
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                      gap: 12,
                    }}
                  >
                    <div>
                      <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>
                        Whole Dal Cost Basis
                      </span>
                      <div style={{ fontSize: 18, fontWeight: 800, color: '#1e293b' }}>
                        ₹{dalCost.toFixed(2)}
                      </div>
                      <small style={{ color: '#64748b' }}>
                        {inQty} kg @ ₹{wholeRate.toFixed(2)}/kg
                      </small>
                    </div>

                    <div>
                      <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>
                        Milling Loss
                      </span>
                      <div style={{ fontSize: 18, fontWeight: 800, color: lossPct > 5 ? '#dc2626' : '#d97706' }}>
                        {lossKg.toFixed(2)} kg ({lossPct.toFixed(1)}%)
                      </div>
                      <small style={{ color: '#64748b' }}>
                        Target: ~2.0% - 2.5%
                      </small>
                    </div>

                    <div>
                      <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>
                        Total Flour Cost Value
                      </span>
                      <div style={{ fontSize: 18, fontWeight: 800, color: '#0f172a' }}>
                        ₹{totalMilledCost.toFixed(2)}
                      </div>
                      <small style={{ color: '#047857' }}>
                        Dal (₹{dalCost.toFixed(2)}) + Exp (₹{expVal.toFixed(2)})
                      </small>
                    </div>

                    <div style={{ borderLeft: '2px solid #86efac', paddingLeft: 12 }}>
                      <span style={{ fontSize: 11, color: '#14532d', textTransform: 'uppercase', fontWeight: 700 }}>
                        New Landed Flour Rate
                      </span>
                      <div style={{ fontSize: 22, fontWeight: 800, color: '#14532d' }}>
                        ₹{unitFlourCost.toFixed(2)} <span style={{ fontSize: 12, fontWeight: 500 }}>/ kg</span>
                      </div>
                      <small style={{ color: '#475569' }}>
                        Automatically feeds recipe costing
                      </small>
                    </div>
                  </div>

                  <button
                    type="submit"
                    style={{
                      ...btn,
                      background: '#15803d',
                      width: '100%',
                      padding: '12px 16px',
                      fontSize: 15,
                    }}
                    disabled={busy || inQty <= 0 || outQty <= 0 || isOverStock || isInvalidOutput}
                  >
                    🥣 {busy ? 'Processing Dal Milling Batch...' : 'Commit Factory Dal Milling Batch'}
                  </button>
                </form>
              );
            })()}
          </div>

          {/* Milling History Table */}
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div>
                <h3 style={{ margin: '0 0 4px', color: '#1e293b' }}>📜 Completed Dal Milling Batches</h3>
                <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>
                  Two-legged ledger entries: Whole Dal issue (MILLING_CONSUMPTION) + Flour receipt (MILLING_OUTPUT).
                </p>
              </div>
              <span style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>
                Total Batches: {millingHistory.length}
              </span>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: '#f1f5f9', borderBottom: '2px solid #cbd5e1' }}>
                    <th style={{ textAlign: 'left', padding: '9px 10px' }}>Batch ID</th>
                    <th style={{ textAlign: 'left', padding: '9px 10px' }}>Date</th>
                    <th style={{ textAlign: 'left', padding: '9px 10px' }}>Whole Dal Consumed</th>
                    <th style={{ textAlign: 'left', padding: '9px 10px' }}>Flour Produced</th>
                    <th style={{ textAlign: 'right', padding: '9px 10px' }}>Loss (kg / %)</th>
                    <th style={{ textAlign: 'right', padding: '9px 10px' }}>Milling Exp</th>
                    <th style={{ textAlign: 'right', padding: '9px 10px' }}>Landed Flour Rate</th>
                    <th style={{ textAlign: 'right', padding: '9px 10px' }}>Total Cost</th>
                    <th style={{ textAlign: 'left', padding: '9px 10px' }}>Ref / Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {millingHistory.map(item => (
                    <tr key={item.milling_batch_id} style={{ borderBottom: '1px solid #e2e8f0' }}>
                      <td style={{ padding: '8px 10px', fontWeight: 700, fontFamily: 'monospace', color: '#0f766e' }}>
                        {item.milling_batch_id}
                      </td>
                      <td style={{ padding: '8px 10px', color: '#475569' }}>
                        {item.milling_date}
                      </td>
                      <td style={{ padding: '8px 10px', color: '#991b1b', fontWeight: 600 }}>
                        -{item.input_quantity_kg} kg {item.source_material_name}
                        <br />
                        <span style={{ fontSize: 10, color: '#64748b' }}>@ ₹{item.source_unit_rate.toFixed(2)}/kg</span>
                      </td>
                      <td style={{ padding: '8px 10px', color: '#166534', fontWeight: 600 }}>
                        +{item.flour_output_kg} kg {item.target_flour_name}
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: item.loss_percentage > 5 ? '#dc2626' : '#d97706', fontWeight: 600 }}>
                        {item.processing_loss_kg.toFixed(2)} kg
                        <br />
                        <span style={{ fontSize: 10 }}>({item.loss_percentage.toFixed(1)}%)</span>
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: '#475569' }}>
                        ₹{item.milling_expenses.toFixed(2)}
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 800, color: '#166534' }}>
                        ₹{item.flour_unit_cost.toFixed(2)}/kg
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 700, color: '#0f172a' }}>
                        ₹{item.total_flour_cost.toFixed(2)}
                      </td>
                      <td style={{ padding: '8px 10px', color: '#64748b' }}>
                        {item.batch_reference ? <span style={{ fontWeight: 600 }}>[{item.batch_reference}] </span> : null}
                        {item.notes || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!millingHistory.length && (
                <p style={{ color: '#64748b', padding: '16px 12px', textAlign: 'center', margin: 0 }}>
                  No milling batches recorded yet. Record your first dal-to-flour grinding run above.
                </p>
              )}
            </div>
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
                  showError('Attendance is already recorded for this worker on this date.');
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
                  showError('Enter at least one valid ingredient line.');
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
              onSubmit={async e => {
                e.preventDefault();
                const ok = await runAction(
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
                  'Production batch saved as PENDING APPROVAL. Owner will review before stock is credited.',
                  refreshBatches
                );
                if (ok) {
                  setProduction({ product_id: '', production_date: today, quantity_kg: '', wastage_kg: '0', flour_base_used_kg: '', recipe_id: '', notes: '' });
                }
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
                placeholder="Gross Produced (kg) *"
                value={production.quantity_kg}
                onChange={e => setProduction({ ...production, quantity_kg: e.target.value })}
                required
              />
              <input
                style={input}
                type="number"
                min="0"
                step="0.001"
                placeholder="Rejected / Wastage (kg)"
                value={production.wastage_kg}
                onChange={e => setProduction({ ...production, wastage_kg: e.target.value })}
              />
              <input
                style={input}
                placeholder="Notes / Batch shift (Optional)"
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
                    fontWeight: 700,
                  }}
                  disabled={busy || !isGoogleSheetsConnected || !persistentWritesEnabled}
                  title={(!isGoogleSheetsConnected || !persistentWritesEnabled) ? 'Google Sheets disconnected. Batch creation locked to prevent data loss.' : ''}
                >
                  {(!isGoogleSheetsConnected || !persistentWritesEnabled) ? '🔒 Locked (Sheets Disconnected)' : 'SAVE PRODUCTION'}
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
              .map(b => {
                const bId = String(b.production_id || b.batch_id || '').trim();
                return (
                <div
                  key={bId || Math.random()}
                  style={{
                    padding: '10px 0',
                    borderTop: '1px solid #e2e8f0',
                    display: 'flex',
                    gap: 10,
                    alignItems: 'center',
                    flexWrap: 'wrap',
                  }}
                >
                  <b>{bId || 'Batch'}</b>
                  <span>
                    {b.product_name_snapshot}: <b>{b.net_quantity_kg} kg net</b>
                    {b.flour_base_used_kg && ` (Flour: ${b.flour_base_used_kg} kg)`}
                  </span>
                  {isOwner ? (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <button
                        style={{
                          ...btn,
                          background: (!isGoogleSheetsConnected || !persistentWritesEnabled || !bId) ? '#64748b' : '#166534',
                          cursor: (busy || !isGoogleSheetsConnected || !persistentWritesEnabled || !bId) ? 'not-allowed' : 'pointer',
                        }}
                        disabled={busy || !isGoogleSheetsConnected || !persistentWritesEnabled || !bId}
                        title={(!isGoogleSheetsConnected || !persistentWritesEnabled) ? 'Google Sheets disconnected. Batch approval locked.' : ''}
                        onClick={() =>
                          runAction(
                            () =>
                              apiRequest(`/api/production/batches/${encodeURIComponent(bId)}/approval`, {
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
                          background: (!isGoogleSheetsConnected || !persistentWritesEnabled || !bId) ? '#64748b' : '#b91c1c',
                          cursor: (busy || !isGoogleSheetsConnected || !persistentWritesEnabled || !bId) ? 'not-allowed' : 'pointer',
                        }}
                        disabled={busy || !isGoogleSheetsConnected || !persistentWritesEnabled || !bId}
                        title={(!isGoogleSheetsConnected || !persistentWritesEnabled) ? 'Google Sheets disconnected. Batch rejection locked.' : ''}
                        onClick={() =>
                          runAction(
                            () =>
                              apiRequest(`/api/production/batches/${encodeURIComponent(bId)}/approval`, {
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
              );
            })}
          </div>
        </>
      )}

      {/* PACKAGING TAB */}
      {tab === 'packaging' && (
        <>
          <div style={card}>
            <h3>Convert Unpackaged Bulk Papad into Packets</h3>
            <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 12px' }}>
              Recording packaging credits finished packets directly to the <b>ProductionStockLedger</b>. Product availability is pre-validated
              before creating the batch record to prevent orphaned rows.
            </p>
            <form
              onSubmit={async e => {
                e.preventDefault();
                const ref = 'PKG-' + Date.now();
                const ok = await runAction(
                  () =>
                    apiRequest('/api/production/packaging', {
                      method: 'POST',
                      body: JSON.stringify({
                        ...pack,
                        bulk_kg_used: Number(pack.bulk_kg_used),
                        packets_200g: Number(pack.packets_200g),
                        packets_500g: Number(pack.packets_500g),
                        packets_1000g: Number(pack.packets_1000g),
                        reference: ref,
                      }),
                    }),
                  'Packaging recorded. Finished packets credited to factory stock ledger.',
                  async () => {
                    await refreshPackaging();
                    await refreshRegister();
                  }
                );
                if (ok) {
                  setPack({
                    product_id: '',
                    packaging_date: today,
                    bulk_kg_used: '',
                    packets_200g: '0',
                    packets_500g: '0',
                    packets_1000g: '0',
                    notes: '',
                  });
                }
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
              Expected kg = 200 g packets × 0.2 + 500 g packets × 0.5 + 1 kg packets × 1. The system records and flags any difference
              for physical audit reconciliation.
            </p>
          </div>
          <div style={card}>
            <h3>Packaging history &amp; ledger recovery</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#f1f5f9' }}>
                    <th style={{ textAlign: 'left', padding: 9 }}>Date</th>
                    <th style={{ textAlign: 'left', padding: 9 }}>Product</th>
                    <th style={{ textAlign: 'right', padding: 9 }}>Bulk kg</th>
                    <th style={{ textAlign: 'right', padding: 9 }}>Packets</th>
                    <th style={{ textAlign: 'right', padding: 9 }}>Expected kg</th>
                    <th style={{ textAlign: 'right', padding: 9 }}>Diff kg</th>
                    <th style={{ textAlign: 'center', padding: 9 }}>Status</th>
                    <th style={{ textAlign: 'center', padding: 9 }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {packaging.map((p, idx) => {
                    const pId = String(p.packaging_id || idx);
                    const isIncomplete = String(p.status).toUpperCase() === 'INCOMPLETE';
                    const diff = Number(p.difference_kg || 0);
                    return (
                      <tr key={pId} style={{ borderBottom: '1px solid #e2e8f0' }}>
                        <td style={{ padding: 9 }}>{String(p.packaging_date || '-')}</td>
                        <td style={{ padding: 9 }}><b>{String(p.product_name_snapshot || p.product_id || '-')}</b></td>
                        <td style={{ textAlign: 'right', padding: 9 }}>{String(p.bulk_kg_used ?? '-')}</td>
                        <td style={{ textAlign: 'right', padding: 9 }}>{String(p.total_packets ?? '-')}</td>
                        <td style={{ textAlign: 'right', padding: 9 }}>{String(p.expected_kg ?? '-')}</td>
                        <td style={{ textAlign: 'right', padding: 9, fontWeight: 600, color: diff !== 0 ? '#b91c1c' : '#166534' }}>
                          {diff > 0 ? `+${diff}` : diff} kg
                        </td>
                        <td style={{ textAlign: 'center', padding: 9 }}>
                          <span
                            style={{
                              padding: '3px 8px',
                              borderRadius: 6,
                              fontSize: 11,
                              fontWeight: 600,
                              background: isIncomplete ? '#fee2e2' : '#dcfce7',
                              color: isIncomplete ? '#991b1b' : '#166534',
                            }}
                          >
                            {String(p.status || (isIncomplete ? 'INCOMPLETE' : 'RECORDED'))}
                          </span>
                        </td>
                        <td style={{ textAlign: 'center', padding: 9 }}>
                          {isIncomplete ? (
                            <button
                              style={{ ...btn, background: '#d97706', padding: '4px 10px', fontSize: 11 }}
                              disabled={busy || recoveringBatchId === pId}
                              onClick={() => handleRecoverPackaging(pId)}
                              title="Post missing stock movements for this incomplete packaging batch"
                            >
                              {recoveringBatchId === pId ? 'Recovering...' : '⚠️ Recover Movements'}
                            </button>
                          ) : (
                            <span style={{ color: '#64748b', fontSize: 12 }}>✓ Reconciled</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {packaging.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ padding: 14, textAlign: 'center', color: '#64748b' }}>
                        No packaging batches recorded yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* DISPATCH TAB */}
      {tab === 'dispatch' && (
        <>
          <div style={card}>
            <h3>Dispatch Finished Packets to Sales Channels &amp; Central Warehouse</h3>
            <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 12px' }}>
              Internal factory dispatches to <b>Central Warehouse</b> transfer factory stock into Company Warehouse stock without affecting external sales. Dispatches to external channels are tracked separately from completed sales.
            </p>
            <form
              onSubmit={async e => {
                e.preventDefault();
                const ok = await runAction(
                  () =>
                    apiRequest('/api/production/dispatch', {
                      method: 'POST',
                      body: JSON.stringify({
                        ...dispatch,
                        quantity_packets: Number(dispatch.quantity_packets),
                      }),
                    }),
                  dispatch.channel === 'WAREHOUSE'
                    ? 'Dispatch recorded to Central Warehouse and credited to Company Stock.'
                    : 'Dispatch recorded. It is a stock transfer, not a sale.',
                  async () => {
                    await refreshDispatches();
                    await refreshRegister();
                  }
                );
                if (ok) {
                  setDispatch({ ...dispatch, quantity_packets: '', destination: '', reference: '', notes: '' });
                }
              }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}
            >
              {productSelect(dispatch.product_id, v => setDispatch({ ...dispatch, product_id: v }))}
              <select
                style={input}
                value={dispatch.channel}
                onChange={e => {
                  const ch = e.target.value;
                  setDispatch({
                    ...dispatch,
                    channel: ch,
                    destination: ch === 'WAREHOUSE' && !dispatch.destination ? 'Company Central Warehouse' : dispatch.destination,
                  });
                }}
              >
                <option value="WAREHOUSE">🏢 Central Warehouse (Company Stock)</option>
                <option value="ECOMMERCE">🛒 E-commerce (External Channel)</option>
                <option value="RETAIL">🏪 Retail Counter (External Channel)</option>
                <option value="SALESMAN">🚶 Salesman Field Stock</option>
                <option value="WHOLESALE">📦 Wholesale</option>
                <option value="DISTRIBUTOR">🚚 Distributor</option>
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

      {/* FINISHED GOODS REGISTER TAB */}
      {tab === 'finished_goods' && (() => {
        const filteredRegister = registerItems.filter(item => {
          const totalOnHand = item.total_internal_on_hand_packets ?? item.total_internal_on_hand ?? 0;
          const channelsDispatched = item.channels_dispatched_packets ?? 0;
          if (hideZeroStock && totalOnHand <= 0 && channelsDispatched <= 0) {
            return false;
          }
          if (registerFamilyFilter !== 'ALL') {
            const fam = String(item.category || '').toUpperCase();
            if (!fam.includes(registerFamilyFilter)) return false;
          }
          if (registerWeightFilter !== 'ALL') {
            if (String(item.pack_weight_g) !== registerWeightFilter) return false;
          }
          if (registerSearch.trim()) {
            const q = registerSearch.trim().toLowerCase();
            const skuMatch = String(item.sku || '').toLowerCase().includes(q);
            const nameMatch = String(item.product_name || '').toLowerCase().includes(q);
            if (!skuMatch && !nameMatch) return false;
          }
          return true;
        });

        const handleExportExcel = () => {
          const exportRows = filteredRegister.map(item => ({
            'SKU': item.sku,
            'Product Name': item.product_name,
            'Category': item.category,
            'Pack Weight (g)': item.pack_weight_g,
            'Selling Unit': item.selling_unit,
            'Factory Packets': item.factory_packets ?? item.factory_stock ?? 0,
            'Warehouse Packets': item.warehouse_packets ?? item.warehouse_stock ?? 0,
            'Salesmen In-Hand Packets': item.salesmen_packets ?? item.salesmen_stock ?? 0,
            'Total Internal On-Hand': item.total_internal_on_hand_packets ?? item.total_internal_on_hand ?? 0,
            'External Channels Dispatched': item.channels_dispatched_packets ?? 0,
            'Stock Status': item.stock_status,
            'Active in Master': item.active ? 'YES' : 'NO',
          }));
          exportSheetToExcel('Kawad_Swad_Finished_Goods_Register', exportRows);
        };

        return (
          <>
            {/* KPI Summary Banner */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 16 }}>
              <div style={{ ...card, background: '#f8fafc', borderColor: '#cbd5e1' }}>
                <small style={{ color: '#64748b' }}>Active Packet SKUs</small>
                <h2 style={{ margin: '4px 0 0', color: '#0f172a' }}>
                  {registerSummary?.active_skus ?? registerItems.length}
                </h2>
                <span style={{ fontSize: 11, color: '#475569' }}>
                  {registerSummary?.active_with_stock ?? 0} with stock · {registerSummary?.active_zero_stock ?? 0} zero stock
                </span>
              </div>
              <div style={{ ...card, background: '#f0fdf4', borderColor: '#bbf7d0' }}>
                <small style={{ color: '#166534' }}>Factory Finished Packets</small>
                <h2 style={{ margin: '4px 0 0', color: '#15803d' }}>
                  {registerSummary?.factory_packets ?? 0}
                </h2>
                <span style={{ fontSize: 11, color: '#166534' }}>Packaged at factory</span>
              </div>
              <div style={{ ...card, background: '#eff6ff', borderColor: '#bfdbfe' }}>
                <small style={{ color: '#1e40af' }}>Central Warehouse Packets</small>
                <h2 style={{ margin: '4px 0 0', color: '#1d4ed8' }}>
                  {registerSummary?.warehouse_packets ?? 0}
                </h2>
                <span style={{ fontSize: 11, color: '#1e40af' }}>Company stock in warehouse</span>
              </div>
              <div style={{ ...card, background: '#fdf4ff', borderColor: '#f5d0fe' }}>
                <small style={{ color: '#86198f' }}>Salesmen In-Hand Packets</small>
                <h2 style={{ margin: '4px 0 0', color: '#a21caf' }}>
                  {registerSummary?.salesmen_packets ?? 0}
                </h2>
                <span style={{ fontSize: 11, color: '#86198f' }}>Field stock balances</span>
              </div>
              <div style={{ ...card, background: '#fefce8', borderColor: '#fef08a' }}>
                <small style={{ color: '#854d0e', fontWeight: 600 }}>Total Internal On-Hand</small>
                <h2 style={{ margin: '4px 0 0', color: '#a16207' }}>
                  {registerSummary?.total_internal_on_hand_packets ?? 0}
                </h2>
                <span style={{ fontSize: 11, color: '#854d0e' }}>Factory + Warehouse + Salesmen</span>
              </div>
              <div style={{ ...card, background: '#f8fafc', borderColor: '#e2e8f0' }}>
                <small style={{ color: '#475569' }}>Channels Dispatched</small>
                <h2 style={{ margin: '4px 0 0', color: '#334155' }}>
                  {registerSummary?.channels_dispatched_packets ?? 0}
                </h2>
                <span style={{ fontSize: 11, color: '#475569' }}>E-com / Retail / Wholesalers</span>
              </div>
            </div>

            {/* Filter and Action Bar */}
            <div style={{ ...card, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
                <div>
                  <h3 style={{ margin: 0, color: '#14532d' }}>Consolidated Finished Goods Register</h3>
                  <p style={{ margin: '3px 0 0', fontSize: 12, color: '#64748b' }}>
                    Authoritative ready-packet inventory across Factory, Central Warehouse, Field Salesmen, and Channels. All active SKUs are tracked, including zero-stock items.
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    style={{ ...btn, background: '#0284c7', fontSize: 12, padding: '7px 12px' }}
                    onClick={refreshRegister}
                    disabled={busy}
                  >
                    🔄 Refresh Register
                  </button>
                  <button
                    type="button"
                    style={{ ...btn, background: '#047857', fontSize: 12, padding: '7px 12px' }}
                    onClick={handleExportExcel}
                  >
                    📥 Export Register (.xlsx)
                  </button>
                </div>
              </div>

              {/* Filter Controls */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, alignItems: 'center' }}>
                <input
                  style={input}
                  placeholder="🔍 Search SKU or Product Name..."
                  value={registerSearch}
                  onChange={e => setRegisterSearch(e.target.value)}
                />
                <select
                  style={input}
                  value={registerFamilyFilter}
                  onChange={e => setRegisterFamilyFilter(e.target.value)}
                >
                  <option value="ALL">All Categories / Families</option>
                  <option value="MOONG">Moong Papad</option>
                  <option value="CHANA">Chana Papad</option>
                  <option value="URAD">Urad Papad</option>
                  <option value="MASALA">Masala</option>
                  <option value="KATRAN">Katran</option>
                </select>
                <select
                  style={input}
                  value={registerWeightFilter}
                  onChange={e => setRegisterWeightFilter(e.target.value)}
                >
                  <option value="ALL">All Pack Sizes</option>
                  <option value="200">200 g Packets</option>
                  <option value="500">500 g Packets</option>
                  <option value="1000">1,000 g (1 kg) Packets</option>
                </select>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer', color: '#334155' }}>
                  <input
                    type="checkbox"
                    checked={hideZeroStock}
                    onChange={e => setHideZeroStock(e.target.checked)}
                  />
                  <span>Hide Zero-Stock SKUs</span>
                </label>
              </div>
            </div>

            {/* Authoritative Inventory Table */}
            <div style={card}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0', color: '#334155' }}>
                      <th style={{ textAlign: 'left', padding: '10px 8px' }}>SKU</th>
                      <th style={{ textAlign: 'left', padding: '10px 8px' }}>Product</th>
                      <th style={{ textAlign: 'left', padding: '10px 8px' }}>Category</th>
                      <th style={{ textAlign: 'center', padding: '10px 8px' }}>Pack Size</th>
                      <th style={{ textAlign: 'right', padding: '10px 8px', color: '#166534' }}>Factory</th>
                      <th style={{ textAlign: 'right', padding: '10px 8px', color: '#1e40af' }}>Warehouse</th>
                      <th style={{ textAlign: 'right', padding: '10px 8px', color: '#86198f' }}>Salesmen</th>
                      <th style={{ textAlign: 'right', padding: '10px 8px', background: '#fefce8', color: '#854d0e', fontWeight: 700 }}>
                        Total On-Hand
                      </th>
                      <th style={{ textAlign: 'right', padding: '10px 8px', color: '#475569' }}>Channels</th>
                      <th style={{ textAlign: 'center', padding: '10px 8px' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRegister.map(item => {
                      const totalOnHand = item.total_internal_on_hand_packets ?? item.total_internal_on_hand ?? 0;
                      const factoryPackets = item.factory_packets ?? item.factory_stock ?? 0;
                      const warehousePackets = item.warehouse_packets ?? item.warehouse_stock ?? 0;
                      const salesmenPackets = item.salesmen_packets ?? item.salesmen_stock ?? 0;
                      const channelsDispatched = item.channels_dispatched_packets ?? 0;
                      const isZero = totalOnHand <= 0;
                      const isLow = totalOnHand > 0 && totalOnHand < 20;
                      return (
                        <tr
                          key={item.product_id}
                          style={{
                            borderBottom: '1px solid #e2e8f0',
                            background: isZero ? '#fafafa' : '#fff',
                          }}
                        >
                          <td style={{ padding: '9px 8px' }}>
                            <span style={{ fontFamily: 'monospace', fontWeight: 600, color: '#0f172a' }}>
                              {item.sku}
                            </span>
                          </td>
                          <td style={{ padding: '9px 8px' }}>
                            <b>{item.product_name}</b>
                          </td>
                          <td style={{ padding: '9px 8px', color: '#64748b' }}>
                            {item.category || 'Papad'}
                          </td>
                          <td style={{ textAlign: 'center', padding: '9px 8px' }}>
                            <span style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, fontSize: 11 }}>
                              {item.pack_weight_g} g
                            </span>
                          </td>
                          <td style={{ textAlign: 'right', padding: '9px 8px', fontWeight: factoryPackets > 0 ? 600 : 400, color: factoryPackets > 0 ? '#15803d' : '#94a3b8' }}>
                            {factoryPackets}
                          </td>
                          <td style={{ textAlign: 'right', padding: '9px 8px', fontWeight: warehousePackets > 0 ? 600 : 400, color: warehousePackets > 0 ? '#1d4ed8' : '#94a3b8' }}>
                            {warehousePackets}
                          </td>
                          <td style={{ textAlign: 'right', padding: '9px 8px', fontWeight: salesmenPackets > 0 ? 600 : 400, color: salesmenPackets > 0 ? '#a21caf' : '#94a3b8' }}>
                            {salesmenPackets}
                          </td>
                          <td
                            style={{
                              textAlign: 'right',
                              padding: '9px 8px',
                              background: isZero ? '#fef2f2' : '#fefce8',
                              color: isZero ? '#b91c1c' : '#854d0e',
                              fontWeight: 700,
                              fontSize: 14,
                            }}
                          >
                            {totalOnHand}
                          </td>
                          <td style={{ textAlign: 'right', padding: '9px 8px', color: '#475569' }}>
                            {channelsDispatched}
                          </td>
                          <td style={{ textAlign: 'center', padding: '9px 8px' }}>
                            <span
                              style={{
                                padding: '3px 8px',
                                borderRadius: 12,
                                fontSize: 11,
                                fontWeight: 600,
                                background: isZero ? '#fee2e2' : isLow ? '#fef3c7' : '#dcfce7',
                                color: isZero ? '#991b1b' : isLow ? '#b45309' : '#166534',
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
                        <td colSpan={10} style={{ padding: 18, textAlign: 'center', color: '#64748b' }}>
                          No finished goods match the selected filters.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        );
      })()}
    </section>
  );
};

