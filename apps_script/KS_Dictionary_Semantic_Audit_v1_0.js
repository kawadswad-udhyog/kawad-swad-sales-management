/**
 * KAWAD SWAD - DICTIONARY SEMANTIC QUALITY AUDIT
 * Version: 1.0
 * READ-ONLY. This script inspects only schema/governance registers.
 * It does not read business transaction rows, employee personal data, or AuthUsers.
 * It does not create, rename, clear, format, or write any worksheet or Drive file.
 *
 * Run: KS_RUN_DICTIONARY_SEMANTIC_AUDIT
 */

var KS_DSA_CONFIG = {
  spreadsheetId: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  expectedSpreadsheetName: 'Kawad_Swad_Sales_Management_Google_Sheets',
  dictionarySheet: 'KS_P1_FIELD_DICTIONARY',
  tableRegisterSheet: 'KS_P1_TABLE_REGISTRY',
  relationshipSheet: 'KS_P1_RELATIONSHIPS',
  maxFindingsPerPart: 35,
  maxCharsPerPart: 5200
};

function KS_RUN_DICTIONARY_SEMANTIC_AUDIT() {
  var ss = SpreadsheetApp.openById(KS_DSA_CONFIG.spreadsheetId);
  if (ss.getId() !== KS_DSA_CONFIG.spreadsheetId ||
      ss.getName() !== KS_DSA_CONFIG.expectedSpreadsheetName) {
    throw new Error('STOP: Target spreadsheet identity does not match the approved audit target.');
  }

  var dictSheet = ss.getSheetByName(KS_DSA_CONFIG.dictionarySheet);
  var registrySheet = ss.getSheetByName(KS_DSA_CONFIG.tableRegisterSheet);
  if (!dictSheet || !registrySheet) {
    throw new Error('STOP: Required schema register sheet is missing. No writes were performed.');
  }

  var dictValues = dictSheet.getDataRange().getDisplayValues();
  var registryValues = registrySheet.getDataRange().getDisplayValues();
  var relSheet = ss.getSheetByName(KS_DSA_CONFIG.relationshipSheet);
  var relValues = relSheet ? relSheet.getDataRange().getDisplayValues() : [];

  if (dictValues.length < 2 || registryValues.length < 2) {
    throw new Error('STOP: Schema registers have no usable data rows.');
  }

  var dh = KS_DSA_headerMap_(dictValues[0]);
  var requiredDictHeaders = ['table', 'field', 'data type'];
  requiredDictHeaders.forEach(function (h) {
    if (dh[h] === undefined) throw new Error('STOP: Field Dictionary is missing column: ' + h);
  });
  var rh = KS_DSA_headerMap_(registryValues[0]);
  if (rh['table'] === undefined) throw new Error('STOP: Table Registry is missing its Table column.');

  var tables = {};
  var duplicateFields = [];
  var malformedNames = [];
  var typeFlags = [];
  var noKeyTables = [];
  var dictionaryRows = 0;

  for (var i = 1; i < dictValues.length; i++) {
    var row = dictValues[i];
    var table = KS_DSA_text_(row[dh.table]);
    var field = KS_DSA_text_(row[dh.field]);
    var type = KS_DSA_text_(row[dh['data type']]).toUpperCase();
    if (!table || !field) continue;
    dictionaryRows++;
    if (!tables[table]) tables[table] = { fields: [], fieldMap: {}, types: {} };
    var key = field.toLowerCase();
    if (tables[table].fieldMap[key]) {
      duplicateFields.push({ table: table, field: field, row: i + 1 });
    }
    tables[table].fieldMap[key] = true;
    tables[table].fields.push(field);
    tables[table].types[key] = type;

    if (/k_p_i|policie|_id_id|__|[^a-z0-9_]/i.test(field)) {
      malformedNames.push({ table: table, field: field, row: i + 1 });
    }
    var isIdentifier = /(^id$|_id$|_key$|_code$|_sku$|_gstin$|_pan$|_phone$|_email$|_url$|_number$|_reference$)/i.test(field);
    var isAmount = /(amount|price|rate|cost|value|total|balance|debit|credit|quantity|qty|weight|hours|factor|percent|score)$/i.test(field);
    var isBoolean = /^(is_|has_|can_|allow_|active$|enabled$|approved$|closed$|verified$|required$|reconciled$)/i.test(field);
    var validTypes = ['TEXT', 'DECIMAL', 'NUMBER', 'INTEGER', 'BOOLEAN', 'DATE', 'DATETIME', 'JSON_TEXT'];
    if (type && validTypes.indexOf(type) === -1) {
      typeFlags.push({ table: table, field: field, type: type, reason: 'UNRECOGNISED_TYPE_TOKEN' });
    } else if (isIdentifier && (type === 'DECIMAL' || type === 'NUMBER' || type === 'INTEGER' || type === 'BOOLEAN' || type === 'DATE' || type === 'DATETIME')) {
      typeFlags.push({ table: table, field: field, type: type, reason: 'IDENTIFIER_LIKE_FIELD_NOT_TEXT_REVIEW' });
    } else if (isAmount && (type === 'TEXT' || type === 'BOOLEAN' || type === 'DATE' || type === 'DATETIME' || type === 'JSON_TEXT')) {
      typeFlags.push({ table: table, field: field, type: type, reason: 'NUMERIC_MEASURE_LIKE_FIELD_TYPE_REVIEW' });
    } else if (isBoolean && type && type !== 'BOOLEAN' && type !== 'TEXT') {
      typeFlags.push({ table: table, field: field, type: type, reason: 'BOOLEAN_LIKE_FIELD_TYPE_REVIEW' });
    }
  }

  var registryTables = [];
  for (var j = 1; j < registryValues.length; j++) {
    var t = KS_DSA_text_(registryValues[j][rh.table]);
    if (t) registryTables.push(t);
  }
  var registryOnly = registryTables.filter(function (t) { return !tables[t] && t !== 'START_HERE'; });
  var dictionaryOnly = Object.keys(tables).filter(function (t) { return registryTables.indexOf(t) === -1; });

  Object.keys(tables).forEach(function (t) {
    var hasId = tables[t].fields.some(function (f) { return /(^id$|_id$)/i.test(f); });
    if (!hasId && t !== 'START_HERE' && t !== 'Settings') noKeyTables.push(t);
  });

  var bundleDefinitions = [
    {
      name: 'GENERIC_EVENT_OR_LEDGER_BUNDLE',
      fields: ['reference_type', 'reference_id', 'record_date', 'description', 'quantity', 'unit', 'amount', 'owner_user_id']
    },
    {
      name: 'GENERIC_PARTY_CONTACT_BUNDLE',
      fields: ['code', 'name', 'category', 'contact_person', 'phone', 'email', 'address', 'active']
    },
    {
      name: 'GENERIC_PLACEHOLDER_BUNDLE',
      fields: ['record_id', 'created_at', 'created_by', 'updated_at', 'updated_by', 'status', 'notes']
    }
  ];
  var bundleFindings = [];
  bundleDefinitions.forEach(function (bundle) {
    var affected = [];
    Object.keys(tables).forEach(function (t) {
      var count = bundle.fields.filter(function (f) { return !!tables[t].fieldMap[f]; }).length;
      if (count >= Math.max(6, bundle.fields.length - 1)) {
        affected.push({ table: t, matchedBundleFields: count, totalBundleFields: bundle.fields.length });
      }
    });
    if (affected.length) bundleFindings.push({ bundle: bundle.name, affectedTableCount: affected.length, tables: affected });
  });

  var identicalSignatures = {};
  Object.keys(tables).forEach(function (t) {
    var signature = tables[t].fields.map(function (f) { return f.toLowerCase(); }).sort().join('|');
    if (!identicalSignatures[signature]) identicalSignatures[signature] = [];
    identicalSignatures[signature].push(t);
  });
  var repeatedSchemas = Object.keys(identicalSignatures).filter(function (sig) {
    return identicalSignatures[sig].length > 1;
  }).map(function (sig) {
    return { tableCount: identicalSignatures[sig].length, tables: identicalSignatures[sig], fieldCount: sig ? sig.split('|').length : 0 };
  });

  var relationshipFindings = [];
  if (relValues.length > 1) {
    var qh = KS_DSA_headerMap_(relValues[0]);
    var childTableCol = qh['child table'];
    var childFieldCol = qh['child field'];
    var parentTableCol = qh['parent table'];
    var parentFieldCol = qh['parent field'];
    if (childTableCol !== undefined && childFieldCol !== undefined && parentTableCol !== undefined && parentFieldCol !== undefined) {
      for (var k = 1; k < relValues.length; k++) {
        var cr = relValues[k];
        var ct = KS_DSA_text_(cr[childTableCol]);
        var cf = KS_DSA_text_(cr[childFieldCol]);
        var pt = KS_DSA_text_(cr[parentTableCol]);
        var pf = KS_DSA_text_(cr[parentFieldCol]);
        if (!ct && !cf && !pt && !pf) continue;
        if (!tables[ct] || !tables[ct].fieldMap[cf.toLowerCase()]) {
          relationshipFindings.push({ row: k + 1, issue: 'CHILD_TABLE_OR_FIELD_NOT_IN_DICTIONARY', childTable: ct, childField: cf });
        }
        if (!tables[pt] || !tables[pt].fieldMap[pf.toLowerCase()]) {
          relationshipFindings.push({ row: k + 1, issue: 'PARENT_TABLE_OR_FIELD_NOT_IN_DICTIONARY', parentTable: pt, parentField: pf });
        }
      }
    }
  }

  var summary = {
    auditName: 'KAWAD_SWAD_DICTIONARY_SEMANTIC_QUALITY_AUDIT',
    version: '1.0',
    spreadsheetName: ss.getName(),
    spreadsheetId: ss.getId(),
    dictionaryDataRowsRead: dictionaryRows,
    dictionaryTablesFound: Object.keys(tables).length,
    registryTablesFound: registryTables.length,
    duplicateFieldDefinitionsWithinTables: duplicateFields.length,
    malformedOrSuspiciousFieldNames: malformedNames.length,
    dataTypeReviewFlags: typeFlags.length,
    tablesWithoutIdLikeField: noKeyTables.length,
    registryTablesMissingDictionary: registryOnly.length,
    dictionaryTablesMissingRegistry: dictionaryOnly.length,
    repeatedGenericBundlesFound: bundleFindings.length,
    identicalFieldSetGroups: repeatedSchemas.length,
    relationshipDictionaryMismatches: relationshipFindings.length,
    transactionRowsRead: false,
    personalDataRead: false,
    authUsersRead: false,
    writesPerformed: false,
    interpretation: 'Heuristic design-quality flags only. Human review is required; this audit does not approve any field or schema change.'
  };
  Logger.log('KS_DSA_SUMMARY ' + JSON.stringify(summary));
  KS_DSA_logParts_('GENERIC_BUNDLE', bundleFindings);
  KS_DSA_logParts_('REPEATED_FIELD_SETS', repeatedSchemas);
  KS_DSA_logParts_('TYPE_REVIEW', typeFlags);
  KS_DSA_logParts_('SUSPICIOUS_FIELD_NAMES', malformedNames);
  KS_DSA_logParts_('DUPLICATE_FIELD_DEFINITIONS', duplicateFields);
  KS_DSA_logParts_('TABLES_WITHOUT_ID_LIKE_FIELD', noKeyTables);
  KS_DSA_logParts_('RELATIONSHIP_DICTIONARY_MISMATCH', relationshipFindings);
  KS_DSA_logParts_('TABLE_REGISTRY_MISMATCH', { registryOnly: registryOnly, dictionaryOnly: dictionaryOnly });
  Logger.log('KS_DSA_END ' + JSON.stringify({ spreadsheetId: ss.getId(), writesPerformed: false }));
}

function KS_DSA_headerMap_(headers) {
  var out = {};
  headers.forEach(function (h, i) {
    var key = KS_DSA_text_(h).toLowerCase();
    if (key) out[key] = i;
  });
  return out;
}

function KS_DSA_text_(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}

function KS_DSA_logParts_(label, data) {
  if (!data || (Array.isArray(data) && data.length === 0)) {
    Logger.log('KS_DSA_' + label + ' NONE');
    return;
  }
  var items = Array.isArray(data) ? data : [data];
  var part = [];
  var partNo = 1;
  var maxItems = KS_DSA_CONFIG.maxFindingsPerPart;
  for (var i = 0; i < items.length; i++) {
    part.push(items[i]);
    if (part.length >= maxItems || i === items.length - 1) {
      Logger.log('KS_DSA_' + label + '_PART ' + partNo + ' ' + JSON.stringify(part));
      part = [];
      partNo++;
    }
  }
}