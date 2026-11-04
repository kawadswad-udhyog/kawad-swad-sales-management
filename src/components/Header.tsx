import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { ViewType } from './Navigation';
import { WorkspaceId, WORKSPACES, getWorkspaceForRole } from '../utils/workspaces';
import {
  Menu,
  RefreshCw,
  LogOut,
  CheckCircle2,
  AlertTriangle,
  X,
  Server,
  Database,
  Eye,
  ChevronDown,
} from 'lucide-react';

interface HeaderProps {
  currentView?: ViewType;
  onToggleMobileNav?: () => void;
  onNavigate?: (v: ViewType) => void;
  activeWorkspaceId?: WorkspaceId;
  onChangeWorkspace?: (id: WorkspaceId) => void;
  isOwnerPreviewing?: boolean;
  onExitWorkspacePreview?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentView = 'dashboard',
  onToggleMobileNav,
  onNavigate,
  activeWorkspaceId,
  onChangeWorkspace,
  isOwnerPreviewing = false,
  onExitWorkspacePreview,
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
    refreshData,
    isRefreshing,
  } = useStore();

  const [showStatusModal, setShowStatusModal] = useState(false);
  const [showWorkspaceMenu, setShowWorkspaceMenu] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);

  const role = String(currentUser?.role || '').toUpperCase();
  const isOwner = ['OWNER', 'OWNER_ADMIN', 'ADMIN'].includes(role);

  const currentWorkspace = activeWorkspaceId && WORKSPACES[activeWorkspaceId]
    ? WORKSPACES[activeWorkspaceId]
    : getWorkspaceForRole(currentUser?.role);

  // Status configuration conforming to truthfulness rules
  let statusBadge = {
    label: 'Online',
    dot: 'bg-emerald-500',
    text: 'text-emerald-800',
    bg: 'bg-emerald-50 border-emerald-200',
    icon: <CheckCircle2 size={13} className="text-emerald-600" />,
  };

  if (!isBackendConnected) {
    statusBadge = {
      label: 'API Standby',
      dot: 'bg-amber-500',
      text: 'text-amber-800',
      bg: 'bg-amber-50 border-amber-200',
      icon: <Server size={13} className="text-amber-600" />,
    };
  } else if (!isGoogleSheetsConnected || !persistentWritesEnabled) {
    statusBadge = {
      label: 'Sheets Standby',
      dot: 'bg-amber-500 animate-pulse',
      text: 'text-amber-900',
      bg: 'bg-amber-50 border-amber-300',
      icon: <Database size={13} className="text-amber-600" />,
    };
  }

  const handleManualReconnect = async () => {
    setIsReconnecting(true);
    try {
      await reconnectGoogleSheets();
      await refreshData();
    } finally {
      setIsReconnecting(false);
    }
  };

  return (
    <header className="h-16 bg-white border-b border-slate-200 px-4 sm:px-6 flex items-center justify-between shrink-0 z-30 select-none">
      {/* Left Area: Mobile Menu Trigger + Workspace Title */}
      <div className="flex items-center gap-3">
        {onToggleMobileNav && (
          <button
            type="button"
            onClick={onToggleMobileNav}
            className="lg:hidden p-2 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
            aria-label="Toggle navigation menu"
          >
            <Menu size={20} />
          </button>
        )}

        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-900 text-sm sm:text-base tracking-tight leading-none">
              {currentWorkspace.title}
            </span>

            {/* Owner Workspace Preview Switcher */}
            {isOwner && onChangeWorkspace && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowWorkspaceMenu((prev) => !prev)}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors cursor-pointer"
                  title="Switch workspace view"
                >
                  <Eye size={12} className="text-slate-500" />
                  <span>Switch</span>
                  <ChevronDown size={11} className="text-slate-400" />
                </button>

                {showWorkspaceMenu && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setShowWorkspaceMenu(false)}
                    />
                    <div className="absolute left-0 mt-1 w-56 bg-white rounded-xl shadow-lg border border-slate-200 py-1.5 z-50 text-xs">
                      <div className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-slate-100 mb-1">
                        Preview Workspace As
                      </div>
                      {(Object.keys(WORKSPACES) as WorkspaceId[]).map((wId) => {
                        const ws = WORKSPACES[wId];
                        const isCurrent = (activeWorkspaceId || 'owner') === wId;
                        return (
                          <button
                            key={wId}
                            type="button"
                            onClick={() => {
                              onChangeWorkspace(wId);
                              setShowWorkspaceMenu(false);
                            }}
                            className={`w-full text-left px-3 py-2 flex flex-col transition-colors cursor-pointer ${
                              isCurrent
                                ? 'bg-emerald-50 text-emerald-950 font-bold'
                                : 'text-slate-700 hover:bg-slate-50'
                            }`}
                          >
                            <span>{ws.title}</span>
                            <span className="text-[10px] text-slate-400 font-normal">
                              {ws.roleBadge}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="text-[11px] text-slate-500 hidden sm:block mt-0.5 truncate max-w-md">
            {currentWorkspace.subtitle}
          </div>
        </div>
      </div>

      {/* Right Area: Status, User Identity, Sync, Logout */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* Owner previewing banner */}
        {isOwnerPreviewing && onExitWorkspacePreview && (
          <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-50 border border-amber-200 text-amber-900 text-xs font-semibold">
            <span>Preview Mode</span>
            <button
              onClick={onExitWorkspacePreview}
              className="text-amber-800 hover:underline font-bold ml-1 cursor-pointer"
            >
              Exit
            </button>
          </div>
        )}

        {/* Sync / Refresh Button */}
        <button
          type="button"
          disabled={isRefreshing}
          onClick={() => refreshData()}
          className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
          title="Refresh ERP data"
          aria-label="Refresh ERP data"
        >
          <RefreshCw size={16} className={isRefreshing ? 'animate-spin text-emerald-700' : ''} />
        </button>

        {/* Connection Status Indicator */}
        <button
          type="button"
          onClick={() => isOwner && setShowStatusModal(true)}
          className={`hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold border transition-colors ${
            statusBadge.bg
          } ${statusBadge.text} ${isOwner ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
          title={isOwner ? 'Click to inspect server connection diagnostics' : undefined}
        >
          <span className={`w-2 h-2 rounded-full shrink-0 ${statusBadge.dot}`} />
          <span>{statusBadge.label}</span>
        </button>

        {/* User Profile Pill */}
        {currentUser && (
          <div className="flex items-center gap-2.5 pl-2 sm:pl-3 border-l border-slate-200">
            <div className="w-8 h-8 rounded-lg bg-emerald-800 text-white font-bold text-xs flex items-center justify-center shadow-2xs">
              {(currentUser.full_name || currentUser.username || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="hidden md:block text-left">
              <div className="text-xs font-bold text-slate-900 leading-tight truncate max-w-[120px]">
                {currentUser.full_name || currentUser.username}
              </div>
              <div className="text-[10px] text-slate-500 font-medium truncate max-w-[120px]">
                {currentWorkspace.roleBadge}
              </div>
            </div>
          </div>
        )}

        {/* Logout Button */}
        <button
          type="button"
          onClick={() => logout()}
          className="p-2 text-slate-500 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors cursor-pointer"
          title="Sign out"
          aria-label="Sign out"
        >
          <LogOut size={16} />
        </button>
      </div>

      {/* Owner-Only Connection & Diagnostics Modal */}
      {showStatusModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-xs">
          <div className="w-full max-w-lg bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server size={18} className="text-emerald-800" />
                <h3 className="text-base font-bold text-slate-900 m-0">
                  Backend & Sheets Diagnostics
                </h3>
              </div>
              <button
                onClick={() => setShowStatusModal(false)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-md"
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-5 space-y-4 text-xs">
              <div className="p-3 bg-slate-50 rounded-xl space-y-2 border border-slate-200/60">
                <div className="flex justify-between items-center">
                  <span className="text-slate-600 font-medium">Backend API:</span>
                  <span className="font-bold text-slate-900">
                    {isBackendConnected ? 'Connected (200 OK)' : 'Standby / Unreachable'}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-600 font-medium">Google Sheets:</span>
                  <span className="font-bold text-slate-900">
                    {isGoogleSheetsConnected ? 'Connected (66 Tabs)' : 'Standby Mode'}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-600 font-medium">Persistent Writes:</span>
                  <span className="font-bold text-slate-900">
                    {persistentWritesEnabled ? 'Enabled' : 'Locked / Inactive'}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-600 font-medium">Server Endpoint:</span>
                  <span className="font-mono text-[11px] text-slate-700 truncate max-w-[220px]">
                    {backendUrl}
                  </span>
                </div>
              </div>

              {connectionError && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-red-900">
                  <strong>Notice:</strong> {connectionError}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={isReconnecting}
                  onClick={handleManualReconnect}
                  className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 text-white font-semibold rounded-lg transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
                >
                  <RefreshCw size={14} className={isReconnecting ? 'animate-spin' : ''} />
                  <span>{isReconnecting ? 'Reconnecting…' : 'Reconnect Storage'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
};
