/**
 * Kawad Swad ERP - Centralized Vocabulary Dictionary
 * Translates technical accounting, procurement, and manufacturing terms into
 * plain, everyday operational language for shop-floor and office workers,
 * while preserving internal database enums and backend contracts.
 */

export interface TermDefinition {
  plain: string;
  hindi: string;
  legacy: string;
  description: string;
}

export const VOCABULARY: Record<string, TermDefinition> = {
  // Supply Chain & Purchasing
  procurement: {
    plain: 'Buy Materials',
    hindi: 'Saaman Khareed',
    legacy: 'Procurement',
    description: 'Purchase raw materials, packaging pouches and spices',
  },
  grn: {
    plain: 'Material Received',
    hindi: 'Maal Aaya / Aamad Slip',
    legacy: 'Goods Receipt Note (GRN)',
    description: 'Verify and record materials delivered by suppliers',
  },
  po: {
    plain: 'Material Order',
    hindi: 'Khareed Order',
    legacy: 'Purchase Order (PO)',
    description: 'Order placed with a supplier for materials',
  },
  vendor: {
    plain: 'Material Supplier',
    hindi: 'Maal Dene Wala Vyapari',
    legacy: 'Supplier / Vendor',
    description: 'Business or merchant supplying raw materials',
  },
  moq: {
    plain: 'Minimum Order Limit',
    hindi: 'Kam Se Kam Order',
    legacy: 'Minimum Order Quantity',
    description: 'Lowest quantity required for order placement',
  },

  // Accounting & Finance
  general_ledger: {
    plain: 'Money Records',
    hindi: 'Khata Vahi / Hisab Kitab',
    legacy: 'General Ledger',
    description: 'Complete record of all cash, bank and business payments',
  },
  accounts_receivable: {
    plain: 'Money to Receive',
    hindi: 'Aane Wala Paisa / Bakaya',
    legacy: 'Accounts Receivable (AR)',
    description: 'Money owed to Kawad Swad by customers and distributors',
  },
  accounts_payable: {
    plain: 'Money to Pay',
    hindi: 'Dena Hai / Udhaar',
    legacy: 'Accounts Payable (AP)',
    description: 'Money owed by Kawad Swad to suppliers and vendors',
  },
  sundry_debtors: {
    plain: 'Customer Balances',
    hindi: 'Grahak Ka Dena',
    legacy: 'Sundry Debtors',
    description: 'List of customers with pending balances',
  },
  sundry_creditors: {
    plain: 'Supplier Dues',
    hindi: 'Vyapari Ka Dena',
    legacy: 'Sundry Creditors',
    description: 'List of suppliers with pending payouts',
  },
  contra_voucher: {
    plain: 'Bank & Cash Transfer',
    hindi: 'Bank Aur Cash Ka Len-Den',
    legacy: 'Contra Voucher',
    description: 'Moving money between cash in hand and company bank accounts',
  },
  journal_voucher: {
    plain: 'Adjustment Entry',
    hindi: 'Hisab Sudhar Entry',
    legacy: 'Journal Voucher (JV)',
    description: 'Record non-cash adjustments, depreciation or corrections',
  },
  trial_balance: {
    plain: 'Accounts Balance Check',
    hindi: 'Khata Santulan Jaanch',
    legacy: 'Trial Balance',
    description: 'Audit summary ensuring debits match credits',
  },
  reconciliation: {
    plain: 'Match & Check',
    hindi: 'Milana Aur Jaanch',
    legacy: 'Reconciliation',
    description: 'Compare physical cash, bank statements and ledger balance',
  },

  // Inventory & Stock
  inventory: {
    plain: 'Stock',
    hindi: 'Maal Ka Stock',
    legacy: 'Inventory',
    description: 'Raw materials, packaging items and ready goods available',
  },
  variance: {
    plain: 'Difference',
    hindi: 'Farak / Anthar',
    legacy: 'Variance',
    description: 'Difference between expected output and actual physical count',
  },
  batch_recipe: {
    plain: 'Mixture Recipe',
    hindi: 'Banane Ka Formula',
    legacy: 'Batch Formulation / Recipe',
    description: 'Proportion of ingredients required to produce papad or masala',
  },
  stock_ledger: {
    plain: 'Stock History',
    hindi: 'Maal Aane Jane Ka Record',
    legacy: 'Stock Ledger / Movement',
    description: 'History of material in-and-out records',
  },

  // Workforce & Staff
  workforce: {
    plain: 'Our Team',
    hindi: 'Hamari Team / Staff',
    legacy: 'Workforce',
    description: 'Factory workers, office staff and field sales personnel',
  },
  muster_roll: {
    plain: 'Daily Attendance',
    hindi: 'Rozana Haaziri',
    legacy: 'Muster Roll',
    description: 'Daily check-in and working hours register',
  },
  payroll: {
    plain: 'Salary & Wages',
    hindi: 'Tankhwah / Mazdoori',
    legacy: 'Payroll / Disbursal',
    description: 'Monthly wages, overtime calculations and payment slips',
  },
  pro_rata: {
    plain: 'Per-Day Calculation',
    hindi: 'Dino Ke Hisab Se',
    legacy: 'Pro-rata Calculation',
    description: 'Wages computed based on actual days worked in the month',
  },
  designation: {
    plain: 'Job Role / Post',
    hindi: 'Kaam Ka Pad',
    legacy: 'Designation',
    description: 'Role assigned to an employee within their department',
  },

  // Sales & Cash Handover
  cash_closing: {
    plain: 'Daily Cash Handover',
    hindi: 'Din Ka Cash Jama',
    legacy: 'Cash Reconciliation / Closing',
    description: 'End-of-day cash handed by salesman or cashier to office',
  },
  invoice: {
    plain: 'Bill / Invoice',
    hindi: 'Pukka Bill',
    legacy: 'Tax Invoice',
    description: 'Bill issued to customer for wholesale or retail order',
  },
  delivery_challan: {
    plain: 'Delivery Slip',
    hindi: 'Maal Bhejne Ki Parchi',
    legacy: 'Delivery Challan',
    description: 'Dispatch document accompanying goods in transit',
  },
};

/**
 * Helper to fetch the plain language term with optional Hindi context.
 */
export function getTerm(key: keyof typeof VOCABULARY, includeHindi = false): string {
  const item = VOCABULARY[key];
  if (!item) return key;
  return includeHindi ? `${item.plain} (${item.hindi})` : item.plain;
}

/**
 * Money card terms for non-accounting staff.
 */
export const SIMPLE_MONEY_TERMS = {
  received: 'Money Received',
  paid: 'Money Paid',
  expenses: 'Expenses',
  remaining: 'Money Remaining (Cash in Hand)',
} as const;
