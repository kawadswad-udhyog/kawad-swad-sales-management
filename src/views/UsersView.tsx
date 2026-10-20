import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { User, UserRole, ApprovalRequest, ReconciliationReport } from '../types';
import { apiRequest } from '../services/api';

export const UsersView: React.FC = () => {
  const {
    users,
    currentUser,
    createUser,
    updateUser,
    setUserStatus,
    resetUserPassword,
    approvalRequests,
    decideApprovalRequest,
    retryApprovalRequest,
    cancelApprovalRequest,
  } = useStore();

  const isOwner = currentUser?.role === 'OWNER';
  const isPA = currentUser?.role === 'PA';

  const [activeTab, setActiveTab] = useState<'directory' | 'approvals' | 'history' | 'reconciliation'>('directory');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);
  const [reconciliationReport, setReconciliationReport] = useState<ReconciliationReport | null>(null);
  const [isLoadingReconciliation, setIsLoadingReconciliation] = useState(false);

  const fetchReconciliation = async () => {
    setIsLoadingReconciliation(true);
    try {
      const data = await apiRequest<ReconciliationReport>('/api/users/reconciliation');
      setReconciliationReport(data);
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to fetch reconciliation report.';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setIsLoadingReconciliation(false);
    }
  };

  // Form states for Create User / Request Create User
  const [fullName, setFullName] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('SALESMAN');
  const [mobile, setMobile] = useState('');
  const [email, setEmail] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Modal states for Edit, Password Reset, Status Change
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editFullName, setEditFullName] = useState('');
  const [editRole, setEditRole] = useState<UserRole>('SALESMAN');
  const [editMobile, setEditMobile] = useState('');
  const [editEmail, setEditEmail] = useState('');
  const [editNotes, setEditNotes] = useState('');

  const [pwResetUser, setPwResetUser] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const [rejectingRequest, setRejectingRequest] = useState<ApprovalRequest | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  if (!isOwner && !isPA) {
    return (
      <div className="card notice-error" style={{ margin: '20px' }}>
        Access restricted. Only Business Owner and Personal Assistant (PA) can access Team &amp; Approvals.
      </div>
    );
  }

  // Pending approval requests count
  const pendingRequests = approvalRequests.filter((r) => r.status === 'PENDING');
  const failedExecutions = approvalRequests.filter((r) => r.status === 'EXECUTION_FAILED');

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    const cleanUsername = username.trim().toLowerCase();
    if (users.some((u) => u.username.toLowerCase() === cleanUsername)) {
      setNotice({ msg: `Username '${cleanUsername}' is already taken. Please choose another username.`, error: true });
      return;
    }

    if (isPA && role === 'OWNER') {
      setNotice({ msg: 'PA is not authorized to create an Owner account.', error: true });
      return;
    }

    if (isOwner && (!password || password.length < 8)) {
      setNotice({ msg: 'Please provide an initial password of at least 8 characters.', error: true });
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await createUser({
        full_name: fullName.trim(),
        username: cleanUsername,
        password: isOwner ? password : '',
        role,
        mobile: mobile.trim(),
        email: email.trim(),
        active: true,
        notes: notes.trim(),
      });

      if (res && res.pending_approval) {
        setNotice({ msg: `Request to create '${cleanUsername}' submitted. Awaiting Owner approval.` });
      } else {
        setNotice({ msg: `Employee account '${fullName}' (${cleanUsername}) created successfully.` });
      }

      setFullName('');
      setUsername('');
      setPassword('');
      setMobile('');
      setEmail('');
      setNotes('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to process user creation.';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenEdit = (u: User) => {
    setEditingUser(u);
    setEditFullName(u.full_name);
    setEditRole(u.role);
    setEditMobile(u.mobile || '');
    setEditEmail(u.email || '');
    setEditNotes(u.notes || '');
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingUser) return;
    setNotice(null);
    setIsSubmitting(true);

    try {
      const res = await updateUser(editingUser.user_id, {
        full_name: editFullName.trim(),
        role: editRole,
        mobile: editMobile.trim(),
        email: editEmail.trim(),
        notes: editNotes.trim(),
      });

      if (res.pending_approval) {
        setNotice({ msg: `Update request for '${editingUser.full_name}' submitted for Owner approval.` });
      } else {
        setNotice({ msg: `Employee '${editFullName}' updated successfully.` });
      }
      setEditingUser(null);
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to update employee.';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggleStatus = async (u: User) => {
    const nextState = !u.active;
    const actionWord = nextState ? 'reactivate' : 'deactivate';
    const confirmMsg = isOwner
      ? `Are you sure you want to ${actionWord} '${u.full_name}'? ${!nextState ? 'This will immediately revoke all active sessions across devices.' : ''}`
      : `Submit a request to Owner to ${actionWord} '${u.full_name}'?`;

    if (!window.confirm(confirmMsg)) return;

    setNotice(null);
    try {
      const res = await setUserStatus(u.user_id, nextState, `Requested by ${currentUser?.full_name}`);
      if (res.pending_approval) {
        setNotice({ msg: `Status change request for '${u.full_name}' submitted for Owner approval.` });
      } else {
        setNotice({ msg: `Account for '${u.full_name}' ${nextState ? 'reactivated' : 'deactivated and all sessions revoked'}.` });
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : `Failed to ${actionWord} employee.`;
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleResetPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pwResetUser) return;
    setNotice(null);

    if (isOwner && (!newPassword || newPassword.length < 8)) {
      setNotice({ msg: 'Please provide a password of at least 8 characters.', error: true });
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await resetUserPassword(pwResetUser.user_id, isOwner ? newPassword : '');
      if (res.pending_approval) {
        setNotice({ msg: `Password reset request for '${pwResetUser.full_name}' submitted for Owner approval.` });
      } else {
        setNotice({ msg: `Password reset for '${pwResetUser.full_name}'. Existing sessions revoked. User must set new password on login.` });
      }
      setPwResetUser(null);
      setNewPassword('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to reset password.';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApprove = async (req: ApprovalRequest) => {
    setNotice(null);
    try {
      const res = await decideApprovalRequest(req.request_id, 'APPROVED');
      const credNotice = (res as { temporary_credentials?: string })?.temporary_credentials;
      setNotice({
        msg: `Request ${req.request_id} (${req.request_type}) approved and executed! ${credNotice ? ` [${credNotice}]` : ''}`,
      });
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to approve request.';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleRejectSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rejectingRequest) return;
    setNotice(null);

    try {
      await decideApprovalRequest(rejectingRequest.request_id, 'REJECTED', rejectReason.trim());
      setNotice({ msg: `Request ${rejectingRequest.request_id} rejected.` });
      setRejectingRequest(null);
      setRejectReason('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to reject request.';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleRetryExecution = async (reqId: string) => {
    setNotice(null);
    try {
      await retryApprovalRequest(reqId);
      setNotice({ msg: `Successfully retried and executed request ${reqId}!` });
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Retry execution failed.';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleCancelRequest = async (reqId: string) => {
    if (!window.confirm(`Cancel your pending request ${reqId}?`)) return;
    setNotice(null);
    try {
      await cancelApprovalRequest(reqId);
      setNotice({ msg: `Request ${reqId} cancelled.` });
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to cancel request.';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'EXECUTED':
      case 'APPROVED':
        return <span style={{ background: '#dcfce7', color: '#15803d', padding: '3px 8px', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }}>EXECUTED</span>;
      case 'PENDING':
        return <span style={{ background: '#fef08a', color: '#854d0e', padding: '3px 8px', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }}>PENDING APPROVAL</span>;
      case 'EXECUTION_FAILED':
        return <span style={{ background: '#fee2e2', color: '#b91c1c', padding: '3px 8px', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }}>EXECUTION FAILED</span>;
      case 'REJECTED':
        return <span style={{ background: '#f1f5f9', color: '#475569', padding: '3px 8px', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }}>REJECTED</span>;
      case 'CANCELLED':
        return <span style={{ background: '#f1f5f9', color: '#64748b', padding: '3px 8px', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }}>CANCELLED</span>;
      default:
        return <span>{status}</span>;
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
        <div>
          <h1 style={{ margin: 0 }}>Team &amp; Approvals</h1>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            {isOwner
              ? 'Owner Workspace · Direct employee administration and PA approval authorization.'
              : 'PA Workspace · Submit employee requests for Owner acceptance. Changes execute upon approval.'}
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            type="button"
            className={activeTab === 'directory' ? 'primary' : 'secondary'}
            onClick={() => setActiveTab('directory')}
          >
            👥 Team Directory ({users.length})
          </button>

          <button
            type="button"
            className={activeTab === 'approvals' ? 'primary' : 'secondary'}
            onClick={() => setActiveTab('approvals')}
            style={{ position: 'relative' }}
          >
            {isOwner ? '⏳ Pending Approvals' : '📋 My Pending Requests'}
            {pendingRequests.length > 0 && (
              <span style={{
                marginLeft: '6px',
                background: '#ef4444',
                color: '#fff',
                borderRadius: '999px',
                padding: '2px 7px',
                fontSize: '0.72rem',
                fontWeight: 800,
              }}>
                {pendingRequests.length}
              </span>
            )}
          </button>

          <button
            type="button"
            className={activeTab === 'history' ? 'primary' : 'secondary'}
            onClick={() => setActiveTab('history')}
          >
            📜 Approval History
          </button>

          {isOwner && (
            <button
              type="button"
              className={activeTab === 'reconciliation' ? 'primary' : 'secondary'}
              onClick={() => {
                setActiveTab('reconciliation');
                void fetchReconciliation();
              }}
            >
              🔍 Sheet Audit &amp; Reconciliation
            </button>
          )}
        </div>
      </div>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'} style={{ marginBottom: '16px' }}>
          {notice.msg}
        </div>
      )}

      {/* Failed Execution Alert for Owner */}
      {isOwner && failedExecutions.length > 0 && (
        <div className="notice-error" style={{ marginBottom: '16px' }}>
          <strong>⚠️ Action Required: Execution Failure ({failedExecutions.length})</strong>
          <p style={{ margin: '4px 0 8px', fontSize: '0.85rem' }}>
            One or more approved requests could not complete Google Sheets persistence. You can safely retry without duplicating records:
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {failedExecutions.map((req) => (
              <div key={req.request_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#fff', padding: '8px 12px', borderRadius: '6px' }}>
                <div>
                  <strong>{req.request_id}</strong>: {req.request_type} on target {req.target_user_id || 'NEW'} — <span style={{ color: '#dc2626' }}>{req.execution_error || 'Write error'}</span>
                </div>
                <button type="button" onClick={() => handleRetryExecution(req.request_id)} style={{ padding: '4px 10px', fontSize: '0.8rem' }}>
                  ⚡ Retry Execution
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 1: TEAM DIRECTORY */}
      {activeTab === 'directory' && (
        <>
          {/* Register New Member Form */}
          <div className="card" style={{ marginBottom: '20px' }}>
            <h2>{isOwner ? 'Register New Team Member' : 'Submit Request for New Team Member'}</h2>
            <p className="muted" style={{ marginTop: '-8px', fontSize: '0.85rem' }}>
              {isOwner
                ? 'Create a new employee profile in Users and login credentials in AuthUsers directly.'
                : 'Submit proposed employee details. An approval request will be routed to the Owner.'}
            </p>

            <form className="inline" onSubmit={handleCreateSubmit} autoComplete="off">
              <label>
                Full Name
                <input
                  required
                  placeholder="e.g. Anand Sharma"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <label>
                Username
                <input
                  required
                  placeholder="e.g. anand"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <label>
                Role
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as UserRole)}
                  disabled={isSubmitting}
                >
                  <option value="SALESMAN">SALESMAN (Field Sales)</option>
                  <option value="PA">PA (Personal Assistant)</option>
                  {isOwner && <option value="OWNER">OWNER (Business Admin)</option>}
                </select>
              </label>

              <label>
                Mobile Number
                <input
                  type="tel"
                  placeholder="10-digit mobile"
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <label>
                Email Address
                <input
                  type="email"
                  placeholder="name@kawadswad.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              {isOwner ? (
                <label>
                  Initial Password (min 8 chars)
                  <input
                    type="password"
                    required
                    placeholder="••••••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={isSubmitting}
                  />
                </label>
              ) : (
                <div style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: '6px', fontSize: '0.82rem', color: '#475569', alignSelf: 'center' }}>
                  🔒 <em>Security Policy: Passwords cannot be set by PA. Credentials will be safely generated upon Owner approval.</em>
                </div>
              )}

              <label style={{ gridColumn: 'span 2' }}>
                Notes / Assigned Territory
                <input
                  placeholder="District, responsibilities, or employee ID reference..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <div style={{ gridColumn: 'span 2', marginTop: '6px' }}>
                <button type="submit" disabled={isSubmitting}>
                  {isSubmitting
                    ? 'Processing…'
                    : isOwner
                    ? 'Create Employee Account'
                    : 'Submit Request for Owner Approval'}
                </button>
              </div>
            </form>
          </div>

          {/* Directory Listing */}
          <div className="card">
            <h2>Team Members Directory</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>User ID</th>
                    <th>Full Name</th>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Mobile</th>
                    <th>Status</th>
                    <th>Join Date</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const isTargetOwner = u.role === 'OWNER';
                    const canManage = isOwner || (isPA && !isTargetOwner);

                    return (
                      <tr key={u.user_id} style={{ opacity: u.active ? 1 : 0.65 }}>
                        <td>
                          <code>{u.user_id}</code>
                        </td>
                        <td>
                          <strong>{u.full_name}</strong>
                          {u.notes && <div className="muted" style={{ fontSize: '0.75rem' }}>{u.notes}</div>}
                        </td>
                        <td>
                          <code>{u.username || '—'}</code>
                        </td>
                        <td>
                          <span
                            style={{
                              padding: '3px 8px',
                              borderRadius: '999px',
                              fontSize: '0.78rem',
                              fontWeight: 700,
                              background:
                                u.role === 'OWNER'
                                  ? '#fef08a'
                                  : u.role === 'PA'
                                  ? '#bfdbfe'
                                  : '#bbf7d0',
                              color:
                                u.role === 'OWNER'
                                  ? '#854d0e'
                                  : u.role === 'PA'
                                  ? '#1e40af'
                                  : '#166534',
                            }}
                          >
                            {u.role}
                          </span>
                        </td>
                        <td>{u.mobile || '—'}</td>
                        <td>
                          {u.active ? (
                            <span className="badge on">Active</span>
                          ) : (
                            <span style={{ background: '#fee2e2', color: '#b91c1c', padding: '2px 8px', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 700 }}>
                              Inactive
                            </span>
                          )}
                          {u.sync_warning && (
                            <div style={{ color: '#dc2626', fontSize: '0.7rem', marginTop: '3px', fontWeight: 600 }}>
                              ⚠️ {u.sync_warning}
                            </div>
                          )}
                        </td>
                        <td>{u.created_at ? new Date(u.created_at).toLocaleDateString('en-IN') : '—'}</td>
                        <td>
                          {canManage ? (
                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                              <button
                                type="button"
                                className="secondary"
                                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                                onClick={() => handleOpenEdit(u)}
                                title={isOwner ? 'Edit employee' : 'Request employee edit'}
                              >
                                {isOwner ? '✏ Edit' : '📝 Req Edit'}
                              </button>

                              <button
                                type="button"
                                className="secondary"
                                style={{
                                  padding: '3px 8px',
                                  fontSize: '0.75rem',
                                  color: u.active ? '#b91c1c' : '#15803d',
                                }}
                                onClick={() => handleToggleStatus(u)}
                                title={isOwner ? (u.active ? 'Deactivate account & revoke sessions' : 'Reactivate account') : 'Request status change'}
                              >
                                {u.active ? (isOwner ? '🚫 Deactivate' : 'Req Deactivate') : (isOwner ? '✅ Reactivate' : 'Req Reactivate')}
                              </button>

                              <button
                                type="button"
                                className="secondary"
                                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                                onClick={() => {
                                  setPwResetUser(u);
                                  setNewPassword('');
                                }}
                                title={isOwner ? 'Reset password and revoke active sessions' : 'Request password reset'}
                              >
                                🔑 Reset PW
                              </button>
                            </div>
                          ) : (
                            <span className="muted" style={{ fontSize: '0.75rem' }}>Protected (Owner)</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* TAB 2: PENDING APPROVALS */}
      {activeTab === 'approvals' && (
        <div className="card">
          <h2>{isOwner ? 'Pending PA Requests Requiring Decision' : 'My Pending Approval Requests'}</h2>
          <p className="muted" style={{ marginTop: '-8px', fontSize: '0.85rem' }}>
            {isOwner
              ? 'Review actions submitted by Personal Assistants. Approving executes the change to Google Sheets and invalidates affected sessions if required.'
              : 'Track the status of requests you submitted to the Owner. You can cancel pending requests before they are decided.'}
          </p>

          {pendingRequests.length === 0 ? (
            <div style={{ padding: '30px 20px', textAlign: 'center', color: '#64748b' }}>
              <div style={{ fontSize: '2rem', marginBottom: '8px' }}>✅</div>
              No pending approval requests. All items have been processed.
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Request ID</th>
                    <th>Type</th>
                    <th>Target User</th>
                    <th>Requested By</th>
                    <th>Submitted At</th>
                    <th>Proposed Changes</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingRequests.map((req) => {
                    let detailsObj: any = {};
                    try {
                      detailsObj = JSON.parse(req.payload_json || '{}');
                    } catch {}

                    return (
                      <tr key={req.request_id}>
                        <td><code>{req.request_id}</code></td>
                        <td>
                          <strong>{req.request_type}</strong>
                        </td>
                        <td><code>{req.target_user_id || 'NEW'}</code></td>
                        <td>{req.requested_by_name || req.requested_by}</td>
                        <td>{new Date(req.requested_at).toLocaleString('en-IN')}</td>
                        <td style={{ fontSize: '0.8rem', maxWidth: '300px' }}>
                          {req.request_type === 'CREATE_USER' && (
                            <div>
                              <strong>{detailsObj.full_name}</strong> ({detailsObj.username}) · Role: {detailsObj.role}
                            </div>
                          )}
                          {req.request_type === 'UPDATE_USER' && (
                            <div>
                              {detailsObj.full_name && <div>Name: {detailsObj.full_name}</div>}
                              {detailsObj.role && <div>Role: {detailsObj.role}</div>}
                              {detailsObj.mobile && <div>Mobile: {detailsObj.mobile}</div>}
                            </div>
                          )}
                          {(req.request_type === 'DEACTIVATE_USER' || req.request_type === 'REACTIVATE_USER') && (
                            <div>
                              Status: <strong>{req.request_type === 'REACTIVATE_USER' ? 'Active' : 'Inactive'}</strong>
                              {detailsObj.reason && <div className="muted">{detailsObj.reason}</div>}
                            </div>
                          )}
                          {req.request_type === 'RESET_PASSWORD' && (
                            <div>Reset password and revoke active sessions</div>
                          )}
                        </td>
                        <td>
                          {isOwner ? (
                            <div style={{ display: 'flex', gap: '6px' }}>
                              <button
                                type="button"
                                style={{ padding: '4px 10px', fontSize: '0.75rem', background: '#15803d' }}
                                onClick={() => handleApprove(req)}
                              >
                                ✓ Approve &amp; Execute
                              </button>

                              <button
                                type="button"
                                className="secondary"
                                style={{ padding: '4px 10px', fontSize: '0.75rem', color: '#b91c1c' }}
                                onClick={() => {
                                  setRejectingRequest(req);
                                  setRejectReason('');
                                }}
                              >
                                ✕ Reject
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="secondary"
                              style={{ padding: '4px 10px', fontSize: '0.75rem', color: '#b91c1c' }}
                              onClick={() => handleCancelRequest(req.request_id)}
                            >
                              Cancel Request
                            </button>
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
      )}

      {/* TAB 3: APPROVAL & DECISION HISTORY */}
      {activeTab === 'history' && (
        <div className="card">
          <h2>Approval Request &amp; Execution Audit History</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Request ID</th>
                  <th>Type</th>
                  <th>Target User</th>
                  <th>Requester</th>
                  <th>Submitted</th>
                  <th>Status</th>
                  <th>Decided By</th>
                  <th>Decided At</th>
                  <th>Notes / Errors</th>
                </tr>
              </thead>
              <tbody>
                {approvalRequests.map((req) => (
                  <tr key={req.request_id}>
                    <td><code>{req.request_id}</code></td>
                    <td>{req.request_type}</td>
                    <td><code>{req.target_user_id || 'NEW'}</code></td>
                    <td>{req.requested_by_name || req.requested_by}</td>
                    <td>{new Date(req.requested_at).toLocaleString('en-IN')}</td>
                    <td>{getStatusBadge(req.status)}</td>
                    <td>{req.decided_by || '—'}</td>
                    <td>{req.decided_at ? new Date(req.decided_at).toLocaleString('en-IN') : '—'}</td>
                    <td style={{ fontSize: '0.8rem' }}>
                      {req.decision_notes && <div>{req.decision_notes}</div>}
                      {req.execution_error && (
                        <div style={{ color: '#dc2626', fontWeight: 600 }}>
                          Error: {req.execution_error}
                          {isOwner && req.status === 'EXECUTION_FAILED' && (
                            <button
                              type="button"
                              onClick={() => handleRetryExecution(req.request_id)}
                              style={{ marginLeft: '6px', padding: '2px 6px', fontSize: '0.72rem' }}
                            >
                              Retry
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 4: SHEET RECONCILIATION AUDIT (Owner Only) */}
      {isOwner && activeTab === 'reconciliation' && (
        <div>
          <div className="card" style={{ marginBottom: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
              <div>
                <h2 style={{ margin: 0 }}>Google Sheets User System Reconciliation Audit</h2>
                <p className="muted" style={{ margin: '4px 0 0', fontSize: '0.85rem' }}>
                  Independent, read-only analysis comparing live records between <code>Users</code> (profiles) and <code>AuthUsers</code> (login credentials).
                </p>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => void fetchReconciliation()}
                disabled={isLoadingReconciliation}
              >
                {isLoadingReconciliation ? 'Analyzing Sheets…' : '🔄 Refresh Live Audit'}
              </button>
            </div>

            {isLoadingReconciliation && (
              <div style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>
                Fetching and auditing live Google Sheets records...
              </div>
            )}

            {!isLoadingReconciliation && reconciliationReport && (
              <div style={{ marginTop: '16px' }}>
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                  gap: '12px',
                  marginBottom: '20px',
                }}>
                  <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <div className="muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase' }}>Users Sheet Profiles</div>
                    <div style={{ fontSize: '1.4rem', fontWeight: 800, marginTop: '4px' }}>{reconciliationReport.total_users_count}</div>
                  </div>
                  <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <div className="muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase' }}>AuthUsers Sheet Logins</div>
                    <div style={{ fontSize: '1.4rem', fontWeight: 800, marginTop: '4px' }}>{reconciliationReport.total_auth_users_count}</div>
                  </div>
                  <div style={{
                    padding: '12px',
                    background: reconciliationReport.healthy ? '#dcfce7' : '#fee2e2',
                    borderRadius: '8px',
                    border: `1px solid ${reconciliationReport.healthy ? '#bbf7d0' : '#fecaca'}`,
                  }}>
                    <div className="muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: reconciliationReport.healthy ? '#166534' : '#991b1b' }}>System Health</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, marginTop: '4px', color: reconciliationReport.healthy ? '#166534' : '#991b1b' }}>
                      {reconciliationReport.healthy ? '✓ Synchronized' : `⚠️ ${reconciliationReport.total_issues_count} Discrepancies`}
                    </div>
                  </div>
                </div>

                {reconciliationReport.healthy ? (
                  <div className="notice-success">
                    <strong>✓ All records are synchronized.</strong> Every profile in <code>Users</code> matches an active login account in <code>AuthUsers</code> with matching roles and statuses.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                    {reconciliationReport.orphaned_profiles.length > 0 && (
                      <div className="notice-error">
                        <strong>Orphaned Profiles in Users Sheet ({reconciliationReport.orphaned_profiles.length}):</strong>
                        <p style={{ margin: '4px 0 8px', fontSize: '0.82rem' }}>
                          These employees exist in <code>Users</code> but have NO login credentials in <code>AuthUsers</code>. They cannot sign in.
                        </p>
                        <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem' }}>
                          {reconciliationReport.orphaned_profiles.map((p, idx) => (
                            <li key={idx}>
                              <code>{p.user_id}</code>: <strong>{p.full_name}</strong> (Username: <code>{p.username || '—'}</code>, Role: {p.role})
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {reconciliationReport.orphaned_auth_accounts.length > 0 && (
                      <div className="notice-error">
                        <strong>Orphaned Credentials in AuthUsers Sheet ({reconciliationReport.orphaned_auth_accounts.length}):</strong>
                        <p style={{ margin: '4px 0 8px', fontSize: '0.82rem' }}>
                          These accounts exist in <code>AuthUsers</code> but have NO profile in <code>Users</code>.
                        </p>
                        <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem' }}>
                          {reconciliationReport.orphaned_auth_accounts.map((a, idx) => (
                            <li key={idx}>
                              User ID: <code>{a.user_id}</code> | Username: <code>{a.username}</code> (Role: {a.role})
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {reconciliationReport.role_mismatches.length > 0 && (
                      <div className="notice-error">
                        <strong>Role Mismatches ({reconciliationReport.role_mismatches.length}):</strong>
                        <ul style={{ margin: '4px 0 0', paddingLeft: '20px', fontSize: '0.85rem' }}>
                          {reconciliationReport.role_mismatches.map((m, idx) => (
                            <li key={idx}>
                              <code>{m.user_id}</code> ({m.username}): Users role <code>{m.users_role}</code> ≠ AuthUsers role <code>{m.auth_role}</code>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {reconciliationReport.status_mismatches.length > 0 && (
                      <div className="notice-error">
                        <strong>Status Divergences ({reconciliationReport.status_mismatches.length}):</strong>
                        <ul style={{ margin: '4px 0 0', paddingLeft: '20px', fontSize: '0.85rem' }}>
                          {reconciliationReport.status_mismatches.map((s, idx) => (
                            <li key={idx}>
                              <code>{s.user_id}</code> ({s.username}): Users is <strong>{s.users_active ? 'Active' : 'Inactive'}</strong> but AuthUsers is <strong>{s.auth_active ? 'Active' : 'Inactive'}</strong>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {reconciliationReport.duplicate_usernames.length > 0 && (
                      <div className="notice-error">
                        <strong>Duplicate Usernames in AuthUsers ({reconciliationReport.duplicate_usernames.length}):</strong>
                        <ul style={{ margin: '4px 0 0', paddingLeft: '20px', fontSize: '0.85rem' }}>
                          {reconciliationReport.duplicate_usernames.map((d, idx) => (
                            <li key={idx}>
                              Username <code>{d.username}</code> is used by user IDs: {d.user_ids.join(', ')}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* MODAL: EDIT EMPLOYEE */}
      {editingUser && (
        <div className="modal-overlay" onClick={() => setEditingUser(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '520px' }}>
            <h2>{isOwner ? `Edit Employee (${editingUser.user_id})` : `Request Edit (${editingUser.user_id})`}</h2>
            <form onSubmit={handleSaveEdit}>
              <label>
                Full Name
                <input
                  required
                  value={editFullName}
                  onChange={(e) => setEditFullName(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <label>
                Role
                <select
                  value={editRole}
                  onChange={(e) => setEditRole(e.target.value as UserRole)}
                  disabled={isSubmitting}
                >
                  <option value="SALESMAN">SALESMAN (Field Sales)</option>
                  <option value="PA">PA (Personal Assistant)</option>
                  {isOwner && <option value="OWNER">OWNER (Business Admin)</option>}
                </select>
              </label>

              <label>
                Mobile
                <input
                  type="tel"
                  value={editMobile}
                  onChange={(e) => setEditMobile(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <label>
                Email
                <input
                  type="email"
                  value={editEmail}
                  onChange={(e) => setEditEmail(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <label>
                Notes
                <input
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  disabled={isSubmitting}
                />
              </label>

              <div className="actions" style={{ marginTop: '16px' }}>
                <button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? 'Saving…' : isOwner ? 'Save Changes' : 'Submit for Owner Approval'}
                </button>
                <button type="button" className="secondary" onClick={() => setEditingUser(null)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: RESET PASSWORD */}
      {pwResetUser && (
        <div className="modal-overlay" onClick={() => setPwResetUser(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '440px' }}>
            <h2>{isOwner ? `Reset Password (${pwResetUser.full_name})` : `Request Password Reset`}</h2>
            <p className="muted" style={{ fontSize: '0.85rem' }}>
              {isOwner
                ? 'Setting a new password will immediately revoke all active sessions across all devices for this user. The employee will be prompted to set their own password upon logging in.'
                : 'Submit a password reset request to the Owner.'}
            </p>

            {isOwner ? (
              <form onSubmit={handleResetPasswordSubmit}>
                <label>
                  New Temporary Password (min 8 characters)
                  <input
                    type="password"
                    required
                    placeholder="••••••••••••"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    disabled={isSubmitting}
                  />
                </label>

                <div className="actions" style={{ marginTop: '16px' }}>
                  <button type="submit" disabled={isSubmitting || newPassword.length < 8}>
                    {isSubmitting ? 'Processing…' : 'Reset Password & Revoke Sessions'}
                  </button>
                  <button type="button" className="secondary" onClick={() => setPwResetUser(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleResetPasswordSubmit}>
                <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '6px', fontSize: '0.85rem', color: '#334155', marginBottom: '16px' }}>
                  🔒 <strong>Policy Note:</strong> A request will be routed to the Owner to reset credentials for <strong>{pwResetUser.full_name}</strong>. Personal Assistants do not issue or view employee passwords.
                </div>
                <div className="actions">
                  <button type="submit" disabled={isSubmitting}>
                    {isSubmitting ? 'Submitting…' : 'Submit Reset Request to Owner'}
                  </button>
                  <button type="button" className="secondary" onClick={() => setPwResetUser(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* MODAL: REJECT REQUEST */}
      {rejectingRequest && (
        <div className="modal-overlay" onClick={() => setRejectingRequest(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '440px' }}>
            <h2>Reject Approval Request {rejectingRequest.request_id}</h2>
            <form onSubmit={handleRejectSubmit}>
              <label>
                Reason for Rejection
                <input
                  required
                  placeholder="e.g. Duplicate request or incorrect salary tier..."
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                />
              </label>

              <div className="actions" style={{ marginTop: '16px' }}>
                <button type="submit" style={{ background: '#b91c1c' }}>
                  Confirm Rejection
                </button>
                <button type="button" className="secondary" onClick={() => setRejectingRequest(null)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
