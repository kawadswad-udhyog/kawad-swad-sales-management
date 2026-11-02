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
  Copy,
  Check,
  FileSpreadsheet,
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
    verifyGoogleSheetsTabs,
    refreshData,
    isRefreshing,
  } = useStore();

  const [showStatusModal, setShowStatusModal] = useState(false);
  const [isEditingUrl, setIsEditingUrl] = useState(false);
  const [urlInput, setUrlInput] = useState(backendUrl);
  const [isTestingBackend, setIsTestingBackend] = useState(false);
  const [backendTestStatus, setBackendTestStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isVerifyingTabs, setIsVerifyingTabs] = useState(false);
  const [verifyResult, setVerifyResult] = useState<any>(null);
  const [copiedSnippet, setCopiedSnippet] = useState(false);
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
    statusBadge = {
      label: 'Standby Mode (Local)',
      color: 'text-amber-800 bg-amber-50 border-amber-300',
      dot: 'bg-amber-500',
      icon: <Server size={13} className="text-amber-600" />,
    };
  } else if (!isGoogleSheetsConnected || !persistentWritesEnabled) {
    statusBadge = {
      label: 'Sheets Standby',
      color: 'text-amber-800 bg-amber-50 border-amber-300',
      dot: 'bg-amber-500 animate-pulse',
      icon: <Database size={13} className="text-amber-600" />,
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

  const handleManualVerifyTabs = async () => {
    setIsVerifyingTabs(true);
    setVerifyResult(null);
    try {
      const res = await verifyGoogleSheetsTabs();
      setVerifyResult(res);
    } finally {
      setIsVerifyingTabs(false);
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
              <div className={`p-3.5 rounded-lg border ${
                isBackendConnected ? 'bg-emerald-50/50 border-emerald-200' : 'bg-amber-50/60 border-amber-200'
              }`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-md ${isBackendConnected ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                      <Server size={16} />
                    </div>
                    <div>
                      <div className="font-semibold text-slate-900 text-xs">FastAPI Backend Service</div>
                      <div className="text-[11px] text-slate-500 truncate max-w-[220px]">
                        {backendUrl || 'Proxy Rewrites (/api)'}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setIsEditingUrl(!isEditingUrl);
                        setUrlInput(backendUrl || 'https://kawad-swad-sales-dev.onrender.com');
                      }}
                      className="text-[11px] font-semibold text-emerald-800 underline hover:text-emerald-950 cursor-pointer"
                    >
                      {isEditingUrl ? 'Cancel' : 'Change URL'}
                    </button>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-md ${
                      isBackendConnected ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                    }`}>
                      {isBackendConnected ? 'Online ✓' : 'Standby / Waking…'}
                    </span>
                  </div>
                </div>

                {/* Inline URL configuration input */}
                {isEditingUrl && (
                  <div className="mt-3 pt-3 border-t border-amber-200/70 space-y-2">
                    <label className="block text-[11px] font-bold text-slate-700">
                      Backend Service URL (Render):
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="url"
                        value={urlInput}
                        onChange={(e) => setUrlInput(e.target.value)}
                        placeholder="https://your-backend.onrender.com"
                        className="flex-1 px-2.5 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700 font-mono"
                      />
                      <button
                        type="button"
                        disabled={isTestingBackend}
                        onClick={async () => {
                          setIsTestingBackend(true);
                          setBackendTestStatus(null);
                          try {
                            const clean = urlInput.trim();
                            updateBackendUrl(clean);
                            const res = await reconnectGoogleSheets();
                            setBackendTestStatus({
                              ok: res.success || isBackendConnected,
                              msg: res.success ? 'Connected to live backend and Google Sheets!' : 'Backend URL saved! Service pinged.',
                            });
                            setIsEditingUrl(false);
                          } catch (e: unknown) {
                            setBackendTestStatus({
                              ok: false,
                              msg: e instanceof Error ? e.message : 'Backend connection attempt failed.',
                            });
                          } finally {
                            setIsTestingBackend(false);
                          }
                        }}
                        className="px-3 py-1.5 bg-emerald-800 hover:bg-emerald-900 text-white font-semibold text-xs rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
                      >
                        {isTestingBackend ? 'Testing…' : 'Save & Connect'}
                      </button>
                    </div>
                    <div className="text-[10px] text-slate-500">
                      💡 Tip: Copy the web service URL from your Render dashboard (Tab 2) and paste here.
                    </div>
                  </div>
                )}

                {backendTestStatus && (
                  <div className={`mt-2 p-2 rounded text-xs font-semibold ${
                    backendTestStatus.ok ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-900'
                  }`}>
                    {backendTestStatus.msg}
                  </div>
                )}
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

              {(!isGoogleSheetsConnected || !persistentWritesEnabled) && (
                <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 space-y-2">
                  <div className="font-bold flex items-center gap-1.5 text-amber-800">
                    <AlertTriangle size={14} className="text-amber-700" />
                    <span>How to connect your live Google Sheet:</span>
                  </div>
                  <ol className="list-decimal pl-4 space-y-1 text-amber-800 text-[11px] leading-relaxed">
                    <li>
                      <strong>Spreadsheet ID:</strong> Open your Google Sheet (<code className="bg-amber-100/70 px-1 py-0.5 rounded">Kawad_Swad_Sales_Management</code>), copy the ID from the URL between <code className="bg-amber-100/70 px-1 py-0.5 rounded">/d/</code> and <code className="bg-amber-100/70 px-1 py-0.5 rounded">/edit</code>.
                    </li>
                    <li>
                      <strong>Share with Service Account:</strong> In Google Sheets, click <strong>Share</strong> and add your Google Service Account email (<code className="bg-amber-100/70 px-1 py-0.5 rounded">...@...iam.gserviceaccount.com</code>) with <strong>Editor</strong> permission.
                    </li>
                    <li>
                      <strong>Configure Render Backend:</strong> In your Render dashboard &rarr; <code className="bg-amber-100/70 px-1 py-0.5 rounded">kawad-swad-sales-dev</code> &rarr; <strong>Environment</strong>, add:
                      <div className="mt-1 font-mono text-[10px] bg-white/80 p-2 rounded border border-amber-200 space-y-0.5 relative">
                        <button
                          type="button"
                          onClick={() => {
                            const snippet = 'SALES_GOOGLE_SPREADSHEET_ID=(Your Sheet ID)\nSALES_ENV=production\nSALES_TESTING=0\nSALES_JWT_SECRET=(Set in Render Environment Settings)';
                            navigator.clipboard.writeText(snippet);
                            setCopiedSnippet(true);
                            setTimeout(() => setCopiedSnippet(false), 2000);
                          }}
                          className="absolute top-1.5 right-1.5 text-[10px] font-bold text-emerald-800 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200 hover:bg-emerald-100 flex items-center gap-1 cursor-pointer"
                        >
                          {copiedSnippet ? <Check size={11} /> : <Copy size={11} />}
                          <span>{copiedSnippet ? 'Copied' : 'Copy'}</span>
                        </button>
                        <div>SALES_GOOGLE_SPREADSHEET_ID = (Your Sheet ID)</div>
                        <div>SALES_GOOGLE_SERVICE_ACCOUNT_JSON = (Paste full JSON key)</div>
                        <div>SALES_ENV = production</div>
                        <div>SALES_TESTING = 0</div>
                      </div>
                    </li>
                    <li>
                      Click <strong>Save Changes</strong> on Render, wait ~30s for redeployment, then click <strong>Reconnect Google Sheets</strong> below.
                    </li>
                  </ol>
                </div>
              )}

              {verifyResult && (
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs space-y-1.5 max-h-40 overflow-y-auto">
                  <div className="font-bold text-slate-800 flex items-center justify-between">
                    <span>Sheet Verification Status:</span>
                    <span className={verifyResult.all_tabs_accessible ? 'text-emerald-700 font-bold' : 'text-amber-700 font-bold'}>
                      {verifyResult.all_tabs_accessible ? 'All 28 Tabs Accessible ✓' : 'Partial / Standby'}
                    </span>
                  </div>
                  {verifyResult.error && <p className="text-red-600 m-0">{verifyResult.error}</p>}
                </div>
              )}

              {connectionError && (
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-600">
                  <span className="font-semibold text-slate-700">Diagnostic message:</span> {connectionError}
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="flex flex-wrap items-center justify-between pt-4 border-t border-slate-100 gap-2">
              <div className="flex items-center gap-2">
                <button
                  disabled={isReconnecting}
                  onClick={handleManualReconnect}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold transition-colors disabled:opacity-50 cursor-pointer"
                >
                  <RefreshCw size={14} className={isReconnecting ? 'animate-spin' : ''} />
                  <span>{isReconnecting ? 'Reconnecting…' : 'Reconnect Google Sheets'}</span>
                </button>

                <button
                  disabled={isVerifyingTabs}
                  onClick={handleManualVerifyTabs}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold transition-colors disabled:opacity-50 cursor-pointer"
                >
                  <FileSpreadsheet size={14} className={isVerifyingTabs ? 'animate-spin text-emerald-700' : ''} />
                  <span>{isVerifyingTabs ? 'Checking…' : 'Verify 28 Tabs'}</span>
                </button>
              </div>

              <button
                onClick={() => setShowStatusModal(false)}
                className="px-4 py-2 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 text-xs font-semibold transition-colors cursor-pointer"
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
