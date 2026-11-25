/**
 * KAWAD SWAD ERP - CORE CONFIGURATION & SCHEMA REGISTRY
 * Blueprint Version: 2.0 (18 Nov 2026)
 * Policy: POL-001, POL-002, POL-016, Section 11.2
 */

const KS_CONFIG = Object.freeze({
  VERSION: '2.0.0-dev',
  TIMEZONE: 'Asia/Kolkata',
  CURRENCY: 'INR',
  LOCK_TIMEOUT_MS: 30000,

  // Exact approved tab names
  TABS: Object.freeze({
    ID_ALLOCATIONS: 'IdAllocations',
    AUDIT_LOG: 'AuditLog',
    EXCEPTION_REGISTER: 'ExceptionRegister',
    SYSTEM_CONFIG: 'SystemConfig',
    PRODUCTS: 'Products',
    RAW_MATERIALS: 'RawMaterials',
    CUSTOMERS: 'Customers',
    SUPPLIERS: 'Suppliers',
    USERS: 'Users',
    AUTH_USERS: 'AuthUsers',
    INVENTORY_LOTS: 'InventoryLots',
    INVENTORY_MOVEMENTS: 'InventoryMovements'
  }),

  // Approved ID prefixes per REQ-101 (never recycled)
  ID_PREFIXES: Object.freeze({
    // Governance & Audit (DB-15)
    IdAllocations: 'ALLOC',
    AuditLog: 'AUD',
    ExceptionRegister: 'EXC',
    DocumentRegister: 'DOC',

    // Master Data (DB-01)
    Products: 'PRD',
    Products_SKU: 'SKU',
    ProductPrices: 'PRC',
    RawMaterials: 'RM',
    PackagingMaterials: 'PKG',
    Customers: 'CUST',
    Suppliers: 'SUP',
    Users: 'USR',
    AuthUsers: 'AUTH',
    Employees: 'EMP',
    FactoryLocations: 'FAC',
    Warehouses: 'WH',

    // Procurement & Inventory (DB-02, DB-03, DB-07)
    PurchaseRequisitions: 'PR',
    SupplierQuotations: 'SQ',
    IncomingQualityChecks: 'IQC',
    InventoryLots: 'LOT',
    InventoryMovements: 'MOV',
    InventoryBalances: 'BAL',
    StockReservations: 'RES',
    StockTransfers: 'TRF',
    StockTransferItems: 'TRFI',
    StockCounts: 'CNT',
    StockCountLines: 'CNTL',
    StockAdjustments: 'ADJ',
    DamagedStock: 'DMG',
    ExpiredStock: 'EXP',
    QuarantineStock: 'QRN',

    // Manufacturing, Quality & Packaging (DB-04, DB-05, DB-06)
    RecipeVersions: 'RCP',
    RecipeIngredients: 'RCPI',
    ProductionPlans: 'PPLN',
    ProductionOrders: 'PO',
    ProductionBatches: 'PB',
    MaterialIssues: 'MIS',
    MaterialConsumption: 'MCON',
    ProductionOutputs: 'POUT',
    ProcessLosses: 'PLOSS',
    ProductionWorkerEntries: 'PWE',
    InProcessQualityChecks: 'IPQC',
    FinishedGoodsQualityChecks: 'FGQC',
    HoldReleaseRecords: 'HLD',
    PackagingPlans: 'PKPLN',
    PackagingBatches: 'PKB',
    PackagingOutputs: 'PKOUT',
    PackagingLosses: 'PKLOSS',

    // Workforce & Payroll (DB-10)
    LeaveRecords: 'LVE',
    ShiftSchedules: 'SHF',
    OvertimeRecords: 'OT',
    SalaryPayments: 'SAL',
    EmployeeAdvances: 'EADV',

    // Sales & Distribution (DB-08, DB-09)
    SalesOrders: 'SO',
    SalesOrderItems: 'SOI',
    SalesInvoices: 'INV',
    SalesInvoiceItems: 'INVI',
    CustomerPayments: 'RCPT',
    CustomerPaymentAllocations: 'RCPTA',
    OrderStatusHistory: 'OSH',
    OrderCancellations: 'SOC',
    SalesReturns: 'SR',
    SalesReturnItems: 'SRI',
    CreditNotes: 'CN',
    Shipments: 'SHP',
    ShipmentItems: 'SHPI',
    DeliveryTracking: 'TRK',
    DeliveryProof: 'POD',

    // Accounting & Payments (DB-11, DB-12)
    JournalEntries: 'JV',
    JournalEntryLines: 'JVL',
    GeneralLedger: 'GL',
    BankTransactions: 'BNK',
    SupplierPayments: 'PAY',
    PaymentAllocations: 'PAYA',
    FinancialPeriods: 'FP'
  }),

  // Verified exact headers for baseline & core governance tabs
  REQUIRED_HEADERS: Object.freeze({
    IdAllocations: ['allocation_id', 'tab_name', 'allocated_id', 'nonce', 'created_at'],
    AuditLog: [
      'audit_id', 'event_datetime', 'actor_user_id', 'action', 'entity_type',
      'entity_id', 'field_changed', 'old_value', 'new_value', 'reason',
      'approved_by_user_id', 'related_record_id'
    ],
    ExceptionRegister: [
      'exception_id', 'created_at', 'severity', 'source_function', 'tab_name',
      'reference_id', 'error_message', 'payload_json', 'assigned_owner',
      'due_date', 'status', 'resolution_notes', 'resolved_by', 'resolved_at'
    ],
    RawMaterials: [
      'raw_material_id', 'material_name', 'unit', 'opening_stock', 'current_stock',
      'minimum_stock', 'active', 'notes', 'rate_per_unit', 'rate_status',
      'category', 'created_at', 'created_by'
    ],
    Customers: [
      'customer_id', 'customer_type', 'shop_name', 'shopkeeper_name', 'mobile',
      'alternate_mobile', 'address', 'locality_area', 'city', 'map_location',
      'active', 'created_at', 'notes', 'gstin'
    ],
    Suppliers: [
      'supplier_id', 'supplier_name', 'contact_person', 'mobile', 'email',
      'address', 'city', 'gstin', 'payment_terms_days', 'opening_balance',
      'active', 'notes', 'created_at', 'created_by'
    ]
  })
});

function ksNowIso_() {
  return Utilities.formatDate(new Date(), KS_CONFIG.TIMEZONE, "yyyy-MM-dd'T'HH:mm:ssXXX");
}

function ksGetActorEmail_() {
  try {
    const email = Session.getActiveUser().getEmail();
    return email || 'UNKNOWN_ACTOR';
  } catch (e) {
    return 'SYSTEM_TRIGGER';
  }
}