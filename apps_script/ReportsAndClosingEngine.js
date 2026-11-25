/**
 * KAWAD SWAD ERP - MANAGEMENT REPORTS & DAILY CLOSING ENGINE
 * Blueprint Version: 2.0 | Enforces POL-001, POL-008, POL-014, Section 12.1..12.5, REQ-040, REQ-072
 * Generates derived reporting views from posted source ledgers without overwriting transaction history.
 */

/**
 * Helper: Creates or refreshes a clearly labeled Reporting View tab (Section 3.10 & 12.5).
 * Never touches authoritative transaction tables.
 */
function ksWriteReportView_(reportTabName, title, metadataRows, tableHeaders, tableRows) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(reportTabName);
  if (!sh) {
    sh = ss.insertSheet(reportTabName);
  } else {
    sh.clearContents();
  }

  const output = [];
  output.push([title]);
  metadataRows.forEach(m => output.push(m));
  output.push([]); // Blank separator row
  output.push(tableHeaders);

  if (tableRows.length === 0) {
    const emptyRow = new Array(tableHeaders.length).fill('');
    emptyRow[0] = 'No posted records found for this scope.';
    output.push(emptyRow);
  } else {
    tableRows.forEach(r => output.push(r));
  }

  const maxCols = Math.max(tableHeaders.length, 2);
  const normalized = output.map(row => {
    const copy = row.slice();
    while (copy.length < maxCols) copy.push('');
    return copy;
  });

  sh.getRange(1, 1, normalized.length, maxCols).setValues(normalized);
  sh.getRange(1, 1).setFontWeight('bold').setFontSize(12);
  const headerRowIdx = metadataRows.length + 3;
  sh.getRange(headerRowIdx, 1, 1, tableHeaders.length).setFontWeight('bold').setBackground('#e8f5e9');
  sh.setFrozenRows(headerRowIdx);
  SpreadsheetApp.flush();

  return sh;
}

/**
 * 1. TRIAL BALANCE REPORT (REQ-017, REQ-072, Section 12.3 & 12.5)
 * Aggregates all POSTED JournalEntryLines by account code and verifies Total Debits === Total Credits.
 */
function ksGenerateTrialBalanceReport(asOfDateStr) {
  const ctx = ksRequireRole_(
    [KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.ACCOUNTS, KS_ROLES.AUDITOR],
    'ksGenerateTrialBalanceReport'
  );

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const asOf = asOfDateStr || ksNowIso_().slice(0, 10);
  const nowIso = ksNowIso_();

  const jelSheet = ss.getSheetByName('JournalEntryLines');
  const { headerMap } = ksGetHeaderMap_(jelSheet, ['item_type', 'item_id', 'unit_rate', 'status', 'created_at']);
  const lastRow = jelSheet.getLastRow();

  const accountMap = {}; // { account_code: { debitPaise, creditPaise } }
  let totalDebitPaise = 0;
  let totalCreditPaise = 0;

  if (lastRow >= 2) {
    const rows = jelSheet.getRange(2, 1, lastRow - 1, jelSheet.getLastColumn()).getValues();
    rows.forEach(r => {
      if (String(r[headerMap['status'] - 1]).trim() !== 'POSTED') return;
      const acct = String(r[headerMap['item_id'] - 1] || 'UNCLASSIFIED').trim();
      const side = String(r[headerMap['item_type'] - 1] || '').trim().toUpperCase();
      const amt = Number(r[headerMap['unit_rate'] - 1]) || 0;
      const paise = Math.round(amt * 100);

      if (!accountMap[acct]) accountMap[acct] = { debitPaise: 0, creditPaise: 0 };
      if (side === 'DEBIT') {
        accountMap[acct].debitPaise += paise;
        totalDebitPaise += paise;
      } else if (side === 'CREDIT') {
        accountMap[acct].creditPaise += paise;
        totalCreditPaise += paise;
      }
    });
  }

  const sortedAccounts = Object.keys(accountMap).sort();
  const tableRows = sortedAccounts.map(acct => {
    const dr = accountMap[acct].debitPaise / 100;
    const cr = accountMap[acct].creditPaise / 100;
    const net = (accountMap[acct].debitPaise - accountMap[acct].creditPaise) / 100;
    return [
      acct,
      dr,
      cr,
      net >= 0 ? net : 0,
      net < 0 ? Math.abs(net) : 0
    ];
  });

  const isBalanced = (totalDebitPaise === totalCreditPaise);
  const diffRupees = (totalDebitPaise - totalCreditPaise) / 100;

  tableRows.push([
    'TOTAL',
    totalDebitPaise / 100,
    totalCreditPaise / 100,
    '',
    ''
  ]);

  if (!isBalanced) {
    ksLogException_(
      'CRITICAL',
      'ksGenerateTrialBalanceReport',
      'JournalEntryLines',
      asOf,
      'Trial Balance out of balance by INR ' + diffRupees.toFixed(2),
      { total_debit: totalDebitPaise / 100, total_credit: totalCreditPaise / 100 }
    );
  }

  const meta = [
    ['Report Status', 'DERIVED SNAPSHOT (NOT SOURCE TRANSACTION) | Basis: POSTED / ACTUAL'],
    ['As-Of Date', asOf],
    ['Generated At', nowIso + ' by ' + ctx.user_id],
    ['Data Source', 'JournalEntryLines (status = POSTED)'],
    ['Balance Check', isBalanced ? 'BALANCED (Total Debits === Total Credits)' : 'UNBALANCED EXCEPTION: Diff INR ' + diffRupees.toFixed(2)]
  ];

  ksWriteReportView_(
    'RPT_TrialBalance',
    'KAWAD SWAD - TRIAL BALANCE REPORT',
    meta,
    ['Account Code', 'Total Debit (INR)', 'Total Credit (INR)', 'Closing Debit (INR)', 'Closing Credit (INR)'],
    tableRows
  );

  ksLogAudit_('REPORT_GENERATED', 'RPT_TrialBalance', asOf, {
    actor_user_id: ctx.user_id,
    field_changed: 'balance_check',
    new_value: isBalanced ? 'BALANCED' : 'UNBALANCED (' + diffRupees.toFixed(2) + ')'
  });

  return {
    success: true,
    report_tab: 'RPT_TrialBalance',
    balanced: isBalanced,
    total_debit: totalDebitPaise / 100,
    total_credit: totalCreditPaise / 100
  };
}

/**
 * 2. LIVE STOCK STATUS & LOT QUALITY REPORT (POL-005, REQ-030, REQ-038, Section 12.1)
 * Derives live balances strictly from InventoryMovements joined with InventoryLots quality status.
 */
function ksGenerateStockStatusReport() {
  const ctx = ksRequireRole_(
    [KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.STORE, KS_ROLES.PRODUCTION, KS_ROLES.PACKAGING, KS_ROLES.SALES, KS_ROLES.AUDITOR],
    'ksGenerateStockStatusReport'
  );

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();

  // Read lot metadata
  const lotSheet = ss.getSheetByName('InventoryLots');
  const lotMapInfo = ksGetHeaderMap_(lotSheet, ['inventory_lot_id', 'item_type', 'item_id', 'lot_number', 'warehouse_id', 'unit', 'quality_status']);
  const lotMeta = {};
  if (lotSheet.getLastRow() >= 2) {
    const lRows = lotSheet.getRange(2, 1, lotSheet.getLastRow() - 1, lotSheet.getLastColumn()).getValues();
    lRows.forEach(r => {
      const id = String(r[lotMapInfo.headerMap['inventory_lot_id'] - 1]).trim();
      if (!id) return;
      lotMeta[id] = {
        item_type: r[lotMapInfo.headerMap['item_type'] - 1],
        item_id: r[lotMapInfo.headerMap['item_id'] - 1],
        lot_number: r[lotMapInfo.headerMap['lot_number'] - 1],
        warehouse_id: r[lotMapInfo.headerMap['warehouse_id'] - 1],
        unit: r[lotMapInfo.headerMap['unit'] - 1],
        quality_status: r[lotMapInfo.headerMap['quality_status'] - 1]
      };
    });
  }

  // Aggregate posted movements by lot
  const movSheet = ss.getSheetByName('InventoryMovements');
  const movMapInfo = ksGetHeaderMap_(movSheet, ['inventory_lot_id', 'item_type', 'item_id', 'quantity_in', 'quantity_out', 'unit', 'status']);
  const lotBalances = {};

  if (movSheet.getLastRow() >= 2) {
    const mRows = movSheet.getRange(2, 1, movSheet.getLastRow() - 1, movSheet.getLastColumn()).getValues();
    mRows.forEach(r => {
      if (String(r[movMapInfo.headerMap['status'] - 1]).trim() !== 'POSTED') return;
      const lotId = String(r[movMapInfo.headerMap['inventory_lot_id'] - 1]).trim();
      if (!lotBalances[lotId]) {
        const meta = lotMeta[lotId] || {};
        lotBalances[lotId] = {
          item_type: meta.item_type || r[movMapInfo.headerMap['item_type'] - 1],
          item_id: meta.item_id || r[movMapInfo.headerMap['item_id'] - 1],
          lot_number: meta.lot_number || lotId,
          warehouse_id: meta.warehouse_id || '',
          unit: meta.unit || r[movMapInfo.headerMap['unit'] - 1],
          quality_status: meta.quality_status || 'UNKNOWN',
          total_in: 0,
          total_out: 0
        };
      }
      lotBalances[lotId].total_in += Number(r[movMapInfo.headerMap['quantity_in'] - 1]) || 0;
      lotBalances[lotId].total_out += Number(r[movMapInfo.headerMap['quantity_out'] - 1]) || 0;
    });
  }

  const tableRows = Object.keys(lotBalances).sort().map(lotId => {
    const b = lotBalances[lotId];
    const closing = Math.round((b.total_in - b.total_out) * 1000) / 1000;
    const saleable = (String(b.quality_status).toUpperCase() === 'RELEASED' && closing > 0) ? closing : 0;
    return [
      lotId,
      b.item_type,
      b.item_id,
      b.lot_number,
      b.warehouse_id,
      b.quality_status,
      b.unit,
      Math.round(b.total_in * 1000) / 1000,
      Math.round(b.total_out * 1000) / 1000,
      closing,
      saleable
    ];
  });

  const meta = [
    ['Report Status', 'DERIVED MOVEMENT-LED STOCK VIEW | Basis: POSTED MOVEMENTS'],
    ['Generated At', nowIso + ' by ' + ctx.user_id],
    ['Data Source', 'InventoryMovements (POSTED) + InventoryLots'],
    ['Control Rule', 'Only lots with quality_status = RELEASED appear under Saleable / Usable Qty (POL-005 / DB-05)']
  ];

  ksWriteReportView_(
    'RPT_StockStatus',
    'KAWAD SWAD - LOT-WISE STOCK & QUALITY STATUS',
    meta,
    ['Inventory Lot ID', 'Item Type', 'Item / SKU ID', 'Lot Number', 'Warehouse', 'QC Status', 'Unit', 'Total In', 'Total Out', 'Closing Balance', 'Saleable / Usable Qty'],
    tableRows
  );

  return { success: true, report_tab: 'RPT_StockStatus', lot_count: tableRows.length };
}

/**
 * 3. DAILY SALES, COLLECTIONS & CUSTOMER OUTSTANDING SUMMARY (REQ-040, REQ-044, Section 12.1)
 */
function ksGenerateDailySalesAndReceivablesReport(targetDateStr) {
  const ctx = ksRequireRole_(
    [KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.ACCOUNTS, KS_ROLES.SALES, KS_ROLES.AUDITOR],
    'ksGenerateDailySalesAndReceivablesReport'
  );

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const targetDate = targetDateStr || ksNowIso_().slice(0, 10);
  const nowIso = ksNowIso_();

  const invSheet = ss.getSheetByName('SalesInvoices');
  const invMap = ksGetHeaderMap_(invSheet, ['sales_invoice_id', 'invoice_date', 'customer_id', 'taxable_value', 'total_tax', 'invoice_total', 'status']);

  const allocSheet = ss.getSheetByName('CustomerPaymentAllocations');
  const allocMap = ksGetHeaderMap_(allocSheet, ['reference_id', 'amount', 'status']);

  // Build map of allocated receipts per invoice
  const paidByInvoice = {};
  if (allocSheet.getLastRow() >= 2) {
    const aRows = allocSheet.getRange(2, 1, allocSheet.getLastRow() - 1, allocSheet.getLastColumn()).getValues();
    aRows.forEach(r => {
      if (String(r[allocMap.headerMap['status'] - 1]).trim() !== 'ALLOCATED') return;
      const invId = String(r[allocMap.headerMap['reference_id'] - 1]).trim();
      paidByInvoice[invId] = (paidByInvoice[invId] || 0) + (Number(r[allocMap.headerMap['amount'] - 1]) || 0);
    });
  }

  const tableRows = [];
  let totalInvoiced = 0;
  let totalAllocated = 0;
  let totalOutstanding = 0;

  if (invSheet.getLastRow() >= 2) {
    const iRows = invSheet.getRange(2, 1, invSheet.getLastRow() - 1, invSheet.getLastColumn()).getValues();
    iRows.forEach(r => {
      const status = String(r[invMap.headerMap['status'] - 1]).trim();
      if (status === 'CANCELLED' || status === 'DRAFT') return;
      const invId = String(r[invMap.headerMap['sales_invoice_id'] - 1]).trim();
      const invDateRaw = r[invMap.headerMap['invoice_date'] - 1];
      const invDate = invDateRaw instanceof Date
        ? Utilities.formatDate(invDateRaw, KS_CONFIG.TIMEZONE, 'yyyy-MM-dd')
        : String(invDateRaw).slice(0, 10);

      const invTotal = Number(r[invMap.headerMap['invoice_total'] - 1]) || 0;
      const allocated = Math.round((paidByInvoice[invId] || 0) * 100) / 100;
      const balanceDue = Math.round((invTotal - allocated) * 100) / 100;

      totalInvoiced += invTotal;
      totalAllocated += allocated;
      totalOutstanding += balanceDue;

      tableRows.push([
        invDate,
        invId,
        r[invMap.headerMap['customer_id'] - 1],
        status,
        Number(r[invMap.headerMap['taxable_value'] - 1]) || 0,
        Number(r[invMap.headerMap['total_tax'] - 1]) || 0,
        invTotal,
        allocated,
        balanceDue,
        balanceDue <= 0 ? 'PAID' : (allocated > 0 ? 'PARTIALLY_PAID' : 'UNPAID')
      ]);
    });
  }

  tableRows.push([
    'TOTAL', '', '', '', '', '',
    Math.round(totalInvoiced * 100) / 100,
    Math.round(totalAllocated * 100) / 100,
    Math.round(totalOutstanding * 100) / 100,
    ''
  ]);

  const meta = [
    ['Report Status', 'DERIVED INVOICE & ALLOCATION REGISTER | Basis: ISSUED INVOICES'],
    ['Report Date', targetDate],
    ['Generated At', nowIso + ' by ' + ctx.user_id],
    ['Data Source', 'SalesInvoices + CustomerPaymentAllocations']
  ];

  ksWriteReportView_(
    'RPT_SalesAndReceivables',
    'KAWAD SWAD - SALES INVOICES & RECEIVABLES REGISTER',
    meta,
    ['Invoice Date', 'Invoice ID', 'Customer ID', 'Invoice Status', 'Taxable (INR)', 'Tax (INR)', 'Invoice Total (INR)', 'Allocated Paid (INR)', 'Balance Due (INR)', 'Collection Status'],
    tableRows
  );

  return {
    success: true,
    report_tab: 'RPT_SalesAndReceivables',
    total_invoiced: Math.round(totalInvoiced * 100) / 100,
    total_outstanding: Math.round(totalOutstanding * 100) / 100
  };
}

/**
 * Refreshes all 3 core management reports in one click and logs completion.
 */
function ksRefreshAllManagementReports() {
  const tb = ksGenerateTrialBalanceReport();
  const stk = ksGenerateStockStatusReport();
  const sal = ksGenerateDailySalesAndReceivablesReport();
  return { trial_balance: tb, stock_status: stk, sales_receivables: sal };
}