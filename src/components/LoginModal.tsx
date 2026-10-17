import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';

export const LoginModal: React.FC = () => {
  const { login, backendUrl, updateBackendUrl } = useStore();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(() => {
    try {
      const saved = sessionStorage.getItem('ks_auth_error') || '';
      sessionStorage.removeItem('ks_auth_error');
      return saved;
    } catch {
      return '';
    }
  });
  const [showServerConfig, setShowServerConfig] = useState(false);
  const [customUrl, setCustomUrl] = useState(backendUrl);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!username.trim() || !password) {
      setError('Please enter both username and password.');
      return;
    }

    setIsLoading(true);
    try {
      await login(username.trim(), password);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Login failed. Please verify credentials.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveBackendUrl = (e: React.FormEvent) => {
    e.preventDefault();
    if (customUrl.trim()) {
      updateBackendUrl(customUrl.trim());
      setShowServerConfig(false);
    }
  };

  return (
    <section className="card login-card">
      <div style={{ textAlign: 'center', marginBottom: '20px' }}>
        <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#183b35' }}>Kawad Swad Udhyog</div>
        <p className="muted" style={{ margin: '4px 0 0' }}>Sales Management · Secure Workspace</p>
      </div>

      <h1>Sign In</h1>
      <p className="muted">Enter your authenticated sales credentials to access the workspace.</p>

      <div style={{ margin: '14px 0', padding: '10px 12px', background: '#edf4f1', borderRadius: '8px', fontSize: '0.82rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
            {backendUrl || 'https://kawad-swad-sales-dev.onrender.com (Proxied)'}
          </span>
        </div>
        <button
          type="button"
          className="secondary"
          style={{ padding: '3px 8px', fontSize: '0.75rem', minHeight: 'auto' }}
          onClick={() => setShowServerConfig(!showServerConfig)}
        >
          {showServerConfig ? 'Close' : 'Change'}
        </button>
      </div>

      {showServerConfig && (
        <form onSubmit={handleSaveBackendUrl} style={{ background: '#f8faf9', padding: '12px', borderRadius: '8px', marginBottom: '14px' }}>
          <label style={{ margin: '0 0 6px', fontSize: '0.8rem' }}>FastAPI Backend Endpoint URL:</label>
          <input
            type="url"
            value={customUrl}
            onChange={(e) => setCustomUrl(e.target.value)}
            placeholder="https://kawad-swad-sales-dev.onrender.com"
            required
            style={{ marginBottom: '8px' }}
          />
          <div className="actions">
            <button type="submit" style={{ padding: '6px 12px', fontSize: '0.82rem' }}>Update API URL</button>
            <button
              type="button"
              className="secondary"
              style={{ padding: '6px 12px', fontSize: '0.82rem' }}
              onClick={() => {
                setCustomUrl('https://kawad-swad-sales-dev.onrender.com');
                updateBackendUrl('https://kawad-swad-sales-dev.onrender.com');
              }}
            >
              Reset to Default Render
            </button>
          </div>
        </form>
      )}

      <form onSubmit={handleSubmit}>
        <label>
          Username
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            placeholder="e.g. owner, mahi, or salesman username"
            disabled={isLoading}
          />
        </label>

        <label>
          Password
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            placeholder="Account password"
            disabled={isLoading}
          />
        </label>

        {error && (
          <div className="notice-error" style={{ fontSize: '0.85rem', marginTop: '12px' }}>
            <strong>Authentication Error:</strong> {error}
            {error.includes('timed out') && (
              <p style={{ margin: '6px 0 0', fontSize: '0.8rem', opacity: 0.9 }}>
                Tip: Render free services sleep after inactivity and can take ~40 seconds to spin up on first request.
              </p>
            )}
          </div>
        )}

        <button
          type="submit"
          style={{ width: '100%', marginTop: '18px', padding: '12px' }}
          disabled={isLoading}
        >
          {isLoading ? 'Verifying with server…' : 'Sign in'}
        </button>
      </form>
    </section>
  );
};
