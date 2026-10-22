import React from 'react';
import { useStore } from '../context/StoreContext';
import {
  LayoutDashboard,
  Factory,
  UserCheck,
  Package,
  Boxes,
  ShoppingCart,
  CheckSquare,
  Users as UsersIcon,
  Tag,
  Receipt,
  MapPin,
  Lock,
  Coins,
  FileText,
  Shield,
  Activity,
  X,
} from 'lucide-react';

export type ViewType =
  | 'dashboard'
  | 'production'
  | 'attendance'
  | 'packaging'
  | 'stock'
  | 'sales'
  | 'approvals'
  | 'customers'
  | 'products'
  | 'expenses'
  | 'visits'
  | 'closing'
  | 'salary'
  | 'reports'
  | 'users'
  | 'audit';

interface NavigationProps {
  currentView: ViewType;
  onSelectView: (view: ViewType) => void;
  isOpenMobile?: boolean;
  onCloseMobile?: () => void;
}

export const Navigation: React.FC<NavigationProps> = ({
  currentView,
  onSelectView,
  isOpenMobile = false,
  onCloseMobile,
}) => {
  const { currentUser, approvalRequests, expenses, dashboardMetrics } = useStore();
  const role = currentUser?.role;

  const pendingApprovalsCount =
    (approvalRequests?.filter((r) => r.status === 'PENDING').length || 0) +
    (dashboardMetrics?.pending_production_approvals || 0);

  const pendingExpensesCount =
    expenses?.filter((e) => e.approval_status === 'PENDING').length ||
    dashboardMetrics?.pending_expenses ||
    0;

  const navItems: {
    view: ViewType;
    label: string;
    icon: React.ReactNode;
    roles: string[];
    badge?: number;
    badgeColor?: string;
  }[] = [
    {
      view: 'dashboard',
      label: role === 'SALESMAN' ? 'Field Workspace' : 'Dashboard',
      icon: <LayoutDashboard size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
    },
    {
      view: 'production',
      label: 'Production',
      icon: <Factory size={18} />,
      roles: ['OWNER', 'PA'],
    },
    {
      view: 'attendance',
      label: 'Attendance',
      icon: <UserCheck size={18} />,
      roles: ['OWNER', 'PA'],
    },
    {
      view: 'packaging',
      label: 'Packaging',
      icon: <Package size={18} />,
      roles: ['OWNER', 'PA'],
    },
    {
      view: 'stock',
      label: 'Inventory',
      icon: <Boxes size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
    },
    {
      view: 'sales',
      label: 'Sales & Bills',
      icon: <ShoppingCart size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
    },
    {
      view: 'approvals',
      label: 'Approvals',
      icon: <CheckSquare size={18} />,
      roles: ['OWNER', 'PA'],
      badge: pendingApprovalsCount,
      badgeColor: '#b45309',
    },
    {
      view: 'customers',
      label: 'Customers',
      icon: <UsersIcon size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
    },
    {
      view: 'products',
      label: 'Products',
      icon: <Tag size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
    },
    {
      view: 'expenses',
      label: 'Expenses',
      icon: <Receipt size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
      badge: role !== 'SALESMAN' && pendingExpensesCount > 0 ? pendingExpensesCount : undefined,
      badgeColor: '#b45309',
    },
    {
      view: 'visits',
      label: 'Shop Visits',
      icon: <MapPin size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
    },
    {
      view: 'closing',
      label: 'Daily Closing',
      icon: <Lock size={18} />,
      roles: ['OWNER', 'PA', 'SALESMAN'],
    },
    {
      view: 'salary',
      label: 'Salary & Incentives',
      icon: <Coins size={18} />,
      roles: ['OWNER', 'PA'],
    },
    {
      view: 'reports',
      label: 'Reports & Exports',
      icon: <FileText size={18} />,
      roles: ['OWNER', 'PA'],
    },
    {
      view: 'users',
      label: 'Team & Security',
      icon: <Shield size={18} />,
      roles: ['OWNER', 'PA'],
    },
    {
      view: 'audit',
      label: 'Audit & Health',
      icon: <Activity size={18} />,
      roles: ['OWNER', 'PA'],
    },
  ];

  const visibleItems = navItems.filter((item) => role && item.roles.includes(role));

  const handleSelect = (v: ViewType) => {
    onSelectView(v);
    if (onCloseMobile) {
      onCloseMobile();
    }
  };

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpenMobile && (
        <div
          onClick={onCloseMobile}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.5)',
            zIndex: 40,
            backdropFilter: 'blur(2px)',
          }}
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`app-sidebar ${isOpenMobile ? 'mobile-open' : ''}`}
        style={{
          width: '240px',
          background: '#ffffff',
          borderRight: '1px solid #e2e8f0',
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          flexShrink: 0,
        }}
      >
        {/* Brand header on mobile sidebar */}
        <div
          style={{
            padding: '16px 18px',
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#14532d', letterSpacing: '-0.02em' }}>
              Kawad Swad
            </div>
            <div style={{ fontSize: '0.72rem', color: '#64748b', fontWeight: 500 }}>
              Sales & Factory ERP
            </div>
          </div>
          {onCloseMobile && (
            <button
              onClick={onCloseMobile}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#64748b',
                cursor: 'pointer',
                padding: '4px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              className="mobile-close-btn"
              title="Close Navigation"
            >
              <X size={20} />
            </button>
          )}
        </div>

        {/* Navigation items list */}
        <div
          style={{
            padding: '12px 10px',
            overflowY: 'auto',
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            gap: '3px',
          }}
        >
          {visibleItems.map((item) => {
            const isActive = currentView === item.view;
            return (
              <button
                key={item.view}
                onClick={() => handleSelect(item.view)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: 'none',
                  background: isActive ? '#ecfdf5' : 'transparent',
                  color: isActive ? '#14532d' : '#475569',
                  fontWeight: isActive ? 700 : 500,
                  fontSize: '0.86rem',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'background 0.15s ease, color 0.15s ease',
                  outline: 'none',
                }}
              >
                <span style={{ color: isActive ? '#166534' : '#64748b', display: 'flex', alignItems: 'center' }}>
                  {item.icon}
                </span>
                <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {item.label}
                </span>
                {item.badge !== undefined && item.badge > 0 && (
                  <span
                    style={{
                      background: item.badgeColor || '#ef4444',
                      color: '#ffffff',
                      fontSize: '0.70rem',
                      fontWeight: 700,
                      padding: '1px 6px',
                      borderRadius: '999px',
                      lineHeight: 1.3,
                    }}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Footer info in sidebar */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid #e2e8f0',
            fontSize: '0.75rem',
            color: '#94a3b8',
            background: '#f8fafc',
          }}
        >
          <div style={{ fontWeight: 600, color: '#475569' }}>Kawad Swad Udhyog</div>
          <div>Nimar, Madhya Pradesh</div>
        </div>
      </aside>
    </>
  );
};
