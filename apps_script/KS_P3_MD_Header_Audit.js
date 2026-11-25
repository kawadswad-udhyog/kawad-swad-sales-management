/*
KAWAD SWAD ERP - PHASE 3 MASTER DATA HEADER AUDIT
Version: 1.0.0
Mode: READ-ONLY business data; creates one uniquely named audit report tab.

IMPORTANT:
- Run this function directly from the Apps Script editor.
- This file intentionally has NO onOpen() function, to avoid conflicts with existing scripts.
- It does not create/edit business records, reserve IDs, change IDs, edit Users, or access AuthUsers.
- It does not change business headers, formulas, validations, or existing tabs.
- It creates one new report tab named KS_P3_MD_HEADER_AUDIT_YYYYMMDD_HHMMSS.
- It verifies exact ordered headers for the six approved sheets from the supplied live-header report.
*/

function KS_P3_MD_HEADER_AUDIT_V1_0() {
  const CFG = {
    spreadsheetId: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
    expectedName: 'Kawad_Swad_Sales_Management_Google_Sheets',
    expected: {
      IdAllocations: ['allocation_id','tab_name','allocated_id','nonce','created_at'],
      Products: ['product_id','sku','product_name','category','variant','pack_weight_g','selling_unit','retail_pack_only','active','notes'],
      RawMaterials: ['raw_material_id','material_name','unit','opening_stock','current_stock','minimum_stock','active','notes','rate_per_unit','rate_status','category','created_at','created_by'],
      Customers: ['customer_id','customer_type','shop_name','shopkeeper_name','mobile','alternate_mobile','address','locality_area','city','map_location','active','created_at','notes','gstin'],
      Suppliers: ['supplier_id','supplier_name','contact_person','mobile','email','address','city','gstin','payment_terms_days','opening_balance','active','notes','created_at','created_by'],
      Users: ['user_id','full_name','role','mobile','email','active','created_at','notes','username','employment_type','designation','department','reporting_manager_id','joining_date','employment_status','salary_frequency','salary_structure_id','address','emergency_contact','bank_details','document_references','updated_at','created_by','effective_from','effective_to']
    }
  };

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss || ss.getId() !== CFG.spreadsheetId) {
    throw new Error('SAFETY STOP: Active spreadsheet ID does not match the approved Kawad Swad workbook. Nothing was written.');
  }
  if (ss.getName() !== CFG.expectedName) {
    throw new Error('SAFETY STOP: Active spreadsheet name does not match the approved workbook. Nothing was written.');
  }

  const checkedAt = new Date();
  const rows = [];
  Object.keys(CFG.expected).forEach(sheetName => {
    const sh = ss.getSheetByName(sheetName);
    if (!sh) {
      rows.push([sheetName, 'MISSING_TAB', '', CFG.expected[sheetName].length, 0, 'Tab not found', 'STOP']);
      return;
    }
    const lastCol = sh.getLastColumn();
    const actual = lastCol > 0
      ? sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0].map(v => String(v).trim())
      : [];
    const expected = CFG.expected[sheetName];
    const blankCols = [];
    const duplicateHeaders = [];
    const seen = {};
    actual.forEach((h, i) => {
      if (!h) blankCols.push(i + 1);
      else if (seen[h]) duplicateHeaders.push(h);
      else seen[h] = true;
    });
    const missing = expected.filter(h => actual.indexOf(h) === -1);
    const extra = actual.filter(h => h && expected.indexOf(h) === -1);
    const orderMatches = actual.length === expected.length && actual.every((h, i) => h === expected[i]);
    const issues = [];
    if (blankCols.length) issues.push('Blank header columns: ' + blankCols.join(','));
    if (duplicateHeaders.length) issues.push('Duplicate headers: ' + Array.from(new Set(duplicateHeaders)).join(', '));
    if (missing.length) issues.push('Missing: ' + missing.join(', '));
    if (extra.length) issues.push('Extra: ' + extra.join(', '));
    if (!orderMatches && !missing.length && !extra.length) issues.push('Header order differs from approved reference');
    const status = issues.length ? 'REVIEW_REQUIRED' : 'EXACT_MATCH';
    // Metadata only. No employee rows or other business data are read.
    const dataRowCountMetadata = Math.max(0, sh.getLastRow() - 1);
    rows.push([
      sheetName, status, actual.length, expected.length, dataRowCountMetadata,
      issues.length ? issues.join(' | ') : 'Exact ordered header match',
      sheetName === 'Users' ? 'HEADER_ONLY; employee values not read' : 'HEADER_ONLY; business values not read'
    ]);
  });

  const stamp = Utilities.formatDate(checkedAt, ss.getSpreadsheetTimeZone(), 'yyyyMMdd_HHmmss');
  const reportName = 'KS_P3_MD_HEADER_AUDIT_' + stamp;
  const report = ss.insertSheet(reportName);
  const reportRows = [
    ['Kawad Swad Phase 3 Master Data Header Audit', ''],
    ['Version', '1.0.0'],
    ['Checked at', checkedAt],
    ['Workbook', ss.getName()],
    ['Workbook ID verified', 'YES'],
    ['Scope', 'Six approved master-data sheets; header-only inspection'],
    ['Business data read', 'NO'],
    ['Business data changed', 'NO'],
    ['ID allocation performed', 'NO'],
    ['Users employee values read', 'NO'],
    ['AuthUsers accessed', 'NO'],
    [],
    ['Sheet', 'Status', 'Actual header count', 'Expected header count', 'Data row count (metadata only)', 'Finding', 'Read scope'],
    ...rows
  ];
  report.getRange(1, 1, reportRows.length, 7).setValues(reportRows.map(r => {
    const a = r.slice(); while (a.length < 7) a.push(''); return a;
  }));
  report.setFrozenRows(13);
  report.autoResizeColumns(1, 7);
  SpreadsheetApp.flush();

  const allExact = rows.every(r => r[1] === 'EXACT_MATCH');
  const summary = {
    status: allExact ? 'HEADER_PREFLIGHT_PASSED' : 'HEADER_REVIEW_REQUIRED',
    reportTab: reportName,
    sheetsChecked: rows.length,
    exactMatches: rows.filter(r => r[1] === 'EXACT_MATCH').length,
    reviewRequired: rows.filter(r => r[1] !== 'EXACT_MATCH').length,
    businessDataRead: false,
    businessDataChanged: false,
    usersEmployeeValuesRead: false,
    authUsersAccessed: false,
    idAllocationPerformed: false
  };
  console.log('KS_P3_MD_HEADER_AUDIT_RESULT ' + JSON.stringify(summary));
  return summary;
}
