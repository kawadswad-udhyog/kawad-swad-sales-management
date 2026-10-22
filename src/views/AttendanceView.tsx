import React, { useState, useEffect, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { apiRequest } from '../services/api';
import { PageHeader } from '../components/common/PageHeader';
import { StatusBadge } from '../components/common/StatusBadge';
import { StatCard } from '../components/common/StatCard';
import {
  UserCheck,
  Calendar,
  Search,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Plus,
  Trash2,
  Edit3,
  Users,
} from 'lucide-react';

type Row = Record<string, any>;
const today = new Date().toISOString().slice(0, 10);

export const AttendanceView: React.FC = () => {
  const { currentUser, isGoogleSheetsConnected, persistentWritesEnabled } = useStore();

  const [workers, setWorkers] = useState<Row[]>([]);
  const [attendance, setAttendance] = useState<Row[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Entry Mode state: 'bulk' (fast floor attendance) or 'individual' (single entry)
  const [entryMode, setEntryMode] = useState<'bulk' | 'individual'>('bulk');
  const [bulkStatuses, setBulkStatuses] = useState<Record<string, 'PRESENT' | 'HALF_DAY' | 'ABSENT'>>({});
  const [bulkNotes, setBulkNotes] = useState<Record<string, string>>({});

  // Form state
  const [selectedDate, setSelectedDate] = useState(today);
  const [selectedWorkerId, setSelectedWorkerId] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<'PRESENT' | 'HALF_DAY' | 'ABSENT'>('PRESENT');
  const [notes, setNotes] = useState('');

  // Editing state for corrections
  const [editingAttendance, setEditingAttendance] = useState<Row | null>(null);
  const [editStatus, setEditStatus] = useState<'PRESENT' | 'HALF_DAY' | 'ABSENT'>('PRESENT');
  const [editNotes, setEditNotes] = useState('');

  // Table search & filter
  const [searchQuery, setSearchQuery] = useState('');
  const [filterDate, setFilterDate] = useState(today);

  const isOwner = currentUser?.role === 'OWNER';

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [wRes, aRes] = await Promise.allSettled([
        apiRequest<Row[]>('/api/production/workers'),
        apiRequest<Row[]>('/api/production/attendance'),
      ]);
      if (wRes.status === 'fulfilled' && Array.isArray(wRes.value)) {
        setWorkers(wRes.value);
      }
      if (aRes.status === 'fulfilled' && Array.isArray(aRes.value)) {
        setAttendance([...aRes.value].reverse());
      }
    } catch (err) {
      console.warn('Attendance load error', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const refreshAttendanceOnly = async () => {
    try {
      const res = await apiRequest<Row[]>('/api/production/attendance');
      if (Array.isArray(res)) {
        setAttendance([...res].reverse());
      }
    } catch (err) {
      console.warn('Attendance refresh error', err);
    }
  };

  const activeWorkers = useMemo(() => {
    return workers.filter((w) => String(w.active).toLowerCase() !== 'false');
  }, [workers]);

  const selectedWorker = useMemo(() => {
    return activeWorkers.find((w) => String(w.worker_id).trim() === selectedWorkerId.trim());
  }, [activeWorkers, selectedWorkerId]);

  // Check if attendance already recorded for this worker on this date
  const existingRecordForWorker = useMemo(() => {
    if (!selectedWorkerId || !selectedDate) return null;
    return attendance.find(
      (a) =>
        String(a.worker_id || '').trim() === selectedWorkerId.trim() &&
        String(a.attendance_date || '').trim() === selectedDate.trim()
    );
  }, [attendance, selectedWorkerId, selectedDate]);

  // Handle Recording Attendance
  const handleRecordAttendance = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWorkerId) {
      setFeedback({ type: 'error', message: 'Please select a worker.' });
      return;
    }
    if (existingRecordForWorker) {
      setFeedback({
        type: 'error',
        message: `Attendance is already recorded for ${selectedWorker?.worker_name || selectedWorkerId} on ${selectedDate}. Use the correction action below to change status.`,
      });
      return;
    }

    setIsSubmitting(true);
    setFeedback(null);
    try {
      await apiRequest('/api/production/attendance', {
        method: 'POST',
        body: JSON.stringify({
          worker_id: selectedWorkerId,
          attendance_date: selectedDate,
          status: selectedStatus,
          notes,
        }),
      });
      setFeedback({
        type: 'success',
        message: `Recorded ${selectedStatus} for ${selectedWorker?.worker_name || selectedWorkerId} on ${selectedDate}.`,
      });
      setNotes('');
      // Keep worker select open for fast next entry
      await refreshAttendanceOnly();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save attendance.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Bulk helper: mark all unrecorded workers with specified status
  const markAllBulk = (status: 'PRESENT' | 'HALF_DAY' | 'ABSENT') => {
    const updated: Record<string, 'PRESENT' | 'HALF_DAY' | 'ABSENT'> = { ...bulkStatuses };
    for (const w of activeWorkers) {
      const wId = String(w.worker_id).trim();
      const already = attendance.some(
        (a) => String(a.worker_id || '').trim() === wId && String(a.attendance_date || '').trim() === selectedDate.trim()
      );
      if (!already) {
        updated[wId] = status;
      }
    }
    setBulkStatuses(updated);
  };

  // Bulk Submission Handler
  const handleRecordBulkAttendance = async (e: React.FormEvent) => {
    e.preventDefault();
    const unrecordedWorkers = activeWorkers.filter((w) => {
      const wId = String(w.worker_id).trim();
      return !attendance.some(
        (a) => String(a.worker_id || '').trim() === wId && String(a.attendance_date || '').trim() === selectedDate.trim()
      );
    });

    if (unrecordedWorkers.length === 0) {
      setFeedback({
        type: 'error',
        message: `All active workers already have attendance marked for ${selectedDate}. Use the correction action below to adjust any existing records.`,
      });
      return;
    }

    const records = unrecordedWorkers.map((w) => {
      const wId = String(w.worker_id).trim();
      return {
        worker_id: wId,
        status: bulkStatuses[wId] || 'PRESENT',
        notes: (bulkNotes[wId] || '').trim(),
      };
    });

    setIsSubmitting(true);
    setFeedback(null);
    try {
      const res = await apiRequest<{ status: string; saved_count: number; message: string }>('/api/production/attendance/bulk', {
        method: 'POST',
        body: JSON.stringify({
          attendance_date: selectedDate,
          records,
        }),
      });
      setFeedback({
        type: 'success',
        message: res?.message || `Successfully marked bulk attendance for ${records.length} workers on ${selectedDate}.`,
      });
      await refreshAttendanceOnly();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save bulk attendance.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Owner Correction
  const handleSaveCorrection = async () => {
    if (!editingAttendance) return;
    setIsSubmitting(true);
    try {
      await apiRequest(`/api/production/attendance/${encodeURIComponent(editingAttendance.attendance_id)}`, {
        method: 'PUT',
        body: JSON.stringify({
          status: editStatus,
          notes: editNotes,
        }),
      });
      setFeedback({
        type: 'success',
        message: `Attendance updated to ${editStatus} for ${editingAttendance.worker_name_snapshot || editingAttendance.worker_id}.`,
      });
      setEditingAttendance(null);
      await refreshAttendanceOnly();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Correction failed.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Remove Duplicate
  const handleRemoveDuplicate = async (attendanceId: string, workerName: string) => {
    if (!window.confirm(`Are you sure you want to remove duplicate attendance row ${attendanceId} for ${workerName}?`)) {
      return;
    }
    setIsSubmitting(true);
    try {
      await apiRequest(`/api/production/attendance/${encodeURIComponent(attendanceId)}`, {
        method: 'DELETE',
      });
      setFeedback({ type: 'success', message: `Duplicate attendance entry removed.` });
      await refreshAttendanceOnly();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to remove duplicate.';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Metrics for selected work date
  const dateRecords = attendance.filter((a) => String(a.attendance_date || '').trim() === filterDate.trim());
  const presentCount = dateRecords.filter((a) => a.status === 'PRESENT').length;
  const halfDayCount = dateRecords.filter((a) => a.status === 'HALF_DAY').length;
  const absentCount = dateRecords.filter((a) => a.status === 'ABSENT').length;
  const totalWageAccrued = dateRecords.reduce((sum, a) => sum + (Number(a.wage_accrued) || 0), 0);

  // Filtered table rows
  const filteredRows = attendance.filter((a) => {
    const matchesDate = filterDate ? String(a.attendance_date || '').trim() === filterDate.trim() : true;
    const matchesQuery = searchQuery
      ? String(a.worker_name_snapshot || a.worker_id || '')
          .toLowerCase()
          .includes(searchQuery.toLowerCase())
      : true;
    return matchesDate && matchesQuery;
  });

  return (
    <div>
      <PageHeader
        title="Worker Attendance & Wages"
        subtitle="Quick daily floor attendance entry, duplicate safeguards, and daily wage accruals."
        icon={<UserCheck size={22} />}
        actions={
          <button
            onClick={loadData}
            disabled={isLoading}
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
              cursor: isLoading ? 'not-allowed' : 'pointer',
            }}
          >
            <RefreshCw size={14} className={isLoading ? 'spin-icon' : ''} />
            Refresh
          </button>
        }
      />

      {/* Top Stat Cards for Selected Filter Date */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px', marginBottom: '20px' }}>
        <StatCard
          title={`Total Workers on ${filterDate}`}
          value={dateRecords.length}
          subtext={`Out of ${activeWorkers.length} active workers`}
          icon={<Users size={18} />}
        />
        <StatCard
          title="Present & Half Day"
          value={`${presentCount} Full / ${halfDayCount} Half`}
          subtext={`Total attendance logged`}
          icon={<CheckCircle2 size={18} />}
          iconBg="#ecfdf5"
          iconColor="#15803d"
        />
        <StatCard
          title="Reported Absent"
          value={absentCount}
          subtext="No wage accrued"
          icon={<AlertTriangle size={18} />}
          iconBg="#fef2f2"
          iconColor="#b91c1c"
        />
        <StatCard
          title="Total Wages Accrued"
          value={`₹${totalWageAccrued.toFixed(2)}`}
          subtext={`Daily wage payout commitment`}
          icon={<Calendar size={18} />}
          iconBg="#eff6ff"
          iconColor="#1d4ed8"
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

      {/* ATTENDANCE ENTRY CONTAINER (BULK & INDIVIDUAL MODES) */}
      <div
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          borderRadius: '12px',
          padding: '20px',
          marginBottom: '24px',
          boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
        }}
      >
        {/* Header with Mode Switcher */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '12px',
            marginBottom: '18px',
            paddingBottom: '14px',
            borderBottom: '1px solid #f1f5f9',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <UserCheck size={20} color="#166534" />
            <h2 style={{ margin: 0, fontSize: '1.15rem', color: '#0f172a' }}>
              {entryMode === 'bulk' ? 'Bulk Floor Attendance' : 'Quick Single Attendance'}
            </h2>
          </div>

          {/* Mode Switcher Tabs */}
          <div style={{ display: 'flex', gap: '6px', background: '#f1f5f9', padding: '4px', borderRadius: '8px' }}>
            <button
              type="button"
              onClick={() => setEntryMode('bulk')}
              style={{
                padding: '6px 14px',
                borderRadius: '6px',
                border: 'none',
                background: entryMode === 'bulk' ? '#ffffff' : 'transparent',
                color: entryMode === 'bulk' ? '#166534' : '#64748b',
                fontWeight: entryMode === 'bulk' ? 700 : 500,
                fontSize: '0.84rem',
                cursor: 'pointer',
                boxShadow: entryMode === 'bulk' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
              }}
            >
              👥 Bulk Attendance ({activeWorkers.length} Workers)
            </button>
            <button
              type="button"
              onClick={() => setEntryMode('individual')}
              style={{
                padding: '6px 14px',
                borderRadius: '6px',
                border: 'none',
                background: entryMode === 'individual' ? '#ffffff' : 'transparent',
                color: entryMode === 'individual' ? '#166534' : '#64748b',
                fontWeight: entryMode === 'individual' ? 700 : 500,
                fontSize: '0.84rem',
                cursor: 'pointer',
                boxShadow: entryMode === 'individual' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
              }}
            >
              👤 Quick Single Entry
            </button>
          </div>
        </div>

        {/* BULK ENTRY MODE */}
        {entryMode === 'bulk' && (
          <form onSubmit={handleRecordBulkAttendance}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <label style={{ fontSize: '0.84rem', fontWeight: 600, color: '#334155' }}>Attendance Date:</label>
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  required
                  style={{
                    padding: '7px 12px',
                    borderRadius: '7px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.88rem',
                  }}
                />
              </div>

              {/* Quick Batch Actions */}
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.80rem', color: '#64748b', fontWeight: 500 }}>Quick Mark:</span>
                <button
                  type="button"
                  onClick={() => markAllBulk('PRESENT')}
                  style={{
                    padding: '5px 12px',
                    borderRadius: '6px',
                    border: '1px solid #bbf7d0',
                    background: '#f0fdf4',
                    color: '#166534',
                    fontSize: '0.80rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  ✓ All Present
                </button>
                <button
                  type="button"
                  onClick={() => markAllBulk('HALF_DAY')}
                  style={{
                    padding: '5px 12px',
                    borderRadius: '6px',
                    border: '1px solid #fde68a',
                    background: '#fffbeb',
                    color: '#b45309',
                    fontSize: '0.80rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  ½ All Half Day
                </button>
                <button
                  type="button"
                  onClick={() => markAllBulk('ABSENT')}
                  style={{
                    padding: '5px 12px',
                    borderRadius: '6px',
                    border: '1px solid #e2e8f0',
                    background: '#f8fafc',
                    color: '#475569',
                    fontSize: '0.80rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  ✗ All Absent
                </button>
              </div>
            </div>

            {/* Bulk Worker Table */}
            <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: '8px', marginBottom: '16px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                <thead>
                  <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', textAlign: 'left', color: '#475569' }}>
                    <th style={{ padding: '10px 14px' }}>Worker Name</th>
                    <th style={{ padding: '10px 14px' }}>Daily Rate</th>
                    <th style={{ padding: '10px 14px', minWidth: '220px' }}>Today's Status</th>
                    <th style={{ padding: '10px 14px' }}>Day Wage</th>
                    <th style={{ padding: '10px 14px', minWidth: '160px' }}>Shift Notes</th>
                    <th style={{ padding: '10px 14px' }}>Record State</th>
                  </tr>
                </thead>
                <tbody>
                  {activeWorkers.map((w) => {
                    const wId = String(w.worker_id).trim();
                    const existing = attendance.find(
                      (a) => String(a.worker_id || '').trim() === wId && String(a.attendance_date || '').trim() === selectedDate.trim()
                    );
                    const currentStatus = bulkStatuses[wId] || 'PRESENT';
                    const dailyWage = Number(w.daily_wage) || 0;
                    const calculatedWage = currentStatus === 'PRESENT' ? dailyWage : currentStatus === 'HALF_DAY' ? dailyWage * 0.5 : 0;

                    return (
                      <tr
                        key={wId}
                        style={{
                          borderBottom: '1px solid #f1f5f9',
                          background: existing ? '#f8fafc' : '#ffffff',
                          opacity: existing ? 0.75 : 1,
                        }}
                      >
                        <td style={{ padding: '10px 14px', fontWeight: 600, color: '#1e293b' }}>
                          {w.worker_name}
                          <div style={{ fontSize: '0.74rem', color: '#64748b', fontWeight: 400 }}>{wId}</div>
                        </td>
                        <td style={{ padding: '10px 14px', color: '#475569' }}>
                          ₹{dailyWage}/day
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          {existing ? (
                            <span style={{ fontSize: '0.82rem', fontWeight: 600, color: existing.status === 'PRESENT' ? '#166534' : existing.status === 'HALF_DAY' ? '#b45309' : '#64748b' }}>
                              Locked ({existing.status})
                            </span>
                          ) : (
                            <div style={{ display: 'flex', gap: '4px' }}>
                              <button
                                type="button"
                                onClick={() => setBulkStatuses({ ...bulkStatuses, [wId]: 'PRESENT' })}
                                style={{
                                  padding: '5px 10px',
                                  borderRadius: '5px',
                                  border: currentStatus === 'PRESENT' ? '2px solid #166534' : '1px solid #cbd5e1',
                                  background: currentStatus === 'PRESENT' ? '#ecfdf5' : '#ffffff',
                                  color: currentStatus === 'PRESENT' ? '#166534' : '#64748b',
                                  fontWeight: currentStatus === 'PRESENT' ? 700 : 500,
                                  fontSize: '0.78rem',
                                  cursor: 'pointer',
                                }}
                              >
                                ✓ Present
                              </button>
                              <button
                                type="button"
                                onClick={() => setBulkStatuses({ ...bulkStatuses, [wId]: 'HALF_DAY' })}
                                style={{
                                  padding: '5px 10px',
                                  borderRadius: '5px',
                                  border: currentStatus === 'HALF_DAY' ? '2px solid #b45309' : '1px solid #cbd5e1',
                                  background: currentStatus === 'HALF_DAY' ? '#fffbeb' : '#ffffff',
                                  color: currentStatus === 'HALF_DAY' ? '#b45309' : '#64748b',
                                  fontWeight: currentStatus === 'HALF_DAY' ? 700 : 500,
                                  fontSize: '0.78rem',
                                  cursor: 'pointer',
                                }}
                              >
                                ½ Half Day
                              </button>
                              <button
                                type="button"
                                onClick={() => setBulkStatuses({ ...bulkStatuses, [wId]: 'ABSENT' })}
                                style={{
                                  padding: '5px 10px',
                                  borderRadius: '5px',
                                  border: currentStatus === 'ABSENT' ? '2px solid #64748b' : '1px solid #cbd5e1',
                                  background: currentStatus === 'ABSENT' ? '#f1f5f9' : '#ffffff',
                                  color: currentStatus === 'ABSENT' ? '#0f172a' : '#64748b',
                                  fontWeight: currentStatus === 'ABSENT' ? 700 : 500,
                                  fontSize: '0.78rem',
                                  cursor: 'pointer',
                                }}
                              >
                                ✗ Absent
                              </button>
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '10px 14px', fontWeight: 600, color: existing ? '#64748b' : '#166534' }}>
                          ₹{existing ? (existing.wage_accrued || 0) : calculatedWage.toFixed(2)}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          {existing ? (
                            <span style={{ fontSize: '0.78rem', color: '#64748b' }}>{existing.notes || '—'}</span>
                          ) : (
                            <input
                              type="text"
                              placeholder="Notes"
                              value={bulkNotes[wId] || ''}
                              onChange={(e) => setBulkNotes({ ...bulkNotes, [wId]: e.target.value })}
                              style={{
                                width: '100%',
                                padding: '5px 8px',
                                borderRadius: '5px',
                                border: '1px solid #cbd5e1',
                                fontSize: '0.80rem',
                                boxSizing: 'border-box',
                              }}
                            />
                          )}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          {existing ? (
                            <span
                              style={{
                                display: 'inline-block',
                                padding: '3px 8px',
                                borderRadius: '4px',
                                background: '#fef3c7',
                                color: '#92400e',
                                fontSize: '0.74rem',
                                fontWeight: 600,
                              }}
                            >
                              Already Saved
                            </span>
                          ) : (
                            <span
                              style={{
                                display: 'inline-block',
                                padding: '3px 8px',
                                borderRadius: '4px',
                                background: '#dcfce7',
                                color: '#166534',
                                fontSize: '0.74rem',
                                fontWeight: 600,
                              }}
                            >
                              Ready to Post
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Bulk Submission Footer */}
            {(() => {
              const unrecordedWorkers = activeWorkers.filter((w) => {
                const wId = String(w.worker_id).trim();
                return !attendance.some(
                  (a) => String(a.worker_id || '').trim() === wId && String(a.attendance_date || '').trim() === selectedDate.trim()
                );
              });
              const presentCount = unrecordedWorkers.filter((w) => (bulkStatuses[String(w.worker_id).trim()] || 'PRESENT') === 'PRESENT').length;
              const halfCount = unrecordedWorkers.filter((w) => (bulkStatuses[String(w.worker_id).trim()] || 'PRESENT') === 'HALF_DAY').length;
              const absentCount = unrecordedWorkers.filter((w) => (bulkStatuses[String(w.worker_id).trim()] || 'PRESENT') === 'ABSENT').length;
              const wageCommitment = unrecordedWorkers.reduce((acc, w) => {
                const st = bulkStatuses[String(w.worker_id).trim()] || 'PRESENT';
                const dw = Number(w.daily_wage) || 0;
                return acc + (st === 'PRESENT' ? dw : st === 'HALF_DAY' ? dw * 0.5 : 0);
              }, 0);

              return (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
                  <div style={{ fontSize: '0.84rem', color: '#475569' }}>
                    Marking <b>{unrecordedWorkers.length}</b> workers on {selectedDate}:{' '}
                    <span style={{ color: '#166534', fontWeight: 600 }}>{presentCount} Present</span> ·{' '}
                    <span style={{ color: '#b45309', fontWeight: 600 }}>{halfCount} Half Day</span> ·{' '}
                    <span style={{ color: '#64748b', fontWeight: 600 }}>{absentCount} Absent</span> · Accrued Wage:{' '}
                    <strong style={{ color: '#166534' }}>₹{wageCommitment.toFixed(2)}</strong>
                  </div>

                  <button
                    type="submit"
                    disabled={isSubmitting || unrecordedWorkers.length === 0 || !isGoogleSheetsConnected || !persistentWritesEnabled}
                    style={{
                      padding: '10px 24px',
                      borderRadius: '8px',
                      border: 'none',
                      background: unrecordedWorkers.length === 0 || !isGoogleSheetsConnected || !persistentWritesEnabled ? '#94a3b8' : '#166534',
                      color: '#ffffff',
                      fontWeight: 700,
                      fontSize: '0.90rem',
                      cursor: unrecordedWorkers.length === 0 || isSubmitting || !isGoogleSheetsConnected || !persistentWritesEnabled ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                    }}
                  >
                    <UserCheck size={16} />
                    {isSubmitting
                      ? 'Saving Bulk Attendance…'
                      : unrecordedWorkers.length === 0
                      ? 'All Active Workers Already Marked'
                      : `Save Bulk Attendance (${unrecordedWorkers.length} Workers)`}
                  </button>
                </div>
              );
            })()}
          </form>
        )}

        {/* INDIVIDUAL ENTRY MODE */}
        {entryMode === 'individual' && (
          <form onSubmit={handleRecordAttendance}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: '14px',
                alignItems: 'flex-start',
              }}
            >
              {/* Work Date */}
              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                  Work Date *
                </label>
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '8px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.90rem',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              {/* Worker Selector */}
              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                  Select Worker *
                </label>
                <select
                  value={selectedWorkerId}
                  onChange={(e) => setSelectedWorkerId(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '8px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.90rem',
                    boxSizing: 'border-box',
                    background: '#ffffff',
                  }}
                >
                  <option value="">-- Choose Worker --</option>
                  {activeWorkers.map((w) => (
                    <option key={w.worker_id} value={w.worker_id}>
                      {w.worker_name} (₹{w.daily_wage || 0}/day)
                    </option>
                  ))}
                </select>
              </div>

              {/* Status Selection Buttons */}
              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                  Attendance Status *
                </label>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    type="button"
                    onClick={() => setSelectedStatus('PRESENT')}
                    style={{
                      flex: 1,
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: selectedStatus === 'PRESENT' ? '2px solid #166534' : '1px solid #cbd5e1',
                      background: selectedStatus === 'PRESENT' ? '#ecfdf5' : '#ffffff',
                      color: selectedStatus === 'PRESENT' ? '#166534' : '#475569',
                      fontWeight: selectedStatus === 'PRESENT' ? 700 : 500,
                      fontSize: '0.82rem',
                      cursor: 'pointer',
                    }}
                  >
                    ✓ Present
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedStatus('HALF_DAY')}
                    style={{
                      flex: 1,
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: selectedStatus === 'HALF_DAY' ? '2px solid #b45309' : '1px solid #cbd5e1',
                      background: selectedStatus === 'HALF_DAY' ? '#fffbeb' : '#ffffff',
                      color: selectedStatus === 'HALF_DAY' ? '#b45309' : '#475569',
                      fontWeight: selectedStatus === 'HALF_DAY' ? 700 : 500,
                      fontSize: '0.82rem',
                      cursor: 'pointer',
                    }}
                  >
                    ½ Half Day
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedStatus('ABSENT')}
                    style={{
                      flex: 1,
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: selectedStatus === 'ABSENT' ? '2px solid #64748b' : '1px solid #cbd5e1',
                      background: selectedStatus === 'ABSENT' ? '#f1f5f9' : '#ffffff',
                      color: selectedStatus === 'ABSENT' ? '#0f172a' : '#475569',
                      fontWeight: selectedStatus === 'ABSENT' ? 700 : 500,
                      fontSize: '0.82rem',
                      cursor: 'pointer',
                    }}
                  >
                    ✗ Absent
                  </button>
                </div>
              </div>

              {/* Notes Input */}
              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                  Shift / Shift Notes (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Morning rolling shift"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '8px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.90rem',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Inline Duplicate Warning Badge */}
            {existingRecordForWorker && (
              <div
                style={{
                  marginTop: '14px',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: '#fffbeb',
                  border: '1px solid #fde68a',
                  color: '#92400e',
                  fontSize: '0.84rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <AlertTriangle size={16} />
                <span>
                  <strong>Attendance Already Recorded:</strong> {existingRecordForWorker.worker_name_snapshot || selectedWorker?.worker_name} is marked as{' '}
                  <strong>{existingRecordForWorker.status}</strong> on {selectedDate} (₹{existingRecordForWorker.wage_accrued || 0}).
                  Use the correction button in the table below if status needs adjustment.
                </span>
              </div>
            )}

            {/* Action Row */}
            <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'flex-end', gap: '10px', alignItems: 'center' }}>
              {selectedWorker && !existingRecordForWorker && (
                <span style={{ fontSize: '0.84rem', color: '#475569' }}>
                  Accrued wage for {selectedStatus}:{' '}
                  <strong style={{ color: '#166534' }}>
                    ₹{selectedStatus === 'PRESENT' ? selectedWorker.daily_wage : selectedStatus === 'HALF_DAY' ? (selectedWorker.daily_wage || 0) * 0.5 : 0}
                  </strong>
                </span>
              )}

              <button
                type="submit"
                disabled={isSubmitting || Boolean(existingRecordForWorker) || !isGoogleSheetsConnected || !persistentWritesEnabled}
                style={{
                  padding: '10px 22px',
                  borderRadius: '8px',
                  border: 'none',
                  background: Boolean(existingRecordForWorker) || !isGoogleSheetsConnected || !persistentWritesEnabled ? '#94a3b8' : '#166534',
                  color: '#ffffff',
                  fontWeight: 700,
                  fontSize: '0.90rem',
                  cursor: Boolean(existingRecordForWorker) || isSubmitting || !isGoogleSheetsConnected || !persistentWritesEnabled ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <UserCheck size={16} />
                {isSubmitting ? 'Saving Attendance…' : 'Record Attendance'}
              </button>
            </div>
          </form>
        )}
      </div>

      {/* OWNER CORRECTION MODAL */}
      {editingAttendance && (
        <div
          onClick={() => setEditingAttendance(null)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.45)',
            zIndex: 50,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '16px',
            backdropFilter: 'blur(2px)',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#ffffff',
              borderRadius: '14px',
              maxWidth: '460px',
              width: '100%',
              padding: '22px',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
              border: '1px solid #e2e8f0',
            }}
          >
            <h3 style={{ margin: '0 0 14px', fontSize: '1.10rem', color: '#0f172a' }}>
              Correct Attendance: {editingAttendance.worker_name_snapshot || editingAttendance.worker_id}
            </h3>
            <p style={{ fontSize: '0.84rem', color: '#64748b', margin: '0 0 14px' }}>
              Date: <strong>{editingAttendance.attendance_date}</strong> · Original Status:{' '}
              <strong>{editingAttendance.status}</strong>
            </p>

            <div style={{ marginBottom: '14px' }}>
              <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                New Status *
              </label>
              <select
                value={editStatus}
                onChange={(e) => setEditStatus(e.target.value as any)}
                style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '0.90rem' }}
              >
                <option value="PRESENT">PRESENT (Full Day Wage)</option>
                <option value="HALF_DAY">HALF_DAY (Half Wage)</option>
                <option value="ABSENT">ABSENT (Zero Wage)</option>
              </select>
            </div>

            <div style={{ marginBottom: '18px' }}>
              <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                Correction Reason (Mandatory Audit Note) *
              </label>
              <input
                type="text"
                placeholder="e.g. Supervisor verified morning presence"
                value={editNotes}
                onChange={(e) => setEditNotes(e.target.value)}
                required
                style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '0.90rem', boxSizing: 'border-box' }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                type="button"
                onClick={() => setEditingAttendance(null)}
                style={{ padding: '8px 14px', borderRadius: '7px', border: '1px solid #cbd5e1', background: '#f8fafc', color: '#475569', cursor: 'pointer', fontWeight: 600 }}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isSubmitting || !editNotes.trim()}
                onClick={handleSaveCorrection}
                style={{ padding: '8px 16px', borderRadius: '7px', border: 'none', background: '#0284c7', color: '#ffffff', cursor: 'pointer', fontWeight: 700 }}
              >
                {isSubmitting ? 'Saving…' : 'Save Correction'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ATTENDANCE RECORDS TABLE */}
      <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <h3 style={{ margin: 0, fontSize: '1.05rem', color: '#0f172a' }}>Attendance Log ({filteredRows.length})</h3>

          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', color: '#475569' }}>
              <span>Filter Date:</span>
              <input
                type="date"
                value={filterDate}
                onChange={(e) => setFilterDate(e.target.value)}
                style={{ padding: '6px 10px', borderRadius: '7px', border: '1px solid #cbd5e1', fontSize: '0.84rem' }}
              />
              {filterDate && (
                <button
                  type="button"
                  onClick={() => setFilterDate('')}
                  style={{ background: 'transparent', border: 'none', color: '#0284c7', cursor: 'pointer', fontSize: '0.78rem' }}
                >
                  View All Dates
                </button>
              )}
            </div>

            <div style={{ position: 'relative' }}>
              <input
                type="text"
                placeholder="Search worker name…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ padding: '6px 10px 6px 30px', borderRadius: '7px', border: '1px solid #cbd5e1', fontSize: '0.84rem', width: '180px' }}
              />
              <Search size={14} style={{ position: 'absolute', left: 9, top: 10, color: '#94a3b8' }} />
            </div>
          </div>
        </div>

        {filteredRows.length === 0 ? (
          <div style={{ padding: '36px 16px', textAlign: 'center', color: '#64748b', fontSize: '0.90rem' }}>
            No attendance records found for the selected filter.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.86rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', textAlign: 'left' }}>
                  <th style={{ padding: '10px 12px' }}>Date</th>
                  <th style={{ padding: '10px 12px' }}>Worker</th>
                  <th style={{ padding: '10px 12px' }}>Status</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right' }}>Daily Wage</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right' }}>Accrued Wage</th>
                  <th style={{ padding: '10px 12px' }}>Notes</th>
                  <th style={{ padding: '10px 12px' }}>Entered By</th>
                  {isOwner && <th style={{ padding: '10px 12px', textAlign: 'center' }}>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((a, idx) => (
                  <tr key={a.attendance_id || idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '10px 12px', color: '#0f172a', fontWeight: 500 }}>{a.attendance_date}</td>
                    <td style={{ padding: '10px 12px', fontWeight: 600 }}>
                      {a.worker_name_snapshot || a.worker_id}
                      {a.is_duplicate && (
                        <span
                          style={{
                            marginLeft: 8,
                            padding: '2px 6px',
                            background: '#fee2e2',
                            color: '#b91c1c',
                            borderRadius: 4,
                            fontSize: '0.70rem',
                            fontWeight: 700,
                          }}
                        >
                          Duplicate in Sheet
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <StatusBadge status={a.status} />
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right', color: '#64748b' }}>
                      ₹{a.daily_wage_snapshot || 0}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 700, color: '#166534' }}>
                      ₹{a.wage_accrued || 0}
                    </td>
                    <td style={{ padding: '10px 12px', color: '#64748b', fontSize: '0.80rem' }}>{a.notes || '-'}</td>
                    <td style={{ padding: '10px 12px', color: '#64748b', fontSize: '0.80rem' }}>{a.created_by || '-'}</td>
                    {isOwner && (
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                          <button
                            type="button"
                            onClick={() => {
                              setEditingAttendance(a);
                              setEditStatus(a.status || 'PRESENT');
                              setEditNotes('');
                            }}
                            style={{
                              padding: '4px 8px',
                              borderRadius: '6px',
                              border: '1px solid #bae6fd',
                              background: '#f0f9ff',
                              color: '#0369a1',
                              fontSize: '0.76rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px',
                            }}
                            title="Correct attendance status or notes"
                          >
                            <Edit3 size={12} /> Correct
                          </button>
                          {a.is_duplicate && (
                            <button
                              type="button"
                              onClick={() => handleRemoveDuplicate(a.attendance_id, a.worker_name_snapshot || a.worker_id)}
                              style={{
                                padding: '4px 8px',
                                borderRadius: '6px',
                                border: '1px solid #fecaca',
                                background: '#fef2f2',
                                color: '#b91c1c',
                                fontSize: '0.76rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                              }}
                              title="Delete redundant duplicate row from Google Sheets"
                            >
                              <Trash2 size={12} /> Duplicate
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
