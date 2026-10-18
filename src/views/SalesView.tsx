import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useStore } from '../context/StoreContext';
import { CustomerType, Sale, SaleItem, Product } from '../types';
import { generateInvoicePdf } from '../utils/generateInvoicePdf';
import { InvoiceModal } from '../components/InvoiceModal';

interface CartLine {
  product_id: string;
  quantity: number;
  actual_unit_price: number;
}

const SALE_TYPES: Array<{ type: CustomerType; label: string; desc: string }> = [
  { type: 'RETAIL', label: 'Retail Sale', desc: 'Direct consumer cash memo' },
  { type: 'RETAILER', label: 'Retailer Sale', desc: 'Kirana & retail partners' },
  { type: 'WHOLESALER', label: 'Wholesaler Sale', desc: 'Bulk trade orders' },
  { type: 'DISTRIBUTOR', label: 'Distributor Sale', desc: 'Area distribution' },
];

const PAYMENT_METHODS: Array<{ method: 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER'; label: string; icon: string }> = [
  { method: 'CASH', label: 'Cash', icon: '💵' },
  { method: 'UPI', label: 'UPI / QR', icon: '📱' },
  { method: 'BANK_TRANSFER', label: 'Bank Transfer', icon: '🏦' },
  { method: 'OTHER', label: 'Other Approved', icon: '💳' },
];

// Helper to determine standard baseline price based on product
const getDefaultPriceForProduct = (p?: Product, saleType?: CustomerType): number => {
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

export const SalesView: React.FC = () => {
  const {
    customers,
    products,
    sales,
    createSale,
    getSaleWithItems,
    currentUser,
    companyStockSummary,
    salesmanStockSummary,
    activeCustomerIdForBilling,
    setActiveCustomerIdForBilling,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
  } = useStore();

  const activeCustomers = useMemo(() => customers.filter((c) => c.active), [customers]);
  const activeProducts = useMemo(() => products.filter((p) => p.active), [products]);

  // Session-safe sale type memory
  const [salesType, setSalesType] = useState<CustomerType>(() => {
    try {
      const saved = sessionStorage.getItem('ks_last_sales_type');
      if (saved && ['RETAIL', 'RETAILER', 'WHOLESALER', 'DISTRIBUTOR'].includes(saved)) {
        return saved as CustomerType;
      }
    } catch {
      // ignore
    }
    return 'RETAIL';
  });

  const handleSaleTypeChange = (type: CustomerType) => {
    setSalesType(type);
    invalidateDraftKey();
    try {
      sessionStorage.setItem('ks_last_sales_type', type);
    } catch {
      // ignore
    }
  };

  // Customer Mode & Selection
  const [customerMode, setCustomerMode] = useState<'walkin' | 'registered'>('walkin');
  const [customerId, setCustomerId] = useState('');
  const [customerSearchQuery, setCustomerSearchQuery] = useState('');
  const [walkInName, setWalkInName] = useState('');
  const [walkInMobile, setWalkInMobile] = useState('');

  // Handle pre-selection from Customers view
  useEffect(() => {
    if (activeCustomerIdForBilling) {
      setCustomerMode('registered');
      setCustomerId(activeCustomerIdForBilling);
      const match = customers.find((c) => c.customer_id === activeCustomerIdForBilling);
      if (match) {
        handleSaleTypeChange(match.customer_type || 'RETAILER');
      }
      setActiveCustomerIdForBilling(null);
    }
  }, [activeCustomerIdForBilling, customers, setActiveCustomerIdForBilling]);

  // Sale & Payment
  const [paymentMethod, setPaymentMethod] = useState<'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER'>('CASH');
  const [paymentReference, setPaymentReference] = useState('');
  const [discountAmount, setDiscountAmount] = useState<number>(0);
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionIdempotencyKey, setSubmissionIdempotencyKey] = useState<string | null>(null);

  const invalidateDraftKey = () => {
    setSubmissionIdempotencyKey(null);
  };

  // Fast Product Search Input State
  const [productSearch, setProductSearch] = useState('');
  const [isProductSearchOpen, setIsProductSearchOpen] = useState(false);
  const productSearchContainerRef = useRef<HTMLDivElement>(null);

  // Post-sale and UI State
  const [searchFilter, setSearchFilter] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);
  const [issuedSale, setIssuedSale] = useState<{ sale: Sale; paymentId: string } | null>(null);
  const [viewingSaleData, setViewingSaleData] = useState<{ sale: Sale; items: SaleItem[] } | null>(null);
  const [customShareMobile, setCustomShareMobile] = useState('');

  const getAvailableStock = (productId: string) => {
    if (currentUser?.role === 'SALESMAN') {
      const sm = salesmanStockSummary.find(
        (s) => s.product_id === productId && s.salesman_user_id === currentUser.user_id
      );
      return sm ? sm.quantity : 0;
    } else {
      const comp = companyStockSummary.find((c) => c.product_id === productId);
      return comp ? comp.company_quantity : 0;
    }
  };

  // Cart state initialized with first product
  const [cart, setCart] = useState<CartLine[]>(() => {
    const firstP = activeProducts[0];
    return [
      {
        product_id: firstP?.product_id || '',
        quantity: 1,
        actual_unit_price: getDefaultPriceForProduct(firstP, 'RETAIL'),
      },
    ];
  });

  // Keep first product updated if activeProducts loads asynchronously
  useEffect(() => {
    if (cart.length === 1 && !cart[0].product_id && activeProducts.length > 0) {
      const firstP = activeProducts[0];
      setCart([
        {
          product_id: firstP.product_id,
          quantity: 1,
          actual_unit_price: getDefaultPriceForProduct(firstP, salesType),
        },
      ]);
    }
  }, [activeProducts, cart, salesType]);

  // Frequently sold product shortcuts (first 5 active products)
  const popularShortcuts = useMemo(() => activeProducts.slice(0, 5), [activeProducts]);

  // Fast search products
  const matchingProducts = useMemo(() => {
    if (!productSearch.trim()) return activeProducts.slice(0, 8);
    const q = productSearch.toLowerCase();
    return activeProducts.filter(
      (p) =>
        p.product_name.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q) ||
        p.category.toLowerCase().includes(q) ||
        p.variant.toLowerCase().includes(q)
    );
  }, [activeProducts, productSearch]);

  // Close product search dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        productSearchContainerRef.current &&
        !productSearchContainerRef.current.contains(event.target as Node)
      ) {
        setIsProductSearchOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const addOrIncrementProduct = (productId: string) => {
    invalidateDraftKey();
    const existingIndex = cart.findIndex((line) => line.product_id === productId);
    if (existingIndex >= 0) {
      setCart((prev) =>
        prev.map((line, idx) =>
          idx === existingIndex ? { ...line, quantity: line.quantity + 1 } : line
        )
      );
    } else {
      const p = activeProducts.find((x) => x.product_id === productId);
      setCart((prev) => [
        ...prev,
        {
          product_id: productId,
          quantity: 1,
          actual_unit_price: getDefaultPriceForProduct(p, salesType),
        },
      ]);
    }
  };

  const handleSelectFromProductSearch = (productId: string) => {
    addOrIncrementProduct(productId);
    setProductSearch('');
    setIsProductSearchOpen(false);
  };

  const addLine = () => {
    invalidateDraftKey();
    if (activeProducts.length === 0) {
      setNotice({ msg: 'Add an active product in Catalogue before creating a bill.', error: true });
      return;
    }
    const defaultProd = activeProducts[0];
    setCart((prev) => [
      ...prev,
      {
        product_id: defaultProd.product_id,
        quantity: 1,
        actual_unit_price: getDefaultPriceForProduct(defaultProd, salesType),
      },
    ]);
  };

  const removeLine = (index: number) => {
    invalidateDraftKey();
    if (cart.length <= 1) return;
    setCart((prev) => prev.filter((_, i) => i !== index));
  };

  const updateLine = (index: number, updates: Partial<CartLine>) => {
    invalidateDraftKey();
    setCart((prev) =>
      prev.map((line, i) => {
        if (i !== index) return line;
        const updated = { ...line, ...updates };
        if (updates.product_id && updates.product_id !== line.product_id) {
          const newProd = activeProducts.find((p) => p.product_id === updates.product_id);
          updated.actual_unit_price = getDefaultPriceForProduct(newProd, salesType);
        }
        return updated;
      })
    );
  };

  // Filtered customer list for instant search
  const filteredCustomers = useMemo(() => {
    if (!customerSearchQuery.trim()) return activeCustomers.slice(0, 10);
    const q = customerSearchQuery.toLowerCase();
    return activeCustomers.filter(
      (c) =>
        c.shop_name.toLowerCase().includes(q) ||
        (c.shopkeeper_name && c.shopkeeper_name.toLowerCase().includes(q)) ||
        (c.mobile && c.mobile.includes(q)) ||
        (c.locality_area && c.locality_area.toLowerCase().includes(q)) ||
        (c.city && c.city.toLowerCase().includes(q))
    );
  }, [activeCustomers, customerSearchQuery]);

  const selectedCustomer = useMemo(
    () => activeCustomers.find((c) => c.customer_id === customerId),
    [activeCustomers, customerId]
  );

  // Totals & Weight Calculations
  const subtotal = cart.reduce(
    (sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.actual_unit_price) || 0),
    0
  );
  const billTotal = Math.max(0, subtotal - (Number(discountAmount) || 0));

  const totalQualifyingWeightKg = cart.reduce((sum, line) => {
    const p = products.find((prod) => prod.product_id === line.product_id);
    const weightG = p?.pack_weight_g || 500;
    return sum + (weightG * (Number(line.quantity) || 0)) / 1000;
  }, 0);

  const totalPackets = cart.reduce((sum, line) => sum + (Number(line.quantity) || 0), 0);

  // Safe deliberate reset for new bill (preserves safe session salesType)
  const resetFormDeliberately = () => {
    setCustomerMode('walkin');
    setCustomerId('');
    setCustomerSearchQuery('');
    setWalkInName('');
    setWalkInMobile('');
    setPaymentMethod('CASH');
    setPaymentReference('');
    setDiscountAmount(0);
    setNotes('');
    setSubmissionIdempotencyKey(null);
    const firstP = activeProducts[0];
    setCart([
      {
        product_id: firstP?.product_id || '',
        quantity: 1,
        actual_unit_price: getDefaultPriceForProduct(firstP, salesType),
      },
    ]);
    setIssuedSale(null);
    setCustomShareMobile('');
    setProductSearch('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (cart.length === 0 || !cart.some((l) => l.product_id)) {
      setNotice({ msg: 'Add at least one valid product line.', error: true });
      return;
    }

    if (discountAmount > subtotal) {
      setNotice({ msg: 'Discount cannot exceed subtotal amount.', error: true });
      return;
    }

    const resolvedCustId = customerMode === 'registered' ? customerId : 'CUS-WALKIN';
    const resolvedCustName =
      customerMode === 'registered'
        ? selectedCustomer?.shop_name || 'Walk-in Customer'
        : walkInName.trim() || 'Walk-in Customer';
    const resolvedMobile =
      customerMode === 'registered' ? selectedCustomer?.mobile || '' : walkInMobile.trim();

    setIsSubmitting(true);
    // Reuse the active idempotency key for retries of this exact bill, preventing duplicate sales
    const idempotencyKey =
      submissionIdempotencyKey ||
      `IDEMP-${Date.now()}-${Math.random().toString(36).substring(2, 8).toUpperCase()}-${(resolvedCustId || 'WALKIN').slice(-4)}`;
    if (!submissionIdempotencyKey) {
      setSubmissionIdempotencyKey(idempotencyKey);
    }

    try {
      const result = await createSale({
        customer_id: resolvedCustId,
        customer_name_snapshot: resolvedCustName,
        customer_mobile: resolvedMobile,
        sales_type: salesType,
        payment_method: paymentMethod,
        payment_reference: paymentReference.trim(),
        discount_amount: Number(discountAmount) || 0,
        notes: notes.trim(),
        delivery_status: 'DELIVERED',
        idempotency_key: idempotencyKey,
        lines: cart.map((line) => ({
          product_id: line.product_id,
          quantity: Number(line.quantity),
          actual_unit_price: Number(line.actual_unit_price),
        })),
      });

      // Clear the idempotency key once successfully completed
      setSubmissionIdempotencyKey(null);

      setIssuedSale({ sale: result.sale, paymentId: result.paymentId || '' });
      if (resolvedMobile) {
        setCustomShareMobile(resolvedMobile);
      }
      setNotice({
        msg: `✅ Bill #${result.sale.bill_number} issued successfully! Full payment recorded and stock updated.`,
      });

      // Clear current bill data while preserving session
      const firstP = activeProducts[0];
      setCart([
        {
          product_id: firstP?.product_id || '',
          quantity: 1,
          actual_unit_price: getDefaultPriceForProduct(firstP, salesType),
        },
      ]);
      setDiscountAmount(0);
      setPaymentReference('');
      setNotes('');
      setWalkInName('');
      setWalkInMobile('');
      setProductSearch('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to issue bill';
      const isTimeoutOrNetwork =
        errorMsg.toLowerCase().includes('time') ||
        errorMsg.toLowerCase().includes('network') ||
        errorMsg.toLowerCase().includes('fetch') ||
        errorMsg.toLowerCase().includes('spin') ||
        errorMsg.toLowerCase().includes('connect');
      setNotice({
        msg: isTimeoutOrNetwork
          ? `${errorMsg}. Your cart and payment details are safely preserved. Click "Retry Bill Submission" to safely resubmit with duplicate protection.`
          : errorMsg,
        error: true,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  // WhatsApp share generator
  const getWhatsAppLink = (sale: Sale, targetMobile?: string) => {
    const saleData = getSaleWithItems(sale.sale_id);
    const items = saleData ? saleData.items : [];
    const mobile = (targetMobile || sale.customer_mobile || customShareMobile || '').replace(/\D/g, '').slice(-10);
    const itemsList = items
      .map(
        (it, idx) =>
          `${idx + 1}. ${it.product_name_snapshot || it.sku_snapshot} (${it.quantity} ${it.unit || 'pkt'}) - ₹${Number(it.line_total).toFixed(2)}`
      )
      .join('\n');

    const msg = `*KAWAD SWAD UDHYOG - SALES INVOICE*\n--------------------------------\nBill No: *${sale.bill_number}*\nDate: ${new Date(sale.sale_datetime).toLocaleDateString('en-IN')}\nCustomer: *${sale.customer_name_snapshot}*\nType: ${sale.sales_type}\n\n*Items:*\n${itemsList}\n--------------------------------\n*Bill Total: ₹${Number(sale.bill_total).toFixed(2)}*\nPayment: *PAID (${sale.payment_status})*\n\nThank you for business with Kawad Swad Udhyog! 🙏`;

    const encoded = encodeURIComponent(msg);
    if (mobile.length === 10) {
      return `https://wa.me/91${mobile}?text=${encoded}`;
    }
    return `https://wa.me/?text=${encoded}`;
  };

  // Filter bills for salesman vs manager
  const userVisibleSales =
    currentUser?.role === 'SALESMAN'
      ? sales.filter(
          (s) =>
            s.salesman_user_id === currentUser.user_id ||
            s.entered_by_user_id === currentUser.user_id
        )
      : sales;

  const filteredSales = userVisibleSales.filter((s) =>
    [s.bill_number, s.customer_name_snapshot, s.sales_type, s.payment_status]
      .join(' ')
      .toLowerCase()
      .includes(searchFilter.toLowerCase())
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
        <div>
          <h1 style={{ margin: 0 }}>Sales, Billing &amp; Invoicing</h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '0.9rem' }}>
            Rapid billing workspace · Direct spot sales, retailer orders &amp; instant invoice generation
          </p>
        </div>
        <button
          type="button"
          onClick={resetFormDeliberately}
          style={{
            background: '#0e7490',
            color: '#fff',
            fontSize: '0.88rem',
            padding: '8px 16px',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <span>➕</span>
          <span>Start Fresh Bill</span>
        </button>
      </div>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'} style={{ marginBottom: '16px' }}>
          {notice.msg}
        </div>
      )}

      {/* Success banner after bill is issued */}
      {issuedSale && (
        <div className="card" style={{ background: '#f0fdf4', borderColor: '#86efac', marginBottom: '20px', padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                <span className="badge on" style={{ background: '#16a34a', color: '#fff' }}>
                  BILL ISSUED &amp; FULL PAYMENT RECORDED
                </span>
                <span style={{ fontSize: '0.82rem', color: '#15803d' }}>Stock auto-deducted</span>
              </div>
              <h2 style={{ color: '#14532d', margin: '4px 0 6px', fontSize: '1.4rem' }}>
                Bill #{issuedSale.sale.bill_number}
              </h2>
              <p style={{ margin: 0, color: '#166534', fontSize: '0.95rem' }}>
                Customer: <strong>{issuedSale.sale.customer_name_snapshot}</strong> · Total:{' '}
                <strong style={{ fontSize: '1.1rem' }}>₹{issuedSale.sale.bill_total.toFixed(2)}</strong> · Mode:{' '}
                <strong>{issuedSale.sale.payment_status}</strong>
              </p>

              {/* WhatsApp instant share bar */}
              <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <input
                  type="tel"
                  placeholder="WhatsApp Mobile (e.g. 98260XXXXX)"
                  value={customShareMobile}
                  onChange={(e) => setCustomShareMobile(e.target.value)}
                  style={{ padding: '6px 10px', fontSize: '0.85rem', width: '220px' }}
                />
                <a
                  href={getWhatsAppLink(issuedSale.sale, customShareMobile)}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                    borderRadius: '6px',
                    background: '#25D366',
                    color: '#fff',
                    fontWeight: 600,
                    fontSize: '0.85rem',
                    textDecoration: 'none',
                  }}
                >
                  <span>💬</span>
                  <span>Share on WhatsApp</span>
                </a>
              </div>
            </div>

            <div className="actions" style={{ gap: '10px', flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={() => {
                  const saleData = getSaleWithItems(issuedSale.sale.sale_id);
                  if (saleData) generateInvoicePdf(saleData.sale, saleData.items);
                }}
                style={{ background: '#15803d', color: '#fff', padding: '8px 14px' }}
              >
                📄 Download PDF
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  const saleData = getSaleWithItems(issuedSale.sale.sale_id);
                  if (saleData) setViewingSaleData(saleData);
                }}
                style={{ padding: '8px 14px' }}
              >
                👁️ Inspect
              </button>
              <button
                type="button"
                onClick={resetFormDeliberately}
                style={{ background: '#0e7490', color: '#fff', padding: '8px 14px' }}
              >
                ➕ Next Bill
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Billing Form Card */}
      <div className="card" style={{ marginBottom: '24px' }}>
        {/* Step 1: Sale Type Selection */}
        <div style={{ marginBottom: '18px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#334155', letterSpacing: '0.03em' }}>
              1. SALE TYPE
            </span>
            <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
              Preference saved for this session
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '8px' }}>
            {SALE_TYPES.map(({ type, label, desc }) => {
              const isSelected = salesType === type;
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => handleSaleTypeChange(type)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: isSelected ? '2px solid #047857' : '1px solid #cbd5e1',
                    background: isSelected ? '#ecfdf5' : '#ffffff',
                    color: isSelected ? '#065f46' : '#334155',
                    fontWeight: isSelected ? 700 : 500,
                    textAlign: 'left',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease-in-out',
                  }}
                >
                  <div style={{ fontSize: '0.95rem' }}>{label}</div>
                  <div style={{ fontSize: '0.72rem', color: isSelected ? '#047857' : '#64748b', marginTop: '2px' }}>
                    {desc}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Step 2: Customer Mode & Selection */}
        <div style={{ background: '#f8fafc', padding: '16px', borderRadius: '10px', border: '1px solid #e2e8f0', marginBottom: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#334155', letterSpacing: '0.03em' }}>
              2. BUYER &amp; CUSTOMER
            </span>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                onClick={() => {
                  invalidateDraftKey();
                  setCustomerMode('walkin');
                  setCustomerId('');
                }}
                style={{
                  padding: '6px 14px',
                  fontSize: '0.85rem',
                  borderRadius: '6px',
                  border: customerMode === 'walkin' ? '2px solid #0f766e' : '1px solid #cbd5e1',
                  background: customerMode === 'walkin' ? '#ccfbf1' : '#ffffff',
                  color: customerMode === 'walkin' ? '#115e59' : '#475569',
                  fontWeight: customerMode === 'walkin' ? 700 : 500,
                }}
              >
                ⚡ Quick Walk-in (No Account)
              </button>
              <button
                type="button"
                onClick={() => {
                  invalidateDraftKey();
                  setCustomerMode('registered');
                  if (activeCustomers[0] && !customerId) {
                    setCustomerId(activeCustomers[0].customer_id);
                  }
                }}
                style={{
                  padding: '6px 14px',
                  fontSize: '0.85rem',
                  borderRadius: '6px',
                  border: customerMode === 'registered' ? '2px solid #0f766e' : '1px solid #cbd5e1',
                  background: customerMode === 'registered' ? '#ccfbf1' : '#ffffff',
                  color: customerMode === 'registered' ? '#115e59' : '#475569',
                  fontWeight: customerMode === 'registered' ? 700 : 500,
                }}
              >
                🏪 Saved Customer
              </button>
            </div>
          </div>

          {customerMode === 'walkin' ? (
            <div>
              <p style={{ margin: '0 0 10px', fontSize: '0.82rem', color: '#64748b' }}>
                Quick retail billing without creating a customer account. Buyer details are completely optional.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
                <label style={{ margin: 0 }}>
                  <span style={{ fontSize: '0.8rem', color: '#475569', fontWeight: 600 }}>Buyer Name (Optional)</span>
                  <input
                    type="text"
                    maxLength={100}
                    placeholder="e.g. Cash Counter / Walk-in Customer"
                    value={walkInName}
                    onChange={(e) => {
                      invalidateDraftKey();
                      setWalkInName(e.target.value);
                    }}
                    style={{ width: '100%', marginTop: '3px', padding: '8px 10px' }}
                  />
                </label>
                <label style={{ margin: 0 }}>
                  <span style={{ fontSize: '0.8rem', color: '#475569', fontWeight: 600 }}>
                    Mobile Number (Optional)
                  </span>
                  <input
                    type="tel"
                    maxLength={20}
                    placeholder="10-digit mobile for WhatsApp bill"
                    value={walkInMobile}
                    onChange={(e) => {
                      invalidateDraftKey();
                      setWalkInMobile(e.target.value);
                    }}
                    style={{ width: '100%', marginTop: '3px', padding: '8px 10px' }}
                  />
                </label>
              </div>
            </div>
          ) : (
            <div>
              <div style={{ marginBottom: '8px' }}>
                <input
                  type="text"
                  placeholder="🔍 Search registered customer by shop name, owner, or mobile..."
                  value={customerSearchQuery}
                  onChange={(e) => setCustomerSearchQuery(e.target.value)}
                  style={{ width: '100%', padding: '9px 12px', fontSize: '0.9rem', borderRadius: '6px' }}
                />
              </div>

              {selectedCustomer ? (
                <div
                  style={{
                    background: '#ecfdf5',
                    border: '1px solid #a7f3d0',
                    padding: '12px 16px',
                    borderRadius: '8px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '8px',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong style={{ color: '#065f46', fontSize: '1.05rem' }}>{selectedCustomer.shop_name}</strong>
                      <span style={{ fontSize: '0.78rem', background: '#d1fae5', color: '#065f46', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
                        {selectedCustomer.customer_type}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.82rem', color: '#047857', marginTop: '2px' }}>
                      {selectedCustomer.locality_area || selectedCustomer.city || 'No area specified'}{' '}
                      {selectedCustomer.shopkeeper_name ? `· Contact: ${selectedCustomer.shopkeeper_name}` : ''}{' '}
                      {selectedCustomer.mobile ? `· 📞 ${selectedCustomer.mobile}` : ''}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      invalidateDraftKey();
                      setCustomerId('');
                      setCustomerSearchQuery('');
                    }}
                    style={{ padding: '5px 12px', fontSize: '0.82rem' }}
                  >
                    Change Customer
                  </button>
                </div>
              ) : (
                <div style={{ maxHeight: '190px', overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: '6px', background: '#fff' }}>
                  {filteredCustomers.length > 0 ? (
                    filteredCustomers.map((c) => (
                      <div
                        key={c.customer_id}
                        onClick={() => {
                          invalidateDraftKey();
                          setCustomerId(c.customer_id);
                          handleSaleTypeChange(c.customer_type || 'RETAILER');
                          setCustomerSearchQuery('');
                        }}
                        style={{
                          padding: '10px 14px',
                          borderBottom: '1px solid #f1f5f9',
                          cursor: 'pointer',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          transition: 'background 0.1s',
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = '#f8fafc')}
                        onMouseLeave={(e) => (e.currentTarget.style.background = '#fff')}
                      >
                        <div>
                          <strong>{c.shop_name}</strong>
                          <span style={{ fontSize: '0.78rem', color: '#64748b', marginLeft: '8px' }}>
                            {c.locality_area || c.city || ''}
                          </span>
                          {c.mobile && (
                            <span style={{ fontSize: '0.78rem', color: '#0f766e', marginLeft: '6px' }}>
                              📞 {c.mobile}
                            </span>
                          )}
                        </div>
                        <span style={{ fontSize: '0.75rem', background: '#f1f5f9', padding: '3px 8px', borderRadius: '4px', color: '#475569' }}>
                          {c.customer_type}
                        </span>
                      </div>
                    ))
                  ) : (
                    <div style={{ padding: '16px', textAlign: 'center', color: '#64748b', fontSize: '0.88rem' }}>
                      No matching registered customer found. Try Quick Walk-in or add customer in Customers view.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Step 3: Fast Product Search & One-Tap Shortcuts */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#334155', letterSpacing: '0.03em' }}>
              3. ADD PRODUCTS TO BILL
            </span>
            <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
              Fast search or one-tap quick shortcuts
            </span>
          </div>

          {/* Fast Product Search Autocomplete Bar */}
          <div ref={productSearchContainerRef} style={{ position: 'relative', marginBottom: '12px' }}>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                placeholder="🔍 Instant Product Search by name, SKU, or category (e.g. Moong, Katran, 200g)..."
                value={productSearch}
                onFocus={() => setIsProductSearchOpen(true)}
                onChange={(e) => {
                  setProductSearch(e.target.value);
                  setIsProductSearchOpen(true);
                }}
                style={{ width: '100%', padding: '10px 14px', fontSize: '0.92rem', borderRadius: '6px' }}
              />
              {productSearch && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setProductSearch('');
                    setIsProductSearchOpen(false);
                  }}
                  style={{ padding: '8px 12px' }}
                >
                  Clear
                </button>
              )}
            </div>

            {isProductSearchOpen && matchingProducts.length > 0 && (
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  background: '#fff',
                  border: '1px solid #cbd5e1',
                  borderRadius: '8px',
                  boxShadow: '0 10px 25px rgba(0,0,0,0.1)',
                  zIndex: 50,
                  maxHeight: '260px',
                  overflowY: 'auto',
                  marginTop: '4px',
                }}
              >
                {matchingProducts.map((p) => {
                  const stock = getAvailableStock(p.product_id);
                  const defaultP = getDefaultPriceForProduct(p, salesType);
                  return (
                    <div
                      key={p.product_id}
                      onClick={() => handleSelectFromProductSearch(p.product_id)}
                      style={{
                        padding: '10px 14px',
                        borderBottom: '1px solid #f1f5f9',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = '#f0fdf4')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = '#fff')}
                    >
                      <div>
                        <strong>{p.product_name}</strong>
                        <span style={{ fontSize: '0.78rem', color: '#64748b', marginLeft: '8px' }}>
                          SKU: {p.sku} · Pack: {p.pack_weight_g}g
                        </span>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <strong style={{ color: '#047857' }}>₹{defaultP}</strong>
                        <div style={{ fontSize: '0.75rem', color: stock > 0 ? '#15803d' : '#b91c1c' }}>
                          Stock: {stock} {p.selling_unit}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Quick-add Shortcuts */}
          {popularShortcuts.length > 0 && (
            <div>
              <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '6px' }}>
                ⚡ POPULAR PRODUCTS (ONE-TAP QUICK ADD)
              </span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {popularShortcuts.map((p) => {
                  const stock = getAvailableStock(p.product_id);
                  const inCart = cart.find((l) => l.product_id === p.product_id);
                  return (
                    <button
                      key={p.product_id}
                      type="button"
                      onClick={() => addOrIncrementProduct(p.product_id)}
                      style={{
                        padding: '7px 12px',
                        fontSize: '0.82rem',
                        background: inCart ? '#ecfdf5' : '#ffffff',
                        border: inCart ? '1px solid #10b981' : '1px solid #cbd5e1',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                      }}
                    >
                      <span style={{ fontWeight: inCart ? 700 : 500 }}>➕ {p.product_name}</span>
                      <span style={{ fontSize: '0.72rem', color: stock > 0 ? '#0f766e' : '#b91c1c' }}>
                        ({stock})
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit}>
          {/* Step 4: Bill Items Table */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', flexWrap: 'wrap', gap: '8px' }}>
            <h3 style={{ margin: 0, fontSize: '1.1rem' }}>
              Bill Line Items ({cart.length}) · {totalPackets} Total Packets
            </h3>
            <span style={{ fontSize: '0.88rem', color: '#065f46', fontWeight: 700, background: '#d1fae5', padding: '3px 10px', borderRadius: '4px' }}>
              ⚖️ Total Weight: {totalQualifyingWeightKg.toFixed(2)} kg
            </span>
          </div>

          <div className="table-wrap" style={{ marginBottom: '14px' }}>
            <table>
              <thead>
                <tr>
                  <th style={{ minWidth: '240px' }}>Product &amp; SKU</th>
                  <th style={{ minWidth: '180px' }}>Quantity</th>
                  <th style={{ minWidth: '110px' }}>Price ₹</th>
                  <th style={{ minWidth: '110px' }}>Line Total</th>
                  <th style={{ width: '50px' }}></th>
                </tr>
              </thead>
              <tbody>
                {cart.map((line, index) => {
                  const lineTotal = (Number(line.quantity) || 0) * (Number(line.actual_unit_price) || 0);
                  const selectedProd = products.find((p) => p.product_id === line.product_id);
                  const avail = getAvailableStock(line.product_id);
                  const isStockShortage = avail < Number(line.quantity);

                  return (
                    <tr key={index}>
                      <td>
                        <select
                          value={line.product_id}
                          onChange={(e) => updateLine(index, { product_id: e.target.value })}
                          required
                          style={{ width: '100%', padding: '7px 8px', borderRadius: '4px' }}
                        >
                          {activeProducts.map((p) => {
                            const pStock = getAvailableStock(p.product_id);
                            return (
                              <option key={p.product_id} value={p.product_id}>
                                {p.product_name} · {p.sku} (Stock: {pStock} {p.selling_unit})
                              </option>
                            );
                          })}
                        </select>
                        {selectedProd && (
                          <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '3px', display: 'flex', gap: '8px' }}>
                            <span>Pack: {selectedProd.pack_weight_g}g</span>
                            <span>·</span>
                            <span>Unit: {selectedProd.selling_unit}</span>
                            {isStockShortage && (
                              <span style={{ color: '#b91c1c', fontWeight: 600 }}>
                                ⚠️ Stock is {avail}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => updateLine(index, { quantity: Math.max(1, line.quantity - 1) })}
                            style={{ padding: '4px 8px', fontSize: '0.9rem', minWidth: '28px' }}
                            title="Decrease 1"
                          >
                            -
                          </button>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            required
                            value={line.quantity}
                            onFocus={(e) => e.target.select()}
                            onChange={(e) =>
                              updateLine(index, {
                                quantity: Math.max(1, parseInt(e.target.value, 10) || 1),
                              })
                            }
                            style={{ width: '60px', textAlign: 'center', padding: '6px 4px', fontWeight: 600 }}
                          />
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => updateLine(index, { quantity: line.quantity + 1 })}
                            style={{ padding: '4px 8px', fontSize: '0.9rem', minWidth: '28px' }}
                            title="Add 1"
                          >
                            +
                          </button>
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => updateLine(index, { quantity: line.quantity + 5 })}
                            style={{ padding: '4px 6px', fontSize: '0.75rem' }}
                            title="Add 5 packets"
                          >
                            +5
                          </button>
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => updateLine(index, { quantity: line.quantity + 10 })}
                            style={{ padding: '4px 6px', fontSize: '0.75rem' }}
                            title="Add 10 packets"
                          >
                            +10
                          </button>
                        </div>
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="0.5"
                          required
                          value={line.actual_unit_price}
                          onFocus={(e) => e.target.select()}
                          onChange={(e) =>
                            updateLine(index, { actual_unit_price: Number(e.target.value) })
                          }
                          style={{ width: '85px', padding: '6px', fontWeight: 600 }}
                        />
                      </td>
                      <td>
                        <strong style={{ color: '#166534', fontSize: '1.05rem' }}>
                          ₹{lineTotal.toFixed(2)}
                        </strong>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => removeLine(index)}
                          disabled={cart.length <= 1}
                          style={{ padding: '4px 8px', fontSize: '0.85rem', color: '#b91c1c' }}
                          title="Remove Line"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div style={{ marginBottom: '20px' }}>
            <button
              type="button"
              className="secondary"
              onClick={addLine}
              style={{ fontSize: '0.88rem', padding: '6px 14px' }}
            >
              ➕ Add Another Product Line
            </button>
          </div>

          {/* Step 5: Large Payment Method Buttons */}
          <div style={{ marginBottom: '18px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#334155', display: 'block', marginBottom: '8px', letterSpacing: '0.03em' }}>
              4. PAYMENT METHOD
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px' }}>
              {PAYMENT_METHODS.map(({ method, label, icon }) => {
                const isSelected = paymentMethod === method;
                return (
                  <button
                    key={method}
                    type="button"
                    onClick={() => {
                      invalidateDraftKey();
                      setPaymentMethod(method);
                    }}
                    style={{
                      padding: '14px 16px',
                      borderRadius: '8px',
                      border: isSelected ? '2px solid #0f766e' : '1px solid #cbd5e1',
                      background: isSelected ? '#f0fdfa' : '#ffffff',
                      color: isSelected ? '#115e59' : '#334155',
                      fontWeight: isSelected ? 700 : 500,
                      textAlign: 'center',
                      cursor: 'pointer',
                      fontSize: '0.95rem',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <span style={{ fontSize: '1.3rem', display: 'block', marginBottom: '4px' }}>
                      {icon}
                    </span>
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {paymentMethod !== 'CASH' && (
            <div style={{ marginBottom: '18px' }}>
              <label style={{ margin: 0 }}>
                <span style={{ fontSize: '0.82rem', color: '#475569', fontWeight: 600 }}>
                  UPI / Bank Reference (UTR or Slip Number)
                </span>
                <input
                  type="text"
                  maxLength={150}
                  placeholder="e.g. UPI Ref / Bank UTR / Payment slip"
                  value={paymentReference}
                  onChange={(e) => {
                    invalidateDraftKey();
                    setPaymentReference(e.target.value);
                  }}
                  style={{ width: '100%', marginTop: '3px', padding: '8px 10px' }}
                />
              </label>
            </div>
          )}

          {/* Step 6: Summary, Discount & Total */}
          <div style={{ background: '#f8fafc', padding: '18px', borderRadius: '10px', border: '1px solid #e2e8f0', marginBottom: '20px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px', alignItems: 'center' }}>
              <div>
                <span style={{ fontSize: '0.85rem', color: '#64748b' }}>Items Subtotal:</span>
                <div style={{ fontSize: '1.2rem', fontWeight: 600, color: '#1e293b' }}>
                  ₹{subtotal.toFixed(2)}
                </div>
              </div>

              <div>
                <label style={{ margin: 0 }}>
                  <span style={{ fontSize: '0.82rem', color: '#64748b' }}>Discount ₹ (Optional):</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={discountAmount || ''}
                    placeholder="0"
                    onFocus={(e) => e.target.select()}
                    onChange={(e) => {
                      invalidateDraftKey();
                      setDiscountAmount(Math.max(0, Number(e.target.value) || 0));
                    }}
                    style={{ width: '100%', marginTop: '3px', padding: '7px 10px' }}
                  />
                </label>
              </div>

              <div style={{ background: '#ecfdf5', padding: '12px 16px', borderRadius: '8px', textAlign: 'right', border: '1px solid #a7f3d0' }}>
                <span style={{ fontSize: '0.85rem', color: '#047857', fontWeight: 700 }}>FINAL BILL TOTAL</span>
                <div style={{ fontSize: '1.75rem', fontWeight: 800, color: '#065f46' }}>
                  ₹{billTotal.toFixed(2)}
                </div>
                <div style={{ fontSize: '0.78rem', color: '#047857', marginTop: '2px' }}>
                  Full payment will be marked as {paymentMethod}
                </div>
              </div>
            </div>

            <div style={{ marginTop: '12px' }}>
              <label style={{ margin: 0 }}>
                <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Bill Notes / Remarks (Optional):</span>
                <input
                  type="text"
                  maxLength={500}
                  placeholder="Delivery remarks, driver details, or shop notes..."
                  value={notes}
                  onChange={(e) => {
                    invalidateDraftKey();
                    setNotes(e.target.value);
                  }}
                  style={{ width: '100%', marginTop: '3px', padding: '7px 10px' }}
                />
              </label>
            </div>
          </div>

          {/* Action Submit Button */}
          <div style={{ display: 'flex', gap: '8px', flexDirection: 'column' }}>
            <button
              type="submit"
              disabled={isSubmitting || !isGoogleSheetsConnected || !persistentWritesEnabled}
              style={{
                width: '100%',
                padding: '16px 24px',
                fontSize: '1.15rem',
                fontWeight: 700,
                background: (!isGoogleSheetsConnected || !persistentWritesEnabled)
                  ? '#64748b'
                  : submissionIdempotencyKey
                  ? '#b45309'
                  : '#047857',
                color: '#fff',
                borderRadius: '8px',
                cursor: (isSubmitting || !isGoogleSheetsConnected || !persistentWritesEnabled) ? 'not-allowed' : 'pointer',
                opacity: (isSubmitting || !isGoogleSheetsConnected || !persistentWritesEnabled) ? 0.75 : 1,
                boxShadow: submissionIdempotencyKey
                  ? '0 4px 12px rgba(180, 83, 9, 0.25)'
                  : '0 4px 12px rgba(4, 120, 87, 0.25)',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                gap: '10px',
              }}
            >
              {(!isGoogleSheetsConnected || !persistentWritesEnabled) ? (
                <span>🔒 Google Sheets Disconnected — Bill Creation Locked</span>
              ) : isSubmitting ? (
                <span>⏳ Processing &amp; Saving Bill...</span>
              ) : submissionIdempotencyKey ? (
                <span>🔄 Retry Bill Submission Safely (₹{billTotal.toFixed(2)})</span>
              ) : (
                <span>✅ Save Bill &amp; Record Full Payment (₹{billTotal.toFixed(2)})</span>
              )}
            </button>
            {(!isGoogleSheetsConnected || !persistentWritesEnabled) && (
              <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: '#b91c1c', textAlign: 'center' }}>
                ⚠️ Google Sheets persistent storage is disconnected. New bills are locked to prevent loss of sales records.
              </p>
            )}
            {submissionIdempotencyKey && !isSubmitting && (
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 2px' }}>
                <span style={{ fontSize: '0.8rem', color: '#b45309', fontWeight: 600 }}>
                  🔒 Bill draft preserved with duplicate protection
                </span>
                <button
                  type="button"
                  onClick={resetFormDeliberately}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#64748b',
                    fontSize: '0.82rem',
                    cursor: 'pointer',
                    textDecoration: 'underline',
                    padding: 0,
                  }}
                >
                  Discard draft &amp; start new bill
                </button>
              </div>
            )}
          </div>
        </form>
      </div>

      {/* Recent Bills Register */}
      <div className="card">
        <div className="toolbar" style={{ flexWrap: 'wrap', gap: '8px', marginBottom: '14px' }}>
          <h2 style={{ margin: 0 }}>
            Recent Issued Bills <span className="count">{filteredSales.length}</span>
          </h2>
          <input
            placeholder="🔍 Search bill number, customer, or type..."
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            style={{ minWidth: '240px', padding: '7px 12px' }}
          />
        </div>

        {filteredSales.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Bill #</th>
                  <th>Date</th>
                  <th>Customer</th>
                  <th>Sale Type</th>
                  <th>Total</th>
                  <th>Payment</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredSales.map((s) => (
                  <tr key={s.sale_id}>
                    <td>
                      <code style={{ fontSize: '0.85rem', fontWeight: 600 }}>{s.bill_number}</code>
                    </td>
                    <td>{new Date(s.sale_datetime).toLocaleDateString('en-IN')}</td>
                    <td>
                      <strong>{s.customer_name_snapshot}</strong>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.8rem', background: '#f1f5f9', padding: '3px 8px', borderRadius: '4px', color: '#475569' }}>
                        {s.sales_type}
                      </span>
                    </td>
                    <td>
                      <strong style={{ color: '#047857', fontSize: '0.98rem' }}>₹{s.bill_total.toFixed(2)}</strong>
                    </td>
                    <td>
                      <span className="badge on">PAID</span>
                    </td>
                    <td>
                      <div className="actions" style={{ gap: '6px' }}>
                        <button
                          type="button"
                          className="secondary"
                          style={{ padding: '4px 8px', fontSize: '0.8rem' }}
                          onClick={() => {
                            const data = getSaleWithItems(s.sale_id);
                            if (data) generateInvoicePdf(data.sale, data.items);
                          }}
                          title="Download PDF Invoice"
                        >
                          📄 PDF
                        </button>
                        <a
                          href={getWhatsAppLink(s)}
                          target="_blank"
                          rel="noreferrer"
                          style={{
                            padding: '4px 8px',
                            fontSize: '0.8rem',
                            borderRadius: '4px',
                            background: '#25D366',
                            color: '#fff',
                            textDecoration: 'none',
                            display: 'inline-flex',
                            alignItems: 'center',
                          }}
                          title="Share on WhatsApp"
                        >
                          💬 Share
                        </a>
                        <button
                          type="button"
                          className="secondary"
                          style={{ padding: '4px 8px', fontSize: '0.8rem' }}
                          onClick={() => {
                            const data = getSaleWithItems(s.sale_id);
                            if (data) setViewingSaleData(data);
                          }}
                          title="Inspect Bill"
                        >
                          👁️ Inspect
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ padding: '14px 0', textAlign: 'center' }}>
            No matching sales records found.
          </p>
        )}
      </div>

      {viewingSaleData && (
        <InvoiceModal
          sale={viewingSaleData.sale}
          items={viewingSaleData.items}
          onClose={() => setViewingSaleData(null)}
        />
      )}
    </div>
  );
};
