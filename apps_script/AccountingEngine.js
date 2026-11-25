/**
 * KAWAD SWAD ERP - DOUBLE-ENTRY JOURNAL & FINANCIAL PERIOD ENGINE
 * Blueprint Version: 2.0 | Enforces POL-003, POL-004, POL-008, Section 6.3, REQ-015, REQ-072
 * Wired strictly to hydrated JournalEntries, JournalEntryLines, and FinancialPeriods headers.
 */

/**
 * Checks whether a posting date falls inside an OPEN (non-closed) FinancialPeriod (POL-008 / Section 6.11).
 * If FinancialPeriods has no rows configured yet during bootstrap, permits posting with a warning note.
 */
function ksAssertOpenFinancialPeriod_(postingDateStr) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const fpSheet = ss.getSheetByName('FinancialPeriods');
  if (!fpSheet || fpSheet.getLastRow() < 2) return { period_id: 'UNCONFIGURED_BOOTSTRAP', is_closed: false };

  const { headerMap } = ksGetHeaderMap_(fpSheet, ['period_id', 'start_date', 'end_date', 'is_closed']);
  const rows = fpSheet.getRange(2, 1, fpSheet.getLastRow() - 1, fpSheet.getLastColumn()).getValues();
  const target = new Date(postingDateStr);

  for (let i = 0; i < rows.length; i++) {
    const start = new Date(rows[i][headerMap['start_date'] - 1]);
    const end = new Date(rows[i][headerMap['end_date'] - 1]);
    if (target >= start && target <= end) {
      const closedVal = String(rows[i][headerMap['is_closed'] - 1]).trim().toUpperCase();
      const isClosed = (closedVal === 'TRUE' || closedVal === 'YES' || closedVal === '1');
      if (isClosed) {
        throw new Error(
          'Period Lock Violation: Date ' + postingDateStr + ' falls in closed period "' +
          rows[i][headerMap['period_id'] - 1] + '" (POL-008 / Section 6.11).'
        );
      }
      return { period_id: String(rows[i][headerMap['period_id'] - 1]), is_closed: false };
    }
  }
  return { period_id: 'NO_MATCHING_PERIOD', is_closed: false };
}

/**
 * Posts a balanced double-entry Journal Voucher (POL-008: Total Debit === Total Credit).
 * Note: Uses exact hydrated header spelling "journal_entrie_id" in JournalEntries.
 */
function ksPostBalancedJournalVoucher(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.ACCOUNTS], 'ksPostBalancedJournalVoucher');

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.record_date) throw new Error('record_date (YYYY-MM-DD) is required.');
  if (!Array.isArray(payload.lines) || payload.lines.length < 2) {
    throw new Error('A double-entry journal voucher requires at least 2 lines.');
  }

  // 1. Enforce Open Financial Period
  const periodInfo = ksAssertOpenFinancialPeriod_(payload.record_date);

  // 2. Enforce exact Debit === Credit balance in integer paise (Section 3.4 & POL-008)
  let totalDebitPaise = 0;
  let totalCreditPaise = 0;

  payload.lines.forEach((line, idx) => {
    const side = String(line.dr_cr || '').trim().toUpperCase();
    const amt = Number(line.amount);
    if (!['DEBIT', 'CREDIT'].includes(side)) {
      throw new Error('Line ' + (idx + 1) + ': dr_cr must be DEBIT or CREDIT.');
    }
    if (!(amt > 0)) {
      throw new Error('Line ' + (idx + 1) + ': amount must be > 0.');
    }
    const paise = Math.round(amt * 100);
    if (side === 'DEBIT') totalDebitPaise += paise;
    if (side === 'CREDIT') totalCreditPaise += paise;
  });

  if (totalDebitPaise !== totalCreditPaise) {
    const errMsg = 'Unbalanced Journal Voucher: Debit INR ' + (totalDebitPaise / 100).toFixed(2) +
      ' != Credit INR ' + (totalCreditPaise / 100).toFixed(2) + ' (POL-008).';
    ksLogException_('CRITICAL', 'ksPostBalancedJournalVoucher', 'JournalEntries', payload.nonce, errMsg, payload);
    throw new Error(errMsg);
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const jvAlloc = ksAllocateId('JournalEntries', payload.nonce + '_JV');
  const jvId = jvAlloc.allocated_id;
  const totalRupees = totalDebitPaise / 100;

  const jvHeader = {
    record_id: jvId,
    journal_entrie_id: jvId,
    reference_type: payload.reference_type || 'MANUAL_JV',
    reference_id: payload.reference_id || '',
    record_date: payload.record_date,
    description: String(payload.description || '').trim(),
    quantity: payload.lines.length,
    unit: 'LINES',
    amount: totalRupees,
    owner_user_id: ctx.user_id,
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: 'Period=' + periodInfo.period_id + (payload.notes ? ' | ' + payload.notes : '')
  };

  ksAppendAndVerifyRow_(ss, 'JournalEntries', jvHeader, 'journal_entrie_id', ['journal_entrie_id', 'record_date', 'amount']);

  payload.lines.forEach((line, idx) => {
    const side = String(line.dr_cr).trim().toUpperCase();
    const amt = Math.round(Number(line.amount) * 100) / 100;
    const lineAlloc = ksAllocateId('JournalEntryLines', payload.nonce + '_JVL_' + (idx + 1));

    const lineRecord = {
      record_id: lineAlloc.allocated_id,
      journal_entry_line_id: lineAlloc.allocated_id,
      parent_record_id: jvId,
      line_number: idx + 1,
      item_type: side, // DEBIT or CREDIT
      item_id: String(line.account_code || '').trim(),
      description: String(line.description || payload.description || '').trim(),
      quantity: 1,
      unit: 'INR',
      unit_rate: amt,
      tax_rate: Number(line.tax_rate) || 0,
      line_amount: side === 'DEBIT' ? amt : -amt, // Signed net amount for instant Trial Balance SUM = 0 check
      status: 'POSTED',
      created_at: nowIso,
      created_by: ctx.user_id,
      notes: line.cost_centre || ''
    };

    ksAppendAndVerifyRow_(ss, 'JournalEntryLines', lineRecord, 'journal_entry_line_id', ['journal_entry_line_id', 'parent_record_id', 'item_id']);
  });

  ksLogAudit_('JOURNAL_VOUCHER_POSTED', 'JournalEntries', jvId, {
    actor_user_id: ctx.user_id,
    field_changed: 'amount',
    new_value: 'INR ' + totalRupees.toFixed(2),
    reason: jvHeader.description,
    related_record_id: jvHeader.reference_id
  });

  return { success: true, journal_voucher_id: jvId, balanced_amount: totalRupees, line_count: payload.lines.length };
}

/**
 * End-to-End Phase G Disposable-Copy Verification Test for Sales + Receipt + Double-Entry Posting.
 */
function ksRunPhaseGSalesAndAccountingTest() {
  const today = ksNowIso_().slice(0, 10);

  // 1. Create Sales Order
  const so = ksCreateSalesOrder({
    nonce: 'TEST_SO_001',
    customer_id: 'CUST-20261118-00001',
    customer_name_snapshot: 'Shree Balaji Kirana Store',
    channel_id: 'RETAIL_FIELD',
    items: [
      { product_id: 'PRD-MMP', sku: 'KS-MMP-200', product_name_snapshot: 'Moong Master Papad 200g', pack_weight_g: 200, quantity: 20, unit_price: 55 }
    ]
  });

  // 2. Issue Distinct Sales Invoice
  const inv = ksCreateSalesInvoice({
    nonce: 'TEST_INV_001',
    sales_order_id: so.sales_order_id,
    customer_id: 'CUST-20261118-00001',
    invoice_date: today,
    taxable_value: so.grand_total,
    items: [
      { item_id: 'KS-MMP-200', description: 'Moong Master Papad 200g', quantity: 20, unit: 'PKT', unit_rate: 55, line_amount: so.grand_total }
    ]
  });

  // 3. Record Customer Receipt & Invoice Allocation
  const rcpt = ksRecordCustomerReceiptAndAllocation({
    nonce: 'TEST_RCPT_001',
    customer_id: 'CUST-20261118-00001',
    sales_order_id: so.sales_order_id,
    sales_invoice_id: inv.sales_invoice_id,
    payment_date: today,
    payment_method_id: 'UPI',
    amount_received: inv.invoice_total,
    transaction_reference: 'UTR-TEST-998877'
  });

  // 4. Post Balanced Double-Entry Journal Voucher
  const jv = ksPostBalancedJournalVoucher({
    nonce: 'TEST_JV_001',
    reference_type: 'SALES_INVOICE',
    reference_id: inv.sales_invoice_id,
    record_date: today,
    description: 'Sales & UPI receipt posting for ' + inv.sales_invoice_id,
    lines: [
      { dr_cr: 'DEBIT', account_code: '1120-BANK-UPI', amount: inv.invoice_total, description: 'UPI receipt ' + rcpt.customer_payment_id },
      { dr_cr: 'CREDIT', account_code: '4100-PRODUCT-SALES', amount: inv.invoice_total, description: 'Sales revenue ' + inv.sales_invoice_id }
    ]
  });

  Logger.log('Phase G Sales & Accounting Test Passed: ' + JSON.stringify({ so: so, inv: inv, rcpt: rcpt, jv: jv }));
}