import React, { useState, useMemo, useEffect } from 'react';
import { Customer, Product, CustomerType, Sale, SaleItem, SalesmanStockItem } from '../../types';
import { getDefaultPriceForProduct, PAYMENT_METHODS } from '../../utils/salesmanUtils';
import { generateInvoicePdf } from '../../utils/generateInvoicePdf';
import {
  X,
  ChevronRight,
  ChevronLeft,
  ShoppingCart,
  Users,
  Package,
  Receipt,
  CheckCircle2,
  AlertCircle,
  Plus,
  Minus,
  Search,
  Share2,
  Download,
  Calendar,
  Sparkles,
  Boxes,
  Truck,
  CreditCard,
  MessageCircle,
} from 'lucide-react';

interface CartItem {
  product_id: string;
  quantity: number;
  unit_price: number;
}

interface MobileOrderWizardProps {
  initialCustomer?: Customer | null;
  allCustomers: Customer[];
  allProducts: Product[];
  salesmanStock?: SalesmanStockItem[];
  isGoogleSheetsConnected?: boolean;
  persistentWritesEnabled?: boolean;
  onClose: () => void;
  onSubmitSale: (saleInput: {
    customer_id?: string;
    customer_name_snapshot?: string;
    customer_mobile?: string;
    sales_type: CustomerType;
    lines: Array<{
      product_id: string;
      quantity: number;
      actual_unit_price: number;
    }>;
    payment_method?: 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER';
    payment_reference?: string;
    discount_amount?: number;
    delivery_status?: 'DELIVERED' | 'PENDING' | 'CANCELLED';
    notes?: string;
    idempotency_key?: string;
  }) => Promise<{ sale: Sale; paymentId?: string }>;
}

export const MobileOrderWizard: React.FC<MobileOrderWizardProps> = ({
  initialCustomer,
  allCustomers,
  allProducts,
  salesmanStock = [],
  isGoogleSheetsConnected = true,
  persistentWritesEnabled = true,
  onClose,
  onSubmitSale,
}) => {
  const [step, setStep] = useState<1 | 2 | 3>(initialCustomer ? 2 : 1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  // Step 1: Customer State
  const [customerMode, setCustomerMode] = useState<'registered' | 'walkin'>('registered');
  const [selectedCustomerId, setSelectedCustomerId] = useState<string>(
    initialCustomer?.customer_id || allCustomers[0]?.customer_id || ''
  );
  const [customerSearch, setCustomerSearch] = useState('');
  const [walkInName, setWalkInName] = useState('');
  const [walkInMobile, setWalkInMobile] = useState('');
  const [saleType, setSaleType] = useState<CustomerType>(
    initialCustomer?.customer_type || 'RETAILER'
  );

  // Step 2: Product Catalog & Cart State
  const [categoryFilter, setCategoryFilter] = useState<string>('ALL');
  const [productSearch, setProductSearch] = useState('');
  const [cart, setCart] = useState<Record<string, number>>({});

  // Step 3: Review, Settlement & Notes
  const [discountAmount, setDiscountAmount] = useState<number>(0);
  const [paymentMethod, setPaymentMethod] = useState<'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER'>('CASH');
  const [paymentReference, setPaymentReference] = useState('');
  const [deliveryStatus, setDeliveryStatus] = useState<'DELIVERED' | 'PENDING'>('DELIVERED');
  const [orderNotes, setOrderNotes] = useState('');
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);

  // Success Confirmation State
  const [issuedSale, setIssuedSale] = useState<Sale | null>(null);

  // Active products only
  const activeProducts = useMemo(() => allProducts.filter((p) => p.active), [allProducts]);

  // Categories list
  const categories = useMemo(() => {
    const set = new Set<string>(['ALL']);
    activeProducts.forEach((p) => {
      if (p.category) set.add(p.category);
    });
    return Array.from(set);
  }, [activeProducts]);

  // Active Customer Object
  const selectedCustomer = useMemo(
    () => allCustomers.find((c) => c.customer_id === selectedCustomerId),
    [allCustomers, selectedCustomerId]
  );

  // Update saleType when selectedCustomer changes
  useEffect(() => {
    if (selectedCustomer?.customer_type) {
      setSaleType(selectedCustomer.customer_type);
    }
  }, [selectedCustomer]);

  // Stock lookup per product
  const getProductStock = (productId: string) => {
    const item = salesmanStock.find((s) => s.product_id === productId);
    return item ? item.quantity : 0;
  };

  // Filtered Products for Catalog
  const filteredProducts = useMemo(() => {
    return activeProducts.filter((p) => {
      const matchesCat = categoryFilter === 'ALL' || p.category === categoryFilter;
      if (!matchesCat) return false;
      if (!productSearch.trim()) return true;
      const q = productSearch.toLowerCase();
      return (
        p.product_name.toLowerCase().includes(q) ||
        p.variant.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q)
      );
    });
  }, [activeProducts, categoryFilter, productSearch]);

  // Quantity updates
  const setProductQuantity = (productId: string, qty: number) => {
    setCart((prev) => {
      const next = { ...prev };
      if (qty <= 0) {
        delete next[productId];
      } else {
        next[productId] = qty;
      }
      return next;
    });
  };

  const incrementProduct = (productId: string, delta: number) => {
    const current = cart[productId] || 0;
    setProductQuantity(productId, Math.max(0, current + delta));
  };

  // Cart calculations
  const cartLines = useMemo(() => {
    return Object.entries(cart)
      .map(([productId, quantity]) => {
        const product = activeProducts.find((p) => p.product_id === productId);
        if (!product || quantity <= 0) return null;
        const unitPrice = getDefaultPriceForProduct(product, saleType);
        const lineTotal = quantity * unitPrice;
        const weightKg = ((product.pack_weight_g || 200) * quantity) / 1000;
        return {
          product,
          productId,
          quantity,
          unitPrice,
          lineTotal,
          weightKg,
        };
      })
      .filter(Boolean) as Array<{
      product: Product;
      productId: string;
      quantity: number;
      unitPrice: number;
      lineTotal: number;
      weightKg: number;
    }>;
  }, [cart, activeProducts, saleType]);

  const subtotal = useMemo(
    () => cartLines.reduce((sum, item) => sum + item.lineTotal, 0),
    [cartLines]
  );

  const totalPackets = useMemo(
    () => cartLines.reduce((sum, item) => sum + item.quantity, 0),
    [cartLines]
  );

  const totalWeightKg = useMemo(
    () => cartLines.reduce((sum, item) => sum + item.weightKg, 0),
    [cartLines]
  );

  const finalBillTotal = Math.max(0, subtotal - (Number(discountAmount) || 0));

  // Filtered customer list for search
  const filteredCustomers = useMemo(() => {
    if (!customerSearch.trim()) return allCustomers.slice(0, 10);
    const q = customerSearch.toLowerCase();
    return allCustomers.filter(
      (c) =>
        c.shop_name.toLowerCase().includes(q) ||
        (c.locality_area && c.locality_area.toLowerCase().includes(q)) ||
        (c.city && c.city.toLowerCase().includes(q)) ||
        (c.shopkeeper_name && c.shopkeeper_name.toLowerCase().includes(q))
    );
  }, [allCustomers, customerSearch]);

  // Submission handler
  const handleFinalSubmit = async () => {
    setErrorMsg('');

    if (cartLines.length === 0) {
      setErrorMsg('Please add at least one product to the order.');
      return;
    }

    if (discountAmount > subtotal) {
      setErrorMsg('Discount cannot exceed subtotal amount.');
      return;
    }

    // Reuse idempotency key on retry to guarantee duplicate prevention
    const safeKey =
      idempotencyKey ||
      `ORD-${Date.now()}-${Math.random().toString(36).substring(2, 7).toUpperCase()}`;
    if (!idempotencyKey) {
      setIdempotencyKey(safeKey);
    }

    const resolvedCustId = customerMode === 'registered' ? selectedCustomerId : 'CUS-WALKIN';
    const resolvedCustName =
      customerMode === 'registered'
        ? selectedCustomer?.shop_name || 'Walk-in Customer'
        : walkInName.trim() || 'Walk-in Customer';
    const resolvedMobile =
      customerMode === 'registered' ? selectedCustomer?.mobile || '' : walkInMobile.trim();

    try {
      setIsSubmitting(true);
      const res = await onSubmitSale({
        customer_id: resolvedCustId,
        customer_name_snapshot: resolvedCustName,
        customer_mobile: resolvedMobile,
        sales_type: saleType,
        lines: cartLines.map((l) => ({
          product_id: l.productId,
          quantity: l.quantity,
          actual_unit_price: l.unitPrice,
        })),
        payment_method: paymentMethod,
        payment_reference: paymentReference.trim() || undefined,
        discount_amount: Number(discountAmount) || 0,
        delivery_status: deliveryStatus,
        notes: orderNotes.trim() || undefined,
        idempotency_key: safeKey,
      });

      setIssuedSale(res.sale);
      setIdempotencyKey(null);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to issue sales bill.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // WhatsApp share link generator
  const getWhatsAppShareLink = () => {
    if (!issuedSale) return '';
    const phone = (issuedSale.customer_mobile || walkInMobile || '').replace(/\D/g, '').slice(-10);
    const itemsText = cartLines
      .map((l, i) => `${i + 1}. ${l.product.product_name} (${l.quantity} pkts) - ₹${l.lineTotal}`)
      .join('\n');

    const msg = `*KAWAD SWAD UDHYOG - SALES BILL*\n---------------------------\nBill No: *${issuedSale.bill_number}*\nCustomer: *${issuedSale.customer_name_snapshot}*\nDate: ${new Date(issuedSale.sale_datetime).toLocaleDateString('en-IN')}\n\n*Items:*\n${itemsText}\n---------------------------\n*Total: ₹${Number(issuedSale.bill_total).toFixed(2)}*\nPayment: *${issuedSale.payment_status} (${issuedSale.payment_method || 'CASH'})*\n\nDhanyawad! 🙏`;

    if (phone.length === 10) {
      return `https://wa.me/91${phone}?text=${encodeURIComponent(msg)}`;
    }
    return `https://wa.me/?text=${encodeURIComponent(msg)}`;
  };

  // --------------------------------------------------------------------------
  // SUCCESS CONFIRMATION SCREEN
  // --------------------------------------------------------------------------
  if (issuedSale) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-900/60 backdrop-blur-xs overflow-y-auto">
        <div className="bg-white rounded-3xl w-full max-w-lg shadow-2xl border border-slate-200 overflow-hidden text-center p-6 sm:p-8 animate-in fade-in zoom-in-95">
          <div className="w-16 h-16 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center mx-auto mb-4">
            <CheckCircle2 size={36} />
          </div>
          <div className="inline-block bg-emerald-50 text-emerald-800 text-[11px] font-bold px-3 py-1 rounded-full uppercase tracking-wider mb-2">
            Bill Issued &amp; Saved
          </div>
          <h2 className="text-2xl font-black text-slate-900 m-0">
            Bill #{issuedSale.bill_number}
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            Issued to <strong className="text-slate-800">{issuedSale.customer_name_snapshot}</strong>
          </p>

          <div className="my-5 p-4 bg-slate-50 rounded-2xl border border-slate-200 text-left space-y-2">
            <div className="flex justify-between text-xs text-slate-500">
              <span>Total Items</span>
              <span className="font-semibold text-slate-800">{totalPackets} packets ({totalWeightKg.toFixed(2)} kg)</span>
            </div>
            <div className="flex justify-between text-xs text-slate-500">
              <span>Payment Mode</span>
              <span className="font-semibold text-slate-800">{paymentMethod}</span>
            </div>
            <div className="flex justify-between text-base font-bold text-slate-900 pt-2 border-t border-slate-200">
              <span>Total Amount</span>
              <span className="font-mono text-emerald-800">₹{Number(issuedSale.bill_total).toFixed(2)}</span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="space-y-2.5">
            <a
              href={getWhatsAppShareLink()}
              target="_blank"
              rel="noopener noreferrer"
              className="w-full py-3 px-4 bg-emerald-700 hover:bg-emerald-800 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 shadow-xs transition-colors"
            >
              <MessageCircle size={16} />
              <span>Share Bill on WhatsApp</span>
            </a>

            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  const saleItems: SaleItem[] = cartLines.map((l, idx) => ({
                    sale_item_id: `${issuedSale.sale_id}-${idx}`,
                    sale_id: issuedSale.sale_id,
                    product_id: l.productId,
                    product_name_snapshot: l.product.product_name,
                    sku_snapshot: l.product.sku,
                    pack_weight_g: l.product.pack_weight_g || 200,
                    unit: l.product.selling_unit || 'PACKET',
                    quantity: l.quantity,
                    actual_unit_price: l.unitPrice,
                    discount_amount: 0,
                    line_total: l.lineTotal,
                    qualifying_kg: l.weightKg,
                    created_at: issuedSale.created_at,
                  }));
                  generateInvoicePdf(issuedSale, saleItems);
                }}
                className="py-2.5 px-3 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              >
                <Download size={14} />
                <span>PDF Invoice</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setCart({});
                  setIssuedSale(null);
                  setStep(1);
                  setDiscountAmount(0);
                  setOrderNotes('');
                }}
                className="py-2.5 px-3 bg-slate-900 hover:bg-black text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              >
                <Plus size={14} />
                <span>Next Order</span>
              </button>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="w-full py-2 text-xs text-slate-500 hover:text-slate-800 underline transition-colors cursor-pointer"
            >
              Close Window
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --------------------------------------------------------------------------
  // WIZARD MODAL CONTAINER
  // --------------------------------------------------------------------------
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-slate-900/60 backdrop-blur-xs overflow-y-auto">
      <div className="bg-white rounded-3xl w-full max-w-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[92vh] overflow-hidden my-auto animate-in fade-in zoom-in-95">
        {/* Wizard Header with Progress Stepper */}
        <div className="bg-emerald-900 text-white p-4 sm:p-5 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-2xl bg-emerald-800 flex items-center justify-center text-emerald-200">
                <ShoppingCart size={20} />
              </div>
              <div>
                <h2 className="text-base sm:text-lg font-bold text-white m-0">Take New Order</h2>
                <div className="text-[11px] text-emerald-200">
                  Step {step} of 3: {step === 1 ? 'Customer' : step === 2 ? 'Products & Quantities' : 'Review & Bill'}
                </div>
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

          {/* Stepper Indicator */}
          <div className="grid grid-cols-3 gap-2 mt-4 pt-3 border-t border-emerald-800">
            <div
              className={`h-1.5 rounded-full transition-all ${
                step >= 1 ? 'bg-emerald-400' : 'bg-emerald-800/60'
              }`}
            />
            <div
              className={`h-1.5 rounded-full transition-all ${
                step >= 2 ? 'bg-emerald-400' : 'bg-emerald-800/60'
              }`}
            />
            <div
              className={`h-1.5 rounded-full transition-all ${
                step >= 3 ? 'bg-emerald-400' : 'bg-emerald-800/60'
              }`}
            />
          </div>
        </div>

        {/* Wizard Body (Scrollable) */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
          {errorMsg && (
            <div className="p-3 bg-red-50 border border-red-200 text-red-800 rounded-xl text-xs flex items-center gap-2">
              <AlertCircle size={15} className="shrink-0 text-red-600" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* ================================================================ */}
          {/* STEP 1: SELECT CUSTOMER & PRICE TIER                             */}
          {/* ================================================================ */}
          {step === 1 && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Select Customer / Buyer
                </span>
                <div className="flex rounded-lg border border-slate-200 p-0.5 bg-slate-50 text-xs">
                  <button
                    type="button"
                    onClick={() => setCustomerMode('registered')}
                    className={`px-3 py-1 rounded-md font-semibold cursor-pointer transition-colors ${
                      customerMode === 'registered' ? 'bg-emerald-800 text-white shadow-xs' : 'text-slate-600'
                    }`}
                  >
                    Saved Shop
                  </button>
                  <button
                    type="button"
                    onClick={() => setCustomerMode('walkin')}
                    className={`px-3 py-1 rounded-md font-semibold cursor-pointer transition-colors ${
                      customerMode === 'walkin' ? 'bg-emerald-800 text-white shadow-xs' : 'text-slate-600'
                    }`}
                  >
                    Quick Walk-in
                  </button>
                </div>
              </div>

              {customerMode === 'registered' ? (
                <div className="space-y-3">
                  <div className="relative">
                    <Search size={16} className="absolute left-3 top-3 text-slate-400" />
                    <input
                      type="text"
                      placeholder="Search shop name, area, city, or phone..."
                      value={customerSearch}
                      onChange={(e) => setCustomerSearch(e.target.value)}
                      className="w-full pl-9 pr-3.5 py-2.5 rounded-xl border border-slate-300 text-xs sm:text-sm focus:outline-emerald-700"
                    />
                  </div>

                  <div className="max-h-64 overflow-y-auto rounded-2xl border border-slate-200 divide-y divide-slate-100 bg-white">
                    {filteredCustomers.map((c) => {
                      const isSelected = selectedCustomerId === c.customer_id;
                      return (
                        <button
                          key={c.customer_id}
                          type="button"
                          onClick={() => {
                            setSelectedCustomerId(c.customer_id);
                            setSaleType(c.customer_type || 'RETAILER');
                          }}
                          className={`w-full p-3 text-left text-xs flex items-center justify-between hover:bg-slate-50 cursor-pointer transition-colors ${
                            isSelected ? 'bg-emerald-50/80 font-bold border-l-4 border-emerald-700' : ''
                          }`}
                        >
                          <div>
                            <div className="text-slate-900 font-bold text-sm">{c.shop_name}</div>
                            <div className="text-slate-500 text-xs mt-0.5">
                              {c.locality_area || c.city || 'Market'}
                              {c.shopkeeper_name ? ` · Contact: ${c.shopkeeper_name}` : ''}
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-slate-100 text-slate-700">
                              {c.customer_type}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="space-y-3 p-4 bg-slate-50 rounded-2xl border border-slate-200">
                  <p className="text-xs text-slate-500 m-0">
                    Quick counter or spot sale without creating an account.
                  </p>
                  <div>
                    <label className="text-xs font-semibold text-slate-700 block mb-1">Buyer Name (Optional)</label>
                    <input
                      type="text"
                      placeholder="e.g. Ramesh Bhai / Walk-in"
                      value={walkInName}
                      onChange={(e) => setWalkInName(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs focus:outline-emerald-700"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-slate-700 block mb-1">Mobile for WhatsApp Bill (Optional)</label>
                    <input
                      type="tel"
                      placeholder="10-digit mobile number"
                      value={walkInMobile}
                      onChange={(e) => setWalkInMobile(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs focus:outline-emerald-700"
                    />
                  </div>
                </div>
              )}

              {/* Price Tier Selection */}
              <div>
                <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block mb-1.5">
                  Wholesale / Pricing Tier
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {(['RETAILER', 'WHOLESALER', 'DISTRIBUTOR'] as CustomerType[]).map((tier) => (
                    <button
                      key={tier}
                      type="button"
                      onClick={() => setSaleType(tier)}
                      className={`py-2 px-2.5 rounded-xl border text-center text-xs font-semibold cursor-pointer transition-all ${
                        saleType === tier
                          ? 'border-emerald-700 bg-emerald-50 text-emerald-950 font-bold ring-2 ring-emerald-700/20'
                          : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                      }`}
                    >
                      <div>{tier}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">
                        {tier === 'DISTRIBUTOR' ? '15% Off' : tier === 'WHOLESALER' ? '10% Off' : 'Standard'}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ================================================================ */}
          {/* STEP 2: VISUAL PRODUCT CATALOG & QUANTITIES                      */}
          {/* ================================================================ */}
          {step === 2 && (
            <div className="space-y-4">
              {/* Category Filter Tabs */}
              <div className="flex items-center gap-1.5 overflow-x-auto pb-1 no-scrollbar">
                {categories.map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setCategoryFilter(cat)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-bold whitespace-nowrap transition-colors cursor-pointer ${
                      categoryFilter === cat
                        ? 'bg-emerald-800 text-white'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Fast Product Search */}
              <div className="relative">
                <Search size={15} className="absolute left-3 top-3 text-slate-400" />
                <input
                  type="text"
                  placeholder="🔍 Search products (Moong, Katran, Chana, 200g)..."
                  value={productSearch}
                  onChange={(e) => setProductSearch(e.target.value)}
                  className="w-full pl-9 pr-3.5 py-2.5 rounded-xl border border-slate-300 text-xs sm:text-sm focus:outline-emerald-700"
                />
              </div>

              {/* Product Cards Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {filteredProducts.map((p) => {
                  const qty = cart[p.product_id] || 0;
                  const price = getDefaultPriceForProduct(p, saleType);
                  const stock = getProductStock(p.product_id);
                  const isShortage = stock < qty;

                  return (
                    <div
                      key={p.product_id}
                      className={`p-3.5 rounded-2xl border transition-all ${
                        qty > 0
                          ? 'border-emerald-600 bg-emerald-50/40 shadow-xs'
                          : 'border-slate-200 bg-white hover:border-slate-300'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="font-bold text-slate-900 text-sm truncate">
                              {p.product_name}
                            </span>
                            <span className="text-[10px] font-semibold px-1.5 py-0.2 rounded bg-slate-100 text-slate-600">
                              {p.variant || 'Plain'}
                            </span>
                          </div>
                          <div className="text-xs text-slate-500 mt-0.5">
                            Pack: <strong>{p.pack_weight_g}g</strong> · SKU: {p.sku}
                          </div>
                        </div>

                        {/* Price */}
                        <div className="text-right shrink-0">
                          <div className="text-sm font-black font-mono text-emerald-800">
                            ₹{price}
                          </div>
                          <div className="text-[10px] text-slate-400">per pkt</div>
                        </div>
                      </div>

                      {/* Van Stock Badge */}
                      <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-100 text-xs">
                        <span className={`text-[11px] font-medium flex items-center gap-1 ${
                          stock > 0 ? 'text-slate-600' : 'text-red-600'
                        }`}>
                          <Boxes size={12} className={stock > 0 ? 'text-emerald-700' : 'text-red-500'} />
                          <span>Van: {stock} {p.selling_unit}</span>
                          {isShortage && <span className="text-red-600 font-bold ml-1">(Stock Low)</span>}
                        </span>

                        {qty > 0 && (
                          <span className="text-xs font-bold text-emerald-800 font-mono">
                            Subtotal: ₹{qty * price}
                          </span>
                        )}
                      </div>

                      {/* Quantity Stepper (Large Touch Targets) */}
                      <div className="flex items-center justify-between gap-2 mt-3">
                        <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-xl">
                          <button
                            type="button"
                            onClick={() => incrementProduct(p.product_id, -1)}
                            disabled={qty <= 0}
                            className="w-8 h-8 rounded-lg bg-white border border-slate-200 text-slate-700 flex items-center justify-center font-bold text-sm disabled:opacity-30 active:scale-95 cursor-pointer"
                          >
                            <Minus size={14} />
                          </button>

                          <input
                            type="number"
                            min="0"
                            value={qty}
                            onChange={(e) =>
                              setProductQuantity(p.product_id, Math.max(0, parseInt(e.target.value, 10) || 0))
                            }
                            className="w-12 text-center text-sm font-bold bg-transparent border-none focus:outline-hidden"
                          />

                          <button
                            type="button"
                            onClick={() => incrementProduct(p.product_id, 1)}
                            className="w-8 h-8 rounded-lg bg-white border border-slate-200 text-slate-700 flex items-center justify-center font-bold text-sm active:scale-95 cursor-pointer"
                          >
                            <Plus size={14} />
                          </button>
                        </div>

                        {/* Quick Add Presets (+5, +10) */}
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => incrementProduct(p.product_id, 5)}
                            className="px-2 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold cursor-pointer"
                          >
                            +5
                          </button>
                          <button
                            type="button"
                            onClick={() => incrementProduct(p.product_id, 10)}
                            className="px-2 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold cursor-pointer"
                          >
                            +10
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ================================================================ */}
          {/* STEP 3: REVIEW, DISCOUNT, PAYMENT & SETTLEMENT                   */}
          {/* ================================================================ */}
          {step === 3 && (
            <div className="space-y-4">
              {/* Order Items Review Summary */}
              <div className="bg-slate-50 p-4 rounded-2xl border border-slate-200 space-y-2">
                <div className="flex items-center justify-between text-xs font-bold text-slate-700 uppercase">
                  <span>Selected Products ({cartLines.length})</span>
                  <span>{totalPackets} pkts · {totalWeightKg.toFixed(2)} kg</span>
                </div>
                <div className="divide-y divide-slate-200/60 max-h-48 overflow-y-auto">
                  {cartLines.map((l) => (
                    <div key={l.productId} className="py-2 flex items-center justify-between text-xs">
                      <div>
                        <div className="font-semibold text-slate-800">{l.product.product_name}</div>
                        <div className="text-[11px] text-slate-400">
                          {l.quantity} pkts × ₹{l.unitPrice}
                        </div>
                      </div>
                      <div className="font-bold text-slate-900 font-mono">₹{l.lineTotal}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Discount Field */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Trade Discount (₹)
                  </label>
                  <input
                    type="number"
                    min="0"
                    placeholder="0.00"
                    value={discountAmount || ''}
                    onChange={(e) => setDiscountAmount(Math.max(0, Number(e.target.value) || 0))}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs focus:outline-emerald-700 font-mono"
                  />
                </div>

                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Delivery Status
                  </label>
                  <div className="grid grid-cols-2 gap-1.5">
                    <button
                      type="button"
                      onClick={() => setDeliveryStatus('DELIVERED')}
                      className={`p-2 rounded-xl text-xs font-semibold border cursor-pointer ${
                        deliveryStatus === 'DELIVERED'
                          ? 'bg-emerald-800 text-white border-emerald-800 font-bold'
                          : 'bg-white text-slate-700 border-slate-200'
                      }`}
                    >
                      Delivered Now
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeliveryStatus('PENDING')}
                      className={`p-2 rounded-xl text-xs font-semibold border cursor-pointer ${
                        deliveryStatus === 'PENDING'
                          ? 'bg-amber-600 text-white border-amber-600 font-bold'
                          : 'bg-white text-slate-700 border-slate-200'
                      }`}
                    >
                      Deliver Later
                    </button>
                  </div>
                </div>
              </div>

              {/* Payment Mode Selection */}
              <div>
                <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block mb-1.5">
                  Payment Mode
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {PAYMENT_METHODS.map((pm) => {
                    const isSelected = paymentMethod === pm.method;
                    return (
                      <button
                        key={pm.method}
                        type="button"
                        onClick={() => setPaymentMethod(pm.method)}
                        className={`p-3 rounded-xl border text-center transition-all cursor-pointer ${
                          isSelected
                            ? 'border-emerald-700 bg-emerald-50 text-emerald-950 font-bold ring-2 ring-emerald-700/20'
                            : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                        }`}
                      >
                        <div className="text-lg mb-1">{pm.icon}</div>
                        <div className="text-xs font-bold">{pm.label}</div>
                        <div className="text-[10px] text-slate-400 mt-0.5">{pm.hindiLabel}</div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Payment Reference if UPI or Bank */}
              {paymentMethod !== 'CASH' && (
                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    UPI / Bank Ref (UTR Number)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. UPI UTR, slip number, or txn ref..."
                    value={paymentReference}
                    onChange={(e) => setPaymentReference(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs focus:outline-emerald-700"
                  />
                </div>
              )}

              {/* Notes */}
              <div>
                <label className="text-xs font-bold text-slate-700 block mb-1">
                  Bill Remarks / Delivery Instructions (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Leave with brother, collected 500 cash, balance on Friday..."
                  value={orderNotes}
                  onChange={(e) => setOrderNotes(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs focus:outline-emerald-700"
                />
              </div>

              {/* Final Totals Card */}
              <div className="p-4 bg-emerald-900 text-white rounded-2xl flex items-center justify-between">
                <div>
                  <div className="text-[11px] text-emerald-300 font-semibold uppercase">Total Bill Amount</div>
                  <div className="text-2xl font-black font-mono text-white mt-0.5">
                    ₹{finalBillTotal.toFixed(2)}
                  </div>
                  {discountAmount > 0 && (
                    <div className="text-[10px] text-emerald-200">Includes ₹{discountAmount} discount</div>
                  )}
                </div>

                <div className="text-right">
                  <div className="text-xs text-emerald-200 font-medium">Customer:</div>
                  <div className="text-sm font-bold text-white truncate max-w-[160px]">
                    {selectedCustomer?.shop_name || walkInName || 'Walk-in'}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Wizard Sticky Bottom Actions */}
        <div className="p-4 bg-slate-50 border-t border-slate-200 flex items-center justify-between gap-3 shrink-0">
          {step > 1 ? (
            <button
              type="button"
              onClick={() => setStep((s) => (s - 1) as any)}
              className="px-4 py-2.5 rounded-xl border border-slate-300 text-slate-700 text-xs font-semibold hover:bg-slate-100 flex items-center gap-1 cursor-pointer"
            >
              <ChevronLeft size={16} />
              <span>Back</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-xl border border-slate-300 text-slate-700 text-xs font-semibold hover:bg-slate-100 cursor-pointer"
            >
              Cancel
            </button>
          )}

          {step === 1 && (
            <button
              type="button"
              disabled={customerMode === 'registered' && !selectedCustomerId}
              onClick={() => setStep(2)}
              className="px-5 py-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm cursor-pointer disabled:opacity-50"
            >
              <span>Choose Products</span>
              <ChevronRight size={16} />
            </button>
          )}

          {step === 2 && (
            <div className="flex items-center gap-3">
              <div className="text-right">
                <div className="text-xs font-black text-slate-900 font-mono">₹{subtotal.toFixed(2)}</div>
                <div className="text-[10px] text-slate-400">{totalPackets} packets</div>
              </div>
              <button
                type="button"
                disabled={cartLines.length === 0}
                onClick={() => setStep(3)}
                className="px-5 py-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm cursor-pointer disabled:opacity-50"
              >
                <span>Review &amp; Pay</span>
                <ChevronRight size={16} />
              </button>
            </div>
          )}

          {step === 3 && (
            <button
              type="button"
              disabled={isSubmitting || !isGoogleSheetsConnected || !persistentWritesEnabled}
              onClick={handleFinalSubmit}
              className="px-6 py-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-black flex items-center gap-2 shadow-md cursor-pointer disabled:opacity-50"
            >
              {isSubmitting ? (
                <span>Saving Bill…</span>
              ) : (
                <>
                  <CheckCircle2 size={16} />
                  <span>Confirm &amp; Issue Bill (₹{finalBillTotal.toFixed(2)})</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
