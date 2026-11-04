import React from 'react';

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
  actionLabel?: string;
  onAction?: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon,
  actionLabel,
  onAction,
}) => {
  return (
    <div className="py-12 px-4 text-center flex flex-col items-center justify-center max-w-md mx-auto">
      {icon && (
        <div className="w-14 h-14 rounded-2xl bg-slate-100 text-slate-500 flex items-center justify-center mb-3.5 shadow-2xs">
          {icon}
        </div>
      )}
      <h3 className="text-base font-bold text-slate-900 tracking-tight m-0">
        {title}
      </h3>
      <p className="text-xs sm:text-sm text-slate-500 mt-1 mb-5 leading-relaxed">
        {description}
      </p>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 active:bg-emerald-950 text-white font-semibold text-xs rounded-lg transition-colors cursor-pointer shadow-xs"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
};
