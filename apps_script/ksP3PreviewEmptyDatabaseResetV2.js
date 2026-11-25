/**
 * KS PHASE 3 - ONE-GO EMPTY BUSINESS DATABASE RESET (v1.2)
 * Run preview first, then the reset function.
 *
 * This version clears ONLY business-table tabs listed in:
 *   KS_P1_TABLE_REGISTRY
 *   DBV5_RUNTIME_EXTRA_29
 *
 * It preserves the complete Phase 1/2/3 blueprint, mappings, audit registers,
 * START_HERE instructions, formulas, formatting, validations and headers.
 * It clears business master and transaction data, including Settings,
 * Users/AuthUsers, IdAllocations and all listed operational tables.
 */

var KS_P3_EMPTY_V12 = {
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME: 'Kawad_Swad_Sales_Management_Google_Sheets',
CONFIRMATION: 'RESET KAWAD SWAD DATABASE TO EMPTY',
  TABLE_REGISTRY: 'KS_P1_TABLE_REGISTRY',
  RUNTIME_REGISTRY: 'DBV5_RUNTIME_EXTRA_29',
  RESET_LOG: 'KS_P3_EMPTY_RESET_LOG',
  PRESERVE_ALWAYS: [
    'START_HERE',
    'KS_P1_TABLE_REGISTRY',
    'KS_P1_FIELD_DICTIONARY',
    'KS_P1_BACKEND_CONTRACTS',
    'KS_P1_RELATIONSHIPS',
    'KS_P1_ID_POLICY',
    'KS_P1_DEPLOYMENT_LOG',
    'KS_P2_LIVE_PREFLIGHT',
    'KS_P2_MASTER_DATA_RULES',
    'KS_P2_DEPLOYMENT_LOG',
    'KS_P3_LIVE_INVENTORY',
    'KS_P3_MIGRATION_PLAN',
    'KS_P3_MIGRATION_LOG',
    'KS_P3_TABLE_MAPPING',
    'KS_P3_FIELD_MAPPING',
    'KS_SCHEMA_AUDIT',
    'KS_FIELD_MAPPING',
    'KS_OPEN_DECISIONS',
    'KS_DEPLOYMENT_LOG',
    'KS_FULL_AUDIT_EXPORT',
    'KS_DEPLOYMENT_AUDIT',
    'DBV5_LIVE_251_INVENTORY',
    'DBV5_TABLE_REGISTER_218',
    'DBV5_FIELD_DICTIONARY_3074',
    'DBV5_BACKEND_CONTRACTS_66',
    'DBV5_RUNTIME_EXTRA_29',
    'DBV5_RELATIONSHIP_REVIEW',
    'DBV5_RAW_LEDGER_REPAIR_AUDIT',
    'DBV5_BACKEND_FILE_REFERENCES',
    'DBV5_FINALIZATION_GATES',
    'DBV5_BACKEND_TEST_RESULTS',
    'DBV5_FINAL_STATUS',
    'DB_Final_Execution_Audit',
    'DB_Header_Conflict_Register',
    'DB_Setup_Audit'
  ]
};

function ksP3V12GetBusinessTableNames_(ss) {
  var names = new Set();
  var registry = ss.getSheetByName(KS_P3_EMPTY_V12.TABLE_REGISTRY);
  if (!registry) throw new Error('Missing ' + KS_P3_EMPTY_V12.TABLE_REGISTRY + '. Reset aborted.');

  // Table registry: first column is "Table"; rows below are table names.
  var last = registry.getLastRow();
  if (last > 1) {
    registry.getRange(2, 1, last - 1, 1).getDisplayValues().forEach(function(r) {
      var n = String(r[0] || '').trim();
      if (n) names.add(n);
    });
  }

  // Runtime-only tables: first column is "Tab"; rows below are table names.
  var runtime = ss.getSheetByName(KS_P3_EMPTY_V12.RUNTIME_REGISTRY);
  if (!runtime) throw new Error('Missing ' + KS_P3_EMPTY_V12.RUNTIME_REGISTRY + '. Reset aborted.');
  last = runtime.getLastRow();
  if (last > 1) {
    runtime.getRange(2, 1, last - 1, 1).getDisplayValues().forEach(function(r) {
      var n = String(r[0] || '').trim();
      if (n) names.add(n);
    });
  }

  KS_P3_EMPTY_V12.PRESERVE_ALWAYS.forEach(function(n) { names.delete(n); });
  names.delete(KS_P3_EMPTY_V12.RESET_LOG);
  return names;
}

function ksP3V12PreviewEmptyDatabaseReset() {
  var ss = SpreadsheetApp.openById(KS_P3_EMPTY_V12.SPREADSHEET_ID);
  if (ss.getName() !== KS_P3_EMPTY_V12.EXPECTED_NAME) {
    throw new Error('Workbook name mismatch. Preview stopped.');
  }
  var targets = ksP3V12GetBusinessTableNames_(ss);
  var preview = [];
  var totalCells = 0;
  var targetCount = 0;

  ss.getSheets().forEach(function(sh) {
    var name = sh.getName();
    var lr = sh.getLastRow();
    var lc = sh.getLastColumn();
    var target = targets.has(name);
    var count = 0;

    if (target && lr > 1 && lc > 0) {
      var vals = sh.getRange(2, 1, lr - 1, lc).getValues();
      var forms = sh.getRange(2, 1, lr - 1, lc).getFormulas();
      for (var r = 0; r < vals.length; r++) {
        for (var c = 0; c < vals[r].length; c++) {
          if (!forms[r][c] && vals[r][c] !== '' && vals[r][c] !== null) count++;
        }
      }
      totalCells += count;
      targetCount++;
    }
    preview.push({
      sheet: name,
      action: target ? 'CLEAR BUSINESS DATA; KEEP HEADER' :
        (KS_P3_EMPTY_V12.PRESERVE_ALWAYS.indexOf(name) >= 0 ? 'PRESERVE BLUEPRINT / CONTROL' : 'PRESERVE UNMAPPED SHEET'),
      dataCellsToClear: count,
      lastRow: lr,
      lastColumn: lc
    });
  });

  // Short log, not a huge JSON dump.
  var summary = {
    previewOnly: true,
    workbook: ss.getName(),
    businessTableTargetsFound: targetCount,
    totalNonFormulaCellsToClear: totalCells,
    preservedBlueprintAndControlSheets: KS_P3_EMPTY_V12.PRESERVE_ALWAYS.length,
    targetSheetNames: preview.filter(function(x) {
      return x.action === 'CLEAR BUSINESS DATA; KEEP HEADER';
    }).map(function(x) { return x.sheet; })
  };
  Logger.log(JSON.stringify(summary, null, 2));
  return summary;
}

function ksP3V12ExecuteEmptyDatabaseReset() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('Another migration is running. No changes made.');

  var backup = null;
  try {
    var ss = SpreadsheetApp.openById(KS_P3_EMPTY_V12.SPREADSHEET_ID);
    if (ss.getName() !== KS_P3_EMPTY_V12.EXPECTED_NAME) {
      throw new Error('Workbook name mismatch. No changes made.');
    }

    var targets = ksP3V12GetBusinessTableNames_(ss);
    var typed = Browser.inputBox(
      'FINAL DATABASE RESET CONFIRMATION',
      'A Drive backup will be created first. Then all data rows in registered business tables will be cleared.\\n' +
      'Blueprint and audit registers will be preserved.\\n\\nType exactly:\\n' +
      KS_P3_EMPTY_V12.CONFIRMATION,
      Browser.Buttons.OK_CANCEL
    );
    if (String(typed || '').trim() !== KS_P3_EMPTY_V12.CONFIRMATION) {
      throw new Error('Confirmation phrase did not match. No changes made.');
    }

    // Backup is mandatory and occurs before the first deletion.
    var sourceFile = DriveApp.getFileById(KS_P3_EMPTY_V12.SPREADSHEET_ID);
    var backupName = ss.getName() + '_PRE_EMPTY_DB_RESET_' +
      Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMdd_HHmmss');
    backup = sourceFile.makeCopy(backupName);
    if (!backup || !backup.getId()) throw new Error('Backup failed. No data was cleared.');

    var results = [];
    var totalCleared = 0;
    var missingTabs = [];

    targets.forEach(function(name) {
      var sh = ss.getSheetByName(name);
      if (!sh) {
        missingTabs.push(name);
        return;
      }
      var lr = sh.getLastRow();
      var lc = sh.getLastColumn();
      var cleared = 0;
      if (lr > 1 && lc > 0) {
        var body = sh.getRange(2, 1, lr - 1, lc);
        var vals = body.getValues();
        var formulas = body.getFormulas();
        var output = vals.map(function(row, r) {
          return row.map(function(v, c) {
            if (formulas[r][c]) return formulas[r][c];
            if (v !== '' && v !== null) cleared++;
            return '';
          });
        });
        if (cleared > 0) body.setValues(output);
      }
      totalCleared += cleared;
      results.push({sheet: name, clearedCells: cleared});
    });

    // Verify target business tables contain no constants below row 1.
    var failures = [];
    results.forEach(function(item) {
      var sh = ss.getSheetByName(item.sheet);
      var lr = sh.getLastRow();
      var lc = sh.getLastColumn();
      if (lr <= 1 || lc < 1) return;
      var vals = sh.getRange(2, 1, lr - 1, lc).getValues();
      var formulas = sh.getRange(2, 1, lr - 1, lc).getFormulas();
      for (var r = 0; r < vals.length; r++) {
        for (var c = 0; c < vals[r].length; c++) {
          if (!formulas[r][c] && vals[r][c] !== '' && vals[r][c] !== null) {
            failures.push(item.sheet + '!R' + (r + 2) + 'C' + (c + 1));
            if (failures.length >= 100) return;
          }
        }
        if (failures.length >= 100) return;
      }
    });

    var log = ss.getSheetByName(KS_P3_EMPTY_V12.RESET_LOG);
    if (!log) {
      log = ss.insertSheet(KS_P3_EMPTY_V12.RESET_LOG);
      log.appendRow(['timestamp','operation','status','backup_url','backup_file_id',
        'business_tables_cleared','cleared_cell_count','missing_registered_tabs',
        'verification_failures','notes']);
    }
    var status = failures.length === 0 ? 'SUCCESS' : 'VERIFICATION_FAILED';
    log.appendRow([new Date(),'PHASE_3_EMPTY_BUSINESS_DATABASE_RESET',status,
      backup.getUrl(),backup.getId(),results.length,totalCleared,
      missingTabs.join(' | '),failures.join(' | '),
      'Blueprint/control registers preserved; registered business-table data rows cleared.']);

    if (failures.length) {
      throw new Error('Reset verification failed. Backup: ' + backup.getUrl() +
        '. Remaining cells: ' + failures.slice(0,10).join(', '));
    }

    var result = {
      success: true,
      workbook: ss.getName(),
      businessTablesCleared: results.length,
      clearedNonFormulaCells: totalCleared,
      missingRegisteredTabs: missingTabs,
      backupUrl: backup.getUrl(),
      status: status,
      note: 'Only registered business-table data rows were cleared. Technical blueprint and control registers were preserved.'
    };
    Logger.log(JSON.stringify(result, null, 2));
    return result;

  } catch (e) {
    Logger.log('PHASE 3 RESET STOPPED: ' + (e && e.stack ? e.stack : e));
    throw e;
  } finally {
    lock.releaseLock();
  }
}
