import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { UserRole } from '../types';

export const UsersView: React.FC = () => {
  const { users, createUser, currentUser } = useStore();
  const [fullName, setFullName] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('password123');
  const [role, setRole] = useState<UserRole>('SALESMAN');
  const [mobile, setMobile] = useState('');
  const [email, setEmail] = useState('');
  const [notes, setNotes] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  if (currentUser?.role !== 'OWNER') {
    return (
      <div className="card notice-error">
        Access restricted. Only the business Owner can manage users.
      </div>
    );
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (users.some((u) => u.username.toLowerCase() === username.trim().toLowerCase())) {
      setNotice({ msg: 'A user with this username already exists.', error: true });
      return;
    }

    try {
      const newUserId = `USR-${role.slice(0, 3)}-${Date.now().toString().slice(-4)}`;
      createUser({
        user_id: newUserId,
        full_name: fullName.trim(),
        username: username.trim().toLowerCase(),
        password,
        role,
        mobile: mobile.trim(),
        email: email.trim(),
        active: true,
        notes: notes.trim(),
      });

      setNotice({ msg: `User ${fullName} (${username}) created successfully.` });
      setFullName('');
      setUsername('');
      setMobile('');
      setEmail('');
      setNotes('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to create user';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  return (
    <div>
      <h1>User &amp; Team Management</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      <div className="card">
        <h2>Register new team member</h2>
        <form className="inline" onSubmit={handleSubmit}>
          <label>
            Full name
            <input
              required
              placeholder="e.g. Anand Sharma"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>

          <label>
            Username
            <input
              required
              placeholder="e.g. anand"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>

          <label>
            Role
            <select value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
              <option value="SALESMAN">SALESMAN (Field Sales)</option>
              <option value="PA">PA (Personal Assistant / Data Handler)</option>
              <option value="OWNER">OWNER (Business Admin)</option>
            </select>
          </label>

          <label>
            Mobile
            <input
              type="tel"
              placeholder="10-digit mobile"
              value={mobile}
              onChange={(e) => setMobile(e.target.value)}
            />
          </label>

          <label>
            Email
            <input
              type="email"
              placeholder="name@kawadswad.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>

          <label>
            Temporary password
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          <label style={{ gridColumn: 'span 2' }}>
            Notes / Territory
            <input
              placeholder="Assigned district or responsibilities..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>

          <div style={{ gridColumn: 'span 2', marginTop: '6px' }}>
            <button type="submit">Create User Account</button>
          </div>
        </form>
      </div>

      <div className="card">
        <h2>Active Team Accounts</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User ID</th>
                <th>Full Name</th>
                <th>Username</th>
                <th>Role</th>
                <th>Mobile</th>
                <th>Status</th>
                <th>Join Date</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id}>
                  <td>
                    <code>{u.user_id}</code>
                  </td>
                  <td>
                    <strong>{u.full_name}</strong>
                  </td>
                  <td>{u.username}</td>
                  <td>
                    <span
                      style={{
                        padding: '3px 8px',
                        borderRadius: '999px',
                        fontSize: '0.78rem',
                        fontWeight: 700,
                        background:
                          u.role === 'OWNER'
                            ? '#fef08a'
                            : u.role === 'PA'
                            ? '#bfdbfe'
                            : '#bbf7d0',
                        color:
                          u.role === 'OWNER'
                            ? '#854d0e'
                            : u.role === 'PA'
                            ? '#1e40af'
                            : '#166534',
                      }}
                    >
                      {u.role}
                    </span>
                  </td>
                  <td>{u.mobile || '—'}</td>
                  <td>
                    <span className="badge on">Active</span>
                  </td>
                  <td>{new Date(u.created_at).toLocaleDateString('en-IN')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
