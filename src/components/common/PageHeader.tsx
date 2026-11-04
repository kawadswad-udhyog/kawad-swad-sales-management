import React from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  kicker?: string;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  icon,
  actions,
  kicker,
}) => {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-5 mb-6 border-b border-slate-200">
      <div className="flex items-start sm:items-center gap-3.5">
        {icon && (
          <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-800 border border-emerald-200/60 flex items-center justify-center shrink-0 shadow-2xs">
            {icon}
          </div>
        )}
        <div>
          {kicker && (
            <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 mb-0.5">
              {kicker}
            </div>
          )}
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight leading-tight m-0">
            {title}
          </h1>
          {subtitle && (
            <p className="text-xs sm:text-sm text-slate-500 font-normal mt-1 mb-0 max-w-2xl leading-relaxed">
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {actions && (
        <div className="flex items-center gap-2.5 flex-wrap shrink-0">
          {actions}
        </div>
      )}
    </div>
  );
};
