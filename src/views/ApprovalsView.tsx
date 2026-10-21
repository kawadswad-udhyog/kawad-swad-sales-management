import React, { useState, useEffect } from 'react';
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
} from 'lucide-react';

type BatchRow = Record<string, any>;

export const ApprovalsView: React.FC = () => {
  const {
    currentUser,
    approvalRequests,
    loadApprovalRequests,
    decideApprovalRequest,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
  } = useStore();

  const [activeTab, setActiveTab] = useState<'PENDING' | 'APPROVED' | 'REJECTED'>('PENDING');
  const [batches, setBatches] = useState<BatchRow[]>([]);
  const [isLoadingBatches, setIsLoadingBatches] = useState(false);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const isOwner = currentUser?.role === 'OWNER';

  const fetchBatches = async () => {
    setIsLoadingBatches(true);
    try {
      const res = await apiRequest<BatchRow[]>('/api/production/batches');
      if (Array.isArray(res)) {
        setBatches([...res].reverse());
      }
    } catch (err) {
      console.warn('Could not load production batches for approvals', err);
    } finally {
      setIsLoadingBatches(false);
    }
  };

  useEffect(() => {
    fetchBatches();
    loadApprovalRequests();
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
      const msg = err instanceof Error ? err.message : 'Approval failed.';
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
      const msg = err instanceof Error ? err.message : 'Rejection failed.';
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
      setFeedback({ type: 'success', message: `Request ${requestId} ${decision.toLowerCase()}.` });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Decision failed.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setBusyActionId(null);
    }
  };

  // Filter batches by tab
  const filteredBatches = batches.filter((b) => {
    const status = String(b.status || 'PENDING').toUpperCase();
    if (activeTab === 'PENDING') return status === 'PENDING';
    if (activeTab === 'APPROVED') return status === 'APPROVED';
    if (activeTab === 'REJECTED') return status === 'REJECTED';
    return true;
  });

  // Filter user requests by tab
  const filteredUserRequests = (approvalRequests || []).filter((r) => {
    const status = String(r.status || 'PENDING').toUpperCase();
    if (activeTab === 'PENDING') return status === 'PENDING';
    if (activeTab === 'APPROVED') return status === 'APPROVED';
    if (activeTab === 'REJECTED') return status === 'REJECTED';
    return true;
  });

  const pendingBatchCount = batches.filter((b) => String(b.status).toUpperCase() === 'PENDING').length;
  const pendingUserCount = (approvalRequests || []).filter((r) => String(r.status).toUpperCase() === 'PENDING').length;
  const totalPending = pendingBatchCount + pendingUserCount;

  return (
    <div>
      <PageHeader
        title="Approvals Workspace"
        subtitle="Review, approve, or reject pending production batches and user account requests."
        icon={<CheckSquare size={22} />}
        actions={
          <button
            onClick={() => {
              fetchBatches();
              loadApprovalRequests();
            }}
            disabled={isLoadingBatches}
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
              cursor: isLoadingBatches ? 'not-allowed' : 'pointer',
            }}
          >
            <RefreshCw size={14} className={isLoadingBatches ? 'spin-icon' : ''} />
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
      </div>

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
        </div>

        {filteredBatches.length === 0 ? (
          <div style={{ padding: '30px 16px', textAlign: 'center', color: '#64748b', fontSize: '0.90rem' }}>
            No {activeTab.toLowerCase()} production batches.
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
                  const isBusy = busyActionId === b.production_id;
                  const isPending = String(b.status).toUpperCase() === 'PENDING';
                  return (
                    <tr key={b.production_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '10px 12px', fontWeight: 600, color: '#0f172a' }}>{b.production_id}</td>
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
                        {isPending ? (
                          isOwner ? (
                            <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                              <button
                                disabled={isBusy || !isGoogleSheetsConnected || !persistentWritesEnabled}
                                onClick={() => handleApproveBatch(b.production_id)}
                                style={{
                                  padding: '5px 10px',
                                  fontSize: '0.78rem',
                                  fontWeight: 700,
                                  background: '#166534',
                                  color: '#ffffff',
                                  border: 'none',
                                  borderRadius: '6px',
                                  cursor: isBusy ? 'not-allowed' : 'pointer',
                                }}
                                title="Approve batch, consume recipe raw materials, and credit bulk stock"
                              >
                                {isBusy ? 'Saving…' : 'Approve'}
                              </button>
                              <button
                                disabled={isBusy || !isGoogleSheetsConnected || !persistentWritesEnabled}
                                onClick={() => handleRejectBatch(b.production_id)}
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

      {/* SECTION 2: User Account & Security Approvals */}
      <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Shield size={18} color="#7e22ce" />
            <h2 style={{ margin: 0, fontSize: '1.10rem', color: '#0f172a' }}>
              User Account & Identity Requests ({filteredUserRequests.length})
            </h2>
          </div>
        </div>

        {filteredUserRequests.length === 0 ? (
          <div style={{ padding: '30px 16px', textAlign: 'center', color: '#64748b', fontSize: '0.90rem' }}>
            No {activeTab.toLowerCase()} user account requests.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.86rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', textAlign: 'left' }}>
                  <th style={{ padding: '10px 12px' }}>Request ID</th>
                  <th style={{ padding: '10px 12px' }}>Type</th>
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
                  const isPending = String(r.status).toUpperCase() === 'PENDING';
                  return (
                    <tr key={r.request_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '10px 12px', fontWeight: 600, color: '#0f172a' }}>{r.request_id}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ fontSize: '0.78rem', fontWeight: 600, background: '#f1f5f9', padding: '3px 7px', borderRadius: '4px' }}>
                          {r.request_type}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', fontWeight: 500 }}>{r.target_user_id}</td>
                      <td style={{ padding: '10px 12px', color: '#64748b' }}>{r.requested_by}</td>
                      <td style={{ padding: '10px 12px', color: '#64748b', fontSize: '0.80rem' }}>
                        {r.requested_at ? r.requested_at.slice(0, 16).replace('T', ' ') : '-'}
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <StatusBadge status={r.status} />
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        {isPending ? (
                          isOwner ? (
                            <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                              <button
                                disabled={isBusy || !isGoogleSheetsConnected || !persistentWritesEnabled}
                                onClick={() => handleDecideUserRequest(r.request_id, 'APPROVED')}
                                style={{
                                  padding: '5px 10px',
                                  fontSize: '0.78rem',
                                  fontWeight: 700,
                                  background: '#166534',
                                  color: '#ffffff',
                                  border: 'none',
                                  borderRadius: '6px',
                                  cursor: isBusy ? 'not-allowed' : 'pointer',
                                }}
                              >
                                {isBusy ? 'Saving…' : 'Approve'}
                              </button>
                              <button
                                disabled={isBusy || !isGoogleSheetsConnected || !persistentWritesEnabled}
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
                            {r.decided_by ? `Decided by ${r.decided_by}` : 'Completed'}
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
    </div>
  );
};
