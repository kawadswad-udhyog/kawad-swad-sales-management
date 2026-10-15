import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { exportSheetToExcel } from '../utils/exportToExcel';

export const AuditView: React.FC = () => {
  const { auditLogs } = useStore();
  const [filterAction, setFilterAction] = useState<string>('ALL');
  const [filterEntity, setFilterEntity] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');

  const actions = ['ALL', ...Array.from(new Set(auditLogs.map((l) => l.action)))];
  const entities = ['ALL', ...Array.from(new Set(auditLogs.map((l) => l.entity_type)))];

  const filteredLogs = auditLogs.filter((log) => {
    if (filterAction !== 'ALL' && log.action !== filterAction) return false;
    if (filterEntity !== 'ALL' && log.entity_type !== filterEntity) return false;
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      return (
        (log.reason && log.reason.toLowerCase().includes(q)) ||
        log.entity_id.toLowerCase().includes(q) ||
        log.actor_user_id.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const handleExport = () => {
    exportSheetToExcel('Audit_Log', filteredLogs);
  };

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
          <div>
            <h2>System Audit Trail</h2>
            <p className="muted">Track all administrative, sales, inventory, and expense operations</p>
          </div>
          <button type="button" className="secondary" onClick={handleExport}>
            Export Audit Log (Excel)
          </button>
        </div>

        <div className="filter-bar" style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
          <div style={{ flex: '1 1 200px' }}>
            <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>Filter by Action</label>
            <select value={filterAction} onChange={(e) => setFilterAction(e.target.value)}>
              {actions.map((act) => (
                <option key={act} value={act}>
                  {act}
                </option>
              ))}
            </select>
          </div>

          <div style={{ flex: '1 1 200px' }}>
            <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>Filter by Entity</label>
            <select value={filterEntity} onChange={(e) => setFilterEntity(e.target.value)}>
              {entities.map((ent) => (
                <option key={ent} value={ent}>
                  {ent}
                </option>
              ))}
            </select>
          </div>

          <div style={{ flex: '2 1 250px' }}>
            <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>Search details / ID</label>
            <input
              type="text"
              placeholder="Search keyword..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </div>

        {filteredLogs.length > 0 ? (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Target ID</th>
                  <th>Details / Reason</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.map((log) => (
                  <tr key={log.audit_id}>
                    <td style={{ fontSize: '0.85rem', whiteSpace: 'nowrap' }}>
                      {new Date(log.event_datetime).toLocaleString()}
                    </td>
                    <td>
                      <strong>{log.actor_user_id}</strong>
                    </td>
                    <td>
                      <span className={`badge ${log.action === 'CREATE' ? 'on' : log.action === 'APPROVE' ? 'on' : 'off'}`}>
                        {log.action}
                      </span>
                    </td>
                    <td>{log.entity_type}</td>
                    <td>
                      <code style={{ fontSize: '0.85rem' }}>{log.entity_id}</code>
                    </td>
                    <td style={{ fontSize: '0.9rem' }}>{log.reason || log.field_changed || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No audit log records match the selected filters.</p>
        )}
      </div>
    </div>
  );
};
