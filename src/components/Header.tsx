import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { UserRole } from '../types';
import { ViewType } from './Navigation';
import {
  Menu,
  RefreshCw,
  LogOut,
  Shield,
  Wifi,
  WifiOff,
  Database,
  CheckCircle2,
  AlertTriangle,
  X,
} from 'lucide-react';

interface HeaderProps {
  currentView?: ViewType;
  onToggleMobileNav?: () => void;
  onNavigate?: (v: ViewType) => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentView = 'dashboard',
  onToggleMobileNav,
  onNavigate,
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
  const [tempUrl, setTempUrl] = useState(backendUrl);
  const [isReconnecting, setIsReconnecting] = useState(false);

  const getRoleBadge = (role?: UserRole) => {
    switch (role) {
      case 'OWNER':
        return { label: 'Owner / Admin', bg: '#fef08a', text: '#854d0e' };
      case 'PA':
        return { label: 'Personal Assistant', bg: '#dbeafe', text: '#1e40af' };
      case 'SALESMAN':
        return { label: 'Field Sales', bg: '#dcfce7', text: '#15803d' };
      default:
        return { label: role || 'Staff', bg: '#f1f5f9', text: '#475569' };
    }
  };

  const getViewTitle = (v: ViewType) => {
    switch (v) {
      case 'dashboard':
        return currentUser?.role === 'SALESMAN' ? 'Field Workspace' : 'Overview Dashboard';
      case 'production':
        return 'Daily Production & Batches';
      case 'attendance':
        return 'Worker Attendance & Wages';
      case 'packaging':
        return 'Packaging & Packet Reconciliation';
      case 'stock':
        return 'Inventory & Stock Ledgers';
      case 'sales':
        return 'Sales Billing & Invoicing';
      case 'approvals':
        return 'Approvals Management';
      case 'customers':
        return 'Customer Directory';
      case 'products':
        return 'Product Catalogue';
      case 'expenses':
        return 'Expenses & Claims';
      case 'visits':
        return 'Shop Visits & Field Activity';
      case 'closing':
        return 'Daily Cash Closing';
      case 'salary':
        return 'Salary & Incentives';
      case 'reports':
        return 'Reports & Data Exports';
      case 'users':
        return 'User Management & Security';
      case 'audit':
        return 'Audit Logs & Sheet Integrity';
      default:
        return 'Management System';
    }
  };

  const roleBadge = getRoleBadge(currentUser?.role);

  // Status configuration
  let statusBadge = {
    label: 'Connected',
    color: '#15803d',
    bg: '#ecfdf5',
    border: '#bbf7d0',
    icon: <CheckCircle2 size={13} />,
  };

  if (!isBackendConnected) {
    statusBadge = {
      label: 'Connecting API…',
      color: '#b45309',
      bg: '#fffbeb',
      border: '#fde68a',
      icon: <AlertTriangle size={13} />,
    };
  } else if (!isGoogleSheetsConnected || !persistentWritesEnabled) {
    statusBadge = {
      label: 'Sheets Offline',
      color: '#b91c1c',
      bg: '#fef2f2',
      border: '#fecaca',
      icon: <WifiOff size={13} />,
    };
  }

  const handleManualReconnect = async () => {
    setIsReconnecting(true);
    try {
      const res = await reconnectGoogleSheets();
      if (res.success) {
        await refreshData();
      }
    } finally {
      setIsReconnecting(false);
    }
  };

  const handleSaveUrl = (e: React.FormEvent) => {
    e.preventDefault();
    if (tempUrl.trim()) {
      updateBackendUrl(tempUrl.trim());
      setShowStatusModal(false);
    }
  };

  return (
    <>
      <header
        style={{
          background: '#ffffff',
          borderBottom: '1px solid #e2e8f0',
          padding: '10px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          height: '62px',
          boxSizing: 'border-box',
          position: 'sticky',
          top: 0,
          zIndex: 30,
        }}
      >
        {/* Left Side: Mobile Menu Button & Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {onToggleMobileNav && (
            <button
              onClick={onToggleMobileNav}
              style={{
                background: 'transparent',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                padding: '7px',
                color: '#475569',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              className="mobile-nav-toggle"
              title="Open Navigation"
            >
              <Menu size={18} />
            </button>
          )}

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.74rem', color: '#64748b' }}>
              <span>Kawad Swad</span>
              <span>/</span>
              <span style={{ fontWeight: 600, color: '#0f172a' }}>{getViewTitle(currentView)}</span>
            </div>
            <div style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
              {new Date().toLocaleDateString('en-IN', {
                weekday: 'short',
                day: 'numeric',
                month: 'short',
                year: 'numeric',
              })}
            </div>
          </div>
        </div>

        {/* Right Side: Quick Actions, Connection Pill & User Info */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* Refresh Button */}
          <button
            onClick={() => refreshData()}
            disabled={isRefreshing}
            style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              padding: '6px 10px',
              color: '#475569',
              fontSize: '0.80rem',
              fontWeight: 500,
              cursor: isRefreshing ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
            title="Refresh active workspace data"
          >
            <RefreshCw size={13} className={isRefreshing ? 'spin-icon' : ''} />
            <span className="hide-on-mobile">{isRefreshing ? 'Syncing…' : 'Sync'}</span>
          </button>

          {/* Connection Status Pill */}
          <div
            onClick={() => setShowStatusModal(true)}
            role="button"
            tabIndex={0}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              fontSize: '0.76rem',
              fontWeight: 600,
              background: statusBadge.bg,
              color: statusBadge.color,
              border: `1px solid ${statusBadge.border}`,
              padding: '5px 10px',
              borderRadius: '999px',
            }}
            title="Click to check connection status"
          >
            {statusBadge.icon}
            <span>{statusBadge.label}</span>
          </div>

          {/* Logged in User Badge */}
          {currentUser && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '4px 8px',
                  borderRadius: '8px',
                  background: '#f8fafc',
                  border: '1px solid #e2e8f0',
                }}
              >
                <div
                  style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '50%',
                    background: '#166534',
                    color: '#ffffff',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.78rem',
                    fontWeight: 700,
                  }}
                >
                  {currentUser.full_name ? currentUser.full_name.slice(0, 1).toUpperCase() : 'U'}
                </div>
                <div className="hide-on-mobile" style={{ textAlign: 'left', lineHeight: 1.15 }}>
                  <div style={{ fontSize: '0.80rem', fontWeight: 600, color: '#0f172a' }}>
                    {currentUser.full_name}
                  </div>
                  <div style={{ fontSize: '0.70rem', color: roleBadge.text, fontWeight: 700 }}>
                    {roleBadge.label}
                  </div>
                </div>
              </div>

              {/* Logout Button */}
              <button
                onClick={logout}
                style={{
                  background: 'transparent',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  padding: '7px 10px',
                  color: '#64748b',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                }}
                title="Sign out of ERP"
              >
                <LogOut size={14} />
                <span className="hide-on-mobile">Logout</span>
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Connection Details Modal */}
      {showStatusModal && (
        <div
          onClick={() => setShowStatusModal(false)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.45)',
            zIndex: 50,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '16px',
            backdropFilter: 'blur(2px)',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#ffffff',
              borderRadius: '14px',
              maxWidth: '520px',
              width: '100%',
              padding: '24px',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)',
              border: '1px solid #e2e8f0',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Wifi size={20} color="#166534" />
                <h3 style={{ margin: 0, fontSize: '1.15rem', color: '#0f172a' }}>System Connection Health</h3>
              </div>
              <button
                onClick={() => setShowStatusModal(false)}
                style={{ background: 'transparent', border: 'none', color: '#64748b', cursor: 'pointer', padding: '4px' }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Status Checklist */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '20px' }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: isBackendConnected ? '#ecfdf5' : '#fffbeb',
                  border: isBackendConnected ? '1px solid #bbf7d0' : '1px solid #fde68a',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem', color: '#0f172a' }}>Backend API Service</div>
                  <div style={{ fontSize: '0.78rem', color: '#64748b' }}>FastAPI on Render ({backendUrl || 'Proxy / direct'})</div>
                </div>
                <span style={{ fontSize: '0.80rem', fontWeight: 700, color: isBackendConnected ? '#15803d' : '#b45309' }}>
                  {isBackendConnected ? 'Online ✓' : 'Connecting / Waking…'}
                </span>
              </div>

              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: isGoogleSheetsConnected ? '#ecfdf5' : '#fef2f2',
                  border: isGoogleSheetsConnected ? '1px solid #bbf7d0' : '1px solid #fecaca',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem', color: '#0f172a' }}>Google Sheets Persistent Storage</div>
                  <div style={{ fontSize: '0.78rem', color: '#64748b' }}>Master 28-tab Google Sheets Database</div>
                </div>
                <span style={{ fontSize: '0.80rem', fontWeight: 700, color: isGoogleSheetsConnected ? '#15803d' : '#b91c1c' }}>
                  {isGoogleSheetsConnected ? 'Connected ✓' : 'Disconnected ✗'}
                </span>
              </div>

              {connectionError && (
                <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '10px 12px', fontSize: '0.78rem', color: '#64748b' }}>
                  <strong>Diagnostic note:</strong> {connectionError}
                </div>
              )}
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button
                disabled={isReconnecting}
                onClick={handleManualReconnect}
                style={{
                  padding: '8px 14px',
                  fontSize: '0.84rem',
                  fontWeight: 600,
                  background: '#166534',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: isReconnecting ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <RefreshCw size={14} className={isReconnecting ? 'spin-icon' : ''} />
                {isReconnecting ? 'Reconnecting Sheets…' : 'Test & Reconnect Sheets'}
              </button>
              <button
                onClick={() => setShowStatusModal(false)}
                style={{
                  padding: '8px 14px',
                  fontSize: '0.84rem',
                  fontWeight: 600,
                  background: '#f1f5f9',
                  color: '#475569',
                  border: '1px solid #cbd5e1',
                  borderRadius: '8px',
                  cursor: 'pointer',
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
