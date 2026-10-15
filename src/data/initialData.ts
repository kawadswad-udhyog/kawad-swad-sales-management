/**
 * Production Data Seeds
 * Real records are loaded dynamically from the FastAPI backend and Google Sheets.
 * Sample demonstration data has been removed to maintain data integrity.
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
