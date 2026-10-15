import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { CustomerType, Sale, SaleItem } from '../types';
import { generateInvoicePdf } from '../utils/generateInvoicePdf';
import { InvoiceModal } from '../components/InvoiceModal';

interface CartLine {
  product_id: string;
  quantity: number;
  actual_unit_price: number;
}

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
  } = useStore();

  const activeCustomers = customers.filter((c) => c.active);
  const activeProducts = products.filter((p) => p.active);

  const [customerId, setCustomerId] = useState(activeCustomers[0]?.customer_id || '');
  const [salesType, setSalesType] = useState<CustomerType>('RETAILER');
  const [paymentMethod, setPaymentMethod] = useState<'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER'>('CASH');
  const [paymentReference, setPaymentReference] = useState('');
  const [discountAmount, setDiscountAmount] = useState<number>(0);
  const [notes, setNotes] = useState('');
  const [searchFilter, setSearchFilter] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);
  const [issuedSale, setIssuedSale] = useState<{ sale: Sale; paymentId: string } | null>(null);
  const [viewingSaleData, setViewingSaleData] = useState<{ sale: Sale; items: SaleItem[] } | null>(null);

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

  // Cart state
  const [cart, setCart] = useState<CartLine[]>([
    {
      product_id: activeProducts[0]?.product_id || '',
      quantity: 1,
      actual_unit_price: 55,
    },
  ]);

  const addLine = () => {
    if (activeProducts.length === 0) {
      setNotice({ msg: 'Add an active product before creating a bill.', error: true });
      return;
    }
    setCart((prev) => [
      ...prev,
      {
        product_id: activeProducts[0].product_id,
        quantity: 1,
        actual_unit_price: 50,
      },
    ]);
  };

  const removeLine = (index: number) => {
    if (cart.length <= 1) return;
    setCart((prev) => prev.filter((_, i) => i !== index));
  };

  const updateLine = (index: number, updates: Partial<CartLine>) => {
    setCart((prev) =>
      prev.map((line, i) => (i === index ? { ...line, ...updates } : line))
    );
  };

  // Calculations
  const subtotal = cart.reduce(
    (sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.actual_unit_price) || 0),
    0
  );
  const billTotal = Math.max(0, subtotal - (Number(discountAmount) || 0));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);
    setIssuedSale(null);

    if (cart.length === 0) {
      setNotice({ msg: 'Add at least one product line.', error: true });
      return;
    }

    if (discountAmount > subtotal) {
      setNotice({ msg: 'Discount cannot exceed subtotal.', error: true });
      return;
    }

    const confirmMsg = `Confirm bill total ₹${billTotal.toFixed(2)} and confirm full payment has been received via ${paymentMethod}?`;
    if (!window.confirm(confirmMsg)) return;

    try {
      const idempotencyKey = `IDEMP-${Date.now()}-${customerId.slice(-4)}`;
      const result = await createSale({
        customer_id: customerId,
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

      setIssuedSale({ sale: result.sale, paymentId: result.paymentId || '' });
      setNotice({ msg: `Bill #${result.sale.bill_number} issued, full payment recorded, and stock automatically deducted.` });

      // Reset cart
      setCart([
        {
          product_id: activeProducts[0]?.product_id || '',
          quantity: 1,
          actual_unit_price: 50,
        },
      ]);
      setDiscountAmount(0);
      setPaymentReference('');
      setNotes('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to issue bill';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  // Filter bills for salesman vs manager
  const userVisibleSales = currentUser?.role === 'SALESMAN'
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
      <h1>Sales, Billing & Payments</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      {issuedSale && (
        <div className="card" style={{ background: '#e5f6ed', borderColor: '#b9dfcb' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            <div>
              <h2 style={{ color: '#176b52', margin: 0 }}>
                Bill Issued: {issuedSale.sale.bill_number}
              </h2>
              <p style={{ margin: '4px 0 0', color: '#183b35' }}>
                Customer: <strong>{issuedSale.sale.customer_name_snapshot}</strong> · Total:{' '}
                <strong>₹{issuedSale.sale.bill_total.toFixed(2)}</strong> · Payment:{' '}
                <span className="badge on">PAID</span>
              </p>
            </div>
            <div className="actions">
              <button
                type="button"
                onClick={() => {
                  const saleData = getSaleWithItems(issuedSale.sale.sale_id);
                  if (saleData) generateInvoicePdf(saleData.sale, saleData.items);
                }}
              >
                Download Invoice PDF
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  const saleData = getSaleWithItems(issuedSale.sale.sale_id);
                  if (saleData) setViewingSaleData(saleData);
                }}
              >
                Inspect Bill
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Create bill & issue payment memo</h2>
        <form onSubmit={handleSubmit}>
          <div className="inline" style={{ marginBottom: '16px' }}>
            <label>
              Customer / trade partner
              <select
                required
                value={customerId}
                onChange={(e) => setCustomerId(e.target.value)}
              >
                {activeCustomers.map((c) => (
                  <option key={c.customer_id} value={c.customer_id}>
                    {c.shop_name} · {c.customer_type} ({c.customer_id})
                  </option>
                ))}
              </select>
            </label>

            <label>
              Sale type
              <select
                value={salesType}
                onChange={(e) => setSalesType(e.target.value as CustomerType)}
              >
                <option value="RETAIL">RETAIL</option>
                <option value="RETAILER">RETAILER</option>
                <option value="WHOLESALER">WHOLESALER</option>
                <option value="DISTRIBUTOR">DISTRIBUTOR</option>
              </select>
            </label>

            <label>
              Payment method
              <select
                value={paymentMethod}
                onChange={(e) =>
                  setPaymentMethod(
                    e.target.value as 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'OTHER'
                  )
                }
              >
                <option value="CASH">Cash</option>
                <option value="UPI">UPI</option>
                <option value="BANK_TRANSFER">Bank transfer</option>
                <option value="OTHER">Other approved method</option>
              </select>
            </label>

            <label>
              Payment reference
              <input
                maxLength={150}
                placeholder="UPI / bank ref or Cash slip"
                value={paymentReference}
                onChange={(e) => setPaymentReference(e.target.value)}
              />
            </label>
          </div>

          <h3>Order Items</h3>
          <div className="table-wrap" style={{ marginBottom: '12px' }}>
            <table>
              <thead>
                <tr>
                  <th style={{ minWidth: '220px' }}>Product</th>
                  <th style={{ minWidth: '100px' }}>Quantity</th>
                  <th style={{ minWidth: '130px' }}>Actual unit price ₹</th>
                  <th style={{ minWidth: '110px' }}>Line total</th>
                  <th style={{ width: '80px' }}></th>
                </tr>
              </thead>
              <tbody>
                {cart.map((line, index) => {
                  const lineTotal =
                    (Number(line.quantity) || 0) * (Number(line.actual_unit_price) || 0);

                  return (
                    <tr key={index}>
                      <td>
                        <select
                          value={line.product_id}
                          onChange={(e) =>
                            updateLine(index, { product_id: e.target.value })
                          }
                          required
                        >
                          {activeProducts.map((p) => {
                            const avail = getAvailableStock(p.product_id);
                            return (
                              <option key={p.product_id} value={p.product_id}>
                                {p.product_name} · {p.sku} (In stock: {avail} {p.selling_unit})
                              </option>
                            );
                          })}
                        </select>
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0.001"
                          step="0.001"
                          required
                          value={line.quantity}
                          onChange={(e) =>
                            updateLine(index, { quantity: Number(e.target.value) })
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          required
                          value={line.actual_unit_price}
                          onChange={(e) =>
                            updateLine(index, {
                              actual_unit_price: Number(e.target.value),
                            })
                          }
                        />
                      </td>
                      <td>
                        <strong>₹{lineTotal.toFixed(2)}</strong>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => removeLine(index)}
                          disabled={cart.length <= 1}
                          style={{ padding: '4px 8px', fontSize: '0.8rem' }}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div style={{ marginBottom: '18px' }}>
            <button type="button" className="secondary" onClick={addLine}>
              + Add product line
            </button>
          </div>

          <div className="inline" style={{ alignItems: 'center' }}>
            <label>
              Discount ₹
              <input
                type="number"
                min="0"
                step="0.01"
                value={discountAmount}
                onChange={(e) => setDiscountAmount(Number(e.target.value))}
              />
            </label>

            <label style={{ gridColumn: 'span 2' }}>
              Bill notes
              <input
                maxLength={500}
                placeholder="Remarks or special instructions..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </label>

            <div className="metric" style={{ margin: 0, padding: '12px 18px' }}>
              <span>Bill total</span>
              <strong style={{ fontSize: '1.4rem' }}>₹{billTotal.toFixed(2)}</strong>
            </div>
          </div>

          <p className="muted" style={{ margin: '14px 0' }}>
            Only issue the bill after the full amount has been received. Prices are the actual prices
            charged on this sale. Issued bills cannot be silently overwritten.
          </p>

          <button type="submit" style={{ padding: '12px 22px', fontSize: '1rem' }}>
            Issue bill + record full payment
          </button>
        </form>
      </div>

      <div className="card">
        <div className="toolbar">
          <h2>
            Recent Bills <span className="count">{filteredSales.length}</span>
          </h2>
          <input
            placeholder="Search bill number or customer..."
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
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
                  <th>Type</th>
                  <th>Total</th>
                  <th>Payment</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredSales.map((s) => (
                  <tr key={s.sale_id}>
                    <td>
                      <code>{s.bill_number}</code>
                    </td>
                    <td>{new Date(s.sale_datetime).toLocaleDateString('en-IN')}</td>
                    <td>
                      <strong>{s.customer_name_snapshot}</strong>
                    </td>
                    <td>{s.sales_type}</td>
                    <td>
                      <strong>₹{s.bill_total.toFixed(2)}</strong>
                    </td>
                    <td>
                      <span className="badge on">PAID</span>
                    </td>
                    <td>
                      <div className="actions">
                        <button
                          type="button"
                          className="secondary"
                          style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                          onClick={() => {
                            const data = getSaleWithItems(s.sale_id);
                            if (data) generateInvoicePdf(data.sale, data.items);
                          }}
                        >
                          PDF
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                          onClick={() => {
                            const data = getSaleWithItems(s.sale_id);
                            if (data) setViewingSaleData(data);
                          }}
                        >
                          View
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No sales records found.</p>
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
