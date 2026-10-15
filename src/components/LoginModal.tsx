import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';

export const LoginModal: React.FC = () => {
  const { login, users } = useStore();
  const [username, setUsername] = useState('owner');
  const [password, setPassword] = useState('password123');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const success = await login(username);
    if (!success) {
      setError('Invalid username. Please select one of the available accounts.');
    }
  };

  const handleQuickLogin = (uname: string) => {
    setUsername(uname);
    setError('');
    login(uname);
  };

  return (
    <section className="card login-card">
      <h1>Welcome back</h1>
      <p className="muted">Sign in to your Kawad Swad sales workspace.</p>

      <div style={{ marginBottom: '18px' }}>
        <label style={{ fontSize: '0.8rem', color: '#66746f', marginBottom: '8px' }}>
          Quick Demo Sign-In:
        </label>
        <div className="quick-login-pills">
          {users.map((u) => (
            <button
              key={u.user_id}
              type="button"
              className="quick-pill"
              onClick={() => handleQuickLogin(u.username)}
            >
              {u.full_name} ({u.role})
            </button>
          ))}
        </div>
      </div>

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
            placeholder="e.g. owner, mahi, ramesh"
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
          />
        </label>

        {error && <p className="notice-error">{error}</p>}

        <button type="submit" style={{ width: '100%', marginTop: '16px' }}>
          Sign in
        </button>
      </form>
    </section>
  );
};
