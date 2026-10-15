import { jsPDF } from 'jspdf';
import { Sale, SaleItem } from '../types';

export function generateInvoicePdf(sale: Sale, items: SaleItem[]): void {
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'mm',
    format: 'a4',
  });

  const primaryColor = [24, 59, 53] as const; // #183b35
  const accentColor = [23, 107, 82] as const; // #176b52
  const textDark = [32, 42, 53] as const;
  const textMuted = [102, 116, 111] as const;

  // Header Banner
  doc.setFillColor(...primaryColor);
  doc.rect(0, 0, 210, 34, 'F');

  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(22);
  doc.text('KAWAD SWAD UDHYOG', 15, 18);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.text('Authentic Handmade Papad, Masala & Snacks · Nimar Region, Madhya Pradesh', 15, 26);

  // Invoice Details Box
  doc.setTextColor(...textDark);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(14);
  doc.text('SALES INVOICE / CASH MEMO', 15, 46);

  doc.setDrawColor(225, 231, 229);
  doc.setLineWidth(0.5);
  doc.line(15, 50, 195, 50);

  // Two-column metadata
  doc.setFontSize(9.5);
  doc.setFont('helvetica', 'bold');
  doc.text('Bill Number:', 15, 58);
  doc.setFont('helvetica', 'normal');
  doc.text(sale.bill_number, 45, 58);

  doc.setFont('helvetica', 'bold');
  doc.text('Date & Time:', 15, 65);
  doc.setFont('helvetica', 'normal');
  doc.text(new Date(sale.sale_datetime).toLocaleString('en-IN'), 45, 65);

  doc.setFont('helvetica', 'bold');
  doc.text('Customer:', 110, 58);
  doc.setFont('helvetica', 'normal');
  doc.text(sale.customer_name_snapshot, 135, 58);

  doc.setFont('helvetica', 'bold');
  doc.text('Sales Type:', 110, 65);
  doc.setFont('helvetica', 'normal');
  doc.text(sale.sales_type, 135, 65);

  doc.setFont('helvetica', 'bold');
  doc.text('Payment:', 110, 72);
  doc.setFont('helvetica', 'normal');
  doc.text(`PAID (${sale.payment_status})`, 135, 72);

  // Table Header
  const startY = 82;
  doc.setFillColor(237, 244, 241); // #edf4f1
  doc.rect(15, startY, 180, 8, 'F');

  doc.setTextColor(...primaryColor);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.text('Item / Product Description', 18, startY + 5.5);
  doc.text('Qty', 115, startY + 5.5);
  doc.text('Price (₹)', 140, startY + 5.5);
  doc.text('Total (₹)', 175, startY + 5.5);

  let currentY = startY + 14;
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(...textDark);

  items.forEach((item) => {
    if (currentY > 260) {
      doc.addPage();
      currentY = 20;
    }

    doc.text(item.product_name_snapshot || item.sku_snapshot, 18, currentY);
    doc.text(`${item.quantity} ${item.unit || 'pkt'}`, 115, currentY);
    doc.text(Number(item.actual_unit_price).toFixed(2), 140, currentY);
    doc.text(Number(item.line_total).toFixed(2), 175, currentY);

    // subtle line separator
    doc.setDrawColor(240, 244, 242);
    doc.line(15, currentY + 3, 195, currentY + 3);

    currentY += 8;
  });

  // Summary section
  currentY += 6;
  doc.setDrawColor(200, 215, 210);
  doc.line(110, currentY, 195, currentY);
  currentY += 6;

  doc.setFontSize(9.5);
  doc.text('Subtotal:', 120, currentY);
  doc.text(`₹${Number(sale.subtotal).toFixed(2)}`, 175, currentY);

  if (sale.discount_amount > 0) {
    currentY += 6;
    doc.text('Discount:', 120, currentY);
    doc.text(`- ₹${Number(sale.discount_amount).toFixed(2)}`, 175, currentY);
  }

  currentY += 8;
  doc.setFillColor(...accentColor);
  doc.rect(110, currentY - 5, 85, 10, 'F');
  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(11);
  doc.text('TOTAL AMOUNT:', 115, currentY + 1.5);
  doc.text(`₹${Number(sale.bill_total).toFixed(2)}`, 165, currentY + 1.5);

  // Footer notes & declaration
  doc.setTextColor(...textMuted);
  doc.setFontSize(8.5);
  doc.setFont('helvetica', 'italic');
  doc.text(
    'Payment recorded in full. Issued bills are final and recorded in the audit register.',
    15,
    270
  );
  doc.text(
    'Thank you for partnering with Kawad Swad Udhyog! For inquiries contact: sales@kawadswad.com',
    15,
    275
  );

  doc.save(`${sale.bill_number}.pdf`);
}
