/**
 * KAWAD SWAD ERP - PHASE 2 LIVE DATABASE PREFLIGHT
 * Version: 1.0 | REPORT-ONLY
 *
 * PURPOSE
 * - Reads the currently open, bound Google Sheet.
 * - Verifies the expected source spreadsheet ID and name.
 * - Inventories all tabs, row counts, headers and header hashes.
 * - Writes ONLY the KS_P2_LIVE_PREFLIGHT report tab.
 * - Does NOT modify business tabs, headers, data, formulas, IDs or formatting.
 * - Does NOT read or export business cell values, password hashes, bank details,
 *   employee documents, salaries or other sensitive data.
 *
 * IMPORTANT
 * - This is a live verification step, not the migration/apply script.
 * - Run it in the LIVE Kawad Swad workbook, not the downloaded XLSX.
 * - Review the generated report before any business schema changes are prepared.
 */

const KS_P2_PREFLIGHT = Object.freeze({
  VERSION: '1.0',
  EXPECTED_SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME_PREFIX: 'Kawad_Swad_Sales_Management_Google_Sheets',
  REPORT_TAB: 'KS_P2_LIVE_PREFLIGHT'
});

function ksP2RunLivePreflight() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (!ss) throw new Error('No active spreadsheet. Open the LIVE Kawad Swad Google Sheet first.');

    const actualId = ss.getId();
    const actualName = ss.getName();

    if (actualId !== KS_P2_PREFLIGHT.EXPECTED_SPREADSHEET_ID) {
      throw new Error(
        'STOP: Spreadsheet ID mismatch. Expected ' +
        KS_P2_PREFLIGHT.EXPECTED_SPREADSHEET_ID +
        ' but found ' + actualId +
        '. Do not run this preflight on a backup or another workbook.'
      );
    }
    if (actualName.indexOf(KS_P2_PREFLIGHT.EXPECTED_NAME_PREFIX) !== 0) {
      throw new Error('STOP: Workbook name does not match the approved Kawad Swad workbook.');
    }

    const rows = [];
    const sheets = ss.getSheets();
    const now = new Date();

    sheets.forEach(function(sh) {
      const lastRow = sh.getLastRow();
      const lastCol = sh.getLastColumn();
      let headers = [];
      if (lastCol > 0 && lastRow > 0) {
        headers = sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0]
          .map(function(v) { return String(v || '').trim(); });
      }
      const nonBlankHeaders = headers.filter(function(v) { return v !== ''; });
      const headerText = nonBlankHeaders.join('|');
      const digest = Utilities.computeDigest(
        Utilities.DigestAlgorithm.SHA_256,
        headerText,
        Utilities.Charset.UTF_8
      );
      const headerHash = digest.map(function(b) {
        const v = (b < 0 ? b + 256 : b).toString(16);
        return v.length === 1 ? '0' + v : v;
      }).join('');

      rows.push([
        sh.getName(),
        Math.max(0, lastRow - 1),
        lastRow,
        lastCol,
        nonBlankHeaders.length,
        headerText,
        headerHash
      ]);
    });

    const reportName = KS_P2_PREFLIGHT.REPORT_TAB;
    let report = ss.getSheetByName(reportName);
    if (!report) {
      report = ss.insertSheet(reportName);
    } else {
      report.clearContents();
    }

    const header = [
      'sheet_name',
      'data_rows_approx',
      'last_row',
      'last_column',
      'nonblank_header_count',
      'physical_headers',
      'header_sha256'
    ];

    report.getRange(1, 1, 1, header.length).setValues([header]);
    if (rows.length) {
      report.getRange(2, 1, rows.length, header.length).setValues(rows);
    }
    report.setFrozenRows(1);
    report.getRange(1, 1, 1, header.length).setFontWeight('bold');
    report.autoResizeColumns(1, header.length);

    const metaRow = rows.length + 3;
    report.getRange(metaRow, 1, 6, 2).setValues([
      ['preflight_version', KS_P2_PREFLIGHT.VERSION],
      ['generated_at', Utilities.formatDate(now, Session.getScriptTimeZone(), "yyyy-MM-dd'T'HH:mm:ss")],
      ['spreadsheet_id', actualId],
      ['spreadsheet_name', actualName],
      ['tab_count', sheets.length],
      ['operation', 'REPORT ONLY. No business tab or business data changed.']
    ]);

    SpreadsheetApp.flush();
    Logger.log(
      'Phase 2 live preflight completed. Tabs: ' + sheets.length +
      '. Report tab: ' + reportName +
      '. Business records changed: NO.'
    );
    return {
      success: true,
      tabCount: sheets.length,
      reportTab: reportName,
      businessDataChanged: false
    };
  } finally {
    lock.releaseLock();
  }
}