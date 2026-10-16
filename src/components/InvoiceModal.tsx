import React, { useState } from 'react';
import { Sale, SaleItem } from '../types';
import { generateInvoicePdf } from '../utils/generateInvoicePdf';

interface InvoiceModalProps {
  sale: Sale;
  items: SaleItem[];
  onClose: () => void;
}

export const InvoiceModal: React.FC<InvoiceModalProps> = ({ sale, items, onClose }) => {
  const [phoneForShare, setPhoneForShare] = useState(
    sale.customer_mobile && sale.customer_mobile !== 'None' ? sale.customer_mobile : ''
  );

  const getWhatsAppUrl = () => {
    const cleanMobile = phoneForShare.replace(/\D/g, '').slice(-10);
    const itemsList = items
      .map(
        (it, idx) =>
          `${idx + 1}. ${it.product_name_snapshot || it.sku_snapshot} (${it.quantity} ${it.unit || 'pkt'}) - ₹${Number(it.line_total).toFixed(2)}`
      )
      .join('\n');

    const msg = `*KAWAD SWAD UDHYOG - SALES INVOICE*\n--------------------------------\nBill No: *${sale.bill_number}*\nDate: ${new Date(sale.sale_datetime).toLocaleDateString('en-IN')}\nCustomer: *${sale.customer_name_snapshot}*\nType: ${sale.sales_type}\n\n*Items:*\n${itemsList}\n--------------------------------\n*Bill Total: ₹${Number(sale.bill_total).toFixed(2)}*\nPayment: *PAID (${sale.payment_status})*\n\nThank you for business with Kawad Swad Udhyog! 🙏`;

    const encoded = encodeURIComponent(msg);
    if (cleanMobile.length === 10) {
      return `https://wa.me/91${cleanMobile}?text=${encoded}`;
    }
    return `https://wa.me/?text=${encoded}`;
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <span style={{ fontSize: '0.8rem', color: '#176b52', fontWeight: 700, textTransform: 'uppercase' }}>
              Kawad Swad Udhyog
            </span>
            <h2 style={{ margin: 0 }}>Bill #{sale.bill_number}</h2>
          </div>
          <button className="secondary" onClick={onClose} style={{ padding: '6px 12px' }}>
            ✕ Close
          </button>
        </div>

        <div style={{ background: '#f8faf9', padding: '14px', borderRadius: '10px', marginBottom: '16px', fontSize: '0.9rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px' }}>
            <div>
              <strong>Customer:</strong> {sale.customer_name_snapshot || 'Walk-in Customer'}
            </div>
            {sale.customer_mobile && sale.customer_mobile !== 'None' && (
              <div>
                <strong>Mobile:</strong> {sale.customer_mobile}
              </div>
            )}
            {sale.customer_gstin && sale.customer_gstin !== 'None' && (
              <div>
                <strong>GSTIN:</strong> {sale.customer_gstin}
              </div>
            )}
            <div>
              <strong>Date:</strong> {new Date(sale.sale_datetime).toLocaleString('en-IN')}
            </div>
            <div>
              <strong>Sale Type:</strong> {sale.sales_type}
            </div>
            <div>
              <strong>Payment Status:</strong>{' '}
              <span className="badge on">PAID ({sale.payment_status})</span>
            </div>
          </div>
        </div>

        <div className="table-wrap" style={{ marginBottom: '16px' }}>
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th style={{ textAlign: 'center' }}>Qty</th>
                <th style={{ textAlign: 'right' }}>Unit Price</th>
                <th style={{ textAlign: 'right' }}>Line Total</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.sale_item_id}>
                  <td>
                    <strong>{it.product_name_snapshot || it.sku_snapshot}</strong>
                    <div className="muted" style={{ fontSize: '0.78rem' }}>
                      SKU: {it.sku_snapshot} {it.pack_weight_g ? `· ${it.pack_weight_g}g` : ''}
                    </div>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    {it.quantity} {it.unit || 'pkt'}
                  </td>
                  <td style={{ textAlign: 'right' }}>₹{Number(it.actual_unit_price).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 600 }}>₹{Number(it.line_total).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ textAlign: 'right', marginBottom: '16px', paddingRight: '8px' }}>
          <div style={{ fontSize: '0.9rem', color: '#66746f' }}>
            Subtotal: ₹{Number(sale.subtotal).toFixed(2)}
          </div>
          {sale.discount_amount > 0 && (
            <div style={{ fontSize: '0.9rem', color: '#b42318' }}>
              Discount: -₹{Number(sale.discount_amount).toFixed(2)}
            </div>
          )}
          <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#183b35', marginTop: '6px' }}>
            Bill Total: ₹{Number(sale.bill_total).toFixed(2)}
          </div>
        </div>

        {/* WhatsApp Mobile Share bar */}
        <div
          style={{
            background: '#f0fdf4',
            border: '1px solid #bbf7d0',
            borderRadius: '8px',
            padding: '12px 14px',
            marginBottom: '18px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '10px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: '1', minWidth: '220px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#166534' }}>
              WhatsApp Bill Share:
            </span>
            <input
              type="tel"
              placeholder="10-digit customer mobile"
              value={phoneForShare}
              onChange={(e) => setPhoneForShare(e.target.value)}
              style={{ padding: '6px 10px', fontSize: '0.85rem', width: '180px' }}
            />
          </div>
          <a
            href={getWhatsAppUrl()}
            target="_blank"
            rel="noreferrer"
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              background: '#25D366',
              color: '#fff',
              fontSize: '0.85rem',
              fontWeight: 600,
              textDecoration: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>💬</span>
            <span>Send on WhatsApp</span>
          </a>
        </div>

        <div className="actions" style={{ justifyContent: 'flex-end', gap: '10px' }}>
          <button
            onClick={() => generateInvoicePdf(sale, items)}
            style={{ background: '#176b52', color: 'white' }}
          >
            📄 Download Invoice PDF
          </button>
          <button className="secondary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
