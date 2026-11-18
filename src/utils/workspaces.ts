import React from 'react';
import { ViewType } from '../components/Navigation';
import { UserRole } from '../types';
import { resolveEmployeeCategory, EmployeeCategory } from './permissions';

export type WorkspaceId =
  | 'owner'
  | 'pa'
  | 'accounts'
  | 'procurement'
  | 'store'
  | 'production'
  | 'quality'
  | 'packaging'
  | 'sales'
  | 'field_salesman'
  | 'hr'
  | 'auditor'
  | 'manager'
  | 'salesman'
  | 'factory'
  | 'employee'
  | 'labour_supervisor'
  | 'accountant'
  | 'freelancer'
  | 'marketing'
  | 'ecommerce';

export interface WorkspaceConfig {
  id: WorkspaceId;
  title: string;
  subtitle: string;
  roleBadge: string;
  category: EmployeeCategory;
  allowedViews: ViewType[];
  defaultView: ViewType;
}

export interface NavItemConfig {
  view: ViewType;
  label: string;
  hindiLabel?: string;
  description: string;
  group: 'main' | 'operations' | 'management' | 'system';
}

/**
 * Standard plain business navigation labels translating legacy ERP terms
 * into clear, operational everyday language.
 */
export const ALL_NAV_ITEMS: Record<ViewType, NavItemConfig> = {
  dashboard: {
    view: 'dashboard',
    label: 'Home',
    hindiLabel: 'Mukhya Page',
    description: 'Dashboard & daily priorities',
    group: 'main',
  },
  workforce: {
    view: 'workforce',
    label: 'Our Team',
    hindiLabel: 'Hamari Team',
    description: 'Staff, tasks & attendance',
    group: 'main',
  },
  sales: {
    view: 'sales',
    label: 'Orders & Bills',
    hindiLabel: 'Order Aur Bill',
    description: 'Sales orders & customer billing',
    group: 'operations',
  },
  customers: {
    view: 'customers',
    label: 'Customers',
    hindiLabel: 'Grahak',
    description: 'Customer directory & balances',
    group: 'operations',
  },
  production: {
    view: 'production',
    label: 'Production',
    hindiLabel: 'Utpadan',
    description: 'Batches, recipes & output',
    group: 'operations',
  },
  stock: {
    view: 'stock',
    label: 'Stock',
    hindiLabel: 'Maal Ka Stock',
    description: 'Inventory & warehouse items',
    group: 'operations',
  },
  attendance: {
    view: 'attendance',
    label: 'Attendance',
    hindiLabel: 'Rozana Haaziri',
    description: 'Daily check-in & wages',
    group: 'operations',
  },
  accounting: {
    view: 'accounting',
    label: 'Money Records',
    hindiLabel: 'Khata Vahi',
    description: 'Accounts, payments & ledger',
    group: 'management',
  },
  approvals: {
    view: 'approvals',
    label: 'Approvals',
    hindiLabel: 'Manzoori',
    description: 'Pending production & expenses',
    group: 'management',
  },
  reports: {
    view: 'reports',
    label: 'Reports',
    hindiLabel: 'Report',
    description: 'Sales & production reports',
    group: 'management',
  },
  users: {
    view: 'users',
    label: 'Team Access',
    hindiLabel: 'Staff Permissions',
    description: 'Staff & permissions',
    group: 'management',
  },
  audit: {
    view: 'audit',
    label: 'System Settings',
    hindiLabel: 'Settings',
    description: 'System health & diagnostics',
    group: 'system',
  },
  // Sub-modules with plain-language labels
  purchasing: {
    view: 'purchasing',
    label: 'Buy Materials',
    hindiLabel: 'Saaman Khareed',
    description: 'Raw materials & suppliers',
    group: 'operations',
  },
  packaging: {
    view: 'packaging',
    label: 'Packaging',
    hindiLabel: 'Packing',
    description: 'Bulk to finished goods packing',
    group: 'operations',
  },
  quality: {
    view: 'quality',
    label: 'Quality Check',
    hindiLabel: 'Gunvatta Jaanch',
    description: 'Quality checks & batch tests',
    group: 'operations',
  },
  expenses: {
    view: 'expenses',
    label: 'Daily Expenses',
    hindiLabel: 'Rozana Kharch',
    description: 'Claims & operational expenses',
    group: 'management',
  },
  visits: {
    view: 'visits',
    label: 'Shop Visits',
    hindiLabel: 'Dukaan Visit',
    description: 'Store interaction register',
    group: 'operations',
  },
  closing: {
    view: 'closing',
    label: 'Daily Cash Handover',
    hindiLabel: 'Din Ka Cash Jama',
    description: 'Cash handover & register closing',
    group: 'management',
  },
  products: {
    view: 'products',
    label: 'Product Rates',
    hindiLabel: 'Item Rate List',
    description: 'Product catalogue & wholesale rates',
    group: 'operations',
  },
  salary: {
    view: 'salary',
    label: 'Salary & Wages',
    hindiLabel: 'Tankhwah / Mazdoori',
    description: 'Salary calculations & payouts',
    group: 'management',
  },
  logistics: {
    view: 'logistics',
    label: 'Logistics & Van Dispatch',
    hindiLabel: 'Gaadi & Dispatch',
    description: 'Van routes, dispatch & delivery',
    group: 'operations',
  },
  channels: {
    view: 'channels',
    label: 'E-Commerce & Channels',
    hindiLabel: 'Online Bazaar',
    description: 'Amazon, Flipkart & distributor settlements',
    group: 'operations',
  },
  compliance_assets: {
    view: 'compliance_assets',
    label: 'Compliance & Assets',
    hindiLabel: 'FSSAI & Machine',
    description: 'Statutory licenses & factory maintenance',
    group: 'management',
  },
  control_policies: {
    view: 'control_policies',
    label: 'Control & CA Policies',
    hindiLabel: 'Niyam & Registry',
    description: '255-tab schema, 32 prefixes & CA policies',
    group: 'system',
  },
};

/**
 * Workspace definitions mapping each backend role & category to its primary workspace
 */
export const WORKSPACES: Record<WorkspaceId, WorkspaceConfig> = {
  owner: {
    id: 'owner',
    title: 'Business Overview',
    subtitle: 'Executive overview of all 15 ERP groups, policies & governed writes',
    roleBadge: 'OWNER_ADMIN',
    category: 'ADMINISTRATIVE',
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
      'logistics',
      'channels',
      'compliance_assets',
      'control_policies',
    ],
    defaultView: 'dashboard',
  },
  pa: {
    id: 'pa',
    title: 'Daily Operations',
    subtitle: 'Operational orchestration without confidential salary/bank access',
    roleBadge: 'PA',
    category: 'OFFICE_STAFF',
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
      'quality',
      'expenses',
      'visits',
      'closing',
      'workforce',
      'logistics',
      'channels',
      'compliance_assets',
    ],
    defaultView: 'dashboard',
  },
  accounts: {
    id: 'accounts',
    title: 'Accounts & Finance',
    subtitle: 'General ledger, payments, GST, trial balance & approved advances',
    roleBadge: 'ACCOUNTS',
    category: 'OFFICE_STAFF',
    allowedViews: [
      'dashboard',
      'accounting',
      'expenses',
      'sales',
      'purchasing',
      'channels',
      'reports',
      'closing',
      'control_policies',
    ],
    defaultView: 'dashboard',
  },
  procurement: {
    id: 'procurement',
    title: 'Procurement & Vendors',
    subtitle: 'Raw materials, suppliers, POs, GRNs & supplier bills',
    roleBadge: 'PROCUREMENT',
    category: 'OFFICE_STAFF',
    allowedViews: ['dashboard', 'purchasing', 'stock', 'quality', 'products'],
    defaultView: 'purchasing',
  },
  store: {
    id: 'store',
    title: 'Store & Warehouse',
    subtitle: 'Warehouse stock, RM/FG balances, van loading & dispatches',
    roleBadge: 'STORE',
    category: 'FACTORY_WORKERS',
    allowedViews: ['dashboard', 'stock', 'purchasing', 'packaging', 'logistics', 'products'],
    defaultView: 'stock',
  },
  production: {
    id: 'production',
    title: 'Production Floor',
    subtitle: 'Milling, dough batches, cooking, output & factory muster roll',
    roleBadge: 'PRODUCTION',
    category: 'FACTORY_WORKERS',
    allowedViews: ['dashboard', 'production', 'attendance', 'stock', 'quality', 'compliance_assets'],
    defaultView: 'production',
  },
  quality: {
    id: 'quality',
    title: 'Quality Assurance (QC)',
    subtitle: 'Lot quarantine/release gates, IPQC/FGQC inspections & recalls',
    roleBadge: 'QUALITY',
    category: 'FACTORY_WORKERS',
    allowedViews: ['dashboard', 'quality', 'production', 'packaging', 'compliance_assets', 'reports'],
    defaultView: 'quality',
  },
  packaging: {
    id: 'packaging',
    title: 'Packaging Desk',
    subtitle: '200g / 500g / 1000g retail packing on RELEASED lots only',
    roleBadge: 'PACKAGING',
    category: 'FACTORY_WORKERS',
    allowedViews: ['dashboard', 'packaging', 'production', 'stock', 'quality', 'products'],
    defaultView: 'packaging',
  },
  sales: {
    id: 'sales',
    title: 'Sales & Channels',
    subtitle: 'B2B orders, retail billing, logistics & marketplace settlements',
    roleBadge: 'SALES',
    category: 'OFFICE_STAFF',
    allowedViews: ['dashboard', 'sales', 'customers', 'products', 'stock', 'logistics', 'channels', 'reports'],
    defaultView: 'sales',
  },
  field_salesman: {
    id: 'field_salesman',
    title: 'Field Sales Mobile',
    subtitle: 'Mobile billing, van stock, shop visits & daily cash handover',
    roleBadge: 'FIELD_SALESMAN',
    category: 'FIELD_STAFF',
    allowedViews: ['dashboard', 'sales', 'customers', 'visits', 'stock', 'expenses', 'closing'],
    defaultView: 'sales',
  },
  hr: {
    id: 'hr',
    title: 'HR & Workforce',
    subtitle: 'Attendance, gig worker verification & non-confidential staff ops',
    roleBadge: 'HR',
    category: 'OFFICE_STAFF',
    allowedViews: ['dashboard', 'workforce', 'attendance', 'reports'],
    defaultView: 'workforce',
  },
  auditor: {
    id: 'auditor',
    title: 'Internal Audit (Read-Only)',
    subtitle: 'Read-only access to audit trails, exceptions, reports & ledger',
    roleBadge: 'AUDITOR',
    category: 'OFFICE_STAFF',
    allowedViews: ['dashboard', 'reports', 'accounting', 'stock', 'quality', 'control_policies', 'audit'],
    defaultView: 'reports',
  },
  manager: {
    id: 'manager',
    title: 'Operations & Approvals',
    subtitle: 'Production monitoring, inventory controls & pending reviews',
    roleBadge: 'Operations Manager',
    category: 'OFFICE_STAFF',
    allowedViews: [
      'dashboard',
      'production',
      'stock',
      'attendance',
      'approvals',
      'quality',
      'packaging',
      'purchasing',
      'reports',
      'workforce',
    ],
    defaultView: 'dashboard',
  },
  salesman: {
    id: 'salesman',
    title: 'My Sales',
    subtitle: 'Field orders, store visits, customer billing & cash handover',
    roleBadge: 'Field Sales',
    category: 'FIELD_STAFF',
    allowedViews: [
      'dashboard',
      'sales',
      'customers',
      'visits',
      'stock',
      'expenses',
      'closing',
      'workforce',
    ],
    defaultView: 'dashboard',
  },
  factory: {
    id: 'factory',
    title: 'Factory Work',
    subtitle: 'Production batches, packaging, materials & daily attendance',
    roleBadge: 'Factory Worker',
    category: 'FACTORY_WORKERS',
    allowedViews: [
      'dashboard',
      'attendance',
      'production',
      'packaging',
      'quality',
      'stock',
    ],
    defaultView: 'dashboard',
  },
  employee: {
    id: 'employee',
    title: 'My Work',
    subtitle: 'Personal attendance, assigned tasks, salary & profile',
    roleBadge: 'Office Staff',
    category: 'OFFICE_STAFF',
    allowedViews: ['dashboard', 'workforce', 'attendance'],
    defaultView: 'dashboard',
  },
  labour_supervisor: {
    id: 'labour_supervisor',
    title: 'Labour & Attendance',
    subtitle: 'Labour muster roll, daily piecework & wage verification',
    roleBadge: 'Factory Supervisor',
    category: 'FACTORY_WORKERS',
    allowedViews: ['dashboard', 'attendance', 'workforce', 'production', 'packaging', 'stock'],
    defaultView: 'dashboard',
  },
  accountant: {
    id: 'accountant',
    title: 'Accounts & Payments',
    subtitle: 'Money records, payments, expenses, receivables & reconciliation',
    roleBadge: 'Accountant',
    category: 'OFFICE_STAFF',
    allowedViews: [
      'dashboard',
      'accounting',
      'expenses',
      'sales',
      'salary',
      'reports',
      'audit',
    ],
    defaultView: 'dashboard',
  },
  freelancer: {
    id: 'freelancer',
    title: 'My Projects',
    subtitle: 'Assigned design projects, milestone deliveries & invoices',
    roleBadge: 'Freelance Partner',
    category: 'FIELD_STAFF',
    allowedViews: ['dashboard', 'workforce'],
    defaultView: 'dashboard',
  },
  marketing: {
    id: 'marketing',
    title: 'Marketing Tasks',
    subtitle: 'Social media campaigns, promotions & marketing deliverables',
    roleBadge: 'Marketing Representative',
    category: 'FIELD_STAFF',
    allowedViews: ['dashboard', 'workforce', 'visits', 'customers'],
    defaultView: 'dashboard',
  },
  ecommerce: {
    id: 'ecommerce',
    title: 'Online Orders',
    subtitle: 'E-commerce marketplace orders, dispatches & customer queries',
    roleBadge: 'E-Commerce Manager',
    category: 'OFFICE_STAFF',
    allowedViews: ['dashboard', 'sales', 'customers', 'stock', 'workforce'],
    defaultView: 'dashboard',
  },
};

/**
 * Maps any backend user role to the appropriate workspace.
 * Always returns a valid workspace, ensuring navigation is never empty!
 */
export function getWorkspaceForRole(role?: string | null): WorkspaceConfig {
  const norm = String(role || '').trim().toUpperCase();

  switch (norm) {
    case 'OWNER':
    case 'OWNER_ADMIN':
    case 'ADMIN':
      return WORKSPACES.owner;

    case 'PA':
    case 'PERSONAL_ASSISTANT':
      return WORKSPACES.pa;

    case 'ACCOUNTS':
    case 'ACCOUNTANT':
    case 'FINANCE':
      return WORKSPACES.accounts;

    case 'PROCUREMENT':
    case 'PURCHASE':
      return WORKSPACES.procurement;

    case 'STORE':
    case 'STOREKEEPER':
    case 'WAREHOUSE':
    case 'DISPATCH':
      return WORKSPACES.store;

    case 'PRODUCTION':
    case 'FACTORY_WORKER':
    case 'PRODUCTION_WORKER':
    case 'WORKER':
    case 'OPERATOR':
      return WORKSPACES.production;

    case 'QUALITY':
    case 'QC':
      return WORKSPACES.quality;

    case 'PACKAGING':
    case 'PACKING':
      return WORKSPACES.packaging;

    case 'SALES':
      return WORKSPACES.sales;

    case 'SALESMAN':
    case 'FIELD_SALESMAN':
      return WORKSPACES.field_salesman;

    case 'HR':
      return WORKSPACES.hr;

    case 'AUDITOR':
      return WORKSPACES.auditor;

    case 'MANAGER':
    case 'OPERATIONS_MANAGER':
      return WORKSPACES.manager;

    case 'LABOUR_SUPERVISOR':
    case 'SUPERVISOR':
      return WORKSPACES.labour_supervisor;

    case 'FREELANCER':
      return WORKSPACES.freelancer;

    case 'SOCIAL_MEDIA_MANAGER':
      return WORKSPACES.marketing;

    case 'ECOMMERCE_MANAGER':
      return WORKSPACES.ecommerce;

    case 'SOCIAL_MEDIA_ECOMMERCE_MANAGER':
      return WORKSPACES.marketing;

    case 'EMPLOYEE':
    default:
      return WORKSPACES.employee;
  }
}

/**
 * Filter the allowed navigation items for a workspace
 */
export function getNavItemsForWorkspace(config: WorkspaceConfig): NavItemConfig[] {
  return config.allowedViews
    .map((view) => ALL_NAV_ITEMS[view])
    .filter((item): item is NavItemConfig => Boolean(item));
}

/**
 * Resolves human-readable category badge for display in headers and user badges
 */
export function getCategoryBadge(workspaceId: WorkspaceId): { label: string; bgClass: string } {
  const ws = WORKSPACES[workspaceId];
  const cat = ws?.category || 'OFFICE_STAFF';
  switch (cat) {
    case 'FACTORY_WORKERS':
      return { label: 'Factory Worker', bgClass: 'bg-amber-100 text-amber-800 border-amber-200' };
    case 'FIELD_STAFF':
      return { label: 'Field Staff', bgClass: 'bg-blue-100 text-blue-800 border-blue-200' };
    case 'OFFICE_STAFF':
      return { label: 'Office Staff', bgClass: 'bg-emerald-100 text-emerald-800 border-emerald-200' };
    case 'ADMINISTRATIVE':
      return { label: 'Owner / Admin', bgClass: 'bg-purple-100 text-purple-800 border-purple-200' };
  }
}
