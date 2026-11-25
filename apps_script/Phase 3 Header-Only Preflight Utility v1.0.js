/**
 * Kawad Swad ERP - Phase 3 Integrated Master Data
 * HEADER-ONLY PREFLIGHT UTILITY v1.0
 *
 * Purpose:
 *   Read row 1 only from these four live tabs:
 *     IdAllocations, RawMaterials, Customers, Suppliers
 *   Write the extracted header names to:
 *     KS_P3_HEADER_PREFLIGHT
 *
 * Safety:
 *   - Does NOT read rows 2 onward.
 *   - Does NOT read Users or AuthUsers.
 *   - Does NOT change business tabs, headers, or business records.
 *   - Creates/refreshes only the dedicated report tab.
 *   - Does not create IDs or master records.
 */

const KS_P3_HEADER_PREFLIGHT_CONFIG = {
  workbookId: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  workbookNamePrefix: 'Kawad_Swad_Sales_Management_Google_Sheets',
  sourceTabs: ['IdAllocations', 'RawMaterials', 'Customers', 'Suppliers'],
  reportTab: 'KS_P3_HEADER_PREFLIGHT'
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Kawad Swad | Phase 3')
    .addItem('Run Header-Only Preflight', 'KS_P3_RUN_HEADER_ONLY_PREFLIGHT')
    .addToUi();
}

function KS_P3_RUN_HEADER_ONLY_PREFLIGHT() {
  const cfg = KS_P3_HEADER_PREFLIGHT_CONFIG;
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  if (ss.getId() !== cfg.workbookId) {
    throw new Error('STOPPED: This is not the approved Kawad Swad workbook. No changes made.');
  }
  if (!ss.getName().startsWith(cfg.workbookNamePrefix)) {
    throw new Error('STOPPED: Workbook name verification failed. No changes made.');
  }

  const output = [[
    'tab_name', 'column_number', 'header_name', 'header_is_blank',
    'extraction_scope', 'source_row_read'
  ]];

  const tabSummary = [];
  const missingTabs = [];

  cfg.sourceTabs.forEach(function(tabName) {
    const sh = ss.getSheetByName(tabName);
    if (!sh) {
      missingTabs.push(tabName);
      tabSummary.push({
        tabName: tabName,
        exists: false,
        columnsRead: 0,
        nonblankHeaders: 0
      });
      return;
    }

    // Only inspect the physical width and row 1. No data rows are read.
    const lastColumn = sh.getLastColumn();
    if (lastColumn < 1) {
      tabSummary.push({
        tabName: tabName,
        exists: true,
        columnsRead: 0,
        nonblankHeaders: 0
      });
      return;
    }

    const headers = sh.getRange(1, 1, 1, lastColumn).getDisplayValues()[0];
    let nonblank = 0;

    headers.forEach(function(value, index) {
      const header = String(value == null ? '' : value).trim();
      if (header !== '') nonblank++;
      output.push([
        tabName,
        index + 1,
        header,
        header === '' ? 'YES' : 'NO',
        'HEADER_ROW_ONLY',
        1
      ]);
    });

    tabSummary.push({
      tabName: tabName,
      exists: true,
      columnsRead: lastColumn,
      nonblankHeaders: nonblank
    });
  });

  if (missingTabs.length) {
    throw new Error(
      'STOPPED: Required source tab(s) missing: ' +
      missingTabs.join(', ') +
      '. No report was written.'
    );
  }

  let report = ss.getSheetByName(cfg.reportTab);
  if (!report) report = ss.insertSheet(cfg.reportTab);

  // The only write/clear operation in this utility is on its own report tab.
  report.clearContents();
  report.getRange(1, 1, output.length, output[0].length).setValues(output);
  report.setFrozenRows(1);
  report.autoResizeColumns(1, output[0].length);

  const result = {
    success: true,
    status: 'HEADER_ONLY_PREFLIGHT_COMPLETE',
    workbookName: ss.getName(),
    workbookIdVerified: true,
    sourceTabs: cfg.sourceTabs,
    tabSummary: tabSummary,
    extractedHeaderCells: output.length - 1,
    businessRowsRead: false,
    usersDataRead: false,
    authUsersDataRead: false,
    businessSchemaChanged: false,
    businessRecordsChanged: false,
    reportTab: cfg.reportTab,
    note: 'Only row 1 was read from the four named tabs. Only the dedicated report tab was written.'
  };

  console.log('KS_P3_HEADER_ONLY_PREFLIGHT_RESULT ' + JSON.stringify(result));
  return result;
}
