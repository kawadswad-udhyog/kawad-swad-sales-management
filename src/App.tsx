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

const MainAppContent: React.FC = () => {
  const { currentUser } = useStore();
  const [currentView, setCurrentView] = useState<ViewType>('dashboard');

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
        return <DashboardView onNavigate={(v) => setCurrentView(v)} />;
      case 'products':
        return <ProductsView />;
      case 'customers':
        return <CustomersView />;
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
      default:
        return <DashboardView onNavigate={(v) => setCurrentView(v)} />;
    }
  };

  return (
    <div>
      <Header />
      <main>
        <Navigation currentView={currentView} onSelectView={setCurrentView} />
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
