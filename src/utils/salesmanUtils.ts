/**
 * Kawad Swad ERP - Field Sales Utilities & Pricing Engine
 * Preserves validated business logic, pricing tiers, customer debt calculation, and follow-up metrics.
 */

import { Product, CustomerType, Sale, Payment, ShopVisit, Customer, Expense, DailyClosing } from '../types';

export const PAYMENT_METHODS: Array<{
  method: 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER';
  label: string;
  hindiLabel: string;
  icon: string;
}> = [
  { method: 'CASH', label: 'Cash', hindiLabel: 'Rokda / Cash', icon: '💵' },
  { method: 'UPI', label: 'UPI / QR', hindiLabel: 'PhonePe / GPay', icon: '📱' },
  { method: 'BANK_TRANSFER', label: 'Bank Transfer', hindiLabel: 'Khata Transfer', icon: '🏦' },
  { method: 'OTHER', label: 'Other Approved', hindiLabel: 'Anya Madh', icon: '💳' },
];

export const COMMON_VISIT_OUTCOMES = [
  { id: 'ORDER_PLACED', label: 'Order Placed', hindi: 'Order Liya', color: 'emerald' },
  { id: 'STOCK_FULL', label: 'Stock Full / No Req', hindi: 'Maal Bhara Hai', color: 'slate' },
  { id: 'PAYMENT_FOLLOWUP', label: 'Payment Follow-up', hindi: 'Paisa Vasooli', color: 'amber' },
  { id: 'SHOP_CLOSED', label: 'Shop Closed / Absent', hindi: 'Dukaan Band', color: 'red' },
  { id: 'SAMPLE_GIVEN', label: 'Sample / Rate Inquiry', hindi: 'Sample Diya / Rate Poocha', color: 'blue' },
];

export const EXPENSE_CATEGORIES: Array<{
  key: 'TRAVEL' | 'DELIVERY' | 'OTHER' | 'DIGITAL';
  label: string;
  hindiLabel: string;
  icon: string;
  presets: number[];
}> = [
  { key: 'TRAVEL', label: 'Bike Petrol / Fuel', hindiLabel: 'Gaadi Ka Petrol', icon: '⛽', presets: [100, 150, 200, 300] },
  { key: 'DELIVERY', label: 'Cartage / Auto Delivery', hindiLabel: 'Auto / Tempo Bhada', icon: '🛺', presets: [50, 100, 150, 250] },
  { key: 'OTHER', label: 'Tea / Refreshment', hindiLabel: 'Chai / Nashta', icon: '🍛', presets: [30, 50, 100, 150] },
  { key: 'DIGITAL', label: 'Packing Tape / Mobile', hindiLabel: 'Tape / Phone Kharch', icon: '📝', presets: [50, 100, 200] },
];

/**
 * Standard baseline product price according to pack weight and wholesale tier.
 * Preserves validated Kawad Swad pricing formulas.
 */
export const getDefaultPriceForProduct = (p?: Product, saleType?: CustomerType): number => {
  if (!p) return 50;
  const weight = p.pack_weight_g || 200;
  let basePrice = 50;
  if (weight <= 200) basePrice = 50;
  else if (weight <= 250) basePrice = 60;
  else if (weight <= 500) basePrice = 110;
  else if (weight <= 1000) basePrice = 210;
  else basePrice = Math.round(weight * 0.22);

  // Slight wholesale/distributor adjustment if applicable
  if (saleType === 'WHOLESALER') return Math.max(10, Math.round(basePrice * 0.9));
  if (saleType === 'DISTRIBUTOR') return Math.max(10, Math.round(basePrice * 0.85));
  return basePrice;
};

/**
 * Calculates total unpaid / outstanding balance for a given customer from sales and payments.
 */
export interface CustomerDebtSummary {
  outstandingBalance: number;
  unpaidBillsCount: number;
  unpaidSales: Array<{
    sale: Sale;
    totalAmount: number;
    amountPaid: number;
    remainingDue: number;
  }>;
}

export function calculateCustomerDebt(
  customerId: string,
  sales: Sale[],
  payments: Payment[]
): CustomerDebtSummary {
  if (!customerId || customerId === 'CUS-WALKIN') {
    return { outstandingBalance: 0, unpaidBillsCount: 0, unpaidSales: [] };
  }

  const customerSales = sales.filter(
    (s) => s.customer_id === customerId && s.bill_status === 'ISSUED'
  );

  const unpaidSales: CustomerDebtSummary['unpaidSales'] = [];
  let totalOutstanding = 0;

  for (const sale of customerSales) {
    const salePayments = payments.filter((p) => p.sale_id === sale.sale_id);
    const amountPaid = salePayments.reduce((sum, p) => sum + (Number(p.amount) || 0), 0);
    const totalAmount = Number(sale.bill_total) || 0;
    const remainingDue = Math.max(0, totalAmount - amountPaid);

    const isExplicitlyUnpaid = sale.payment_status === 'UNPAID';
    if (remainingDue > 0.01 && (isExplicitlyUnpaid || salePayments.length > 0)) {
      totalOutstanding += remainingDue;
      unpaidSales.push({
        sale,
        totalAmount,
        amountPaid,
        remainingDue,
      });
    }
  }

  return {
    outstandingBalance: Math.round(totalOutstanding * 100) / 100,
    unpaidBillsCount: unpaidSales.length,
    unpaidSales,
  };
}

/**
 * Retrieves the last order, last payment, and last shop visit for a customer.
 */
export function getCustomerInteractionHistory(
  customerId: string,
  sales: Sale[],
  payments: Payment[],
  shopVisits: ShopVisit[]
) {
  const customerSales = sales
    .filter((s) => s.customer_id === customerId && s.bill_status === 'ISSUED')
    .sort((a, b) => new Date(b.sale_datetime).getTime() - new Date(a.sale_datetime).getTime());

  const lastOrder = customerSales[0] || null;

  const customerSaleIds = new Set(customerSales.map((s) => s.sale_id));
  const customerPayments = payments
    .filter((p) => customerSaleIds.has(p.sale_id))
    .sort((a, b) => new Date(b.payment_datetime).getTime() - new Date(a.payment_datetime).getTime());

  const lastPayment = customerPayments[0] || null;

  const customerVisits = shopVisits
    .filter((v) => v.customer_id === customerId)
    .sort((a, b) => new Date(b.visit_datetime).getTime() - new Date(a.visit_datetime).getTime());

  const lastVisit = customerVisits[0] || null;

  return { lastOrder, lastPayment, lastVisit };
}

/**
 * Generates quick follow-up date strings for shop visits.
 */
export function getFollowUpPresets(): Array<{ label: string; hindi: string; date: string }> {
  const now = new Date();

  const addDays = (days: number) => {
    const d = new Date(now);
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  };

  return [
    { label: 'Tomorrow', hindi: 'Kal', date: addDays(1) },
    { label: 'After 3 Days', hindi: '3 Din Baad', date: addDays(3) },
    { label: 'Next Week', hindi: 'Agle Hafte', date: addDays(7) },
  ];
}

/**
 * Checks whether a given date is today or overdue.
 */
export function isDateTodayOrOverdue(dateStr?: string | null): boolean {
  if (!dateStr) return false;
  const todayStr = new Date().toISOString().slice(0, 10);
  return dateStr <= todayStr;
}
