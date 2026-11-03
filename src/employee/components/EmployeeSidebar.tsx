import React from 'react';
import { useStore } from '../../context/StoreContext';
import { EmployeeViewType } from '../types';
import {
  LayoutDashboard,
  CheckSquare,
  Clock,
  Receipt,
  Briefcase,
  User,
  X,
  Sparkles,
} from 'lucide-react';

interface EmployeeSidebarProps {
  currentView: EmployeeViewType;
  onSelectView: (view: EmployeeViewType) => void;
  isOpenMobile: boolean;
  onCloseMobile: () => void;
  pendingTasksCount?: number;
}

export const EmployeeSidebar: React.FC<EmployeeSidebarProps> = ({
  currentView,
  onSelectView,
  isOpenMobile,
  onCloseMobile,
  pendingTasksCount = 0,
}) => {
  const { currentUser } = useStore();
  const role = (currentUser?.role || '').toUpperCase();
  const isFreelancer = role === 'FREELANCER';

  const navItems = [
    {
      view: 'overview' as EmployeeViewType,
      label: 'My Workspace',
      icon: <LayoutDashboard size={18} />,
    },
    {
      view: 'tasks' as EmployeeViewType,
      label: 'Assigned Tasks',
      icon: <CheckSquare size={18} />,
      badge: pendingTasksCount > 0 ? pendingTasksCount : undefined,
    },
    {
      view: 'attendance' as EmployeeViewType,
      label: 'Attendance & Clock-In',
      icon: <Clock size={18} />,
    },
    ...(isFreelancer
      ? [
          {
            view: 'projects' as EmployeeViewType,
            label: 'Projects & Milestones',
            icon: <Briefcase size={18} />,
          },
        ]
      : []),
    {
      view: 'salary' as EmployeeViewType,
      label: 'My Salary & Receipts',
      icon: <Receipt size={18} />,
    },
    {
      view: 'profile' as EmployeeViewType,
      label: 'Profile & Bank Details',
      icon: <User size={18} />,
    },
  ];

  const handleSelect = (v: EmployeeViewType) => {
    onSelectView(v);
    onCloseMobile();
  };

  const navContent = (
    <div className="flex flex-col h-full bg-slate-900 border-r border-slate-800 text-slate-300">
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-emerald-400" />
          <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
            Navigation
          </span>
        </div>
        <button
          onClick={onCloseMobile}
          className="md:hidden text-slate-400 hover:text-white p-1 rounded-md"
        >
          <X size={18} />
        </button>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1.5 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = currentView === item.view;
          return (
            <button
              key={item.view}
              onClick={() => handleSelect(item.view)}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-medium transition-all cursor-pointer ${
                isActive
                  ? 'bg-emerald-600 text-white font-semibold shadow-sm shadow-emerald-900/40'
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/80'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={isActive ? 'text-white' : 'text-slate-400'}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                    isActive
                      ? 'bg-emerald-800 text-emerald-100'
                      : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Role Tip */}
      <div className="p-3.5 m-3 rounded-xl bg-slate-800/60 border border-slate-700/60 text-[11px] text-slate-400">
        <div className="font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          Privacy Protection
        </div>
        Your account is strictly isolated. You only see your own tasks, attendance, and approved receipts.
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <aside className="hidden md:block w-64 shrink-0 h-[calc(100vh-3.75rem)] sticky top-15">
        {navContent}
      </aside>

      {/* Mobile Drawer */}
      {isOpenMobile && (
        <div className="fixed inset-0 z-50 md:hidden flex">
          <div
            className="fixed inset-0 bg-slate-950/70 backdrop-blur-xs transition-opacity"
            onClick={onCloseMobile}
          />
          <div className="relative w-64 max-w-[80vw] h-full z-10">
            {navContent}
          </div>
        </div>
      )}
    </>
  );
};
