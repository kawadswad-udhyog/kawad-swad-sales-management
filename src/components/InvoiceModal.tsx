import React from 'react';
import { Sale, SaleItem } from '../types';
import { generateInvoicePdf } from '../utils/generateInvoicePdf';

interface InvoiceModalProps {
  sale: Sale;
  items: SaleItem[];
  onClose: () => void;
}

export const InvoiceModal: React.FC<InvoiceModalProps> = ({ sale, items, onClose }) => {
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
              <strong>Customer:</strong> {sale.customer_name_snapshot}
            </div>
            <div>
              <strong>Date:</strong> {new Date(sale.sale_datetime).toLocaleString('en-IN')}
            </div>
            <div>
              <strong>Sale Type:</strong> {sale.sales_type}
            </div>
            <div>
              <strong>Status:</strong>{' '}
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

        <div style={{ textAlign: 'right', marginBottom: '20px', paddingRight: '8px' }}>
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

        <div className="actions" style={{ justifyContent: 'flex-end' }}>
          <button
            onClick={() => generateInvoicePdf(sale, items)}
            style={{ background: '#176b52', color: 'white' }}
          >
            Download Invoice PDF
          </button>
          <button className="secondary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
