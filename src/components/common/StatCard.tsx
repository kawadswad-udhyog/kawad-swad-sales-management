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
  trend?: string;
  trendPositive?: boolean;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtext,
  icon,
  alert = false,
  alertColor = 'amber',
  onClick,
  trend,
  trendPositive,
}) => {
  const isClickable = Boolean(onClick);

  let borderClasses = 'border-slate-200 bg-white hover:border-slate-300';
  if (alert) {
    if (alertColor === 'red') {
      borderClasses = 'border-red-200 bg-red-50/40 hover:border-red-300';
    } else {
      borderClasses = 'border-amber-200 bg-amber-50/40 hover:border-amber-300';
    }
  }

  return (
    <div
      onClick={onClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={isClickable ? (e) => e.key === 'Enter' && onClick!() : undefined}
      className={`border rounded-xl p-4 sm:p-5 shadow-2xs transition-all duration-150 flex flex-col justify-between gap-3 ${borderClasses} ${
        isClickable ? 'cursor-pointer hover:shadow-xs active:scale-[0.99]' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 leading-snug">
          {title}
        </span>
        {icon && (
          <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-100 flex items-center justify-center shrink-0 shadow-2xs">
            {icon}
          </div>
        )}
      </div>

      <div className="flex items-baseline justify-between gap-2">
        <div className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
          {value}
        </div>
        {trend && (
          <span
            className={`text-xs font-bold ${
              trendPositive ? 'text-emerald-700' : 'text-slate-500'
            }`}
          >
            {trend}
          </span>
        )}
      </div>

      {subtext && (
        <div className="text-xs text-slate-500 font-medium leading-relaxed border-t border-slate-100 pt-2 -mb-0.5">
          {subtext}
        </div>
      )}
    </div>
  );
};

export const SummaryCard = StatCard;
