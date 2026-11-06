/**
 * Kawad Swad ERP - Centralized Role, Category & Permission Matrix
 * Enforces role-based view access and action permissions while keeping backend authorization authoritative.
 */

import { UserRole } from '../types';

export type EmployeeCategory = 'FACTORY_WORKERS' | 'OFFICE_STAFF' | 'FIELD_STAFF' | 'ADMINISTRATIVE';

export interface DesignationConfig {
  id: string;
  title: string;
  category: EmployeeCategory;
  defaultRole: UserRole;
  department: string;
  allowedViews: string[];
  canEditProduction: boolean;
  canEditOrders: boolean;
  canBuyMaterials: boolean;
  canManageTeam: boolean;
  canViewAccounting: boolean;
}

export const DESIGNATIONS: Record<string, DesignationConfig> = {
  // 1. Factory Workers
  production_worker: {
    id: 'production_worker',
    title: 'Production Worker',
    category: 'FACTORY_WORKERS',
    defaultRole: 'FACTORY_WORKER',
    department: 'Factory Floor',
    allowedViews: ['dashboard', 'attendance', 'production', 'stock'],
    canEditProduction: true,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  packaging_worker: {
    id: 'packaging_worker',
    title: 'Packaging Worker',
    category: 'FACTORY_WORKERS',
    defaultRole: 'FACTORY_WORKER',
    department: 'Packaging',
    allowedViews: ['dashboard', 'attendance', 'packaging', 'stock'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  machine_operator: {
    id: 'machine_operator',
    title: 'Machine Operator',
    category: 'FACTORY_WORKERS',
    defaultRole: 'OPERATOR',
    department: 'Milling & Roasting',
    allowedViews: ['dashboard', 'attendance', 'production', 'quality', 'stock'],
    canEditProduction: true,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  helper: {
    id: 'helper',
    title: 'Helper / General Labour',
    category: 'FACTORY_WORKERS',
    defaultRole: 'WORKER',
    department: 'Factory Floor',
    allowedViews: ['dashboard', 'attendance', 'stock'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  factory_supervisor: {
    id: 'factory_supervisor',
    title: 'Factory Supervisor',
    category: 'FACTORY_WORKERS',
    defaultRole: 'LABOUR_SUPERVISOR',
    department: 'Production Operations',
    allowedViews: ['dashboard', 'attendance', 'production', 'packaging', 'quality', 'stock', 'workforce'],
    canEditProduction: true,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: true,
    canViewAccounting: false,
  },

  // 2. Office Staff
  office_assistant: {
    id: 'office_assistant',
    title: 'Office Assistant',
    category: 'OFFICE_STAFF',
    defaultRole: 'EMPLOYEE',
    department: 'Administration',
    allowedViews: ['dashboard', 'attendance', 'workforce'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  billing_operator: {
    id: 'billing_operator',
    title: 'Billing Operator',
    category: 'OFFICE_STAFF',
    defaultRole: 'PA',
    department: 'Sales & Billing',
    allowedViews: ['dashboard', 'sales', 'customers', 'stock', 'closing'],
    canEditProduction: false,
    canEditOrders: true,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  purchase_assistant: {
    id: 'purchase_assistant',
    title: 'Purchase Assistant',
    category: 'OFFICE_STAFF',
    defaultRole: 'PA',
    department: 'Raw Material Supply',
    allowedViews: ['dashboard', 'purchasing', 'stock', 'expenses'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: true,
    canManageTeam: false,
    canViewAccounting: false,
  },
  stock_manager: {
    id: 'stock_manager',
    title: 'Stock Manager',
    category: 'OFFICE_STAFF',
    defaultRole: 'MANAGER',
    department: 'Warehouse & Inventory',
    allowedViews: ['dashboard', 'stock', 'purchasing', 'production', 'reports'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: true,
    canManageTeam: false,
    canViewAccounting: false,
  },
  production_manager: {
    id: 'production_manager',
    title: 'Production Manager',
    category: 'OFFICE_STAFF',
    defaultRole: 'MANAGER',
    department: 'Plant Operations',
    allowedViews: ['dashboard', 'production', 'packaging', 'quality', 'stock', 'approvals', 'reports'],
    canEditProduction: true,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: true,
    canViewAccounting: false,
  },
  accountant: {
    id: 'accountant',
    title: 'Accountant',
    category: 'OFFICE_STAFF',
    defaultRole: 'ACCOUNTANT',
    department: 'Accounts & Finance',
    allowedViews: ['dashboard', 'accounting', 'expenses', 'sales', 'salary', 'reports', 'audit'],
    canEditProduction: false,
    canEditOrders: true,
    canBuyMaterials: true,
    canManageTeam: false,
    canViewAccounting: true,
  },
  personal_assistant: {
    id: 'personal_assistant',
    title: 'Personal Assistant (PA)',
    category: 'OFFICE_STAFF',
    defaultRole: 'PA',
    department: 'Executive Operations',
    allowedViews: [
      'dashboard',
      'sales',
      'customers',
      'production',
      'stock',
      'attendance',
      'approvals',
      'reports',
      'purchasing',
      'packaging',
      'expenses',
      'visits',
      'closing',
      'workforce',
    ],
    canEditProduction: true,
    canEditOrders: true,
    canBuyMaterials: true,
    canManageTeam: true,
    canViewAccounting: false,
  },
  ecommerce_manager: {
    id: 'ecommerce_manager',
    title: 'E-Commerce Manager',
    category: 'OFFICE_STAFF',
    defaultRole: 'ECOMMERCE_MANAGER',
    department: 'Online Fulfillment',
    allowedViews: ['dashboard', 'sales', 'customers', 'stock', 'workforce'],
    canEditProduction: false,
    canEditOrders: true,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },

  // 3. Field Staff
  salesman: {
    id: 'salesman',
    title: 'Field Salesman',
    category: 'FIELD_STAFF',
    defaultRole: 'SALESMAN',
    department: 'Field Sales',
    allowedViews: ['dashboard', 'sales', 'customers', 'visits', 'stock', 'expenses', 'closing', 'workforce'],
    canEditProduction: false,
    canEditOrders: true,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  delivery_staff: {
    id: 'delivery_staff',
    title: 'Delivery Staff',
    category: 'FIELD_STAFF',
    defaultRole: 'SALESMAN',
    department: 'Distribution',
    allowedViews: ['dashboard', 'sales', 'customers', 'stock', 'closing'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  payment_collector: {
    id: 'payment_collector',
    title: 'Payment Collector',
    category: 'FIELD_STAFF',
    defaultRole: 'SALESMAN',
    department: 'Field Collections',
    allowedViews: ['dashboard', 'customers', 'closing', 'expenses'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  marketing_rep: {
    id: 'marketing_rep',
    title: 'Marketing Representative',
    category: 'FIELD_STAFF',
    defaultRole: 'SOCIAL_MEDIA_MANAGER',
    department: 'Marketing & Retail',
    allowedViews: ['dashboard', 'visits', 'workforce', 'customers'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },
  freelancer: {
    id: 'freelancer',
    title: 'Freelance Specialist',
    category: 'FIELD_STAFF',
    defaultRole: 'FREELANCER',
    department: 'Design & Media',
    allowedViews: ['dashboard', 'workforce'],
    canEditProduction: false,
    canEditOrders: false,
    canBuyMaterials: false,
    canManageTeam: false,
    canViewAccounting: false,
  },

  // 4. Executive
  owner: {
    id: 'owner',
    title: 'Business Owner / MD',
    category: 'ADMINISTRATIVE',
    defaultRole: 'OWNER',
    department: 'Executive Management',
    allowedViews: [
      'dashboard',
      'sales',
      'customers',
      'production',
      'stock',
      'attendance',
      'accounting',
      'approvals',
      'reports',
      'users',
      'audit',
      'purchasing',
      'packaging',
      'quality',
      'expenses',
      'visits',
      'closing',
      'salary',
      'workforce',
      'products',
    ],
    canEditProduction: true,
    canEditOrders: true,
    canBuyMaterials: true,
    canManageTeam: true,
    canViewAccounting: true,
  },
};

/**
 * Derives the Employee Category from user role and explicit category field.
 */
export function resolveEmployeeCategory(role?: string | null, explicitCategory?: string | null): EmployeeCategory {
  if (explicitCategory) {
    const normCat = explicitCategory.trim().toUpperCase();
    if (normCat.includes('FACTORY')) return 'FACTORY_WORKERS';
    if (normCat.includes('FIELD')) return 'FIELD_STAFF';
    if (normCat.includes('OFFICE')) return 'OFFICE_STAFF';
    if (normCat.includes('ADMIN') || normCat.includes('OWNER')) return 'ADMINISTRATIVE';
  }

  const normRole = String(role || '').trim().toUpperCase();
  if (normRole === 'OWNER' || normRole === 'OWNER_ADMIN' || normRole === 'ADMIN') {
    return 'ADMINISTRATIVE';
  }
  if (
    normRole === 'FACTORY_WORKER' ||
    normRole === 'PRODUCTION_WORKER' ||
    normRole === 'WORKER' ||
    normRole === 'OPERATOR' ||
    normRole === 'PRODUCTION' ||
    normRole === 'DISPATCH' ||
    normRole === 'LABOUR_SUPERVISOR' ||
    normRole === 'SUPERVISOR'
  ) {
    return 'FACTORY_WORKERS';
  }
  if (
    normRole === 'SALESMAN' ||
    normRole === 'FIELD_SALESMAN' ||
    normRole === 'FREELANCER' ||
    normRole === 'SOCIAL_MEDIA_MANAGER' ||
    normRole === 'SOCIAL_MEDIA_ECOMMERCE_MANAGER'
  ) {
    return 'FIELD_STAFF';
  }
  return 'OFFICE_STAFF';
}

/**
 * Human-readable category title
 */
export function getCategoryTitle(cat: EmployeeCategory): string {
  switch (cat) {
    case 'FACTORY_WORKERS':
      return 'Factory Worker';
    case 'FIELD_STAFF':
      return 'Field Staff';
    case 'OFFICE_STAFF':
      return 'Office Staff';
    case 'ADMINISTRATIVE':
      return 'Business Owner';
  }
}
