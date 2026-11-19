import React, { useState, useEffect, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { resolveCanonical12Role } from '../utils/permissions';
import { StockTxnType, FinishedGoodsRegisterItem, FinishedGoodsRegisterSummary, VanLoadingPass, VanLoadingItem } from '../types';
import {
  apiRequest,
  getVanLoadingPasses,
  createVanLoadingPass,
  acceptVanLoadingPass,
  reportVanLoadingDiscrepancy,
  cancelVanLoadingPass,
  createSubmissionNonce,
  isUnknownOutcomeError,
} from '../services/api';
import {
  Truck,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Plus,
  X,
  FileText,
  Package,
  ShieldCheck,
  AlertCircle,
  ArrowRight,
  Info,
} from 'lucide-react';
import {
  FormLayout,
  FormSection,
  FormField,
  MoneyInput,
  QuantityInput,
  TextInput,
  SelectInput,
  CalculationPreview,
  FormActions,
  SaveButton,
  CancelButton,
} from '../components/common/FormComponents';

const UNKNOWN_OUTCOME_MSG =
  'Status not confirmed; do not submit a new transaction. Your inputs and retry key are preserved—retry safely.';

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

  const canonicalRole = resolveCanonical12Role(currentUser?.role);
  const isAuditor = canonicalRole === 'AUDITOR';
  const isFieldSalesman = canonicalRole === 'FIELD_SALESMAN';
  const isManager = !isAuditor && (canonicalRole === 'OWNER_ADMIN' || canonicalRole === 'PA');
  const activeProducts = products.filter((p) => p.active);
  const activeSalesmen = users.filter((u) => resolveCanonical12Role(u.role) === 'FIELD_SALESMAN' && u.active);

  const [stockTab, setStockTab] = useState<'register' | 'movements' | 'physical' | 'van_loading'>('register');
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

  // Bulk Batch Tracking State
  const [showBatchTracking, setShowBatchTracking] = useState(false);
  const [bulkBatches, setBulkBatches] = useState<{
    batch_id: string;
    production_date: string;
    product_name: string;
    bulk_product_key: string;
    produced_kg: number;
    consumed_kg: number;
    available_kg: number;
    unit_cost_per_kg: number | null;
    cost_status: string;
    cost_source?: string;
    cost_date?: string;
    cost_notes?: string;
    valuation?: number;
  }[]>([]);
  const [loadingBatches, setLoadingBatches] = useState(false);
  const [batchFilterText, setBatchFilterText] = useState('');
  const [batchNotice, setBatchNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  // Legacy batch cost resolution
  const [resolvingBatchId, setResolvingBatchId] = useState<string | null>(null);
  const [resolveRate, setResolveRate] = useState<number>(0);
  const [resolveStatus, setResolveStatus] = useState<'ACTUAL' | 'ESTIMATED'>('ACTUAL');
  const [resolveNotes, setResolveNotes] = useState('');
  const [resolvingLoading, setResolvingLoading] = useState(false);

  // --------------------------------------------------------------------------
  // Phase 2A.1: Morning Van Loading Pass State
  // --------------------------------------------------------------------------
  const [loadingPasses, setLoadingPasses] = useState<VanLoadingPass[]>([]);
  const [loadingPassesLoading, setLoadingPassesLoading] = useState(false);
  const [loadingPassFilterStatus, setLoadingPassFilterStatus] = useState<string>('ALL');
  const [loadingPassNotice, setLoadingPassNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  // New Loading Pass Form State (Warehouse Keeper)
  const [passDate, setPassDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [passVan, setPassVan] = useState<string>('Van 1');
  const [passSalesmanId, setPassSalesmanId] = useState<string>(activeSalesmen[0]?.user_id || '');
  const [passQuantities, setPassQuantities] = useState<Record<string, number>>({});
  const [passNotes, setPassNotes] = useState<string>('');
  const [isCreatingPass, setIsCreatingPass] = useState(false);

  // Detail / Verification Modal
  const [viewingPass, setViewingPass] = useState<VanLoadingPass | null>(null);

  // Discrepancy Reporting Modal
  const [discrepancyModalPass, setDiscrepancyModalPass] = useState<VanLoadingPass | null>(null);
  const [discrepancyNotes, setDiscrepancyNotes] = useState<string>('');
  const [isSubmittingDiscrepancy, setIsSubmittingDiscrepancy] = useState(false);

  // Accept Loading Action State
  const [acceptingPassId, setAcceptingPassId] = useState<string | null>(null);

  // Submission guards & stable idempotency nonces (preserved across retries / HTTP 504)
  const [createPassNonce, setCreatePassNonce] = useState('');
  const [acceptPassNonces, setAcceptPassNonces] = useState<Record<string, string>>({});
  const [discrepancyNonce, setDiscrepancyNonce] = useState('');
  const [discrepancyError, setDiscrepancyError] = useState<string | null>(null);
  const [cancelPassNonces, setCancelPassNonces] = useState<Record<string, string>>({});
  const [cancellingPassId, setCancellingPassId] = useState<string | null>(null);
  const [cancelPassTargetId, setCancelPassTargetId] = useState<string | null>(null);
  const [resolveCostNonces, setResolveCostNonces] = useState<Record<string, string>>({});
  const [reconNonce, setReconNonce] = useState('');
  const [reconFallbackRef, setReconFallbackRef] = useState('');
  const [movementNonce, setMovementNonce] = useState('');
  const [movementSubmitting, setMovementSubmitting] = useState(false);
  const [discSubmitNonce, setDiscSubmitNonce] = useState('');
  const [discSubmitting, setDiscSubmitting] = useState(false);
  const [reviewNonces, setReviewNonces] = useState<Record<string, string>>({});
  const [reviewingDiscId, setReviewingDiscId] = useState<string | null>(null);

  const loadLoadingPasses = async () => {
    try {
      setLoadingPassesLoading(true);
      const res = await getVanLoadingPasses();
      setLoadingPasses(res || []);
    } catch (err: any) {
      console.error('Failed to load van loading passes:', err);
    } finally {
      setLoadingPassesLoading(false);
    }
  };

  useEffect(() => {
    loadLoadingPasses();
  }, []);

  const warehouseStockMap = useMemo(() => {
    const map: Record<string, number> = {};
    activeProducts.forEach((p) => {
      const match = companyStockSummary.find((c) => c.product_id === p.product_id);
      map[p.product_id] = match?.company_quantity ?? 0;
    });
    return map;
  }, [activeProducts, companyStockSummary]);

  const passSummary = useMemo(() => {
    let totalSkus = 0;
    let totalPackets = 0;
    let totalWeightKg = 0;
    let hasExceededStock = false;

    activeProducts.forEach((p) => {
      const qty = passQuantities[p.product_id] || 0;
      if (qty > 0) {
        totalSkus += 1;
        totalPackets += qty;
        const packWeight = p.pack_weight_g || 500;
        totalWeightKg += (qty * packWeight) / 1000.0;
        const available = warehouseStockMap[p.product_id] || 0;
        if (qty > available) {
          hasExceededStock = true;
        }
      }
    });

    return { totalSkus, totalPackets, totalWeightKg, hasExceededStock };
  }, [activeProducts, passQuantities, warehouseStockMap]);

  const pendingSalesmanPasses = useMemo(() => {
    return loadingPasses.filter(
      (p) => p.status === 'PENDING_ACCEPTANCE' && (!isFieldSalesman || p.salesman_user_id === currentUser?.user_id)
    );
  }, [loadingPasses, currentUser, isFieldSalesman]);

  const handleCreateLoadingPass = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreatingPass) return;
    setLoadingPassNotice(null);

    if (passSummary.totalPackets <= 0) {
      setLoadingPassNotice({ msg: 'Please enter packet quantities for at least one product.', error: true });
      return;
    }
    if (passSummary.hasExceededStock) {
      setLoadingPassNotice({ msg: 'Cannot load more packets than available warehouse stock.', error: true });
      return;
    }
    if (!passSalesmanId) {
      setLoadingPassNotice({ msg: 'Please select an assigned salesman.', error: true });
      return;
    }

    const activeNonce = createPassNonce || createSubmissionNonce('STK-VLP');
    if (!createPassNonce) setCreatePassNonce(activeNonce);

    try {
      setIsCreatingPass(true);
      const itemsToLoad = activeProducts
        .filter((p) => (passQuantities[p.product_id] || 0) > 0)
        .map((p) => ({
          product_id: p.product_id,
          quantity: passQuantities[p.product_id],
        }));

      const created = await createVanLoadingPass({
        loading_date: passDate,
        van_number: passVan,
        salesman_user_id: passSalesmanId,
        items: itemsToLoad,
        notes: passNotes,
      }, activeNonce);

      setCreatePassNonce('');
      setLoadingPassNotice({
        msg: `Loading Pass ${created.pass_number} created successfully! Waiting for salesman verification and acceptance.`,
      });
      setPassQuantities({});
      setPassNotes('');
      await loadLoadingPasses();
      await refreshData();
    } catch (err: any) {
      setLoadingPassNotice({
        msg: isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err?.message || 'Failed to create van loading pass',
        error: true,
      });
    } finally {
      setIsCreatingPass(false);
    }
  };

  const handleAcceptPass = async (passIdOrNumber: string) => {
    if (acceptingPassId) return;
    const activeNonce = acceptPassNonces[passIdOrNumber] || createSubmissionNonce('STK-VLA');
    if (!acceptPassNonces[passIdOrNumber]) {
      setAcceptPassNonces((prev) => ({ ...prev, [passIdOrNumber]: activeNonce }));
    }
    try {
      setAcceptingPassId(passIdOrNumber);
      setLoadingPassNotice(null);
      const accepted = await acceptVanLoadingPass(passIdOrNumber, undefined, activeNonce);
      setAcceptPassNonces((prev) => {
        const next = { ...prev };
        delete next[passIdOrNumber];
        return next;
      });
      setLoadingPassNotice({
        msg: `Stock loading pass ${accepted.pass_number} verified and accepted! Van inventory has been credited and warehouse inventory deducted.`,
      });
      await loadLoadingPasses();
      await refreshData();
      if (viewingPass?.pass_id === accepted.pass_id) {
        setViewingPass(accepted);
      }
    } catch (err: any) {
      setLoadingPassNotice({
        msg: isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err?.message || 'Failed to accept loading pass',
        error: true,
      });
    } finally {
      setAcceptingPassId(null);
    }
  };

  const handleReportDiscrepancy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!discrepancyModalPass || isSubmittingDiscrepancy) return;
    setDiscrepancyError(null);
    if (!discrepancyNotes.trim()) {
      setDiscrepancyError('Please describe the physical count discrepancy.');
      return;
    }

    const activeNonce = discrepancyNonce || createSubmissionNonce('STK-VLD');
    if (!discrepancyNonce) setDiscrepancyNonce(activeNonce);

    try {
      setIsSubmittingDiscrepancy(true);
      const updated = await reportVanLoadingDiscrepancy(
        discrepancyModalPass.pass_id,
        discrepancyNotes,
        activeNonce
      );
      setDiscrepancyNonce('');
      setDiscrepancyError(null);
      setLoadingPassNotice({
        msg: `Discrepancy on ${updated.pass_number} recorded. The warehouse manager has been notified for resolution.`,
      });
      setDiscrepancyModalPass(null);
      setDiscrepancyNotes('');
      await loadLoadingPasses();
      await refreshData();
    } catch (err: any) {
      setDiscrepancyError(
        isUnknownOutcomeError(err)
          ? UNKNOWN_OUTCOME_MSG
          : `Failed to report discrepancy: ${err?.message || err}`
      );
    } finally {
      setIsSubmittingDiscrepancy(false);
    }
  };

  const handleCancelPass = async (passIdOrNumber: string) => {
    if (cancellingPassId) return;
    const activeNonce = cancelPassNonces[passIdOrNumber] || createSubmissionNonce('STK-VLC');
    if (!cancelPassNonces[passIdOrNumber]) {
      setCancelPassNonces((prev) => ({ ...prev, [passIdOrNumber]: activeNonce }));
    }
    try {
      setCancellingPassId(passIdOrNumber);
      setLoadingPassNotice(null);
      const cancelled = await cancelVanLoadingPass(
        passIdOrNumber,
        'Cancelled from management dashboard',
        activeNonce
      );
      setCancelPassNonces((prev) => {
        const next = { ...prev };
        delete next[passIdOrNumber];
        return next;
      });
      setCancelPassTargetId(null);
      setLoadingPassNotice({ msg: `Loading pass ${cancelled.pass_number} cancelled.` });
      await loadLoadingPasses();
      await refreshData();
      if (viewingPass?.pass_id === cancelled.pass_id) {
        setViewingPass(cancelled);
      }
    } catch (err: any) {
      setLoadingPassNotice({
        msg: isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err?.message || 'Failed to cancel loading pass',
        error: true,
      });
    } finally {
      setCancellingPassId(null);
    }
  };


  const loadBulkBatches = async () => {
    try {
      setLoadingBatches(true);
      setBatchNotice(null);
      const res = await apiRequest<any[]>('/api/stock/bulk-batches');
      if (Array.isArray(res)) {
        setBulkBatches(res);
      }
    } catch (err: any) {
      setBatchNotice({ msg: err?.message || 'Failed to load bulk batch tracking data.', error: true });
    } finally {
      setLoadingBatches(false);
    }
  };

  const handleResolveLegacyCost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resolvingBatchId || resolvingLoading) return;
    const batchKey = resolvingBatchId;
    const activeNonce = resolveCostNonces[batchKey] || createSubmissionNonce('STK-COST');
    if (!resolveCostNonces[batchKey]) {
      setResolveCostNonces((prev) => ({ ...prev, [batchKey]: activeNonce }));
    }
    try {
      setResolvingLoading(true);
      await apiRequest(`/api/production/batches/${batchKey}/resolve-legacy-cost`, {
        method: 'POST',
        idempotencyKey: activeNonce,
        body: JSON.stringify({
          cost_per_kg: Number(resolveRate),
          cost_status: resolveStatus,
          source: 'OWNER_STOCK_AUDIT',
          notes: resolveNotes || 'Resolved from StockView Batch Tracking modal',
        }),
      });
      setResolveCostNonces((prev) => {
        const next = { ...prev };
        delete next[batchKey];
        return next;
      });
      setBatchNotice({ msg: `Successfully updated cost for batch ${batchKey} to ₹${resolveRate}/kg (${resolveStatus}).` });
      setResolvingBatchId(null);
      setResolveRate(0);
      setResolveNotes('');
      await loadBulkBatches();
    } catch (err: any) {
      setBatchNotice({
        msg: isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err?.message || 'Failed to resolve batch cost.',
        error: true,
      });
    } finally {
      setResolvingLoading(false);
    }
  };

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
      return reg ? (reg.factory_packets ?? reg.factory_stock ?? 0) : 0;
    }
    if (reconLocation === 'WAREHOUSE') {
      const reg = registerItems.find(r => r.product_id === reconProductId);
      if (reg) return reg.warehouse_packets ?? reg.warehouse_stock ?? 0;
      const comp = companyStockSummary.find(c => c.product_id === reconProductId);
      return comp ? comp.company_quantity : 0;
    }
    const sm = salesmanStockSummary.find(s => s.salesman_user_id === reconLocation && s.product_id === reconProductId);
    return sm ? sm.quantity : 0;
  }, [reconLocation, reconProductId, registerItems, companyStockSummary, salesmanStockSummary]);

  const liveAdjustmentDiff = Number(reconPhysicalCount) - (currentExpectedCount ?? 0);

  const handleReconcileOpening = async (e: React.FormEvent) => {
    e.preventDefault();
    if (reconLoading) return;
    setReconNotice(null);
    if (!reconProductId) {
      setReconNotice({ msg: 'Please select a product SKU.', error: true });
      return;
    }
    if (Number(reconPhysicalCount) < 0) {
      setReconNotice({ msg: 'Physical count cannot be negative.', error: true });
      return;
    }
    const activeNonce = reconNonce || createSubmissionNonce('STK-RECON');
    if (!reconNonce) setReconNonce(activeNonce);
    const activeRef = reconReference.trim() || reconFallbackRef || `RECON-${Date.now()}`;
    if (!reconReference.trim() && !reconFallbackRef) {
      setReconFallbackRef(activeRef);
    }
    try {
      setReconLoading(true);
      const res = await apiRequest<{ message: string; adjustment: any }>('/api/stock/reconcile-opening', {
        method: 'POST',
        idempotencyKey: activeNonce,
        body: JSON.stringify({
          product_id: reconProductId,
          location: reconLocation,
          physical_count: Number(reconPhysicalCount),
          reason: reconReason.trim() || 'Physical inventory audit reconciliation',
          reference: activeRef,
        }),
      });
      setReconNonce('');
      setReconFallbackRef('');
      setReconNotice({ msg: res.message || 'Physical stock reconciled and ledger balance updated successfully.' });
      setReconReason('');
      setReconReference('');
      await Promise.allSettled([loadRegister(), refreshData()]);
    } catch (err: any) {
      setReconNotice({
        msg: isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err?.message || 'Reconciliation failed',
        error: true,
      });
    } finally {
      setReconLoading(false);
    }
  };

  const needsSalesman = ['ISSUED', 'RETURNED', 'SOLD', 'SALESMAN_ADJUSTMENT'].includes(txnType);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (movementSubmitting) return;
    setNotice(null);

    if (quantity <= 0) {
      setNotice({ msg: 'Quantity must be greater than 0.', error: true });
      return;
    }

    const activeNonce = movementNonce || createSubmissionNonce('STK-MOV');
    if (!movementNonce) setMovementNonce(activeNonce);

    try {
      setMovementSubmitting(true);
      await recordStockMovement({
        txn_type: txnType,
        product_id: productId,
        salesman_user_id: needsSalesman ? salesmanId : '',
        quantity: Number(quantity),
        notes: notes.trim(),
      }, activeNonce);

      setMovementNonce('');
      setNotice({ msg: `Stock movement "${txnType}" recorded successfully.` });
      setNotes('');
      loadRegister();
    } catch (err: unknown) {
      const errorMsg = isUnknownOutcomeError(err)
        ? UNKNOWN_OUTCOME_MSG
        : err instanceof Error
        ? err.message
        : 'Failed to record stock movement';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setMovementSubmitting(false);
    }
  };

  const handleDiscrepancySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (discSubmitting) return;
    setNotice(null);
    if (!discProductId) {
      setNotice({ msg: 'Select a product for audit discrepancy check.', error: true });
      return;
    }
    const activeNonce = discSubmitNonce || createSubmissionNonce('STK-DISC');
    if (!discSubmitNonce) setDiscSubmitNonce(activeNonce);
    try {
      setDiscSubmitting(true);
      await submitStockDiscrepancy({
        location: discLocation,
        product_id: discProductId,
        expected_stock: Number(discExpected),
        physical_count: Number(discPhysical),
        reason: discReason.trim() || 'Physical stock audit reconciliation',
      }, activeNonce);
      setDiscSubmitNonce('');
      setNotice({ msg: 'Stock physical count submitted for review. Unexplained differences are preserved for verification and not treated as automatic losses.' });
      setDiscReason('');
    } catch (err: unknown) {
      const errStr = isUnknownOutcomeError(err)
        ? UNKNOWN_OUTCOME_MSG
        : `Failed to submit discrepancy: ${err instanceof Error ? err.message : String(err)}`;
      setNotice({ msg: errStr, error: true });
    } finally {
      setDiscSubmitting(false);
    }
  };

  const handleReview = async (discrepancyId: string, action: 'APPROVE' | 'REJECT') => {
    if (reviewingDiscId) return;
    const key = `${discrepancyId}:${action}`;
    const activeNonce = reviewNonces[key] || createSubmissionNonce('STK-REV');
    if (!reviewNonces[key]) {
      setReviewNonces((prev) => ({ ...prev, [key]: activeNonce }));
    }
    try {
      setReviewingDiscId(discrepancyId);
      await reviewStockDiscrepancy(
        discrepancyId,
        action,
        action === 'APPROVE' ? 'Approved in physical audit' : 'Rejected',
        activeNonce
      );
      setReviewNonces((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setNotice({ msg: `Discrepancy ${action === 'APPROVE' ? 'approved and stock adjusted' : 'rejected'}.` });
      loadRegister();
    } catch (err: unknown) {
      const errStr = isUnknownOutcomeError(err)
        ? UNKNOWN_OUTCOME_MSG
        : `Review failed: ${err instanceof Error ? err.message : String(err)}`;
      setNotice({ msg: errStr, error: true });
    } finally {
      setReviewingDiscId(null);
    }
  };

  // Filter salesman stock & ledger for salesman role
  const visibleSalesmanStock = isFieldSalesman
    ? salesmanStockSummary.filter((s) => s.salesman_user_id === currentUser?.user_id)
    : salesmanStockSummary;

  const visibleTransactions = isFieldSalesman
    ? stockTransactions.filter((t) => t.salesman_user_id === currentUser?.user_id)
    : stockTransactions;

  const userNameMap = useMemo(() => {
    const m: Record<string, string> = {};
    users.forEach((u) => {
      m[u.user_id] = u.full_name || u.user_id;
    });
    return m;
  }, [users]);

  const formatLocationLabel = (loc: string) => {
    const norm = String(loc || '').trim().toUpperCase();
    if (!norm || ['COMPANY_WAREHOUSE', 'WAREHOUSE', 'COMPANY', 'FACTORY'].includes(norm)) {
      return norm === 'FACTORY' ? '🏭 Factory Storage' : '🏢 Central Warehouse';
    }
    const uName = userNameMap[String(loc).trim()];
    return uName ? `🚶 ${uName} (${loc})` : String(loc);
  };

  const classifyDiscrepancy = (loc: string, diff: number) => {
    const norm = String(loc || '').trim().toUpperCase();
    const isWh = !norm || ['COMPANY_WAREHOUSE', 'WAREHOUSE', 'COMPANY', 'FACTORY'].includes(norm);
    if (diff === 0) {
      return {
        label: 'No Difference',
        impact: 'No stock change needed',
        bg: '#f1f5f9',
        color: '#475569',
      };
    }
    if (isWh) {
      return diff < 0
        ? {
            label: 'Warehouse Shortage',
            impact: 'Reduces warehouse stock only (Salesman unchanged)',
            bg: '#fee2e2',
            color: '#b91c1c',
          }
        : {
            label: 'Warehouse Surplus',
            impact: 'Increases warehouse stock only (Salesman unchanged)',
            bg: '#dcfce7',
            color: '#15803d',
          };
    }
    return diff < 0
      ? {
          label: 'Salesman Shortage',
          impact: 'Reduces salesman stock only (Warehouse does NOT increase)',
          bg: '#ffedd5',
          color: '#c2410c',
        }
      : {
          label: 'Salesman Surplus',
          impact: 'Increases salesman stock only (Warehouse unchanged)',
          bg: '#dbeafe',
          color: '#1d4ed8',
        };
  };

  const formatMovementBadge = (tType: string) => {
    const kind = String(tType || '').toUpperCase();
    switch (kind) {
      case 'COMPANY_RECEIPT':
        return { label: 'Warehouse Stock Receipt', bg: '#dcfce7', color: '#15803d' };
      case 'ISSUED':
      case 'ISSUE_TO_SALESMAN':
        return { label: 'Issued to Van / Salesman', bg: '#e0f2fe', color: '#0369a1' };
      case 'RETURNED':
      case 'RETURN_FROM_SALESMAN':
        return { label: 'Actual Return (Van → Warehouse)', bg: '#ede9fe', color: '#6d28d9' };
      case 'SALESMAN_NEGATIVE_ADJUSTMENT':
        return { label: 'Salesman Shortage (Van −)', bg: '#ffedd5', color: '#c2410c' };
      case 'SALESMAN_POSITIVE_ADJUSTMENT':
      case 'SALESMAN_ADJUSTMENT':
        return { label: 'Salesman Surplus (Van +)', bg: '#dbeafe', color: '#1d4ed8' };
      case 'NEGATIVE_ADJUSTMENT':
        return { label: 'Warehouse Shortage (WH −)', bg: '#fee2e2', color: '#b91c1c' };
      case 'POSITIVE_ADJUSTMENT':
      case 'COMPANY_ADJUSTMENT':
        return { label: 'Warehouse Surplus (WH +)', bg: '#dcfce7', color: '#15803d' };
      case 'SOLD':
      case 'SOLD_DELIVERY':
      case 'SALE_DELIVERY':
        return { label: 'Delivered / Sold', bg: '#f1f5f9', color: '#334155' };
      default:
        return { label: kind || 'MOVEMENT', bg: '#fef3c7', color: '#b45309' };
    }
  };

  const liveDiscDiff = Number(discPhysical) - Number(discExpected);
  const liveDiscClass = classifyDiscrepancy(discLocation, liveDiscDiff);

  const filteredRegister = registerItems.filter((item) => {
    const totalInternalOnHand = item.total_internal_on_hand_packets ?? item.total_internal_on_hand ?? 0;
    const channelsDispatched = item.channels_dispatched_packets ?? 0;
    if (hideZeroStock && totalInternalOnHand <= 0 && channelsDispatched <= 0) {
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

  const handleExportRegisterExcel = async () => {
    const exportRows = filteredRegister.map((item) => ({
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
      'Active': item.active ? 'YES' : 'NO',
    }));
    const { exportSheetToExcel } = await import('../utils/exportToExcel');
    await exportSheetToExcel('Finished_Goods_Stock_Register', exportRows);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="pb-4 border-b border-slate-200">
        <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight m-0">
          Stock
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 mt-1 mb-0 leading-relaxed">
          Ready-to-sell packet stock across Factory, Warehouse, Field Salesmen, and Channels
        </p>
      </div>

      <div className="flex items-center gap-1.5 p-1.5 bg-slate-100 rounded-xl overflow-x-auto border border-slate-200/60">
        <button
          type="button"
          onClick={() => setStockTab('register')}
          className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer whitespace-nowrap ${
            stockTab === 'register'
              ? 'bg-white text-slate-900 shadow-2xs font-bold'
              : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          Ready Stock Register
        </button>
        <button
          type="button"
          onClick={() => setStockTab('movements')}
          className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer whitespace-nowrap ${
            stockTab === 'movements'
              ? 'bg-white text-slate-900 shadow-2xs font-bold'
              : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          Stock History
        </button>
        {isManager && (
          <button
            type="button"
            onClick={() => setStockTab('physical')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer whitespace-nowrap ${
              stockTab === 'physical'
                ? 'bg-white text-slate-900 shadow-2xs font-bold'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            Physical Count &amp; Difference
          </button>
        )}
        <button
          type="button"
          onClick={() => setStockTab('van_loading')}
          className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
            stockTab === 'van_loading'
              ? 'bg-emerald-800 text-white shadow-2xs font-bold'
              : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          <Truck className="w-3.5 h-3.5" />
          <span>Van Loading / गाड़ी में माल</span>
          {pendingSalesmanPasses.length > 0 && (
            <span className="bg-amber-500 text-white text-[10px] font-extrabold px-1.5 py-0.2 rounded-full animate-pulse">
              {pendingSalesmanPasses.length}
            </span>
          )}
        </button>
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
                  onClick={() => {
                    setShowBatchTracking(true);
                    loadBulkBatches();
                  }}
                  style={{ fontSize: '0.85rem', background: '#0284c7' }}
                >
                  🔍 Bulk Batch Tracking
                </button>
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
                    const totalOnHand = item.total_internal_on_hand_packets ?? item.total_internal_on_hand ?? 0;
                    const factoryPackets = item.factory_packets ?? item.factory_stock ?? 0;
                    const warehousePackets = item.warehouse_packets ?? item.warehouse_stock ?? 0;
                    const salesmenPackets = item.salesmen_packets ?? item.salesmen_stock ?? 0;
                    const channelsDispatched = item.channels_dispatched_packets ?? 0;
                    const isZero = totalOnHand <= 0;
                    const isLow = totalOnHand > 0 && totalOnHand < 20;
                    return (
                      <tr key={item.product_id} style={{ background: isZero ? '#fafafa' : undefined }}>
                        <td><strong>{item.sku}</strong></td>
                        <td>{item.product_name}</td>
                        <td className="muted">{item.category || 'Papad'}</td>
                        <td style={{ textAlign: 'center' }}>{item.pack_weight_g} g</td>
                        <td style={{ textAlign: 'right', fontWeight: factoryPackets > 0 ? 700 : 400, color: factoryPackets > 0 ? '#15803d' : '#94a3b8' }}>
                          {factoryPackets}
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: warehousePackets > 0 ? 700 : 400, color: warehousePackets > 0 ? '#1d4ed8' : '#94a3b8' }}>
                          {warehousePackets}
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: salesmenPackets > 0 ? 700 : 400, color: salesmenPackets > 0 ? '#a21caf' : '#94a3b8' }}>
                          {salesmenPackets}
                        </td>
                        <td style={{ textAlign: 'right', background: isZero ? '#fef2f2' : '#fefce8', color: isZero ? '#b91c1c' : '#854d0e', fontWeight: 700 }}>
                          {totalOnHand}
                        </td>
                        <td style={{ textAlign: 'right', color: '#475569' }}>
                          {channelsDispatched}
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

            <form onSubmit={handleReconcileOpening} className="space-y-4 mb-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <FormField label="Location / Node" required>
                  <SelectInput
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
                  </SelectInput>
                </FormField>

                <FormField label="Product SKU" required>
                  <SelectInput
                    required
                    value={reconProductId}
                    onChange={(e) => setReconProductId(e.target.value)}
                  >
                    {activeProducts.map((p) => (
                      <option key={p.product_id} value={p.product_id}>
                        {p.sku} · {p.product_name} ({p.pack_weight_g}g)
                      </option>
                    ))}
                  </SelectInput>
                </FormField>

                <FormField label="Actual Physical Count" required helpText="Counted packets in warehouse/van">
                  <QuantityInput
                    unit="pkts"
                    min={0}
                    step={1}
                    value={reconPhysicalCount}
                    onChange={(val) => setReconPhysicalCount(val)}
                  />
                </FormField>

                <FormField label="Audit Reference Tag" helpText="e.g. AUDIT-2026-COUNT">
                  <TextInput
                    placeholder="e.g. AUDIT-2026-COUNT"
                    value={reconReference}
                    onChange={(e) => setReconReference(e.target.value)}
                  />
                </FormField>

                <div className="sm:col-span-2 lg:col-span-4">
                  <FormField label="Reason / Investigation Note" helpText="Explanation of physical count or opening baseline setup">
                    <TextInput
                      placeholder="Explanation of variance or opening balance setup..."
                      value={reconReason}
                      onChange={(e) => setReconReason(e.target.value)}
                    />
                  </FormField>
                </div>
              </div>

              <CalculationPreview
                title="Reconciliation Variance Analysis"
                items={[
                  {
                    label: 'Current Ledger Expected',
                    value: `${currentExpectedCount} pkts`,
                    subtitle: 'Recorded in ledger',
                  },
                  {
                    label: 'Actual Physical Count',
                    value: `${reconPhysicalCount} pkts`,
                    subtitle: 'Audited physical stock',
                    variant: 'slate',
                  },
                  {
                    label: 'Balancing Adjustment',
                    value: liveAdjustmentDiff >= 0 ? `+${liveAdjustmentDiff} pkts` : `${liveAdjustmentDiff} pkts`,
                    subtitle: liveAdjustmentDiff === 0 ? 'Exact match' : liveAdjustmentDiff > 0 ? 'Surplus adjustment' : 'Shortage write-off',
                    isHighlight: true,
                    variant: liveAdjustmentDiff === 0 ? 'emerald' : liveAdjustmentDiff > 0 ? 'amber' : 'rose',
                  },
                ]}
              />

              <div className="flex justify-end pt-2">
                <SaveButton
                  label="Submit Audited Reconciliation"
                  isLoading={reconLoading}
                />
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
                <form onSubmit={handleSubmit} className="space-y-4 mb-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <FormField label="Movement Type" required>
                      <SelectInput
                        value={txnType}
                        onChange={(e) => setTxnType(e.target.value as StockTxnType)}
                      >
                        <option value="COMPANY_RECEIPT">🏢 Company stock received / opening</option>
                        <option value="ISSUED">🚶 Issue to salesman (Warehouse → Van)</option>
                        <option value="RETURNED">↩️ Actual Goods Returned by Salesman (Van → Warehouse)</option>
                        <option value="COMPANY_ADJUSTMENT">📈 Warehouse surplus / positive adjustment</option>
                        <option value="SALESMAN_ADJUSTMENT">📊 Salesman surplus / positive adjustment</option>
                      </SelectInput>
                    </FormField>

                    <FormField label="Product SKU" required>
                      <SelectInput
                        required
                        value={productId}
                        onChange={(e) => setProductId(e.target.value)}
                      >
                        {activeProducts.map((p) => (
                          <option key={p.product_id} value={p.product_id}>
                            {p.sku} · {p.product_name} ({p.pack_weight_g}g)
                          </option>
                        ))}
                      </SelectInput>
                    </FormField>

                    <FormField
                      label="Salesman / Assignee"
                      required={needsSalesman}
                      helpText={needsSalesman ? 'Required for van issues and returns' : 'Not required for company inventory'}
                    >
                      <SelectInput
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
                      </SelectInput>
                    </FormField>

                    <FormField label="Quantity (Packets)" required helpText="Quantity to move">
                      <QuantityInput
                        unit="pkts"
                        min={1}
                        step={1}
                        value={quantity}
                        onChange={(val) => setQuantity(val)}
                      />
                    </FormField>

                    <div className="sm:col-span-2 lg:col-span-4">
                      <FormField label="Notes / Challan Reference" helpText="Opening stock, challan #, return voucher note...">
                        <TextInput
                          maxLength={500}
                          placeholder="Opening stock, challan #, return voucher note..."
                          value={notes}
                          onChange={(e) => setNotes(e.target.value)}
                        />
                      </FormField>
                    </div>
                  </div>

                  {txnType === 'RETURNED' && (
                    <div className="p-3 rounded-xl bg-purple-50 border border-purple-200 text-xs text-purple-900">
                      <strong>Actual Physical Return (Van → Warehouse):</strong> Use this only when packets physically come back into the Central Warehouse.
                      It reduces salesman stock and increases warehouse stock. For missing or damaged salesman packets, use the{' '}
                      <strong>Physical Stock Audit &amp; Discrepancy Workflow</strong> below instead.
                    </div>
                  )}

                  <div className="flex justify-end pt-2">
                    <SaveButton label="Record Stock Movement" isLoading={movementSubmitting} />
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

        <form onSubmit={handleDiscrepancySubmit} className="space-y-4 mb-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <FormField label="Location / Custody" required>
              <SelectInput value={discLocation} onChange={(e) => setDiscLocation(e.target.value)}>
                <option value="COMPANY_WAREHOUSE">🏢 Central Warehouse</option>
                {activeSalesmen.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    🚶 Salesman: {u.full_name} ({u.user_id})
                  </option>
                ))}
              </SelectInput>
            </FormField>

            <FormField label="Product SKU" required>
              <SelectInput value={discProductId} onChange={(e) => setDiscProductId(e.target.value)}>
                {activeProducts.map((p) => (
                  <option key={p.product_id} value={p.product_id}>
                    {p.sku} - {p.product_name} ({p.pack_weight_g}g)
                  </option>
                ))}
              </SelectInput>
            </FormField>

            <FormField label="Expected Ledger Count" required>
              <QuantityInput
                unit="pkts"
                value={discExpected}
                onChange={(val) => setDiscExpected(val)}
                placeholder="System expected"
              />
            </FormField>

            <FormField label="Physical Counted" required>
              <QuantityInput
                unit="pkts"
                value={discPhysical}
                onChange={(val) => setDiscPhysical(val)}
                placeholder="Actual counted"
              />
            </FormField>

            <div className="sm:col-span-2 lg:col-span-4">
              <FormField label="Audit Explanation / Reason" helpText="e.g. Physical count post-market, batch recount, carton damage">
                <TextInput
                  value={discReason}
                  onChange={(e) => setDiscReason(e.target.value)}
                  placeholder="e.g. Physical count post-market, batch recount"
                />
              </FormField>
            </div>
          </div>

          <div className="p-3 rounded-xl border border-slate-200 bg-slate-50 text-xs flex flex-wrap items-center justify-between gap-2">
            <div>
              <strong style={{ color: liveDiscClass.color }}>{liveDiscClass.label}:</strong>{' '}
              <span className="text-slate-700">{liveDiscClass.impact}</span>
            </div>
            <span
              style={{
                padding: '2px 8px',
                borderRadius: '6px',
                fontWeight: 700,
                background: liveDiscClass.bg,
                color: liveDiscClass.color,
              }}
            >
              Difference: {liveDiscDiff > 0 ? `+${liveDiscDiff}` : liveDiscDiff} pkts
            </span>
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton label="Record Physical Audit Count" isLoading={discSubmitting} />
          </div>
        </form>

        {stockDiscrepancies && stockDiscrepancies.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Location</th>
                  <th>Product</th>
                  <th>Type / Stock Impact</th>
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
                  const discClass = classifyDiscrepancy(d.location, diff);
                  return (
                    <tr key={d.discrepancy_id}>
                      <td>{d.discrepancy_date}</td>
                      <td>{formatLocationLabel(d.location)}</td>
                      <td>{d.product_name_snapshot}</td>
                      <td>
                        <span
                          style={{
                            fontSize: '0.75rem',
                            padding: '2px 7px',
                            borderRadius: '5px',
                            fontWeight: 700,
                            background: discClass.bg,
                            color: discClass.color,
                            display: 'inline-block',
                          }}
                          title={discClass.impact}
                        >
                          {discClass.label}
                        </span>
                      </td>
                      <td>{d.expected_stock}</td>
                      <td>{d.physical_count}</td>
                      <td>
                        <strong style={{ color: diff < 0 ? '#dc2626' : diff > 0 ? '#16a34a' : '#475569' }}>
                          {diff > 0 ? `+${diff}` : diff}
                        </strong>
                      </td>
                      <td className="muted">{d.reason || '—'}</td>
                      <td>{userNameMap[d.counted_by_user_id] || d.counted_by_user_id}</td>
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
                                disabled={Boolean(reviewingDiscId)}
                                style={{ padding: '3px 8px', fontSize: '0.75rem', background: '#16a34a', color: '#fff' }}
                                onClick={() => handleReview(d.discrepancy_id, 'APPROVE')}
                              >
                                {reviewingDiscId === d.discrepancy_id ? 'Saving...' : 'Approve'}
                              </button>
                              <button
                                type="button"
                                className="secondary"
                                disabled={Boolean(reviewingDiscId)}
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
                {visibleTransactions.slice(0, 50).map((t) => {
                  const badge = formatMovementBadge(t.txn_type);
                  return (
                    <tr key={t.stock_txn_id}>
                      <td>{new Date(t.txn_datetime).toLocaleString('en-IN')}</td>
                      <td>
                        <span
                          style={{
                            fontSize: '0.8rem',
                            padding: '3px 8px',
                            borderRadius: '4px',
                            fontWeight: 700,
                            background: badge.bg,
                            color: badge.color,
                          }}
                          title={t.txn_type}
                        >
                          {badge.label}
                        </span>
                      </td>
                      <td>{t.sku_snapshot}</td>
                      <td>{t.salesman_user_id ? (userNameMap[t.salesman_user_id] || t.salesman_user_id) : 'Central Warehouse'}</td>
                      <td>
                        <strong>{t.quantity}</strong>
                      </td>
                      <td>{t.unit}</td>
                      <td className="muted">{t.notes || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No stock transactions recorded yet.</p>
        )}
      </div>
        </>
      )}
      {/* BATCH TRACKING MODAL */}
      {showBatchTracking && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(15, 23, 42, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16,
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: 960,
              width: '100%',
              maxHeight: '90vh',
              overflowY: 'auto',
              background: '#ffffff',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
              borderRadius: 8,
              position: 'relative',
              padding: 24,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h2 style={{ margin: 0, fontSize: '1.25rem', color: '#0f172a' }}>
                  📦 Bulk Batch Tracking &amp; Cost Valuation
                </h2>
                <p className="muted" style={{ margin: '4px 0 0', fontSize: '0.85rem' }}>
                  Traceable per-batch bulk inventory balance with actual production cost carryover and legacy resolution audit.
                </p>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setShowBatchTracking(false);
                  setResolvingBatchId(null);
                  setResolveCostNonces({});
                }}
                style={{ padding: '4px 12px', fontSize: '0.9rem' }}
              >
                ✕ Close
              </button>
            </div>

            {batchNotice && (
              <div
                className={batchNotice.error ? 'notice-error' : 'notice-success'}
                style={{ marginBottom: 14 }}
              >
                {batchNotice.msg}
              </div>
            )}

            {/* KPI Summary Header */}
            {(() => {
              const totalAvail = bulkBatches.reduce((sum, b) => sum + (b.available_kg || 0), 0);
              const totalVal = bulkBatches.reduce((sum, b) => sum + ((b.available_kg || 0) * (b.unit_cost_per_kg || 0)), 0);
              const missingCount = bulkBatches.filter((b) => b.cost_status === 'MISSING').length;
              const estimatedCount = bulkBatches.filter((b) => b.cost_status === 'ESTIMATED').length;
              return (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginBottom: 16 }}>
                  <div style={{ background: '#f8fafc', padding: '10px 14px', borderRadius: 6, border: '1px solid #e2e8f0' }}>
                    <small className="muted">Total Available Bulk</small>
                    <h3 style={{ margin: '2px 0 0', color: '#0f172a' }}>{totalAvail.toFixed(2)} kg</h3>
                  </div>
                  <div style={{ background: '#f0fdf4', padding: '10px 14px', borderRadius: 6, border: '1px solid #bbf7d0' }}>
                    <small style={{ color: '#166534' }}>Estimated Bulk Valuation</small>
                    <h3 style={{ margin: '2px 0 0', color: '#15803d' }}>₹{totalVal.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</h3>
                  </div>
                  <div style={{ background: '#eff6ff', padding: '10px 14px', borderRadius: 6, border: '1px solid #bfdbfe' }}>
                    <small style={{ color: '#1e40af' }}>Active Production Batches</small>
                    <h3 style={{ margin: '2px 0 0', color: '#1d4ed8' }}>{bulkBatches.length}</h3>
                  </div>
                  {(missingCount > 0 || estimatedCount > 0) && (
                    <div style={{ background: '#fffbeb', padding: '10px 14px', borderRadius: 6, border: '1px solid #fde68a' }}>
                      <small style={{ color: '#b45309' }}>Cost Status Warnings</small>
                      <h4 style={{ margin: '2px 0 0', color: '#b45309', fontSize: '0.9rem' }}>
                        {missingCount > 0 ? `⚠️ ${missingCount} Missing` : ''}
                        {missingCount > 0 && estimatedCount > 0 ? ' · ' : ''}
                        {estimatedCount > 0 ? `ℹ️ ${estimatedCount} Estimated` : ''}
                      </h4>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Filter and Refresh */}
            <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'center' }}>
              <input
                placeholder="🔍 Search Batch ID, Product or Status..."
                value={batchFilterText}
                onChange={(e) => setBatchFilterText(e.target.value)}
                style={{ flex: 1 }}
              />
              <button
                type="button"
                className="secondary"
                onClick={loadBulkBatches}
                disabled={loadingBatches}
                style={{ fontSize: '0.85rem' }}
              >
                🔄 {loadingBatches ? 'Loading...' : 'Refresh'}
              </button>
            </div>

            {/* Legacy Cost Resolution Form using FormComponents */}
            {resolvingBatchId && isManager && (
              <div className="mb-5">
                <FormLayout
                  title={`Resolve Legacy Cost for Batch: ${resolvingBatchId}`}
                  subtitle="Authoritative costing setup for legacy production run"
                  maxWidth="2xl"
                  onSubmit={handleResolveLegacyCost}
                  onCancel={() => {
                    const key = resolvingBatchId;
                    if (key) {
                      setResolveCostNonces((prev) => {
                        const next = { ...prev };
                        delete next[key];
                        return next;
                      });
                    }
                    setResolvingBatchId(null);
                  }}
                  actions={
                    <FormActions
                      onCancel={() => {
                        const key = resolvingBatchId;
                        if (key) {
                          setResolveCostNonces((prev) => {
                            const next = { ...prev };
                            delete next[key];
                            return next;
                          });
                        }
                        setResolvingBatchId(null);
                      }}
                      cancelLabel="Cancel"
                      saveLabel="Save Batch Cost"
                      isLoading={resolvingLoading}
                      disabled={resolveRate <= 0 || !resolveNotes.trim()}
                    />
                  }
                >
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <FormField label="Unit Cost (₹/kg)" required helpText="Calculated or audited cost per kg of bulk papad">
                      <MoneyInput
                        value={resolveRate || ''}
                        onChange={(val) => setResolveRate(val)}
                        placeholder="145.50"
                        required
                      />
                    </FormField>

                    <FormField label="Cost Classification" required helpText="Actual invoice or provisional estimate">
                      <SelectInput
                        value={resolveStatus}
                        onChange={(e) => setResolveStatus(e.target.value as 'ACTUAL' | 'ESTIMATED')}
                        options={[
                          { value: 'ACTUAL', label: 'ACTUAL (Verified Historical Invoices)' },
                          { value: 'ESTIMATED', label: 'ESTIMATED (Provisional / Benchmark)' },
                        ]}
                      />
                    </FormField>

                    <div className="sm:col-span-2">
                      <FormField label="Audit Explanation / Source" required helpText="Source document or calculation basis">
                        <TextInput
                          required
                          value={resolveNotes}
                          onChange={(e) => setResolveNotes(e.target.value)}
                          placeholder="e.g. Audit based on RawMaterialLedger invoice RM-INV-042 and milling yield"
                        />
                      </FormField>
                    </div>
                  </div>
                </FormLayout>
              </div>
            )}

            {/* Batches Table */}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Batch ID</th>
                    <th>Date</th>
                    <th>Product</th>
                    <th style={{ textAlign: 'right' }}>Produced</th>
                    <th style={{ textAlign: 'right' }}>Consumed</th>
                    <th style={{ textAlign: 'right', fontWeight: 700 }}>Available</th>
                    <th style={{ textAlign: 'right' }}>Unit Cost</th>
                    <th style={{ textAlign: 'center' }}>Cost Status</th>
                    <th style={{ textAlign: 'right' }}>Valuation</th>
                    {isManager && <th style={{ textAlign: 'center' }}>Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {bulkBatches
                    .filter((b) => {
                      if (!batchFilterText.trim()) return true;
                      const q = batchFilterText.toLowerCase();
                      return (
                        b.batch_id?.toLowerCase().includes(q) ||
                        b.product_name?.toLowerCase().includes(q) ||
                        b.cost_status?.toLowerCase().includes(q) ||
                        b.cost_source?.toLowerCase().includes(q)
                      );
                    })
                    .map((b) => {
                      const avail = b.available_kg || 0;
                      const cost = b.unit_cost_per_kg;
                      const val = (avail * (cost || 0));
                      const isActual = b.cost_status === 'ACTUAL';
                      const isEstimated = b.cost_status === 'ESTIMATED';
                      const isMissing = b.cost_status === 'MISSING';
                      return (
                        <tr key={b.batch_id}>
                          <td><strong>{b.batch_id}</strong></td>
                          <td>{b.production_date || '—'}</td>
                          <td>{b.product_name}</td>
                          <td style={{ textAlign: 'right' }}>{b.produced_kg.toFixed(2)} kg</td>
                          <td style={{ textAlign: 'right', color: '#64748b' }}>{b.consumed_kg.toFixed(2)} kg</td>
                          <td style={{ textAlign: 'right', fontWeight: 700, color: avail > 0 ? '#15803d' : '#94a3b8' }}>
                            {avail.toFixed(2)} kg
                          </td>
                          <td style={{ textAlign: 'right', fontWeight: 600 }}>
                            {cost !== null && cost !== undefined ? `₹${Number(cost).toFixed(2)}` : '—'}
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <span
                              style={{
                                fontSize: '0.75rem',
                                padding: '2px 8px',
                                borderRadius: 4,
                                fontWeight: 700,
                                background: isActual ? '#dcfce7' : isEstimated ? '#fef3c7' : '#fee2e2',
                                color: isActual ? '#15803d' : isEstimated ? '#b45309' : '#b91c1c',
                              }}
                              title={b.cost_source ? `Source: ${b.cost_source}` : undefined}
                            >
                              {b.cost_status || 'ACTUAL'}
                            </span>
                          </td>
                          <td style={{ textAlign: 'right', fontWeight: 600 }}>
                            {cost !== null && cost !== undefined ? `₹${val.toFixed(2)}` : '—'}
                          </td>
                          {isManager && (
                            <td style={{ textAlign: 'center' }}>
                              {(isMissing || isEstimated) && (
                                <button
                                  type="button"
                                  className="secondary"
                                  onClick={() => {
                                    setResolveCostNonces((prev) => {
                                      const next = { ...prev };
                                      delete next[b.batch_id];
                                      return next;
                                    });
                                    setResolvingBatchId(b.batch_id);
                                    setResolveRate(cost || 0);
                                    setResolveStatus(isEstimated ? 'ESTIMATED' : 'ACTUAL');
                                    setResolveNotes(b.cost_notes || '');
                                  }}
                                  style={{ fontSize: '0.75rem', padding: '2px 8px' }}
                                >
                                  ⚖️ Resolve
                                </button>
                              )}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  {bulkBatches.length === 0 && (
                    <tr>
                      <td colSpan={isManager ? 10 : 9} style={{ textAlign: 'center', padding: 16 }} className="muted">
                        {loadingBatches ? 'Loading bulk batch inventory...' : 'No approved bulk production batches found.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================= */}
      {/* PHASE 2A.1: MORNING VAN LOADING PASS TAB                          */}
      {/* ================================================================= */}
      {stockTab === 'van_loading' && (
        <div className="space-y-6">
          {loadingPassNotice && (
            <div className={`p-4 rounded-xl text-sm font-medium flex items-center justify-between border ${
              loadingPassNotice.error
                ? 'bg-rose-50 text-rose-800 border-rose-200'
                : 'bg-emerald-50 text-emerald-800 border-emerald-200'
            }`}>
              <div className="flex items-center gap-2.5">
                {loadingPassNotice.error ? (
                  <AlertCircle className="w-5 h-5 text-rose-600 shrink-0" />
                ) : (
                  <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                )}
                <span>{loadingPassNotice.msg}</span>
              </div>
              <button
                type="button"
                onClick={() => setLoadingPassNotice(null)}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* SALESMAN ACTION BANNER: PENDING LOADING PASSES */}
          {pendingSalesmanPasses.length > 0 && (
            <div className="bg-amber-50 border-2 border-amber-300 rounded-2xl p-5 shadow-xs space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-amber-500 text-white flex items-center justify-center font-bold shadow-xs">
                    <Truck className="w-6 h-6" />
                  </div>
                  <div>
                    <h2 className="text-base sm:text-lg font-bold text-amber-950 m-0">
                      Your Van Loading is Ready / आपकी गाड़ी का माल तैयार है
                    </h2>
                    <p className="text-xs sm:text-sm text-amber-800 mt-0.5 mb-0">
                      Please verify physical packet counts in the van and accept stock to begin daily sales.
                    </p>
                  </div>
                </div>
                <span className="bg-amber-200 text-amber-900 text-xs font-extrabold px-2.5 py-1 rounded-full uppercase tracking-wider">
                  {pendingSalesmanPasses.length} Pending
                </span>
              </div>

              <div className="grid grid-cols-1 gap-4">
                {pendingSalesmanPasses.map((pass) => (
                  <div key={pass.pass_id} className="bg-white rounded-xl border border-amber-200 p-4 shadow-2xs space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
                      <div>
                        <span className="text-xs font-mono font-bold text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          {pass.pass_number}
                        </span>
                        <span className="ml-2 font-bold text-slate-800 text-sm">
                          {pass.van_number}
                        </span>
                        <span className="text-xs text-slate-500 ml-2">
                          ({pass.loading_date})
                        </span>
                      </div>
                      <div className="text-xs text-slate-600">
                        Loaded by: <span className="font-semibold text-slate-800">{pass.created_by_name}</span>
                      </div>
                    </div>

                    {/* Loaded Items Table */}
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs text-left">
                        <thead className="bg-slate-50 text-slate-600">
                          <tr>
                            <th className="py-2 px-3">Product Name / Item</th>
                            <th className="py-2 px-3 text-center">Pack Size</th>
                            <th className="py-2 px-3 text-right">Quantity (Packets)</th>
                            <th className="py-2 px-3 text-right">Weight (kg)</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {pass.items.map((it, idx) => (
                            <tr key={idx} className="hover:bg-slate-50/50">
                              <td className="py-2 px-3 font-medium text-slate-900">
                                {it.product_name || it.sku}
                              </td>
                              <td className="py-2 px-3 text-center text-slate-600">
                                {it.pack_weight_g}g
                              </td>
                              <td className="py-2 px-3 text-right font-bold text-emerald-700">
                                {it.quantity} pkts
                              </td>
                              <td className="py-2 px-3 text-right text-slate-600">
                                {it.weight_kg ? Number(it.weight_kg).toFixed(2) : '-'} kg
                              </td>
                            </tr>
                          ))}
                        </tbody>
                        <tfoot className="bg-slate-50 font-bold border-t border-slate-200 text-slate-900">
                          <tr>
                            <td className="py-2 px-3" colSpan={2}>Total Loaded</td>
                            <td className="py-2 px-3 text-right text-emerald-800">{pass.total_packets} pkts</td>
                            <td className="py-2 px-3 text-right text-slate-800">{Number(pass.total_weight_kg).toFixed(2)} kg</td>
                          </tr>
                        </tfoot>
                      </table>
                    </div>

                    {pass.notes && (
                      <div className="text-xs text-slate-500 bg-slate-50 p-2 rounded border border-slate-100">
                        <span className="font-semibold">Notes:</span> {pass.notes}
                      </div>
                    )}

                    {/* Salesman Verification Action Buttons */}
                    <div className="flex flex-col sm:flex-row items-center justify-end gap-2.5 pt-2">
                      <button
                        type="button"
                        onClick={() => {
                          setDiscrepancyModalPass(pass);
                          setDiscrepancyNotes('');
                          setDiscrepancyNonce('');
                          setDiscrepancyError(null);
                        }}
                        className="w-full sm:w-auto px-4 py-2.5 text-xs font-bold text-amber-800 bg-amber-100 hover:bg-amber-200 border border-amber-300 rounded-xl transition-all cursor-pointer flex items-center justify-center gap-1.5"
                      >
                        <AlertTriangle className="w-4 h-4 text-amber-700" />
                        <span>Report Discrepancy / गड़बड़ी दर्ज करें</span>
                      </button>

                      <button
                        type="button"
                        disabled={acceptingPassId === pass.pass_id}
                        onClick={() => handleAcceptPass(pass.pass_id)}
                        className="w-full sm:w-auto px-6 py-2.5 text-xs font-extrabold text-white bg-emerald-700 hover:bg-emerald-800 shadow-sm hover:shadow rounded-xl transition-all cursor-pointer flex items-center justify-center gap-2 disabled:opacity-50"
                      >
                        {acceptingPassId === pass.pass_id ? (
                          <>
                            <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            <span>Confirming Transfer...</span>
                          </>
                        ) : (
                          <>
                            <CheckCircle2 className="w-4 h-4" />
                            <span>Confirm Physical Count &amp; Accept Stock / माल स्वीकार करें</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* WAREHOUSE KEEPER: CREATE LOADING PASS FORM */}
          {isManager && (
            <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
              <div className="p-4 sm:p-5 border-b border-slate-100 bg-slate-50/60 flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-slate-900 m-0 flex items-center gap-2">
                    <Truck className="w-5 h-5 text-emerald-700" />
                    <span>Create Van Loading Pass / गाड़ी में माल भरो</span>
                  </h2>
                  <p className="text-xs text-slate-500 mt-0.5 mb-0">
                    Select van, assigned salesman, and enter finished goods packets to load. Stock is deducted upon salesman acceptance.
                  </p>
                </div>
              </div>

              <form onSubmit={handleCreateLoadingPass} className="p-4 sm:p-6 space-y-6">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">
                      Loading Date / दिनांक <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="date"
                      value={passDate}
                      onChange={(e) => setPassDate(e.target.value)}
                      required
                      className="w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:border-emerald-600 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">
                      Delivery Van / गाड़ी नंबर <span className="text-rose-500">*</span>
                    </label>
                    <select
                      value={passVan}
                      onChange={(e) => setPassVan(e.target.value)}
                      required
                      className="w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:border-emerald-600 focus:outline-none"
                    >
                      <option value="Van 1 - RJ 09 GA 1234">Van 1 (RJ 09 GA 1234)</option>
                      <option value="Van 2 - RJ 09 GA 5678">Van 2 (RJ 09 GA 5678)</option>
                      <option value="Van 3 - RJ 09 GA 9012">Van 3 (RJ 09 GA 9012)</option>
                      <option value="Auto / Rickshaw 1">Auto / Rickshaw 1</option>
                      <option value="Factory Counter / Direct">Factory Direct Loading</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">
                      Assigned Salesman / गाड़ी चालक <span className="text-rose-500">*</span>
                    </label>
                    <select
                      value={passSalesmanId}
                      onChange={(e) => setPassSalesmanId(e.target.value)}
                      required
                      className="w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:border-emerald-600 focus:outline-none"
                    >
                      <option value="">-- Select Salesman --</option>
                      {activeSalesmen.map((s) => (
                        <option key={s.user_id} value={s.user_id}>
                          {s.full_name} ({s.user_id})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* PRODUCT SELECTION TABLE */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                      Product Quantities / माल की मात्रा (पैकेट)
                    </label>
                    <span className="text-xs text-slate-500">
                      Warehouse stock cannot become negative
                    </span>
                  </div>

                  <div className="overflow-x-auto border border-slate-200 rounded-xl">
                    <table className="w-full text-xs text-left">
                      <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                        <tr>
                          <th className="py-2.5 px-3">Product SKU &amp; Name</th>
                          <th className="py-2.5 px-3 text-center">Pack Weight</th>
                          <th className="py-2.5 px-3 text-right">Available in Warehouse</th>
                          <th className="py-2.5 px-3 text-center min-w-[200px]">Packets to Load</th>
                          <th className="py-2.5 px-3 text-right">Weight (kg)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {activeProducts.map((p) => {
                          const available = warehouseStockMap[p.product_id] || 0;
                          const entered = passQuantities[p.product_id] || 0;
                          const isOver = entered > available;
                          const lineWeightKg = ((entered * (p.pack_weight_g || 500)) / 1000.0).toFixed(2);

                          return (
                            <tr
                              key={p.product_id}
                              className={`transition-colors ${
                                isOver ? 'bg-rose-50/70' : entered > 0 ? 'bg-emerald-50/40' : 'hover:bg-slate-50/50'
                              }`}
                            >
                              <td className="py-2.5 px-3">
                                <div className="font-bold text-slate-900">{p.product_name}</div>
                                <div className="text-[11px] font-mono text-slate-500">{p.sku}</div>
                              </td>
                              <td className="py-2.5 px-3 text-center text-slate-600 font-medium">
                                {p.pack_weight_g}g
                              </td>
                              <td className="py-2.5 px-3 text-right">
                                <span className={`inline-block px-2 py-0.5 rounded text-xs font-bold ${
                                  available <= 0
                                    ? 'bg-rose-100 text-rose-700'
                                    : available < 20
                                    ? 'bg-amber-100 text-amber-800'
                                    : 'bg-slate-100 text-slate-700'
                                }`}>
                                  {available} pkts
                                </span>
                              </td>
                              <td className="py-2.5 px-3">
                                <div className="flex items-center justify-center gap-1.5">
                                  <input
                                    type="number"
                                    min="0"
                                    max={available}
                                    value={entered || ''}
                                    placeholder="0"
                                    onChange={(e) => {
                                      const val = Math.max(0, parseInt(e.target.value, 10) || 0);
                                      setPassQuantities((prev) => ({ ...prev, [p.product_id]: val }));
                                    }}
                                    className={`w-20 px-2 py-1.5 text-center text-sm font-bold rounded-lg border focus:outline-none ${
                                      isOver
                                        ? 'border-rose-400 bg-rose-50 text-rose-700'
                                        : entered > 0
                                        ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                                        : 'border-slate-200 bg-white text-slate-900'
                                    }`}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => setPassQuantities((prev) => ({ ...prev, [p.product_id]: Math.min(available, (prev[p.product_id] || 0) + 10) }))}
                                    className="px-2 py-1 text-[11px] bg-slate-100 hover:bg-slate-200 text-slate-700 rounded font-semibold cursor-pointer"
                                  >
                                    +10
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setPassQuantities((prev) => ({ ...prev, [p.product_id]: Math.min(available, (prev[p.product_id] || 0) + 25) }))}
                                    className="px-2 py-1 text-[11px] bg-slate-100 hover:bg-slate-200 text-slate-700 rounded font-semibold cursor-pointer"
                                  >
                                    +25
                                  </button>
                                  {entered > 0 && (
                                    <button
                                      type="button"
                                      onClick={() => setPassQuantities((prev) => ({ ...prev, [p.product_id]: 0 }))}
                                      className="p-1 text-slate-400 hover:text-rose-600 rounded cursor-pointer"
                                      title="Clear"
                                    >
                                      <X className="w-3.5 h-3.5" />
                                    </button>
                                  )}
                                </div>
                                {isOver && (
                                  <div className="text-[10px] text-rose-600 font-bold text-center mt-1">
                                    Exceeds available stock ({available} pkts)!
                                  </div>
                                )}
                              </td>
                              <td className="py-2.5 px-3 text-right font-medium text-slate-700">
                                {entered > 0 ? `${lineWeightKg} kg` : '—'}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* NOTES */}
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Notes / Remarks / विशेष टिप्पणी (वैकल्पिक)
                  </label>
                  <input
                    type="text"
                    value={passNotes}
                    onChange={(e) => setPassNotes(e.target.value)}
                    placeholder="e.g. Route: Bhilwara Mandi, Extra stock for festive promotion"
                    className="w-full px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:border-emerald-600 focus:outline-none"
                  />
                </div>

                {/* SUMMARY & SUBMISSION BAR */}
                <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 flex flex-col sm:flex-row items-center justify-between gap-4">
                  <div className="grid grid-cols-3 gap-6 text-center sm:text-left">
                    <div>
                      <div className="text-[11px] text-slate-500 font-medium">Total SKUs</div>
                      <div className="text-base font-extrabold text-slate-900">{passSummary.totalSkus} SKUs</div>
                    </div>
                    <div>
                      <div className="text-[11px] text-slate-500 font-medium">Total Packets</div>
                      <div className="text-base font-extrabold text-emerald-700">{passSummary.totalPackets} pkts</div>
                    </div>
                    <div>
                      <div className="text-[11px] text-slate-500 font-medium">Total Weight</div>
                      <div className="text-base font-extrabold text-slate-900">{passSummary.totalWeightKg.toFixed(2)} kg</div>
                    </div>
                  </div>

                  <button
                    type="submit"
                    disabled={isCreatingPass || passSummary.totalPackets <= 0 || passSummary.hasExceededStock}
                    className="w-full sm:w-auto px-6 py-3 bg-emerald-800 hover:bg-emerald-900 text-white font-extrabold text-sm rounded-xl shadow-sm transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {isCreatingPass ? (
                      <>
                        <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        <span>Generating Loading Pass...</span>
                      </>
                    ) : (
                      <>
                        <Truck className="w-4 h-4" />
                        <span>Generate Loading Pass / लोडिंग पर्ची बनाएं</span>
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* LOADING PASSES RECORD & AUDIT HISTORY */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
            <div className="p-4 sm:p-5 border-b border-slate-100 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-slate-900 m-0">
                  Van Loading Passes History / लोडिंग पर्ची रिकॉर्ड
                </h3>
                <p className="text-xs text-slate-500 mt-0.5 mb-0">
                  Traceable audit trail of morning stock dispatches and physical salesman acceptances
                </p>
              </div>

              {/* Status Filter */}
              <div className="flex items-center gap-1.5">
                {['ALL', 'PENDING_ACCEPTANCE', 'ACCEPTED', 'DISCREPANCY_REPORTED', 'CANCELLED'].map((st) => (
                  <button
                    key={st}
                    type="button"
                    onClick={() => setLoadingPassFilterStatus(st)}
                    className={`px-2.5 py-1 text-[11px] font-bold rounded-lg transition-all cursor-pointer ${
                      loadingPassFilterStatus === st
                        ? 'bg-slate-900 text-white'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    {st === 'ALL'
                      ? 'All'
                      : st === 'PENDING_ACCEPTANCE'
                      ? 'Pending'
                      : st === 'ACCEPTED'
                      ? 'Accepted'
                      : st === 'DISCREPANCY_REPORTED'
                      ? 'Discrepancy'
                      : 'Cancelled'}
                  </button>
                ))}
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                  <tr>
                    <th className="py-2.5 px-3">Pass Number</th>
                    <th className="py-2.5 px-3">Date</th>
                    <th className="py-2.5 px-3">Van / Vehicle</th>
                    <th className="py-2.5 px-3">Assigned Salesman</th>
                    <th className="py-2.5 px-3 text-center">SKUs</th>
                    <th className="py-2.5 px-3 text-right">Packets</th>
                    <th className="py-2.5 px-3 text-right">Total kg</th>
                    <th className="py-2.5 px-3 text-center">Status</th>
                    <th className="py-2.5 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {loadingPasses
                    .filter((p) => loadingPassFilterStatus === 'ALL' || p.status === loadingPassFilterStatus)
                    .map((pass) => {
                      const isPending = pass.status === 'PENDING_ACCEPTANCE';
                      const isAccepted = pass.status === 'ACCEPTED';
                      const isDiscrepancy = pass.status === 'DISCREPANCY_REPORTED';
                      const isCancelled = pass.status === 'CANCELLED';

                      return (
                        <tr key={pass.pass_id} className="hover:bg-slate-50/60">
                          <td className="py-2.5 px-3 font-mono font-bold text-emerald-800">
                            {pass.pass_number}
                          </td>
                          <td className="py-2.5 px-3 text-slate-600 whitespace-nowrap">
                            {pass.loading_date}
                          </td>
                          <td className="py-2.5 px-3 font-medium text-slate-900">
                            {pass.van_number}
                          </td>
                          <td className="py-2.5 px-3">
                            <span className="font-semibold text-slate-900">{pass.salesman_name}</span>
                            <span className="text-[10px] text-slate-500 block">{pass.salesman_user_id}</span>
                          </td>
                          <td className="py-2.5 px-3 text-center text-slate-600 font-medium">
                            {pass.total_skus}
                          </td>
                          <td className="py-2.5 px-3 text-right font-bold text-slate-900">
                            {pass.total_packets} pkts
                          </td>
                          <td className="py-2.5 px-3 text-right text-slate-600">
                            {Number(pass.total_weight_kg).toFixed(2)} kg
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            {isAccepted && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-800">
                                <CheckCircle2 className="w-3 h-3 text-emerald-700" />
                                <span>Accepted</span>
                              </span>
                            )}
                            {isPending && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-100 text-amber-800 animate-pulse">
                                <Clock className="w-3 h-3 text-amber-700" />
                                <span>Waiting</span>
                              </span>
                            )}
                            {isDiscrepancy && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-100 text-rose-800">
                                <AlertTriangle className="w-3 h-3 text-rose-700" />
                                <span>Discrepancy</span>
                              </span>
                            )}
                            {isCancelled && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-slate-100 text-slate-600">
                                <span>Cancelled</span>
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 px-3 text-right whitespace-nowrap">
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => setViewingPass(pass)}
                                className="px-2.5 py-1 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg cursor-pointer"
                              >
                                View Details
                              </button>

                              {/* Salesman or Manager can accept if pending */}
                              {!isAuditor && isPending && (!isFieldSalesman || pass.salesman_user_id === currentUser?.user_id) && (
                                <button
                                  type="button"
                                  onClick={() => handleAcceptPass(pass.pass_id)}
                                  disabled={acceptingPassId === pass.pass_id}
                                  className="px-2.5 py-1 text-xs font-bold text-white bg-emerald-700 hover:bg-emerald-800 rounded-lg cursor-pointer shadow-2xs"
                                >
                                  {acceptingPassId === pass.pass_id ? 'Accepting...' : 'Accept'}
                                </button>
                              )}

                              {/* Manager or Creator can cancel if pending */}
                              {isPending && isManager && (
                                <button
                                  type="button"
                                  disabled={Boolean(cancellingPassId)}
                                  onClick={() => setCancelPassTargetId(pass.pass_id)}
                                  className="px-2 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50 rounded-lg cursor-pointer disabled:opacity-50"
                                  title="Cancel Pass"
                                >
                                  {cancellingPassId === pass.pass_id ? 'Cancelling...' : 'Cancel'}
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}

                  {loadingPasses.length === 0 && (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-slate-500">
                        {loadingPassesLoading
                          ? 'Loading van loading passes...'
                          : 'No van loading passes recorded yet. Create the first morning pass above.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* VIEW PASS MODAL */}
          {viewingPass && (
            <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
              <div className="bg-white rounded-2xl max-w-lg w-full p-5 sm:p-6 shadow-xl border border-slate-200 space-y-4 max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between pb-3 border-b border-slate-200">
                  <div>
                    <h3 className="text-base font-bold text-slate-900 m-0">
                      Van Loading Pass / गाड़ी लोडिंग पर्ची
                    </h3>
                    <span className="text-xs font-mono font-bold text-emerald-800">
                      {viewingPass.pass_number}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setViewingPass(null)}
                    className="text-slate-400 hover:text-slate-600 p-1"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-3 text-xs bg-slate-50 p-3 rounded-xl border border-slate-100">
                  <div>
                    <span className="text-slate-500">Date:</span>{' '}
                    <span className="font-bold text-slate-800">{viewingPass.loading_date}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Van:</span>{' '}
                    <span className="font-bold text-slate-800">{viewingPass.van_number}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Salesman:</span>{' '}
                    <span className="font-bold text-slate-800">{viewingPass.salesman_name}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Issuer:</span>{' '}
                    <span className="font-bold text-slate-800">{viewingPass.created_by_name}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Status:</span>{' '}
                    <span className="font-extrabold text-emerald-800">{viewingPass.status}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Created:</span>{' '}
                    <span className="text-slate-700">{viewingPass.created_at ? viewingPass.created_at.slice(0, 16).replace('T', ' ') : '—'}</span>
                  </div>
                </div>

                {viewingPass.discrepancy_notes && (
                  <div className="bg-rose-50 border border-rose-200 p-3 rounded-xl text-xs text-rose-900">
                    <span className="font-bold block mb-0.5">Reported Discrepancy:</span>
                    {viewingPass.discrepancy_notes}
                  </div>
                )}

                {/* Items breakdown */}
                <div className="overflow-x-auto border border-slate-200 rounded-xl">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-slate-50 text-slate-600">
                      <tr>
                        <th className="py-2 px-3">Product Name</th>
                        <th className="py-2 px-3 text-center">Pack</th>
                        <th className="py-2 px-3 text-right">Packets</th>
                        <th className="py-2 px-3 text-right">kg</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {viewingPass.items.map((it, idx) => (
                        <tr key={idx}>
                          <td className="py-2 px-3 font-medium text-slate-900">{it.product_name || it.sku}</td>
                          <td className="py-2 px-3 text-center text-slate-600">{it.pack_weight_g}g</td>
                          <td className="py-2 px-3 text-right font-bold text-emerald-800">{it.quantity} pkts</td>
                          <td className="py-2 px-3 text-right text-slate-600">{it.weight_kg ? Number(it.weight_kg).toFixed(2) : '-'} kg</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="bg-slate-50 font-bold border-t border-slate-200 text-slate-900">
                      <tr>
                        <td className="py-2 px-3" colSpan={2}>Grand Total</td>
                        <td className="py-2 px-3 text-right text-emerald-800">{viewingPass.total_packets} pkts</td>
                        <td className="py-2 px-3 text-right">{Number(viewingPass.total_weight_kg).toFixed(2)} kg</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>

                {viewingPass.accepted_at && (
                  <div className="text-xs text-emerald-800 bg-emerald-50 p-2.5 rounded-xl border border-emerald-100 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                    <span>
                      Accepted by <strong>{viewingPass.accepted_by_user_id}</strong> on{' '}
                      {viewingPass.accepted_at.slice(0, 16).replace('T', ' ')}
                    </span>
                  </div>
                )}

                <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                  <button
                    type="button"
                    onClick={() => setViewingPass(null)}
                    className="px-4 py-2 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-xl cursor-pointer"
                  >
                    Close
                  </button>
                  {!isAuditor && viewingPass.status === 'PENDING_ACCEPTANCE' && (!isFieldSalesman || viewingPass.salesman_user_id === currentUser?.user_id) && (
                    <button
                      type="button"
                      onClick={() => handleAcceptPass(viewingPass.pass_id)}
                      disabled={acceptingPassId === viewingPass.pass_id}
                      className="px-4 py-2 text-xs font-bold text-white bg-emerald-700 hover:bg-emerald-800 rounded-xl cursor-pointer shadow-xs"
                    >
                      {acceptingPassId === viewingPass.pass_id ? 'Accepting...' : 'Accept Stock'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* DISCREPANCY REPORTING MODAL */}
          {discrepancyModalPass && (
            <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
              <form onSubmit={handleReportDiscrepancy} className="bg-white rounded-2xl max-w-md w-full p-5 sm:p-6 shadow-xl border border-slate-200 space-y-4">
                <div className="flex items-center justify-between pb-3 border-b border-slate-200">
                  <div className="flex items-center gap-2 text-amber-700 font-bold">
                    <AlertTriangle className="w-5 h-5 text-amber-600" />
                    <span>Report Physical Count Discrepancy</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setDiscrepancyModalPass(null);
                      setDiscrepancyNonce('');
                      setDiscrepancyError(null);
                    }}
                    className="text-slate-400 hover:text-slate-600 p-1"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                {discrepancyError && (
                  <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-semibold">
                    {discrepancyError}
                  </div>
                )}

                <p className="text-xs text-slate-600 m-0">
                  Report any missing, leaking, or damaged packets found while verifying loading pass{' '}
                  <strong className="font-mono text-slate-900">{discrepancyModalPass.pass_number}</strong>.
                  The pass will be flagged for warehouse manager review.
                </p>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Discrepancy Details / गड़बड़ी का विवरण <span className="text-rose-500">*</span>
                  </label>
                  <textarea
                    rows={4}
                    value={discrepancyNotes}
                    onChange={(e) => setDiscrepancyNotes(e.target.value)}
                    required
                    placeholder="e.g. Counted 22 packets of Chana Chotu 200g instead of 25. 3 packets missing from carton."
                    className="w-full px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:border-amber-500 focus:outline-none"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                  <button
                    type="button"
                    onClick={() => {
                      setDiscrepancyModalPass(null);
                      setDiscrepancyNonce('');
                      setDiscrepancyError(null);
                    }}
                    className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmittingDiscrepancy || !discrepancyNotes.trim()}
                    className="px-4 py-2 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-xl cursor-pointer shadow-xs disabled:opacity-50"
                  >
                    {isSubmittingDiscrepancy ? 'Submitting...' : 'Submit Discrepancy'}
                  </button>
                </div>
              </form>
            </div>
          )}

          {cancelPassTargetId && (
            <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
              <div className="bg-white rounded-2xl max-w-md w-full p-5 shadow-xl border border-slate-200 space-y-4">
                <h3 className="text-base font-bold text-slate-900 m-0">Cancel Pending Loading Pass</h3>
                <p className="text-xs text-slate-600 m-0">
                  Are you sure you want to cancel pending loading pass{' '}
                  <strong className="font-mono text-slate-900">{cancelPassTargetId}</strong>?
                </p>
                <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                  <button
                    type="button"
                    disabled={Boolean(cancellingPassId)}
                    onClick={() => setCancelPassTargetId(null)}
                    className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl cursor-pointer disabled:opacity-50"
                  >
                    Keep Pass
                  </button>
                  <button
                    type="button"
                    disabled={Boolean(cancellingPassId)}
                    onClick={() => handleCancelPass(cancelPassTargetId)}
                    className="px-4 py-2 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-xl cursor-pointer disabled:opacity-50"
                  >
                    {cancellingPassId === cancelPassTargetId ? 'Cancelling...' : 'Confirm Cancel Pass'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};


