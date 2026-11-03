import React from 'react';
import { useStore } from '../../context/StoreContext';
import { Menu, LogOut, ArrowLeft, Shield } from 'lucide-react';

interface EmployeeHeaderProps {
  onToggleMobileNav: () => void;
  onExitPreview?: () => void;
  isOwnerPreviewing?: boolean;
}

export const EmployeeHeader: React.FC<EmployeeHeaderProps> = ({
  onToggleMobileNav,
  onExitPreview,
  isOwnerPreviewing = false,
}) => {
  const { currentUser, logout } = useStore();

  const roleLabel = (role: string = '') => {
    switch (role.toUpperCase()) {
      case 'SALESMAN':
      case 'FIELD_SALESMAN':
        return 'Field Sales Officer';
      case 'FREELANCER':
        return 'Freelancer / Specialist';
      case 'PA':
      case 'PERSONAL_ASSISTANT':
        return 'Personal Assistant';
      case 'ACCOUNTANT':
        return 'Senior Accountant';
      case 'SOCIAL_MEDIA_ECOMMERCE_MANAGER':
      case 'SOCIAL_MEDIA_MANAGER':
      case 'ECOMMERCE_MANAGER':
        return 'Social Media & E-Commerce';
      default:
        return role;
    }
  };

  const todayStr = new Date().toLocaleDateString('en-IN', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });

  return (
    <header className="bg-slate-900 border-b border-slate-800 text-white sticky top-0 z-40 select-none shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-15 flex items-center justify-between gap-3">
        {/* Left: Branding & Mobile Menu */}
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleMobileNav}
            className="md:hidden p-1.5 -ml-1 text-slate-300 hover:text-white hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
            aria-label="Toggle navigation"
          >
            <Menu size={20} />
          </button>

          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-emerald-600 flex items-center justify-center font-black text-white text-sm shadow-sm ring-2 ring-emerald-500/20">
              KS
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-sm sm:text-base tracking-tight text-white">
                  Kawad Swad
                </span>
                <span className="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[10px] font-semibold px-2 py-0.5 rounded-full">
                  Staff Workspace
                </span>
              </div>
              <p className="text-[11px] text-slate-400 hidden sm:block">
                Employee Self-Service & Activity Portal
              </p>
            </div>
          </div>
        </div>

        {/* Right: Date, Profile Badge, Actions */}
        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block">
            <div className="text-xs font-semibold text-slate-200">
              {currentUser?.full_name || 'Team Member'}
            </div>
            <div className="text-[10px] font-medium text-emerald-400">
              {roleLabel(currentUser?.role)}
            </div>
          </div>

          <span className="hidden lg:inline-block text-xs text-slate-400 border-l border-slate-700 pl-3">
            {todayStr}
          </span>

          {isOwnerPreviewing && onExitPreview && (
            <button
              onClick={onExitPreview}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/30 text-xs font-semibold transition-all cursor-pointer"
              title="Return to Owner ERP"
            >
              <ArrowLeft size={14} />
              <span className="hidden sm:inline">Back to ERP</span>
            </button>
          )}

          <button
            onClick={() => logout()}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 text-xs font-medium transition-colors cursor-pointer"
            title="Log out of employee portal"
          >
            <LogOut size={16} />
            <span className="hidden md:inline">Sign Out</span>
          </button>
        </div>
      </div>
    </header>
  );
};
