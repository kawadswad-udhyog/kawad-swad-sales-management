/**
 * KAWAD SWAD ERP - PHASE 3 POST-RESET READ-ONLY AUDIT v1.0
 *
 * PURPOSE
 * Verify the live workbook after the successful empty-business-data reset.
 * This script is READ-ONLY: it does not create, edit, clear, rename, or delete
 * any sheet or cell. It writes results only to the Apps Script execution log.
 *
 * RUN:
 *   ksP3PostResetReadOnlyAudit()
 *
 * It checks:
 * - Correct workbook identity.
 * - Presence of the Phase 1/2/3 technical blueprint sheets.
 * - Business table names from the two approved registries.
 * - Missing registered tabs, missing/duplicate/blank headers.
 * - Residual non-formula business data below row 1.
 * - Formula and data-validation counts below the header.
 * - Critical post-reset tabs (Users, AuthUsers, Settings, IdAllocations).
 * - Field dictionary and table registry header layouts for the next schema audit.
 *
 * IMPORTANT
 * This is a verification pass, not schema implementation. It does not add
 * missing columns, change field names, initialize IDs, create admin users,
 * or change settings.
 */

var KS_P3_POST_RESET_AUDIT = {
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME: 'Kawad_Swad_Sales_Management_Google_Sheets',

  TABLE_REGISTRY: 'KS_P1_TABLE_REGISTRY',
  FIELD_DICTIONARY: 'KS_P1_FIELD_DICTIONARY',
  RUNTIME_REGISTRY: 'DBV5_RUNTIME_EXTRA_29',

  RESET_LOG: 'KS_P3_EMPTY_RESET_LOG',

  CRITICAL_EMPTY_TABS: [
    'Users',
    'AuthUsers',
    'Settings',
    'IdAllocations'
  ],

  REQUIRED_TECHNICAL_TABS: [
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


function ksP3AuditReadRegistryNames_(ss, sheetName) {
  var sh = ss.getSheetByName(sheetName);
  if (!sh) throw new Error('Required registry missing: ' + sheetName);

  var lastRow = sh.getLastRow();
  if (lastRow < 2) return [];

  return sh.getRange(2, 1, lastRow - 1, 1).getDisplayValues()
    .map(function(row) { return String(row[0] || '').trim(); })
    .filter(function(value) { return value !== ''; });
}


function ksP3AuditHeaderLayout_(ss, sheetName) {
  var sh = ss.getSheetByName(sheetName);
  if (!sh) return { sheet: sheetName, exists: false };

  var lastCol = sh.getLastColumn();
  var headers = lastCol > 0
    ? sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0]
    : [];

  var normalized = headers.map(function(value) {
    return String(value || '').trim();
  });

  var blankColumns = [];
  var seen = {};
  var duplicateHeaders = [];

  normalized.forEach(function(header, index) {
    var column = index + 1;
    if (!header) blankColumns.push(column);

    var key = header.toLowerCase();
    if (key) {
      if (seen[key]) duplicateHeaders.push({
        header: header,
        firstColumn: seen[key],
        duplicateColumn: column
      });
      else seen[key] = column;
    }
  });

  return {
    sheet: sheetName,
    exists: true,
    lastRow: sh.getLastRow(),
    lastColumn: lastCol,
    headers: normalized,
    blankHeaderColumns: blankColumns,
    duplicateHeaders: duplicateHeaders
  };
}


function ksP3AuditBusinessTab_(ss, sheetName) {
  var sh = ss.getSheetByName(sheetName);
  if (!sh) return { sheet: sheetName, exists: false };

  var lastRow = sh.getLastRow();
  var lastCol = sh.getLastColumn();

  var result = {
    sheet: sheetName,
    exists: true,
    lastRow: lastRow,
    lastColumn: lastCol,
    headerCount: 0,
    blankHeaderColumns: [],
    duplicateHeaders: [],
    residualNonFormulaCells: 0,
    residualExamples: [],
    formulasBelowHeader: 0,
    validationCellsBelowHeader: 0
  };

  if (lastCol > 0) {
    var headers = sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0];
    var seen = {};

    headers.forEach(function(value, index) {
      var header = String(value || '').trim();
      if (header) {
        result.headerCount++;
        var key = header.toLowerCase();
        if (seen[key]) {
          result.duplicateHeaders.push({
            header: header,
            firstColumn: seen[key],
            duplicateColumn: index + 1
          });
        } else {
          seen[key] = index + 1;
        }
      } else {
        result.blankHeaderColumns.push(index + 1);
      }
    });
  }

  if (lastRow > 1 && lastCol > 0) {
    var range = sh.getRange(2, 1, lastRow - 1, lastCol);
    var values = range.getValues();
    var formulas = range.getFormulas();
    var validations = range.getDataValidations();

    for (var r = 0; r < values.length; r++) {
      for (var c = 0; c < values[r].length; c++) {
        if (formulas[r][c]) result.formulasBelowHeader++;

        if (validations[r][c]) result.validationCellsBelowHeader++;

        if (!formulas[r][c] &&
            values[r][c] !== '' &&
            values[r][c] !== null) {
          result.residualNonFormulaCells++;
          if (result.residualExamples.length < 10) {
            result.residualExamples.push({
              cell: 'R' + (r + 2) + 'C' + (c + 1),
              value: String(values[r][c]).slice(0, 80)
            });
          }
        }
      }
    }
  }

  return result;
}


/**
 * Main read-only audit.
 */
function ksP3PostResetReadOnlyAudit() {
  var ss = SpreadsheetApp.openById(KS_P3_POST_RESET_AUDIT.SPREADSHEET_ID);

  if (ss.getName() !== KS_P3_POST_RESET_AUDIT.EXPECTED_NAME) {
    throw new Error(
      'Workbook name mismatch. Expected "' +
      KS_P3_POST_RESET_AUDIT.EXPECTED_NAME +
      '", found "' + ss.getName() + '".'
    );
  }

  var missingTechnicalTabs = KS_P3_POST_RESET_AUDIT.REQUIRED_TECHNICAL_TABS
    .filter(function(name) { return !ss.getSheetByName(name); });

  var canonicalNames = ksP3AuditReadRegistryNames_(
    ss,
    KS_P3_POST_RESET_AUDIT.TABLE_REGISTRY
  );
  var runtimeNames = ksP3AuditReadRegistryNames_(
    ss,
    KS_P3_POST_RESET_AUDIT.RUNTIME_REGISTRY
  );

  var allNames = Array.from(new Set(canonicalNames.concat(runtimeNames)));
  var preservedNames = new Set(KS_P3_POST_RESET_AUDIT.REQUIRED_TECHNICAL_TABS);
  var targets = allNames.filter(function(name) {
    return !preservedNames.has(name) &&
      name !== KS_P3_POST_RESET_AUDIT.RESET_LOG;
  });

  var tableResults = targets.map(function(name) {
    return ksP3AuditBusinessTab_(ss, name);
  });

  var missingBusinessTabs = tableResults
    .filter(function(item) { return !item.exists; })
    .map(function(item) { return item.sheet; });

  var residualDataTabs = tableResults
    .filter(function(item) { return item.residualNonFormulaCells > 0; })
    .map(function(item) {
      return {
        sheet: item.sheet,
        residualNonFormulaCells: item.residualNonFormulaCells,
        examples: item.residualExamples
      };
    });

  var blankHeaderTabs = tableResults
    .filter(function(item) { return item.blankHeaderColumns.length > 0; })
    .map(function(item) {
      return {
        sheet: item.sheet,
        blankHeaderColumns: item.blankHeaderColumns
      };
    });

  var duplicateHeaderTabs = tableResults
    .filter(function(item) { return item.duplicateHeaders.length > 0; })
    .map(function(item) {
      return {
        sheet: item.sheet,
        duplicateHeaders: item.duplicateHeaders
      };
    });

  var criticalTabs = KS_P3_POST_RESET_AUDIT.CRITICAL_EMPTY_TABS.map(function(name) {
    var result = ksP3AuditBusinessTab_(ss, name);
    return {
      sheet: name,
      exists: result.exists,
      residualNonFormulaCells: result.residualNonFormulaCells,
      formulasBelowHeader: result.formulasBelowHeader,
      headerCount: result.headerCount
    };
  });

  var resetLogSheet = ss.getSheetByName(KS_P3_POST_RESET_AUDIT.RESET_LOG);
  var latestResetLog = null;

  if (resetLogSheet && resetLogSheet.getLastRow() >= 2) {
    var logLastCol = resetLogSheet.getLastColumn();
    latestResetLog = resetLogSheet
      .getRange(resetLogSheet.getLastRow(), 1, 1, logLastCol)
      .getDisplayValues()[0];
  }

  var dictionaryLayout = ksP3AuditHeaderLayout_(
    ss,
    KS_P3_POST_RESET_AUDIT.FIELD_DICTIONARY
  );
  var tableRegistryLayout = ksP3AuditHeaderLayout_(
    ss,
    KS_P3_POST_RESET_AUDIT.TABLE_REGISTRY
  );

  var totalResidualCells = tableResults.reduce(function(sum, item) {
    return sum + (item.residualNonFormulaCells || 0);
  }, 0);

  var totalFormulas = tableResults.reduce(function(sum, item) {
    return sum + (item.formulasBelowHeader || 0);
  }, 0);

  var totalValidationCells = tableResults.reduce(function(sum, item) {
    return sum + (item.validationCellsBelowHeader || 0);
  }, 0);

  var report = {
    audit: 'KAWAD_SWAD_PHASE_3_POST_RESET_READ_ONLY_AUDIT',
    version: '1.0',
    readOnly: true,
    workbook: ss.getName(),
    spreadsheetId: ss.getId(),
    registryCounts: {
      canonicalRegistryRows: canonicalNames.length,
      runtimeRegistryRows: runtimeNames.length,
      uniqueRegisteredBusinessTabs: targets.length
    },
    technicalBlueprint: {
      requiredSheetsChecked: KS_P3_POST_RESET_AUDIT.REQUIRED_TECHNICAL_TABS.length,
      missingTechnicalSheets: missingTechnicalTabs
    },
    businessTables: {
      registeredTabsChecked: tableResults.length,
      missingTabs: missingBusinessTabs,
      totalResidualNonFormulaCells: totalResidualCells,
      residualDataTabs: residualDataTabs,
      tabsWithBlankHeaders: blankHeaderTabs,
      tabsWithDuplicateHeaders: duplicateHeaderTabs,
      formulaCellsBelowHeaders: totalFormulas,
      validationCellsBelowHeaders: totalValidationCells
    },
    criticalPostResetTabs: criticalTabs,
    resetLogLatestRow: latestResetLog,
    schemaSourceLayouts: {
      fieldDictionary: dictionaryLayout,
      tableRegistry: tableRegistryLayout
    },
    nextStep: 'Use the dictionary and registry header layouts to build a field-by-field live schema reconciliation. Do not auto-add or rename columns from fuzzy matches.'
  };

  Logger.log(JSON.stringify(report, null, 2));
  return report;
}
