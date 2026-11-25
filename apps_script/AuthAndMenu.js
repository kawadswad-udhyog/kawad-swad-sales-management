/**
 * KAWAD SWAD ERP - ROLE-BASED ACCESS CONTROL, MENU & SIDEBAR CONTROLLER
 * Blueprint Version: 2.0 | Enforces POL-011, POL-012, POL-015, Section 10.1, Section 11.4, Section 12
 */

const KS_ROLES = Object.freeze({
  OWNER_ADMIN: 'OWNER_ADMIN',
  PA: 'PA',
  ACCOUNTS: 'ACCOUNTS',
  PROCUREMENT: 'PROCUREMENT',
  STORE: 'STORE',
  PRODUCTION: 'PRODUCTION',
  QUALITY: 'QUALITY',
  PACKAGING: 'PACKAGING',
  SALES: 'SALES',
  FIELD_SALESMAN: 'FIELD_SALESMAN',
  HR: 'HR',
  AUDITOR: 'AUDITOR'
});

/**
 * Resolves the current logged-in user's record and active role from the Users tab.
 * Fails closed (returns UNAUTHORIZED) if user is missing or inactive (POL-012).
 */
function ksGetCurrentUserContext_() {
  const email = ksGetActorEmail_();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ownerEmail = ss.getOwner() ? ss.getOwner().getEmail() : '';

  const userSheet = ss.getSheetByName(KS_CONFIG.TABS.USERS);
  if (userSheet && userSheet.getLastRow() >= 2) {
    const { headerMap } = ksGetHeaderMap_(userSheet, ['user_id']);
    const emailCol = headerMap['email'] || headerMap['work_email'] || headerMap['login_email'];
    const roleCol = headerMap['role'] || headerMap['user_role'] || headerMap['role_code'];
    const activeCol = headerMap['active'] || headerMap['is_active'] || headerMap['status'];
    const nameCol = headerMap['full_name'] || headerMap['name'] || headerMap['user_name'];

    if (emailCol && roleCol) {
      const data = userSheet.getRange(2, 1, userSheet.getLastRow() - 1, userSheet.getLastColumn()).getValues();
      for (let i = 0; i < data.length; i++) {
        const rowEmail = String(data[i][emailCol - 1] || '').trim().toLowerCase();
        if (rowEmail === email.toLowerCase()) {
          const activeVal = activeCol ? String(data[i][activeCol - 1]).trim().toUpperCase() : 'TRUE';
          const isActive = (activeVal === 'TRUE' || activeVal === 'YES' || activeVal === 'ACTIVE' || activeVal === '1');
          return {
            authenticated: isActive,
            user_id: String(data[i][headerMap['user_id'] - 1]),
            name: nameCol ? String(data[i][nameCol - 1]) : email,
            email: email,
            role: isActive ? String(data[i][roleCol - 1]).trim().toUpperCase() : 'INACTIVE'
          };
        }
      }
    }
  }

  // Spreadsheet owner fallback during initial clean-database bootstrap (POL-017)
  if (ownerEmail && email.toLowerCase() === ownerEmail.toLowerCase()) {
    return {
      authenticated: true,
      user_id: 'OWNER_BOOTSTRAP',
      name: 'Owner Admin',
      email: email,
      role: KS_ROLES.OWNER_ADMIN
    };
  }

  return {
    authenticated: false,
    user_id: 'UNREGISTERED',
    name: email,
    email: email,
    role: 'UNAUTHORIZED'
  };
}

/**
 * Enforces role permission before executing any protected workflow (Section 10.1 & 11.2).
 */
function ksRequireRole_(allowedRoles, actionName) {
  const ctx = ksGetCurrentUserContext_();
  if (!ctx.authenticated || !allowedRoles.includes(ctx.role)) {
    const msg = 'Access Denied for "' + actionName + '": User ' + ctx.email +
      ' (Role: ' + ctx.role + ') lacks required role [' + allowedRoles.join(', ') + '].';
    ksLogException_('HIGH', actionName, 'Users', ctx.email, msg, { role: ctx.role });
    throw new Error(msg);
  }
  return ctx;
}

/**
 * Builds the role-aware Kawad Swad ERP menu when the spreadsheet opens (Section 11.4).
 */
function onOpen() {
  let ui;
  try {
    ui = SpreadsheetApp.getUi();
  } catch (e) {
    Logger.log('onOpen skipped UI build (not in active spreadsheet UI context).');
    return;
  }

  const ctx = ksGetCurrentUserContext_();
  const menu = ui.createMenu('Kawad Swad ERP');

  if (!ctx.authenticated) {
    menu.addItem('Access Status (Unauthorized)', 'ksUiShowWhoAmI').addToUi();
    return;
  }

  menu.addItem('Open Operations Sidebar', 'ksUiOpenOperationsSidebar');
  menu.addItem('My Session & Role (' + ctx.role + ')', 'ksUiShowWhoAmI');
  menu.addSeparator();

  const r = ctx.role;
  if ([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.STORE, KS_ROLES.PROCUREMENT].includes(r)) {
    menu.addItem('1. Purchase / Material Receipt', 'ksUiOpenPurchaseForm');
  }
  if ([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.PRODUCTION].includes(r)) {
    menu.addItem('2. Production Batch Entry', 'ksUiOpenProductionForm');
  }
  if ([KS_ROLES.OWNER_ADMIN, KS_ROLES.QUALITY].includes(r)) {
    menu.addItem('3. Quality Release / Hold', 'ksUiOpenQualityForm');
  }
  if ([KS_ROLES.OWNER_ADMIN, KS_ROLES.PACKAGING].includes(r)) {
    menu.addItem('4. Packaging Batch (SKUs)', 'ksUiOpenPackagingForm');
  }
  if ([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.SALES, KS_ROLES.FIELD_SALESMAN].includes(r)) {
    menu.addItem('5. Sales Order & Invoice', 'ksUiOpenSalesForm');
  }
  if ([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.ACCOUNTS, KS_ROLES.FIELD_SALESMAN].includes(r)) {
    menu.addItem('6. Customer Receipt / Expense', 'ksUiOpenFinanceForm');
  }

  // Management Reports submenu (Section 12)
  menu.addSeparator();
  menu.addSubMenu(
    ui.createMenu('Management Reports')
      .addItem('Refresh All Core Reports', 'ksUiRefreshAllReports')
      .addItem('Generate Trial Balance (RPT_TrialBalance)', 'ksUiGenTrialBalance')
      .addItem('Generate Lot Stock Status (RPT_StockStatus)', 'ksUiGenStockStatus')
      .addItem('Generate Sales & Receivables (RPT_SalesAndReceivables)', 'ksUiGenSalesReceivables')
  );

  if ([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.AUDITOR].includes(r)) {
    menu.addSeparator();
    menu.addSubMenu(
      ui.createMenu('System & Governance')
        .addItem('Run Full Schema Health Check', 'ksUiRunSchemaHealthCheck')
        .addItem('Inspect Users Table Headers', 'ksInspectUsersHeaders')
    );
  }

  menu.addToUi();
}

function ksOpenSidebarWithTab_(defaultTab) {
  const ctx = ksGetCurrentUserContext_();
  if (!ctx.authenticated) {
    SpreadsheetApp.getUi().alert('Access Denied', 'Your account (' + ctx.email + ') is not authorized.', SpreadsheetApp.getUi().ButtonSet.OK);
    return;
  }
  const tpl = HtmlService.createTemplateFromFile('ErpSidebar');
  tpl.userContext = JSON.stringify(ctx);
  tpl.defaultTab = defaultTab || 'purchase';
  const html = tpl.evaluate()
    .setTitle('Kawad Swad ERP')
    .setWidth(380);
  SpreadsheetApp.getUi().showSidebar(html);
}

function ksUiOpenOperationsSidebar() { ksOpenSidebarWithTab_('purchase'); }
function ksUiOpenPurchaseForm()      { ksOpenSidebarWithTab_('purchase'); }
function ksUiOpenProductionForm()    { ksOpenSidebarWithTab_('production'); }
function ksUiOpenQualityForm()       { ksOpenSidebarWithTab_('quality'); }
function ksUiOpenPackagingForm()     { ksOpenSidebarWithTab_('packaging'); }
function ksUiOpenSalesForm()         { ksOpenSidebarWithTab_('sales'); }
function ksUiOpenFinanceForm()       { ksOpenSidebarWithTab_('finance'); }

function ksUiRefreshAllReports() {
  const res = ksRefreshAllManagementReports();
  SpreadsheetApp.getUi().alert(
    'Reports Refreshed',
    'Trial Balance: ' + (res.trial_balance.balanced ? 'BALANCED (INR ' + res.trial_balance.total_debit + ')' : 'UNBALANCED!') +
    '\nStock Lots Tracked: ' + res.stock_status.lot_count +
    '\nTotal Invoiced: INR ' + res.sales_receivables.total_invoiced + ' (Outstanding: INR ' + res.sales_receivables.total_outstanding + ')',
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function ksUiGenTrialBalance() {
  const res = ksGenerateTrialBalanceReport();
  SpreadsheetApp.getUi().alert(
    'Trial Balance Generated',
    'Tab: RPT_TrialBalance\nStatus: ' + (res.balanced ? 'BALANCED' : 'UNBALANCED') +
    '\nTotal Debit: INR ' + res.total_debit + '\nTotal Credit: INR ' + res.total_credit,
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function ksUiGenStockStatus() {
  const res = ksGenerateStockStatusReport();
  SpreadsheetApp.getUi().alert('Stock Status Generated', 'Tab: RPT_StockStatus\nLots tracked: ' + res.lot_count, SpreadsheetApp.getUi().ButtonSet.OK);
}

function ksUiGenSalesReceivables() {
  const res = ksGenerateDailySalesAndReceivablesReport();
  SpreadsheetApp.getUi().alert(
    'Sales & Receivables Generated',
    'Tab: RPT_SalesAndReceivables\nTotal Invoiced: INR ' + res.total_invoiced + '\nTotal Outstanding: INR ' + res.total_outstanding,
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function ksUiShowWhoAmI() {
  const ctx = ksGetCurrentUserContext_();
  SpreadsheetApp.getUi().alert(
    'Kawad Swad ERP Session',
    'User ID: ' + ctx.user_id + '\nName: ' + ctx.name + '\nEmail: ' + ctx.email + '\nActive Role: ' + ctx.role,
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function ksUiRunSchemaHealthCheck() {
  ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA], 'ksUiRunSchemaHealthCheck');
  ksRunFullSchemaHealthCheck();
  SpreadsheetApp.getUi().alert('Schema Health Check Complete', 'All 92 core tables verified and logged to AuditLog.', SpreadsheetApp.getUi().ButtonSet.OK);
}

function ksInspectUsersHeaders() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(KS_CONFIG.TABS.USERS);
  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  Logger.log('Users headers (cols=' + headers.length + '): ' + JSON.stringify(headers));
}

function ksUiSubmitExpenseVoucher(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.ACCOUNTS], 'ksUiSubmitExpenseVoucher');
  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  const amount = Number(payload.amount);
  if (!(amount > 0)) throw new Error('Expense amount must be greater than 0.');
  if (!payload.expense_account || !payload.payment_account || !payload.payee) {
    throw new Error('Payee, expense category/account, and payment mode/account are required.');
  }

  return ksPostBalancedJournalVoucher({
    nonce: payload.nonce,
    reference_type: 'EXPENSE_VOUCHER',
    reference_id: payload.voucher_ref || ('EXP-' + payload.expense_date),
    record_date: payload.expense_date,
    description: 'Expense: ' + payload.payee + ' - ' + (payload.purpose || ''),
    notes: 'Recorded via ERP Sidebar by ' + ctx.user_id,
    lines: [
      { dr_cr: 'DEBIT', account_code: payload.expense_account, amount: amount, description: payload.purpose || payload.payee },
      { dr_cr: 'CREDIT', account_code: payload.payment_account, amount: amount, description: 'Paid via ' + payload.payment_account }
    ]
  });
}

function ksUiSubmitSalesEntry(payload) {
  const so = ksCreateSalesOrder(payload);
  let inv = null;
  if (payload.issue_invoice_now) {
    const today = ksNowIso_().slice(0, 10);
    inv = ksCreateSalesInvoice({
      nonce: payload.nonce + '_AUTO_INV',
      sales_order_id: so.sales_order_id,
      customer_id: payload.customer_id,
      invoice_date: today,
      taxable_value: so.grand_total,
      notes: payload.notes || '',
      items: payload.items.map(it => ({
        item_type: 'PACKAGED_SKU',
        item_id: it.sku || it.product_id,
        description: it.product_name_snapshot || it.sku,
        quantity: it.quantity,
        unit: 'PKT',
        unit_rate: it.unit_price,
        tax_rate: it.tax_rate || 0,
        line_amount: Number(it.quantity) * Number(it.unit_price)
      }))
    });
  }
  return { success: true, sales_order: so, sales_invoice: inv };
}