/**
 * Kawad Swad ERP - Centralized Status Dictionary
 * Translates backend system status codes into plain, user-friendly labels with clear colour indicators.
 * Preserves backend enum values on the wire.
 */

export interface StatusConfig {
  label: string;
  hindi: string;
  badgeClass: string;
  borderClass: string;
  dotClass: string;
  iconName: 'Clock' | 'CheckCircle2' | 'XCircle' | 'PieChart' | 'CheckCheck' | 'Play' | 'Ban' | 'FileText' | 'AlertTriangle' | 'Coins' | 'AlertCircle';
}

export const STATUS_DICTIONARY: Record<string, StatusConfig> = {
  // General & Approvals
  PENDING: {
    label: 'Waiting',
    hindi: 'Ruka Hua',
    badgeClass: 'bg-amber-50 text-amber-800 border-amber-200',
    borderClass: 'border-amber-200',
    dotClass: 'bg-amber-500',
    iconName: 'Clock',
  },
  WAITING: {
    label: 'Waiting',
    hindi: 'Ruka Hua',
    badgeClass: 'bg-amber-50 text-amber-800 border-amber-200',
    borderClass: 'border-amber-200',
    dotClass: 'bg-amber-500',
    iconName: 'Clock',
  },
  APPROVED: {
    label: 'Approved',
    hindi: 'Manzoor',
    badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    borderClass: 'border-emerald-200',
    dotClass: 'bg-emerald-600',
    iconName: 'CheckCircle2',
  },
  REJECTED: {
    label: 'Not Approved',
    hindi: 'Nakaara',
    badgeClass: 'bg-rose-50 text-rose-800 border-rose-200',
    borderClass: 'border-rose-200',
    dotClass: 'bg-rose-500',
    iconName: 'XCircle',
  },
  PARTIAL: {
    label: 'Partial',
    hindi: 'Aadha Hua',
    badgeClass: 'bg-sky-50 text-sky-800 border-sky-200',
    borderClass: 'border-sky-200',
    dotClass: 'bg-sky-500',
    iconName: 'PieChart',
  },
  COMPLETED: {
    label: 'Done',
    hindi: 'Poora Hua',
    badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    borderClass: 'border-emerald-200',
    dotClass: 'bg-emerald-600',
    iconName: 'CheckCheck',
  },
  DONE: {
    label: 'Done',
    hindi: 'Poora Hua',
    badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    borderClass: 'border-emerald-200',
    dotClass: 'bg-emerald-600',
    iconName: 'CheckCheck',
  },
  IN_PROGRESS: {
    label: 'In Progress',
    hindi: 'Kaam Chal Raha Hai',
    badgeClass: 'bg-blue-50 text-blue-800 border-blue-200',
    borderClass: 'border-blue-200',
    dotClass: 'bg-blue-500',
    iconName: 'Play',
  },
  CANCELLED: {
    label: 'Cancelled',
    hindi: 'Radd Hua',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-300',
    borderClass: 'border-slate-300',
    dotClass: 'bg-slate-400',
    iconName: 'Ban',
  },
  DRAFT: {
    label: 'Draft',
    hindi: 'Kaccha',
    badgeClass: 'bg-slate-50 text-slate-600 border-slate-200',
    borderClass: 'border-slate-200',
    dotClass: 'bg-slate-400',
    iconName: 'FileText',
  },
  OVERDUE: {
    label: 'Overdue',
    hindi: 'Samay Beeta',
    badgeClass: 'bg-rose-50 text-rose-800 border-rose-200',
    borderClass: 'border-rose-200',
    dotClass: 'bg-rose-500',
    iconName: 'AlertTriangle',
  },

  // Payment Statuses
  PAID: {
    label: 'Paid',
    hindi: 'Chukaya',
    badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    borderClass: 'border-emerald-200',
    dotClass: 'bg-emerald-600',
    iconName: 'Coins',
  },
  UNPAID: {
    label: 'Unpaid',
    hindi: 'Baaqi',
    badgeClass: 'bg-amber-50 text-amber-800 border-amber-200',
    borderClass: 'border-amber-200',
    dotClass: 'bg-amber-500',
    iconName: 'AlertCircle',
  },
  DISBURSED: {
    label: 'Paid to Staff',
    hindi: 'Staff Ko Diya',
    badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    borderClass: 'border-emerald-200',
    dotClass: 'bg-emerald-600',
    iconName: 'Coins',
  },

  // Attendance Statuses
  PRESENT: {
    label: 'Present',
    hindi: 'Hazir',
    badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    borderClass: 'border-emerald-200',
    dotClass: 'bg-emerald-600',
    iconName: 'CheckCircle2',
  },
  ABSENT: {
    label: 'Absent',
    hindi: 'Ghair Hazir',
    badgeClass: 'bg-rose-50 text-rose-800 border-rose-200',
    borderClass: 'border-rose-200',
    dotClass: 'bg-rose-500',
    iconName: 'XCircle',
  },
  HALF_DAY: {
    label: 'Half Day',
    hindi: 'Aadha Din',
    badgeClass: 'bg-amber-50 text-amber-800 border-amber-200',
    borderClass: 'border-amber-200',
    dotClass: 'bg-amber-500',
    iconName: 'PieChart',
  },

  // User & Master Statuses
  ACTIVE: {
    label: 'Active',
    hindi: 'Chalu',
    badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    borderClass: 'border-emerald-200',
    dotClass: 'bg-emerald-600',
    iconName: 'CheckCircle2',
  },
  INACTIVE: {
    label: 'Inactive',
    hindi: 'Band',
    badgeClass: 'bg-slate-100 text-slate-600 border-slate-300',
    borderClass: 'border-slate-300',
    dotClass: 'bg-slate-400',
    iconName: 'Ban',
  },
};

/**
 * Safe status lookup helper.
 * Never crashes on undefined or unknown status codes.
 */
export function getStatusConfig(status?: string | null): StatusConfig {
  if (!status) {
    return {
      label: 'Unknown',
      hindi: 'Agyat',
      badgeClass: 'bg-slate-50 text-slate-600 border-slate-200',
      borderClass: 'border-slate-200',
      dotClass: 'bg-slate-400',
      iconName: 'FileText',
    };
  }
  const norm = String(status).trim().toUpperCase();
  return (
    STATUS_DICTIONARY[norm] || {
      label: norm.replace(/_/g, ' '),
      hindi: '',
      badgeClass: 'bg-slate-50 text-slate-700 border-slate-200',
      borderClass: 'border-slate-200',
      dotClass: 'bg-slate-400',
      iconName: 'FileText',
    }
  );
}
