import React, { useState, useMemo } from 'react';
import { Customer } from '../../types';
import { COMMON_VISIT_OUTCOMES, getFollowUpPresets } from '../../utils/salesmanUtils';
import {
  X,
  MapPin,
  Calendar,
  CheckCircle2,
  AlertCircle,
  ShoppingCart,
  Clock,
  FileText,
  Store,
  ChevronRight,
} from 'lucide-react';

interface ShopVisitModalProps {
  customer?: Customer | null;
  allCustomers: Customer[];
  onClose: () => void;
  onSubmitVisit: (visitData: {
    customer_id: string;
    visit_outcome: string;
    order_taken: boolean;
    follow_up_date?: string;
    next_action?: string;
    notes?: string;
  }) => Promise<boolean>;
  onProceedToOrder?: (customer: Customer) => void;
}

export const ShopVisitModal: React.FC<ShopVisitModalProps> = ({
  customer: initialCustomer,
  allCustomers,
  onClose,
  onSubmitVisit,
  onProceedToOrder,
}) => {
  const [selectedCustomerId, setSelectedCustomerId] = useState<string>(
    initialCustomer?.customer_id || allCustomers[0]?.customer_id || ''
  );
  const [customerSearch, setCustomerSearch] = useState('');
  const [outcome, setOutcome] = useState('Order Placed');
  const [orderTaken, setOrderTaken] = useState(true);
  const [followUpDate, setFollowUpDate] = useState('');
  const [customOutcome, setCustomOutcome] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const followUpPresets = useMemo(() => getFollowUpPresets(), []);

  // Filtered customer list for instant search
  const filteredCustomers = useMemo(() => {
    if (!customerSearch.trim()) return allCustomers.slice(0, 8);
    const q = customerSearch.toLowerCase();
    return allCustomers.filter(
      (c) =>
        c.shop_name.toLowerCase().includes(q) ||
        (c.locality_area && c.locality_area.toLowerCase().includes(q)) ||
        (c.city && c.city.toLowerCase().includes(q)) ||
        (c.shopkeeper_name && c.shopkeeper_name.toLowerCase().includes(q))
    );
  }, [allCustomers, customerSearch]);

  const activeCustomer = useMemo(
    () => allCustomers.find((c) => c.customer_id === selectedCustomerId),
    [allCustomers, selectedCustomerId]
  );

  const handleOutcomeSelect = (item: (typeof COMMON_VISIT_OUTCOMES)[number]) => {
    setOutcome(item.label);
    if (item.id === 'ORDER_PLACED') {
      setOrderTaken(true);
    } else {
      setOrderTaken(false);
    }
  };

  const handleSubmit = async (proceedToOrderAfterSave = false) => {
    setErrorMsg('');
    setSuccessMsg('');

    if (!selectedCustomerId) {
      setErrorMsg('Please select a retail shop.');
      return;
    }

    const finalOutcome = (outcome === 'Custom' ? customOutcome.trim() : outcome) || 'Shop Visit';

    try {
      setIsSubmitting(true);
      const ok = await onSubmitVisit({
        customer_id: selectedCustomerId,
        visit_outcome: finalOutcome,
        order_taken: orderTaken,
        follow_up_date: followUpDate || undefined,
        next_action: orderTaken ? 'Prepare delivery order' : undefined,
        notes: notes.trim() || undefined,
      });

      if (ok) {
        if (proceedToOrderAfterSave && onProceedToOrder && activeCustomer) {
          onProceedToOrder(activeCustomer);
          onClose();
        } else {
          setSuccessMsg(`Visit at ${activeCustomer?.shop_name || 'shop'} recorded successfully!`);
          setTimeout(() => {
            onClose();
          }, 900);
        }
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to record shop visit.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-900/60 backdrop-blur-xs overflow-y-auto">
      <div className="bg-white rounded-3xl w-full max-w-lg shadow-2xl border border-slate-200 overflow-hidden my-auto animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="bg-emerald-900 text-white p-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-emerald-800 flex items-center justify-center text-emerald-200">
              <Store size={22} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white m-0">Record Shop Visit</h2>
              <p className="text-xs text-emerald-200 mt-0.5 mb-0">Dukaan Visit &amp; Follow-up</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-emerald-800/80 hover:bg-emerald-700 text-emerald-100 flex items-center justify-center transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-5 sm:p-6 space-y-5 max-h-[80vh] overflow-y-auto">
          {errorMsg && (
            <div className="p-3 bg-red-50 border border-red-200 text-red-800 rounded-xl text-xs flex items-center gap-2">
              <AlertCircle size={15} className="shrink-0 text-red-600" />
              <span>{errorMsg}</span>
            </div>
          )}

          {successMsg && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs flex items-center gap-2">
              <CheckCircle2 size={15} className="shrink-0 text-emerald-600" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* 1. Target Shop */}
          <div>
            <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block mb-1.5">
              1. Shop / Retailer
            </label>
            {initialCustomer ? (
              <div className="p-3.5 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center justify-between">
                <div>
                  <div className="font-bold text-emerald-900 text-sm">{initialCustomer.shop_name}</div>
                  <div className="text-xs text-emerald-700 mt-0.5">
                    {initialCustomer.locality_area || initialCustomer.city}
                    {initialCustomer.mobile ? ` · 📞 ${initialCustomer.mobile}` : ''}
                  </div>
                </div>
                <span className="text-xs font-semibold bg-emerald-200/60 text-emerald-900 px-2 py-0.5 rounded-md">
                  {initialCustomer.customer_type}
                </span>
              </div>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  placeholder="🔍 Search shop by name, owner or area..."
                  value={customerSearch}
                  onChange={(e) => setCustomerSearch(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 text-sm focus:outline-emerald-700"
                />
                <div className="max-h-36 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100 bg-white">
                  {filteredCustomers.map((c) => (
                    <button
                      key={c.customer_id}
                      type="button"
                      onClick={() => {
                        setSelectedCustomerId(c.customer_id);
                        setCustomerSearch('');
                      }}
                      className={`w-full p-2.5 text-left text-xs flex items-center justify-between hover:bg-slate-50 cursor-pointer ${
                        selectedCustomerId === c.customer_id ? 'bg-emerald-50 font-bold' : ''
                      }`}
                    >
                      <div>
                        <div className="text-slate-900 font-semibold">{c.shop_name}</div>
                        <div className="text-slate-400 text-[11px]">{c.locality_area || c.city}</div>
                      </div>
                      <span className="text-[10px] text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                        {c.customer_type}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 2. Visit Outcome (1-Tap Chips) */}
          <div>
            <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block mb-1.5">
              2. What happened during this visit? (Outcome)
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {COMMON_VISIT_OUTCOMES.map((item) => {
                const isSelected = outcome === item.label;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleOutcomeSelect(item)}
                    className={`p-3 rounded-xl border text-left flex items-start gap-2.5 transition-all cursor-pointer ${
                      isSelected
                        ? 'border-emerald-700 bg-emerald-50/90 text-emerald-950 font-bold ring-2 ring-emerald-700/20'
                        : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full border mt-0.5 flex items-center justify-center shrink-0 ${
                        isSelected ? 'border-emerald-700 bg-emerald-700' : 'border-slate-300 bg-white'
                      }`}
                    >
                      {isSelected && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                    </div>
                    <div>
                      <div className="text-xs">{item.label}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">{item.hindi}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 3. Follow-up Scheduling */}
          <div>
            <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block mb-1.5">
              3. Next Follow-up Date (Optional)
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {followUpPresets.map((preset) => {
                const isSelected = followUpDate === preset.date;
                return (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => setFollowUpDate(isSelected ? '' : preset.date)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-emerald-800 text-white border-emerald-800'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border-slate-200'
                    }`}
                  >
                    <span>{preset.label}</span>
                    <span className="text-[10px] opacity-75 ml-1">({preset.hindi})</span>
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2">
              <Calendar size={16} className="text-slate-400 shrink-0" />
              <input
                type="date"
                value={followUpDate}
                onChange={(e) => setFollowUpDate(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs text-slate-700 focus:outline-emerald-700"
              />
            </div>
          </div>

          {/* 4. Notes & Shop Feedback */}
          <div>
            <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block mb-1.5">
              4. Notes / Shopkeeper Feedback
            </label>
            <textarea
              rows={2}
              placeholder="e.g. Rate inquiry, wants 200g Katran next time, asked to call before delivery..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 text-xs focus:outline-emerald-700"
            />
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-4 sm:p-5 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center gap-2.5 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="w-full sm:w-auto px-4 py-2.5 rounded-xl border border-slate-300 text-slate-700 text-xs font-semibold hover:bg-slate-100 transition-colors cursor-pointer"
          >
            Cancel
          </button>

          {/* If outcome is Order Placed, provide direct transition to order */}
          {outcome === 'Order Placed' && onProceedToOrder && (
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleSubmit(true)}
              className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-bold shadow-sm transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
            >
              <ShoppingCart size={15} />
              <span>Save &amp; Take Order Now &rarr;</span>
            </button>
          )}

          <button
            type="button"
            disabled={isSubmitting}
            onClick={() => handleSubmit(false)}
            className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-slate-900 hover:bg-black text-white text-xs font-bold shadow-sm transition-all flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
          >
            {isSubmitting ? 'Saving Visit…' : 'Save Visit Log'}
          </button>
        </div>
      </div>
    </div>
  );
};
