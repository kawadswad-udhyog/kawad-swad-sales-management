import React, { useState, useEffect, useCallback } from 'react';
import {
  ShieldCheck,
  Plus,
  RefreshCw,
  Search,
  CheckCircle,
  AlertTriangle,
  AlertOctagon,
  Clock,
  Layers,
  ArrowRightLeft,
  X,
  FileText,
  BadgeAlert,
  ShieldAlert,
} from 'lucide-react';
import {
  getQualityChecks,
  createQualityCheck,
  getProductLots,
  createProductLot,
  updateLotStatus,
  getLotMovements,
  getCustomerReturns,
  createCustomerReturn,
  getComplaintsRecalls,
  createComplaintOrRecall,
  closeComplaint,
  getQualitySummary,
  createSubmissionNonce,
  extractUnknownOutcomeInfo,
  isUnknownOutcomeError,
} from '../services/api';
import { UnknownOutcomeBanner } from '../components/common/UnknownOutcomeBanner';
import { shouldBlockDraftNonceReset, useUnknownOutcomeGuard } from '../utils/unknownOutcomeLock';
import type {
  QualityCheck,
  ProductLot,
  LotMovement,
  CustomerReturn,
  ComplaintRecall,
} from '../types';
import {
  FormLayout,
  FormField,
  TextInput,
  SelectInput,
  TextArea,
  DateInput,
  FormActions,
  SaveButton,
  CancelButton,
} from '../components/common/FormComponents';

import { useStore } from '../context/StoreContext';
import { resolveCanonical12Role } from '../utils/permissions';

type QualityTab = 'checks' | 'lots' | 'returns' | 'complaints';

const UNKNOWN_OUTCOME_MSG =
  'Status not confirmed; do not submit a new transaction. Your inputs and retry key are preserved—retry safely.';

function getIstToday(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
}

export const QualityView: React.FC = () => {
  const { currentUser, products, customers } = useStore();
  const canonicalRole = resolveCanonical12Role(currentUser?.role);
  const isAuditor = canonicalRole === 'AUDITOR';
  const canSubmitCheck = ['OWNER_ADMIN', 'QUALITY', 'PRODUCTION'].includes(canonicalRole);
  const canManageQuality = ['OWNER_ADMIN', 'QUALITY'].includes(canonicalRole);
  const canCloseComplaint = canonicalRole === 'OWNER_ADMIN';

  const [activeTab, setActiveTab] = useState<QualityTab>('lots');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Metrics
  const [summary, setSummary] = useState({
    total_checks: 0,
    quarantined_lots: 0,
    open_returns: 0,
    open_complaints: 0,
  });

  // Tab Data States
  const [checks, setChecks] = useState<QualityCheck[]>([]);
  const [lots, setLots] = useState<ProductLot[]>([]);
  const [returns, setReturns] = useState<CustomerReturn[]>([]);
  const [complaints, setComplaints] = useState<ComplaintRecall[]>([]);
  const [movements, setMovements] = useState<LotMovement[]>([]);
  const [selectedLotForMovement, setSelectedLotForMovement] = useState<string | null>(null);

  // Modals
  const [showCheckModal, setShowCheckModal] = useState(false);
  const [showLotModal, setShowLotModal] = useState(false);
  const [showReturnModal, setShowReturnModal] = useState(false);
  const [showComplaintModal, setShowComplaintModal] = useState(false);
  const [showResolveModal, setShowResolveModal] = useState<ComplaintRecall | null>(null);
  const [lotActionModal, setLotActionModal] = useState<{
    lotId: string;
    targetStatus: 'RELEASED' | 'ON_HOLD' | 'REJECTED';
    reason: string;
  } | null>(null);

  // Submission guards & stable idempotency nonces (preserved across retries / HTTP 504)
  const [lotTransitionSubmitting, setLotTransitionSubmitting] = useState(false);
  const [checkSubmitting, setCheckSubmitting] = useState(false);
  const [lotSubmitting, setLotSubmitting] = useState(false);
  const [returnSubmitting, setReturnSubmitting] = useState(false);
  const [complaintSubmitting, setComplaintSubmitting] = useState(false);
  const [resolveSubmitting, setResolveSubmitting] = useState(false);
  const [lotActionNonces, setLotActionNonces] = useState<Record<string, string>>({});
  const [checkNonce, setCheckNonce] = useState('');
  const [lotNonce, setLotNonce] = useState('');
  const [returnNonce, setReturnNonce] = useState('');
  const [complaintNonce, setComplaintNonce] = useState('');
  const [resolveNonce, setResolveNonce] = useState('');
  const {
    unknownOutcome,
    isOutcomeLocked,
    lockWithUnknownOutcome,
    clearAfterVerifiedResolution,
  } = useUnknownOutcomeGuard('quality_view');

  // Clean form states (POL-013: no fabricated dummy records pre-filled)
  const [newCheck, setNewCheck] = useState({
    check_type: 'FINISHED_GOODS' as 'RAW_MATERIAL' | 'IN_PROCESS' | 'FINISHED_GOODS',
    entity_type: 'LOT',
    entity_id: '',
    item_name: '',
    decision: 'PASS' as 'PASS' | 'FAIL' | 'HOLD',
    defect_details: '',
    corrective_action: '',
    notes: '',
  });

  const [newLot, setNewLot] = useState({
    product_id: '',
    product_name: '',
    initial_quantity: 0,
    unit: 'packet',
    expiry_date: '',
    notes: '',
  });

  const [newReturn, setNewReturn] = useState({
    sale_id: '',
    customer_id: '',
    customer_name: '',
    return_date: getIstToday(),
    disposition: 'PENDING_INSPECTION' as 'SCRAP' | 'RESTOCK' | 'PENDING_INSPECTION',
    notes: '',
    items: [
      { product_id: '', sku: '', product_name: '', quantity: 1, unit: 'packet', unit_price: 0, reason: '' },
    ],
  });

  const [newComplaint, setNewComplaint] = useState({
    report_type: 'COMPLAINT' as 'COMPLAINT' | 'RECALL',
    product_id: '',
    lot_id: '',
    customer_id: '',
    customer_name: '',
    quantity_affected: 0,
    severity: 'MEDIUM' as 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL',
    description: '',
    notes: '',
  });

  const [resolveForm, setResolveForm] = useState({
    investigation: '',
    corrective_action: '',
    notes: '',
  });

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const sum = await getQualitySummary().catch(() => ({
        total_checks: 0,
        quarantined_lots: 0,
        open_returns: 0,
        open_complaints: 0,
      }));
      setSummary(sum);

      if (activeTab === 'lots') {
        const lotList = await getProductLots().catch(() => []);
        setLots(lotList);
      } else if (activeTab === 'checks') {
        const checkList = await getQualityChecks().catch(() => []);
        setChecks(checkList);
      } else if (activeTab === 'returns') {
        const retList = await getCustomerReturns().catch(() => []);
        setReturns(retList);
      } else if (activeTab === 'complaints') {
        const compList = await getComplaintsRecalls().catch(() => []);
        setComplaints(compList);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  }, [activeTab]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleOpenLotTransition = (lotId: string, targetStatus: 'RELEASED' | 'ON_HOLD' | 'REJECTED') => {
    if (isOutcomeLocked) return;
    setError(null);
    setLotActionModal({ lotId, targetStatus, reason: '' });
  };

  const handleConfirmLotTransition = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!lotActionModal || lotTransitionSubmitting || isOutcomeLocked) return;
    if (lotActionModal.targetStatus !== 'RELEASED' && !lotActionModal.reason.trim()) {
      setError(`Reason is required before marking a lot as ${lotActionModal.targetStatus}.`);
      return;
    }
    const key = `${lotActionModal.lotId}:${lotActionModal.targetStatus}`;
    const activeNonce = lotActionNonces[key] || createSubmissionNonce('QC-LOTST');
    if (!lotActionNonces[key]) {
      setLotActionNonces((prev) => ({ ...prev, [key]: activeNonce }));
    }
    setLotTransitionSubmitting(true);
    setError(null);
    try {
      await updateLotStatus(
        lotActionModal.lotId,
        lotActionModal.targetStatus as any,
        lotActionModal.reason.trim() || undefined,
        activeNonce
      );
      clearAfterVerifiedResolution();
      setLotActionNonces((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setSuccessMsg(`Lot ${lotActionModal.lotId} quality_status updated to ${lotActionModal.targetStatus}.`);
      setLotActionModal(null);
      loadData();
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, `Update Lot ${lotActionModal.lotId}`);
      if (unknownInfo) {
        lockWithUnknownOutcome(unknownInfo);
      }
      setError(isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err instanceof Error ? err.message : String(err));
    } finally {
      setLotTransitionSubmitting(false);
    }
  };

  const handleViewMovements = async (lotId: string) => {
    setSelectedLotForMovement(lotId);
    try {
      const mList = await getLotMovements(lotId);
      setMovements(mList);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreateCheck = async (e: React.FormEvent) => {
    e.preventDefault();
    if (checkSubmitting || isOutcomeLocked) return;
    const activeNonce = checkNonce || createSubmissionNonce('QC-CHK');
    if (!checkNonce) setCheckNonce(activeNonce);
    setCheckSubmitting(true);
    setError(null);
    try {
      await createQualityCheck(newCheck, activeNonce);
      clearAfterVerifiedResolution();
      setCheckNonce('');
      setSuccessMsg('Quality inspection record submitted.');
      setShowCheckModal(false);
      loadData();
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, 'Record QC Check');
      if (unknownInfo) {
        lockWithUnknownOutcome(unknownInfo);
      }
      setError(isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err instanceof Error ? err.message : String(err));
    } finally {
      setCheckSubmitting(false);
    }
  };

  const handleCreateLot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (lotSubmitting || isOutcomeLocked) return;
    const activeNonce = lotNonce || createSubmissionNonce('QC-LOT');
    if (!lotNonce) setLotNonce(activeNonce);
    setLotSubmitting(true);
    setError(null);
    try {
      await createProductLot(newLot, activeNonce);
      clearAfterVerifiedResolution();
      setLotNonce('');
      setSuccessMsg(`Product Lot created for ${newLot.product_name}.`);
      setShowLotModal(false);
      loadData();
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, 'Create Product Lot');
      if (unknownInfo) {
        lockWithUnknownOutcome(unknownInfo);
      }
      setError(isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err instanceof Error ? err.message : String(err));
    } finally {
      setLotSubmitting(false);
    }
  };

  const handleCreateReturn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (returnSubmitting || isOutcomeLocked) return;
    const activeNonce = returnNonce || createSubmissionNonce('QC-RET');
    if (!returnNonce) setReturnNonce(activeNonce);
    setReturnSubmitting(true);
    setError(null);
    try {
      await createCustomerReturn(newReturn, activeNonce);
      clearAfterVerifiedResolution();
      setReturnNonce('');
      setSuccessMsg('Customer return registered. Goods placed under quarantine disposition.');
      setShowReturnModal(false);
      loadData();
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, 'Customer Return Intake');
      if (unknownInfo) {
        lockWithUnknownOutcome(unknownInfo);
      }
      setError(isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err instanceof Error ? err.message : String(err));
    } finally {
      setReturnSubmitting(false);
    }
  };

  const handleCreateComplaint = async (e: React.FormEvent) => {
    e.preventDefault();
    if (complaintSubmitting || isOutcomeLocked) return;
    const activeNonce = complaintNonce || createSubmissionNonce('QC-CMP');
    if (!complaintNonce) setComplaintNonce(activeNonce);
    setComplaintSubmitting(true);
    setError(null);
    try {
      await createComplaintOrRecall(newComplaint, activeNonce);
      clearAfterVerifiedResolution();
      setComplaintNonce('');
      setSuccessMsg(`${newComplaint.report_type} ticket registered for quality audit.`);
      setShowComplaintModal(false);
      loadData();
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, `Log ${newComplaint.report_type}`);
      if (unknownInfo) {
        lockWithUnknownOutcome(unknownInfo);
      }
      setError(isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err instanceof Error ? err.message : String(err));
    } finally {
      setComplaintSubmitting(false);
    }
  };

  const handleResolveComplaint = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!showResolveModal || resolveSubmitting || isOutcomeLocked) return;
    const activeNonce = resolveNonce || createSubmissionNonce('QC-CAPA');
    if (!resolveNonce) setResolveNonce(activeNonce);
    setResolveSubmitting(true);
    setError(null);
    try {
      await closeComplaint(showResolveModal.complaint_id, resolveForm, activeNonce);
      clearAfterVerifiedResolution();
      setResolveNonce('');
      setSuccessMsg(`Complaint ${showResolveModal.complaint_id} marked CLOSED with CAPA.`);
      setShowResolveModal(null);
      loadData();
    } catch (err: unknown) {
      const unknownInfo = extractUnknownOutcomeInfo(err, activeNonce, `Resolve Complaint ${showResolveModal.complaint_id}`);
      if (unknownInfo) {
        lockWithUnknownOutcome(unknownInfo);
      }
      setError(isUnknownOutcomeError(err) ? UNKNOWN_OUTCOME_MSG : err instanceof Error ? err.message : String(err));
    } finally {
      setResolveSubmitting(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 flex items-center gap-2">
            <ShieldCheck className="text-emerald-700" size={26} />
            Quality Control, Batch Lots & Traceability
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-0.5">
            Production lot inspection, quarantine hold, backward/forward traceability, and complaint management.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadData()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            Refresh
          </button>
          {activeTab === 'lots' && canManageQuality && (
            <button
              disabled={isOutcomeLocked}
              onClick={() => setShowLotModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 shadow-xs transition-colors disabled:opacity-50"
            >
              <Plus size={14} /> New Batch Lot
            </button>
          )}
          {activeTab === 'checks' && canSubmitCheck && (
            <button
              disabled={isOutcomeLocked}
              onClick={() => setShowCheckModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 shadow-xs transition-colors disabled:opacity-50"
            >
              <Plus size={14} /> Record QC Check
            </button>
          )}
          {activeTab === 'returns' && canManageQuality && (
            <button
              disabled={isOutcomeLocked}
              onClick={() => setShowReturnModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-amber-700 text-white hover:bg-amber-800 shadow-xs transition-colors disabled:opacity-50"
            >
              <Plus size={14} /> Log Customer Return
            </button>
          )}
          {activeTab === 'complaints' && canManageQuality && (
            <button
              disabled={isOutcomeLocked}
              onClick={() => setShowComplaintModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-red-700 text-white hover:bg-red-800 shadow-xs transition-colors disabled:opacity-50"
            >
              <Plus size={14} /> Log Complaint / Recall
            </button>
          )}
        </div>
      </div>

      <UnknownOutcomeBanner
        outcome={unknownOutcome}
        onConfirmedRecorded={async () => {
          clearAfterVerifiedResolution();
          setCheckNonce('');
          setLotNonce('');
          setReturnNonce('');
          setComplaintNonce('');
          setResolveNonce('');
          await loadData();
        }}
        onDismiss={clearAfterVerifiedResolution}
      />

      <fieldset
        disabled={isOutcomeLocked}
        data-tx-form-locked={isOutcomeLocked ? 'true' : 'false'}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
      >

      {isAuditor && (
        <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700 flex items-center gap-2">
          <ShieldAlert size={16} className="text-slate-500 shrink-0" />
          <span>Read-Only Audit Mode: Quality records, lot traceability, returns, and complaints are viewable for inspection only.</span>
        </div>
      )}

      {/* Notifications */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
            <X size={14} />
          </button>
        </div>
      )}
      {successMsg && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle size={16} className="shrink-0" />
            <span>{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-600 hover:text-emerald-800">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">QC Inspections</span>
            <ShieldCheck className="text-emerald-600" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-slate-900">{summary.total_checks}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Quarantined / Held Lots</span>
            <AlertOctagon className="text-amber-500" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-amber-700">{summary.quarantined_lots}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Customer Returns</span>
            <ArrowRightLeft className="text-blue-500" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-blue-700">{summary.open_returns}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Open Complaints & Recalls</span>
            <BadgeAlert className="text-red-500" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-red-700">{summary.open_complaints}</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200 flex items-center gap-2 overflow-x-auto">
        {[
          { key: 'lots', label: 'Product Lots & Traceability', icon: <Layers size={15} /> },
          { key: 'checks', label: 'QC Inspection Logs', icon: <CheckCircle size={15} /> },
          { key: 'returns', label: 'Customer Returns & Quarantine', icon: <ArrowRightLeft size={15} /> },
          { key: 'complaints', label: 'Complaints & Recalls', icon: <BadgeAlert size={15} /> },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveTab(tab.key as QualityTab);
              setSelectedLotForMovement(null);
            }}
            className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 whitespace-nowrap transition-colors ${
              activeTab === tab.key
                ? 'border-emerald-700 text-emerald-800 bg-emerald-50/50'
                : 'border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 1: Product Lots */}
      {activeTab === 'lots' && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
            <div className="p-4 border-b border-slate-200 flex items-center justify-between">
              <h2 className="text-sm font-bold text-slate-900">Finished Goods Lots & Release Control</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-600">
                <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                  <tr>
                    <th className="px-4 py-3">Lot Number</th>
                    <th className="px-4 py-3">Product Name</th>
                    <th className="px-4 py-3">Mfg Date</th>
                    <th className="px-4 py-3">Best Before</th>
                    <th className="px-4 py-3 text-right">Current Balance</th>
                    <th className="px-4 py-3">Quality Status</th>
                    <th className="px-4 py-3 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {lots.map((l) => (
                    <tr key={l.lot_id} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3 font-semibold text-slate-900">{l.lot_number}</td>
                      <td className="px-4 py-3">{l.product_name}</td>
                      <td className="px-4 py-3">{l.creation_date}</td>
                      <td className="px-4 py-3">{l.expiry_date || '6 Months'}</td>
                      <td className="px-4 py-3 text-right font-bold text-slate-900">
                        {l.current_quantity} {l.unit}s
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-full text-2xs font-bold ${
                            l.quality_status === 'RELEASED'
                              ? 'bg-emerald-100 text-emerald-800'
                              : l.quality_status === 'PENDING_QC'
                              ? 'bg-blue-100 text-blue-800'
                              : l.quality_status === 'ON_HOLD' || l.quality_status === 'QUARANTINE'
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {l.quality_status}
                        </span>
                        {l.hold_reason && (
                          <div className="text-2xs text-amber-700 mt-0.5 italic">{l.hold_reason}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center space-x-1.5 whitespace-nowrap">
                        {canManageQuality && l.quality_status !== 'RELEASED' && (
                          <button
                            type="button"
                            onClick={() => handleOpenLotTransition(l.lot_id, 'RELEASED')}
                            className="text-2xs font-semibold px-2 py-1 rounded-sm text-emerald-700 hover:bg-emerald-50 border border-emerald-300"
                          >
                            Release
                          </button>
                        )}
                        {canManageQuality && l.quality_status !== 'ON_HOLD' && (
                          <button
                            type="button"
                            onClick={() => handleOpenLotTransition(l.lot_id, 'ON_HOLD')}
                            className="text-2xs font-semibold px-2 py-1 rounded-sm text-amber-700 hover:bg-amber-50 border border-amber-300"
                          >
                            Hold
                          </button>
                        )}
                        {canManageQuality && l.quality_status !== 'REJECTED' && (
                          <button
                            type="button"
                            onClick={() => handleOpenLotTransition(l.lot_id, 'REJECTED')}
                            className="text-2xs font-semibold px-2 py-1 rounded-sm text-red-700 hover:bg-red-50 border border-red-300"
                          >
                            Reject
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleViewMovements(l.lot_id)}
                          className="text-2xs font-semibold text-blue-600 hover:underline ml-1"
                        >
                          Trace
                        </button>
                      </td>
                    </tr>
                  ))}
                  {lots.length === 0 && (
                    <tr>
                      <td colSpan={7} className="text-center py-8 text-slate-400">
                        No product lots registered yet. Click &quot;New Batch Lot&quot; to assign a traceable lot.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Traceability Audit Trail Panel */}
          {selectedLotForMovement && (
            <div className="bg-slate-900 text-white p-4 rounded-xl shadow-md space-y-3">
              <div className="flex items-center justify-between border-b border-slate-700 pb-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400">
                  Traceability Audit Trail — {selectedLotForMovement}
                </h3>
                <button
                  onClick={() => setSelectedLotForMovement(null)}
                  className="text-slate-400 hover:text-white"
                >
                  <X size={15} />
                </button>
              </div>
              <div className="space-y-1.5 text-xs">
                {movements.map((m) => (
                  <div key={m.movement_id} className="flex items-center justify-between py-1 border-b border-slate-800">
                    <div>
                      <span className="font-semibold text-emerald-300">{m.movement_type}</span>
                      <span className="text-slate-400 ml-2">{m.movement_date}</span>
                      <span className="text-slate-500 ml-2">({m.reference_type} #{m.reference_id})</span>
                    </div>
                    <div className="font-mono text-emerald-400">
                      {m.quantity > 0 ? `+${m.quantity}` : m.quantity} {m.unit}
                    </div>
                  </div>
                ))}
                {movements.length === 0 && (
                  <div className="text-slate-400 text-center py-3">No movements recorded for this lot.</div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Quality Checks */}
      {activeTab === 'checks' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Inspection & Quality Test Log</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Check #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Item / Lot</th>
                  <th className="px-4 py-3">Decision</th>
                  <th className="px-4 py-3">Observations</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {checks.map((c) => (
                  <tr key={c.check_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{c.check_number}</td>
                    <td className="px-4 py-3">{c.check_date}</td>
                    <td className="px-4 py-3">{c.check_type}</td>
                    <td className="px-4 py-3 font-medium text-slate-900">{c.item_name}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-2xs font-bold ${
                          c.decision === 'PASS'
                            ? 'bg-emerald-100 text-emerald-800'
                            : c.decision === 'HOLD'
                            ? 'bg-amber-100 text-amber-800'
                            : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {c.decision}
                      </span>
                    </td>
                    <td className="px-4 py-3">{c.defect_details || c.notes || '-'}</td>
                  </tr>
                ))}
                {checks.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-400">
                      No quality inspections recorded. Click &quot;Record QC Check&quot; to log batch inspections.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 3: Customer Returns */}
      {activeTab === 'returns' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Customer Returns & Quarantine Intake</h2>
              <p className="text-2xs text-slate-500 mt-0.5">
                Returned items are held under quarantine until approved disposition (SCRAP or RESTOCK).
              </p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Return #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Customer</th>
                  <th className="px-4 py-3">Disposition</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {returns.map((ret) => (
                  <tr key={ret.return_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{ret.return_number}</td>
                    <td className="px-4 py-3">{ret.return_date}</td>
                    <td className="px-4 py-3 font-medium text-slate-900">{ret.customer_name}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-2xs font-bold ${
                          ret.disposition === 'RESTOCK'
                            ? 'bg-emerald-100 text-emerald-800'
                            : ret.disposition === 'SCRAP'
                            ? 'bg-red-100 text-red-800'
                            : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {ret.disposition}
                      </span>
                    </td>
                    <td className="px-4 py-3">{ret.status}</td>
                    <td className="px-4 py-3">{ret.notes || '-'}</td>
                  </tr>
                ))}
                {returns.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-400">
                      No customer returns recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 4: Complaints & Recalls */}
      {activeTab === 'complaints' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Customer Complaints & Product Recalls</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Ticket #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Customer / Party</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {complaints.map((comp) => (
                  <tr key={comp.complaint_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{comp.complaint_id}</td>
                    <td className="px-4 py-3">{comp.report_date}</td>
                    <td className="px-4 py-3">
                      <span className="font-semibold text-slate-800">{comp.report_type}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-2xs font-bold ${
                          comp.severity === 'CRITICAL'
                            ? 'bg-red-200 text-red-900'
                            : comp.severity === 'HIGH'
                            ? 'bg-red-100 text-red-800'
                            : comp.severity === 'MEDIUM'
                            ? 'bg-amber-100 text-amber-800'
                            : 'bg-slate-100 text-slate-800'
                        }`}
                      >
                        {comp.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3">{comp.customer_name || '-'}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-2xs font-bold ${
                          comp.status === 'CLOSED'
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {comp.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {canCloseComplaint && comp.status !== 'CLOSED' && (
                        <button
                          onClick={() => setShowResolveModal(comp)}
                          className="text-2xs font-semibold px-2 py-1 rounded-sm bg-emerald-50 text-emerald-700 border border-emerald-300 hover:bg-emerald-100"
                        >
                          Resolve & Close
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {complaints.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-slate-400">
                      No complaints or recalls recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Modal: New QC Check */}
      {showCheckModal && (
        <FormLayout
          asModal
          title="Record Quality Control Inspection"
          subtitle="Mandatory quality check for raw materials, in-process dough/rolling, or finished lots"
          onClose={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowCheckModal(false); setCheckNonce(''); }}
          maxWidth="max-w-md"
        >
          <form onSubmit={handleCreateCheck} className="space-y-4">
            <FormField label="Check Type" required helpText="Select inspection stage">
              <SelectInput
                value={newCheck.check_type}
                onChange={(e) => setNewCheck({ ...newCheck, check_type: e.target.value as any })}
                options={[
                  { value: 'FINISHED_GOODS', label: 'Finished Goods Inspection' },
                  { value: 'IN_PROCESS', label: 'In-Process / Moisture & Rolling Test' },
                  { value: 'RAW_MATERIAL', label: 'Raw Material Inward Inspection' },
                ]}
              />
            </FormField>

            <FormField label="Item / Product Name" required helpText="Product variant or raw material identifier">
              <TextInput
                type="text"
                required
                value={newCheck.item_name}
                onChange={(e) => setNewCheck({ ...newCheck, item_name: e.target.value })}
              />
            </FormField>

            <FormField label="Inspection Decision" required helpText="Disposition based on laboratory standards">
              <SelectInput
                value={newCheck.decision}
                onChange={(e) => setNewCheck({ ...newCheck, decision: e.target.value as any })}
                options={[
                  { value: 'PASS', label: 'PASS — Compliant with quality standards' },
                  { value: 'HOLD', label: 'HOLD — Quarantine for lab re-test' },
                  { value: 'FAIL', label: 'FAIL — Reject / Non-conforming' },
                ]}
              />
            </FormField>

            <FormField label="Observation & Test Results" helpText="Specific measurements, moisture %, or defect reasons">
              <TextArea
                rows={2}
                value={newCheck.notes}
                onChange={(e) => setNewCheck({ ...newCheck, notes: e.target.value })}
                placeholder="e.g. Moisture within 11.2% limit, crispness passed"
              />
            </FormField>

            <FormActions>
              <CancelButton onClick={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowCheckModal(false); setCheckNonce(''); }} />
              <SaveButton label="Submit Inspection" variant="primary" isLoading={checkSubmitting} />
            </FormActions>
          </form>
        </FormLayout>
      )}

      {/* Modal: New Lot */}
      {showLotModal && (
        <FormLayout
          asModal
          title="Create Traceable Product Lot"
          subtitle="Generate batch identifier and expiry tracker for finished goods inventory"
          onClose={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowLotModal(false); setLotNonce(''); }}
          maxWidth="max-w-md"
        >
          <form onSubmit={handleCreateLot} className="space-y-4">
            <FormField label="Product Catalogue Item" required helpText="Select an active product from the live catalogue">
              {products.length > 0 ? (
                <SelectInput
                  value={newLot.product_id}
                  required
                  onChange={(e) => {
                    const id = e.target.value;
                    const match = products.find((p) => p.product_id === id);
                    setNewLot({
                      ...newLot,
                      product_id: id,
                      product_name: match ? match.product_name : '',
                    });
                  }}
                  options={[
                    { value: '', label: 'Select a product…' },
                    ...products.map((p) => ({
                      value: p.product_id,
                      label: `${p.product_name} (${p.sku})`,
                    })),
                  ]}
                />
              ) : (
                <TextInput
                  type="text"
                  required
                  value={newLot.product_id}
                  onChange={(e) => setNewLot({ ...newLot, product_id: e.target.value, product_name: e.target.value })}
                  placeholder="Enter Product ID (e.g. PRD-000001)"
                />
              )}
            </FormField>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <FormField label="Batch Packets" required helpText="Number of packaged units">
                <TextInput
                  type="number"
                  min="1"
                  required
                  value={newLot.initial_quantity}
                  onChange={(e) => setNewLot({ ...newLot, initial_quantity: Number(e.target.value) })}
                />
              </FormField>

              <FormField label="Expiry Date" helpText="Recommended shelf life">
                <DateInput
                  value={newLot.expiry_date}
                  onChange={(val) => setNewLot({ ...newLot, expiry_date: val })}
                />
              </FormField>
            </div>

            <FormActions>
              <CancelButton onClick={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowLotModal(false); setLotNonce(''); }} />
              <SaveButton label="Generate Lot" variant="primary" isLoading={lotSubmitting} />
            </FormActions>
          </form>
        </FormLayout>
      )}

      {/* Modal: Customer Return */}
      {showReturnModal && (
        <FormLayout
          asModal
          title="Intake Customer Return (Quarantine)"
          subtitle="Record goods received back from distributors or retail partners"
          onClose={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowReturnModal(false); setReturnNonce(''); }}
          maxWidth="max-w-md"
        >
          <form onSubmit={handleCreateReturn} className="space-y-4">
            <FormField label="Customer / Shop" required helpText="Select returning customer from live directory">
              {customers.length > 0 ? (
                <SelectInput
                  value={newReturn.customer_id}
                  required
                  onChange={(e) => {
                    const cid = e.target.value;
                    const match = customers.find((c) => c.customer_id === cid);
                    setNewReturn({
                      ...newReturn,
                      customer_id: cid,
                      customer_name: match ? match.shop_name : '',
                    });
                  }}
                  options={[
                    { value: '', label: 'Select customer…' },
                    ...customers.map((c) => ({
                      value: c.customer_id,
                      label: `${c.shop_name} (${c.customer_id})`,
                    })),
                  ]}
                />
              ) : (
                <TextInput
                  type="text"
                  required
                  value={newReturn.customer_name}
                  onChange={(e) => setNewReturn({ ...newReturn, customer_name: e.target.value })}
                  placeholder="Enter customer / shop name"
                />
              )}
            </FormField>

            <FormField label="Returned Product" required helpText="Select returned SKU from live catalogue">
              {products.length > 0 ? (
                <SelectInput
                  value={newReturn.items[0].product_id}
                  required
                  onChange={(e) => {
                    const pid = e.target.value;
                    const match = products.find((p) => p.product_id === pid);
                    const updated = [...newReturn.items];
                    updated[0] = {
                      ...updated[0],
                      product_id: pid,
                      sku: match?.sku || '',
                      product_name: match?.product_name || '',
                    };
                    setNewReturn({ ...newReturn, items: updated });
                  }}
                  options={[
                    { value: '', label: 'Select product…' },
                    ...products.map((p) => ({
                      value: p.product_id,
                      label: `${p.product_name} (${p.sku})`,
                    })),
                  ]}
                />
              ) : (
                <TextInput
                  type="text"
                  required
                  value={newReturn.items[0].product_id}
                  onChange={(e) => {
                    const updated = [...newReturn.items];
                    updated[0] = { ...updated[0], product_id: e.target.value, sku: e.target.value, product_name: e.target.value };
                    setNewReturn({ ...newReturn, items: updated });
                  }}
                  placeholder="Enter Product ID"
                />
              )}
            </FormField>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <FormField label="Packets Returned" required helpText="Count of returned units">
                <TextInput
                  type="number"
                  min="1"
                  required
                  value={newReturn.items[0].quantity}
                  onChange={(e) => {
                    const updated = [...newReturn.items];
                    updated[0].quantity = Number(e.target.value);
                    setNewReturn({ ...newReturn, items: updated });
                  }}
                />
              </FormField>

              <FormField label="Disposition" required helpText="Initial warehouse quarantine status">
                <SelectInput
                  value={newReturn.disposition}
                  onChange={(e) => setNewReturn({ ...newReturn, disposition: e.target.value as any })}
                  options={[
                    { value: 'PENDING_INSPECTION', label: 'Hold in Quarantine' },
                    { value: 'SCRAP', label: 'Scrap / Write-off' },
                    { value: 'RESTOCK', label: 'Restock (Inspected OK)' },
                  ]}
                />
              </FormField>
            </div>

            <FormField label="Return Reason" required helpText="Customer feedback or reason for return">
              <TextInput
                type="text"
                required
                value={newReturn.items[0].reason}
                onChange={(e) => {
                  const val = e.target.value;
                  const updated = [...newReturn.items];
                  updated[0].reason = val;
                  setNewReturn({ ...newReturn, notes: val, items: updated });
                }}
                placeholder="e.g. Outer carton damaged during transit"
              />
            </FormField>

            <FormActions>
              <CancelButton onClick={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowReturnModal(false); setReturnNonce(''); }} />
              <SaveButton label="Accept Return to Quarantine" variant="primary" isLoading={returnSubmitting} />
            </FormActions>
          </form>
        </FormLayout>
      )}

      {/* Modal: Complaint / Recall */}
      {showComplaintModal && (
        <FormLayout
          asModal
          title="Log Quality Complaint / Recall"
          subtitle="Register customer defect escalation or initiate batch recall protocol"
          onClose={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowComplaintModal(false); setComplaintNonce(''); }}
          maxWidth="max-w-md"
        >
          <form onSubmit={handleCreateComplaint} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <FormField label="Ticket Type" helpText="Complaint vs formal recall">
                <SelectInput
                  value={newComplaint.report_type}
                  onChange={(e) => setNewComplaint({ ...newComplaint, report_type: e.target.value as any })}
                  options={[
                    { value: 'COMPLAINT', label: 'Customer Complaint' },
                    { value: 'RECALL', label: 'Product Recall Notice' },
                  ]}
                />
              </FormField>

              <FormField label="Severity" helpText="Risk level to consumer">
                <SelectInput
                  value={newComplaint.severity}
                  onChange={(e) => setNewComplaint({ ...newComplaint, severity: e.target.value as any })}
                  options={[
                    { value: 'LOW', label: 'Low' },
                    { value: 'MEDIUM', label: 'Medium' },
                    { value: 'HIGH', label: 'High' },
                    { value: 'CRITICAL', label: 'Critical' },
                  ]}
                />
              </FormField>
            </div>

            <FormField label="Customer / Complainant" helpText="Contact person or shopkeeper">
              <TextInput
                type="text"
                value={newComplaint.customer_name}
                onChange={(e) => setNewComplaint({ ...newComplaint, customer_name: e.target.value })}
                placeholder="e.g. Shri Krishna Supermarket"
              />
            </FormField>

            <FormField label="Defect Description" required helpText="Describe defect, off-taste, packaging leak, etc.">
              <TextArea
                rows={3}
                required
                value={newComplaint.description}
                onChange={(e) => setNewComplaint({ ...newComplaint, description: e.target.value })}
                placeholder="Detailed explanation of the issue reported by the customer…"
              />
            </FormField>

            <FormActions>
              <CancelButton onClick={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowComplaintModal(false); setComplaintNonce(''); }} />
              <SaveButton label="Submit Ticket" variant="danger" isLoading={complaintSubmitting} />
            </FormActions>
          </form>
        </FormLayout>
      )}

      {/* Modal: Resolve Complaint */}
      {showResolveModal && (
        <FormLayout
          asModal
          title={`Resolve Complaint ${showResolveModal.complaint_id}`}
          subtitle="Document root cause and preventive actions (CAPA) before formal closure"
          onClose={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowResolveModal(null); setResolveNonce(''); }}
          maxWidth="max-w-md"
        >
          <form onSubmit={handleResolveComplaint} className="space-y-4">
            <FormField label="Root Cause & Investigation" required helpText="Why did the defect occur in the batch?">
              <TextArea
                rows={2}
                required
                value={resolveForm.investigation}
                onChange={(e) => setResolveForm({ ...resolveForm, investigation: e.target.value })}
                placeholder="Investigation findings…"
              />
            </FormField>

            <FormField label="Corrective & Preventive Action (CAPA)" required helpText="Action taken to prevent recurrence">
              <TextArea
                rows={2}
                required
                value={resolveForm.corrective_action}
                onChange={(e) => setResolveForm({ ...resolveForm, corrective_action: e.target.value })}
                placeholder="Preventive steps implemented…"
              />
            </FormField>

            <FormActions>
              <CancelButton onClick={() => { if (shouldBlockDraftNonceReset(unknownOutcome)) return; setShowResolveModal(null); setResolveNonce(''); }} />
              <SaveButton label="Close Ticket with CAPA" variant="primary" isLoading={resolveSubmitting} />
            </FormActions>
          </form>
        </FormLayout>
      )}

      {/* Modal: Lot Quality Transition (RELEASED / ON_HOLD / REJECTED) */}
      {lotActionModal && (
        <FormLayout
          asModal
          title={`Update Lot ${lotActionModal.lotId} → ${lotActionModal.targetStatus}`}
          subtitle="Lot Quality State Machine: PENDING_QC → RELEASED / ON_HOLD / REJECTED"
          onClose={() => {
            if (shouldBlockDraftNonceReset(unknownOutcome)) return;
            const key = `${lotActionModal.lotId}:${lotActionModal.targetStatus}`;
            setLotActionNonces((prev) => {
              const next = { ...prev };
              delete next[key];
              return next;
            });
            setLotActionModal(null);
          }}
          maxWidth="max-w-md"
        >
          <form onSubmit={handleConfirmLotTransition} className="space-y-4">
            <FormField
              label="QC Decision Reason / Inspection Note"
              required={lotActionModal.targetStatus !== 'RELEASED'}
              helpText="Required when placing lot ON_HOLD or marking REJECTED"
            >
              <TextArea
                rows={3}
                required={lotActionModal.targetStatus !== 'RELEASED'}
                value={lotActionModal.reason}
                onChange={(e) =>
                  setLotActionModal({ ...lotActionModal, reason: e.target.value })
                }
                placeholder="Enter QC inspection remarks or hold/rejection reason…"
              />
            </FormField>
            <FormActions>
              <CancelButton
                onClick={() => {
                  if (shouldBlockDraftNonceReset(unknownOutcome)) return;
                  const key = `${lotActionModal.lotId}:${lotActionModal.targetStatus}`;
                  setLotActionNonces((prev) => {
                    const next = { ...prev };
                    delete next[key];
                    return next;
                  });
                  setLotActionModal(null);
                }}
              />
              <SaveButton
                label={`Confirm ${lotActionModal.targetStatus}`}
                variant={lotActionModal.targetStatus === 'REJECTED' ? 'danger' : 'primary'}
                isLoading={lotTransitionSubmitting}
              />
            </FormActions>
          </form>
        </FormLayout>
      )}
      </fieldset>
    </div>
  );
};
