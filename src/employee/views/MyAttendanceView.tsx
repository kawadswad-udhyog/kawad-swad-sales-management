import React, { useState, useEffect } from 'react';
import { useStore } from '../../context/StoreContext';
import { apiFetch } from '../../services/api';
import { AttendanceItem } from '../types';
import {
  Clock,
  CheckCircle2,
  Calendar,
  AlertCircle,
  Coffee,
  Check,
} from 'lucide-react';

export const MyAttendanceView: React.FC = () => {
  const { currentUser } = useStore();
  const [attendances, setAttendances] = useState<AttendanceItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [clockLoading, setClockLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [notes, setNotes] = useState('');

  const fetchAttendance = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch('/api/workforce/my-attendance');
      if (res.ok) {
        const data = await res.json();
        setAttendances(data);
      }
    } catch (err) {
      console.error('Failed to load attendance:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAttendance();
  }, []);

  const todayStr = new Date().toISOString().slice(0, 10);
  const todayRecord = attendances.find((a) => a.attendance_date === todayStr);

  const handleCheckIn = async () => {
    setClockLoading(true);
    setStatusMessage('');
    try {
      const res = await apiFetch('/api/workforce/my-attendance/check-in', {
        method: 'POST',
        body: JSON.stringify({ notes: notes || 'Staff self-check-in' }),
      });
      const data = await res.json();
      if (res.ok) {
        setStatusMessage(data.message || 'Checked in successfully!');
        setNotes('');
        await fetchAttendance();
      } else {
        setStatusMessage(data.detail || 'Failed to check in.');
      }
    } catch (err) {
      setStatusMessage('Network error during check-in.');
    } finally {
      setClockLoading(false);
    }
  };

  const handleCheckOut = async () => {
    setClockLoading(true);
    setStatusMessage('');
    try {
      const res = await apiFetch('/api/workforce/my-attendance/check-out', {
        method: 'POST',
        body: JSON.stringify({ notes: notes || 'Clock-out' }),
      });
      const data = await res.json();
      if (res.ok) {
        setStatusMessage(data.message || 'Checked out successfully!');
        setNotes('');
        await fetchAttendance();
      } else {
        setStatusMessage(data.detail || 'Failed to check out.');
      }
    } catch (err) {
      setStatusMessage('Network error during clock-out.');
    } finally {
      setClockLoading(false);
    }
  };

  // Stats
  const thisMonthStr = todayStr.slice(0, 7);
  const thisMonthRecords = attendances.filter((a) => a.attendance_date.startsWith(thisMonthStr));
  const daysPresent = thisMonthRecords.filter((a) => a.status === 'PRESENT').length;
  const totalHoursWorked = thisMonthRecords.reduce((sum, a) => sum + (Number(a.total_hours) || 0), 0);

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-black text-slate-900 m-0">
            Attendance & Daily Punch
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Real-time daily punch-in/out records for payroll verification.
          </p>
        </div>
        <div className="text-xs text-slate-500 font-medium bg-white px-3 py-1.5 rounded-lg border border-slate-200">
          Today: <strong className="text-slate-800">{todayStr}</strong>
        </div>
      </div>

      {/* Clock-in Hero Card */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs p-6">
        <div className="max-w-xl mx-auto text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-emerald-50 text-emerald-700 flex items-center justify-center mx-auto shadow-inner">
            <Clock size={28} />
          </div>

          <div>
            <h2 className="text-base font-bold text-slate-900 m-0">
              {todayRecord ? (todayRecord.check_out_time ? 'Day Completed' : 'Currently Clocked In') : 'Ready to Start Work'}
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              {todayRecord
                ? `Clocked in at ${todayRecord.check_in_time}${todayRecord.check_out_time ? ` • Clocked out at ${todayRecord.check_out_time}` : ''}`
                : 'Click below to punch your official attendance for today.'}
            </p>
          </div>

          {statusMessage && (
            <div className="p-3 rounded-xl bg-emerald-50 text-emerald-800 text-xs border border-emerald-200">
              {statusMessage}
            </div>
          )}

          {!todayRecord ? (
            <div className="space-y-3">
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Optional daily note (e.g. Route / Station / Task)…"
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600 text-center"
              />
              <button
                onClick={handleCheckIn}
                disabled={clockLoading}
                className="w-full sm:w-auto px-8 py-3 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-sm transition-all cursor-pointer disabled:opacity-50 inline-flex items-center justify-center gap-2"
              >
                <CheckCircle2 size={16} />
                <span>{clockLoading ? 'Clocking in…' : 'Punch In for Today'}</span>
              </button>
            </div>
          ) : !todayRecord.check_out_time ? (
            <div className="space-y-3">
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Optional sign-off notes…"
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600 text-center"
              />
              <button
                onClick={handleCheckOut}
                disabled={clockLoading}
                className="w-full sm:w-auto px-8 py-3 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs shadow-sm transition-all cursor-pointer disabled:opacity-50 inline-flex items-center justify-center gap-2"
              >
                <Coffee size={16} />
                <span>{clockLoading ? 'Clocking out…' : 'Clock Out for the Day'}</span>
              </button>
            </div>
          ) : (
            <div className="p-3 rounded-xl bg-slate-50 text-slate-700 text-xs font-semibold border border-slate-200 inline-block">
              ✓ Day verified: {todayRecord.total_hours || 8} hours logged
            </div>
          )}
        </div>
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            This Month Days Present
          </div>
          <div className="text-2xl font-black text-slate-900 mt-1">
            {daysPresent} Days
          </div>
          <p className="text-[11px] text-slate-400 mt-1">In {thisMonthStr}</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Total Hours Logged
          </div>
          <div className="text-2xl font-black text-slate-900 mt-1">
            {totalHoursWorked.toFixed(1)} Hrs
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Regular & approved overtime</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Attendance Rate
          </div>
          <div className="text-2xl font-black text-slate-900 mt-1">
            {thisMonthRecords.length > 0 ? `${Math.round((daysPresent / thisMonthRecords.length) * 100)}%` : '100%'}
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Official verified presence</p>
        </div>
      </div>

      {/* Attendance History Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-900 m-0">Recent Attendance History</h3>
          <span className="text-xs text-slate-500">{attendances.length} records</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
              <tr>
                <th className="py-3 px-4">Date</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Clock In</th>
                <th className="py-3 px-4">Clock Out</th>
                <th className="py-3 px-4 text-right">Hours Logged</th>
                <th className="py-3 px-4">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-400">Loading attendance history…</td>
                </tr>
              ) : attendances.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-400">No attendance records found.</td>
                </tr>
              ) : (
                attendances.map((att) => (
                  <tr key={att.attendance_id || att.attendance_date} className="hover:bg-slate-50/60">
                    <td className="py-3 px-4 font-semibold text-slate-900">
                      {att.attendance_date}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                          att.status === 'PRESENT'
                            ? 'bg-emerald-100 text-emerald-800'
                            : att.status === 'HALF_DAY'
                            ? 'bg-amber-100 text-amber-800'
                            : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {att.status}
                      </span>
                    </td>
                    <td className="py-3 px-4 font-medium">{att.check_in_time || '--'}</td>
                    <td className="py-3 px-4 font-medium">{att.check_out_time || '--'}</td>
                    <td className="py-3 px-4 text-right font-bold text-slate-900">
                      {att.total_hours ? `${att.total_hours} hrs` : '--'}
                    </td>
                    <td className="py-3 px-4 text-slate-500 max-w-xs truncate">
                      {att.notes || '--'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
