/**
 * KAWAD SWAD ERP - PHASE 3 MIGRATION CONTROL
 * Corrected review version: 1.0.1
 *
 * PURPOSE:
 *   Installs/refreshes only the three Phase-3-owned control tabs.
 *   It does NOT migrate or restructure business tables.
 *
 * RUN:
 *   ksP3InstallMigrationControl()
 * VERIFY:
 *   ksP3VerifyMigrationControl()
 *
 * SAFETY:
 *   - Exact workbook ID and name-prefix checks.
 *   - Full Drive backup before any write.
 *   - Reads only sheet names, dimensions and row-1 headers.
 *   - Never reads business row values.
 *   - Never touches business tabs, IDs, formulas, prices, recipes,
 *     tax rules, transactions, employee records or AuthUsers values.
 *   - Existing migration plan is preserved on reruns, including statuses
 *     and approvals. Only a blank plan tab is initialized.
 *   - Inventory is refreshed because it is a generated snapshot.
 *   - Migration log is append-only.
 */

const KS_P3_BOOT = Object.freeze({
  VERSION: '1.0.1',
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME_PREFIX: 'Kawad_Swad_Sales_Management_Google_Sheets',
  INVENTORY_TAB: 'KS_P3_LIVE_INVENTORY',
  PLAN_TAB: 'KS_P3_MIGRATION_PLAN',
  LOG_TAB: 'KS_P3_MIGRATION_LOG',
  MAX_HEADER_COLS: 300
});

function ksP3InstallMigrationControl() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    ksP3AssertTarget_(ss);

    // Validate existing owned-tab headers BEFORE creating a backup or writing.
    const inventoryHeaders = [
      'sheet_name','data_rows_approx','last_row','last_column',
      'nonblank_header_count','blank_header_positions','duplicate_headers',
      'physical_headers','header_sha256','captured_at'
    ];
    const planHeaders = [
      'sequence','workstream','operation_type','source_tab_or_field',
      'target_tab_or_field','dependency_check','data_migration_rule',
      'validation_rule','rollback_rule','status','approval_reference'
    ];
    const logHeaders = [
      'timestamp','version','event','spreadsheet_id','spreadsheet_name',
      'backup_url','live_tab_count','inventory_rows',
      'business_schema_changed','details'
    ];

    ksP3AssertOwnedTabHeader_(ss, KS_P3_BOOT.INVENTORY_TAB, inventoryHeaders);
    ksP3AssertOwnedTabHeader_(ss, KS_P3_BOOT.PLAN_TAB, planHeaders);
    ksP3AssertOwnedTabHeader_(ss, KS_P3_BOOT.LOG_TAB, logHeaders);

    // Backup before the first write.
    const stamp = Utilities.formatDate(
      new Date(),
      Session.getScriptTimeZone() || 'Asia/Kolkata',
      'yyyyMMdd_HHmmss'
    );
    const backupFile = DriveApp.getFileById(ss.getId()).makeCopy(
      'Kawad Swad ERP PRE-PHASE-3 CONTROL BACKUP ' + stamp
    );
    const backupUrl = backupFile.getUrl();

    // Structural inventory only.
    const inventory = ksP3BuildLiveInventory_(ss);

    const invTab = ss.getSheetByName(KS_P3_BOOT.INVENTORY_TAB) ||
      ss.insertSheet(KS_P3_BOOT.INVENTORY_TAB);
    ksP3ReplaceGeneratedTab_(invTab, inventory.headers, inventory.rows);

    // Initialize the plan only when blank. Never erase existing decisions.
    let planTab = ss.getSheetByName(KS_P3_BOOT.PLAN_TAB);
    if (!planTab) planTab = ss.insertSheet(KS_P3_BOOT.PLAN_TAB);
    if (planTab.getLastRow() === 0) {
      const planRows = [
        [1,'Live inventory reconciliation','VERIFY','All live tabs','Authoritative Phase 3 inventory',
         'Compare live inventory to Phase 1/2 exports and backend routes',
         'No business data moved','Resolve every unexplained tab/header difference',
         'No business schema changed in this step','IN_PROGRESS',''],
        [2,'Canonical table mapping','MAP','218 canonical table register','Canonical-to-physical map',
         'Map all 218 tables to actual live tabs and route usage',
         'No business data moved','Every table classified KEEP / RENAME / MERGE / CREATE / RETIRE',
         'Mapping register retained','NOT_STARTED',''],
        [3,'Field mapping','MAP','3,074 field dictionary rows','Canonical-to-physical field map',
         'Check backend routes, formulas and downstream references',
         'Preserve all existing values and types unless an approved conversion exists',
         'All required fields mapped or formally waived',
         'Old headers and mapping retained until cutover verified','NOT_STARTED',''],
        [4,'Relationship migration','MAP','41 proposed relationships','Verified key relationships',
         'Prove parent uniqueness, child key mapping and orphan counts',
         'No ID rewriting; no cascade delete',
         'Zero unexplained orphans before enforcement',
         'Disable new enforcement and restore prior mapping','NOT_STARTED',''],
        [5,'ID allocation','UPGRADE','IdAllocations and ID namespaces','Single controlled ID allocator',
         'Check all generators, Apps Script and backend call paths',
         'Preserve all historical IDs and reservations',
         'No duplicate/reused IDs under concurrent allocation tests',
         'Retain old allocator until cutover tests pass','NOT_STARTED',''],
        [6,'Data integrity','UPGRADE','Required/unique/conditional fields','Validation rules and exception handling',
         'Check current data before enabling strict validation',
         'No mass normalization or silent value coercion',
         'Zero unexplained violations; owner-approved exceptions',
         'Remove newly added rules if validation blocks valid legacy records','NOT_STARTED',''],
        [7,'Transaction/recovery','UPGRADE','Sales, stock, payments, production, accounting','Recoverable transaction controls',
         'Map every write path and ledger authority',
         'Append-only movements; idempotent retries; compensating reversals',
         'Failure/retry tests show no duplicate postings',
         'Restore prior code/config and reconcile pending transactions','NOT_STARTED',''],
        [8,'Tab/field restructuring','MIGRATE','Approved RENAME / MERGE / RETIRE / CREATE list','Final canonical structure',
         'All formulas, Apps Script, backend routes, integrations and reports mapped',
         'Copy/reconcile before cutover; never discard unreconciled records',
         'Row counts, key counts, totals and hashes reconcile',
         'Restore backup or reverse mapped copy/cutover','NOT_STARTED',''],
        [9,'Final live audit','VERIFY','Final workbook','Phase 3 acceptance',
         'Re-run contracts, relationships, IDs, integrity and transaction tests',
         'No unapproved data change','All critical acceptance gates pass',
         'Keep pre-migration backup and migration log','NOT_STARTED','']
      ];
      ksP3WriteTable_(planTab, planHeaders, planRows);
    } else {
      ksP3AssertExactHeader_(planTab, planHeaders);
    }

    let logTab = ss.getSheetByName(KS_P3_BOOT.LOG_TAB);
    if (!logTab) logTab = ss.insertSheet(KS_P3_BOOT.LOG_TAB);
    if (logTab.getLastRow() === 0) {
      ksP3WriteTable_(logTab, logHeaders, []);
    } else {
      ksP3AssertExactHeader_(logTab, logHeaders);
    }

    logTab.appendRow([
      new Date(), KS_P3_BOOT.VERSION, 'PHASE3_CONTROL_BOOTSTRAP_INSTALLED_OR_REFRESHED',
      ss.getId(), ss.getName(), backupUrl, ss.getSheets().length,
      inventory.rows.length, 'NO',
      'Control inventory refreshed. Existing plan preserved. No business tabs or data changed.'
    ]);

    SpreadsheetApp.flush();
    const result = {
      success: true,
      version: KS_P3_BOOT.VERSION,
      liveTabCount: ss.getSheets().length,
      inventoriedTabs: inventory.rows.length,
      backupUrl: backupUrl,
      controlTabs: [
        KS_P3_BOOT.INVENTORY_TAB,
        KS_P3_BOOT.PLAN_TAB,
        KS_P3_BOOT.LOG_TAB
      ],
      businessSchemaChanged: false,
      existingPlanPreserved: true
    };
    Logger.log(JSON.stringify(result, null, 2));
    return result;
  } finally {
    lock.releaseLock();
  }
}

function ksP3AssertTarget_(ss) {
  if (!ss) throw new Error('STOP: Open the LIVE Kawad Swad Google Sheet first.');
  if (ss.getId() !== KS_P3_BOOT.SPREADSHEET_ID) {
    throw new Error('STOP: Spreadsheet ID mismatch. No changes made.');
  }
  if (ss.getName().indexOf(KS_P3_BOOT.EXPECTED_NAME_PREFIX) !== 0) {
    throw new Error('STOP: Workbook name mismatch. No changes made.');
  }
}

function ksP3AssertOwnedTabHeader_(ss, name, expectedHeaders) {
  const sh = ss.getSheetByName(name);
  if (!sh || sh.getLastRow() === 0) return;
  ksP3AssertExactHeader_(sh, expectedHeaders);
}

function ksP3AssertExactHeader_(sh, expectedHeaders) {
  const lastCol = sh.getLastColumn();
  if (sh.getLastRow() === 0 || lastCol === 0) return;
  const existing = sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0]
    .map(v => String(v || '').trim());
  const expected = expectedHeaders.map(String);
  if (existing.join('\u001f') !== expected.join('\u001f')) {
    throw new Error(
      'STOP: Existing tab "' + sh.getName() +
      '" has an unexpected header. No report tab was overwritten.'
    );
  }
}

function ksP3BuildLiveInventory_(ss) {
  const headers = [
    'sheet_name','data_rows_approx','last_row','last_column',
    'nonblank_header_count','blank_header_positions','duplicate_headers',
    'physical_headers','header_sha256','captured_at'
  ];
  const capturedAt = new Date();
  const rows = ss.getSheets().map(sh => {
    const lastRow = sh.getLastRow();
    const actualLastCol = sh.getLastColumn();
    const lastCol = Math.min(actualLastCol, KS_P3_BOOT.MAX_HEADER_COLS);
    const rawHeaders = (lastRow > 0 && lastCol > 0)
      ? sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0]
          .map(v => String(v || '').trim())
      : [];
    const nonblank = rawHeaders.filter(v => v !== '');
    const blankPositions = [];
    rawHeaders.forEach((v, i) => { if (!v) blankPositions.push(i + 1); });
    const counts = {};
    nonblank.forEach(v => { counts[v] = (counts[v] || 0) + 1; });
    const duplicates = Object.keys(counts).filter(k => counts[k] > 1);
    const headerText = rawHeaders.join('|');
    const digest = Utilities.computeDigest(
      Utilities.DigestAlgorithm.SHA_256,
      headerText,
      Utilities.Charset.UTF_8
    );
    const hash = digest.map(b => {
      const n = b < 0 ? b + 256 : b;
      return ('0' + n.toString(16)).slice(-2);
    }).join('');
    return [
      sh.getName(),
      Math.max(0, lastRow - 1), // approximate, not a count of populated records
      lastRow,
      actualLastCol,
      nonblank.length,
      blankPositions.join(','),
      duplicates.join(' | '),
      rawHeaders.join(' | '),
      hash,
      capturedAt
    ];
  });
  return { headers: headers, rows: rows };
}

function ksP3ReplaceGeneratedTab_(sh, headers, rows) {
  // Caller has verified exact tab name and header contract.
  sh.clearContents();
  sh.getRange(1, 1, 1, headers.length).setValues([headers]);
  if (rows.length) {
    sh.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  sh.autoResizeColumns(1, headers.length);
}

function ksP3WriteTable_(sh, headers, rows) {
  sh.getRange(1, 1, 1, headers.length).setValues([headers]);
  if (rows.length) {
    sh.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  sh.autoResizeColumns(1, headers.length);
}

/**
 * Read-only verification after installation.
 */
function ksP3VerifyMigrationControl() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ksP3AssertTarget_(ss);
  const names = [
    KS_P3_BOOT.INVENTORY_TAB,
    KS_P3_BOOT.PLAN_TAB,
    KS_P3_BOOT.LOG_TAB
  ];
  const result = names.map(name => {
    const sh = ss.getSheetByName(name);
    return {
      tab: name,
      exists: !!sh,
      rows: sh ? Math.max(0, sh.getLastRow() - 1) : 0,
      columns: sh ? sh.getLastColumn() : 0
    };
  });
  const output = {
    success: result.every(x => x.exists),
    controls: result,
    liveTabCount: ss.getSheets().length,
    note: 'Verification only. No business tabs or data changed.'
  };
  Logger.log(JSON.stringify(output, null, 2));
  return output;
}
