import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';

export const LoginModal: React.FC = () => {
  const { login, backendUrl, updateBackendUrl } = useStore();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
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
      <p className="muted">Enter your username and password to access the workspace.</p>

      <form onSubmit={handleSubmit} style={{ marginTop: '16px' }}>
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
                Tip: Render free services sleep after inactivity and can take ~40 seconds to spin up on the first request.
              </p>
            )}
            {error.toLowerCase().includes('invalid username or password') && (
              <p style={{ margin: '6px 0 0', fontSize: '0.8rem', opacity: 0.9 }}>
                Please check username and password casing. Ensure this account exists in the active <code>AuthUsers</code> sheet.
              </p>
            )}
            {error.toLowerCase().includes('legacy password') && (
              <p style={{ margin: '6px 0 0', fontSize: '0.8rem', opacity: 0.9 }}>
                This account has a legacy password. Run <code>python backend/scripts/reset_password.py</code> to set an upgraded PBKDF2 password.
              </p>
            )}
          </div>
        )}

        <button
          type="submit"
          style={{ width: '100%', marginTop: '20px', padding: '12px', fontWeight: 700 }}
          disabled={isLoading}
        >
          {isLoading ? '⏳ Verifying credentials…' : 'Sign In'}
        </button>
      </form>

      <div style={{ textAlign: 'center', marginTop: '20px' }}>
        <button
          type="button"
          onClick={() => setShowServerConfig(!showServerConfig)}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#64748b',
            fontSize: '0.75rem',
            cursor: 'pointer',
            textDecoration: 'underline'
          }}
        >
          {showServerConfig ? 'Hide connection settings' : '⚙ Connection settings'}
        </button>
      </div>

      {showServerConfig && (
        <form onSubmit={handleSaveBackendUrl} style={{ background: '#f8faf9', padding: '12px', borderRadius: '8px', marginTop: '10px' }}>
          <label style={{ margin: '0 0 6px', fontSize: '0.78rem' }}>FastAPI Backend Endpoint URL:</label>
          <input
            type="url"
            value={customUrl}
            onChange={(e) => setCustomUrl(e.target.value)}
            placeholder="https://kawad-swad-sales-dev.onrender.com"
            required
            style={{ marginBottom: '8px', fontSize: '0.80rem' }}
          />
          <div className="actions" style={{ gap: '8px' }}>
            <button type="submit" style={{ padding: '5px 10px', fontSize: '0.78rem' }}>Save URL</button>
            <button
              type="button"
              className="secondary"
              style={{ padding: '5px 10px', fontSize: '0.78rem' }}
              onClick={() => {
                setCustomUrl('https://kawad-swad-sales-dev.onrender.com');
                updateBackendUrl('https://kawad-swad-sales-dev.onrender.com');
                setShowServerConfig(false);
              }}
            >
              Reset Default
            </button>
          </div>
        </form>
      )}
    </section>
  );
};
