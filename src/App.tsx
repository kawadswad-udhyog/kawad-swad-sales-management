import React, { useState, useEffect, useMemo } from 'react';
import { useStore, StoreProvider } from './context/StoreContext';
import { Header } from './components/Header';
import { Navigation, ViewType } from './components/Navigation';
import { LoginModal } from './components/LoginModal';
import { ErrorBoundary } from './components/ErrorBoundary';
import { DashboardView } from './views/DashboardView';
import { ProductsView } from './views/ProductsView';
import { CustomersView } from './views/CustomersView';
import { SalesView } from './views/SalesView';
import { StockView } from './views/StockView';
import { ExpensesView } from './views/ExpensesView';
import { VisitsView } from './views/VisitsView';
import { ClosingView } from './views/ClosingView';
import { SalaryView } from './views/SalaryView';
import { ReportsView } from './views/ReportsView';
import { AuditView } from './views/AuditView';
import { UsersView } from './views/UsersView';
import { ProductionView } from './views/ProductionView';
import { AttendanceView } from './views/AttendanceView';
import { ApprovalsView } from './views/ApprovalsView';
import { AccountingView } from './views/AccountingView';
import { PurchasingView } from './views/PurchasingView';
import { QualityView } from './views/QualityView';
import { WorkforceView } from './views/WorkforceView';
import { EmployeePortal } from './employee/EmployeePortal';
import { WorkspaceId, WORKSPACES, getWorkspaceForRole } from './utils/workspaces';
import { AlertTriangle, AlertCircle, RefreshCw, X, ShieldAlert } from 'lucide-react';

const MainAppContent: React.FC = () => {
  const {
    currentUser,
    syncError,
    clearSyncError,
    refreshData,
    isLoading,
    isRefreshing,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
    connectionError,
    reconnectGoogleSheets,
  } = useStore();

  const [activeWorkspaceOverride, setActiveWorkspaceOverride] = useState<WorkspaceId | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const [isPreviewingEmployeePortal, setIsPreviewingEmployeePortal] = useState(false);

  // Active workspace calculation
  const role = String(currentUser?.role || '').toUpperCase();
  const isOwner = ['OWNER', 'OWNER_ADMIN', 'ADMIN'].includes(role);

  const activeWorkspace = useMemo(() => {
    if (isOwner && activeWorkspaceOverride && WORKSPACES[activeWorkspaceOverride]) {
      return WORKSPACES[activeWorkspaceOverride];
    }
    return getWorkspaceForRole(currentUser?.role);
  }, [currentUser?.role, isOwner, activeWorkspaceOverride]);

  // View state with strict authorization enforcement
  const [currentView, setCurrentView] = useState<ViewType>(() => {
    if (typeof window !== 'undefined') {
      const saved = sessionStorage.getItem('ks_current_view') as ViewType | null;
      if (saved) return saved;
    }
    return 'dashboard';
  });

  // Ensure currentView is always valid and authorized for the active workspace
  useEffect(() => {
    if (currentUser && activeWorkspace) {
      if (!activeWorkspace.allowedViews.includes(currentView)) {
        setCurrentView(activeWorkspace.defaultView);
        if (typeof window !== 'undefined') {
          sessionStorage.setItem('ks_current_view', activeWorkspace.defaultView);
        }
      }
    }
  }, [currentUser, activeWorkspace, currentView]);

  const handleSelectView = (v: ViewType) => {
    // Only allow selecting views permitted in the active workspace
    if (activeWorkspace.allowedViews.includes(v)) {
      setCurrentView(v);
      setIsMobileNavOpen(false);
      if (typeof window !== 'undefined') {
        sessionStorage.setItem('ks_current_view', v);
      }
    } else {
      setCurrentView(activeWorkspace.defaultView);
    }
  };

  const handleWorkspaceChange = (wId: WorkspaceId) => {
    setActiveWorkspaceOverride(wId);
    const targetWs = WORKSPACES[wId];
    if (targetWs) {
      if (!targetWs.allowedViews.includes(currentView)) {
        handleSelectView(targetWs.defaultView);
      }
    }
  };

  const handleExitWorkspacePreview = () => {
    setActiveWorkspaceOverride(null);
    const ownerWs = WORKSPACES.owner;
    handleSelectView(ownerWs.defaultView);
  };

  // Dedicated Employee Portal for employee-only roles or when explicitly requested
  const isEmployeeOnlyRole = [
    'FREELANCER',
    'SOCIAL_MEDIA_ECOMMERCE_MANAGER',
    'SOCIAL_MEDIA_MANAGER',
    'ECOMMERCE_MANAGER',
  ].includes(role);

  if (isLoading && !currentUser) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <Header />
        <main className="flex-1 flex flex-col items-center justify-center p-6 text-center">
          <div className="w-12 h-12 rounded-2xl bg-emerald-800 text-white flex items-center justify-center font-extrabold text-lg mb-4 shadow-sm animate-pulse">
            KS
          </div>
          <h2 className="text-base font-bold text-slate-900 m-0">Kawad Swad Udhyog</h2>
          <p className="text-xs text-slate-500 mt-1 max-w-xs">
            Restoring session and initializing secure ERP workspace…
          </p>
        </main>
      </div>
    );
  }

  if (!currentUser) {
    return <LoginModal />;
  }

  if ((isEmployeeOnlyRole && !activeWorkspaceOverride) || isPreviewingEmployeePortal) {
    return (
      <EmployeePortal
        isOwnerPreviewing={isPreviewingEmployeePortal}
        onExitPreview={() => setIsPreviewingEmployeePortal(false)}
      />
    );
  }

  const renderView = () => {
    switch (currentView) {
      case 'dashboard':
        return (
          <DashboardView
            onNavigate={(v) => handleSelectView(v)}
            activeWorkspaceId={activeWorkspace.id}
          />
        );
      case 'purchasing':
        return <PurchasingView />;
      case 'production':
        return <ProductionView initialTab="production" />;
      case 'attendance':
        return <AttendanceView />;
      case 'packaging':
        return <ProductionView initialTab="packaging" />;
      case 'quality':
        return <QualityView />;
      case 'stock':
        return <StockView />;
      case 'sales':
        return <SalesView />;
      case 'approvals':
        return <ApprovalsView />;
      case 'customers':
        return <CustomersView onNavigate={(v) => handleSelectView(v)} />;
      case 'products':
        return <ProductsView />;
      case 'expenses':
        return <ExpensesView />;
      case 'visits':
        return <VisitsView />;
      case 'closing':
        return <ClosingView />;
      case 'salary':
        return <SalaryView />;
      case 'workforce':
        return (
          <WorkforceView
            onPreviewEmployeePortal={() => setIsPreviewingEmployeePortal(true)}
          />
        );
      case 'reports':
        return <ReportsView />;
      case 'accounting':
        return <AccountingView />;
      case 'audit':
        return <AuditView />;
      case 'users':
        return <UsersView />;
      default:
        return (
          <DashboardView
            onNavigate={(v) => handleSelectView(v)}
            activeWorkspaceId={activeWorkspace.id}
          />
        );
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col antialiased">
      <Header
        currentView={currentView}
        onToggleMobileNav={() => setIsMobileNavOpen((prev) => !prev)}
        onNavigate={handleSelectView}
        activeWorkspaceId={activeWorkspace.id}
        onChangeWorkspace={handleWorkspaceChange}
        isOwnerPreviewing={Boolean(activeWorkspaceOverride)}
        onExitWorkspacePreview={handleExitWorkspacePreview}
      />

      {/* Critical Status Banners */}
      {!isBackendConnected && (
        <div className="bg-amber-900 text-amber-50 px-4 py-2.5 flex items-center justify-between text-xs flex-wrap gap-2 border-b border-amber-700">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-amber-300 shrink-0" />
            <div>
              <span className="font-bold">Backend API Standby:</span> Cannot reach backend service right now.
              <span className="text-amber-200 ml-1.5 hidden sm:inline">
                The Render server may be spinning up from cold sleep (~40s).
                {connectionError ? ` (${connectionError})` : ''}
              </span>
            </div>
          </div>
          <button
            disabled={isRefreshing}
            onClick={() => refreshData()}
            className="flex items-center gap-1.5 px-3 py-1 rounded bg-amber-700 hover:bg-amber-600 font-semibold text-xs transition-colors shrink-0 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw size={13} className={isRefreshing ? 'animate-spin' : ''} />
            <span>{isRefreshing ? 'Connecting…' : 'Retry Connection'}</span>
          </button>
        </div>
      )}

      {isBackendConnected && (!isGoogleSheetsConnected || !persistentWritesEnabled) && (
        <div className="bg-red-900 text-red-50 px-4 py-2.5 flex items-center justify-between text-xs flex-wrap gap-2 border-b border-red-700">
          <div className="flex items-center gap-2">
            <ShieldAlert size={16} className="text-red-300 shrink-0" />
            <div>
              <span className="font-bold">Persistent Storage Locked:</span> Google Sheets is currently disconnected from the backend.
              <span className="text-red-200 ml-1.5 hidden sm:inline">
                New sales, production approvals, and payment writes are paused to prevent silent data loss.
              </span>
            </div>
          </div>
          <button
            disabled={isReconnecting}
            onClick={async () => {
              setIsReconnecting(true);
              try {
                const res = await reconnectGoogleSheets();
                if (res.success) {
                  await refreshData();
                }
              } finally {
                setIsReconnecting(false);
              }
            }}
            className="flex items-center gap-1.5 px-3 py-1 rounded bg-red-700 hover:bg-red-600 font-semibold text-xs transition-colors shrink-0 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw size={13} className={isReconnecting ? 'animate-spin' : ''} />
            <span>{isReconnecting ? 'Reconnecting…' : 'Reconnect Sheets'}</span>
          </button>
        </div>
      )}

      {syncError && isBackendConnected && isGoogleSheetsConnected && persistentWritesEnabled && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center justify-between text-xs text-amber-800">
          <div className="flex items-center gap-2">
            <AlertCircle size={15} className="text-amber-600 shrink-0" />
            <span><strong>Sync Warning:</strong> {syncError}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              disabled={isRefreshing}
              onClick={() => refreshData()}
              className="text-xs font-semibold text-amber-800 hover:underline"
            >
              Retry
            </button>
            <button
              onClick={clearSyncError}
              className="p-1 text-amber-600 hover:text-amber-900"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Main ERP Layout: Sidebar on Left, Content Area on Right */}
      <div className="flex-1 flex overflow-hidden">
        <Navigation
          currentView={currentView}
          onSelectView={handleSelectView}
          isOpenMobile={isMobileNavOpen}
          onCloseMobile={() => setIsMobileNavOpen(false)}
          activeWorkspaceId={activeWorkspace.id}
        />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto">
          <ErrorBoundary>
            {renderView()}
          </ErrorBoundary>
        </main>
      </div>

      <footer className="bg-white border-t border-slate-200 py-3 px-6 text-center text-xs text-slate-400">
        Kawad Swad Udhyog · Sales & Factory Management ERP · Nimar, Madhya Pradesh
      </footer>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <StoreProvider>
        <MainAppContent />
      </StoreProvider>
    </ErrorBoundary>
  );
};

export default App;
