import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import { getAuthToken, apiFetch } from '../services/api';
import {
  Users,
  UserPlus,
  Briefcase,
  Coins,
  Clock,
  CheckSquare,
  CheckCircle2,
  AlertCircle,
  FileCheck,
  Download,
  Filter,
  Plus,
  Search,
  ExternalLink,
  Shield,
  Eye,
  Calendar,
  CreditCard,
  Building,
  RefreshCw,
  Send,
  X,
} from 'lucide-react';
import { generateSalaryReceiptPdf } from '../utils/generateSalaryReceiptPdf';

type WorkforceTab =
  | 'overview'
  | 'employees'
  | 'labour'
  | 'labour_attendance'
  | 'labour_work'
  | 'tasks'
  | 'projects'
  | 'payroll'
  | 'receipts'
  | 'audit';

interface WorkforceViewProps {
  onPreviewEmployeePortal?: () => void;
}

export const WorkforceView: React.FC<WorkforceViewProps> = ({ onPreviewEmployeePortal }) => {
  const { currentUser } = useStore();
  const token = getAuthToken();
  const [activeTab, setActiveTab] = useState<WorkforceTab>('overview');
  const [isLoading, setIsLoading] = useState(false);

  // Data states
  const [metrics, setMetrics] = useState<any>(null);
  const [employees, setEmployees] = useState<any[]>([]);
  const [labourList, setLabourList] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [payrollRuns, setPayrollRuns] = useState<any[]>([]);
  const [receipts, setReceipts] = useState<any[]>([]);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);

  // Search & Filter
  const [searchTerm, setSearchTerm] = useState('');

  // Modals
  const [showAddEmployeeModal, setShowAddEmployeeModal] = useState(false);
  const [showAddLabourModal, setShowAddLabourModal] = useState(false);
  const [showAssignTaskModal, setShowAssignTaskModal] = useState(false);
  const [showCreateProjectModal, setShowCreateProjectModal] = useState(false);
  const [showAddMilestoneModal, setShowAddMilestoneModal] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [showCalcPayrollModal, setShowCalcPayrollModal] = useState(false);
  const [showDisburseModal, setShowDisburseModal] = useState(false);
  const [selectedDisburseItem, setSelectedDisburseItem] = useState<any>(null);
  const [reviewTaskTarget, setReviewTaskTarget] = useState<any>(null);
  const [reviewMilestoneTarget, setReviewMilestoneTarget] = useState<any>(null);
  const [selectedPayrollRun, setSelectedPayrollRun] = useState<any>(null);
  const [payrollItems, setPayrollItems] = useState<any[]>([]);

  // Feedback notifications
  const [actionSuccess, setActionSuccess] = useState('');
  const [actionError, setActionError] = useState('');

  const isOwner = currentUser?.role === 'OWNER' || String(currentUser?.role || '') === 'OWNER_ADMIN';

  // Loaders
  const loadMetrics = async () => {
    try {
      const res = await apiFetch('/api/workforce/dashboard-metrics');
      if (res.ok) setMetrics(await res.json());
    } catch (err) {}
  };

  const loadEmployees = async () => {
    try {
      const res = await apiFetch('/api/workforce/employees');
      if (res.ok) setEmployees(await res.json());
    } catch (err) {}
  };

  const loadLabour = async () => {
    try {
      const res = await apiFetch('/api/workforce/labour');
      if (res.ok) setLabourList(await res.json());
    } catch (err) {}
  };

  const loadTasks = async () => {
    try {
      const res = await apiFetch('/api/workforce/tasks');
      if (res.ok) setTasks(await res.json());
    } catch (err) {}
  };

  const loadProjects = async () => {
    try {
      const res = await apiFetch('/api/workforce/projects');
      if (res.ok) setProjects(await res.json());
    } catch (err) {}
  };

  const loadPayroll = async () => {
    try {
      const res = await apiFetch('/api/workforce/payroll');
      if (res.ok) setPayrollRuns(await res.json());
    } catch (err) {}
  };

  const loadReceipts = async () => {
    try {
      const res = await apiFetch('/api/workforce/receipts');
      if (res.ok) setReceipts(await res.json());
    } catch (err) {}
  };

  const loadAuditLogs = async () => {
    try {
      const res = await apiFetch('/api/workforce/audit-logs');
      if (res.ok) setAuditLogs(await res.json());
    } catch (err) {}
  };

  const refreshAll = () => {
    loadMetrics();
    loadEmployees();
    loadLabour();
    loadTasks();
    loadProjects();
    loadPayroll();
    loadReceipts();
    loadAuditLogs();
  };

  useEffect(() => {
    refreshAll();
  }, [token]);

  // Labour Attendance State for Bulk Entry
  const [attDate, setAttDate] = useState(new Date().toISOString().slice(0, 10));
  const [attendanceDraft, setAttendanceDraft] = useState<Record<string, { status: string; hours: number; notes: string }>>({});

  useEffect(() => {
    if (labourList.length > 0) {
      const draft: Record<string, { status: string; hours: number; notes: string }> = {};
      labourList.forEach((l) => {
        draft[l.labour_id] = { status: 'PRESENT', hours: 8, notes: '' };
      });
      setAttendanceDraft(draft);
    }
  }, [labourList]);

  const handleSaveBulkAttendance = async () => {
    setIsLoading(true);
    setActionSuccess('');
    setActionError('');
    try {
      const records = Object.entries(attendanceDraft).map(([lid, d]) => ({
        labour_id: lid,
        attendance_date: attDate,
        status: d.status,
        hours_worked: Number(d.hours) || 8,
        overtime_hours: Math.max(0, (Number(d.hours) || 8) - 8),
        notes: d.notes,
      }));

      const res = await apiFetch('/api/workforce/labour/attendance/bulk', {
        method: 'POST',
        body: JSON.stringify({
          attendance_date: attDate,
          records,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setActionSuccess(data.message || 'Labour attendance saved successfully!');
        loadMetrics();
      } else {
        setActionError(data.detail || 'Failed to save labour attendance.');
      }
    } catch (err) {
      setActionError('Network error while saving attendance.');
    } finally {
      setIsLoading(false);
    }
  };

  // Labour Work Entry State
  const [showLogWorkModal, setShowLogWorkModal] = useState(false);
  const [workLabourId, setWorkLabourId] = useState('');
  const [workActivity, setWorkActivity] = useState('');
  const [workUnits, setWorkUnits] = useState('');
  const [workUom, setWorkUom] = useState('KG');
  const [workPieceRate, setWorkPieceRate] = useState('');
  const [workNotes, setWorkNotes] = useState('');

  const handleSaveWorkEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setActionSuccess('');
    setActionError('');
    try {
      const res = await apiFetch('/api/workforce/labour/work-entries', {
        method: 'POST',
        body: JSON.stringify({
          labour_id: workLabourId,
          entry_date: attDate,
          activity_name: workActivity,
          units_completed: Number(workUnits) || 0,
          unit_of_measure: workUom,
          piece_rate: Number(workPieceRate) || 0,
          notes: workNotes,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setActionSuccess(data.message || 'Work entry logged successfully!');
        setShowLogWorkModal(false);
        setWorkActivity('');
        setWorkUnits('');
        setWorkPieceRate('');
      } else {
        setActionError(data.detail || 'Failed to log work entry.');
      }
    } catch (err) {
      setActionError('Network error logging work entry.');
    } finally {
      setIsLoading(false);
    }
  };

  // Payroll Calculation State
  const [calcMonth, setCalcMonth] = useState(new Date().toISOString().slice(0, 7));

  const handleCalculatePayroll = async () => {
    setIsLoading(true);
    setActionSuccess('');
    setActionError('');
    try {
      const res = await apiFetch('/api/workforce/payroll/calculate', {
        method: 'POST',
        body: JSON.stringify({
          month: calcMonth,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setActionSuccess(data.message || 'Draft payroll calculated!');
        setShowCalcPayrollModal(false);
        loadPayroll();
        setSelectedPayrollRun(data.payroll_run);
        setPayrollItems(data.items || []);
      } else {
        setActionError(data.detail || 'Failed to calculate payroll.');
      }
    } catch (err) {
      setActionError('Network error calculating payroll.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleApprovePayroll = async (runId: string) => {
    if (!window.confirm(`Approve payroll run ${runId}? This freezes calculations for payment.`)) return;
    setIsLoading(true);
    setActionSuccess('');
    setActionError('');
    try {
      const res = await apiFetch(`/api/workforce/payroll/${runId}/approve`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        setActionSuccess(data.message || 'Payroll approved successfully!');
        loadPayroll();
      } else {
        setActionError(data.detail || 'Failed to approve payroll.');
      }
    } catch (err) {
      setActionError('Network error approving payroll.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenRunItems = async (run: any) => {
    setSelectedPayrollRun(run);
    try {
      const res = await apiFetch(`/api/workforce/payroll/${run.payroll_run_id}/items`);
      if (res.ok) {
        setPayrollItems(await res.json());
      }
    } catch (err) {}
  };

  // Disburse Payment Handler
  const [disburseMethod, setDisburseMethod] = useState('BANK_TRANSFER');
  const [disburseRef, setDisburseRef] = useState('');
  const [disburseNotes, setDisburseNotes] = useState('');

  const handleRecordPayment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDisburseItem) return;
    setIsLoading(true);
    setActionSuccess('');
    setActionError('');
    try {
      const res = await apiFetch('/api/workforce/payments', {
        method: 'POST',
        body: JSON.stringify({
          reference_id: selectedDisburseItem.id,
          payment_type: selectedDisburseItem.type,
          recipient_id: selectedDisburseItem.recipient_id,
          recipient_name: selectedDisburseItem.recipient_name,
          amount: selectedDisburseItem.amount,
          payment_method: disburseMethod,
          payment_reference: disburseRef,
          notes: disburseNotes,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setActionSuccess(data.message || 'Payment recorded and official receipt generated!');
        setShowDisburseModal(false);
        loadReceipts();
        loadPayroll();
        if (selectedPayrollRun) handleOpenRunItems(selectedPayrollRun);
      } else {
        setActionError(data.detail || 'Failed to record payment.');
      }
    } catch (err) {
      setActionError('Network error recording payment.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl sm:text-2xl font-black text-slate-900 m-0">
              Workforce, Labour & Payroll
            </h1>
            <span className="bg-emerald-100 text-emerald-800 border border-emerald-200 text-xs font-bold px-2.5 py-0.5 rounded-full">
              ERP Master
            </span>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Complete management of Salaried Staff, Factory Labourers, Freelance Specialists & Double-Entry Payroll.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {onPreviewEmployeePortal && (
            <button
              onClick={onPreviewEmployeePortal}
              className="px-3.5 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold shadow-xs transition-all flex items-center gap-1.5 cursor-pointer"
            >
              <Eye size={15} />
              <span>Preview Staff Portal</span>
            </button>
          )}

          <button
            onClick={refreshAll}
            className="p-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 transition-colors cursor-pointer"
            title="Refresh Workforce Data"
          >
            <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Notifications */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-emerald-50 text-emerald-800 text-xs border border-emerald-200 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
            <span>{actionSuccess}</span>
          </div>
          <button onClick={() => setActionSuccess('')} className="text-emerald-700 hover:text-emerald-900">
            <X size={14} />
          </button>
        </div>
      )}

      {actionError && (
        <div className="p-3.5 rounded-xl bg-red-50 text-red-700 text-xs border border-red-200 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <AlertCircle size={16} className="text-red-600 shrink-0" />
            <span>{actionError}</span>
          </div>
          <button onClick={() => setActionError('')} className="text-red-700 hover:text-red-900">
            <X size={14} />
          </button>
        </div>
      )}

      {/* 2. Sub-Tabs Bar */}
      <div className="border-b border-slate-200 flex items-center gap-1 overflow-x-auto pb-1 text-xs font-semibold">
        {[
          { id: 'overview', label: 'Dashboard & Metrics', icon: <Users size={15} /> },
          { id: 'employees', label: 'Employee Directory', icon: <Building size={15} /> },
          { id: 'labour', label: 'Labour Master', icon: <Briefcase size={15} /> },
          { id: 'labour_attendance', label: 'Daily Labour Attendance', icon: <Clock size={15} /> },
          { id: 'tasks', label: 'Work Assignments', icon: <CheckSquare size={15} /> },
          { id: 'projects', label: 'Freelancer Projects', icon: <FileCheck size={15} /> },
          { id: 'payroll', label: 'Payroll Engine', icon: <Coins size={15} /> },
          { id: 'receipts', label: 'Salary Receipts', icon: <Download size={15} /> },
          { id: 'audit', label: 'Audit Register', icon: <Shield size={15} /> },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as WorkforceTab)}
            className={`px-3.5 py-2.5 rounded-xl whitespace-nowrap transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === tab.id
                ? 'bg-emerald-700 text-white font-bold shadow-xs'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
            }`}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* 3. TAB CONTENT */}

      {/* TAB 1: OVERVIEW & KPIS */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-xs">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Active Employees</span>
              <div className="text-2xl font-black text-slate-900 mt-1">
                {metrics?.active_employees_count ?? employees.length}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Salaried & field specialists</p>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-xs">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Active Labour</span>
              <div className="text-2xl font-black text-slate-900 mt-1">
                {metrics?.active_labour_count ?? labourList.length}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Rolling, packing & roasting</p>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-xs">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Labour Present Today</span>
              <div className="text-2xl font-black text-emerald-700 mt-1">
                {metrics?.labour_present_today ?? 0}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Daily punch verified</p>
            </div>

            <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-xs">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Pending Task Reviews</span>
              <div className="text-2xl font-black text-amber-600 mt-1">
                {metrics?.submitted_tasks_for_review ?? 0}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Submissions awaiting sign-off</p>
            </div>
          </div>

          {/* Quick Action Hub */}
          <div className="bg-gradient-to-r from-slate-900 to-slate-950 rounded-2xl p-6 text-white border border-slate-800 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h3 className="text-base font-bold text-white m-0">Monthly Payroll & Wage Processing</h3>
              <p className="text-xs text-slate-300 mt-1 max-w-xl">
                Kawad Swad double-entry engine automatically computes attendance pro-rata wages, applies salesman 100kg-slab incentives, and generates auditable voucher receipts.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  setActiveTab('payroll');
                  setShowCalcPayrollModal(true);
                }}
                className="px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-xs transition-colors cursor-pointer flex items-center gap-1.5"
              >
                <Coins size={15} />
                <span>Run Monthly Payroll</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: EMPLOYEE DIRECTORY */}
      {activeTab === 'employees' && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Search size={15} className="text-slate-400" />
              <input
                type="text"
                placeholder="Search by employee name, role, department…"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="text-xs p-1.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-600 w-64"
              />
            </div>
            <span className="text-xs text-slate-500 font-semibold">{employees.length} registered staff</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                <tr>
                  <th className="py-3 px-4">User ID</th>
                  <th className="py-3 px-4">Name & Username</th>
                  <th className="py-3 px-4">System Role</th>
                  <th className="py-3 px-4">Designation</th>
                  <th className="py-3 px-4">Department</th>
                  <th className="py-3 px-4 text-right">Base Pay</th>
                  <th className="py-3 px-4">Contact</th>
                  <th className="py-3 px-4 text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {employees
                  .filter(
                    (e) =>
                      !searchTerm ||
                      e.full_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                      e.role?.toLowerCase().includes(searchTerm.toLowerCase())
                  )
                  .map((emp) => (
                    <tr key={emp.user_id} className="hover:bg-slate-50/60">
                      <td className="py-3 px-4 font-mono font-bold text-slate-900">{emp.user_id}</td>
                      <td className="py-3 px-4 font-semibold text-slate-900">
                        {emp.full_name}
                        <span className="block text-[10px] text-slate-400 font-normal">@{emp.username}</span>
                      </td>
                      <td className="py-3 px-4">
                        <span className="font-semibold text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded-md">
                          {emp.role}
                        </span>
                      </td>
                      <td className="py-3 px-4">{emp.designation || emp.role}</td>
                      <td className="py-3 px-4">{emp.department || 'Operations'}</td>
                      <td className="py-3 px-4 text-right font-bold text-slate-900">
                        ₹{Number(emp.basic_salary || 0).toLocaleString('en-IN')}
                      </td>
                      <td className="py-3 px-4 text-slate-500">{emp.mobile || emp.email || '--'}</td>
                      <td className="py-3 px-4 text-center">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                            emp.active ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {emp.active ? 'ACTIVE' : 'INACTIVE'}
                        </span>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 3: LABOUR REGISTER */}
      {activeTab === 'labour' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 m-0">Permanent Factory & Packaging Labour Master</h2>
            <button
              onClick={() => setShowAddLabourModal(true)}
              className="px-3.5 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
            >
              <Plus size={15} />
              <span>Register Labour Worker</span>
            </button>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                  <tr>
                    <th className="py-3 px-4">Labour ID</th>
                    <th className="py-3 px-4">Worker Name</th>
                    <th className="py-3 px-4">Station / Category</th>
                    <th className="py-3 px-4">Wage Type</th>
                    <th className="py-3 px-4 text-right">Standard Rate</th>
                    <th className="py-3 px-4">Contact</th>
                    <th className="py-3 px-4 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {labourList.map((l) => (
                    <tr key={l.labour_id} className="hover:bg-slate-50/60">
                      <td className="py-3 px-4 font-mono font-bold text-slate-900">{l.labour_id}</td>
                      <td className="py-3 px-4 font-bold text-slate-900">{l.full_name}</td>
                      <td className="py-3 px-4 font-semibold text-slate-800">{l.category}</td>
                      <td className="py-3 px-4">{l.wage_type}</td>
                      <td className="py-3 px-4 text-right font-black text-emerald-800">
                        ₹{Number(l.base_rate || 0).toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-slate-500">{l.mobile || '--'}</td>
                      <td className="py-3 px-4 text-center">
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800">
                          {l.active ? 'ACTIVE' : 'INACTIVE'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: DAILY LABOUR ATTENDANCE */}
      {activeTab === 'labour_attendance' && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-xs p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-100">
            <div>
              <h2 className="text-sm font-bold text-slate-900 m-0">Bulk Daily Labour Attendance Punch</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Mark daily attendance and log hours worked for rolling, roasting, and packaging labour.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs font-bold text-slate-600">Date:</label>
              <input
                type="date"
                value={attDate}
                onChange={(e) => setAttDate(e.target.value)}
                className="text-xs p-1.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-600 font-semibold"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                <tr>
                  <th className="py-3 px-4">Labour ID</th>
                  <th className="py-3 px-4">Worker Name</th>
                  <th className="py-3 px-4">Category</th>
                  <th className="py-3 px-4">Daily Rate</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Hours</th>
                  <th className="py-3 px-4 text-right">Earned Wage</th>
                  <th className="py-3 px-4">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {labourList.map((l) => {
                  const draft = attendanceDraft[l.labour_id] || { status: 'PRESENT', hours: 8, notes: '' };
                  const rate = Number(l.base_rate) || 0;
                  let wage = 0;
                  if (draft.status === 'PRESENT') wage = rate;
                  else if (draft.status === 'HALF_DAY') wage = rate * 0.5;

                  return (
                    <tr key={l.labour_id} className="hover:bg-slate-50/60">
                      <td className="py-3 px-4 font-mono font-bold text-slate-900">{l.labour_id}</td>
                      <td className="py-3 px-4 font-bold text-slate-900">{l.full_name}</td>
                      <td className="py-3 px-4 text-slate-600">{l.category}</td>
                      <td className="py-3 px-4 font-semibold text-slate-800">₹{rate.toFixed(2)}</td>
                      <td className="py-3 px-4">
                        <select
                          value={draft.status}
                          onChange={(e) => {
                            const val = e.target.value;
                            setAttendanceDraft((prev) => ({
                              ...prev,
                              [l.labour_id]: { ...draft, status: val, hours: val === 'HALF_DAY' ? 4 : val === 'ABSENT' ? 0 : 8 },
                            }));
                          }}
                          className="text-xs p-1 rounded-md border border-slate-200 font-semibold"
                        >
                          <option value="PRESENT">PRESENT</option>
                          <option value="HALF_DAY">HALF_DAY</option>
                          <option value="ABSENT">ABSENT</option>
                        </select>
                      </td>
                      <td className="py-3 px-4">
                        <input
                          type="number"
                          value={draft.hours}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setAttendanceDraft((prev) => ({
                              ...prev,
                              [l.labour_id]: { ...draft, hours: val },
                            }));
                          }}
                          className="w-16 text-xs p-1 rounded-md border border-slate-200 text-center font-bold"
                          min={0}
                          max={24}
                        />
                      </td>
                      <td className="py-3 px-4 text-right font-black text-emerald-800">
                        ₹{wage.toFixed(2)}
                      </td>
                      <td className="py-3 px-4">
                        <input
                          type="text"
                          value={draft.notes}
                          placeholder="Optional remarks…"
                          onChange={(e) => {
                            const val = e.target.value;
                            setAttendanceDraft((prev) => ({
                              ...prev,
                              [l.labour_id]: { ...draft, notes: val },
                            }));
                          }}
                          className="text-xs p-1 rounded-md border border-slate-200 w-full"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="pt-3 border-t border-slate-100 flex justify-end">
            <button
              onClick={handleSaveBulkAttendance}
              disabled={isLoading}
              className="px-6 py-2.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            >
              <CheckCircle2 size={15} />
              <span>{isLoading ? 'Saving…' : 'Save Attendance Records'}</span>
            </button>
          </div>
        </div>
      )}

      {/* TAB 5: WORK ASSIGNMENTS */}
      {activeTab === 'tasks' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 m-0">Team Tasks & Deliverable Tracking</h2>
            <button
              onClick={() => setShowAssignTaskModal(true)}
              className="px-3.5 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
            >
              <Plus size={15} />
              <span>Assign New Task</span>
            </button>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                  <tr>
                    <th className="py-3 px-4">Task ID</th>
                    <th className="py-3 px-4">Title & Instructions</th>
                    <th className="py-3 px-4">Assignee</th>
                    <th className="py-3 px-4">Priority</th>
                    <th className="py-3 px-4">Due Date</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {tasks.map((task) => (
                    <tr key={task.task_id} className="hover:bg-slate-50/60">
                      <td className="py-3 px-4 font-mono font-bold text-slate-900">{task.task_id}</td>
                      <td className="py-3 px-4">
                        <span className="font-bold text-slate-900 block">{task.title}</span>
                        <span className="text-[11px] text-slate-500 line-clamp-1">{task.description}</span>
                        {task.submission_notes && (
                          <div className="mt-1 p-1.5 rounded-md bg-blue-50 text-blue-900 text-[10px]">
                            <strong>Submitted:</strong> {task.submission_notes}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 font-semibold text-slate-900">{task.assigned_to_name}</td>
                      <td className="py-3 px-4">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                            task.priority === 'URGENT'
                              ? 'bg-red-100 text-red-800'
                              : task.priority === 'HIGH'
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-slate-100 text-slate-700'
                          }`}
                        >
                          {task.priority}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-slate-500">{task.due_date || '--'}</td>
                      <td className="py-3 px-4">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                            task.status === 'COMPLETED' || task.status === 'APPROVED'
                              ? 'bg-emerald-100 text-emerald-800'
                              : task.status === 'SUBMITTED'
                              ? 'bg-blue-100 text-blue-800'
                              : 'bg-amber-100 text-amber-800'
                          }`}
                        >
                          {task.status}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-center">
                        {task.status === 'SUBMITTED' && (
                          <button
                            onClick={() => setReviewTaskTarget(task)}
                            className="px-2.5 py-1 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-[11px] cursor-pointer"
                          >
                            Review
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 6: FREELANCER PROJECTS */}
      {activeTab === 'projects' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 m-0">Freelancer Contracts & Milestones</h2>
            <button
              onClick={() => setShowCreateProjectModal(true)}
              className="px-3.5 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
            >
              <Plus size={15} />
              <span>Create Project</span>
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4">
            {projects.map((proj) => (
              <div key={proj.project_id} className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-100">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-slate-400">{proj.project_id}</span>
                      <h3 className="text-sm font-bold text-slate-900 m-0">{proj.title}</h3>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800">
                        {proj.status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Assigned to: <strong>{proj.freelancer_name}</strong> • Target: {proj.target_completion_date || 'Ongoing'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-black text-slate-900">
                      Budget: ₹{Number(proj.total_budget || 0).toLocaleString('en-IN')}
                    </span>
                    <button
                      onClick={() => {
                        setSelectedProjectId(proj.project_id);
                        setShowAddMilestoneModal(true);
                      }}
                      className="px-2.5 py-1 rounded-lg border border-slate-200 hover:bg-slate-50 text-xs font-semibold cursor-pointer"
                    >
                      + Milestone
                    </button>
                  </div>
                </div>

                {/* Milestones list */}
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
                  {(proj.milestones || []).map((ms: any) => (
                    <div key={ms.milestone_id} className="p-3 rounded-xl border border-slate-100 bg-slate-50/60 text-xs flex flex-col justify-between">
                      <div>
                        <div className="flex items-center justify-between gap-1 mb-1">
                          <span className="font-bold text-slate-900">{ms.title}</span>
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-slate-200 text-slate-800">
                            {ms.status}
                          </span>
                        </div>
                        <div className="text-[11px] font-bold text-emerald-800">
                          ₹{Number(ms.amount || 0).toLocaleString('en-IN')}
                        </div>
                        {ms.submission_notes && (
                          <div className="mt-1.5 text-[10px] text-slate-600 bg-white p-1.5 rounded border border-slate-100">
                            <strong>Deliverable:</strong> {ms.submission_notes}
                          </div>
                        )}
                      </div>

                      <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between">
                        {ms.status === 'SUBMITTED' ? (
                          <button
                            onClick={() => setReviewMilestoneTarget(ms)}
                            className="px-2 py-0.5 rounded bg-emerald-700 text-white font-bold text-[10px] cursor-pointer"
                          >
                            Review & Sign-Off
                          </button>
                        ) : ms.status === 'APPROVED' ? (
                          <button
                            onClick={() => {
                              setSelectedDisburseItem({
                                id: ms.milestone_id,
                                type: 'FREELANCER_MILESTONE',
                                recipient_id: proj.freelancer_user_id,
                                recipient_name: proj.freelancer_name,
                                amount: Number(ms.amount || 0),
                              });
                              setShowDisburseModal(true);
                            }}
                            className="px-2 py-0.5 rounded bg-amber-600 hover:bg-amber-500 text-white font-bold text-[10px] cursor-pointer"
                          >
                            Disburse Payment
                          </button>
                        ) : (
                          <span className="text-[10px] text-slate-400">{ms.status}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 7: PAYROLL ENGINE */}
      {activeTab === 'payroll' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 m-0">Monthly Payroll Runs & Ledger Postings</h2>
            <button
              onClick={() => setShowCalcPayrollModal(true)}
              className="px-3.5 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
            >
              <Coins size={15} />
              <span>Calculate New Run</span>
            </button>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                <tr>
                  <th className="py-3 px-4">Run ID</th>
                  <th className="py-3 px-4">Month</th>
                  <th className="py-3 px-4">Employees</th>
                  <th className="py-3 px-4 text-right">Gross Total</th>
                  <th className="py-3 px-4 text-right">Deductions</th>
                  <th className="py-3 px-4 text-right">Net Payable</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {payrollRuns.map((run) => (
                  <tr key={run.payroll_run_id} className="hover:bg-slate-50/60">
                    <td className="py-3 px-4 font-mono font-bold text-slate-900">{run.payroll_run_id}</td>
                    <td className="py-3 px-4 font-bold text-slate-900">{run.month}</td>
                    <td className="py-3 px-4">{run.total_employees} staff</td>
                    <td className="py-3 px-4 text-right font-medium">₹{Number(run.total_gross || 0).toLocaleString('en-IN')}</td>
                    <td className="py-3 px-4 text-right font-medium text-red-600">₹{Number(run.total_deductions || 0).toLocaleString('en-IN')}</td>
                    <td className="py-3 px-4 text-right font-black text-emerald-800">
                      ₹{Number(run.total_net || 0).toLocaleString('en-IN')}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                          run.status === 'APPROVED' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {run.status}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <button
                        onClick={() => handleOpenRunItems(run)}
                        className="px-2.5 py-1 rounded-lg border border-slate-200 hover:bg-slate-100 text-xs font-semibold cursor-pointer mr-2"
                      >
                        View Items
                      </button>
                      {run.status !== 'APPROVED' && isOwner && (
                        <button
                          onClick={() => handleApprovePayroll(run.payroll_run_id)}
                          className="px-2.5 py-1 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs cursor-pointer"
                        >
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Active Run Items View */}
          {selectedPayrollRun && (
            <div className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 space-y-3">
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <div>
                  <h3 className="text-sm font-bold text-slate-900 m-0">
                    Line Items for {selectedPayrollRun.month} ({selectedPayrollRun.payroll_run_id})
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Disburse individual employee salary slips and track payment vouchers.
                  </p>
                </div>
                <button
                  onClick={() => setSelectedPayrollRun(null)}
                  className="text-xs text-slate-500 hover:text-slate-800 cursor-pointer"
                >
                  Close Items
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                    <tr>
                      <th className="py-2 px-3">Employee</th>
                      <th className="py-2 px-3">Role</th>
                      <th className="py-2 px-3">Attendance</th>
                      <th className="py-2 px-3 text-right">Earned Base</th>
                      <th className="py-2 px-3 text-right">Incentives</th>
                      <th className="py-2 px-3 text-right">Deductions</th>
                      <th className="py-2 px-3 text-right">Net Payable</th>
                      <th className="py-2 px-3">Status</th>
                      <th className="py-2 px-3 text-center">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-slate-700">
                    {payrollItems.map((item) => (
                      <tr key={item.item_id} className="hover:bg-slate-50/60">
                        <td className="py-2 px-3 font-bold text-slate-900">{item.employee_name}</td>
                        <td className="py-2 px-3">{item.role}</td>
                        <td className="py-2 px-3 text-slate-600">{item.notes}</td>
                        <td className="py-2 px-3 text-right font-medium">₹{Number(item.earned_basic || 0).toFixed(2)}</td>
                        <td className="py-2 px-3 text-right font-medium text-purple-700">₹{Number(item.incentive_amount || 0).toFixed(2)}</td>
                        <td className="py-2 px-3 text-right font-medium text-red-600">-₹{Number(item.deductions || 0).toFixed(2)}</td>
                        <td className="py-2 px-3 text-right font-black text-emerald-800">₹{Number(item.net_amount || 0).toFixed(2)}</td>
                        <td className="py-2 px-3">
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                              item.payment_status === 'PAID' ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-700'
                            }`}
                          >
                            {item.payment_status}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-center">
                          {item.payment_status !== 'PAID' ? (
                            <button
                              onClick={() => {
                                setSelectedDisburseItem({
                                  id: item.item_id,
                                  type: 'SALARY',
                                  recipient_id: item.user_id,
                                  recipient_name: item.employee_name,
                                  amount: Number(item.net_amount || 0),
                                });
                                setShowDisburseModal(true);
                              }}
                              className="px-2.5 py-1 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-[11px] cursor-pointer"
                            >
                              Disburse
                            </button>
                          ) : (
                            <span className="text-[11px] text-emerald-700 font-bold">✓ Paid</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 8: SALARY RECEIPTS */}
      {activeTab === 'receipts' && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 m-0">Verifiable Payment Receipts & Slips</h2>
            <span className="text-xs text-slate-500 font-semibold">{receipts.length} vouchers</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                <tr>
                  <th className="py-3 px-4">Receipt #</th>
                  <th className="py-3 px-4">Recipient</th>
                  <th className="py-3 px-4">Type</th>
                  <th className="py-3 px-4">Date</th>
                  <th className="py-3 px-4">Method / Ref</th>
                  <th className="py-3 px-4 text-right">Net Amount</th>
                  <th className="py-3 px-4 text-center">PDF Download</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {receipts.map((rec) => (
                  <tr key={rec.receipt_id} className="hover:bg-slate-50/60">
                    <td className="py-3 px-4 font-mono font-bold text-slate-900">{rec.receipt_number || rec.receipt_id}</td>
                    <td className="py-3 px-4 font-bold text-slate-900">{rec.recipient_name}</td>
                    <td className="py-3 px-4">{rec.recipient_type}</td>
                    <td className="py-3 px-4">{rec.payment_date}</td>
                    <td className="py-3 px-4">
                      {rec.payment_method}
                      {rec.payment_reference && <span className="block text-[10px] text-slate-400">Ref: {rec.payment_reference}</span>}
                    </td>
                    <td className="py-3 px-4 text-right font-black text-emerald-800">
                      ₹{Number(rec.net_paid || 0).toFixed(2)}
                    </td>
                    <td className="py-3 px-4 text-center">
                      <button
                        onClick={() =>
                          generateSalaryReceiptPdf({
                            receipt_number: rec.receipt_number || rec.receipt_id,
                            recipient_id: rec.recipient_id,
                            recipient_name: rec.recipient_name,
                            recipient_type: rec.recipient_type,
                            role_or_category: rec.role_or_category,
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
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-xs transition-colors cursor-pointer"
                      >
                        <Download size={13} />
                        <span>PDF</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 9: AUDIT LOGS */}
      {activeTab === 'audit' && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900 m-0">Workforce & HR Audit Trail</h2>
            <span className="text-xs text-slate-500 font-semibold">{auditLogs.length} events</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
                <tr>
                  <th className="py-3 px-4">Audit ID</th>
                  <th className="py-3 px-4">Timestamp</th>
                  <th className="py-3 px-4">Action</th>
                  <th className="py-3 px-4">Entity</th>
                  <th className="py-3 px-4">Actor</th>
                  <th className="py-3 px-4">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {auditLogs.map((log) => (
                  <tr key={log.audit_id} className="hover:bg-slate-50/60">
                    <td className="py-3 px-4 font-mono font-bold text-slate-900">{log.audit_id}</td>
                    <td className="py-3 px-4 text-slate-500">{log.created_at ? log.created_at.slice(0, 19).replace('T', ' ') : '--'}</td>
                    <td className="py-3 px-4 font-bold text-slate-800">{log.action}</td>
                    <td className="py-3 px-4">{log.entity_type} ({log.entity_id})</td>
                    <td className="py-3 px-4 font-semibold text-slate-900">{log.actor_id}</td>
                    <td className="py-3 px-4 text-slate-600 max-w-sm truncate">{log.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* MODAL: Register Labour Worker */}
      {showAddLabourModal && (
        <AddLabourModal
          onClose={() => setShowAddLabourModal(false)}
          onSuccess={(msg) => {
            setShowAddLabourModal(false);
            setActionSuccess(msg);
            loadLabour();
          }}
        />
      )}

      {/* MODAL: Assign Task */}
      {showAssignTaskModal && (
        <AssignTaskModal
          employees={employees}
          onClose={() => setShowAssignTaskModal(false)}
          onSuccess={(msg) => {
            setShowAssignTaskModal(false);
            setActionSuccess(msg);
            loadTasks();
          }}
        />
      )}

      {/* MODAL: Create Project */}
      {showCreateProjectModal && (
        <CreateProjectModal
          employees={employees}
          onClose={() => setShowCreateProjectModal(false)}
          onSuccess={(msg) => {
            setShowCreateProjectModal(false);
            setActionSuccess(msg);
            loadProjects();
          }}
        />
      )}

      {/* MODAL: Add Milestone */}
      {showAddMilestoneModal && (
        <AddMilestoneModal
          projectId={selectedProjectId}
          onClose={() => setShowAddMilestoneModal(false)}
          onSuccess={(msg) => {
            setShowAddMilestoneModal(false);
            setActionSuccess(msg);
            loadProjects();
          }}
        />
      )}

      {/* MODAL: Calculate Payroll */}
      {showCalcPayrollModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden p-6 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-sm font-bold text-slate-900 m-0">Run Monthly Payroll</h3>
              <button onClick={() => setShowCalcPayrollModal(false)} className="text-slate-400 hover:text-slate-700">
                <X size={18} />
              </button>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Select Processing Month (YYYY-MM)</label>
              <input
                type="month"
                value={calcMonth}
                onChange={(e) => setCalcMonth(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200 font-bold"
              />
              <p className="text-[11px] text-slate-500 mt-2">
                The engine will evaluate attendance records, calculate basic pro-rata wages, compute salesman sales incentives, and create itemized payroll records.
              </p>
            </div>

            <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowCalcPayrollModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCalculatePayroll}
                disabled={isLoading}
                className="px-5 py-2 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs cursor-pointer disabled:opacity-50"
              >
                {isLoading ? 'Calculating…' : 'Calculate Draft Payroll'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Disburse Payment */}
      {showDisburseModal && selectedDisburseItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden p-6 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-sm font-bold text-slate-900 m-0">Record Payment & Generate Slip</h3>
              <button onClick={() => setShowDisburseModal(false)} className="text-slate-400 hover:text-slate-700">
                <X size={18} />
              </button>
            </div>

            <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 text-xs space-y-1">
              <div>Recipient: <strong>{selectedDisburseItem.recipient_name}</strong></div>
              <div>Type: <strong>{selectedDisburseItem.type}</strong></div>
              <div>Amount to Disburse: <strong className="text-emerald-700">₹{selectedDisburseItem.amount.toFixed(2)}</strong></div>
            </div>

            <form onSubmit={handleRecordPayment} className="space-y-3">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Payment Method</label>
                <select
                  value={disburseMethod}
                  onChange={(e) => setDisburseMethod(e.target.value)}
                  className="w-full text-xs p-2.5 rounded-xl border border-slate-200 font-semibold"
                >
                  <option value="BANK_TRANSFER">Bank Transfer (NEFT/RTGS/IMPS)</option>
                  <option value="UPI">UPI Direct</option>
                  <option value="CASH">Cash Disbursement</option>
                  <option value="CHEQUE">Company Cheque</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Transaction Reference / UTR Number</label>
                <input
                  type="text"
                  value={disburseRef}
                  onChange={(e) => setDisburseRef(e.target.value)}
                  placeholder="e.g. UTR123456789 or Cash Voucher #"
                  className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
                />
              </div>

              <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowDisburseModal(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="px-5 py-2 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs cursor-pointer disabled:opacity-50"
                >
                  {isLoading ? 'Processing…' : 'Confirm & Generate Slip'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Review Task */}
      {reviewTaskTarget && (
        <ReviewTaskModal
          task={reviewTaskTarget}
          onClose={() => setReviewTaskTarget(null)}
          onSuccess={(msg) => {
            setReviewTaskTarget(null);
            setActionSuccess(msg);
            loadTasks();
          }}
        />
      )}
    </div>
  );
};

// Sub-components: Add Labour Modal
const AddLabourModal: React.FC<{ onClose: () => void; onSuccess: (msg: string) => void }> = ({
  onClose,
  onSuccess,
}) => {
  const token = getAuthToken();
  const [fullName, setFullName] = useState('');
  const [category, setCategory] = useState('ROLLING');
  const [wageType, setWageType] = useState('DAILY');
  const [baseRate, setBaseRate] = useState('');
  const [mobile, setMobile] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fullName.trim()) return setError('Worker full name is required.');
    setIsSubmitting(true);
    setError('');

    try {
      const res = await apiFetch('/api/workforce/labour', {
        method: 'POST',
        body: JSON.stringify({
          full_name: fullName.trim(),
          category,
          wage_type: wageType,
          base_rate: Number(baseRate) || 0,
          mobile: mobile.trim(),
        }),
      });
      const data = await res.json();
      if (res.ok) {
        onSuccess(data.message || 'Worker registered.');
      } else {
        setError(data.detail || 'Failed to register worker.');
      }
    } catch (err) {
      setError('Network error registering labour worker.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
      <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden p-6 space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <h3 className="text-sm font-bold text-slate-900 m-0">Register Labour Worker</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X size={18} />
          </button>
        </div>

        {error && <div className="p-2.5 rounded-lg bg-red-50 text-red-700 text-xs">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Worker Full Name *</label>
            <input
              type="text"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Radheshyam Sharma"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Station / Category</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              >
                <option value="ROLLING">Papad Rolling</option>
                <option value="PACKING">Pouch Packaging</option>
                <option value="ROASTING">Roasting & Drying</option>
                <option value="CLEANING">Sanitation / Cleaning</option>
                <option value="GENERAL">General Factory</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Wage Basis</label>
              <select
                value={wageType}
                onChange={(e) => setWageType(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              >
                <option value="DAILY">Daily Wage</option>
                <option value="PIECE_RATE">Piece-Rate / Per KG</option>
                <option value="HOURLY">Hourly Wage</option>
                <option value="MONTHLY">Monthly Fixed</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Standard Rate (₹)</label>
            <input
              type="number"
              step="any"
              required
              value={baseRate}
              onChange={(e) => setBaseRate(e.target.value)}
              placeholder="e.g. 450 for Daily, or 12 for Piece-Rate"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Mobile Contact</label>
            <input
              type="tel"
              value={mobile}
              onChange={(e) => setMobile(e.target.value)}
              placeholder="+91 98765 00000"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs disabled:opacity-50"
            >
              {isSubmitting ? 'Registering…' : 'Register Worker'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Sub-components: Assign Task Modal
const AssignTaskModal: React.FC<{
  employees: any[];
  onClose: () => void;
  onSuccess: (msg: string) => void;
}> = ({ employees, onClose, onSuccess }) => {
  const token = getAuthToken();
  const [assigneeId, setAssigneeId] = useState(employees[0]?.user_id || '');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState('MEDIUM');
  const [dueDate, setDueDate] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return setError('Task title is required.');
    setIsSubmitting(true);
    setError('');

    try {
      const res = await apiFetch('/api/workforce/tasks', {
        method: 'POST',
        body: JSON.stringify({
          assigned_to_user_id: assigneeId,
          title: title.trim(),
          description: description.trim(),
          priority,
          due_date: dueDate,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        onSuccess(data.message || 'Task assigned.');
      } else {
        setError(data.detail || 'Failed to assign task.');
      }
    } catch (err) {
      setError('Network error assigning task.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
      <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden p-6 space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <h3 className="text-sm font-bold text-slate-900 m-0">Assign Work Task</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X size={18} />
          </button>
        </div>

        {error && <div className="p-2.5 rounded-lg bg-red-50 text-red-700 text-xs">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Assign To Employee *</label>
            <select
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            >
              {employees.map((emp) => (
                <option key={emp.user_id} value={emp.user_id}>
                  {emp.full_name} ({emp.role})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Task Title *</label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Visit 10 shopkeepers in Sadar Bazaar / Create Papad banner"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Detailed Instructions</label>
            <textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Provide targets, instructions, and verification criteria…"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Priority</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              >
                <option value="LOW">Low</option>
                <option value="MEDIUM">Medium</option>
                <option value="HIGH">High</option>
                <option value="URGENT">Urgent</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Due Date</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              />
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs disabled:opacity-50"
            >
              {isSubmitting ? 'Assigning…' : 'Assign Task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Sub-components: Review Task Modal
const ReviewTaskModal: React.FC<{
  task: any;
  onClose: () => void;
  onSuccess: (msg: string) => void;
}> = ({ task, onClose, onSuccess }) => {
  const token = getAuthToken();
  const [status, setStatus] = useState('APPROVED');
  const [reviewNotes, setReviewNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      const res = await apiFetch(`/api/workforce/tasks/${task.task_id}/review`, {
        method: 'POST',
        body: JSON.stringify({
          status,
          review_notes: reviewNotes,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        onSuccess(data.message || 'Task reviewed.');
      }
    } catch (err) {}
    setIsSubmitting(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
      <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden p-6 space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <h3 className="text-sm font-bold text-slate-900 m-0">Review Task Deliverable</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X size={18} />
          </button>
        </div>

        <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 text-xs space-y-1">
          <div>Task: <strong>{task.title}</strong></div>
          <div>Submitted by: <strong>{task.assigned_to_name}</strong></div>
          <div>Deliverable Notes: <span className="text-slate-600">{task.submission_notes}</span></div>
          {task.proof_url && (
            <a href={task.proof_url} target="_blank" rel="noreferrer" className="text-emerald-700 font-bold underline block mt-1">
              Open Deliverable Link
            </a>
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Decision</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200 font-bold"
            >
              <option value="APPROVED">Approve Deliverable</option>
              <option value="REJECTED">Reject / Request Revisions</option>
              <option value="COMPLETED">Mark as Completed</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Review Feedback Notes</label>
            <textarea
              rows={2}
              value={reviewNotes}
              onChange={(e) => setReviewNotes(e.target.value)}
              placeholder="Feedback for employee…"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs disabled:opacity-50"
            >
              {isSubmitting ? 'Saving…' : 'Submit Decision'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Sub-components: Create Project Modal
const CreateProjectModal: React.FC<{
  employees: any[];
  onClose: () => void;
  onSuccess: (msg: string) => void;
}> = ({ employees, onClose, onSuccess }) => {
  const token = getAuthToken();
  const [freelancerId, setFreelancerId] = useState(employees[0]?.user_id || '');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [budget, setBudget] = useState('');
  const [targetDate, setTargetDate] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      const res = await apiFetch('/api/workforce/projects', {
        method: 'POST',
        body: JSON.stringify({
          freelancer_user_id: freelancerId,
          title: title.trim(),
          description: description.trim(),
          total_budget: Number(budget) || 0,
          target_completion_date: targetDate,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        onSuccess(data.message || 'Project created.');
      }
    } catch (err) {}
    setIsSubmitting(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
      <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden p-6 space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <h3 className="text-sm font-bold text-slate-900 m-0">Create Freelancer Project</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Contractor / Freelancer</label>
            <select
              value={freelancerId}
              onChange={(e) => setFreelancerId(e.target.value)}
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            >
              {employees.map((emp) => (
                <option key={emp.user_id} value={emp.user_id}>
                  {emp.full_name} ({emp.role})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Project Scope / Title *</label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Papad Pouch Redesign & Print Files"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Total Agreed Budget (₹)</label>
              <input
                type="number"
                required
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="25000"
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Target Date</label>
              <input
                type="date"
                value={targetDate}
                onChange={(e) => setTargetDate(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              />
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs disabled:opacity-50"
            >
              {isSubmitting ? 'Creating…' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Sub-components: Add Milestone Modal
const AddMilestoneModal: React.FC<{
  projectId: string;
  onClose: () => void;
  onSuccess: (msg: string) => void;
}> = ({ projectId, onClose, onSuccess }) => {
  const token = getAuthToken();
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      const res = await apiFetch(`/api/workforce/projects/${projectId}/milestones`, {
        method: 'POST',
        body: JSON.stringify({
          project_id: projectId,
          title: title.trim(),
          amount: Number(amount) || 0,
          due_date: dueDate,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        onSuccess(data.message || 'Milestone added.');
      }
    } catch (err) {}
    setIsSubmitting(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
      <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden p-6 space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <h3 className="text-sm font-bold text-slate-900 m-0">Add Project Milestone</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">Milestone Title *</label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Initial Packaging Vector Mockups"
              className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Milestone Payout (₹) *</label>
              <input
                type="number"
                required
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="10000"
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Target Date</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full text-xs p-2.5 rounded-xl border border-slate-200"
              />
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs disabled:opacity-50"
            >
              {isSubmitting ? 'Adding…' : 'Add Milestone'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
