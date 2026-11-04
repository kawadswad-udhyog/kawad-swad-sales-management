import React, { useState } from 'react';
import {
  AlertCircle,
  HelpCircle,
  CheckCircle2,
  RefreshCw,
  Calendar,
  IndianRupee,
  ChevronDown,
  ChevronUp,
  Plus,
  Minus,
  X,
} from 'lucide-react';

/**
 * ------------------------------------------------------------------
 * KAWAD SWAD ERP: COMMON FORM DESIGN SYSTEM
 * Standardized, accessible, touch-friendly form primitives
 * ------------------------------------------------------------------
 */

export interface FormLayoutProps {
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  onSubmit?: (e: React.FormEvent) => void | Promise<void>;
  onCancel?: () => void;
  onClose?: () => void;
  asModal?: boolean;
  isLoading?: boolean;
  children: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl' | '4xl' | 'full' | string;
}

export const FormLayout: React.FC<FormLayoutProps> = ({
  title,
  subtitle,
  icon,
  badge,
  onSubmit,
  onCancel,
  onClose,
  asModal = false,
  isLoading = false,
  children,
  actions,
  className = '',
  maxWidth = '2xl',
}) => {
  const standardWidths: Record<string, string> = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
    '3xl': 'max-w-3xl',
    '4xl': 'max-w-4xl',
    full: 'max-w-full',
  };

  const resolvedMaxWidth = standardWidths[maxWidth] || maxWidth;

  const content = (
    <div
      className={`bg-white border border-[#E7E2D6] rounded-2xl shadow-[0_8px_30px_rgb(0,0,0,0.06)] overflow-hidden w-full ${resolvedMaxWidth} mx-auto ${className}`}
    >
      {/* Form Header */}
      <div className="p-5 sm:p-6 border-b border-[#F0ECE1] bg-[#FAF8F5] flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          {icon && (
            <div className="w-10 h-10 rounded-xl bg-[#0F2C23] text-white flex items-center justify-center shrink-0 shadow-xs mt-0.5">
              {icon}
            </div>
          )}
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg sm:text-xl font-bold text-slate-900 tracking-tight m-0" style={{ color: '#0f172a' }}>
                {title}
              </h2>
              {badge}
            </div>
            {subtitle && (
              <p className="text-xs text-slate-500 mt-1 leading-relaxed m-0">{subtitle}</p>
            )}
          </div>
        </div>
        {(onClose || onCancel) && (
          <button
            type="button"
            onClick={onClose || onCancel}
            className="text-slate-400 hover:text-slate-700 p-1 rounded-lg hover:bg-slate-100 transition-colors"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* Form Body & Actions */}
      {onSubmit ? (
        <form onSubmit={onSubmit}>
          <div className="p-5 sm:p-7 space-y-6">{children}</div>
          {actions && (
            <div className="p-4 sm:p-5 border-t border-[#F0ECE1] bg-[#FAF8F5] flex items-center justify-end gap-3">
              {actions}
            </div>
          )}
        </form>
      ) : (
        <>
          <div className="p-5 sm:p-7 space-y-6">{children}</div>
          {actions && (
            <div className="p-4 sm:p-5 border-t border-[#F0ECE1] bg-[#FAF8F5] flex items-center justify-end gap-3">
              {actions}
            </div>
          )}
        </>
      )}
    </div>
  );

  if (asModal) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs overflow-y-auto">
        {content}
      </div>
    );
  }

  return content;
};

export interface FormSectionProps {
  title: string;
  description?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
  children: React.ReactNode;
  badge?: React.ReactNode;
  className?: string;
}

export const FormSection: React.FC<FormSectionProps> = ({
  title,
  description,
  collapsible = false,
  defaultOpen = true,
  children,
  badge,
  className = '',
}) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className={`border border-[#EAE6DF] rounded-xl overflow-hidden bg-white ${className}`}>
      <div
        className={`px-4 py-3 bg-[#FAF8F5] border-b border-[#EAE6DF] flex items-center justify-between gap-3 ${
          collapsible ? 'cursor-pointer select-none hover:bg-[#F5F2EB] transition-colors' : ''
        }`}
        onClick={collapsible ? () => setIsOpen(!isOpen) : undefined}
      >
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 m-0" style={{ color: '#1e293b' }}>
              {title}
            </h3>
            {badge}
          </div>
          {description && <p className="text-[11px] text-slate-500 mt-0.5 m-0">{description}</p>}
        </div>

        {collapsible && (
          <button
            type="button"
            className="text-slate-400 hover:text-slate-700 transition-colors p-1"
            aria-label={isOpen ? 'Collapse section' : 'Expand section'}
          >
            {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        )}
      </div>

      {isOpen && <div className="p-4 sm:p-5 space-y-4">{children}</div>}
    </div>
  );
};

export interface FormFieldProps {
  label?: string;
  htmlFor?: string;
  required?: boolean;
  error?: string | null;
  helpText?: string;
  children: React.ReactNode;
  className?: string;
}

export const FormField: React.FC<FormFieldProps> = ({
  label,
  htmlFor,
  required = false,
  error,
  helpText,
  children,
  className = '',
}) => {
  return (
    <div className={`space-y-1.5 ${className}`}>
      {label && (
        <label
          htmlFor={htmlFor}
          className="block text-xs font-bold text-slate-700 tracking-tight"
          style={{ display: 'block', color: '#334155' }}
        >
          {label}
          {required && <span className="text-rose-600 ml-1 font-black">*</span>}
        </label>
      )}

      {children}

      {error ? (
        <div className="flex items-center gap-1.5 text-xs text-rose-700 font-medium pt-0.5">
          <AlertCircle size={13} className="shrink-0 text-rose-600" />
          <span>{error}</span>
        </div>
      ) : helpText ? (
        <p className="text-[11px] text-slate-500 font-normal leading-normal m-0">{helpText}</p>
      ) : null}
    </div>
  );
};

export interface MoneyInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  value: number | string;
  onChange: (val: number) => void;
  currencySymbol?: string;
}

export const MoneyInput: React.FC<MoneyInputProps> = ({
  value,
  onChange,
  currencySymbol = '₹',
  disabled,
  placeholder = '0.00',
  className = '',
  ...props
}) => {
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value;
    const clean = raw.replace(/[^0-9.]/g, '');
    const num = parseFloat(clean);
    onChange(isNaN(num) ? 0 : num);
  };

  return (
    <div className="relative flex items-center">
      <span className="absolute left-3 text-slate-400 font-bold text-sm pointer-events-none select-none">
        {currencySymbol}
      </span>
      <input
        type="text"
        inputMode="decimal"
        value={value === 0 && placeholder ? '' : value}
        onChange={handleChange}
        placeholder={placeholder}
        disabled={disabled}
        style={{ paddingLeft: '32px', paddingRight: '14px' }}
        className={`w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] font-medium text-slate-900 transition-colors disabled:bg-slate-50 disabled:text-slate-400 ${className}`}
        {...props}
      />
    </div>
  );
};

export interface QuantityInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  value: number | string;
  onChange: (val: number) => void;
  unit?: string;
  step?: number;
  min?: number;
  max?: number;
  allowNegative?: boolean;
}

export const QuantityInput: React.FC<QuantityInputProps> = ({
  value,
  onChange,
  unit = 'kg',
  step = 1,
  min = 0,
  max,
  allowNegative = false,
  disabled,
  className = '',
  ...props
}) => {
  const numVal = typeof value === 'number' ? value : parseFloat(value) || 0;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value;
    const parsed = parseFloat(raw);
    if (isNaN(parsed)) {
      onChange(0);
      return;
    }
    if (!allowNegative && parsed < min) {
      onChange(min);
      return;
    }
    if (max !== undefined && parsed > max) {
      onChange(max);
      return;
    }
    onChange(parsed);
  };

  const increment = () => {
    const next = numVal + step;
    if (max !== undefined && next > max) return;
    onChange(Math.round(next * 1000) / 1000);
  };

  const decrement = () => {
    const next = numVal - step;
    if (!allowNegative && next < min) return;
    onChange(Math.round(next * 1000) / 1000);
  };

  return (
    <div className="relative flex items-center">
      <input
        type="number"
        step={step}
        min={min}
        max={max}
        value={value}
        onChange={handleChange}
        disabled={disabled}
        style={{ paddingRight: unit ? '58px' : '36px' }}
        className={`w-full py-2.5 pl-3 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] font-medium text-slate-900 transition-colors disabled:bg-slate-50 disabled:text-slate-400 ${className}`}
        {...props}
      />
      {unit && (
        <span className="absolute right-2.5 px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[11px] font-bold uppercase tracking-wider pointer-events-none select-none">
          {unit}
        </span>
      )}
    </div>
  );
};

export interface DateInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> {
  value: string;
  onChange: (val: string) => void;
  showTodayButton?: boolean;
}

export const DateInput: React.FC<DateInputProps> = ({
  value,
  onChange,
  showTodayButton = true,
  disabled,
  className = '',
  ...props
}) => {
  const setToday = () => {
    const now = new Date();
    const str = now.toISOString().split('T')[0];
    onChange(str);
  };

  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1 flex items-center">
        <span className="absolute left-3 text-slate-400 pointer-events-none">
          <Calendar size={15} />
        </span>
        <input
          type="date"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          style={{ paddingLeft: '34px', paddingRight: '12px' }}
          className={`w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] font-medium text-slate-900 transition-colors disabled:bg-slate-50 disabled:text-slate-400 ${className}`}
          {...props}
        />
      </div>

      {showTodayButton && (
        <button
          type="button"
          onClick={setToday}
          disabled={disabled}
          className="px-2.5 py-2 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors cursor-pointer shrink-0 disabled:opacity-50"
          title="Set date to today"
        >
          Today
        </button>
      )}
    </div>
  );
};

export interface CalculationPreviewItem {
  label: string;
  value: React.ReactNode;
  subtitle?: string;
  isHighlight?: boolean;
  variant?: 'emerald' | 'amber' | 'slate' | 'rose';
}

export interface CalculationPreviewProps {
  label?: string;
  value?: React.ReactNode;
  subtitle?: string;
  variant?: 'emerald' | 'amber' | 'slate' | 'rose';
  className?: string;
  title?: string;
  items?: CalculationPreviewItem[];
}

export const CalculationPreview: React.FC<CalculationPreviewProps> = ({
  label,
  value,
  subtitle,
  variant = 'emerald',
  className = '',
  title,
  items,
}) => {
  if (items && items.length > 0) {
    return (
      <div className={`p-4 rounded-xl border border-slate-200 bg-[#FAF9F6] space-y-2.5 ${className}`}>
        {title && (
          <div className="text-xs font-bold uppercase tracking-wider text-slate-700 flex items-center justify-between border-b border-slate-200/80 pb-2">
            <span>{title}</span>
            <span className="text-[10px] text-emerald-800 font-semibold bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
              Live Preview
            </span>
          </div>
        )}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {items.map((it, idx) => {
            const isHigh = it.isHighlight;
            return (
              <div
                key={idx}
                className={`p-2.5 rounded-lg border ${
                  isHigh
                    ? 'bg-[#F0FDF4] border-[#BBF7D0] text-[#14532D] col-span-2 sm:col-span-1 shadow-xs'
                    : 'bg-white border-slate-200 text-slate-800'
                }`}
              >
                <span className="text-[11px] font-semibold text-slate-500 block leading-tight">{it.label}</span>
                <div className={`mt-0.5 font-bold ${isHigh ? 'text-base text-emerald-900 font-extrabold' : 'text-sm'}`}>
                  {it.value}
                </div>
                {it.subtitle && <span className="text-[10px] text-slate-400 block mt-0.5">{it.subtitle}</span>}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  const styleMap = {
    emerald: 'bg-[#F0FDF4] border-[#BBF7D0] text-[#14532D]',
    amber: 'bg-[#FFFBEB] border-[#FDE68A] text-[#78350F]',
    slate: 'bg-[#F8FAFC] border-[#E2E8F0] text-[#0F172A]',
    rose: 'bg-[#FFF1F2] border-[#FECDD3] text-[#881337]',
  }[variant];

  return (
    <div className={`p-3.5 rounded-xl border flex items-center justify-between gap-3 ${styleMap} ${className}`}>
      <div>
        <span className="text-xs font-bold uppercase tracking-wider block opacity-90">{label}</span>
        {subtitle && <span className="text-[11px] opacity-75 block mt-0.5">{subtitle}</span>}
      </div>
      <div className="text-base sm:text-lg font-black tracking-tight">{value}</div>
    </div>
  );
};

export interface SaveButtonProps {
  label?: string;
  isLoading?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
  variant?: 'primary' | 'danger' | 'secondary';
  onClick?: () => void;
  className?: string;
}

export const SaveButton: React.FC<SaveButtonProps> = ({
  label = 'Save Record',
  isLoading = false,
  disabled = false,
  icon,
  variant = 'primary',
  onClick,
  className = '',
}) => {
  const bgClass = {
    primary: 'bg-[#0F2C23] hover:bg-[#153D31] active:bg-[#0A201A] text-white',
    danger: 'bg-rose-700 hover:bg-rose-800 active:bg-rose-900 text-white',
    secondary: 'bg-slate-800 hover:bg-slate-900 active:bg-black text-white',
  }[variant];

  return (
    <button
      type={onClick ? 'button' : 'submit'}
      onClick={onClick}
      disabled={isLoading || disabled}
      className={`px-5 py-2.5 rounded-xl text-xs font-bold transition-all shadow-sm flex items-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${bgClass} ${className}`}
    >
      {isLoading ? (
        <>
          <RefreshCw size={14} className="animate-spin text-white" />
          <span>Processing…</span>
        </>
      ) : (
        <>
          {icon}
          <span>{label}</span>
        </>
      )}
    </button>
  );
};

export interface CancelButtonProps {
  label?: string;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
}

export const CancelButton: React.FC<CancelButtonProps> = ({
  label = 'Cancel',
  onClick,
  disabled = false,
  className = '',
}) => {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`px-4 py-2.5 rounded-xl border border-slate-300 hover:bg-slate-100 active:bg-slate-200 text-slate-700 text-xs font-bold transition-colors cursor-pointer disabled:opacity-50 ${className}`}
    >
      {label}
    </button>
  );
};

export interface FormActionsProps {
  onCancel?: () => void;
  cancelLabel?: string;
  saveLabel?: string;
  isLoading?: boolean;
  disabled?: boolean;
  secondaryActions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

export const FormActions: React.FC<FormActionsProps> = ({
  onCancel,
  cancelLabel = 'Cancel',
  saveLabel = 'Save Record',
  isLoading = false,
  disabled = false,
  secondaryActions,
  children,
  className = '',
}) => {
  if (children) {
    return (
      <div className={`flex items-center justify-end gap-3 pt-2 ${className}`}>
        {children}
      </div>
    );
  }

  return (
    <div className={`flex items-center justify-end gap-3 pt-2 ${className}`}>
      {secondaryActions}

      {onCancel && (
        <CancelButton onClick={onCancel} label={cancelLabel} disabled={isLoading} />
      )}

      <SaveButton label={saveLabel} isLoading={isLoading} disabled={disabled} />
    </div>
  );
};

export interface TextInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  icon?: React.ReactNode;
}

export const TextInput: React.FC<TextInputProps> = ({
  icon,
  className = '',
  disabled,
  ...props
}) => {
  return (
    <div className="relative flex items-center">
      {icon && (
        <span className="absolute left-3 text-slate-400 pointer-events-none select-none">
          {icon}
        </span>
      )}
      <input
        disabled={disabled}
        style={{ paddingLeft: icon ? '34px' : '12px', paddingRight: '12px' }}
        className={`w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] font-medium text-slate-900 transition-colors disabled:bg-slate-50 disabled:text-slate-400 ${className}`}
        {...props}
      />
    </div>
  );
};

export interface SelectInputProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  icon?: React.ReactNode;
  options?: Array<{ value: string | number; label: string }>;
  children?: React.ReactNode;
}

export const SelectInput: React.FC<SelectInputProps> = ({
  icon,
  options,
  children,
  className = '',
  disabled,
  ...props
}) => {
  return (
    <div className="relative flex items-center">
      {icon && (
        <span className="absolute left-3 text-slate-400 pointer-events-none select-none">
          {icon}
        </span>
      )}
      <select
        disabled={disabled}
        style={{ paddingLeft: icon ? '34px' : '12px', paddingRight: '32px' }}
        className={`w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] font-medium text-slate-900 transition-colors disabled:bg-slate-50 disabled:text-slate-400 appearance-none ${className}`}
        {...props}
      >
        {options
          ? options.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))
          : children}
      </select>
      <span className="absolute right-3 text-slate-400 pointer-events-none select-none">
        <ChevronDown size={14} />
      </span>
    </div>
  );
};

export interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

export const TextArea: React.FC<TextAreaProps> = ({
  className = '',
  disabled,
  ...props
}) => {
  return (
    <textarea
      disabled={disabled}
      className={`w-full p-3 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] font-medium text-slate-900 transition-colors disabled:bg-slate-50 disabled:text-slate-400 ${className}`}
      {...props}
    />
  );
};

