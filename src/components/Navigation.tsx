import React from 'react';
import { useStore } from '../context/StoreContext';

export type ViewType =
  | 'dashboard'
  | 'products'
  | 'customers'
  | 'sales'
  | 'stock'
  | 'expenses'
  | 'visits'
  | 'closing'
  | 'salary'
  | 'reports'
  | 'audit'
  | 'users'
  | 'production';

interface NavigationProps {
  currentView: ViewType;
  onSelectView: (view: ViewType) => void;
}

export const Navigation: React.FC<NavigationProps> = ({ currentView, onSelectView }) => {
  const { currentUser, logout } = useStore();
  const role = currentUser?.role;

  const navItems: { view: ViewType; label: string; roles: string[] }[] = [
    { view: 'dashboard', label: role === 'SALESMAN' ? 'Field Workspace' : 'Dashboard', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'sales', label: 'Sales & Bills', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'products', label: 'Products', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'customers', label: 'Customers', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'stock', label: 'Stock', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'expenses', label: 'Expenses', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'visits', label: 'Shop Visits', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'closing', label: 'Daily Closing', roles: ['OWNER', 'PA', 'SALESMAN'] },
    { view: 'production', label: 'Production', roles: ['OWNER', 'PA'] },
    { view: 'salary', label: 'Salary & Incentives', roles: ['OWNER', 'PA'] },
    { view: 'reports', label: 'Reports & Exports', roles: ['OWNER', 'PA'] },
    { view: 'audit', label: 'Audit Log', roles: ['OWNER', 'PA'] },
    { view: 'users', label: 'Users', roles: ['OWNER'] },
  ];

  const visibleItems = navItems.filter((item) => role && item.roles.includes(role));

  return (
    <nav className="nav-bar" style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
      {visibleItems.map((item) => (
        <button
          key={item.view}
          className={currentView === item.view ? 'active' : ''}
          onClick={() => onSelectView(item.view)}
        >
          {item.label}
        </button>
      ))}

      {currentUser && (
        <button
          type="button"
          onClick={logout}
          style={{
            marginLeft: 'auto',
            background: '#fee2e2',
            border: '1px solid #fca5a5',
            color: '#b91c1c',
            fontWeight: 700,
            cursor: 'pointer',
            padding: '6px 14px',
            borderRadius: '6px',
            fontSize: '0.80rem',
            whiteSpace: 'nowrap'
          }}
          title="Sign out of current account"
        >
          Sign Out ({currentUser.username || currentUser.user_id})
        </button>
      )}
    </nav>
  );
};
