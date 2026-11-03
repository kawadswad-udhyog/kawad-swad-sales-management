import React, { useState, useEffect } from 'react';
import { useStore } from '../../context/StoreContext';
import { apiFetch } from '../../services/api';
import { EmployeeViewType, TaskItem } from '../types';
import {
  Clock,
  CheckCircle2,
  Calendar,
  AlertCircle,
  FileCheck,
  Briefcase,
  TrendingUp,
  Download,
  ArrowRight,
  ShieldCheck,
  CheckSquare,
} from 'lucide-react';
import { generateSalaryReceiptPdf } from '../../utils/generateSalaryReceiptPdf';

interface EmployeeOverviewViewProps {
  onNavigate: (view: EmployeeViewType) => void;
}

export const EmployeeOverviewView: React.FC<EmployeeOverviewViewProps> = ({ onNavigate }) => {
  const { currentUser } = useStore();
  const [workspace, setWorkspace] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [clockActionLoading, setClockActionLoading] = useState(false);
  const [clockMessage, setClockMessage] = useState('');

  const fetchWorkspace = async () => {
    try {
      const res = await apiFetch('/api/workforce/my-workspace');
      if (res.ok) {
        const data = await res.json();
        setWorkspace(data);
      }
    } catch (err) {
      console.error('Failed to load workspace data:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchWorkspace();
  }, []);

  const handleCheckIn = async () => {
    setClockActionLoading(true);
    setClockMessage('');
    try {
      const res = await apiFetch('/api/workforce/my-attendance/check-in', {
        method: 'POST',
        body: JSON.stringify({ notes: 'Self check-in from web portal' }),
      });
      const data = await res.json();
      if (res.ok) {
        setClockMessage(data.message || 'Checked in successfully!');
        await fetchWorkspace();
      } else {
        setClockMessage(data.detail || 'Failed to check in.');
      }
    } catch (err) {
      setClockMessage('Network error during check-in.');
    } finally {
      setClockActionLoading(false);
    }
  };

  const handleCheckOut = async () => {
    setClockActionLoading(true);
    setClockMessage('');
    try {
      const res = await apiFetch('/api/workforce/my-attendance/check-out', {
        method: 'POST',
        body: JSON.stringify({ notes: 'Clock-out from portal' }),
      });
      const data = await res.json();
      if (res.ok) {
        setClockMessage(data.message || 'Checked out successfully!');
        await fetchWorkspace();
      } else {
        setClockMessage(data.detail || 'Failed to check out.');
      }
    } catch (err) {
      setClockMessage('Network error during check-out.');
    } finally {
      setClockActionLoading(false);
    }
  };

  const role = (currentUser?.role || '').toUpperCase();
  const todayAtt = workspace?.today_attendance;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header Banner */}
      <div className="bg-gradient-to-r from-emerald-900 via-slate-900 to-slate-950 rounded-2xl p-6 text-white shadow-sm border border-emerald-800/40 relative overflow-hidden">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs px-2.5 py-1 rounded-full mb-3">
              <ShieldCheck size={14} />
              <span>Role-Isolated Staff Workspace</span>
            </div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-white m-0">
              Welcome back, {currentUser?.full_name || 'Team Member'}
            </h1>
            <p className="text-xs sm:text-sm text-slate-300 mt-1 max-w-xl">
              {workspace?.designation || role} • Kawad Swad Udhyog Bikaner. Here is your daily task agenda, attendance status, and verified earnings.
            </p>
          </div>

          {/* Quick Clock-in Widget */}
          <div className="bg-slate-800/80 backdrop-blur-xs p-4 rounded-xl border border-slate-700/80 shrink-0 min-w-[260px]">
            <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span className="flex items-center gap-1.5 font-medium">
                <Clock size={14} className="text-emerald-400" />
                Today's Attendance
              </span>
              <span className="font-semibold text-slate-300">
                {new Date().toISOString().slice(0, 10)}
              </span>
            </div>

            {todayAtt ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs bg-slate-900/60 p-2 rounded-lg border border-slate-700">
                  <span className="text-slate-400">In: <strong className="text-emerald-400">{todayAtt.check_in_time || '--'}</strong></span>
                  <span className="text-slate-400">Out: <strong className="text-slate-200">{todayAtt.check_out_time || 'Working'}</strong></span>
                </div>
                {!todayAtt.check_out_time ? (
                  <button
                    onClick={handleCheckOut}
                    disabled={clockActionLoading}
                    className="w-full py-2 px-3 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-semibold text-xs transition-colors cursor-pointer disabled:opacity-50"
                  >
                    {clockActionLoading ? 'Recording…' : 'Clock Out for Today'}
                  </button>
                ) : (
                  <div className="text-center text-xs text-emerald-400 font-semibold py-1">
                    ✓ Day Completed ({todayAtt.total_hours || 8} hrs logged)
                  </div>
                )}
              </div>
            ) : (
              <button
                onClick={handleCheckIn}
                disabled={clockActionLoading}
                className="w-full py-2.5 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs shadow-sm transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <CheckCircle2 size={16} />
                <span>{clockActionLoading ? 'Clocking in…' : 'Clock In for Today'}</span>
              </button>
            )}

            {clockMessage && (
              <div className="text-[11px] text-emerald-300 mt-2 text-center">
                {clockMessage}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 2. Role-Specific KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Pending Tasks</span>
            <CheckSquare size={18} className="text-blue-600" />
          </div>
          <div className="text-2xl font-black text-slate-900">
            {workspace?.pending_tasks_count ?? 0}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Open assignments needing action</p>
        </div>

        {role === 'SALESMAN' && (
          <>
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between text-slate-500 mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider">Today's Sales</span>
                <TrendingUp size={18} className="text-emerald-600" />
              </div>
              <div className="text-2xl font-black text-slate-900">
                ₹{Number(workspace?.role_context?.today_sales_amount || 0).toLocaleString('en-IN')}
              </div>
              <p className="text-[11px] text-slate-500 mt-1">
                {workspace?.role_context?.today_sales_count || 0} bills issued today
              </p>
            </div>

            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between text-slate-500 mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider">Incentive Slab</span>
                <FileCheck size={18} className="text-purple-600" />
              </div>
              <div className="text-2xl font-black text-slate-900">
                ₹200 / 100 kg
              </div>
              <p className="text-[11px] text-slate-500 mt-1">Calculated automatically on billing</p>
            </div>
          </>
        )}

        {role === 'FREELANCER' && (
          <>
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between text-slate-500 mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider">Active Projects</span>
                <Briefcase size={18} className="text-indigo-600" />
              </div>
              <div className="text-2xl font-black text-slate-900">
                {workspace?.role_context?.active_projects_count ?? 0}
              </div>
              <p className="text-[11px] text-slate-500 mt-1">Contract deliverables in progress</p>
            </div>

            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between text-slate-500 mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider">Open Milestones</span>
                <Clock size={18} className="text-amber-600" />
              </div>
              <div className="text-2xl font-black text-slate-900">
                {workspace?.role_context?.pending_milestones_count ?? 0}
              </div>
              <p className="text-[11px] text-slate-500 mt-1">Milestones awaiting submission</p>
            </div>
          </>
        )}

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Recent Slips</span>
            <Download size={18} className="text-emerald-600" />
          </div>
          <div className="text-2xl font-black text-slate-900">
            {workspace?.recent_receipts?.length ?? 0}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Verified salary vouchers ready</p>
        </div>
      </div>

      {/* 3. Main Grid: Recent Tasks & Recent Receipts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Assigned Tasks */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <CheckSquare size={18} className="text-emerald-600" />
              <h2 className="text-sm font-bold text-slate-900 m-0">Recent Assigned Tasks</h2>
            </div>
            <button
              onClick={() => onNavigate('tasks')}
              className="text-xs font-semibold text-emerald-700 hover:text-emerald-800 flex items-center gap-1 cursor-pointer"
            >
              <span>View All</span>
              <ArrowRight size={14} />
            </button>
          </div>

          {workspace?.recent_tasks && workspace.recent_tasks.length > 0 ? (
            <div className="space-y-3">
              {workspace.recent_tasks.slice(0, 4).map((task: TaskItem) => (
                <div
                  key={task.task_id}
                  className="p-3.5 rounded-xl border border-slate-100 hover:border-slate-200 bg-slate-50/50 flex items-center justify-between gap-3 transition-colors"
                >
                  <div>
                    <div className="text-xs font-bold text-slate-900">{task.title}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5 line-clamp-1">
                      {task.description || 'No detailed instructions.'}
                    </div>
                    {task.due_date && (
                      <div className="text-[10px] text-slate-400 mt-1 flex items-center gap-1">
                        <Calendar size={12} />
                        <span>Due: {task.due_date}</span>
                      </div>
                    )}
                  </div>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0 ${
                      task.status === 'COMPLETED' || task.status === 'APPROVED'
                        ? 'bg-emerald-100 text-emerald-800'
                        : task.status === 'SUBMITTED'
                        ? 'bg-blue-100 text-blue-800'
                        : 'bg-amber-100 text-amber-800'
                    }`}
                  >
                    {task.status}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-xs text-slate-400">
              No tasks currently assigned to you.
            </div>
          )}
        </div>

        {/* Salary Receipts */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <Download size={18} className="text-emerald-600" />
              <h2 className="text-sm font-bold text-slate-900 m-0">Verified Salary Receipts</h2>
            </div>
            <button
              onClick={() => onNavigate('salary')}
              className="text-xs font-semibold text-emerald-700 hover:text-emerald-800 flex items-center gap-1 cursor-pointer"
            >
              <span>View All</span>
              <ArrowRight size={14} />
            </button>
          </div>

          {workspace?.recent_receipts && workspace.recent_receipts.length > 0 ? (
            <div className="space-y-3">
              {workspace.recent_receipts.map((rec: any) => (
                <div
                  key={rec.receipt_id}
                  className="p-3.5 rounded-xl border border-slate-100 bg-slate-50/50 flex items-center justify-between gap-3"
                >
                  <div>
                    <div className="text-xs font-bold text-slate-900">
                      {rec.receipt_number || rec.receipt_id}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      Period: {rec.period_start} to {rec.period_end}
                    </div>
                    <div className="text-[10px] font-semibold text-emerald-700 mt-1">
                      ₹{Number(rec.net_paid || 0).toLocaleString('en-IN')} ({rec.payment_method})
                    </div>
                  </div>
                  <button
                    onClick={() =>
                      generateSalaryReceiptPdf({
                        receipt_number: rec.receipt_number || rec.receipt_id,
                        recipient_id: rec.recipient_id,
                        recipient_name: rec.recipient_name,
                        recipient_type: rec.recipient_type || 'SALARY',
                        role_or_category: rec.role_or_category || role,
                        period_start: rec.period_start,
                        period_end: rec.period_end,
                        payment_date: rec.payment_date,
                        payment_method: rec.payment_method,
                        payment_reference: rec.payment_reference,
                        gross_earnings: Number(rec.gross_earnings || rec.net_paid),
                        total_deductions: Number(rec.total_deductions || 0),
                        net_paid: Number(rec.net_paid || 0),
                        notes: rec.notes,
                      })
                    }
                    className="p-2 rounded-lg bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors flex items-center gap-1 text-xs font-semibold cursor-pointer"
                    title="Download Official PDF Receipt"
                  >
                    <Download size={14} />
                    <span>PDF</span>
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-xs text-slate-400">
              No salary receipts disbursed yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
