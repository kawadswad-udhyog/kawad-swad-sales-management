import React, { useState, useEffect, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { apiRequest } from '../services/api';
import { PageHeader } from '../components/common/PageHeader';
import { StatusBadge } from '../components/common/StatusBadge';
import { StatCard } from '../components/common/StatCard';
import {
  CheckSquare,
  CheckCircle2,
  XCircle,
  Clock,
  Factory,
  Shield,
  RefreshCw,
  AlertTriangle,
  Info,
  ChevronDown,
  ChevronRight,
  AlertCircle,
} from 'lucide-react';
import { ApprovalRequest } from '../types';

type BatchRow = Record<string, any>;

// Normalization helpers for approval states
const isPending = (status: unknown) => {
  const norm = String(status || '').trim().toUpperCase();
  return ['PENDING', 'PENDING_APPROVAL', 'PENDING APPROVAL', 'SUBMITTED', 'IN_REVIEW', 'AWAITING_APPROVAL', 'AWAITING_OWNER'].includes(norm);
};

const isApproved = (status: unknown) => {
  const norm = String(status || '').trim().toUpperCase();
  return ['APPROVED', 'COMPLETED', 'CONFIRMED'].includes(norm);
};

const isRejected = (status: unknown) => {
  const norm = String(status || '').trim().toUpperCase();
  return ['REJECTED', 'DISAPPROVED', 'CANCELLED'].includes(norm);
};

const isFailed = (status: unknown) => {
  const norm = String(status || '').trim().toUpperCase();
  return ['EXECUTION_FAILED', 'FAILED'].includes(norm);
};

export const ApprovalsView: React.FC = () => {
  const {
    currentUser,
    approvalRequests,
    loadApprovalRequests,
    decideApprovalRequest,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
  } = useStore();

  const [activeTab, setActiveTab] = useState<'PENDING' | 'APPROVED' | 'REJECTED' | 'FAILED'>('PENDING');
  const [batches, setBatches] = useState<BatchRow[]>([]);
  const [isLoadingBatches, setIsLoadingBatches] = useState(false);
  const [batchesError, setBatchesError] = useState<string | null>(null);

  const [isLoadingRequests, setIsLoadingRequests] = useState(false);
  const [requestsError, setRequestsError] = useState<string | null>(null);

  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [expandedPayloadIds, setExpandedPayloadIds] = useState<Set<string>>(new Set());

  // Check if current user has authorized approval rights (Owner, Owner Admin, or System Admin)
  const canDecide = ['OWNER', 'OWNER_ADMIN', 'ADMIN'].includes(currentUser?.role?.toUpperCase() || '');

  const toggleExpand = (id: string) => {
    setExpandedPayloadIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const fetchBatches = async () => {
    setIsLoadingBatches(true);
    setBatchesError(null);
    try {
      const res = await apiRequest<BatchRow[]>('/api/production/batches');
      if (Array.isArray(res)) {
        const normalized = res.map((b) => {
          const id = String(b.production_id || b.batch_id || '').trim();
          return {
            ...b,
            production_id: id,
            batch_id: id,
          };
        });
        setBatches([...normalized].reverse());
      } else {
        setBatches([]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Could not retrieve production batches.';
      console.warn('Could not load production batches for approvals:', err);
      setBatchesError(msg);
    } finally {
      setIsLoadingBatches(false);
    }
  };

  const fetchRequests = async () => {
    setIsLoadingRequests(true);
    setRequestsError(null);
    try {
      await loadApprovalRequests();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Could not retrieve approval requests.';
      console.warn('Could not load approval requests:', err);
      setRequestsError(msg);
    } finally {
      setIsLoadingRequests(false);
    }
  };

  const refreshAll = async () => {
    await Promise.all([fetchBatches(), fetchRequests()]);
  };

  useEffect(() => {
    refreshAll();
  }, []);

  const handleApproveBatch = async (batchId: string) => {
    setBusyActionId(batchId);
    setFeedback(null);
    try {
      await apiRequest(`/api/production/batches/${encodeURIComponent(batchId)}/approval`, {
        method: 'POST',
        body: JSON.stringify({ approved: true, notes: `Approved by ${currentUser?.full_name || 'Owner'}` }),
      });
      setFeedback({ type: 'success', message: `Batch ${batchId} approved. Raw materials consumed and bulk inventory credited.` });
      await fetchBatches();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Batch approval failed.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setBusyActionId(null);
    }
  };

  const handleRejectBatch = async (batchId: string) => {
    setBusyActionId(batchId);
    setFeedback(null);
    try {
      await apiRequest(`/api/production/batches/${encodeURIComponent(batchId)}/approval`, {
        method: 'POST',
        body: JSON.stringify({ approved: false, notes: `Rejected by ${currentUser?.full_name || 'Owner'}` }),
      });
      setFeedback({ type: 'success', message: `Batch ${batchId} rejected.` });
      await fetchBatches();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Batch rejection failed.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setBusyActionId(null);
    }
  };

  const handleDecideUserRequest = async (requestId: string, decision: 'APPROVED' | 'REJECTED') => {
    setBusyActionId(requestId);
    setFeedback(null);
    try {
      await decideApprovalRequest(requestId, decision, `${decision} by ${currentUser?.full_name || 'Owner'}`);
      setFeedback({ type: 'success', message: `Request ${requestId} ${decision.toLowerCase()} successfully.` });
      await fetchRequests();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Decision execution failed.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setBusyActionId(null);
    }
  };

  // Cross-reference any production batches from ApprovalRequests that might be missing in ProductionBatches
  const synthesizedBatches = useMemo(() => {
    const list = [...batches];
    const existingIds = new Set(list.map((b) => String(b.production_id || b.batch_id || '').trim()));

    (approvalRequests || []).forEach((req) => {
      if (req.request_type === 'PRODUCTION_BATCH') {
        let payload: any = {};
        try {
          payload = typeof req.payload_json === 'string' ? JSON.parse(req.payload_json || '{}') : (req.payload_json || {});
        } catch {}
        const bId = String(req.target_user_id || payload.production_id || payload.batch_id || req.request_id).trim();
        if (bId && !existingIds.has(bId)) {
          existingIds.add(bId);
          list.push({
            production_id: bId,
            batch_id: bId,
            production_date: req.requested_at?.slice(0, 10) || '',
            product_name_snapshot: payload.product_name || 'Production Batch',
            net_quantity_kg: payload.net_quantity_kg || 0,
            flour_base_used_kg: payload.flour_base_used_kg || '-',
            yield_variance_kg: payload.yield_variance_kg || 0,
            created_by: req.requested_by_name || req.requested_by || 'PA',
            status: req.status || 'PENDING',
            recipe_id: payload.recipe_id || '',
            notes: payload.notes || req.decision_notes || '',
            _from_request: req.request_id,
          });
        }
      }
    });

    return list;
  }, [batches, approvalRequests]);

  // Filter batches by active tab
  const filteredBatches = useMemo(() => {
    return synthesizedBatches.filter((b) => {
      const s = b.status;
      if (activeTab === 'PENDING') return isPending(s) || isFailed(s);
      if (activeTab === 'APPROVED') return isApproved(s);
      if (activeTab === 'REJECTED') return isRejected(s);
      if (activeTab === 'FAILED') return isFailed(s);
      return true;
    });
  }, [synthesizedBatches, activeTab]);

  // Filter identity requests by tab (excluding PRODUCTION_BATCH which is handled in Section 1)
  const identityRequests = useMemo(() => {
    return (approvalRequests || []).filter((r) => r.request_type !== 'PRODUCTION_BATCH');
  }, [approvalRequests]);

  const filteredUserRequests = useMemo(() => {
    return identityRequests.filter((r) => {
      const s = r.status;
      if (activeTab === 'PENDING') return isPending(s) || isFailed(s);
      if (activeTab === 'APPROVED') return isApproved(s);
      if (activeTab === 'REJECTED') return isRejected(s);
      if (activeTab === 'FAILED') return isFailed(s);
      return true;
    });
  }, [identityRequests, activeTab]);

  // Counts for stat cards and badges
  const pendingBatchCount = synthesizedBatches.filter((b) => isPending(b.status)).length;
  const pendingUserCount = identityRequests.filter((r) => isPending(r.status)).length;
  const failedCount =
    synthesizedBatches.filter((b) => isFailed(b.status)).length +
    identityRequests.filter((r) => isFailed(r.status)).length;
  const totalPending = pendingBatchCount + pendingUserCount;

  // Helper to parse human-readable summary of user requests
  const describePayload = (r: ApprovalRequest) => {
    try {
      const p = typeof r.payload_json === 'string' ? JSON.parse(r.payload_json || '{}') : (r.payload_json || {});
      if (r.request_type === 'CREATE_USER') {
        return `Create account for "${p.full_name || p.username || r.target_user_id}" with role ${p.role || 'SALESMAN'}${p.mobile ? ` (Mobile: ${p.mobile})` : ''}`;
      }
      if (r.request_type === 'UPDATE_USER') {
        const changes = Object.keys(p).filter((k) => k !== 'password').map((k) => `${k}: ${p[k]}`).join(', ');
        return `Update details: ${changes || 'Field modifications'}`;
      }
      if (r.request_type === 'DEACTIVATE_USER') {
        return `Deactivate account: ${p.reason || 'Requested by PA'}`;
      }
      if (r.request_type === 'REACTIVATE_USER') {
        return `Reactivate account: ${p.reason || 'Requested by PA'}`;
      }
      if (r.request_type === 'RESET_PASSWORD') {
        return `Reset account password and invalidate existing active sessions`;
      }
      return JSON.stringify(p);
    } catch {
      return r.payload_json || '-';
    }
  };

  return (
    <div>
      <PageHeader
        title="Approvals Workspace"
        subtitle="Review, approve, or reject pending production batches and user account requests."
        icon={<CheckSquare size={22} />}
        actions={
          <button
            onClick={refreshAll}
            disabled={isLoadingBatches || isLoadingRequests}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              borderRadius: '8px',
              background: '#f8fafc',
              border: '1px solid #cbd5e1',
              color: '#475569',
              fontWeight: 600,
              fontSize: '0.84rem',
              cursor: isLoadingBatches || isLoadingRequests ? 'not-allowed' : 'pointer',
            }}
          >
            <RefreshCw size={14} className={isLoadingBatches || isLoadingRequests ? 'spin-icon' : ''} />
            Refresh
          </button>
        }
      />

      {/* Top Metric Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px', marginBottom: '20px' }}>
        <StatCard
          title="Total Pending Approvals"
          value={totalPending}
          subtext={`${pendingBatchCount} production, ${pendingUserCount} user accounts`}
          icon={<Clock size={18} />}
          alert={totalPending > 0}
          alertColor="amber"
          onClick={() => setActiveTab('PENDING')}
        />
        <StatCard
          title="Pending Batches"
          value={pendingBatchCount}
          subtext="Awaiting recipe deduction & stock credit"
          icon={<Factory size={18} />}
          iconBg="#eff6ff"
          iconColor="#1d4ed8"
          onClick={() => setActiveTab('PENDING')}
        />
        <StatCard
          title="Account Requests"
          value={pendingUserCount}
          subtext="New users, role changes, credentials"
          icon={<Shield size={18} />}
          iconBg="#faf5ff"
          iconColor="#7e22ce"
          onClick={() => setActiveTab('PENDING')}
        />
        {failedCount > 0 && (
          <StatCard
            title="Failed Executions"
            value={failedCount}
            subtext="Needs owner retry or rejection"
            icon={<AlertTriangle size={18} />}
            alert={true}
            alertColor="red"
            onClick={() => setActiveTab('FAILED')}
          />
        )}
      </div>

      {/* Role / Permission Notice for Non-Owners */}
      {!canDecide && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            marginBottom: '16px',
            background: '#f8fafc',
            border: '1px solid #e2e8f0',
            color: '#64748b',
            fontSize: '0.84rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <Info size={16} color="#64748b" />
          <span>
            Logged in as <strong>{currentUser?.role || 'User'}</strong> ({currentUser?.full_name || currentUser?.username}).
            Approval decisions require Owner or Administrator authorization. You can inspect pending status and submitted details below.
          </span>
        </div>
      )}

      {/* Feedback Banner */}
      {feedback && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            marginBottom: '16px',
            fontSize: '0.88rem',
            fontWeight: 500,
            background: feedback.type === 'success' ? '#ecfdf5' : '#fef2f2',
            color: feedback.type === 'success' ? '#166534' : '#b91c1c',
            border: `1px solid ${feedback.type === 'success' ? '#bbf7d0' : '#fecaca'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>{feedback.message}</span>
          <button
            onClick={() => setFeedback(null)}
            style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1rem' }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Status Filter Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '8px',
          borderBottom: '2px solid #e2e8f0',
          marginBottom: '20px',
        }}
      >
        <button
          onClick={() => setActiveTab('PENDING')}
          style={{
            padding: '10px 18px',
            border: 'none',
            borderBottom: activeTab === 'PENDING' ? '2px solid #166534' : '2px solid transparent',
            marginBottom: '-2px',
            background: 'transparent',
            fontWeight: activeTab === 'PENDING' ? 700 : 500,
            color: activeTab === 'PENDING' ? '#166534' : '#64748b',
            cursor: 'pointer',
            fontSize: '0.90rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span>Pending Decisions</span>
          {totalPending > 0 && (
            <span
              style={{
                background: '#f59e0b',
                color: '#ffffff',
                fontSize: '0.72rem',
                fontWeight: 700,
                padding: '1px 7px',
                borderRadius: '999px',
              }}
            >
              {totalPending}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('APPROVED')}
          style={{
            padding: '10px 18px',
            border: 'none',
            borderBottom: activeTab === 'APPROVED' ? '2px solid #166534' : '2px solid transparent',
            marginBottom: '-2px',
            background: 'transparent',
            fontWeight: activeTab === 'APPROVED' ? 700 : 500,
            color: activeTab === 'APPROVED' ? '#166534' : '#64748b',
            cursor: 'pointer',
            fontSize: '0.90rem',
          }}
        >
          Approved History
        </button>

        <button
          onClick={() => setActiveTab('REJECTED')}
          style={{
            padding: '10px 18px',
            border: 'none',
            borderBottom: activeTab === 'REJECTED' ? '2px solid #166534' : '2px solid transparent',
            marginBottom: '-2px',
            background: 'transparent',
            fontWeight: activeTab === 'REJECTED' ? 700 : 500,
            color: activeTab === 'REJECTED' ? '#166534' : '#64748b',
            cursor: 'pointer',
            fontSize: '0.90rem',
          }}
        >
          Rejected
        </button>

        {failedCount > 0 && (
          <button
            onClick={() => setActiveTab('FAILED')}
            style={{
              padding: '10px 18px',
              border: 'none',
              borderBottom: activeTab === 'FAILED' ? '2px solid #dc2626' : '2px solid transparent',
              marginBottom: '-2px',
              background: 'transparent',
              fontWeight: activeTab === 'FAILED' ? 700 : 500,
              color: activeTab === 'FAILED' ? '#dc2626' : '#64748b',
              cursor: 'pointer',
              fontSize: '0.90rem',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>Failed Executions</span>
            <span
              style={{
                background: '#dc2626',
                color: '#ffffff',
                fontSize: '0.72rem',
                fontWeight: 700,
                padding: '1px 7px',
                borderRadius: '999px',
              }}
            >
              {failedCount}
            </span>
          </button>
        )}
      </div>

      {/* SECTION 1: Production Batches */}
      <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '18px', marginBottom: '22px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Factory size={18} color="#166534" />
            <h2 style={{ margin: 0, fontSize: '1.10rem', color: '#0f172a' }}>
              Production Batches ({filteredBatches.length})
            </h2>
          </div>
          {isLoadingBatches && <span style={{ fontSize: '0.80rem', color: '#64748b' }}>Refreshing ledger…</span>}
        </div>

        {/* Batches Error Banner */}
        {batchesError && (
          <div
            style={{
              padding: '12px 14px',
              borderRadius: '8px',
              marginBottom: '16px',
              background: '#fef2f2',
              border: '1px solid #fecaca',
              color: '#b91c1c',
              fontSize: '0.86rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertTriangle size={16} />
              <span>Could not synchronize production batches: {batchesError}</span>
            </div>
            <button
              onClick={fetchBatches}
              style={{
                background: '#ffffff',
                border: '1px solid #fca5a5',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '0.78rem',
                fontWeight: 600,
                color: '#b91c1c',
                cursor: 'pointer',
              }}
            >
              Retry
            </button>
          </div>
        )}

        {filteredBatches.length === 0 ? (
          <div style={{ padding: '30px 16px', textAlign: 'center', color: '#64748b', fontSize: '0.90rem' }}>
            {isLoadingBatches
              ? 'Loading production batches from ledger…'
              : `No ${activeTab.toLowerCase()} production batches found.`}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.86rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', textAlign: 'left' }}>
                  <th style={{ padding: '10px 12px' }}>Batch ID</th>
                  <th style={{ padding: '10px 12px' }}>Date</th>
                  <th style={{ padding: '10px 12px' }}>Product</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right' }}>Flour (kg)</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right' }}>Net Output (kg)</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right' }}>Yield Variance</th>
                  <th style={{ padding: '10px 12px' }}>Entered By</th>
                  <th style={{ padding: '10px 12px' }}>Status</th>
                  <th style={{ padding: '10px 12px', textAlign: 'center' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredBatches.map((b) => {
                  const bId = String(b.production_id || b.batch_id || '').trim();
                  const isBusy = busyActionId === bId;
                  const pendingDecision = isPending(b.status) || isFailed(b.status);
                  const isExecutionFailed = isFailed(b.status);
                  const fromRequest = b._from_request;

                  return (
                    <tr key={bId || Math.random()} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '10px 12px', fontWeight: 600, color: '#0f172a' }}>{bId || '-'}</td>
                      <td style={{ padding: '10px 12px', color: '#64748b' }}>{b.production_date || '-'}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 500 }}>{b.product_name_snapshot || '-'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right' }}>{b.flour_base_used_kg || '-'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 700, color: '#166534' }}>
                        {b.net_quantity_kg || b.saleable_output_kg || b.quantity_kg || 0} kg
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontSize: '0.82rem', color: Number(b.yield_variance_kg) < 0 ? '#b91c1c' : '#15803d' }}>
                        {b.yield_variance_kg ? `${b.yield_variance_kg} kg` : '-'}
                      </td>
                      <td style={{ padding: '10px 12px', color: '#64748b', fontSize: '0.80rem' }}>{b.created_by || '-'}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <StatusBadge status={b.status || 'PENDING'} />
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        {pendingDecision ? (
                          canDecide ? (
                            <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                              <button
                                disabled={isBusy || (!isGoogleSheetsConnected && persistentWritesEnabled) || !bId}
                                onClick={() => (fromRequest ? handleDecideUserRequest(fromRequest, 'APPROVED') : handleApproveBatch(bId))}
                                style={{
                                  padding: '5px 11px',
                                  fontSize: '0.78rem',
                                  fontWeight: 700,
                                  background: isExecutionFailed ? '#d97706' : '#166534',
                                  color: '#ffffff',
                                  border: 'none',
                                  borderRadius: '6px',
                                  cursor: isBusy || !bId ? 'not-allowed' : 'pointer',
                                }}
                                title="Approve batch, consume recipe raw materials, and credit bulk stock"
                              >
                                {isBusy ? 'Saving…' : isExecutionFailed ? 'Retry Approval' : 'Approve'}
                              </button>
                              <button
                                disabled={isBusy || (!isGoogleSheetsConnected && persistentWritesEnabled) || !bId}
                                onClick={() => (fromRequest ? handleDecideUserRequest(fromRequest, 'REJECTED') : handleRejectBatch(bId))}
                                style={{
                                  padding: '5px 10px',
                                  fontSize: '0.78rem',
                                  fontWeight: 700,
                                  background: '#b91c1c',
                                  color: '#ffffff',
                                  border: 'none',
                                  borderRadius: '6px',
                                  cursor: isBusy || !bId ? 'not-allowed' : 'pointer',
                                }}
                              >
                                Reject
                              </button>
                            </div>
                          ) : (
                            <span style={{ fontSize: '0.76rem', color: '#64748b', fontStyle: 'italic' }}>
                              Awaiting Owner
                            </span>
                          )
                        ) : (
                          <span style={{ fontSize: '0.76rem', color: '#94a3b8' }}>
                            {b.approved_by ? `By ${b.approved_by}` : 'Completed'}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* SECTION 2: User Account & Identity Approvals */}
      <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Shield size={18} color="#7e22ce" />
            <h2 style={{ margin: 0, fontSize: '1.10rem', color: '#0f172a' }}>
              User Account & Identity Requests ({filteredUserRequests.length})
            </h2>
          </div>
          {isLoadingRequests && <span style={{ fontSize: '0.80rem', color: '#64748b' }}>Refreshing requests…</span>}
        </div>

        {/* Requests Error Banner */}
        {requestsError && (
          <div
            style={{
              padding: '12px 14px',
              borderRadius: '8px',
              marginBottom: '16px',
              background: '#fef2f2',
              border: '1px solid #fecaca',
              color: '#b91c1c',
              fontSize: '0.86rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertTriangle size={16} />
              <span>Could not retrieve account requests: {requestsError}</span>
            </div>
            <button
              onClick={fetchRequests}
              style={{
                background: '#ffffff',
                border: '1px solid #fca5a5',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '0.78rem',
                fontWeight: 600,
                color: '#b91c1c',
                cursor: 'pointer',
              }}
            >
              Retry
            </button>
          </div>
        )}

        {filteredUserRequests.length === 0 ? (
          <div style={{ padding: '30px 16px', textAlign: 'center', color: '#64748b', fontSize: '0.90rem' }}>
            {isLoadingRequests
              ? 'Loading account requests…'
              : `No ${activeTab.toLowerCase()} user account requests found.`}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.86rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', textAlign: 'left' }}>
                  <th style={{ padding: '10px 12px' }}>Request ID</th>
                  <th style={{ padding: '10px 12px' }}>Type</th>
                  <th style={{ padding: '10px 12px' }}>Proposed Action</th>
                  <th style={{ padding: '10px 12px' }}>Target Employee</th>
                  <th style={{ padding: '10px 12px' }}>Requested By</th>
                  <th style={{ padding: '10px 12px' }}>Requested At</th>
                  <th style={{ padding: '10px 12px' }}>Status</th>
                  <th style={{ padding: '10px 12px', textAlign: 'center' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredUserRequests.map((r) => {
                  const isBusy = busyActionId === r.request_id;
                  const pendingDecision = isPending(r.status) || isFailed(r.status);
                  const isExecutionFailed = isFailed(r.status);
                  const isExpanded = expandedPayloadIds.has(r.request_id);

                  return (
                    <React.Fragment key={r.request_id}>
                      <tr style={{ borderBottom: isExpanded ? 'none' : '1px solid #f1f5f9' }}>
                        <td style={{ padding: '10px 12px', fontWeight: 600, color: '#0f172a' }}>{r.request_id}</td>
                        <td style={{ padding: '10px 12px' }}>
                          <span
                            style={{
                              fontSize: '0.74rem',
                              fontWeight: 700,
                              background: '#f3e8ff',
                              color: '#7e22ce',
                              padding: '3px 8px',
                              borderRadius: '4px',
                            }}
                          >
                            {r.request_type}
                          </span>
                        </td>
                        <td style={{ padding: '10px 12px', fontSize: '0.83rem', color: '#1e293b' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span>{describePayload(r)}</span>
                            {r.payload_json && r.payload_json !== '{}' && (
                              <button
                                onClick={() => toggleExpand(r.request_id)}
                                style={{
                                  background: 'transparent',
                                  border: 'none',
                                  cursor: 'pointer',
                                  padding: 0,
                                  color: '#64748b',
                                  display: 'flex',
                                  alignItems: 'center',
                                }}
                                title="Toggle JSON payload"
                              >
                                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                              </button>
                            )}
                          </div>
                          {isExecutionFailed && r.execution_error && (
                            <div
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                color: '#b91c1c',
                                fontSize: '0.76rem',
                                marginTop: '4px',
                                fontWeight: 500,
                              }}
                            >
                              <AlertCircle size={12} />
                              <span>Error: {r.execution_error}</span>
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '10px 12px', fontWeight: 500 }}>{r.target_user_id || 'NEW'}</td>
                        <td style={{ padding: '10px 12px', color: '#64748b', fontSize: '0.82rem' }}>
                          {r.requested_by_name || r.requested_by || 'PA'}
                        </td>
                        <td style={{ padding: '10px 12px', color: '#64748b', fontSize: '0.80rem' }}>
                          {r.requested_at ? r.requested_at.slice(0, 16).replace('T', ' ') : '-'}
                        </td>
                        <td style={{ padding: '10px 12px' }}>
                          <StatusBadge status={r.status} />
                        </td>
                        <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                          {pendingDecision ? (
                            canDecide ? (
                              <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                                <button
                                  disabled={isBusy || (!isGoogleSheetsConnected && persistentWritesEnabled)}
                                  onClick={() => handleDecideUserRequest(r.request_id, 'APPROVED')}
                                  style={{
                                    padding: '5px 11px',
                                    fontSize: '0.78rem',
                                    fontWeight: 700,
                                    background: isExecutionFailed ? '#d97706' : '#166534',
                                    color: '#ffffff',
                                    border: 'none',
                                    borderRadius: '6px',
                                    cursor: isBusy ? 'not-allowed' : 'pointer',
                                  }}
                                  title={isExecutionFailed ? 'Retry failed execution' : 'Approve user request'}
                                >
                                  {isBusy ? 'Saving…' : isExecutionFailed ? 'Retry' : 'Approve'}
                                </button>
                                <button
                                  disabled={isBusy || (!isGoogleSheetsConnected && persistentWritesEnabled)}
                                  onClick={() => handleDecideUserRequest(r.request_id, 'REJECTED')}
                                  style={{
                                    padding: '5px 10px',
                                    fontSize: '0.78rem',
                                    fontWeight: 700,
                                    background: '#b91c1c',
                                    color: '#ffffff',
                                    border: 'none',
                                    borderRadius: '6px',
                                    cursor: isBusy ? 'not-allowed' : 'pointer',
                                  }}
                                >
                                  Reject
                                </button>
                              </div>
                            ) : (
                              <span style={{ fontSize: '0.76rem', color: '#64748b', fontStyle: 'italic' }}>
                                Awaiting Owner
                              </span>
                            )
                          ) : (
                            <span style={{ fontSize: '0.76rem', color: '#94a3b8' }}>
                              {r.decided_by ? `By ${r.decided_by}` : 'Completed'}
                            </span>
                          )}
                        </td>
                      </tr>
                      {/* Expandable JSON Detail View */}
                      {isExpanded && (
                        <tr style={{ background: '#f8fafc', borderBottom: '1px solid #f1f5f9' }}>
                          <td colSpan={8} style={{ padding: '8px 14px' }}>
                            <div style={{ fontSize: '0.78rem', fontFamily: 'monospace', color: '#334155' }}>
                              <strong>Request Payload:</strong> {r.payload_json}
                              {r.decision_notes && (
                                <div style={{ marginTop: '4px', color: '#475569' }}>
                                  <strong>Decision Notes:</strong> {r.decision_notes}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
