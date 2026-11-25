/**
 * KAWAD SWAD ERP - DICTIONARY-DRIVEN SCHEMA HYDRATOR
 * Blueprint Version: 2.0 | Enforces Section 3.3, Section 11.2, Section 15.2, POL-018
 * Reads DBV5_FIELD_DICTIONARY_3074 using verified exact headers:
 * ["Table","Position","Field","Data type","Required rule","Uniqueness",
 *  "Relationship note","Plain-language meaning","Schema source","Confidence","Execution eligibility"]
 */

const KS_DICTIONARY_TAB = 'DBV5_FIELD_DICTIONARY_3074';

/**
 * Loads and indexes DBV5_FIELD_DICTIONARY_3074 by exact Table, Position, and Field headers.
 */
function ksLoadDictionaryIndex_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dictSheet = ss.getSheetByName(KS_DICTIONARY_TAB);
  if (!dictSheet) {
    throw new Error('Dictionary tab "' + KS_DICTIONARY_TAB + '" not found in workbook.');
  }

  const requiredDictCols = ['Table', 'Position', 'Field'];
  const { headerMap } = ksGetHeaderMap_(dictSheet, requiredDictCols);
  const lastRow = dictSheet.getLastRow();
  const lastCol = dictSheet.getLastColumn();
  if (lastRow < 2) return { tableCount: 0, byTable: {} };

  const idxTable = headerMap['Table'] - 1;
  const idxPos   = headerMap['Position'] - 1;
  const idxField = headerMap['Field'] - 1;
  const idxElig  = headerMap['Execution eligibility'] ? headerMap['Execution eligibility'] - 1 : -1;

  const rows = dictSheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
  const byTable = {};

  rows.forEach((r, idx) => {
    const tName = String(r[idxTable] || '').trim();
    const fName = String(r[idxField] || '').trim();
    if (!tName || !fName) return;

    const orderVal = Number(r[idxPos]) || (idx + 1);
    const eligVal  = idxElig >= 0 ? String(r[idxElig] || '').trim() : '';

    if (!byTable[tName]) byTable[tName] = [];
    byTable[tName].push({
      field: fName,
      order: orderVal,
      eligibility: eligVal
    });
  });

  // Sort each table's fields by Position and deduplicate
  Object.keys(byTable).forEach(tName => {
    byTable[tName].sort((a, b) => a.order - b.order);
    const seen = new Set();
    byTable[tName] = byTable[tName]
      .filter(item => {
        if (seen.has(item.field)) return false;
        seen.add(item.field);
        return true;
      });
  });

  return {
    tableCount: Object.keys(byTable).length,
    byTable: byTable
  };
}

/**
 * Read-only preview: compares current physical headers of a table group against
 * DBV5_FIELD_DICTIONARY_3074 so we can see exact columns to add before touching any sheet.
 */
function ksPreviewDictionaryDiff(groupName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tables = KS_CORE_TABLES[groupName];
  if (!tables) throw new Error('Unknown group: ' + groupName);

  const dict = ksLoadDictionaryIndex_();
  Logger.log('=== DICTIONARY DIFF PREVIEW: ' + groupName + ' (Dictionary tables=' + dict.tableCount + ') ===');

  tables.forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) {
      Logger.log('[MISSING TAB] ' + tabName);
      return;
    }
    const lastCol = sh.getLastColumn();
    const currentHeaders = lastCol > 0 ? sh.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim()) : [];
    const expectedItems = dict.byTable[tabName] || [];
    const missing = expectedItems
      .map(item => item.field)
      .filter(h => !currentHeaders.includes(h));

    Logger.log(
      tabName + ' | physical=' + currentHeaders.length +
      ' | dict=' + expectedItems.length +
      ' | to_add=' + missing.length +
      ' -> ' + JSON.stringify(missing)
    );
  });
}

function ksPreviewInventoryDictDiff()  { ksPreviewDictionaryDiff('INVENTORY'); }
function ksPreviewProductionDictDiff() { ksPreviewDictionaryDiff('PRODUCTION'); }
function ksPreviewSalesDictDiff()      { ksPreviewDictionaryDiff('SALES'); }
function ksPreviewAccountingDictDiff() { ksPreviewDictionaryDiff('ACCOUNTING'); }
function ksPreviewMasterDictDiff()     { ksPreviewDictionaryDiff('MASTER'); }

/**
 * Hydrates missing dictionary columns onto existing tables in a DISPOSABLE TEST COPY
 * by appending missing headers to the right of existing headers (never deletes/overwrites).
 * Requires OWNER_ADMIN role and logs every schema expansion to AuditLog (POL-018).
 */
function ksHydrateTableGroupFromDictionary(groupName) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksHydrateTableGroupFromDictionary:' + groupName);
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tables = KS_CORE_TABLES[groupName];
  if (!tables) throw new Error('Unknown group: ' + groupName);

  const dict = ksLoadDictionaryIndex_();
  let hydratedCount = 0;

  tables.forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) return;

    const lastCol = sh.getLastColumn();
    const currentHeaders = lastCol > 0 ? sh.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim()) : [];
    const expectedItems = dict.byTable[tabName] || [];
    const missing = expectedItems
      .map(item => item.field)
      .filter(h => !currentHeaders.includes(h));

    if (missing.length > 0) {
      sh.getRange(1, lastCol + 1, 1, missing.length).setValues([missing]);
      sh.setFrozenRows(1);
      hydratedCount++;

      ksLogAudit_('SCHEMA_HYDRATE', tabName, tabName, {
        actor_user_id: ctx.user_id,
        field_changed: 'headers',
        old_value: currentHeaders.length + ' cols',
        new_value: (currentHeaders.length + missing.length) + ' cols',
        reason: 'Hydrated ' + missing.length + ' dictionary fields from ' + KS_DICTIONARY_TAB
      });
    }
  });

  SpreadsheetApp.flush();
  Logger.log('Hydrated ' + hydratedCount + ' tables in group "' + groupName + '".');
  return hydratedCount;
}

function ksHydrateInventoryTables()  { return ksHydrateTableGroupFromDictionary('INVENTORY'); }
function ksHydrateProductionTables() { return ksHydrateTableGroupFromDictionary('PRODUCTION'); }
function ksHydrateSalesTables()      { return ksHydrateTableGroupFromDictionary('SALES'); }
function ksHydrateAccountingTables() { return ksHydrateTableGroupFromDictionary('ACCOUNTING'); }
function ksHydrateMasterTables()     { return ksHydrateTableGroupFromDictionary('MASTER'); }

/**
 * Hydrates ALL 5 core operational/accounting groups in one controlled run
 * in the disposable test copy.
 */
function ksHydrateAllCoreGroups() {
  const groups = ['MASTER', 'INVENTORY', 'PRODUCTION', 'SALES', 'ACCOUNTING'];
  const summary = {};
  groups.forEach(g => {
    summary[g] = ksHydrateTableGroupFromDictionary(g);
  });
  Logger.log('Full Core Schema Hydration Complete: ' + JSON.stringify(summary));
}