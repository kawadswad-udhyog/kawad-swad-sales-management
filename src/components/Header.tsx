import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { UserRole } from '../types';

export const Header: React.FC = () => {
  const {
    currentUser,
    logout,
    backendUrl,
    updateBackendUrl,
    isBackendConnected,
    isGoogleSheetsConnected,
    refreshData,
    isRefreshing,
  } = useStore();
  const [showConfig, setShowConfig] = useState(false);
  const [tempUrl, setTempUrl] = useState(backendUrl);

  const getRoleBadgeStyle = (role?: UserRole) => {
    switch (role) {
      case 'OWNER':
        return { background: '#fef08a', color: '#854d0e' };
      case 'PA':
        return { background: '#bfdbfe', color: '#1e40af' };
      case 'SALESMAN':
        return { background: '#bbf7d0', color: '#166534' };
      default:
        return {};
    }
  };

  const handleSaveUrl = (e: React.FormEvent) => {
    e.preventDefault();
    if (tempUrl.trim()) {
      updateBackendUrl(tempUrl.trim());
      setShowConfig(false);
    }
  };

  const statusColor = !isBackendConnected ? '#fbbf24' : isGoogleSheetsConnected ? '#4ade80' : '#ef4444';
  const statusText = !isBackendConnected
    ? 'Connecting…'
    : isGoogleSheetsConnected
    ? 'Sheets Connected'
    : 'Sheets Disconnected';

  return (
    <>
      <header>
        <div className="brand">
          Kawad Swad
          <small>Sales Management</small>
        </div>

        <div className="header-right">
          {/* Connection status indicator */}
          <div
            onClick={() => setShowConfig(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              fontSize: '0.78rem',
              background: 'rgba(255, 255, 255, 0.1)',
              padding: '5px 10px',
              borderRadius: '999px',
              border: '1px solid rgba(255, 255, 255, 0.2)',
            }}
            title={`Backend: ${backendUrl} (Click to change)`}
          >
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: statusColor,
                display: 'inline-block',
              }}
            />
            <span style={{ color: '#fff', opacity: 0.9 }}>
              {statusText}
            </span>
          </div>

          {currentUser ? (
            <>
              <div className="user-badge" title="Authenticated session">
                <span>{currentUser.full_name}</span>
                <span
                  style={{
                    ...getRoleBadgeStyle(currentUser.role),
                    fontSize: '0.72rem',
                    padding: '2px 7px',
                    borderRadius: '999px',
                    fontWeight: 800,
                    textTransform: 'uppercase',
                  }}
                >
                  {currentUser.role}
                </span>
              </div>

              <button
                onClick={refreshData}
                disabled={isRefreshing}
                className="secondary"
                title="Sync records from Google Sheets / FastAPI backend"
                style={{
                  fontSize: '0.8rem',
                  padding: '6px 12px',
                  background: isRefreshing ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.15)',
                  color: '#fff',
                  cursor: isRefreshing ? 'not-allowed' : 'pointer',
                }}
              >
                {isRefreshing ? '⏳ Syncing…' : '↻ Refresh'}
              </button>

              <button
                onClick={logout}
                className="secondary"
                style={{
                  padding: '6px 14px',
                  background: 'rgba(239, 68, 68, 0.25)',
                  border: '1px solid rgba(239, 68, 68, 0.5)',
                  color: '#fff',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
                title="Sign out of current account"
              >
                Sign out
              </button>
            </>
          ) : null}
        </div>
      </header>

      {showConfig && (
        <div className="modal-overlay" onClick={() => setShowConfig(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '480px' }}>
            <h2 style={{ marginTop: 0 }}>Backend Service Settings</h2>
            <p className="muted">
              Configure the remote FastAPI backend URL hosted on Render or local proxy:
            </p>

            <form onSubmit={handleSaveUrl}>
              <label>
                API Base URL
                <input
                  type="url"
                  value={tempUrl}
                  onChange={(e) => setTempUrl(e.target.value)}
                  placeholder="https://kawad-swad-sales-dev.onrender.com"
                  required
                />
              </label>

              <div className="actions" style={{ marginTop: '16px' }}>
                <button type="submit">Save &amp; Reconnect</button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setTempUrl('https://kawad-swad-sales-dev.onrender.com');
                    updateBackendUrl('https://kawad-swad-sales-dev.onrender.com');
                    setShowConfig(false);
                  }}
                >
                  Reset Default
                </button>
                <button type="button" className="secondary" onClick={() => setShowConfig(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
};
