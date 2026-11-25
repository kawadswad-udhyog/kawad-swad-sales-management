/**
 * KAWAD SWAD ERP - PHASE 3 FIELD-BY-FIELD LIVE SCHEMA RECONCILIATION v1.0
 *
 * READ-ONLY AGAINST THE WORKBOOK.
 * Creates two CSV report files in Google Drive; it does not edit workbook tabs.
 *
 * Run:
 *   ksP3FieldReconciliationPreview()
 *   ksP3CreateFieldReconciliationReports()
 *
 * The report uses exact header matching only. It does NOT auto-accept aliases,
 * fuzzy matches, rename headers, add columns, or change any business data.
 */

var KS_P3_RECON = {
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME: 'Kawad_Swad_Sales_Management_Google_Sheets',
  TABLE_REGISTRY: 'KS_P1_TABLE_REGISTRY',
  FIELD_DICTIONARY: 'KS_P1_FIELD_DICTIONARY',
  RUNTIME_REGISTRY: 'DBV5_RUNTIME_EXTRA_29'
};

function ksP3ReconReadTableNames_(ss) {
  var names = [];
  [KS_P3_RECON.TABLE_REGISTRY, KS_P3_RECON.RUNTIME_REGISTRY].forEach(function(tab) {
    var sh = ss.getSheetByName(tab);
    if (!sh) throw new Error('Missing required registry: ' + tab);
    if (sh.getLastRow() < 2) return;
    sh.getRange(2, 1, sh.getLastRow() - 1, 1).getDisplayValues().forEach(function(r) {
      var name = String(r[0] || '').trim();
      if (name && names.indexOf(name) === -1) names.push(name);
    });
  });
  return names;
}

function ksP3ReconHeaderIndex_(headers) {
  var map = {};
  headers.forEach(function(h, i) {
    var key = String(h || '').trim();
    if (key) map[key] = i;
  });
  return map;
}

function ksP3ReconCsv_(rows) {
  return rows.map(function(row) {
    return row.map(function(value) {
      var s = value === null || value === undefined ? '' : String(value);
      return '"' + s.replace(/"/g, '""') + '"';
    }).join(',');
  }).join('\r\n');
}

function ksP3ReconLoad_(ss) {
  if (ss.getName() !== KS_P3_RECON.EXPECTED_NAME) {
    throw new Error('Workbook name mismatch. No report generated.');
  }

  var dict = ss.getSheetByName(KS_P3_RECON.FIELD_DICTIONARY);
  var registry = ss.getSheetByName(KS_P3_RECON.TABLE_REGISTRY);
  if (!dict || !registry) throw new Error('Field dictionary or table registry missing.');

  var dictData = dict.getDataRange().getDisplayValues();
  var regData = registry.getDataRange().getDisplayValues();
  if (dictData.length < 2 || regData.length < 2) {
    throw new Error('Dictionary or registry has no data rows.');
  }

  var dh = ksP3ReconHeaderIndex_(dictData[0]);
  var rh = ksP3ReconHeaderIndex_(regData[0]);

  var requiredDictHeaders = [
    'Table', 'Position', 'Field', 'Data type', 'Required rule',
    'Uniqueness', 'Relationship note', 'Plain-language meaning',
    'Schema source', 'Confidence', 'Execution eligibility'
  ];
  requiredDictHeaders.forEach(function(h) {
    if (dh[h] === undefined) throw new Error('Missing dictionary column: ' + h);
  });

  var requiredRegHeaders = ['Table', 'Finalization status', 'Safe action'];
  requiredRegHeaders.forEach(function(h) {
    if (rh[h] === undefined) throw new Error('Missing registry column: ' + h);
  });

  var regByTable = {};
  for (var r = 1; r < regData.length; r++) {
    var t = String(regData[r][rh['Table']] || '').trim();
    if (t) {
      regByTable[t] = {
        finalizationStatus: regData[r][rh['Finalization status']],
        safeAction: regData[r][rh['Safe action']]
      };
    }
  }

  var names = ksP3ReconReadTableNames_(ss);
  var liveByTable = {};
  var missingTabs = [];

  names.forEach(function(name) {
    var sh = ss.getSheetByName(name);
    if (!sh) {
      missingTabs.push(name);
      liveByTable[name] = [];
      return;
    }
    var lastCol = sh.getLastColumn();
    var headers = lastCol > 0
      ? sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0]
      : [];
    liveByTable[name] = headers.map(function(h) { return String(h || '').trim(); })
      .filter(function(h) { return h !== ''; });
  });

  var fields = [];
  for (var i = 1; i < dictData.length; i++) {
    var row = dictData[i];
    var table = String(row[dh['Table']] || '').trim();
    var field = String(row[dh['Field']] || '').trim();
    if (!table || !field) continue;

    var liveHeaders = liveByTable[table] || [];
    var exact = liveHeaders.indexOf(field) !== -1;
    var caseInsensitive = liveHeaders.some(function(h) {
      return h.toLowerCase() === field.toLowerCase();
    });
    var regInfo = regByTable[table] || {};

    fields.push({
      table: table,
      position: row[dh['Position']],
      field: field,
      dataType: row[dh['Data type']],
      requiredRule: row[dh['Required rule']],
      uniqueness: row[dh['Uniqueness']],
      relationshipNote: row[dh['Relationship note']],
      plainMeaning: row[dh['Plain-language meaning']],
      schemaSource: row[dh['Schema source']],
      confidence: row[dh['Confidence']],
      executionEligibility: row[dh['Execution eligibility']],
      exactLiveHeader: exact ? 'YES' : 'NO',
      caseInsensitiveOnly: (!exact && caseInsensitive) ? 'YES' : 'NO',
      liveHeaderCount: liveHeaders.length,
      tableFinalizationStatus: regInfo.finalizationStatus || '',
      tableSafeAction: regInfo.safeAction || '',
      tableExists: ss.getSheetByName(table) ? 'YES' : 'NO'
    });
  }

  var liveOnly = [];
  Object.keys(liveByTable).forEach(function(table) {
    var liveHeaders = liveByTable[table];
    var dictionaryFields = fields.filter(function(f) { return f.table === table; })
      .map(function(f) { return f.field; });

    liveHeaders.forEach(function(header) {
      if (dictionaryFields.indexOf(header) === -1) {
        liveOnly.push({
          table: table,
          liveHeader: header,
          inDictionaryExact: 'NO',
          note: 'Live header has no exact field-name match in KS_P1_FIELD_DICTIONARY. Review manually; do not rename automatically.'
        });
      }
    });
  });

  return {
    names: names,
    missingTabs: missingTabs,
    fields: fields,
    liveOnly: liveOnly
  };
}

function ksP3FieldReconciliationPreview() {
  var ss = SpreadsheetApp.openById(KS_P3_RECON.SPREADSHEET_ID);
  var data = ksP3ReconLoad_(ss);

  var exact = data.fields.filter(function(f) { return f.exactLiveHeader === 'YES'; }).length;
  var missing = data.fields.length - exact;
  var caseOnly = data.fields.filter(function(f) { return f.caseInsensitiveOnly === 'YES'; }).length;
  var noTable = data.fields.filter(function(f) { return f.tableExists === 'NO'; }).length;

  var report = {
    previewOnly: true,
    readOnlyWorkbook: true,
    workbook: ss.getName(),
    uniqueRegisteredTabs: data.names.length,
    missingRegisteredTabs: data.missingTabs,
    dictionaryFieldRows: data.fields.length,
    exactHeaderMatches: exact,
    nonExactDictionaryFields: missing,
    caseInsensitiveOnlyMatches: caseOnly,
    dictionaryRowsWhoseTableTabIsMissing: noTable,
    liveHeadersWithoutExactDictionaryMatch: data.liveOnly.length,
    note: 'Exact-name reconciliation only. No schema or business data changed.'
  };

  Logger.log(JSON.stringify(report, null, 2));
  return report;
}

function ksP3CreateFieldReconciliationReports() {
  var ss = SpreadsheetApp.openById(KS_P3_RECON.SPREADSHEET_ID);
  var data = ksP3ReconLoad_(ss);

  var fieldHeaders = [
    'Table', 'Position', 'Field', 'Data type', 'Required rule', 'Uniqueness',
    'Relationship note', 'Plain-language meaning', 'Schema source', 'Confidence',
    'Execution eligibility', 'Exact live header', 'Case-insensitive only',
    'Live header count', 'Table finalization status', 'Table safe action', 'Table exists'
  ];

  var fieldRows = [fieldHeaders];
  data.fields.forEach(function(f) {
    fieldRows.push([
      f.table, f.position, f.field, f.dataType, f.requiredRule, f.uniqueness,
      f.relationshipNote, f.plainMeaning, f.schemaSource, f.confidence,
      f.executionEligibility, f.exactLiveHeader, f.caseInsensitiveOnly,
      f.liveHeaderCount, f.tableFinalizationStatus, f.tableSafeAction, f.tableExists
    ]);
  });

  var liveHeaders = ['Table', 'Live header', 'Exact dictionary match', 'Review note'];
  var liveRows = [liveHeaders];
  data.liveOnly.forEach(function(x) {
    liveRows.push([x.table, x.liveHeader, x.inDictionaryExact, x.note]);
  });

  var stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMdd_HHmmss');
  var fieldFile = DriveApp.createFile(
    'Kawad_Swad_Phase3_Field_Reconciliation_' + stamp + '.csv',
    ksP3ReconCsv_(fieldRows),
    MimeType.CSV
  );
  var liveFile = DriveApp.createFile(
    'Kawad_Swad_Phase3_Live_Headers_Without_Dictionary_Match_' + stamp + '.csv',
    ksP3ReconCsv_(liveRows),
    MimeType.CSV
  );

  var exactCount = data.fields.filter(function(f) { return f.exactLiveHeader === 'YES'; }).length;
  var report = {
    success: true,
    workbookModified: false,
    dictionaryFieldRows: data.fields.length,
    exactHeaderMatches: exactCount,
    nonExactDictionaryFields: data.fields.length - exactCount,
    liveHeadersWithoutExactDictionaryMatch: data.liveOnly.length,
    missingRegisteredTabs: data.missingTabs,
    fieldReconciliationCsv: fieldFile.getUrl(),
    liveOnlyHeadersCsv: liveFile.getUrl(),
    instruction: 'Review both reports. No columns were added, renamed, or approved as aliases.'
  };

  Logger.log(JSON.stringify(report, null, 2));
  return report;
}