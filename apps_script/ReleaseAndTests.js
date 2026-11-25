/**
 * KAWAD SWAD ERP - SECTION 11.6 EDGE-CASE TEST SUITE & PHASE H RELEASE GATE
 * Blueprint Version: 2.0 | Enforces POL-003..018, Section 11.6, Section 11.7, Section 16.1
 * Validates that every guardrail blocks invalid/unauthorized/duplicate actions and logs
 * formal test & release readiness evidence.
 */

function ksAssertThrows_(testName, fn) {
  try {
    fn();
  } catch (e) {
    return { test: testName, status: 'PASS_BLOCKED_AS_EXPECTED', blocked_reason: e.message };
  }
  throw new Error('SECURITY / VALIDATION TEST FAILED: "' + testName + '" succeeded when it should have been blocked!');
}

/**
 * Runs the complete Section 11.6 Negative & Edge-Case Verification Suite in the disposable copy.
 */
function ksRunSection11_6EdgeCaseTestSuite() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksRunSection11_6EdgeCaseTestSuite');
  const results = [];
  const today = ksNowIso_().slice(0, 10);

  // TEST 1: Duplicate Request / Idempotency Retry Safety (POL-002, REQ-101)
  const retryNonce = 'EDGE_NONCE_RETRY_' + Date.now();
  const id1 = ksAllocateId('Customers', retryNonce);
  const id2 = ksAllocateId('Customers', retryNonce);
  if (id1.allocated_id !== id2.allocated_id || id2.status !== 'EXISTING_IDEMPOTENT') {
    throw new Error('TEST 1 FAILED: Duplicate nonce created a second ID!');
  }
  results.push({ test: '1_IDEMPOTENT_RETRY', status: 'PASS', allocated_id: id1.allocated_id });

  // TEST 2: Missing Mandatory Field Rejection (POL-003)
  results.push(ksAssertThrows_('2_MISSING_MANDATORY_FIELD', function() {
    ksCreateSalesOrder({ nonce: 'EDGE_MISSING_' + Date.now(), customer_id: '', items: [] });
  }));

  // TEST 3: Stock Overdraft Block (POL-005)
  results.push(ksAssertThrows_('3_STOCK_OVERDRAFT_BLOCK', function() {
    ksRecordProductionConsumption({
      nonce: 'EDGE_OVERDRAFT_' + Date.now(),
      production_batch_id: 'PO-EDGE-001',
      raw_material_id: 'RM-TEST-MOONG-DAL',
      inventory_lot_id: 'LOT-20261118-00001',
      actual_quantity: 9999999,
      unit: 'KG'
    });
  }));

  // TEST 4: Quality Hold Gate Block (DB-05 / POL-011)
  const heldLot = ksCreateInventoryLotAndReceipt({
    nonce: 'EDGE_HELD_LOT_' + Date.now(),
    item_type: 'BULK_FG',
    item_id: 'PRD-MMP',
    quantity_received: 50,
    unit: 'KG',
    quality_status: 'PENDING_QC',
    notes: 'Held lot for Section 11.6 test'
  });

  results.push(ksAssertThrows_('4_QUALITY_HOLD_PACKAGING_BLOCK', function() {
    ksRecordPackagingOutput({
      nonce: 'EDGE_PKG_HELD_' + Date.now(),
      packaging_batch_id: 'PKB-EDGE-001',
      bulk_lot_id: heldLot.inventory_lot_id,
      product_id: 'PRD-MMP',
      sku: 'KS-MMP-200',
      pack_weight_g: 200,
      packet_count: 50
    });
  }));

  // TEST 5: Invalid Retail Pack Size Rejection (200g / 500g / 1000g rule)
  results.push(ksAssertThrows_('5_INVALID_RETAIL_PACK_SIZE', function() {
    ksRecordPackagingOutput({
      nonce: 'EDGE_BAD_PACK_' + Date.now(),
      packaging_batch_id: 'PKB-EDGE-002',
      bulk_lot_id: 'LOT-20261118-00002',
      product_id: 'PRD-MMP',
      sku: 'KS-MMP-350',
      pack_weight_g: 350,
      packet_count: 50
    });
  }));

  // TEST 6: Unbalanced Double-Entry Journal Voucher Block (POL-008)
  results.push(ksAssertThrows_('6_UNBALANCED_JOURNAL_BLOCK', function() {
    ksPostBalancedJournalVoucher({
      nonce: 'EDGE_UNBAL_JV_' + Date.now(),
      record_date: today,
      description: 'Intentionally unbalanced test voucher',
      lines: [
        { dr_cr: 'DEBIT', account_code: '1110-PETTY-CASH', amount: 1000 },
        { dr_cr: 'CREDIT', account_code: '4100-PRODUCT-SALES', amount: 900 }
      ]
    });
  }));

  // TEST 7: Unverified Gig Worker Payout Block (REQ-023 & POL-011)
  const unverifiedWorker = ksRegisterWorkerOrEmployee({
    nonce: 'EDGE_GIG_EMP_' + Date.now(),
    full_name: 'Test Unverified Worker',
    designation: 'Helper',
    employment_type: 'GIG_WORKER'
  });
  ksRecordWorkerProductionEntry({
    nonce: 'EDGE_GIG_WORK_' + Date.now(),
    production_batch_id: 'PO-EDGE-002',
    employee_id: unverifiedWorker.employee_id,
    work_date: today,
    task_type: 'SORTING',
    hours_worked: 4,
    rate: 100 // Submitted, NOT verified
  });
  results.push(ksAssertThrows_('7_UNVERIFIED_GIG_PAYOUT_BLOCK', function() {
    ksProcessGigWorkerPayout({
      nonce: 'EDGE_GIG_PAY_' + Date.now(),
      employee_id: unverifiedWorker.employee_id,
      period_start: today,
      period_end: today
    });
  }));

  // TEST 8: Reconciliation & Trial Balance Proof (Section 12.5 & 16.1)
  const reports = ksRefreshAllManagementReports();
  if (!reports.trial_balance.balanced) {
    throw new Error('TEST 8 FAILED: Trial Balance is out of balance!');
  }
  results.push({
    test: '8_TRIAL_BALANCE_AND_STOCK_RECONCILIATION',
    status: 'PASS',
    trial_balance_total: reports.trial_balance.total_debit,
    lots_reconciled: reports.stock_status.lot_count
  });

  ksLogAudit_('SECTION_11_6_SUITE_PASSED', 'WORKBOOK', 'PHASE_G_VALIDATION', {
    actor_user_id: ctx.user_id,
    field_changed: 'test_suite',
    new_value: results.length + '/' + results.length + ' PASSED',
    reason: 'All Section 11.6 negative, security, and reconciliation tests passed'
  });

  Logger.log('=== SECTION 11.6 FULL TEST SUITE PASSED (' + results.length + '/' + results.length + ') ===');
  Logger.log(JSON.stringify(results, null, 2));
  return results;
}

/**
 * Generates a read-only Phase H Controlled Live Release Readiness Checklist tab
 * (RPT_PhaseH_ReleaseGate) per Section 11.7 & Section 16 without altering live data.
 */
function ksGeneratePhaseHReleaseChecklist() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksGeneratePhaseHReleaseChecklist');
  const nowIso = ksNowIso_();

  const gates = [
    ['GATE-01', 'Phase A: Business Fact Confirmation', 'Confirm legal entity, locations, channels, SKUs, and 47 open decisions (Section 17)', 'OWNER_ADMIN', 'PENDING_OWNER_SIGN_OFF'],
    ['GATE-02', 'Phase B & C: Schema & Data Dictionary Mapping', '92 core tables verified & hydrated from DBV5_FIELD_DICTIONARY_3074', 'OWNER_ADMIN / TECH', 'VERIFIED_IN_TEST_COPY'],
    ['GATE-03', 'Phase D: CA-Approved Chart of Accounts & Tax Setup', 'Confirm COA codes, GST registration/HSN rates, and inventory valuation policy', 'OWNER_ADMIN / CA', 'PENDING_CA_CONFIRMATION'],
    ['GATE-04', 'Phase E & F: Role Access & Users Master Setup', 'Populate Users tab with active emails and roles (OWNER_ADMIN, PA, STORE, PRODUCTION, QUALITY, PACKAGING, SALES, ACCOUNTS)', 'OWNER_ADMIN', 'PENDING_USER_POPULATION'],
    ['GATE-05', 'Phase G: Disposable-Copy & Edge-Case Tests', 'Run ksRunSection11_6EdgeCaseTestSuite() with 8/8 checks passing', 'OWNER_ADMIN / TECH', 'READY_TO_VERIFY'],
    ['GATE-06', 'Phase H1: Timestamped Live Workbook Backup', 'Create protected backup copy of live workbook and log in BackupRegister (POL-018)', 'OWNER_ADMIN', 'REQUIRED_BEFORE_GO_LIVE'],
    ['GATE-07', 'Phase H2: Clean Production Baseline Verification', 'Confirm live workbook starts with 0 test rows and verified opening balances (POL-017)', 'OWNER_ADMIN', 'REQUIRED_BEFORE_GO_LIVE'],
    ['GATE-08', 'Phase H3: Explicit Owner Go-Live Approval', 'Record signed Owner release approval in AuditLog / Deployment Log before live entry', 'OWNER_ADMIN', 'PENDING_OWNER_APPROVAL']
  ];

  ksWriteReportView_(
    'RPT_PhaseH_ReleaseGate',
    'KAWAD SWAD ERP - PHASE H CONTROLLED LIVE RELEASE CHECKLIST (SECTION 11.7)',
    [
      ['Blueprint Version', 'Version 2.0 (18 November 2026)'],
      ['Generated At', nowIso + ' by ' + ctx.user_id],
      ['Governing Rule', 'POL-017 & POL-018: Never copy test transactions into live; deploy scripts & clean schema only after all gates pass.']
    ],
    ['Gate ID', 'Release Checkpoint', 'Verification Requirement', 'Accountable Owner', 'Current Status'],
    gates
  );

  Logger.log('Generated RPT_PhaseH_ReleaseGate checklist tab.');
}