import React, { useState, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import {
  LayoutDashboard,
  Factory,
  UserCheck,
  Package,
  Boxes,
  ShoppingCart,
  CheckCircle2,
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
  Briefcase,
  Search,
} from 'lucide-react';
import {
  getWorkspaceForRole,
  getNavItemsForWorkspace,
  ALL_NAV_ITEMS,
  WorkspaceId,
  WORKSPACES,
} from '../utils/workspaces';

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
  | 'workforce'
  | 'reports'
  | 'accounting'
  | 'users'
  | 'audit';

interface NavigationProps {
  currentView: ViewType;
  onSelectView: (view: ViewType) => void;
  isOpenMobile?: boolean;
  onCloseMobile?: () => void;
  activeWorkspaceId?: WorkspaceId;
}

const VIEW_ICONS: Record<ViewType, React.ReactNode> = {
  dashboard: <LayoutDashboard size={18} />,
  workforce: <Briefcase size={18} />,
  sales: <ShoppingCart size={18} />,
  customers: <UsersIcon size={18} />,
  production: <Factory size={18} />,
  stock: <Boxes size={18} />,
  attendance: <UserCheck size={18} />,
  accounting: <Scale size={18} />,
  approvals: <CheckCircle2 size={18} />,
  reports: <FileText size={18} />,
  users: <Shield size={18} />,
  audit: <Activity size={18} />,
  purchasing: <Truck size={18} />,
  packaging: <Package size={18} />,
  quality: <ShieldCheck size={18} />,
  expenses: <Receipt size={18} />,
  visits: <MapPin size={18} />,
  closing: <Lock size={18} />,
  salary: <Coins size={18} />,
  products: <Tag size={18} />,
};

export const Navigation: React.FC<NavigationProps> = ({
  currentView,
  onSelectView,
  isOpenMobile = false,
  onCloseMobile,
  activeWorkspaceId,
}) => {
  const { currentUser, approvalRequests, expenses, dashboardMetrics } = useStore();
  const [navSearch, setNavSearch] = useState('');

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

  // Resolve current active workspace config
  const workspaceConfig = useMemo(() => {
    if (activeWorkspaceId && WORKSPACES[activeWorkspaceId]) {
      return WORKSPACES[activeWorkspaceId];
    }
    return getWorkspaceForRole(currentUser?.role);
  }, [currentUser?.role, activeWorkspaceId]);

  // Derive allowed navigation items for this workspace
  const navItems = useMemo(() => {
    const rawItems = getNavItemsForWorkspace(workspaceConfig);
    if (!navSearch.trim()) return rawItems;
    const q = navSearch.toLowerCase().trim();
    return rawItems.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q)
    );
  }, [workspaceConfig, navSearch]);

  // Badges calculation
  const pendingApprovalsCount =
    (approvalRequests?.filter((r) => r.status === 'PENDING').length || 0) +
    (dashboardMetrics?.pending_production_approvals || 0);

  const pendingExpensesCount =
    expenses?.filter((e) => String(e.approval_status || '').toUpperCase() === 'PENDING').length ||
    dashboardMetrics?.pending_expenses ||
    0;

  const handleSelect = (v: ViewType) => {
    onSelectView(v);
    if (onCloseMobile) {
      onCloseMobile();
    }
  };

  return (
    <>
      {/* Mobile Drawer Backdrop */}
      {isOpenMobile && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs z-40 lg:hidden transition-opacity"
          aria-hidden="true"
        />
      )}

      {/* Main Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 bg-white border-r border-slate-200 flex flex-col shrink-0 select-none transition-all duration-200 ease-in-out lg:static ${
          isOpenMobile ? 'translate-x-0 shadow-2xl' : '-translate-x-full lg:translate-x-0'
        } ${isCollapsed ? 'lg:w-18' : 'lg:w-64'}`}
      >
        {/* Brand & Workspace Header */}
        <div className="h-16 border-b border-slate-200 px-4 flex items-center justify-between shrink-0">
          <div className={`flex items-center gap-3 overflow-hidden ${isCollapsed ? 'lg:hidden' : ''}`}>
            <div className="w-8 h-8 rounded-lg bg-emerald-800 text-white flex items-center justify-center font-extrabold text-sm shadow-xs shrink-0">
              KS
            </div>
            <div className="truncate">
              <div className="font-bold text-slate-900 text-sm tracking-tight truncate leading-tight">
                Kawad Swad
              </div>
              <div className="text-[11px] text-emerald-700 font-semibold truncate">
                {workspaceConfig.title}
              </div>
            </div>
          </div>

          {/* When collapsed on desktop */}
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
              className="lg:hidden p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-md transition-colors cursor-pointer"
              aria-label="Close navigation"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* Quick Search inside Navigation (desktop expanded only) */}
        {!isCollapsed && navItems.length > 6 && (
          <div className="px-3 pt-3 pb-1">
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-2.5 flex items-center text-slate-400 pointer-events-none">
                <Search size={13} />
              </span>
              <input
                type="text"
                value={navSearch}
                onChange={(e) => setNavSearch(e.target.value)}
                placeholder="Find in menu…"
                className="w-full pl-7 pr-6 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700 font-medium placeholder:text-slate-400"
              />
              {navSearch && (
                <button
                  onClick={() => setNavSearch('')}
                  className="absolute inset-y-0 right-0 pr-2 flex items-center text-slate-400 hover:text-slate-600"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>
        )}

        {/* Navigation Links */}
        <nav
          className="flex-1 overflow-y-auto px-3 py-3 space-y-1"
          aria-label="Primary Navigation"
        >
          {navItems.map((item) => {
            const isActive = currentView === item.view;
            const icon = VIEW_ICONS[item.view] || <LayoutDashboard size={18} />;

            let badgeCount: number | undefined;
            let badgeColor = 'bg-amber-100 text-amber-900 border-amber-300';
            if (item.view === 'approvals' && pendingApprovalsCount > 0) {
              badgeCount = pendingApprovalsCount;
            } else if (item.view === 'expenses' && pendingExpensesCount > 0) {
              badgeCount = pendingExpensesCount;
            }

            return (
              <button
                key={item.view}
                type="button"
                onClick={() => handleSelect(item.view)}
                title={isCollapsed ? `${item.label} · ${item.description}` : undefined}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all duration-150 cursor-pointer ${
                  isActive
                    ? 'bg-emerald-800 text-white shadow-2xs'
                    : 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'
                } ${isCollapsed ? 'justify-center px-2' : ''}`}
              >
                <span
                  className={`shrink-0 ${
                    isActive ? 'text-white' : 'text-slate-500'
                  }`}
                >
                  {icon}
                </span>

                {!isCollapsed && (
                  <span className="truncate flex-1 text-left">
                    {item.label}
                  </span>
                )}

                {!isCollapsed && badgeCount !== undefined && badgeCount > 0 && (
                  <span
                    className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${badgeColor}`}
                  >
                    {badgeCount}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Desktop Collapse Toggle */}
        <div className="hidden lg:flex p-3 border-t border-slate-200 justify-end">
          <button
            type="button"
            onClick={toggleCollapse}
            className="w-full flex items-center justify-center gap-2 p-2 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 text-xs font-semibold transition-colors cursor-pointer"
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isCollapsed ? (
              <ChevronRight size={16} />
            ) : (
              <>
                <ChevronLeft size={16} />
                <span>Collapse</span>
              </>
            )}
          </button>
        </div>
      </aside>
    </>
  );
};
