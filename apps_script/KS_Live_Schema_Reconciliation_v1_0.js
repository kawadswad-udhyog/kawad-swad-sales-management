/**
 * KAWAD SWAD - LIVE SCHEMA RECONCILIATION (READ ONLY)
 * Version: 1.0
 *
 * PURPOSE
 * Compare the physical header row of each registered canonical worksheet
 * against KS_P1_FIELD_DICTIONARY, using KS_P1_TABLE_REGISTRY as the table list.
 * Detect exact matches, missing dictionary fields, additional physical headers,
 * duplicate headers, and the known generic placeholder header pattern.
 *
 * READ-ONLY GUARANTEE
 * - Reads only the table register, field dictionary, worksheet names and row-1 headers.
 * - Does not read business transaction rows, employee/customer/supplier personal data,
 *   authentication data, or cell values below the header row.
 * - Does not create, rename, clear, format, or modify any worksheet or cell.
 * - Does not allocate IDs or write audit results into the workbook.
 * - Writes diagnostic output only to the Apps Script execution log.
 *
 * RUN
 * Select and run: KS_RUN_LIVE_SCHEMA_RECONCILIATION
 */

const KS_SCHEMA_RECON_V1 = {
  TABLE_REGISTER_TAB: 'KS_P1_TABLE_REGISTRY',
  FIELD_DICTIONARY_TAB: 'KS_P1_FIELD_DICTIONARY',
  MAX_LOG_CHARS: 8500,
  SPECIAL_NON_TABLES: ['START_HERE'],
  GENERIC_PLACEHOLDER_HEADERS: [
    ['record_id', 'created_at', 'created_by', 'updated_at', 'updated_by', 'status', 'notes']
  ]
};

function KS_RUN_LIVE_SCHEMA_RECONCILIATION() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('No active spreadsheet is available. Open this script from the target spreadsheet.');

  const registerSheet = ss.getSheetByName(KS_SCHEMA_RECON_V1.TABLE_REGISTER_TAB);
  const dictionarySheet = ss.getSheetByName(KS_SCHEMA_RECON_V1.FIELD_DICTIONARY_TAB);
  if (!registerSheet) throw new Error('Required register tab not found: ' + KS_SCHEMA_RECON_V1.TABLE_REGISTER_TAB);
  if (!dictionarySheet) throw new Error('Required field dictionary tab not found: ' + KS_SCHEMA_RECON_V1.FIELD_DICTIONARY_TAB);

  // These two tabs contain schema metadata, not transaction records.
  const registerValues = registerSheet.getDataRange().getDisplayValues();
  const dictionaryValues = dictionarySheet.getDataRange().getDisplayValues();
  if (registerValues.length < 2) throw new Error('Table register has no table rows.');
  if (dictionaryValues.length < 2) throw new Error('Field dictionary has no field rows.');

  const registerHeader = KS_schemaHeaderMap_(registerValues[0]);
  const dictionaryHeader = KS_schemaHeaderMap_(dictionaryValues[0]);
  const requiredRegisterColumns = ['table'];
  const requiredDictionaryColumns = ['table', 'field'];
  KS_schemaRequireColumns_(registerHeader, requiredRegisterColumns, KS_SCHEMA_RECON_V1.TABLE_REGISTER_TAB);
  KS_schemaRequireColumns_(dictionaryHeader, requiredDictionaryColumns, KS_SCHEMA_RECON_V1.FIELD_DICTIONARY_TAB);

  const tables = [];
  const seenTables = new Set();
  const duplicateTableRegisterRows = [];
  for (let r = 1; r < registerValues.length; r++) {
    const tableName = String(registerValues[r][registerHeader.table] || '').trim();
    if (!tableName) continue;
    const key = KS_schemaNorm_(tableName);
    if (seenTables.has(key)) {
      duplicateTableRegisterRows.push({ row: r + 1, table: tableName });
      continue;
    }
    seenTables.add(key);
    tables.push({
      table: tableName,
      priority: KS_schemaValue_(registerValues[r], registerHeader, 'priority'),
      group: KS_schemaValue_(registerValues[r], registerHeader, 'group'),
      purpose: KS_schemaValue_(registerValues[r], registerHeader, 'purpose / record grain')
    });
  }

  const fieldsByTable = new Map();
  let dictionaryFieldRows = 0;
  const duplicateDictionaryFields = [];
  const seenFieldKeys = new Set();
  for (let r = 1; r < dictionaryValues.length; r++) {
    const tableName = String(dictionaryValues[r][dictionaryHeader.table] || '').trim();
    const fieldName = String(dictionaryValues[r][dictionaryHeader.field] || '').trim();
    if (!tableName || !fieldName) continue;
    dictionaryFieldRows++;
    const tableKey = KS_schemaNorm_(tableName);
    const fieldKey = KS_schemaNorm_(fieldName);
    const combined = tableKey + '::' + fieldKey;
    if (seenFieldKeys.has(combined)) duplicateDictionaryFields.push({ row: r + 1, table: tableName, field: fieldName });
    seenFieldKeys.add(combined);
    if (!fieldsByTable.has(tableKey)) fieldsByTable.set(tableKey, []);
    fieldsByTable.get(tableKey).push(fieldName);
  }

  const results = [];
  let specialSkipped = 0;
  let missingPhysicalTabs = 0;
  let genericPlaceholders = 0;
  let exactMatches = 0;
  let missingFieldTables = 0;
  let extraHeaderTables = 0;
  let duplicateHeaderTables = 0;
  let noDictionaryTables = 0;
  let expectedFieldCount = 0;
  let matchedFieldCount = 0;
  let missingFieldCount = 0;
  let extraHeaderCount = 0;
  let blankPhysicalHeaderCells = 0;

  for (const tableInfo of tables) {
    const tableName = tableInfo.table;
    const tableKey = KS_schemaNorm_(tableName);
    const expectedFields = fieldsByTable.get(tableKey) || [];
    expectedFieldCount += expectedFields.length;

    if (KS_SCHEMA_RECON_V1.SPECIAL_NON_TABLES.map(KS_schemaNorm_).indexOf(tableKey) >= 0) {
      specialSkipped++;
      results.push({
        table: tableName,
        priority: tableInfo.priority,
        status: 'SPECIAL_CONTROL_NOT_A_NORMALISED_TABLE',
        expectedFieldCount: expectedFields.length,
        matchedFieldCount: 0,
        missingFields: [],
        extraPhysicalHeaders: [],
        duplicateHeaders: [],
        note: 'START_HERE is an instruction page, not a database table; header comparison is intentionally skipped.'
      });
      continue;
    }

    const sh = ss.getSheetByName(tableName);
    if (!sh) {
      missingPhysicalTabs++;
      missingFieldCount += expectedFields.length;
      results.push({
        table: tableName,
        priority: tableInfo.priority,
        status: 'MISSING_PHYSICAL_TAB',
        expectedFieldCount: expectedFields.length,
        matchedFieldCount: 0,
        missingFields: expectedFields,
        extraPhysicalHeaders: [],
        duplicateHeaders: [],
        note: 'No worksheet with this exact name exists.'
      });
      continue;
    }

    if (expectedFields.length === 0) noDictionaryTables++;

    const lastCol = sh.getLastColumn();
    const headerCells = lastCol > 0 ? sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0] : [];
    const blankHeaderColumns = [];
    headerCells.forEach((value, index) => { if (!String(value || '').trim()) blankHeaderColumns.push(index + 1); });
    blankPhysicalHeaderCells += blankHeaderColumns.length;
    const physicalHeaders = headerCells.map(v => String(v || '').trim()).filter(Boolean);
    const normalizedPhysical = physicalHeaders.map(KS_schemaNorm_);
    const physicalSet = new Set(normalizedPhysical);

    const duplicateHeaders = [];
    const headerSeen = new Set();
    for (const header of physicalHeaders) {
      const key = KS_schemaNorm_(header);
      if (headerSeen.has(key) && duplicateHeaders.indexOf(header) < 0) duplicateHeaders.push(header);
      headerSeen.add(key);
    }

    const expectedSet = new Set(expectedFields.map(KS_schemaNorm_));
    const missingFields = expectedFields.filter(f => !physicalSet.has(KS_schemaNorm_(f)));
    const extraPhysicalHeaders = physicalHeaders.filter(h => !expectedSet.has(KS_schemaNorm_(h)));
    const matched = expectedFields.length - missingFields.length;
    matchedFieldCount += matched;
    missingFieldCount += missingFields.length;
    extraHeaderCount += extraPhysicalHeaders.length;

    const genericSignature = KS_schemaIsGenericPlaceholder_(physicalHeaders);
    let status;
    if (genericSignature) {
      status = 'GENERIC_PLACEHOLDER_HEADER';
      genericPlaceholders++;
    } else if (duplicateHeaders.length) {
      status = 'DUPLICATE_PHYSICAL_HEADERS_REVIEW';
      duplicateHeaderTables++;
    } else if (missingFields.length && extraPhysicalHeaders.length) {
      status = 'MISSING_FIELDS_AND_EXTRA_HEADERS_REVIEW';
      missingFieldTables++;
      extraHeaderTables++;
    } else if (missingFields.length) {
      status = 'MISSING_DICTIONARY_FIELDS_REVIEW';
      missingFieldTables++;
    } else if (extraPhysicalHeaders.length) {
      status = 'EXTRA_PHYSICAL_HEADERS_REVIEW';
      extraHeaderTables++;
    } else if (expectedFields.length === 0) {
      status = 'NO_DICTIONARY_DEFINITION';
    } else {
      status = 'EXACT_HEADER_SET_MATCH';
      exactMatches++;
    }

    results.push({
      table: tableName,
      priority: tableInfo.priority,
      status: status,
      physicalHeaderCount: physicalHeaders.length,
      blankHeaderColumns: blankHeaderColumns,
      expectedFieldCount: expectedFields.length,
      matchedFieldCount: matched,
      missingFields: missingFields,
      extraPhysicalHeaders: extraPhysicalHeaders,
      duplicateHeaders: duplicateHeaders,
      note: 'Header-set comparison only. Does not verify stored values, types, formulas, route usage, or accounting behaviour.'
    });
  }

  const summary = {
    auditName: 'KAWAD_SWAD_LIVE_SCHEMA_RECONCILIATION',
    version: '1.0',
    spreadsheetName: ss.getName(),
    spreadsheetId: ss.getId(),
    physicalSheetCount: ss.getSheets().length,
    registeredTableCount: tables.length,
    dictionaryFieldRows: dictionaryFieldRows,
    expectedFieldCountAcrossRegisteredTables: expectedFieldCount,
    matchedFieldCount: matchedFieldCount,
    missingFieldCount: missingFieldCount,
    extraPhysicalHeaderCount: extraHeaderCount,
    blankPhysicalHeaderCells: blankPhysicalHeaderCells,
    exactHeaderSetMatches: exactMatches,
    genericPlaceholderTables: genericPlaceholders,
    tablesWithMissingFields: missingFieldTables,
    tablesWithExtraHeaders: extraHeaderTables,
    tablesWithDuplicateHeaders: duplicateHeaderTables,
    missingPhysicalTabs: missingPhysicalTabs,
    tablesWithoutDictionaryDefinition: noDictionaryTables,
    specialPagesSkipped: specialSkipped,
    duplicateTableRegisterRows: duplicateTableRegisterRows.length,
    duplicateDictionaryFieldDefinitions: duplicateDictionaryFields.length,
    transactionRowsRead: false,
    personalDataRead: false,
    writesPerformed: false
  };

  Logger.log('KS_SCHEMA_RECON_START ' + JSON.stringify(summary));
  if (duplicateTableRegisterRows.length) Logger.log('KS_SCHEMA_RECON_DUPLICATE_TABLES ' + JSON.stringify(duplicateTableRegisterRows));
  if (duplicateDictionaryFields.length) Logger.log('KS_SCHEMA_RECON_DUPLICATE_FIELDS ' + JSON.stringify(duplicateDictionaryFields));

  // Chunk by serialized size so unusually wide tables do not create oversized log entries.
  const chunks = [];
  let currentChunk = [];
  let currentLength = 2;
  for (const item of results) {
    const itemText = JSON.stringify(item);
    const addedLength = itemText.length + (currentChunk.length ? 1 : 0);
    if (currentChunk.length && currentLength + addedLength > KS_SCHEMA_RECON_V1.MAX_LOG_CHARS) {
      chunks.push(currentChunk);
      currentChunk = [];
      currentLength = 2;
    }
    currentChunk.push(item);
    currentLength += itemText.length + (currentChunk.length > 1 ? 1 : 0);
  }
  if (currentChunk.length) chunks.push(currentChunk);
  for (let i = 0; i < chunks.length; i++) {
    Logger.log('KS_SCHEMA_RECON_PART ' + (i + 1) + '/' + chunks.length + ' ' + JSON.stringify(chunks[i]));
  }
  Logger.log('KS_SCHEMA_RECON_END ' + JSON.stringify({ spreadsheetId: ss.getId(), registeredTableCount: tables.length, writesPerformed: false }));
}

function KS_schemaHeaderMap_(headers) {
  const map = {};
  headers.forEach((value, index) => {
    const key = KS_schemaNorm_(value);
    if (key && map[key] === undefined) map[key] = index;
  });
  return map;
}

function KS_schemaRequireColumns_(map, required, tabName) {
  const missing = required.filter(name => map[name] === undefined);
  if (missing.length) throw new Error('Missing required columns in ' + tabName + ': ' + missing.join(', '));
}

function KS_schemaValue_(row, headerMap, name) {
  const index = headerMap[KS_schemaNorm_(name)];
  return index === undefined ? '' : String(row[index] || '').trim();
}

function KS_schemaNorm_(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/^\uFEFF/, '')
    .trim()
    .toLowerCase();
}

function KS_schemaIsGenericPlaceholder_(headers) {
  const actual = headers.map(KS_schemaNorm_).sort();
  return KS_SCHEMA_RECON_V1.GENERIC_PLACEHOLDER_HEADERS.some(signature => {
    const expected = signature.map(KS_schemaNorm_).sort();
    return actual.length === expected.length && actual.every((value, index) => value === expected[index]);
  });
}
