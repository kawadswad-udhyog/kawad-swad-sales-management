import React from 'react';
import { ViewType } from '../components/Navigation';
import { UserRole } from '../types';

export type WorkspaceId =
  | 'owner'
  | 'pa'
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
  allowedViews: ViewType[];
  defaultView: ViewType;
}

export interface NavItemConfig {
  view: ViewType;
  label: string;
  description: string;
  group: 'main' | 'operations' | 'management' | 'system';
}

/**
 * Standard plain English navigation labels mandated by Section 2:
 * Home, My Work, Orders, Customers, Production, Stock, Attendance, Payments, Approvals, Reports, Team, Settings
 */
export const ALL_NAV_ITEMS: Record<ViewType, NavItemConfig> = {
  dashboard: {
    view: 'dashboard',
    label: 'Home',
    description: 'Dashboard & daily priorities',
    group: 'main',
  },
  workforce: {
    view: 'workforce',
    label: 'My Work',
    description: 'Tasks, attendance & team',
    group: 'main',
  },
  sales: {
    view: 'sales',
    label: 'Orders',
    description: 'Sales orders & billing',
    group: 'operations',
  },
  customers: {
    view: 'customers',
    label: 'Customers',
    description: 'Customer directory & balances',
    group: 'operations',
  },
  production: {
    view: 'production',
    label: 'Production',
    description: 'Batches, recipes & milling',
    group: 'operations',
  },
  stock: {
    view: 'stock',
    label: 'Stock',
    description: 'Inventory & warehouse ledgers',
    group: 'operations',
  },
  attendance: {
    view: 'attendance',
    label: 'Attendance',
    description: 'Daily check-in & wages',
    group: 'operations',
  },
  accounting: {
    view: 'accounting',
    label: 'Payments',
    description: 'Accounts, expenses & ledger',
    group: 'management',
  },
  approvals: {
    view: 'approvals',
    label: 'Approvals',
    description: 'Pending production & expenses',
    group: 'management',
  },
  reports: {
    view: 'reports',
    label: 'Reports',
    description: 'Sales & production reports',
    group: 'management',
  },
  users: {
    view: 'users',
    label: 'Team',
    description: 'Staff & permissions',
    group: 'management',
  },
  audit: {
    view: 'audit',
    label: 'Settings',
    description: 'System health & diagnostics',
    group: 'system',
  },
  // Sub-modules grouped within primary navigation:
  purchasing: {
    view: 'purchasing',
    label: 'Purchasing',
    description: 'Raw materials & suppliers',
    group: 'operations',
  },
  packaging: {
    view: 'packaging',
    label: 'Packaging',
    description: 'Bulk to finished goods packing',
    group: 'operations',
  },
  quality: {
    view: 'quality',
    label: 'Quality',
    description: 'Quality checks & batch tests',
    group: 'operations',
  },
  expenses: {
    view: 'expenses',
    label: 'Expenses',
    description: 'Claims & operational expenses',
    group: 'management',
  },
  visits: {
    view: 'visits',
    label: 'Shop Visits',
    description: 'Store interaction register',
    group: 'operations',
  },
  closing: {
    view: 'closing',
    label: 'Daily Closing',
    description: 'Cash handover & closing',
    group: 'management',
  },
  products: {
    view: 'products',
    label: 'Products',
    description: 'Product catalogue & wholesale rates',
    group: 'operations',
  },
  salary: {
    view: 'salary',
    label: 'Payroll',
    description: 'Salary calculations & payouts',
    group: 'management',
  },
};

/**
 * Workspace definitions mapping each backend role to its primary workspace
 */
export const WORKSPACES: Record<WorkspaceId, WorkspaceConfig> = {
  owner: {
    id: 'owner',
    title: 'Business Overview',
    subtitle: 'Executive overview of sales, production, inventory & finances',
    roleBadge: 'Owner / Admin',
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
    ],
    defaultView: 'dashboard',
  },
  pa: {
    id: 'pa',
    title: 'Daily Operations',
    subtitle: 'Daily priorities, coordination, purchases & team workflow',
    roleBadge: 'Personal Assistant',
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
    defaultView: 'dashboard',
  },
  manager: {
    id: 'manager',
    title: 'Operations & Approvals',
    subtitle: 'Production monitoring, inventory controls & pending reviews',
    roleBadge: 'Operations Manager',
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
    subtitle: 'Field orders, store visits, customer billing & cash closing',
    roleBadge: 'Field Sales',
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
    roleBadge: 'Factory Operations',
    allowedViews: [
      'dashboard',
      'production',
      'packaging',
      'quality',
      'stock',
      'attendance',
    ],
    defaultView: 'dashboard',
  },
  employee: {
    id: 'employee',
    title: 'My Work',
    subtitle: 'Personal attendance, assigned tasks, salary & profile',
    roleBadge: 'Staff Member',
    allowedViews: ['dashboard', 'workforce', 'attendance'],
    defaultView: 'dashboard',
  },
  labour_supervisor: {
    id: 'labour_supervisor',
    title: 'Labour & Attendance',
    subtitle: 'Labour muster roll, daily piecework & wage verification',
    roleBadge: 'Labour Supervisor',
    allowedViews: ['dashboard', 'attendance', 'workforce', 'production'],
    defaultView: 'dashboard',
  },
  accountant: {
    id: 'accountant',
    title: 'Accounts & Payments',
    subtitle: 'General ledger, payments, expenses, receivables & reconciliation',
    roleBadge: 'Finance & Accounts',
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
    allowedViews: ['dashboard', 'workforce'],
    defaultView: 'dashboard',
  },
  marketing: {
    id: 'marketing',
    title: 'Marketing Tasks',
    subtitle: 'Social media campaigns, promotions & marketing deliverables',
    roleBadge: 'Social Media Manager',
    allowedViews: ['dashboard', 'workforce'],
    defaultView: 'dashboard',
  },
  ecommerce: {
    id: 'ecommerce',
    title: 'Online Orders',
    subtitle: 'E-commerce marketplace orders, dispatches & customer queries',
    roleBadge: 'E-Commerce Manager',
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

    case 'MANAGER':
    case 'OPERATIONS_MANAGER':
      return WORKSPACES.manager;

    case 'SALESMAN':
    case 'FIELD_SALESMAN':
      return WORKSPACES.salesman;

    case 'FACTORY_WORKER':
    case 'PRODUCTION_WORKER':
    case 'WORKER':
    case 'OPERATOR':
    case 'PRODUCTION':
      return WORKSPACES.factory;

    case 'DISPATCH':
      return WORKSPACES.factory;

    case 'LABOUR_SUPERVISOR':
    case 'SUPERVISOR':
      return WORKSPACES.labour_supervisor;

    case 'ACCOUNTANT':
    case 'FINANCE':
      return WORKSPACES.accountant;

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
      // Graceful default: My Work employee workspace
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
