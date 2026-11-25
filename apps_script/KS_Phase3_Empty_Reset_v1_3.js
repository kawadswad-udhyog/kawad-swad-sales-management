/**
 * KAWAD SWAD ERP - PHASE 3 ONE-GO EMPTY BUSINESS DATABASE RESET (v1.3)
 *
 * PURPOSE
 * Clear business data from registered business tables while preserving the
 * complete technical blueprint, mappings, audit registers and sheet design.
 *
 * TARGET REGISTRIES
 *   KS_P1_TABLE_REGISTRY
 *   DBV5_RUNTIME_EXTRA_29
 *
 * SAFETY
 * - Verifies workbook ID and name.
 * - Uses a native YES/NO confirmation dialog. No typed confirmation phrase.
 * - Creates a full Drive backup BEFORE clearing any business data.
 * - Clears only data rows (row 2 onward) of registered business tables.
 * - Preserves row 1 headers, formulas, formatting, validations and sheet names.
 * - Preserves all blueprint/control sheets listed below.
 * - Verifies target business tables after clearing and writes a reset log.
 *
 * RUN PREVIEW FIRST:
 *   ksP3V13PreviewEmptyDatabaseReset()
 *
 * THEN RUN:
 *   ksP3V13ExecuteEmptyDatabaseReset()
 */

var KS_P3_EMPTY_V13 = {
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME: 'Kawad_Swad_Sales_Management_Google_Sheets',
  TABLE_REGISTRY: 'KS_P1_TABLE_REGISTRY',
  RUNTIME_REGISTRY: 'DBV5_RUNTIME_EXTRA_29',
  RESET_LOG: 'KS_P3_EMPTY_RESET_LOG',

  // Optional: enter a Google Drive folder ID to store the backup there.
  // Leave blank to place the backup beside the source workbook.
  BACKUP_FOLDER_ID: '',

  PRESERVE_ALWAYS: [
    'START_HERE',

    // Phase 1 blueprint
    'KS_P1_TABLE_REGISTRY',
    'KS_P1_FIELD_DICTIONARY',
    'KS_P1_BACKEND_CONTRACTS',
    'KS_P1_RELATIONSHIPS',
    'KS_P1_ID_POLICY',
    'KS_P1_DEPLOYMENT_LOG',

    // Phase 2 blueprint and reconciliation
    'KS_P2_LIVE_PREFLIGHT',
    'KS_P2_MASTER_DATA_RULES',
    'KS_P2_DEPLOYMENT_LOG',

    // Phase 3 migration and mapping registers
    'KS_P3_LIVE_INVENTORY',
    'KS_P3_MIGRATION_PLAN',
    'KS_P3_MIGRATION_LOG',
    'KS_P3_TABLE_MAPPING',
    'KS_P3_FIELD_MAPPING',

    // Existing technical audits and control registers
    'KS_SCHEMA_AUDIT',
    'KS_FIELD_MAPPING',
    'KS_OPEN_DECISIONS',
    'KS_DEPLOYMENT_LOG',
    'KS_FULL_AUDIT_EXPORT',
    'KS_DEPLOYMENT_AUDIT',

    // DBV5 blueprint / technical review registers
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


/**
 * Read business table names from the approved registries.
 * Registry column A contains the table/tab name; row 1 is the header.
 */
function ksP3V13GetBusinessTableNames_(ss) {
  var names = new Set();

  var tableRegistry = ss.getSheetByName(KS_P3_EMPTY_V13.TABLE_REGISTRY);
  if (!tableRegistry) {
    throw new Error(
      'Missing registry: ' + KS_P3_EMPTY_V13.TABLE_REGISTRY +
      '. Reset aborted before any changes.'
    );
  }

  var lastRow = tableRegistry.getLastRow();
  if (lastRow > 1) {
    tableRegistry.getRange(2, 1, lastRow - 1, 1)
      .getDisplayValues()
      .forEach(function(row) {
        var name = String(row[0] || '').trim();
        if (name) names.add(name);
      });
  }

  var runtimeRegistry = ss.getSheetByName(KS_P3_EMPTY_V13.RUNTIME_REGISTRY);
  if (!runtimeRegistry) {
    throw new Error(
      'Missing registry: ' + KS_P3_EMPTY_V13.RUNTIME_REGISTRY +
      '. Reset aborted before any changes.'
    );
  }

  lastRow = runtimeRegistry.getLastRow();
  if (lastRow > 1) {
    runtimeRegistry.getRange(2, 1, lastRow - 1, 1)
      .getDisplayValues()
      .forEach(function(row) {
        var name = String(row[0] || '').trim();
        if (name) names.add(name);
      });
  }

  // Explicitly remove all technical/blueprint sheets from the deletion set.
  KS_P3_EMPTY_V13.PRESERVE_ALWAYS.forEach(function(name) {
    names.delete(name);
  });
  names.delete(KS_P3_EMPTY_V13.RESET_LOG);

  return names;
}


/**
 * NON-DESTRUCTIVE PREVIEW.
 * Review the target list before running the reset.
 */
function ksP3V13PreviewEmptyDatabaseReset() {
  var ss = SpreadsheetApp.openById(KS_P3_EMPTY_V13.SPREADSHEET_ID);

  if (ss.getName() !== KS_P3_EMPTY_V13.EXPECTED_NAME) {
    throw new Error('Workbook name mismatch. Preview stopped.');
  }

  var targets = ksP3V13GetBusinessTableNames_(ss);
  var targetSheets = [];
  var totalNonFormulaCells = 0;
  var populatedTargetSheets = 0;
  var missingRegisteredTabs = [];

  targets.forEach(function(name) {
    var sh = ss.getSheetByName(name);
    if (!sh) {
      missingRegisteredTabs.push(name);
      return;
    }

    var lastRow = sh.getLastRow();
    var lastCol = sh.getLastColumn();
    var nonFormulaCells = 0;

    if (lastRow > 1 && lastCol > 0) {
      var values = sh.getRange(2, 1, lastRow - 1, lastCol).getValues();
      var formulas = sh.getRange(2, 1, lastRow - 1, lastCol).getFormulas();

      for (var r = 0; r < values.length; r++) {
        for (var c = 0; c < values[r].length; c++) {
          if (!formulas[r][c] && values[r][c] !== '' && values[r][c] !== null) {
            nonFormulaCells++;
          }
        }
      }
    }

    if (nonFormulaCells > 0) populatedTargetSheets++;
    totalNonFormulaCells += nonFormulaCells;

    targetSheets.push({
      sheet: name,
      populatedCellsToClear: nonFormulaCells,
      lastRow: lastRow,
      lastColumn: lastCol
    });
  });

  var result = {
    previewOnly: true,
    workbook: ss.getName(),
    registeredBusinessTablesFound: targetSheets.length,
    populatedBusinessTables: populatedTargetSheets,
    totalNonFormulaCellsToClear: totalNonFormulaCells,
    missingRegisteredTabs: missingRegisteredTabs,
    preservedBlueprintAndControlSheets: KS_P3_EMPTY_V13.PRESERVE_ALWAYS.length,
    targetSheetNames: targetSheets.map(function(item) {
      return item.sheet;
    })
  };

  Logger.log(JSON.stringify(result, null, 2));
  return result;
}


/**
 * DESTRUCTIVE ONE-GO RESET.
 *
 * A native YES/NO dialog replaces the unreliable typed phrase.
 * A Drive backup is created before the first data-clearing operation.
 */
function ksP3V13ExecuteEmptyDatabaseReset() {
  var lock = LockService.getScriptLock();

  if (!lock.tryLock(30000)) {
    throw new Error('Another migration is running. No changes made.');
  }

  var backupFile = null;

  try {
    var ss = SpreadsheetApp.openById(KS_P3_EMPTY_V13.SPREADSHEET_ID);

    if (ss.getName() !== KS_P3_EMPTY_V13.EXPECTED_NAME) {
      throw new Error('Workbook name mismatch. Reset aborted.');
    }

    var targets = ksP3V13GetBusinessTableNames_(ss);

    if (targets.size === 0) {
      throw new Error('No registered business tables found. Reset aborted.');
    }

    // Native confirmation dialog. Click YES to proceed, NO to stop.
    var ui = SpreadsheetApp.getUi();
    var response = ui.alert(
      'FINAL DATABASE RESET CONFIRMATION',
      'You are about to clear all data rows in the registered business tables.\n\n' +
      'A complete Google Drive backup will be created BEFORE deletion.\n\n' +
      'WILL BE CLEARED:\n' +
      '- Business master records\n' +
      '- Sales, purchases, payments and expenses\n' +
      '- Production and stock records\n' +
      '- Users and authentication records\n' +
      '- Settings and ID allocation records\n\n' +
      'WILL BE PRESERVED:\n' +
      '- Phase 1, Phase 2 and Phase 3 blueprints\n' +
      '- Table and field dictionaries\n' +
      '- Backend contracts and relationships\n' +
      '- Migration registers and technical audits\n' +
      '- Headers, formulas, formatting and validations\n\n' +
      'Do you want to create the backup and continue?',
      ui.ButtonSet.YES_NO
    );

    if (response !== ui.Button.YES) {
      throw new Error('Reset cancelled by user. No changes made.');
    }

    Logger.log('Reset confirmed by user. Creating backup now.');

    // Mandatory backup, before any deletion.
    var sourceFile = DriveApp.getFileById(KS_P3_EMPTY_V13.SPREADSHEET_ID);
    var timestamp = Utilities.formatDate(
      new Date(),
      Session.getScriptTimeZone(),
      'yyyyMMdd_HHmmss'
    );
    var backupName = ss.getName() + '_PRE_EMPTY_DB_RESET_' + timestamp;

    if (KS_P3_EMPTY_V13.BACKUP_FOLDER_ID) {
      backupFile = sourceFile.makeCopy(
        backupName,
        DriveApp.getFolderById(KS_P3_EMPTY_V13.BACKUP_FOLDER_ID)
      );
    } else {
      backupFile = sourceFile.makeCopy(backupName);
    }

    if (!backupFile || !backupFile.getId()) {
      throw new Error('Backup creation failed. No business data was cleared.');
    }

    Logger.log('Backup created: ' + backupFile.getUrl());

    var clearedResults = [];
    var missingTabs = [];
    var totalClearedCells = 0;

    // Clear only registered business table tabs. Row 1 is always retained.
    targets.forEach(function(name) {
      var sh = ss.getSheetByName(name);

      if (!sh) {
        missingTabs.push(name);
        return;
      }

      var lastRow = sh.getLastRow();
      var lastCol = sh.getLastColumn();
      var clearedCells = 0;

      if (lastRow > 1 && lastCol > 0) {
        var body = sh.getRange(2, 1, lastRow - 1, lastCol);
        var values = body.getValues();
        var formulas = body.getFormulas();

        var output = values.map(function(row, r) {
          return row.map(function(value, c) {
            if (formulas[r][c]) {
              return formulas[r][c];
            }

            if (value !== '' && value !== null) {
              clearedCells++;
            }

            return '';
          });
        });

        if (clearedCells > 0) {
          body.setValues(output);
        }
      }

      totalClearedCells += clearedCells;
      clearedResults.push({
        sheet: name,
        clearedCells: clearedCells
      });
    });

    SpreadsheetApp.flush();

    // Verify that no non-formula constants remain below row 1 in target tabs.
    var verificationFailures = [];

    clearedResults.forEach(function(item) {
      if (verificationFailures.length >= 100) return;

      var sh = ss.getSheetByName(item.sheet);
      if (!sh) {
        verificationFailures.push(item.sheet + ': SHEET MISSING AFTER RESET');
        return;
      }

      var lastRow = sh.getLastRow();
      var lastCol = sh.getLastColumn();

      if (lastRow <= 1 || lastCol < 1) return;

      var values = sh.getRange(2, 1, lastRow - 1, lastCol).getValues();
      var formulas = sh.getRange(2, 1, lastRow - 1, lastCol).getFormulas();

      for (var r = 0; r < values.length; r++) {
        for (var c = 0; c < values[r].length; c++) {
          if (!formulas[r][c] && values[r][c] !== '' && values[r][c] !== null) {
            verificationFailures.push(
              item.sheet + '!R' + (r + 2) + 'C' + (c + 1)
            );
            if (verificationFailures.length >= 100) return;
          }
        }
        if (verificationFailures.length >= 100) return;
      }
    });

    // Write a permanent reset log. This log is technical evidence, not business data.
    var resetLog = ss.getSheetByName(KS_P3_EMPTY_V13.RESET_LOG);

    if (!resetLog) {
      resetLog = ss.insertSheet(KS_P3_EMPTY_V13.RESET_LOG);
      resetLog.appendRow([
        'timestamp',
        'operation',
        'status',
        'backup_url',
        'backup_file_id',
        'business_tables_processed',
        'cleared_cell_count',
        'missing_registered_tabs',
        'verification_failures',
        'notes'
      ]);
    }

    var finalStatus = verificationFailures.length === 0
      ? 'SUCCESS'
      : 'VERIFICATION_FAILED';

    resetLog.appendRow([
      new Date(),
      'PHASE_3_EMPTY_BUSINESS_DATABASE_RESET',
      finalStatus,
      backupFile.getUrl(),
      backupFile.getId(),
      clearedResults.length,
      totalClearedCells,
      missingTabs.join(' | '),
      verificationFailures.join(' | '),
      'Registered business data rows cleared; technical blueprint/control registers preserved.'
    ]);

    SpreadsheetApp.flush();

    if (verificationFailures.length > 0) {
      throw new Error(
        'Reset verification failed. Backup is available at: ' +
        backupFile.getUrl() +
        '. Remaining data examples: ' +
        verificationFailures.slice(0, 10).join(', ')
      );
    }

    var finalResult = {
      success: true,
      workbook: ss.getName(),
      businessTablesProcessed: clearedResults.length,
      clearedNonFormulaCells: totalClearedCells,
      missingRegisteredTabs: missingTabs,
      backupUrl: backupFile.getUrl(),
      backupFileId: backupFile.getId(),
      status: finalStatus,
      note: 'Registered business-table data rows cleared. Technical blueprint and control registers preserved.'
    };

    Logger.log(JSON.stringify(finalResult, null, 2));
    return finalResult;

  } catch (error) {
    Logger.log(
      'PHASE 3 RESET STOPPED: ' +
      (error && error.stack ? error.stack : error)
    );
    throw error;

  } finally {
    lock.releaseLock();
  }
}
