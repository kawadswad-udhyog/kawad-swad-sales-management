/**
 * Cleaned Initial State Constants for Kawad Swad Udhyog ERP (Blueprint v2.1).
 * Fake production data and non-standard 250g/400g SKUs have been removed.
 * Authoritative business records are loaded live from the FastAPI backend + Google Sheets.
 * Unconnected or failed storage fails closed with empty arrays/null rather than seeded mock records.
 */
import {
  User,
  Product,
  Customer,
  Sale,
  SaleItem,
  Payment,
  StockTransaction,
  Expense,
  ShopVisit,
  DailyClosing,
  SalaryIncentive,
  AuditLog,
  DashboardMetrics,
} from '../types';

export const INITIAL_USERS: User[] = [];
export const INITIAL_PRODUCTS: Product[] = [];
export const INITIAL_CUSTOMERS: Customer[] = [];
export const INITIAL_SALES: Sale[] = [];
export const INITIAL_SALE_ITEMS: SaleItem[] = [];
export const INITIAL_PAYMENTS: Payment[] = [];
export const INITIAL_STOCK_TRANSACTIONS: StockTransaction[] = [];
export const INITIAL_EXPENSES: Expense[] = [];
export const INITIAL_SHOP_VISITS: ShopVisit[] = [];
export const INITIAL_DAILY_CLOSINGS: DailyClosing[] = [];
export const INITIAL_SALARY_INCENTIVES: SalaryIncentive[] = [];
export const INITIAL_AUDIT_LOGS: AuditLog[] = [];
export const INITIAL_DASHBOARD_METRICS: DashboardMetrics | null = null;
