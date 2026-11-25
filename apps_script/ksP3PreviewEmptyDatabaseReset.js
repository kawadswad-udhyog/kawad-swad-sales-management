// KAWAD SWAD ERP - PHASE 3 ONE-GO EMPTY DATABASE RESET
const KS_P3_RESET_CONFIG = Object.freeze({
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME: 'Kawad_Swad_Sales_Management_Google_Sheets',
  CONFIRMATION_PHRASE: 'RESET KAWAD SWAD DATABASE TO EMPTY',
  BACKUP_FOLDER_ID: '', // Optional: put a Drive folder ID here. Blank = same folder as source.
  CONTROL_SHEETS_TO_PRESERVE: [
    'KS_P3_LIVE_INVENTORY',
    'KS_P3_MIGRATION_PLAN',
    'KS_P3_MIGRATION_LOG',
    'KS_P3_TABLE_MAPPING',
    'KS_P3_FIELD_MAPPING'
  ],
  RESET_LOG_SHEET: 'KS_P3_EMPTY_RESET_LOG'
});

/**
 * MAIN ONE-GO RUNNER.
 * Execute this function once from Apps Script.
 */
function ksP3ExecuteEmptyDatabaseReset() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('Another migration is running. No changes made.');

  let backupFile = null;
  const startedAt = new Date();
  const resetCounts = [];

  try {
    const ss = SpreadsheetApp.openById(KS_P3_RESET_CONFIG.SPREADSHEET_ID);
    if (ss.getName() !== KS_P3_RESET_CONFIG.EXPECTED_NAME) {
      throw new Error('Workbook name mismatch. Expected "' +
        KS_P3_RESET_CONFIG.EXPECTED_NAME + '", found "' + ss.getName() + '". No changes made.');
    }

    const typed = Browser.inputBox(
      'FINAL DESTRUCTIVE CONFIRMATION',
      'This will permanently clear all business data rows from the live workbook after making a backup.\\n\\n' +
      'Type exactly:\\n' + KS_P3_RESET_CONFIG.CONFIRMATION_PHRASE,
      Browser.Buttons.OK_CANCEL
    );
    if (typed !== KS_P3_RESET_CONFIG.CONFIRMATION_PHRASE) {
      throw new Error('Confirmation phrase did not match. No changes made.');
    }

    // Create a full workbook backup before touching any sheet.
    const sourceFile = DriveApp.getFileById(KS_P3_RESET_CONFIG.SPREADSHEET_ID);
    const backupName = ss.getName() + '_PRE_EMPTY_RESET_BACKUP_' +
      Utilities.formatDate(startedAt, Session.getScriptTimeZone(), 'yyyyMMdd_HHmmss');
    backupFile = KS_P3_RESET_CONFIG.BACKUP_FOLDER_ID
      ? sourceFile.makeCopy(backupName, DriveApp.getFolderById(KS_P3_RESET_CONFIG.BACKUP_FOLDER_ID))
      : sourceFile.makeCopy(backupName);

    if (!backupFile || !backupFile.getId()) {
      throw new Error('Backup creation failed. Reset aborted before data deletion.');
    }

    const protectedNames = new Set(KS_P3_RESET_CONFIG.CONTROL_SHEETS_TO_PRESERVE);
    const sheets = ss.getSheets();

    // Preflight all sheets before first write.
    const preflight = sheets.map(sh => ({
      name: sh.getName(),
      rows: sh.getLastRow(),
      cols: sh.getLastColumn(),
      protected: protectedNames.has(sh.getName())
    }));

    // Preserve all table headers (row 1) and formulas. Clear all other values.
    for (const sh of sheets) {
      const name = sh.getName();
      if (protectedNames.has(name) || name === KS_P3_RESET_CONFIG.RESET_LOG_SHEET) continue;

      const lastRow = sh.getLastRow();
      const lastCol = sh.getLastColumn();
      if (lastRow <= 1 || lastCol < 1) {
        resetCounts.push({sheet: name, clearedCells: 0, status: 'NO DATA ROWS'});
        continue;
      }

      const body = sh.getRange(2, 1, lastRow - 1, lastCol);
      const values = body.getValues();
      const formulas = body.getFormulas();
      let clearedCells = 0;

      const output = values.map((row, r) => row.map((value, c) => {
        if (formulas[r][c]) return formulas[r][c];
        if (value !== '' && value !== null) clearedCells++;
        return '';
      }));

      if (clearedCells > 0) body.setValues(output);
      resetCounts.push({sheet: name, clearedCells: clearedCells, status: 'CLEARED'});
    }

    // Verify all non-control sheets contain no constants below the header.
    const verificationFailures = [];
    for (const sh of ss.getSheets()) {
      if (protectedNames.has(sh.getName()) || sh.getName() === KS_P3_RESET_CONFIG.RESET_LOG_SHEET) continue;
      const lr = sh.getLastRow();
      const lc = sh.getLastColumn();
      if (lr <= 1 || lc < 1) continue;
      const vals = sh.getRange(2, 1, lr - 1, lc).getValues();
      const forms = sh.getRange(2, 1, lr - 1, lc).getFormulas();
      for (let r = 0; r < vals.length; r++) {
        for (let c = 0; c < vals[r].length; c++) {
          if (!forms[r][c] && vals[r][c] !== '' && vals[r][c] !== null) {
            verificationFailures.push(sh.getName() + '!R' + (r + 2) + 'C' + (c + 1));
            if (verificationFailures.length >= 100) break;
          }
        }
        if (verificationFailures.length >= 100) break;
      }
      if (verificationFailures.length >= 100) break;
    }

    const log = ksP3GetOrCreateResetLog_(ss);
    log.appendRow([
      new Date(), 'EMPTY_DATABASE_RESET',
      verificationFailures.length === 0 ? 'SUCCESS' : 'PARTIAL_FAILURE',
      backupFile.getUrl(), backupFile.getId(),
      sheets.length, resetCounts.reduce((n, x) => n + x.clearedCells, 0),
      verificationFailures.join(' | '),
      'Headers/formulas/formatting/validation preserved; business data rows cleared.'
    ]);

    if (verificationFailures.length) {
      throw new Error('Reset ran but verification found remaining constants: ' +
        verificationFailures.slice(0, 10).join(', ') +
        '. Backup: ' + backupFile.getUrl());
    }

    const result = {
      success: true,
      workbook: ss.getName(),
      sheetCount: sheets.length,
      clearedCells: resetCounts.reduce((n, x) => n + x.clearedCells, 0),
      clearedSheets: resetCounts.filter(x => x.status === 'CLEARED').length,
      preservedControlSheets: Array.from(protectedNames),
      backupUrl: backupFile.getUrl(),
      backupFileId: backupFile.getId(),
      completedAt: new Date().toISOString(),
      note: 'All non-control sheets were cleared below row 1. Headers and formulas remain.'
    };
    console.log(JSON.stringify(result, null, 2));
    return result;

  } catch (err) {
    console.error('PHASE 3 EMPTY RESET FAILED: ' + (err && err.stack ? err.stack : err));
    throw err;
  } finally {
    lock.releaseLock();
  }
}

function ksP3GetOrCreateResetLog_(ss) {
  let sh = ss.getSheetByName(KS_P3_RESET_CONFIG.RESET_LOG_SHEET);
  if (!sh) {
    sh = ss.insertSheet(KS_P3_RESET_CONFIG.RESET_LOG_SHEET);
    sh.appendRow([
      'timestamp', 'operation', 'status', 'backup_url', 'backup_file_id',
      'sheet_count', 'cleared_cell_count', 'verification_failures', 'notes'
    ]);
  }
  return sh;
}

/**
 * NON-DESTRUCTIVE PREVIEW.
 * Run this first if you want a sheet-by-sheet count before executing the reset.
 */
function ksP3PreviewEmptyDatabaseReset() {
  const ss = SpreadsheetApp.openById(KS_P3_RESET_CONFIG.SPREADSHEET_ID);
  if (ss.getName() !== KS_P3_RESET_CONFIG.EXPECTED_NAME) {
    throw new Error('Workbook name mismatch. Preview aborted.');
  }
  const protectedNames = new Set(KS_P3_RESET_CONFIG.CONTROL_SHEETS_TO_PRESERVE);
  const preview = ss.getSheets().map(sh => {
    const lr = sh.getLastRow();
    const lc = sh.getLastColumn();
    let populated = 0;
    if (lr > 1 && lc > 0) {
      const vals = sh.getRange(2, 1, lr - 1, lc).getValues();
      const forms = sh.getRange(2, 1, lr - 1, lc).getFormulas();
      for (let r = 0; r < vals.length; r++) {
        for (let c = 0; c < vals[r].length; c++) {
          if (!forms[r][c] && vals[r][c] !== '' && vals[r][c] !== null) populated++;
        }
      }
    }
    return {
      sheet: sh.getName(),
      lastRow: lr,
      lastColumn: lc,
      nonFormulaDataCellsBelowHeader: populated,
      action: protectedNames.has(sh.getName()) ? 'PRESERVE CONTROL REGISTER' : 'CLEAR DATA ROWS; KEEP HEADER'
    };
  });
  console.log(JSON.stringify(preview, null, 2));
  return preview;
}
