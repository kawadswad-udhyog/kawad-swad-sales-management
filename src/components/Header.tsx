import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { UserRole } from '../types';
import { ViewType } from './Navigation';
import {
  Menu,
  RefreshCw,
  LogOut,
  Wifi,
  WifiOff,
  CheckCircle2,
  AlertTriangle,
  X,
  Server,
  Database,
  ExternalLink,
} from 'lucide-react';

interface HeaderProps {
  currentView?: ViewType;
  onToggleMobileNav?: () => void;
  onNavigate?: (v: ViewType) => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentView = 'dashboard',
  onToggleMobileNav,
  onNavigate,
}) => {
  const {
    currentUser,
    logout,
    backendUrl,
    updateBackendUrl,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
    connectionError,
    reconnectGoogleSheets,
    refreshData,
    isRefreshing,
  } = useStore();

  const [showStatusModal, setShowStatusModal] = useState(false);
  const [tempUrl, setTempUrl] = useState(backendUrl);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [lastSyncTime, setLastSyncTime] = useState<string>('Just now');

  const getRoleBadge = (role?: UserRole) => {
    switch (role) {
      case 'OWNER':
        return { label: 'Admin / Owner', bg: 'bg-amber-100 text-amber-800 border-amber-200' };
      case 'PA':
        return { label: 'Personal Assistant', bg: 'bg-blue-100 text-blue-800 border-blue-200' };
      case 'SALESMAN':
        return { label: 'Field Sales', bg: 'bg-emerald-100 text-emerald-800 border-emerald-200' };
      default:
        return { label: role || 'Staff', bg: 'bg-slate-100 text-slate-700 border-slate-200' };
    }
  };

  const getViewBreadcrumb = (v: ViewType) => {
    switch (v) {
      case 'dashboard':
        return { group: 'Overview', title: currentUser?.role === 'SALESMAN' ? 'Field Workspace' : 'Dashboard' };
      case 'production':
        return { group: 'Operations', title: 'Daily Production & Batches' };
      case 'attendance':
        return { group: 'Operations', title: 'Worker Attendance & Wages' };
      case 'packaging':
        return { group: 'Operations', title: 'Packaging & Reconciliation' };
      case 'stock':
        return { group: 'Inventory', title: 'Finished Goods & Ledgers' };
      case 'approvals':
        return { group: 'Inventory', title: 'Approvals & Requests' };
      case 'sales':
        return { group: 'Commercial', title: 'Sales Billing & Invoicing' };
      case 'customers':
        return { group: 'Commercial', title: 'Customer Directory' };
      case 'products':
        return { group: 'Commercial', title: 'Product Catalogue' };
      case 'expenses':
        return { group: 'Commercial', title: 'Expenses & Claims' };
      case 'visits':
        return { group: 'Commercial', title: 'Shop Visits & GPS Logs' };
      case 'closing':
        return { group: 'Commercial', title: 'Daily Cash Closing' };
      case 'salary':
        return { group: 'Management', title: 'Salary & Payroll' };
      case 'reports':
        return { group: 'Management', title: 'Reports & Data Exports' };
      case 'users':
        return { group: 'Management', title: 'Team & User Security' };
      case 'audit':
        return { group: 'Management', title: 'Audit Trail & Sheets Health' };
      default:
        return { group: 'Operations', title: 'Management System' };
    }
  };

  const roleBadge = getRoleBadge(currentUser?.role);
  const breadcrumb = getViewBreadcrumb(currentView);

  // Status configuration
  let statusBadge = {
    label: 'Online',
    color: 'text-emerald-700 bg-emerald-50 border-emerald-200',
    dot: 'bg-emerald-500',
    icon: <CheckCircle2 size={13} className="text-emerald-600" />,
  };

  if (!isBackendConnected) {
    if (connectionError) {
      statusBadge = {
        label: 'API Offline',
        color: 'text-red-700 bg-red-50 border-red-200',
        dot: 'bg-red-500',
        icon: <WifiOff size={13} className="text-red-600" />,
      };
    } else {
      statusBadge = {
        label: 'Connecting…',
        color: 'text-amber-700 bg-amber-50 border-amber-200',
        dot: 'bg-amber-500 animate-pulse',
        icon: <AlertTriangle size={13} className="text-amber-600" />,
      };
    }
  } else if (!isGoogleSheetsConnected || !persistentWritesEnabled) {
    statusBadge = {
      label: 'Sheets Offline',
      color: 'text-red-700 bg-red-50 border-red-200',
      dot: 'bg-red-500',
      icon: <WifiOff size={13} className="text-red-600" />,
    };
  }

  const handleManualReconnect = async () => {
    setIsReconnecting(true);
    try {
      const res = await reconnectGoogleSheets();
      if (res.success) {
        await refreshData();
        setLastSyncTime(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      }
    } finally {
      setIsReconnecting(false);
    }
  };

  const handleRefresh = async () => {
    await refreshData();
    setLastSyncTime(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
  };

  return (
    <>
      <header className="h-16 bg-white border-b border-slate-200 px-4 sm:px-6 flex items-center justify-between gap-4 sticky top-0 z-20 shrink-0">
        {/* Left Side: Mobile Menu Button & Breadcrumb */}
        <div className="flex items-center gap-3 min-w-0">
          {onToggleMobileNav && (
            <button
              onClick={onToggleMobileNav}
              className="lg:hidden p-2 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors"
              title="Open Navigation"
            >
              <Menu size={18} />
            </button>
          )}

          <div className="flex flex-col min-w-0">
            <nav className="flex items-center gap-1.5 text-xs text-slate-500">
              <span className="font-semibold text-emerald-800">Kawad Swad</span>
              <span>/</span>
              <span className="hidden sm:inline text-slate-400">{breadcrumb.group}</span>
              <span className="hidden sm:inline">/</span>
              <span className="font-semibold text-slate-900 truncate">{breadcrumb.title}</span>
            </nav>
            <div className="text-[11px] text-slate-400 font-medium">
              {new Date().toLocaleDateString('en-IN', {
                weekday: 'short',
                day: 'numeric',
                month: 'short',
                year: 'numeric',
              })}
            </div>
          </div>
        </div>

        {/* Right Side: Quick Actions, Connection Pill & User Info */}
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          {/* Refresh Button */}
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-700 text-xs font-semibold transition-colors disabled:opacity-50"
            title={`Refresh active workspace data (Last synced: ${lastSyncTime})`}
          >
            <RefreshCw size={13} className={isRefreshing ? 'animate-spin text-emerald-600' : 'text-slate-500'} />
            <span className="hidden md:inline">{isRefreshing ? 'Syncing…' : 'Sync'}</span>
          </button>

          {/* Connection Status Pill */}
          <button
            onClick={() => setShowStatusModal(true)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold transition-all hover:shadow-xs cursor-pointer ${statusBadge.color}`}
            title="Inspect backend & Google Sheets connection health"
          >
            <span className={`w-1.5 h-1.5 rounded-full ${statusBadge.dot}`} />
            {statusBadge.icon}
            <span>{statusBadge.label}</span>
          </button>

          {/* Logged in User Badge */}
          {currentUser && (
            <div className="flex items-center gap-2 pl-2 border-l border-slate-200">
              <div className="flex items-center gap-2 p-1 rounded-lg">
                <div className="w-8 h-8 rounded-full bg-emerald-800 text-white flex items-center justify-center text-xs font-bold shrink-0 shadow-xs">
                  {currentUser.full_name ? currentUser.full_name.charAt(0).toUpperCase() : 'U'}
                </div>
                <div className="hidden sm:flex flex-col text-left leading-tight">
                  <div className="text-xs font-bold text-slate-900 truncate max-w-[130px]">
                    {currentUser.full_name}
                  </div>
                  <div className="text-[10px] font-semibold text-emerald-800">
                    {roleBadge.label}
                  </div>
                </div>
              </div>

              {/* Logout Button */}
              <button
                onClick={logout}
                className="p-2 text-slate-500 hover:text-red-700 hover:bg-red-50 rounded-lg border border-transparent hover:border-red-200 transition-colors"
                title="Sign out of ERP"
              >
                <LogOut size={16} />
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Connection Details Diagnostic Modal */}
      {showStatusModal && (
        <div
          onClick={() => setShowStatusModal(false)}
          className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs z-50 flex items-center justify-center p-4"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="bg-white rounded-xl max-w-lg w-full p-6 shadow-xl border border-slate-200 animate-in fade-in zoom-in-95 duration-150"
          >
            <div className="flex items-center justify-between pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-emerald-50 text-emerald-800 rounded-lg">
                  <Server size={18} />
                </div>
                <div>
                  <h3 className="font-bold text-slate-900 text-base m-0">Connection Diagnostics</h3>
                  <p className="text-xs text-slate-500 m-0">FastAPI Backend & Google Sheets Persistence</p>
                </div>
              </div>
              <button
                onClick={() => setShowStatusModal(false)}
                className="p-1.5 text-slate-400 hover:text-slate-700 rounded-md"
              >
                <X size={18} />
              </button>
            </div>

            {/* Checklist items */}
            <div className="py-4 space-y-3">
              {/* Backend API */}
              <div className={`p-3.5 rounded-lg border flex items-center justify-between ${
                isBackendConnected ? 'bg-emerald-50/50 border-emerald-200' : 'bg-amber-50/60 border-amber-200'
              }`}>
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-md ${isBackendConnected ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                    <Server size={16} />
                  </div>
                  <div>
                    <div className="font-semibold text-slate-900 text-xs">FastAPI Backend Service</div>
                    <div className="text-[11px] text-slate-500 truncate max-w-[240px]">
                      {backendUrl || 'Direct / Proxy'}
                    </div>
                  </div>
                </div>
                <span className={`text-xs font-bold px-2 py-0.5 rounded-md ${
                  isBackendConnected ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                }`}>
                  {isBackendConnected ? 'Online ✓' : 'Connecting / Waking…'}
                </span>
              </div>

              {/* Google Sheets Persistence */}
              <div className={`p-3.5 rounded-lg border flex items-center justify-between ${
                isGoogleSheetsConnected && persistentWritesEnabled
                  ? 'bg-emerald-50/50 border-emerald-200'
                  : 'bg-red-50/60 border-red-200'
              }`}>
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-md ${
                    isGoogleSheetsConnected && persistentWritesEnabled
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-red-100 text-red-700'
                  }`}>
                    <Database size={16} />
                  </div>
                  <div>
                    <div className="font-semibold text-slate-900 text-xs">Google Sheets Persistence</div>
                    <div className="text-[11px] text-slate-500">28-sheet enterprise ledger & auth database</div>
                  </div>
                </div>
                <span className={`text-xs font-bold px-2 py-0.5 rounded-md ${
                  isGoogleSheetsConnected && persistentWritesEnabled
                    ? 'bg-emerald-100 text-emerald-800'
                    : 'bg-red-100 text-red-800'
                }`}>
                  {isGoogleSheetsConnected && persistentWritesEnabled ? 'Connected ✓' : 'Disconnected ✗'}
                </span>
              </div>

              {connectionError && (
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-600">
                  <span className="font-semibold text-slate-700">Diagnostic message:</span> {connectionError}
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-100 gap-2">
              <button
                disabled={isReconnecting}
                onClick={handleManualReconnect}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold transition-colors disabled:opacity-50"
              >
                <RefreshCw size={14} className={isReconnecting ? 'animate-spin' : ''} />
                <span>{isReconnecting ? 'Reconnecting Sheets…' : 'Reconnect Google Sheets'}</span>
              </button>

              <button
                onClick={() => setShowStatusModal(false)}
                className="px-4 py-2 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 text-xs font-semibold transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
