import React from 'react';
import { useStore } from '../context/StoreContext';
import { UserRole } from '../types';

export const Header: React.FC = () => {
  const { currentUser, logout, users, login, resetToSampleData } = useStore();

  const handleRoleQuickSwitch = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selectedUserId = e.target.value;
    const user = users.find((u) => u.user_id === selectedUserId);
    if (user) {
      login(user.username);
    }
  };

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

  return (
    <header>
      <div className="brand">
        Kawad Swad
        <small>Sales Management</small>
      </div>

      <div className="header-right">
        {currentUser ? (
          <>
            <div className="user-badge" title="Active signed in user">
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

            {/* Quick Switcher for easy testing during demo */}
            <select
              title="Switch user role for testing"
              value={currentUser.user_id}
              onChange={handleRoleQuickSwitch}
              style={{
                width: 'auto',
                padding: '6px 10px',
                margin: 0,
                fontSize: '0.8rem',
                background: '#235248',
                color: '#fff',
                borderColor: '#37685e',
                cursor: 'pointer',
              }}
            >
              {users.map((u) => (
                <option key={u.user_id} value={u.user_id} style={{ background: '#fff', color: '#000' }}>
                  Switch to: {u.full_name} ({u.role})
                </option>
              ))}
            </select>

            <button
              onClick={resetToSampleData}
              className="secondary"
              title="Reset data to initial state"
              style={{ fontSize: '0.8rem', padding: '6px 10px', background: 'rgba(255,255,255,0.1)', color: '#fff', border: '1px solid rgba(255,255,255,0.2)' }}
            >
              Reset Data
            </button>

            <button onClick={logout} className="secondary" style={{ padding: '6px 14px' }}>
              Sign out
            </button>
          </>
        ) : null}
      </div>
    </header>
  );
};
