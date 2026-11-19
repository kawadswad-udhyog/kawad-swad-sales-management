import React, { useState, useEffect, useCallback } from 'react';
import {
  Truck,
  Store,
  ShieldCheck,
  Sliders,
  AlertTriangle,
  RefreshCw,
  CheckCircle2,
  Clock,
  Lock,
  Search,
  ChevronLeft,
  ChevronRight,
  Wrench,
  Briefcase,
  Wallet,
  Database,
  FileWarning,
} from 'lucide-react';
import { useStore } from '../context/StoreContext';
import { PageHeader } from '../components/common/PageHeader';
import {
  apiRequest,
  createSubmissionNonce,
  fetchV2Collection,
  fetchV2SchemaRegistry,
  postV2GovernedAction,
  updateV2Policy,
  isUnknownOutcomeError,
  isBlockedOwnerSetupError,
  classifySchemaStatusBadge,
  ApiHttpError,
  ApiOutcomeUnknownError,
  UNKNOWN_OUTCOME_STANDARD_MSG,
} from '../services/api';
import { UnknownOutcomeBanner } from '../components/common/UnknownOutcomeBanner';
import { resolveCanonical12Role } from '../utils/permissions';
import type {
  PaginatedV2Response,
  PendingCaPolicy,
  ProductLot,
  SchemaRegistryPayload,
} from '../types';

export type HubModuleType =
  | 'logistics'
  | 'channels'
  | 'compliance_assets'
  | 'control_policies';

interface ErpOperationsHubViewProps {
  initialModule: HubModuleType;
}

interface SubmissionStatusBanner {
  state: 'CONFIRMED' | 'NOT_SAVED' | 'PENDING_UNKNOWN' | 'BLOCKED_PENDING_OWNER_SETUP';
  message: string;
  nonce?: string;
  correlationId?: string;
}

const MODULE_META: Record<
  HubModuleType,
  { title: string; subtitle: string; kicker: string; icon: React.ReactNode }
> = {
  logistics: {
    title: 'Logistics & Quality-Gated Dispatch',
    subtitle: 'Route dispatches, van loading verification & strict RELEASED-lot gate',
    kicker: 'Blueprint v2.1 · Group 09 (Distribution & Logistics)',
    icon: <Truck size={20} />,
  },
  channels: {
    title: 'E-Commerce & Channel Settlements',
    subtitle: 'Marketplace settlements, fee reconciliation & CA-approved GST posting',
    kicker: 'Blueprint v2.1 · Group 08 (Channel, Marketplace & Marketing)',
    icon: <Store size={20} />,
  },
  compliance_assets: {
    title: 'Compliance, Assets, Gig Work & Advances',
    subtitle: 'FSSAI/statutory compliance, machinery maintenance, gig piece-rate workflow & confidential advances',
    kicker: 'Blueprint v2.1 · Groups 12 & 13 (Compliance, Assets & Risk)',
    icon: <ShieldCheck size={20} />,
  },
  control_policies: {
    title: 'Policies, Schema Registry & Control Logs',
    subtitle: 'Pending CA/Owner approvals, Apps Script Single-Write-Owner gateway, 255-tab architecture & audit logs',
    kicker: 'Blueprint v2.1 · Group 00 (System Control & Governance)',
    icon: <Sliders size={20} />,
  },
};

export const ErpOperationsHubView: React.FC<ErpOperationsHubViewProps> = ({
  initialModule,
}) => {
  const {
    currentUser,
    products,
    users,
    capabilities,
    refreshCapabilities,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
    appsScriptBridgeConfigured,
  } = useStore();

  const canonicalRole = resolveCanonical12Role(currentUser?.role);
  const isOwnerAdmin = canonicalRole === 'OWNER_ADMIN';
  const canViewAdvances = canonicalRole === 'OWNER_ADMIN' || canonicalRole === 'ACCOUNTS';
  const isAuditor = canonicalRole === 'AUDITOR';

  const [moduleTab, setModuleTab] = useState<HubModuleType>(initialModule);
  useEffect(() => {
    setModuleTab(initialModule);
  }, [initialModule]);

  // Compliance/Assets sub-tab state
  const [complianceSubTab, setComplianceSubTab] = useState<
    'compliance' | 'assets' | 'gig' | 'advances'
  >('compliance');

  // Shared list/pagination state
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [collection, setCollection] = useState<PaginatedV2Response | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // Additional control & reference data
  const [schemaRegistry, setSchemaRegistry] = useState<SchemaRegistryPayload | null>(null);
  const [controlSubTab, setControlSubTab] = useState<'policies' | 'schema' | 'audit' | 'exceptions'>('policies');
  const [lots, setLots] = useState<ProductLot[]>([]);

  // Per-module status banner & loading state
  const [submitting, setSubmitting] = useState(false);
  const [banner, setBanner] = useState<SubmissionStatusBanner | null>(null);

  // ---------------- Logistics Dispatch Draft (Stable Nonce) ----------------
  const [dispatchNonce, setDispatchNonce] = useState<string | null>(null);
  const [dispatchForm, setDispatchForm] = useState({
    dispatch_date: new Date().toISOString().slice(0, 10),
    product_id: '',
    lot_id: '',
    channel: 'VAN_ROUTE' as
      | 'WAREHOUSE'
      | 'VAN_ROUTE'
      | 'DISTRIBUTOR'
      | 'WHOLESALE'
      | 'RETAIL'
      | 'ECOMMERCE',
    destination: '',
    van_number: '',
    salesman_user_id: '',
    quantity_packets: 1,
    notes: '',
  });

  // ---------------- Marketplace Settlement Draft (Stable Nonce) ----------------
  const [settlementNonce, setSettlementNonce] = useState<string | null>(null);
  const [settlementForm, setSettlementForm] = useState({
    channel_name: 'Amazon',
    settlement_ref: '',
    settlement_date: new Date().toISOString().slice(0, 10),
    gross_sales_amount: '0.00',
    marketplace_fees: '0.00',
    net_settlement_amount: '0.00',
    apply_automated_gst_posting: false,
    notes: '',
  });

  // ---------------- Compliance Draft (Stable Nonce) ----------------
  const [complianceNonce, setComplianceNonce] = useState<string | null>(null);
  const [complianceForm, setComplianceForm] = useState({
    record_type: 'FSSAI_AUDIT' as
      | 'FSSAI_AUDIT'
      | 'HYGIENE_LOG'
      | 'STATUTORY_FILING'
      | 'EQUIPMENT_CALIBRATION'
      | 'CORRECTIVE_ACTION',
    title: '',
    due_date: new Date().toISOString().slice(0, 10),
    status: 'OPEN' as 'OPEN' | 'VERIFIED' | 'EXPIRED',
    notes: '',
  });

  // ---------------- Assets Maintenance Draft (Stable Nonce) ----------------
  const [assetNonce, setAssetNonce] = useState<string | null>(null);
  const [assetForm, setAssetForm] = useState({
    asset_code: '',
    asset_name: '',
    maintenance_type: 'PREVENTIVE' as 'PREVENTIVE' | 'BREAKDOWN' | 'INSPECTION',
    cost_amount: '0.00',
    scheduled_date: new Date().toISOString().slice(0, 10),
    notes: '',
  });

  // ---------------- Gig Work Entry Draft (Stable Nonce) ----------------
  const [gigNonce, setGigNonce] = useState<string | null>(null);
  const [gigForm, setGigForm] = useState({
    worker_id: '',
    work_date: new Date().toISOString().slice(0, 10),
    batch_id: '',
    activity_name: '',
    units_completed: '1',
    unit_of_measure: 'KG' as 'KG' | 'SHIFT' | 'PACKET' | 'HOUR',
    piece_rate: '0.00',
    notes: '',
  });
  const [gigActionNonces, setGigActionNonces] = useState<Record<string, string>>({});

  // ---------------- Approved Advance Disbursement Nonces ----------------
  const [advanceMethod, setAdvanceMethod] = useState<'BANK_TRANSFER' | 'UPI' | 'CASH'>('BANK_TRANSFER');
  const [advanceRefs, setAdvanceRefs] = useState<Record<string, string>>({});
  const [advanceActionNonces, setAdvanceActionNonces] = useState<Record<string, string>>({});

  // ---------------- Policy Draft Edits (OWNER_ADMIN) ----------------
  const [policyDrafts, setPolicyDrafts] = useState<
    Record<string, { status: 'APPROVED' | 'PENDING_CA_APPROVAL'; value: string; notes: string }>
  >({});
  const [policyNonces, setPolicyNonces] = useState<Record<string, string>>({});

  const resolveCollectionEndpoint = useCallback((): string | null => {
    if (moduleTab === 'logistics') return '/api/v2/logistics/dispatches';
    if (moduleTab === 'channels') return '/api/v2/channels/settlements';
    if (moduleTab === 'compliance_assets') {
      if (complianceSubTab === 'compliance') return '/api/v2/compliance/records';
      if (complianceSubTab === 'assets') return '/api/v2/assets/maintenance';
      if (complianceSubTab === 'gig') return '/api/v2/workforce/gig-entries';
      if (complianceSubTab === 'advances') return canViewAdvances ? '/api/v2/workforce/advances' : null;
    }
    if (moduleTab === 'control_policies') {
      if (controlSubTab === 'audit') return '/api/v2/control/audit-logs';
      if (controlSubTab === 'exceptions') return '/api/v2/control/exceptions';
    }
    return null;
  }, [moduleTab, complianceSubTab, controlSubTab, canViewAdvances]);

  const loadCollection = useCallback(async () => {
    const endpoint = resolveCollectionEndpoint();
    if (!endpoint) {
      setCollection(null);
      setListError(null);
      return;
    }
    setListLoading(true);
    setListError(null);
    try {
      const res = await fetchV2Collection(endpoint, { page, page_size: 20, search: search.trim() || undefined });
      setCollection(res);
    } catch (err: unknown) {
      setCollection(null);
      setListError(err instanceof Error ? err.message : 'Unable to load records from Google Sheets.');
    } finally {
      setListLoading(false);
    }
  }, [resolveCollectionEndpoint, page, search]);

  useEffect(() => {
    setPage(1);
  }, [moduleTab, complianceSubTab, controlSubTab]);

  useEffect(() => {
    loadCollection();
  }, [loadCollection]);

  useEffect(() => {
    if (moduleTab === 'logistics') {
      apiRequest<ProductLot[]>('/api/quality/lots')
        .then((res) => setLots(Array.isArray(res) ? res : []))
        .catch(() => setLots([]));
    }
    if (moduleTab === 'control_policies') {
      refreshCapabilities().catch(() => {});
      fetchV2SchemaRegistry()
        .then((res) => setSchemaRegistry(res))
        .catch(() => setSchemaRegistry(null));
    }
  }, [moduleTab, refreshCapabilities]);

  const handleGovernedError = (err: unknown, nonce: string) => {
    if (isUnknownOutcomeError(err)) {
      const correlationId =
        err instanceof ApiOutcomeUnknownError || err instanceof ApiHttpError
          ? err.correlationId
          : undefined;
      setBanner({
        state: 'PENDING_UNKNOWN',
        nonce,
        correlationId,
        message: UNKNOWN_OUTCOME_STANDARD_MSG,
      });
      return;
    }
    if (err instanceof ApiHttpError) {
      if (isBlockedOwnerSetupError(err)) {
        setBanner({
          state: 'BLOCKED_PENDING_OWNER_SETUP',
          nonce,
          correlationId: err.correlationId,
          message: `${err.message} (Write blocked by backend — inputs preserved, NOT SAVED.)`,
        });
        return;
      }
      setBanner({
        state: 'NOT_SAVED',
        nonce,
        correlationId: err.correlationId,
        message: `${err.message} — Record NOT SAVED. Inputs are preserved for review/retry.`,
      });
      return;
    }
    setBanner({
      state: 'NOT_SAVED',
      nonce,
      message: `${err instanceof Error ? err.message : 'Submission failed'} — Record NOT SAVED.`,
    });
  };

  const handleDispatchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const activeNonce = dispatchNonce || createSubmissionNonce('MOV');
    if (!dispatchNonce) setDispatchNonce(activeNonce);
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await postV2GovernedAction('/api/v2/logistics/dispatches', {
        ...dispatchForm,
        quantity_packets: Number(dispatchForm.quantity_packets),
        nonce: activeNonce,
      });
      setDispatchNonce(null);
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Dispatch confirmed (${res.allocated_id || activeNonce}).`,
      });
      setDispatchForm((prev) => ({
        ...prev,
        destination: '',
        van_number: '',
        notes: '',
        quantity_packets: 1,
      }));
      loadCollection();
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSettlementSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const activeNonce = settlementNonce || createSubmissionNonce('STL');
    if (!settlementNonce) setSettlementNonce(activeNonce);
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await postV2GovernedAction('/api/v2/channels/settlements', {
        ...settlementForm,
        nonce: activeNonce,
      });
      setSettlementNonce(null);
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Marketplace settlement recorded (${res.allocated_id || activeNonce}).`,
      });
      setSettlementForm((prev) => ({ ...prev, settlement_ref: '', notes: '' }));
      loadCollection();
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const handleComplianceSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const activeNonce = complianceNonce || createSubmissionNonce('STAT');
    if (!complianceNonce) setComplianceNonce(activeNonce);
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await postV2GovernedAction('/api/v2/compliance/records', {
        ...complianceForm,
        nonce: activeNonce,
      });
      setComplianceNonce(null);
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Compliance record confirmed (${res.allocated_id || activeNonce}).`,
      });
      setComplianceForm((prev) => ({ ...prev, title: '', notes: '' }));
      loadCollection();
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAssetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const activeNonce = assetNonce || createSubmissionNonce('MAINT');
    if (!assetNonce) setAssetNonce(activeNonce);
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await postV2GovernedAction('/api/v2/assets/maintenance', {
        ...assetForm,
        nonce: activeNonce,
      });
      setAssetNonce(null);
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Maintenance entry confirmed (${res.allocated_id || activeNonce}).`,
      });
      setAssetForm((prev) => ({ ...prev, asset_code: '', asset_name: '', cost_amount: '0.00', notes: '' }));
      loadCollection();
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const handleGigSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const activeNonce = gigNonce || createSubmissionNonce('PWE');
    if (!gigNonce) setGigNonce(activeNonce);
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await postV2GovernedAction('/api/v2/workforce/gig-entries', {
        ...gigForm,
        nonce: activeNonce,
      });
      setGigNonce(null);
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Gig work entry submitted in SUBMITTED status (${res.allocated_id || activeNonce}).`,
      });
      setGigForm((prev) => ({ ...prev, activity_name: '', notes: '' }));
      loadCollection();
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const handleGigTransition = async (entryId: string, action: 'verify' | 'pay') => {
    const key = `${entryId}:${action}`;
    const activeNonce = gigActionNonces[key] || createSubmissionNonce('PWE');
    setGigActionNonces((prev) => ({ ...prev, [key]: activeNonce }));
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await postV2GovernedAction(`/api/v2/workforce/gig-entries/${encodeURIComponent(entryId)}/${action}`, {
        nonce: activeNonce,
        payment_method: action === 'pay' ? 'CASH' : undefined,
        notes: `${action.toUpperCase()} action`,
      });
      setGigActionNonces((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Gig entry ${entryId} transitioned via ${action.toUpperCase()}.`,
      });
      loadCollection();
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAdvanceDisburse = async (advanceId: string) => {
    const ref = (advanceRefs[advanceId] || '').trim();
    if (!ref) {
      setBanner({
        state: 'NOT_SAVED',
        message: 'Payment reference number is required to disburse an approved advance.',
      });
      return;
    }
    const activeNonce = advanceActionNonces[advanceId] || createSubmissionNonce('EADV');
    setAdvanceActionNonces((prev) => ({ ...prev, [advanceId]: activeNonce }));
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await postV2GovernedAction(`/api/v2/workforce/advances/${encodeURIComponent(advanceId)}/disburse`, {
        nonce: activeNonce,
        payment_method: advanceMethod,
        payment_reference: ref,
        notes: 'Disbursed against approved advance',
      });
      setAdvanceActionNonces((prev) => {
        const next = { ...prev };
        delete next[advanceId];
        return next;
      });
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Approved advance ${advanceId} disbursed.`,
      });
      loadCollection();
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSavePolicy = async (policy: PendingCaPolicy) => {
    const draft = policyDrafts[policy.policy_key] || {
      status: (policy.status === 'APPROVED' ? 'APPROVED' : 'PENDING_CA_APPROVAL') as 'APPROVED' | 'PENDING_CA_APPROVAL',
      value: policy.value || (policy.allowed_values?.[0] || ''),
      notes: policy.notes || '',
    };
    const activeNonce = policyNonces[policy.policy_key] || createSubmissionNonce('POL');
    setPolicyNonces((prev) => ({ ...prev, [policy.policy_key]: activeNonce }));
    setSubmitting(true);
    setBanner(null);
    try {
      const res = await updateV2Policy(policy.policy_key, {
        status: draft.status,
        value: draft.value,
        notes: draft.notes,
        nonce: activeNonce,
      });
      setPolicyNonces((prev) => {
        const next = { ...prev };
        delete next[policy.policy_key];
        return next;
      });
      await refreshCapabilities();
      setBanner({
        state: 'CONFIRMED',
        nonce: activeNonce,
        correlationId: res.correlation_id,
        message: `Policy '${policy.policy_key}' updated to ${draft.status} (${draft.value || 'unset'}).`,
      });
    } catch (err) {
      handleGovernedError(err, activeNonce);
    } finally {
      setSubmitting(false);
    }
  };

  const meta = MODULE_META[moduleTab];
  const bridgeReady = Boolean(appsScriptBridgeConfigured || capabilities?.apps_script_bridge_configured);
  const writesLocked =
    isAuditor ||
    !isBackendConnected ||
    !isGoogleSheetsConnected ||
    !persistentWritesEnabled ||
    !bridgeReady;
  const policiesMap = capabilities?.pending_ca_policies || {};
  const policyList = Object.values(policiesMap);
  const releasedLots = lots.filter((l) => String(l.quality_status || '').toUpperCase() === 'RELEASED');
  const blockedLots = lots.filter((l) => String(l.quality_status || '').toUpperCase() !== 'RELEASED');

  const items = collection?.items || [];
  const totalPages = collection?.total_pages || 1;
  const totalCount = collection?.total || 0;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <PageHeader
        title={meta.title}
        subtitle={meta.subtitle}
        kicker={meta.kicker}
        icon={meta.icon}
        actions={
          <button
            type="button"
            onClick={() => loadCollection()}
            disabled={listLoading}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 rounded-lg text-xs font-semibold text-slate-700 flex items-center gap-1.5 cursor-pointer"
          >
            <RefreshCw size={14} className={listLoading ? 'animate-spin' : ''} />
            <span>Refresh Data</span>
          </button>
        }
      />

      {/* Fail-Closed Infrastructure Warning */}
      {(!isBackendConnected || !isGoogleSheetsConnected || !bridgeReady) && (
        <div className="bg-amber-50 border border-amber-300 rounded-xl p-4 text-xs text-amber-950 flex items-start gap-3">
          <Lock size={18} className="text-amber-700 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-bold uppercase tracking-wider text-[11px] text-amber-800">
              Fail-Closed Write Governance Status
            </div>
            <div>
              {!isBackendConnected || !isGoogleSheetsConnected
                ? 'Backend API or Google Sheets connection is unavailable. Data shown below (if any) cannot be supplemented by fabricated local data.'
                : 'Apps Script Single-Write-Owner gateway is not yet configured in environment (`BLOCKED_PENDING_OWNER_SETUP`). Governed mutations will fail closed cleanly and preserve your draft nonce without fabricating saves.'}
            </div>
          </div>
        </div>
      )}

      {/* Submission Outcome Banner */}
      {banner?.state === 'PENDING_UNKNOWN' && (
        <UnknownOutcomeBanner
          outcome={{
            nonce: banner.nonce || '',
            correlationId: banner.correlationId,
            message: banner.message,
            actionLabel: meta.title,
          }}
          onConfirmedRecorded={(statusRes) => {
            setBanner({
              state: 'CONFIRMED',
              nonce: banner.nonce,
              correlationId: statusRes.correlation_id || banner.correlationId,
              message: `Transaction confirmed recorded in Google Sheets (${statusRes.allocated_id || banner.nonce}).`,
            });
            loadCollection();
          }}
          onDismiss={() => setBanner(null)}
        />
      )}
      {banner && banner.state !== 'PENDING_UNKNOWN' && (
        <div
          className={`rounded-xl p-4 border text-xs flex items-start justify-between gap-3 ${
            banner.state === 'CONFIRMED'
              ? 'bg-emerald-50 border-emerald-300 text-emerald-950'
              : 'bg-red-50 border-red-300 text-red-950'
          }`}
        >
          <div className="flex items-start gap-2.5">
            {banner.state === 'CONFIRMED' ? (
              <CheckCircle2 size={18} className="text-emerald-700 shrink-0 mt-0.5" />
            ) : (
              <AlertTriangle size={18} className="text-red-700 shrink-0 mt-0.5" />
            )}
            <div className="space-y-1">
              <div className="font-bold uppercase tracking-wider text-[11px]">
                {banner.state === 'CONFIRMED'
                  ? 'CONFIRMED'
                  : banner.state === 'BLOCKED_PENDING_OWNER_SETUP'
                  ? 'BLOCKED_PENDING_OWNER_SETUP (NOT SAVED)'
                  : 'NOT SAVED'}
              </div>
              <div>{banner.message}</div>
              {(banner.nonce || banner.correlationId) && (
                <div className="text-[11px] font-mono opacity-80">
                  {banner.nonce ? `Nonce: ${banner.nonce} ` : ''}
                  {banner.correlationId ? `· Correlation: ${banner.correlationId}` : ''}
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setBanner(null)}
            className="text-xs font-semibold underline shrink-0 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* LOGISTICS MODULE */}
      {moduleTab === 'logistics' && (
        <div className="space-y-6">
          {!isAuditor && (
            <form
              onSubmit={handleDispatchSubmit}
              onChange={() => {
                if (!dispatchNonce) return;
              }}
              className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4"
            >
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h2 className="text-sm font-bold text-slate-900 m-0">
                    Record Quality-Gated Dispatch
                  </h2>
                  <p className="text-xs text-slate-500 mt-0.5 m-0">
                    Strict Rule: Only <span className="font-bold text-emerald-700">RELEASED</span> ProductLots may be dispatched. ({releasedLots.length} released, {blockedLots.length} pending/hold/rejected)
                  </p>
                </div>
                {dispatchNonce && (
                  <span className="px-2.5 py-1 rounded bg-amber-100 text-amber-900 font-mono text-[11px] font-bold">
                    Draft Nonce Active: {dispatchNonce}
                  </span>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                <label className="block">
                  <span className="font-semibold text-slate-700">Dispatch Date</span>
                  <input
                    type="date"
                    required
                    value={dispatchForm.dispatch_date}
                    onChange={(e) => {
                      setDispatchNonce(null);
                      setDispatchForm({ ...dispatchForm, dispatch_date: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Product SKU</span>
                  <select
                    required
                    value={dispatchForm.product_id}
                    onChange={(e) => {
                      setDispatchNonce(null);
                      setDispatchForm({ ...dispatchForm, product_id: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  >
                    <option value="">-- Select Product --</option>
                    {products.filter((p) => p.active).map((p) => (
                      <option key={p.product_id} value={p.product_id}>
                        {p.sku} — {p.product_name} ({p.pack_weight_g}g)
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Product Lot ID (RELEASED)</span>
                  {lots.length > 0 ? (
                    <select
                      required
                      value={dispatchForm.lot_id}
                      onChange={(e) => {
                        setDispatchNonce(null);
                        setDispatchForm({ ...dispatchForm, lot_id: e.target.value });
                      }}
                      className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white"
                    >
                      <option value="">-- Select Lot --</option>
                      {lots.map((l) => (
                        <option key={l.lot_id} value={l.lot_id}>
                          {l.lot_number || l.lot_id} [{l.quality_status}] — Bal: {l.current_quantity}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      required
                      placeholder="e.g. LOT-2026-001"
                      value={dispatchForm.lot_id}
                      onChange={(e) => {
                        setDispatchNonce(null);
                        setDispatchForm({ ...dispatchForm, lot_id: e.target.value });
                      }}
                      className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                    />
                  )}
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Channel</span>
                  <select
                    value={dispatchForm.channel}
                    onChange={(e) => {
                      setDispatchNonce(null);
                      setDispatchForm({
                        ...dispatchForm,
                        channel: e.target.value as typeof dispatchForm.channel,
                      });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  >
                    <option value="VAN_ROUTE">VAN_ROUTE</option>
                    <option value="WAREHOUSE">WAREHOUSE</option>
                    <option value="DISTRIBUTOR">DISTRIBUTOR</option>
                    <option value="WHOLESALE">WHOLESALE</option>
                    <option value="RETAIL">RETAIL</option>
                    <option value="ECOMMERCE">ECOMMERCE</option>
                  </select>
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Destination / Route</span>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Sanawad Route / Distributor"
                    value={dispatchForm.destination}
                    onChange={(e) => {
                      setDispatchNonce(null);
                      setDispatchForm({ ...dispatchForm, destination: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Quantity (Packets)</span>
                  <input
                    type="number"
                    min={1}
                    required
                    value={dispatchForm.quantity_packets}
                    onChange={(e) => {
                      setDispatchNonce(null);
                      setDispatchForm({
                        ...dispatchForm,
                        quantity_packets: Math.max(1, Number(e.target.value) || 1),
                      });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Van Number (Optional)</span>
                  <input
                    type="text"
                    placeholder="e.g. MP-10-AB-1234"
                    value={dispatchForm.van_number}
                    onChange={(e) => {
                      setDispatchNonce(null);
                      setDispatchForm({ ...dispatchForm, van_number: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Field Salesman (Optional)</span>
                  <select
                    value={dispatchForm.salesman_user_id}
                    onChange={(e) => {
                      setDispatchNonce(null);
                      setDispatchForm({ ...dispatchForm, salesman_user_id: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  >
                    <option value="">-- Select Salesman --</option>
                    {users
                      .filter((u) => ['SALESMAN', 'FIELD_SALESMAN', 'SALES'].includes(String(u.role).toUpperCase()))
                      .map((u) => (
                        <option key={u.user_id} value={u.user_id}>
                          {u.full_name} ({u.user_id})
                        </option>
                      ))}
                  </select>
                </label>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="submit"
                  disabled={submitting || writesLocked}
                  title={writesLocked ? 'Governed writes are locked until Apps Script gateway & Sheets are connected.' : undefined}
                  className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 text-white rounded-lg text-xs font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting
                    ? 'Submitting Governed Write…'
                    : writesLocked
                    ? 'Write Gateway Locked'
                    : dispatchNonce
                    ? 'Retry Dispatch with Same Nonce'
                    : 'Submit Quality-Gated Dispatch'}
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* CHANNELS MODULE */}
      {moduleTab === 'channels' && (
        <div className="space-y-6">
          {!isAuditor && (
            <form
              onSubmit={handleSettlementSubmit}
              className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4"
            >
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h2 className="text-sm font-bold text-slate-900 m-0">
                    Record Marketplace Settlement
                  </h2>
                  <p className="text-xs text-slate-500 mt-0.5 m-0">
                    Automated GST posting requires CA approval on <code className="font-mono">hsn_gst_tax_rates</code>.
                  </p>
                </div>
                {settlementNonce && (
                  <span className="px-2.5 py-1 rounded bg-amber-100 text-amber-900 font-mono text-[11px] font-bold">
                    Draft Nonce Active: {settlementNonce}
                  </span>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
                <label className="block">
                  <span className="font-semibold text-slate-700">Channel Name</span>
                  <input
                    type="text"
                    required
                    value={settlementForm.channel_name}
                    onChange={(e) => {
                      setSettlementNonce(null);
                      setSettlementForm({ ...settlementForm, channel_name: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Settlement Reference</span>
                  <input
                    type="text"
                    required
                    placeholder="e.g. AMZ-STL-2026-11"
                    value={settlementForm.settlement_ref}
                    onChange={(e) => {
                      setSettlementNonce(null);
                      setSettlementForm({ ...settlementForm, settlement_ref: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Settlement Date</span>
                  <input
                    type="date"
                    required
                    value={settlementForm.settlement_date}
                    onChange={(e) => {
                      setSettlementNonce(null);
                      setSettlementForm({ ...settlementForm, settlement_date: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Gross Sales (₹)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={settlementForm.gross_sales_amount}
                    onChange={(e) => {
                      setSettlementNonce(null);
                      setSettlementForm({ ...settlementForm, gross_sales_amount: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Marketplace Fees (₹)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={settlementForm.marketplace_fees}
                    onChange={(e) => {
                      setSettlementNonce(null);
                      setSettlementForm({ ...settlementForm, marketplace_fees: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono"
                  />
                </label>

                <label className="block">
                  <span className="font-semibold text-slate-700">Net Settlement Amount (₹)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={settlementForm.net_settlement_amount}
                    onChange={(e) => {
                      setSettlementNonce(null);
                      setSettlementForm({ ...settlementForm, net_settlement_amount: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono"
                  />
                </label>
              </div>

              <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settlementForm.apply_automated_gst_posting}
                  onChange={(e) => {
                    setSettlementNonce(null);
                    setSettlementForm({
                      ...settlementForm,
                      apply_automated_gst_posting: e.target.checked,
                    });
                  }}
                />
                <span>
                  Apply Automated GST Posting (requires approved CA <code className="font-mono">hsn_gst_tax_rates</code> policy)
                </span>
              </label>

              <div className="flex items-center justify-end gap-3 pt-1">
                <button
                  type="submit"
                  disabled={submitting || writesLocked}
                  title={writesLocked ? 'Governed writes are locked until Apps Script gateway & Sheets are connected.' : undefined}
                  className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 text-white rounded-lg text-xs font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting
                    ? 'Submitting Settlement…'
                    : writesLocked
                    ? 'Write Gateway Locked'
                    : settlementNonce
                    ? 'Retry Settlement with Same Nonce'
                    : 'Submit Marketplace Settlement'}
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* COMPLIANCE, ASSETS, GIG WORK & ADVANCES MODULE */}
      {moduleTab === 'compliance_assets' && (
        <div className="space-y-5">
          <div className="flex items-center gap-2 border-b border-slate-200 overflow-x-auto">
            {[
              { id: 'compliance', label: 'Compliance & Statutory', icon: <ShieldCheck size={14} /> },
              { id: 'assets', label: 'Assets & Maintenance', icon: <Wrench size={14} /> },
              { id: 'gig', label: 'Gig Work (SUBMITTED → VERIFIED → PAID)', icon: <Briefcase size={14} /> },
              ...(canViewAdvances
                ? [{ id: 'advances', label: 'Approved Advances (Confidential)', icon: <Wallet size={14} /> }]
                : []),
            ].map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setComplianceSubTab(t.id as typeof complianceSubTab)}
                className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 whitespace-nowrap cursor-pointer ${
                  complianceSubTab === t.id
                    ? 'border-emerald-700 text-emerald-900 bg-emerald-50/50'
                    : 'border-transparent text-slate-600 hover:text-slate-900'
                }`}
              >
                {t.icon}
                <span>{t.label}</span>
              </button>
            ))}
          </div>

          {!isAuditor && complianceSubTab === 'compliance' && (
            <form
              onSubmit={handleComplianceSubmit}
              className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4"
            >
              <div className="flex items-center justify-between flex-wrap gap-2">
                <h2 className="text-sm font-bold text-slate-900 m-0">
                  Create Compliance / FSSAI / Statutory Record
                </h2>
                {complianceNonce && (
                  <span className="px-2.5 py-1 rounded bg-amber-100 text-amber-900 font-mono text-[11px] font-bold">
                    Draft Nonce: {complianceNonce}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                <label className="block">
                  <span className="font-semibold text-slate-700">Record Type</span>
                  <select
                    value={complianceForm.record_type}
                    onChange={(e) => {
                      setComplianceNonce(null);
                      setComplianceForm({
                        ...complianceForm,
                        record_type: e.target.value as typeof complianceForm.record_type,
                      });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  >
                    <option value="FSSAI_AUDIT">FSSAI_AUDIT</option>
                    <option value="HYGIENE_LOG">HYGIENE_LOG</option>
                    <option value="STATUTORY_FILING">STATUTORY_FILING</option>
                    <option value="EQUIPMENT_CALIBRATION">EQUIPMENT_CALIBRATION</option>
                    <option value="CORRECTIVE_ACTION">CORRECTIVE_ACTION</option>
                  </select>
                </label>
                <label className="block sm:col-span-2">
                  <span className="font-semibold text-slate-700">Title</span>
                  <input
                    type="text"
                    required
                    minLength={3}
                    placeholder="e.g. Monthly FSSAI Hygiene Inspection"
                    value={complianceForm.title}
                    onChange={(e) => {
                      setComplianceNonce(null);
                      setComplianceForm({ ...complianceForm, title: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Due Date</span>
                  <input
                    type="date"
                    value={complianceForm.due_date}
                    onChange={(e) => {
                      setComplianceNonce(null);
                      setComplianceForm({ ...complianceForm, due_date: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={submitting || writesLocked}
                  title={writesLocked ? 'Governed writes are locked until Apps Script gateway & Sheets are connected.' : undefined}
                  className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 text-white rounded-lg text-xs font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {writesLocked ? 'Write Gateway Locked' : complianceNonce ? 'Retry Compliance Record' : 'Submit Compliance Record'}
                </button>
              </div>
            </form>
          )}

          {!isAuditor && complianceSubTab === 'assets' && (
            <form
              onSubmit={handleAssetSubmit}
              className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4"
            >
              <div className="flex items-center justify-between flex-wrap gap-2">
                <h2 className="text-sm font-bold text-slate-900 m-0">
                  Log Factory Asset Maintenance
                </h2>
                {assetNonce && (
                  <span className="px-2.5 py-1 rounded bg-amber-100 text-amber-900 font-mono text-[11px] font-bold">
                    Draft Nonce: {assetNonce}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 text-xs">
                <label className="block">
                  <span className="font-semibold text-slate-700">Asset Code</span>
                  <input
                    type="text"
                    required
                    placeholder="e.g. MCH-DRYER-01"
                    value={assetForm.asset_code}
                    onChange={(e) => {
                      setAssetNonce(null);
                      setAssetForm({ ...assetForm, asset_code: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Asset Name</span>
                  <input
                    type="text"
                    required
                    placeholder="Solar Dryer Line 1"
                    value={assetForm.asset_name}
                    onChange={(e) => {
                      setAssetNonce(null);
                      setAssetForm({ ...assetForm, asset_name: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Type</span>
                  <select
                    value={assetForm.maintenance_type}
                    onChange={(e) => {
                      setAssetNonce(null);
                      setAssetForm({
                        ...assetForm,
                        maintenance_type: e.target.value as typeof assetForm.maintenance_type,
                      });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  >
                    <option value="PREVENTIVE">PREVENTIVE</option>
                    <option value="BREAKDOWN">BREAKDOWN</option>
                    <option value="INSPECTION">INSPECTION</option>
                  </select>
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Cost (₹)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={assetForm.cost_amount}
                    onChange={(e) => {
                      setAssetNonce(null);
                      setAssetForm({ ...assetForm, cost_amount: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono"
                  />
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Scheduled Date</span>
                  <input
                    type="date"
                    value={assetForm.scheduled_date}
                    onChange={(e) => {
                      setAssetNonce(null);
                      setAssetForm({ ...assetForm, scheduled_date: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={submitting || writesLocked}
                  title={writesLocked ? 'Governed writes are locked until Apps Script gateway & Sheets are connected.' : undefined}
                  className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 text-white rounded-lg text-xs font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {writesLocked ? 'Write Gateway Locked' : assetNonce ? 'Retry Maintenance Log' : 'Submit Maintenance Record'}
                </button>
              </div>
            </form>
          )}

          {!isAuditor && complianceSubTab === 'gig' && (
            <form
              onSubmit={handleGigSubmit}
              className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4"
            >
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h2 className="text-sm font-bold text-slate-900 m-0">
                    Submit Gig Worker Piece-Rate Work Entry
                  </h2>
                  <p className="text-xs text-slate-500 mt-0.5 m-0">
                    Separated from FIXED_EMPLOYEE confidential payroll. Lifecycle: <strong>SUBMITTED</strong> → <strong>VERIFIED</strong> → <strong>PAID</strong> (OWNER_ADMIN).
                  </p>
                </div>
                {gigNonce && (
                  <span className="px-2.5 py-1 rounded bg-amber-100 text-amber-900 font-mono text-[11px] font-bold">
                    Draft Nonce: {gigNonce}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-6 gap-3 text-xs">
                <label className="block">
                  <span className="font-semibold text-slate-700">Worker ID</span>
                  <input
                    type="text"
                    required
                    placeholder="e.g. LBR-001"
                    value={gigForm.worker_id}
                    onChange={(e) => {
                      setGigNonce(null);
                      setGigForm({ ...gigForm, worker_id: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>
                <label className="block sm:col-span-2">
                  <span className="font-semibold text-slate-700">Activity</span>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Papad Rolling & Tray Sorting"
                    value={gigForm.activity_name}
                    onChange={(e) => {
                      setGigNonce(null);
                      setGigForm({ ...gigForm, activity_name: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Units Completed</span>
                  <input
                    type="number"
                    step="0.001"
                    min="0.001"
                    required
                    value={gigForm.units_completed}
                    onChange={(e) => {
                      setGigNonce(null);
                      setGigForm({ ...gigForm, units_completed: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono"
                  />
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Unit</span>
                  <select
                    value={gigForm.unit_of_measure}
                    onChange={(e) => {
                      setGigNonce(null);
                      setGigForm({
                        ...gigForm,
                        unit_of_measure: e.target.value as typeof gigForm.unit_of_measure,
                      });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white"
                  >
                    <option value="KG">KG</option>
                    <option value="PACKET">PACKET</option>
                    <option value="SHIFT">SHIFT</option>
                    <option value="HOUR">HOUR</option>
                  </select>
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">Piece Rate (₹)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={gigForm.piece_rate}
                    onChange={(e) => {
                      setGigNonce(null);
                      setGigForm({ ...gigForm, piece_rate: e.target.value });
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono"
                  />
                </label>
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={submitting || writesLocked}
                  title={writesLocked ? 'Governed writes are locked until Apps Script gateway & Sheets are connected.' : undefined}
                  className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 text-white rounded-lg text-xs font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {writesLocked ? 'Write Gateway Locked' : gigNonce ? 'Retry Gig Work Entry' : 'Submit Gig Work Entry'}
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* CONTROL, CA POLICIES & SCHEMA REGISTRY MODULE */}
      {moduleTab === 'control_policies' && (
        <div className="space-y-5">
          <div className="flex items-center gap-2 border-b border-slate-200 overflow-x-auto">
            {[
              { id: 'policies', label: 'Pending CA / Owner Policies', icon: <Sliders size={14} /> },
              { id: 'schema', label: '255-Tab Schema & 32 Prefixes', icon: <Database size={14} /> },
              { id: 'audit', label: 'Audit Log', icon: <ShieldCheck size={14} /> },
              { id: 'exceptions', label: 'Exception Logs', icon: <FileWarning size={14} /> },
            ].map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setControlSubTab(t.id as typeof controlSubTab)}
                className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 whitespace-nowrap cursor-pointer ${
                  controlSubTab === t.id
                    ? 'border-emerald-700 text-emerald-900 bg-emerald-50/50'
                    : 'border-transparent text-slate-600 hover:text-slate-900'
                }`}
              >
                {t.icon}
                <span>{t.label}</span>
              </button>
            ))}
          </div>

          {controlSubTab === 'policies' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {policyList.map((policy) => {
                const draft = policyDrafts[policy.policy_key] || {
                  status: (policy.status === 'APPROVED' ? 'APPROVED' : 'PENDING_CA_APPROVAL') as 'APPROVED' | 'PENDING_CA_APPROVAL',
                  value: policy.value || (policy.allowed_values?.[0] || ''),
                  notes: policy.notes || '',
                };
                return (
                  <div
                    key={policy.policy_key}
                    className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs space-y-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-xs font-mono text-slate-500">{policy.policy_key}</div>
                        <h3 className="text-sm font-bold text-slate-900 m-0">
                          {policy.label || policy.policy_key}
                        </h3>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                          policy.status === 'APPROVED'
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {policy.status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 m-0">{policy.notes}</p>
                    <div className="text-xs text-slate-700">
                      Current Approved Value:{' '}
                      <strong className="font-mono">{policy.value || 'UNSET (Automated posting blocked)'}</strong>
                    </div>

                    {isOwnerAdmin && (
                      <div className="pt-2 border-t border-slate-100 space-y-2 text-xs">
                        <div className="grid grid-cols-2 gap-2">
                          <select
                            value={draft.status}
                            onChange={(e) =>
                              setPolicyDrafts((prev) => ({
                                ...prev,
                                [policy.policy_key]: {
                                  ...draft,
                                  status: e.target.value as 'APPROVED' | 'PENDING_CA_APPROVAL',
                                },
                              }))
                            }
                            className="rounded border border-slate-300 px-2 py-1.5 bg-white"
                          >
                            <option value="PENDING_CA_APPROVAL">PENDING_CA_APPROVAL</option>
                            <option value="APPROVED">APPROVED</option>
                          </select>
                          <select
                            value={draft.value}
                            onChange={(e) =>
                              setPolicyDrafts((prev) => ({
                                ...prev,
                                [policy.policy_key]: { ...draft, value: e.target.value },
                              }))
                            }
                            className="rounded border border-slate-300 px-2 py-1.5 bg-white"
                          >
                            {(policy.allowed_values || []).map((val) => (
                              <option key={val} value={val}>
                                {val}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="flex justify-end">
                          <button
                            type="button"
                            disabled={submitting || writesLocked}
                            onClick={() => handleSavePolicy(policy)}
                            className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {policyNonces[policy.policy_key] ? 'Retry CA Policy Decision' : 'Save CA Policy Decision'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {controlSubTab === 'schema' && schemaRegistry && (
            <div className="space-y-4">
              <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-3 text-xs">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <h3 className="text-sm font-bold text-slate-900 m-0">
                    Cleaned Workbook Baseline: {schemaRegistry.cleaned_tab_baseline} Official Tabs (15 Groups)
                  </h3>
                  <span className="font-mono text-red-700 font-semibold">
                    Forbidden Scratch Prefixes: {schemaRegistry.forbidden_scratch_prefixes.join(', ')}
                  </span>
                </div>
                {schemaRegistry.table_registry_summary && (
                  <div className="flex flex-wrap gap-2 text-[11px]">
                    <span className="px-2 py-1 rounded bg-slate-100 text-slate-800 font-semibold">
                      Catalogued Tabs: {schemaRegistry.table_registry_summary.total_catalogued_tabs} / {schemaRegistry.cleaned_tab_baseline}
                    </span>
                    {typeof schemaRegistry.table_registry_summary.unmapped_workbook_tabs_remaining === 'number' && (
                      <span className="px-2 py-1 rounded bg-amber-100 text-amber-900 font-semibold">
                        Unmapped Tabs Remaining: {schemaRegistry.table_registry_summary.unmapped_workbook_tabs_remaining}
                      </span>
                    )}
                    {typeof schemaRegistry.table_registry_summary.write_blocked_schema_tabs_count === 'number' && (
                      <span className="px-2 py-1 rounded bg-red-100 text-red-900 font-semibold">
                        Write-Blocked Tabs: {schemaRegistry.table_registry_summary.write_blocked_schema_tabs_count}
                      </span>
                    )}
                    {schemaRegistry.table_registry_summary.coverage_status && (
                      <span
                        className={`px-2 py-1 rounded font-semibold ${
                          classifySchemaStatusBadge(schemaRegistry.table_registry_summary.coverage_status).className
                        }`}
                      >
                        Coverage: {schemaRegistry.table_registry_summary.coverage_status}
                      </span>
                    )}
                    {Object.entries(schemaRegistry.table_registry_summary.status_counts || {}).map(([st, cnt]) => {
                      const badge = classifySchemaStatusBadge(st);
                      return (
                        <span
                          key={st}
                          className={`px-2 py-1 rounded font-semibold ${badge.className}`}
                        >
                          {badge.label}: {cnt}
                        </span>
                      );
                    })}
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {schemaRegistry.database_groups.map((grp) => {
                    const hasConflictingTab = (schemaRegistry.conflicting_core_schema_tabs || []).some((t) =>
                      grp.workbook_tabs.includes(t)
                    );
                    const hasPendingTab = (schemaRegistry.pending_owner_mapping_tabs || []).some((t) =>
                      grp.workbook_tabs.includes(t)
                    );
                    const effectiveGroupStatus = hasConflictingTab
                      ? 'CONFLICT_RECONCILIATION_REQUIRED'
                      : hasPendingTab && grp.header_mapping_status === 'VERIFIED_CORE'
                      ? 'PENDING_OWNER_MAPPING'
                      : grp.header_mapping_status;
                    const badge = classifySchemaStatusBadge(effectiveGroupStatus);
                    return (
                      <div key={grp.group_code} className="border border-slate-200 rounded-lg p-3 bg-slate-50/50">
                        <div className="flex items-center justify-between mb-1 gap-1">
                          <span className="font-bold text-slate-900">
                            {grp.group_code}. {grp.group_name}
                          </span>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${badge.className}`}
                          >
                            {badge.label}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-600 font-mono break-words">
                          {grp.workbook_tabs.join(', ')}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {(() => {
                const rawConflicts = schemaRegistry.tab_reconciliation_conflicts;
                const conflictList = Array.isArray(rawConflicts)
                  ? rawConflicts
                  : rawConflicts && typeof rawConflicts === 'object'
                  ? Object.entries(rawConflicts).map(([key, item]) => ({ prefix: key, ...item }))
                  : [];
                if (conflictList.length === 0) return null;
                return (
                  <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-xs text-red-950 space-y-2">
                    <div className="font-bold uppercase tracking-wider text-[11px] text-red-800">
                      CONFLICT_RECONCILIATION_REQUIRED — Tab &amp; Prefix Conflicts ({conflictList.length})
                    </div>
                    {conflictList.map((c, idx) => (
                      <div key={idx} className="bg-white/80 border border-red-200 rounded-lg p-2.5 font-mono text-[11px]">
                        <strong>{String(c.canonical_prefix || c.prefix || 'CONFLICT')}:</strong>{' '}
                        {String(c.primary_tab || c.snapshot_tab || c.canonical_tab || '')} vs{' '}
                        {String(c.conflicting_tab || c.draft_tab || '')} —{' '}
                        {String(c.resolution_required || c.notes || 'Owner reconciliation required before write.')}
                      </div>
                    ))}
                  </div>
                );
              })()}

              {(schemaRegistry.conflicting_core_schema_tabs?.length || 0) > 0 && (
                <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-xs text-red-950 space-y-2">
                  <div className="font-bold uppercase tracking-wider text-[11px] text-red-800">
                    CORE_SCHEMA_CONFLICT_UNRECONCILED ({schemaRegistry.conflicting_core_schema_tabs!.length} Core Tabs Write-Blocked Until Owner Row-1 Header Reconciliation)
                  </div>
                  <div className="font-mono text-[11px] text-red-900 break-words">
                    {schemaRegistry.conflicting_core_schema_tabs!.join(', ')}
                  </div>
                </div>
              )}

              {(schemaRegistry.pending_owner_mapping_tabs?.length || 0) > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-xs text-amber-950 space-y-2">
                  <div className="font-bold uppercase tracking-wider text-[11px] text-amber-800">
                    PENDING_OWNER_MAPPING ({schemaRegistry.pending_owner_mapping_tabs!.length} Extended Tabs Awaiting Row-1 Header Verification)
                  </div>
                  <div className="font-mono text-[11px] text-amber-900 break-words">
                    {schemaRegistry.pending_owner_mapping_tabs!.join(', ')}
                  </div>
                </div>
              )}

              <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs text-xs">
                <h3 className="text-sm font-bold text-slate-900 mb-3">
                  Locked 32 Business ID Prefixes
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-2">
                  {Object.entries(schemaRegistry.locked_32_id_prefixes).map(([prefix, tab]) => (
                    <div key={prefix} className="border border-slate-200 rounded px-2.5 py-1.5 bg-slate-50">
                      <div className="font-mono font-bold text-emerald-800">{prefix}-</div>
                      <div className="text-[11px] text-slate-600 truncate">{tab}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {controlSubTab === 'exceptions' &&
            (() => {
              const rawConflicts = schemaRegistry?.tab_reconciliation_conflicts;
              const hasConflicts = Array.isArray(rawConflicts)
                ? rawConflicts.length > 0
                : Boolean(rawConflicts && Object.keys(rawConflicts).length > 0);
              return hasConflicts;
            })() && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-xs text-red-950">
              <strong>Reconciliation Gate Active (CONFLICT_RECONCILIATION_REQUIRED):</strong> Canonical exception tab is{' '}
              <code className="font-mono">ExceptionRegister</code> (legacy draft alias{' '}
              <code className="font-mono">ExceptionLogs</code> deprecated); Row-1 physical headers remain{' '}
              <code className="font-mono">PENDING_OWNER_MAPPING</code> before writes are permitted.
            </div>
          )}
        </div>
      )}

      {/* PAGINATED GOOGLE SHEETS COLLECTION TABLE */}
      {resolveCollectionEndpoint() && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-slate-900 m-0">
                Authoritative Sheet Records ({collection?.tab_name || 'Google Sheets'})
              </h3>
              <p className="text-xs text-slate-500 mt-0.5 m-0">
                Showing {items.length} of {totalCount} records · Server-side paginated
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search records…"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setPage(1);
                  }}
                  className="pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-300"
                />
              </div>
            </div>
          </div>

          {listError ? (
            <div className="p-6 text-xs text-red-800 bg-red-50 border-t border-red-200">
              <strong>Fail-Closed Read State:</strong> {listError}
            </div>
          ) : items.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-500">
              {listLoading
                ? 'Loading live records from Google Sheets…'
                : 'No records returned for this collection in Google Sheets.'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 uppercase text-[11px]">
                  <tr>
                    {Object.keys(items[0]).slice(0, 7).map((col) => (
                      <th key={col} className="px-4 py-2.5 font-semibold whitespace-nowrap">
                        {col}
                      </th>
                    ))}
                    {(complianceSubTab === 'gig' || complianceSubTab === 'advances') &&
                      moduleTab === 'compliance_assets' &&
                      !isAuditor && (
                        <th className="px-4 py-2.5 font-semibold text-right">Workflow Action</th>
                      )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((row, idx) => {
                    const rowId =
                      row.entry_id ||
                      row.advance_id ||
                      row.dispatch_id ||
                      row.settlement_id ||
                      row.compliance_id ||
                      row.maintenance_id ||
                      String(idx);
                    return (
                      <tr key={rowId} className="hover:bg-slate-50/70">
                        {Object.keys(items[0])
                          .slice(0, 7)
                          .map((col) => (
                            <td key={col} className="px-4 py-2.5 text-slate-700 whitespace-nowrap font-mono">
                              {String(row[col] ?? '')}
                            </td>
                          ))}

                        {moduleTab === 'compliance_assets' && complianceSubTab === 'gig' && !isAuditor && (
                          <td className="px-4 py-2.5 text-right space-x-2 whitespace-nowrap">
                            {String(row.status || '').toUpperCase() === 'SUBMITTED' &&
                              (isOwnerAdmin || canonicalRole === 'HR') && (
                                <button
                                  type="button"
                                  disabled={submitting || writesLocked}
                                  onClick={() => handleGigTransition(String(row.entry_id), 'verify')}
                                  className="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white rounded text-[11px] font-bold cursor-pointer disabled:opacity-50"
                                >
                                  Verify Work
                                </button>
                              )}
                            {String(row.status || '').toUpperCase() === 'VERIFIED' && isOwnerAdmin && (
                              <button
                                type="button"
                                disabled={submitting || writesLocked}
                                onClick={() => handleGigTransition(String(row.entry_id), 'pay')}
                                className="px-2.5 py-1 bg-emerald-700 hover:bg-emerald-800 text-white rounded text-[11px] font-bold cursor-pointer disabled:opacity-50"
                              >
                                Pay Gig Wage
                              </button>
                            )}
                          </td>
                        )}

                        {moduleTab === 'compliance_assets' &&
                          complianceSubTab === 'advances' &&
                          canViewAdvances &&
                          !isAuditor && (
                            <td className="px-4 py-2.5 text-right whitespace-nowrap">
                              <div className="inline-flex items-center gap-1.5">
                                <select
                                  value={advanceMethod}
                                  onChange={(e) =>
                                    setAdvanceMethod(e.target.value as typeof advanceMethod)
                                  }
                                  className="border border-slate-300 rounded px-1.5 py-1 text-[11px] bg-white"
                                >
                                  <option value="BANK_TRANSFER">BANK_TRANSFER</option>
                                  <option value="UPI">UPI</option>
                                  <option value="CASH">CASH</option>
                                </select>
                                <input
                                  type="text"
                                  placeholder="Payment Ref"
                                  value={advanceRefs[String(row.advance_id)] || ''}
                                  onChange={(e) =>
                                    setAdvanceRefs((prev) => ({
                                      ...prev,
                                      [String(row.advance_id)]: e.target.value,
                                    }))
                                  }
                                  className="border border-slate-300 rounded px-2 py-1 text-[11px] w-28"
                                />
                                <button
                                  type="button"
                                  disabled={submitting || writesLocked}
                                  onClick={() => handleAdvanceDisburse(String(row.advance_id))}
                                  className="px-2.5 py-1 bg-emerald-700 hover:bg-emerald-800 text-white rounded text-[11px] font-bold cursor-pointer disabled:opacity-50"
                                >
                                  Disburse
                                </button>
                              </div>
                            </td>
                          )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination Footer */}
          <div className="p-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-600">
            <span>
              Page {page} of {Math.max(1, totalPages)}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1 || listLoading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="p-1.5 rounded border border-slate-300 bg-white disabled:opacity-40 cursor-pointer"
              >
                <ChevronLeft size={14} />
              </button>
              <button
                type="button"
                disabled={page >= totalPages || listLoading}
                onClick={() => setPage((p) => p + 1)}
                className="p-1.5 rounded border border-slate-300 bg-white disabled:opacity-40 cursor-pointer"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
