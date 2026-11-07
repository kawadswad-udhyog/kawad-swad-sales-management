import React, { useMemo } from 'react';
import { Customer, Sale, Payment, ShopVisit, SalesmanStockItem } from '../../types';
import {
  calculateCustomerDebt,
  getCustomerInteractionHistory,
} from '../../utils/salesmanUtils';
import {
  Store,
  Phone,
  MapPin,
  Clock,
  ArrowRight,
  ShoppingCart,
  Receipt,
  MapPinned,
  CheckCircle2,
  AlertCircle,
  Boxes,
  MessageCircle,
} from 'lucide-react';

interface SmartCustomerCardProps {
  customer: Customer;
  sales: Sale[];
  payments: Payment[];
  shopVisits: ShopVisit[];
  salesmanStock?: SalesmanStockItem[];
  onTakeOrder: (customer: Customer) => void;
  onCollectPayment: (customer: Customer) => void;
  onVisitShop: (customer: Customer) => void;
  onViewHistory?: (customer: Customer) => void;
}

export const SmartCustomerCard: React.FC<SmartCustomerCardProps> = ({
  customer,
  sales,
  payments,
  shopVisits,
  salesmanStock = [],
  onTakeOrder,
  onCollectPayment,
  onVisitShop,
  onViewHistory,
}) => {
  // Compute debt and history
  const debt = useMemo(
    () => calculateCustomerDebt(customer.customer_id, sales, payments),
    [customer.customer_id, sales, payments]
  );

  const history = useMemo(
    () => getCustomerInteractionHistory(customer.customer_id, sales, payments, shopVisits),
    [customer.customer_id, sales, payments, shopVisits]
  );

  // Available total packets in salesman van
  const totalVanPackets = useMemo(
    () => salesmanStock.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0),
    [salesmanStock]
  );

  const cleanPhone = (customer.mobile || '').replace(/\D/g, '').slice(-10);

  return (
    <div className="bg-white border border-[#E7E2D6] rounded-2xl p-4 sm:p-5 shadow-xs transition-all hover:border-emerald-300">
      {/* Top Row: Shop Name & Customer Type */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight truncate m-0">
              {customer.shop_name}
            </h3>
            <span
              className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${
                customer.customer_type === 'DISTRIBUTOR'
                  ? 'bg-purple-100 text-purple-800'
                  : customer.customer_type === 'WHOLESALER'
                  ? 'bg-blue-100 text-blue-800'
                  : 'bg-emerald-100 text-emerald-800'
              }`}
            >
              {customer.customer_type || 'RETAILER'}
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-500 mt-1">
            <span className="flex items-center gap-1">
              <MapPin size={13} className="text-slate-400 shrink-0" />
              <span className="truncate">
                {customer.locality_area || customer.city || 'Local Market'}
                {customer.city && customer.locality_area ? `, ${customer.city}` : ''}
              </span>
            </span>
            {customer.shopkeeper_name && (
              <>
                <span className="text-slate-300">·</span>
                <span className="text-slate-600 truncate">{customer.shopkeeper_name}</span>
              </>
            )}
          </div>
        </div>

        {/* Outstanding Balance Badge */}
        <div className="text-right shrink-0">
          {debt.outstandingBalance > 0 ? (
            <div className="bg-amber-50 border border-amber-200 text-amber-900 px-2.5 py-1 rounded-xl text-right">
              <div className="text-[10px] font-bold uppercase tracking-wider text-amber-700">
                Balance Due
              </div>
              <div className="text-sm font-black font-mono text-amber-900">
                ₹{debt.outstandingBalance.toLocaleString('en-IN')}
              </div>
            </div>
          ) : (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-2.5 py-1 rounded-xl text-right">
              <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-700">
                Balance
              </div>
              <div className="text-xs font-bold text-emerald-800 flex items-center gap-1 justify-end">
                <CheckCircle2 size={12} />
                <span>Cleared</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Contact Quick Triggers (Phone & WhatsApp) */}
      {cleanPhone.length === 10 && (
        <div className="flex items-center gap-2 mt-3 pt-2.5 border-t border-slate-100">
          <a
            href={`tel:+91${cleanPhone}`}
            className="flex-1 inline-flex items-center justify-center gap-1.5 py-1.5 px-2 bg-slate-50 hover:bg-slate-100 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 transition-colors"
          >
            <Phone size={13} className="text-emerald-700" />
            <span>Call +91-{cleanPhone}</span>
          </a>
          <a
            href={`https://wa.me/91${cleanPhone}?text=${encodeURIComponent(
              `Namaste ${customer.shopkeeper_name || customer.shop_name}! Kawad Swad Udhyog field update.`
            )}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-1.5 py-1.5 px-3 bg-emerald-50 hover:bg-emerald-100 text-emerald-800 rounded-lg text-xs font-semibold border border-emerald-200 transition-colors"
          >
            <MessageCircle size={14} className="text-emerald-700" />
            <span>WhatsApp</span>
          </a>
        </div>
      )}

      {/* Historical Intelligence Strip */}
      <div className="grid grid-cols-3 gap-2 mt-3 p-2.5 bg-slate-50/80 rounded-xl border border-slate-100 text-[11px]">
        <div>
          <span className="text-[10px] font-semibold text-slate-400 block uppercase">Last Order</span>
          {history.lastOrder ? (
            <div className="font-medium text-slate-800 mt-0.5 truncate">
              ₹{Number(history.lastOrder.bill_total).toLocaleString('en-IN')}{' '}
              <span className="text-[10px] text-slate-400">
                ({new Date(history.lastOrder.sale_datetime).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })})
              </span>
            </div>
          ) : (
            <span className="text-slate-400 mt-0.5 block">No orders yet</span>
          )}
        </div>

        <div>
          <span className="text-[10px] font-semibold text-slate-400 block uppercase">Last Payment</span>
          {history.lastPayment ? (
            <div className="font-medium text-emerald-700 mt-0.5 truncate">
              ₹{Number(history.lastPayment.amount).toLocaleString('en-IN')}{' '}
              <span className="text-[10px] text-slate-400">
                ({new Date(history.lastPayment.payment_datetime).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })})
              </span>
            </div>
          ) : (
            <span className="text-slate-400 mt-0.5 block">No payment</span>
          )}
        </div>

        <div>
          <span className="text-[10px] font-semibold text-slate-400 block uppercase">Last Visit</span>
          {history.lastVisit ? (
            <div className="font-medium text-slate-800 mt-0.5 truncate">
              {history.lastVisit.visit_outcome}{' '}
              <span className="text-[10px] text-slate-400">
                ({new Date(history.lastVisit.visit_datetime).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })})
              </span>
            </div>
          ) : (
            <span className="text-slate-400 mt-0.5 block">No visit log</span>
          )}
        </div>
      </div>

      {/* Van Stock Availability Context */}
      <div className="flex items-center justify-between text-xs text-slate-500 mt-2.5 px-1">
        <span className="flex items-center gap-1.5 text-[11px]">
          <Boxes size={13} className="text-emerald-700" />
          <span>Van Stock: <strong>{totalVanPackets} pkts</strong> available for delivery</span>
        </span>
        {onViewHistory && (
          <button
            type="button"
            onClick={() => onViewHistory(customer)}
            className="text-[11px] font-medium text-emerald-800 hover:text-emerald-950 underline cursor-pointer"
          >
            History &rarr;
          </button>
        )}
      </div>

      {/* 3 Direct Primary Actions */}
      <div className="grid grid-cols-3 gap-2 mt-3.5 pt-3 border-t border-slate-100">
        <button
          type="button"
          onClick={() => onTakeOrder(customer)}
          className="flex flex-col items-center justify-center p-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-900 active:bg-emerald-950 text-white font-semibold shadow-xs transition-transform active:scale-98 cursor-pointer"
        >
          <ShoppingCart size={17} className="mb-1" />
          <span className="text-xs">Take Order</span>
          <span className="text-[9px] text-emerald-200 font-normal">Naya Order</span>
        </button>

        <button
          type="button"
          onClick={() => onCollectPayment(customer)}
          className={`flex flex-col items-center justify-center p-2.5 rounded-xl font-semibold shadow-xs transition-transform active:scale-98 cursor-pointer ${
            debt.outstandingBalance > 0
              ? 'bg-amber-600 hover:bg-amber-700 active:bg-amber-800 text-white'
              : 'bg-slate-100 hover:bg-slate-200 active:bg-slate-300 text-slate-700 border border-slate-200'
          }`}
        >
          <Receipt size={17} className="mb-1" />
          <span className="text-xs">Collect Pay</span>
          <span className={`text-[9px] font-normal ${debt.outstandingBalance > 0 ? 'text-amber-100' : 'text-slate-400'}`}>
            Vasooli
          </span>
        </button>

        <button
          type="button"
          onClick={() => onVisitShop(customer)}
          className="flex flex-col items-center justify-center p-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 active:bg-slate-300 text-slate-800 font-semibold border border-slate-200 shadow-xs transition-transform active:scale-98 cursor-pointer"
        >
          <MapPinned size={17} className="text-slate-600 mb-1" />
          <span className="text-xs">Visit Shop</span>
          <span className="text-[9px] text-slate-500 font-normal">Dukaan Visit</span>
        </button>
      </div>
    </div>
  );
};
