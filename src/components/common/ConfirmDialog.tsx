import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
  isLoading?: boolean;
  inputLabel?: string;
  inputPlaceholder?: string;
  inputValue?: string;
  onInputChange?: (value: string) => void;
  inputRequired?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDestructive = false,
  isLoading = false,
  inputLabel,
  inputPlaceholder,
  inputValue = '',
  onInputChange,
  inputRequired = false,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  const isConfirmDisabled =
    isLoading || (Boolean(onInputChange) && inputRequired && !inputValue.trim());

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-xs">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="p-6">
          <div className="flex items-start gap-3.5">
            <div
              className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                isDestructive
                  ? 'bg-red-100 text-red-700'
                  : 'bg-amber-100 text-amber-700'
              }`}
            >
              <AlertTriangle size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-bold text-slate-900 m-0">
                {title}
              </h3>
              <p className="text-xs sm:text-sm text-slate-600 mt-1 mb-0 leading-relaxed">
                {message}
              </p>
            </div>
            <button
              type="button"
              onClick={onCancel}
              disabled={isLoading}
              className="text-slate-400 hover:text-slate-600 p-1 -mr-1 -mt-1 rounded-md disabled:opacity-50"
            >
              <X size={16} />
            </button>
          </div>

          {onInputChange && (
            <div className="mt-4">
              {inputLabel && (
                <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                  {inputLabel}
                  {inputRequired ? ' *' : ''}
                </label>
              )}
              <textarea
                rows={3}
                value={inputValue}
                onChange={(e) => onInputChange(e.target.value)}
                placeholder={inputPlaceholder || 'Enter reason...'}
                disabled={isLoading}
                className="w-full px-3 py-2 text-xs sm:text-sm text-slate-800 bg-slate-50 border border-slate-300 rounded-xl focus:bg-white focus:border-emerald-700 focus:outline-none disabled:opacity-60"
              />
            </div>
          )}

          <div className="mt-6 flex items-center justify-end gap-3 pt-4 border-t border-slate-100">
            <button
              type="button"
              onClick={onCancel}
              disabled={isLoading}
              className="px-4 py-2 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
            >
              {cancelLabel}
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isConfirmDisabled}
              className={`px-4 py-2 text-xs font-semibold text-white rounded-lg transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-2 ${
                isDestructive
                  ? 'bg-red-700 hover:bg-red-800'
                  : 'bg-emerald-800 hover:bg-emerald-900'
              }`}
            >
              {isLoading ? 'Processing…' : confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
