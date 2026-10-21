import React from 'react';

export type BadgeVariant =
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
  | 'neutral'
  | 'purple';

interface StatusBadgeProps {
  status: string;
  variant?: BadgeVariant;
  icon?: React.ReactNode;
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  variant,
  icon,
  size = 'md',
}) => {
  const norm = String(status || '').toUpperCase().trim();

  let autoVariant: BadgeVariant = variant || 'neutral';
  if (!variant) {
    if (['APPROVED', 'PRESENT', 'PAID', 'DELIVERED', 'ISSUED', 'CONNECTED', 'OK', 'RECEIVED', 'ACTIVE'].includes(norm)) {
      autoVariant = 'success';
    } else if (['PENDING', 'HALF_DAY', 'SUBMITTED', 'DRAFT', 'CONNECTING', 'UNPAID'].includes(norm)) {
      autoVariant = 'warning';
    } else if (['REJECTED', 'ABSENT', 'CANCELLED', 'DISCONNECTED', 'ERROR', 'INACTIVE'].includes(norm)) {
      autoVariant = 'danger';
    } else if (['ECOMMERCE', 'WHOLESALE', 'RETAIL', 'BULK'].includes(norm)) {
      autoVariant = 'info';
    }
  }

  const styles: Record<BadgeVariant, { bg: string; text: string; border: string }> = {
    success: { bg: '#ecfdf5', text: '#15803d', border: '#bbf7d0' },
    warning: { bg: '#fffbeb', text: '#b45309', border: '#fde68a' },
    danger: { bg: '#fef2f2', text: '#b91c1c', border: '#fecaca' },
    info: { bg: '#f0f9ff', text: '#0369a1', border: '#bae6fd' },
    purple: { bg: '#faf5ff', text: '#7e22ce', border: '#e9d5ff' },
    neutral: { bg: '#f1f5f9', text: '#475569', border: '#e2e8f0' },
  };

  const current = styles[autoVariant] || styles.neutral;
  const isSm = size === 'sm';

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: isSm ? '2px 6px' : '3px 8px',
        fontSize: isSm ? '0.70rem' : '0.78rem',
        fontWeight: 600,
        borderRadius: '6px',
        background: current.bg,
        color: current.text,
        border: `1px solid ${current.border}`,
        lineHeight: 1.2,
        whiteSpace: 'nowrap',
      }}
    >
      {icon}
      <span>{status || 'Unknown'}</span>
    </span>
  );
};
