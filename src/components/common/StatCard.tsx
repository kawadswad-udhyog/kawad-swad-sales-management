import React from 'react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  icon?: React.ReactNode;
  iconBg?: string;
  iconColor?: string;
  alert?: boolean;
  alertColor?: 'amber' | 'red';
  onClick?: () => void;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtext,
  icon,
  iconBg = '#ecfdf5',
  iconColor = '#166534',
  alert = false,
  alertColor = 'amber',
  onClick,
}) => {
  const isClickable = Boolean(onClick);

  let border = '1px solid #e2e8f0';
  let bg = '#ffffff';

  if (alert) {
    if (alertColor === 'red') {
      border = '1px solid #fca5a5';
      bg = '#fef2f2';
    } else {
      border = '1px solid #fde68a';
      bg = '#fffbeb';
    }
  }

  return (
    <div
      onClick={onClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={isClickable ? (e) => e.key === 'Enter' && onClick!() : undefined}
      style={{
        background: bg,
        border,
        borderRadius: '12px',
        padding: '16px 18px',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
        cursor: isClickable ? 'pointer' : 'default',
        transition: 'transform 0.15s ease, box-shadow 0.15s ease',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        gap: '8px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
        <span
          style={{
            fontSize: '0.80rem',
            fontWeight: 600,
            color: alert ? (alertColor === 'red' ? '#991b1b' : '#92400e') : '#64748b',
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}
        >
          {title}
        </span>
        {icon && (
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: iconBg,
              color: iconColor,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            {icon}
          </div>
        )}
      </div>

      <div
        style={{
          fontSize: '1.65rem',
          fontWeight: 800,
          color: alert ? (alertColor === 'red' ? '#b91c1c' : '#b45309') : '#0f172a',
          lineHeight: 1.15,
        }}
      >
        {value}
      </div>

      {subtext && (
        <span
          style={{
            fontSize: '0.78rem',
            color: alert ? (alertColor === 'red' ? '#b91c1c' : '#92400e') : '#64748b',
            fontWeight: 500,
          }}
        >
          {subtext}
        </span>
      )}
    </div>
  );
};
