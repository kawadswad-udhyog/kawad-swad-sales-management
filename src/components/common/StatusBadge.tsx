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
    if (['APPROVED', 'PRESENT', 'PAID', 'DELIVERED', 'ISSUED', 'CONNECTED', 'OK', 'RECEIVED', 'ACTIVE', 'POSTED', 'SUBMITTED_APPROVED'].includes(norm)) {
      autoVariant = 'success';
    } else if (['PENDING', 'HALF_DAY', 'SUBMITTED', 'DRAFT', 'CONNECTING', 'UNPAID', 'IN_PROGRESS'].includes(norm)) {
      autoVariant = 'warning';
    } else if (['REJECTED', 'ABSENT', 'CANCELLED', 'DISCONNECTED', 'ERROR', 'INACTIVE', 'FAILED'].includes(norm)) {
      autoVariant = 'danger';
    } else if (['ECOMMERCE', 'WHOLESALE', 'RETAIL', 'BULK', 'EXPORT'].includes(norm)) {
      autoVariant = 'info';
    }
  }

  const colorStyles: Record<BadgeVariant, { dot: string; text: string; bg: string; border: string }> = {
    success: {
      dot: 'bg-emerald-600',
      text: 'text-emerald-900',
      bg: 'bg-emerald-50',
      border: 'border-emerald-200',
    },
    warning: {
      dot: 'bg-amber-500',
      text: 'text-amber-900',
      bg: 'bg-amber-50',
      border: 'border-amber-200',
    },
    danger: {
      dot: 'bg-rose-500',
      text: 'text-rose-900',
      bg: 'bg-rose-50',
      border: 'border-rose-200',
    },
    info: {
      dot: 'bg-sky-500',
      text: 'text-sky-900',
      bg: 'bg-sky-50',
      border: 'border-sky-200',
    },
    purple: {
      dot: 'bg-purple-500',
      text: 'text-purple-900',
      bg: 'bg-purple-50',
      border: 'border-purple-200',
    },
    neutral: {
      dot: 'bg-slate-400',
      text: 'text-slate-700',
      bg: 'bg-slate-100',
      border: 'border-slate-200',
    },
  };

  const style = colorStyles[autoVariant];
  const isSm = size === 'sm';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-semibold border rounded-md uppercase tracking-wider ${
        isSm ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs'
      } ${style.bg} ${style.text} ${style.border}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${style.dot}`} />
      {icon && <span className="shrink-0">{icon}</span>}
      <span className="truncate">{status}</span>
    </span>
  );
};
