import React from 'react';

interface QuickActionProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  badge?: string | number;
  disabled?: boolean;
}

export const QuickAction: React.FC<QuickActionProps> = ({
  title,
  description,
  icon,
  onClick,
  primary = false,
  badge,
  disabled = false,
}) => {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`relative w-full p-4 sm:p-5 text-left rounded-xl border transition-all duration-150 flex items-start gap-4 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed group ${
        primary
          ? 'bg-emerald-50/70 border-emerald-300 hover:bg-emerald-100/70 hover:border-emerald-400 text-emerald-950 shadow-2xs'
          : 'bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50/60 text-slate-900 shadow-2xs'
      }`}
    >
      <div
        className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 text-base font-bold transition-transform group-hover:scale-105 shadow-2xs ${
          primary
            ? 'bg-emerald-800 text-white'
            : 'bg-slate-100 text-slate-700 group-hover:bg-slate-200'
        }`}
      >
        {icon}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <strong className="text-sm font-bold tracking-tight truncate block">
            {title}
          </strong>
          {badge !== undefined && badge !== null && (
            <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 shrink-0">
              {badge}
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500 font-normal mt-0.5 line-clamp-2 leading-relaxed">
          {description}
        </p>
      </div>
    </button>
  );
};
