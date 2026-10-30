import React, { useState } from 'react';
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
  Activity,
  Shield,
  Scale,
  X,
  ChevronLeft,
  ChevronRight,
  Truck,
  ShieldCheck,
} from 'lucide-react';


export type ViewType =
  | 'dashboard'
  | 'purchasing'
  | 'production'
  | 'attendance'
  | 'packaging'
  | 'quality'
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
  | 'accounting'
  | 'users'
  | 'audit';


interface NavigationProps {
  currentView: ViewType;
  onSelectView: (view: ViewType) => void;
  isOpenMobile?: boolean;
  onCloseMobile?: () => void;
}

interface NavItem {
  view: ViewType;
  label: string;
  icon: React.ReactNode;
  roles: string[];
  badge?: number;
  badgeColor?: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

export const Navigation: React.FC<NavigationProps> = ({
  currentView,
  onSelectView,
  isOpenMobile = false,
  onCloseMobile,
}) => {
  const { currentUser, approvalRequests, expenses, dashboardMetrics } = useStore();
  const role = currentUser?.role;

  const [isCollapsed, setIsCollapsed] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('ks_nav_collapsed') === 'true';
    }
    return false;
  });

  const toggleCollapse = () => {
    setIsCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== 'undefined') {
        localStorage.setItem('ks_nav_collapsed', String(next));
      }
      return next;
    });
  };

  const pendingApprovalsCount =
    (approvalRequests?.filter((r) => r.status === 'PENDING').length || 0) +
    (dashboardMetrics?.pending_production_approvals || 0);

  const pendingExpensesCount =
    expenses?.filter((e) => e.approval_status === 'PENDING').length ||
    dashboardMetrics?.pending_expenses ||
    0;

  const sections: NavSection[] = [
    {
      title: 'Operations',
      items: [
        {
          view: 'dashboard',
          label: role === 'SALESMAN' ? 'Field Workspace' : 'Dashboard',
          icon: <LayoutDashboard size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
        },
        {
          view: 'purchasing',
          label: 'Purchasing & Vendors',
          icon: <Truck size={18} />,
          roles: ['OWNER', 'PA'],
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
      ],
    },
    {
      title: 'Inventory & Approvals',
      items: [
        {
          view: 'stock',
          label: 'Inventory Ledgers',
          icon: <Boxes size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
        },
        {
          view: 'quality',
          label: 'Quality & Traceability',
          icon: <ShieldCheck size={18} />,
          roles: ['OWNER', 'PA'],
        },
        {
          view: 'approvals',
          label: 'Approvals',
          icon: <CheckSquare size={18} />,
          roles: ['OWNER', 'PA'],
          badge: pendingApprovalsCount,
          badgeColor: 'bg-amber-600 text-white',
        },
      ],
    },
    {
      title: 'Commercial & Sales',
      items: [
        {
          view: 'sales',
          label: 'Sales & Bills',
          icon: <ShoppingCart size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
        },
        {
          view: 'customers',
          label: 'Customers',
          icon: <UsersIcon size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
        },
        {
          view: 'products',
          label: 'Product Catalogue',
          icon: <Tag size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
        },
        {
          view: 'expenses',
          label: 'Expenses & Claims',
          icon: <Receipt size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
          badge: role !== 'SALESMAN' && pendingExpensesCount > 0 ? pendingExpensesCount : undefined,
          badgeColor: 'bg-amber-600 text-white',
        },
        {
          view: 'visits',
          label: 'Shop Visits',
          icon: <MapPin size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
        },
        {
          view: 'closing',
          label: 'Daily Cash Closing',
          icon: <Lock size={18} />,
          roles: ['OWNER', 'PA', 'SALESMAN'],
        },
      ],
    },
    {
      title: 'Management & Admin',
      items: [
        {
          view: 'salary',
          label: 'Salary & Payroll',
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
          view: 'accounting',
          label: 'General Ledger & Accounts',
          icon: <Scale size={18} />,
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
      ],
    },
  ];

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
          className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs z-40 lg:hidden"
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`app-sidebar ${isOpenMobile ? 'mobile-open' : ''} ${
          isCollapsed ? 'lg:w-18' : 'lg:w-64'
        } bg-white border-r border-slate-200 flex flex-col shrink-0 select-none transition-all duration-200 ease-in-out z-30`}
      >
        {/* Brand header */}
        <div className="h-16 border-b border-slate-200 px-4 flex items-center justify-between shrink-0">
          <div className={`flex items-center gap-3 overflow-hidden ${isCollapsed ? 'lg:hidden' : ''}`}>
            <div className="w-8 h-8 rounded-lg bg-emerald-800 text-white flex items-center justify-center font-extrabold text-sm shadow-xs shrink-0">
              KS
            </div>
            <div className="truncate">
              <div className="font-bold text-slate-900 text-sm tracking-tight truncate leading-tight">
                Kawad Swad
              </div>
              <div className="text-[11px] text-slate-500 font-medium truncate">
                Enterprise ERP
              </div>
            </div>
          </div>

          {/* When collapsed on desktop, show only logo */}
          {isCollapsed && (
            <div className="hidden lg:flex w-full items-center justify-center">
              <div className="w-8 h-8 rounded-lg bg-emerald-800 text-white flex items-center justify-center font-extrabold text-sm shadow-xs">
                KS
              </div>
            </div>
          )}

          {/* Mobile close button */}
          {onCloseMobile && (
            <button
              onClick={onCloseMobile}
              className="lg:hidden p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-md transition-colors"
              title="Close navigation"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* Navigation items list */}
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
          {sections.map((section, idx) => {
            const visibleItems = section.items.filter((item) => role && item.roles.includes(role));
            if (visibleItems.length === 0) return null;

            return (
              <div key={idx} className="space-y-1">
                {/* Section header */}
                <div
                  className={`text-[11px] font-semibold tracking-wider text-slate-400 uppercase px-3 py-1 ${
                    isCollapsed ? 'lg:hidden' : ''
                  }`}
                >
                  {section.title}
                </div>

                {visibleItems.map((item) => {
                  const isActive = currentView === item.view;
                  return (
                    <button
                      key={item.view}
                      onClick={() => handleSelect(item.view)}
                      title={isCollapsed ? item.label : undefined}
                      className={`group relative flex items-center w-full px-3 py-2 rounded-lg text-xs font-semibold transition-colors duration-150 text-left outline-none ${
                        isActive
                          ? 'bg-emerald-50 text-emerald-900 font-bold'
                          : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/70'
                      } ${isCollapsed ? 'lg:justify-center lg:px-2' : 'gap-3'}`}
                    >
                      {/* Active indicator bar */}
                      {isActive && (
                        <span className="absolute left-0 top-1.5 bottom-1.5 w-1 bg-emerald-700 rounded-r-md" />
                      )}

                      <span
                        className={`shrink-0 transition-colors ${
                          isActive
                            ? 'text-emerald-700'
                            : 'text-slate-400 group-hover:text-slate-600'
                        }`}
                      >
                        {item.icon}
                      </span>

                      <span
                        className={`truncate flex-1 ${
                          isCollapsed ? 'lg:hidden' : 'block'
                        }`}
                      >
                        {item.label}
                      </span>

                      {item.badge !== undefined && item.badge > 0 && (
                        <span
                          className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full shrink-0 ${
                            item.badgeColor || 'bg-slate-200 text-slate-700'
                          } ${isCollapsed ? 'lg:hidden' : 'inline-block'}`}
                        >
                          {item.badge}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* Footer Collapse Toggle (Desktop) */}
        <div className="border-t border-slate-200 p-2.5 bg-slate-50/60 hidden lg:flex items-center justify-between">
          {!isCollapsed && (
            <div className="px-2 text-[11px] text-slate-400 truncate">
              v1.0 · Nimar, MP
            </div>
          )}
          <button
            onClick={toggleCollapse}
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 rounded-md transition-colors mx-auto"
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>
      </aside>
    </>
  );
};
