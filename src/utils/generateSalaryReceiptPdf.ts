import jsPDF from 'jspdf';

export interface SalaryReceiptData {
  receipt_number: string;
  recipient_id: string;
  recipient_name: string;
  recipient_type: string; // SALARY, LABOUR_WAGE, FREELANCER_MILESTONE, INCENTIVE
  role_or_category: string;
  period_start: string;
  period_end: string;
  payment_date: string;
  payment_method: string;
  payment_reference?: string;
  gross_earnings: number;
  total_deductions: number;
  net_paid: number;
  notes?: string;
  basic_salary?: number;
  allowances?: number;
  incentives?: number;
  bonus?: number;
  pf_deduction?: number;
  tds_deduction?: number;
}

export function generateSalaryReceiptPdf(data: SalaryReceiptData): void {
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'mm',
    format: 'a4',
  });

  const pageWidth = doc.internal.pageSize.getWidth();

  // Colors
  const emeraldDark = [6, 78, 59]; // #064e3b
  const slateDark = [30, 41, 59];
  const slateLight = [241, 245, 249];

  // 1. Header Banner
  doc.setFillColor(emeraldDark[0], emeraldDark[1], emeraldDark[2]);
  doc.rect(0, 0, pageWidth, 28, 'F');

  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(16);
  doc.text('KAWAD SWAD UDHYOG', pageWidth / 2, 11, { align: 'center' });

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.text(
    'Premium Bikaneri Handmade Papads, Spices & Authentic Food Products',
    pageWidth / 2,
    17,
    { align: 'center' }
  );
  doc.text(
    'Industrial Area, Bikaner, Rajasthan 334001 | GSTIN: 08AABCK1234F1Z8',
    pageWidth / 2,
    22,
    { align: 'center' }
  );

  // 2. Receipt Title & Badge
  doc.setTextColor(slateDark[0], slateDark[1], slateDark[2]);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(13);
  doc.text('OFFICIAL PAYMENT & SALARY DISBURSEMENT RECEIPT', pageWidth / 2, 38, {
    align: 'center',
  });

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(100, 116, 139);
  doc.text(
    `Voucher: ${data.receipt_number} | Issue Date: ${data.payment_date || new Date().toISOString().slice(0, 10)}`,
    pageWidth / 2,
    43,
    { align: 'center' }
  );

  // 3. Employee & Payment Information Box
  doc.setFillColor(slateLight[0], slateLight[1], slateLight[2]);
  doc.roundedRect(14, 48, pageWidth - 28, 38, 2, 2, 'F');
  doc.setDrawColor(203, 213, 225);
  doc.roundedRect(14, 48, pageWidth - 28, 38, 2, 2, 'D');

  doc.setFontSize(9);
  doc.setTextColor(slateDark[0], slateDark[1], slateDark[2]);

  // Left Column
  doc.setFont('helvetica', 'bold');
  doc.text('Recipient Name:', 18, 56);
  doc.setFont('helvetica', 'normal');
  doc.text(data.recipient_name, 55, 56);

  doc.setFont('helvetica', 'bold');
  doc.text('Worker / User ID:', 18, 63);
  doc.setFont('helvetica', 'normal');
  doc.text(data.recipient_id, 55, 63);

  doc.setFont('helvetica', 'bold');
  doc.text('Designation / Role:', 18, 70);
  doc.setFont('helvetica', 'normal');
  doc.text(data.role_or_category, 55, 70);

  doc.setFont('helvetica', 'bold');
  doc.text('Disbursement Type:', 18, 77);
  doc.setFont('helvetica', 'normal');
  doc.text(data.recipient_type, 55, 77);

  // Right Column
  const rightColX = 110;
  doc.setFont('helvetica', 'bold');
  doc.text('Period Covered:', rightColX, 56);
  doc.setFont('helvetica', 'normal');
  doc.text(`${data.period_start} to ${data.period_end}`, rightColX + 32, 56);

  doc.setFont('helvetica', 'bold');
  doc.text('Payment Date:', rightColX, 63);
  doc.setFont('helvetica', 'normal');
  doc.text(data.payment_date, rightColX + 32, 63);

  doc.setFont('helvetica', 'bold');
  doc.text('Payment Method:', rightColX, 70);
  doc.setFont('helvetica', 'normal');
  doc.text(data.payment_method || 'BANK_TRANSFER', rightColX + 32, 70);

  doc.setFont('helvetica', 'bold');
  doc.text('Tx Reference:', rightColX, 77);
  doc.setFont('helvetica', 'normal');
  doc.text(data.payment_reference || 'N/A', rightColX + 32, 77);

  // 4. Breakdown Table
  const tableStartY = 94;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(10);
  doc.text('Itemized Disbursement Breakdown', 14, tableStartY);

  // Table Headers
  const colWidth = (pageWidth - 28) / 2;
  doc.setFillColor(248, 250, 252);
  doc.rect(14, tableStartY + 3, colWidth, 7, 'F');
  doc.rect(14 + colWidth, tableStartY + 3, colWidth, 7, 'F');
  doc.setDrawColor(226, 232, 240);
  doc.rect(14, tableStartY + 3, colWidth, 7, 'D');
  doc.rect(14 + colWidth, tableStartY + 3, colWidth, 7, 'D');

  doc.setFontSize(9);
  doc.setTextColor(emeraldDark[0], emeraldDark[1], emeraldDark[2]);
  doc.text('EARNINGS & ALLOWANCES', 18, tableStartY + 8);
  doc.text('DEDUCTIONS & ADJUSTMENTS', 14 + colWidth + 4, tableStartY + 8);

  // Rows
  const rowY1 = tableStartY + 16;
  const rowY2 = tableStartY + 23;
  const rowY3 = tableStartY + 30;
  const rowY4 = tableStartY + 37;

  doc.setFont('helvetica', 'normal');
  doc.setTextColor(slateDark[0], slateDark[1], slateDark[2]);

  // Left items
  doc.text('Basic Earned Wages / Salary:', 18, rowY1);
  doc.text(
    `Rs. ${(data.basic_salary ?? data.gross_earnings).toFixed(2)}`,
    14 + colWidth - 6,
    rowY1,
    { align: 'right' }
  );

  doc.text('Allowances (HRA / Conveyance):', 18, rowY2);
  doc.text(
    `Rs. ${(data.allowances ?? 0).toFixed(2)}`,
    14 + colWidth - 6,
    rowY2,
    { align: 'right' }
  );

  doc.text('Sales Commission & Incentives:', 18, rowY3);
  doc.text(
    `Rs. ${(data.incentives ?? 0).toFixed(2)}`,
    14 + colWidth - 6,
    rowY3,
    { align: 'right' }
  );

  doc.text('Bonus & Overtime Pay:', 18, rowY4);
  doc.text(`Rs. ${(data.bonus ?? 0).toFixed(2)}`, 14 + colWidth - 6, rowY4, {
    align: 'right',
  });

  // Right items
  doc.text('Provident Fund (PF):', 14 + colWidth + 4, rowY1);
  doc.text(
    `Rs. ${(data.pf_deduction ?? 0).toFixed(2)}`,
    pageWidth - 20,
    rowY1,
    { align: 'right' }
  );

  doc.text('Tax Deducted at Source (TDS):', 14 + colWidth + 4, rowY2);
  doc.text(
    `Rs. ${(data.tds_deduction ?? 0).toFixed(2)}`,
    pageWidth - 20,
    rowY2,
    { align: 'right' }
  );

  doc.text('Advances / Other Deductions:', 14 + colWidth + 4, rowY3);
  const otherDed = Math.max(
    0,
    data.total_deductions - (data.pf_deduction ?? 0) - (data.tds_deduction ?? 0)
  );
  doc.text(`Rs. ${otherDed.toFixed(2)}`, pageWidth - 20, rowY3, {
    align: 'right',
  });

  doc.text('Total Deductions:', 14 + colWidth + 4, rowY4);
  doc.text(
    `Rs. ${data.total_deductions.toFixed(2)}`,
    pageWidth - 20,
    rowY4,
    { align: 'right' }
  );

  // Line below items
  doc.setDrawColor(203, 213, 225);
  doc.line(14, tableStartY + 42, pageWidth - 14, tableStartY + 42);

  // 5. Total Net Box
  const totalBoxY = tableStartY + 46;
  doc.setFillColor(236, 253, 245); // light emerald
  doc.roundedRect(14, totalBoxY, pageWidth - 28, 16, 2, 2, 'F');
  doc.setDrawColor(16, 185, 129);
  doc.roundedRect(14, totalBoxY, pageWidth - 28, 16, 2, 2, 'D');

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(11);
  doc.setTextColor(emeraldDark[0], emeraldDark[1], emeraldDark[2]);
  doc.text('NET DISBURSED AMOUNT:', 18, totalBoxY + 10);
  doc.setFontSize(13);
  doc.text(
    `INR ${data.net_paid.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    pageWidth - 20,
    totalBoxY + 10.5,
    { align: 'right' }
  );

  // 6. Notes if any
  if (data.notes) {
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.setTextColor(100, 116, 139);
    doc.text(`Notes: ${data.notes}`, 14, totalBoxY + 22);
  }

  // 7. Signature Section
  const sigY = 220;
  doc.setDrawColor(148, 163, 184);
  doc.line(20, sigY, 70, sigY);
  doc.line(pageWidth - 70, sigY, pageWidth - 20, sigY);

  doc.setFontSize(8.5);
  doc.setTextColor(slateDark[0], slateDark[1], slateDark[2]);
  doc.setFont('helvetica', 'bold');
  doc.text('Recipient Signature', 45, sigY + 5, { align: 'center' });
  doc.text('For Kawad Swad Udhyog', pageWidth - 45, sigY + 5, {
    align: 'center',
  });

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(7.5);
  doc.setTextColor(148, 163, 184);
  doc.text('Verified Employee / Contractor', 45, sigY + 9, { align: 'center' });
  doc.text('Authorized Signatory (Owner / PA)', pageWidth - 45, sigY + 9, {
    align: 'center',
  });

  // 8. Footer
  doc.setFontSize(7.5);
  doc.setTextColor(148, 163, 184);
  doc.text(
    'This is an authoritative computer-generated payment voucher issued under Kawad Swad ERP.',
    pageWidth / 2,
    275,
    { align: 'center' }
  );
  doc.text(
    'Kawad Swad Udhyog | Confidential & Auditable Payroll Record',
    pageWidth / 2,
    280,
    { align: 'center' }
  );

  // Trigger download
  doc.save(`Kawad_Swad_Receipt_${data.receipt_number}.pdf`);
}
