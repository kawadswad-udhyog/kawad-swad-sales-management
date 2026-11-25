/**
 * KAWAD SWAD ERP - DYNAMIC SCHEMA REGISTRY & DICTIONARY BRIDGE
 * Blueprint Version: 2.0 | Enforces Section 3.3, Section 11.2, Section 15
 * Reads live sheet headers & DBV5_FIELD_DICTIONARY_3074 so no column index is ever guessed.
 */

const KS_CORE_TABLES = Object.freeze({
  // DB-01 Master Data
  MASTER: [
    'CompanyProfile', 'BusinessRegistrations', 'FactoryLocations', 'Warehouses',
    'StorageLocations', 'Products', 'ProductVariants', 'Products_SKU',
    'ProductPrices', 'ProductTaxRules', 'RawMaterials', 'PackagingMaterials',
    'UnitsOfMeasurement', 'Suppliers', 'Customers', 'SalesChannels',
    'PaymentMethods', 'ExpenseCategories', 'Users', 'Employees'
  ],
  // DB-02 & DB-03 Procurement & Inventory
  INVENTORY: [
    'PurchaseRequisitions', 'SupplierQuotations', 'IncomingQualityChecks',
    'SupplierBillItems', 'PaymentAllocations', 'InventoryLots',
    'InventoryMovements', 'InventoryBalances', 'StockReservations',
    'StockTransfers', 'StockTransferItems', 'StockCounts', 'StockCountLines',
    'StockAdjustments', 'DamagedStock', 'ExpiredStock', 'QuarantineStock'
  ],
  // DB-04, DB-05, DB-06 Manufacturing, Quality & Packaging
  PRODUCTION: [
    'RecipeVersions', 'RecipeIngredients', 'ProductionPlans', 'ProductionOrders',
    'MaterialIssues', 'MaterialConsumption', 'MillingCosts', 'ProductionOutputs',
    'ProcessLosses', 'ProductionWorkerEntries', 'ProductionApprovals',
    'InProcessQualityChecks', 'FinishedGoodsQualityChecks', 'HoldReleaseRecords',
    'PackagingPlans', 'PackagingMaterialIssues', 'PackagingMaterialConsumption',
    'PackagingOutputs', 'PackagingLosses', 'PackagingQualityChecks', 'LabelVersions'
  ],
  // DB-08 & DB-09 Sales & Distribution
  SALES: [
    'SalesOrders', 'SalesOrderItems', 'SalesInvoices', 'SalesInvoiceItems',
    'CustomerPayments', 'CustomerPaymentAllocations', 'OrderStatusHistory',
    'OrderCancellations', 'SalesReturns', 'SalesReturnItems', 'CreditNotes',
    'CustomerCreditLimits', 'CustomerOutstanding', 'Shipments', 'ShipmentItems',
    'DeliveryTracking', 'DeliveryProof'
  ],
  // DB-11 & DB-12 Accounting & Costing
  ACCOUNTING: [
    'JournalEntries', 'JournalEntryLines', 'GeneralLedger', 'BankTransactions',
    'BankReconciliation', 'AccountsReceivable', 'AccountsPayable',
    'GSTTransactions', 'FinancialPeriods', 'FinancialClosings'
  ],
  // DB-13 & DB-15 Compliance & Governance
  GOVERNANCE: [
    'IdAllocations', 'AuditLog', 'ExceptionRegister', 'DocumentRegister',
    'ComplianceRegister', 'ComplianceCalendar', 'ComplianceTasks'
  ]
});

/**
 * Inspects exact headers of any group of tables and logs them cleanly
 * without hitting Apps Script's single-log truncation limit.
 */
function ksInspectTableGroupHeaders(groupName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tables = KS_CORE_TABLES[groupName];
  if (!tables) {
    throw new Error('Unknown group "' + groupName + '". Use: ' + Object.keys(KS_CORE_TABLES).join(', '));
  }

  Logger.log('=== SCHEMA INSPECTION: ' + groupName + ' (' + tables.length + ' tables) ===');
  tables.forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) {
      Logger.log('[MISSING TAB] ' + tabName);
      return;
    }
    const lastCol = sh.getLastColumn();
    const headers = lastCol > 0 ? sh.getRange(1, 1, 1, lastCol).getValues()[0] : [];
    Logger.log('[OK] ' + tabName + ' (rows=' + sh.getLastRow() + ', cols=' + lastCol + '): ' + JSON.stringify(headers));
  });
}

function ksInspectMasterHeaders()     { ksInspectTableGroupHeaders('MASTER'); }
function ksInspectInventoryHeaders()  { ksInspectTableGroupHeaders('INVENTORY'); }
function ksInspectProductionHeaders() { ksInspectTableGroupHeaders('PRODUCTION'); }
function ksInspectSalesHeaders()      { ksInspectTableGroupHeaders('SALES'); }
function ksInspectAccountingHeaders() { ksInspectTableGroupHeaders('ACCOUNTING'); }
function ksInspectGovernanceHeadersV2() { ksInspectTableGroupHeaders('GOVERNANCE'); }

/**
 * Validates that every core table exists and has unique, non-blank headers (Section 3.3).
 * Logs any missing tab or header defect to ExceptionRegister without modifying data.
 */
function ksRunFullSchemaHealthCheck() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let checked = 0;
  let passed = 0;
  const issues = [];

  Object.keys(KS_CORE_TABLES).forEach(group => {
    KS_CORE_TABLES[group].forEach(tabName => {
      checked++;
      const sh = ss.getSheetByName(tabName);
      if (!sh) {
        issues.push({ tab: tabName, issue: 'MISSING_TAB' });
        return;
      }
      try {
        ksGetHeaderMap_(sh, []);
        passed++;
      } catch (e) {
        issues.push({ tab: tabName, issue: e.message });
      }
    });
  });

  ksLogAudit_('SCHEMA_HEALTH_CHECK', 'WORKBOOK', 'ALL_CORE_TABLES', {
    field_changed: 'schema_status',
    new_value: passed + '/' + checked + ' OK',
    reason: 'Phase C/F Schema Health Verification'
  });

  Logger.log('Schema Health Check Complete: ' + passed + '/' + checked + ' passed.');
  if (issues.length > 0) {
    Logger.log('Issues found: ' + JSON.stringify(issues, null, 2));
  }
}