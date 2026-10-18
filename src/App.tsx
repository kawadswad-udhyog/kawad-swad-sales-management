import React, { useState } from 'react';
import { useStore, StoreProvider } from './context/StoreContext';
import { Header } from './components/Header';
import { Navigation, ViewType } from './components/Navigation';
import { LoginModal } from './components/LoginModal';
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

const MainAppContent: React.FC = () => {
  const {
    currentUser,
    syncError,
    clearSyncError,
    refreshData,
    isLoading,
    isRefreshing,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
    connectionError,
    reconnectGoogleSheets,
  } = useStore();
  const [currentView, setCurrentView] = useState<ViewType>(() => {
    if (typeof window !== 'undefined') {
      const saved = sessionStorage.getItem('ks_current_view');
      if (saved) return saved as ViewType;
    }
    return 'dashboard';
  });

  const handleSelectView = (v: ViewType) => {
    setCurrentView(v);
    if (typeof window !== 'undefined') {
      sessionStorage.setItem('ks_current_view', v);
    }
  };

  if (isLoading && !currentUser) {
    return (
      <div>
        <Header />
        <main style={{ padding: '80px 20px', textAlign: 'center', color: '#475569' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '16px' }}>⏳</div>
          <h2 style={{ margin: '0 0 8px', color: '#14532d' }}>Kawad Swad Udhyog</h2>
          <p style={{ margin: 0, fontSize: '0.95rem', color: '#64748b' }}>
            Restoring session and syncing catalogue data…
          </p>
        </main>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <div>
        <Header />
        <main>
          <LoginModal />
        </main>
      </div>
    );
  }

  const renderView = () => {
    switch (currentView) {
      case 'dashboard':
        return <DashboardView onNavigate={(v) => handleSelectView(v)} />;
      case 'products':
        return <ProductsView />;
      case 'customers':
        return <CustomersView onNavigate={(v) => handleSelectView(v)} />;
      case 'sales':
        return <SalesView />;
      case 'stock':
        return <StockView />;
      case 'expenses':
        return <ExpensesView />;
      case 'visits':
        return <VisitsView />;
      case 'closing':
        return <ClosingView />;
      case 'salary':
        return <SalaryView />;
      case 'reports':
        return <ReportsView />;
      case 'audit':
        return <AuditView />;
      case 'users':
        return <UsersView />;
      case 'production':
        return <ProductionView />;
      default:
        return <DashboardView onNavigate={(v) => handleSelectView(v)} />;
    }
  };

  const [isReconnecting, setIsReconnecting] = useState(false);

  return (
    <div>
      <Header />
      {(!isGoogleSheetsConnected || !persistentWritesEnabled) && (
        <div style={{
          background: '#450a0a',
          borderBottom: '2px solid #ef4444',
          padding: '12px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          color: '#fee2e2',
          fontSize: '0.88rem',
          flexWrap: 'wrap',
          gap: '12px'
        }}>
          <div>
            <strong>🔴 Persistent Storage Disconnected:</strong> Google Sheets is currently unreachable.
            <div style={{ fontSize: '0.80rem', marginTop: '2px', color: '#fca5a5' }}>
              Business writes (new sales bills, batch production, payments) are temporarily locked to prevent data loss.
              {connectionError ? ` Reason: ${connectionError}` : ''}
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
            style={{
              padding: '6px 14px',
              fontSize: '0.80rem',
              fontWeight: 700,
              background: isReconnecting ? '#991b1b' : '#ef4444',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              cursor: isReconnecting ? 'not-allowed' : 'pointer'
            }}
          >
            {isReconnecting ? '⏳ Reconnecting…' : '🔄 Reconnect Google Sheets'}
          </button>
        </div>
      )}
      {syncError && (
        <div style={{
          background: '#fef2f2',
          borderBottom: '1px solid #fecaca',
          padding: '10px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          color: '#991b1b',
          fontSize: '0.88rem'
        }}>
          <div>
            <strong>⚠️ Database Sync Warning:</strong> {syncError}
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => refreshData()}
              style={{
                padding: '4px 10px',
                fontSize: '0.8rem',
                background: '#dc2626',
                color: '#fff',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              Retry Sync
            </button>
            <button
              onClick={clearSyncError}
              style={{
                padding: '4px 8px',
                fontSize: '0.8rem',
                background: 'transparent',
                color: '#991b1b',
                border: 'none',
                cursor: 'pointer'
              }}
            >
              ✕
            </button>
          </div>
        </div>
      )}
      <main>
        <Navigation currentView={currentView} onSelectView={handleSelectView} />
        {renderView()}
      </main>
      <footer style={{ textAlign: 'center', padding: '30px 16px', color: '#718078', fontSize: '0.85rem' }}>
        Kawad Swad Udhyog · Sales Management System · Nimar, Madhya Pradesh
      </footer>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <StoreProvider>
      <MainAppContent />
    </StoreProvider>
  );
};

export default App;
