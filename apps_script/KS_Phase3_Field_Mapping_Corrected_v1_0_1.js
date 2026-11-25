/**
 * KAWAD SWAD ERP - PHASE 3 WORKSTREAM 3
 * Canonical-to-physical field mapping
 * Corrected review version: 1.0.1
 *
 * RUN:
 *   ksP3BuildFieldMapping()
 * VERIFY:
 *   ksP3VerifyFieldMapping()
 * LOGGER CHECK:
 *   ksP3CheckMigrationLoggerAlignment()
 *
 * SAFETY:
 * - Exact workbook ID and name-prefix checks.
 * - Reads governance registers only, not business row values.
 * - Writes only KS_P3_FIELD_MAPPING and appends to KS_P3_MIGRATION_LOG.
 * - Preserves manual approval_status and review_notes by table + field key.
 * - Does not alter business tabs, headers, records, formulas, IDs or types.
 * - No-exact-match is review-only, never auto-approved as an alias.
 */

const KS_P3_FIELD_CFG = Object.freeze({
  spreadsheetId: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  expectedNamePrefix: 'Kawad_Swad_Sales_Management_Google_Sheets',
  dictionaryTab: 'DBV5_FIELD_DICTIONARY_3074',
  priorFieldReviewTab: 'KS_FIELD_MAPPING',
  inventoryTab: 'KS_P3_LIVE_INVENTORY',
  tableMappingTab: 'KS_P3_TABLE_MAPPING',
  outputTab: 'KS_P3_FIELD_MAPPING',
  migrationLogTab: 'KS_P3_MIGRATION_LOG',
  expectedDictionaryRows: 3074,
  version: '1.0.1'
});

function ksP3BuildFieldMapping() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    ksP3FieldAssertTarget_(ss);

    const dict = ksP3FieldRead_(ss, KS_P3_FIELD_CFG.dictionaryTab);
    const prior = ksP3FieldRead_(ss, KS_P3_FIELD_CFG.priorFieldReviewTab);
    const inv = ksP3FieldRead_(ss, KS_P3_FIELD_CFG.inventoryTab);
    const tableMap = ksP3FieldRead_(ss, KS_P3_FIELD_CFG.tableMappingTab);

    if (dict.length < 2 || prior.length < 2 || inv.length < 2 || tableMap.length < 2) {
      throw new Error('STOP: one or more required governance registers are empty. No output written.');
    }

    const dh = dict[0].map(ksP3FieldNorm_);
    const ph = prior[0].map(ksP3FieldNorm_);
    const ih = inv[0].map(ksP3FieldNorm_);
    const th = tableMap[0].map(ksP3FieldNorm_);
    const col = (h, n) => h.indexOf(ksP3FieldNorm_(n));
    const need = (h, names, label) => names.forEach(n => {
      if (col(h, n) < 0) throw new Error('STOP: missing ' + label + ' column: ' + n);
    });

    need(dh, ['table','position','field','data type','required rule','uniqueness',
      'relationship note','plain-language meaning','schema source','confidence',
      'execution eligibility'], 'dictionary');
    need(ph, ['canonical table','canonical field','recommended type','mapping status',
      'observed live headers','recommended action','review finding'], 'prior field review');
    need(ih, ['sheet_name','physical_headers','header_sha256','data_rows_approx'], 'live inventory');
    need(th, ['live_tab_name','mapping_class','approval_status'], 'table mapping');

    if (dict.length - 1 !== KS_P3_FIELD_CFG.expectedDictionaryRows) {
      throw new Error('STOP: expected ' + KS_P3_FIELD_CFG.expectedDictionaryRows +
        ' dictionary rows; found ' + (dict.length - 1) + '. No output written.');
    }

    const live = new Map();
    inv.slice(1).forEach(r => {
      const name = String(r[col(ih,'sheet_name')] || '').trim();
      if (!name) return;
      if (live.has(name)) throw new Error('STOP: duplicate live inventory tab: ' + name);
      const raw = String(r[col(ih,'physical_headers')] || '');
      const headers = raw.split('|').map(x => String(x).trim()).filter(Boolean);
      live.set(name, {
        headers,
        headerSet: new Set(headers.map(ksP3FieldNorm_)),
        hash: r[col(ih,'header_sha256')] || '',
        rows: r[col(ih,'data_rows_approx')] || 0
      });
    });

    const priorMap = new Map();
    prior.slice(1).forEach(r => {
      const t = String(r[col(ph,'canonical table')] || '').trim();
      const f = String(r[col(ph,'canonical field')] || '').trim();
      if (t && f) priorMap.set(t + '\u001f' + f, r);
    });

    const tableMeta = new Map();
    tableMap.slice(1).forEach(r => {
      const t = String(r[col(th,'live_tab_name')] || '').trim();
      if (t) tableMeta.set(t, r);
    });

    const headers = [
      'canonical_table','position','canonical_field','dictionary_type','required_rule',
      'uniqueness_rule','relationship_note','plain_language_meaning','schema_source',
      'confidence','execution_eligibility','physical_tab_exists','physical_header_match',
      'mapping_status','prior_mapping_status','prior_recommended_type','prior_review_finding',
      'live_headers_snapshot','live_header_sha256','approx_data_rows','table_mapping_class',
      'table_approval_status','proposed_action','approval_status','review_notes'
    ];

    // Preserve only genuinely manual columns. Derived fields are recalculated.
    const priorManual = ksP3FieldReadManual_(ss, headers);
    const out = [];
    const counts = {};

    dict.slice(1).forEach(r => {
      const table = String(r[col(dh,'table')] || '').trim();
      const field = String(r[col(dh,'field')] || '').trim();
      if (!table || !field) return;

      const liveInfo = live.get(table);
      const priorRow = priorMap.get(table + '\u001f' + field);
      const tableRow = tableMeta.get(table);
      const exact = !!(liveInfo && liveInfo.headerSet.has(ksP3FieldNorm_(field)));
      const priorStatus = priorRow ? priorRow[col(ph,'mapping status')] : '';
      const priorType = priorRow ? priorRow[col(ph,'recommended type')] : '';
      const priorFinding = priorRow ? priorRow[col(ph,'review finding')] : '';

      let status;
      if (!liveInfo) status = 'MISSING_PHYSICAL_TABLE';
      else if (exact) status = 'EXACT_MATCH';
      else if (priorStatus === 'NO_EXACT_HEADER_MATCH') status = 'ALIAS_OR_MISSING_REVIEW';
      else status = 'MISSING_FIELD_REVIEW';

      // This is a proposed-type conflict only, not proof of physical cell type.
      const dictionaryType = r[col(dh,'data type')] || '';
      const typeReview = priorType && dictionaryType &&
        ksP3FieldNorm_(priorType) !== ksP3FieldNorm_(dictionaryType);

      const tableClass = tableRow ? tableRow[col(th,'mapping_class')] : 'TABLE_NOT_IN_MAPPING';
      const tableApproval = tableRow ? tableRow[col(th,'approval_status')] : 'PENDING';

      let action = exact ? 'PRESERVE_EXISTING_HEADER' : 'REVIEW_ALIAS_OR_MISSING_FIELD';
      if (typeReview) action = 'REVIEW_TYPE_DIFFERENCE; DO_NOT_CONVERT';
      if (String(r[col(dh,'execution eligibility')] || '').toUpperCase().indexOf('NOT APPROVED') >= 0) {
        action += '; NOT APPROVED FOR EXECUTION';
      }

      const notes = !liveInfo
        ? 'No physical tab found in Phase 3 inventory.'
        : exact
          ? 'Exact header name exists. Header presence does not confirm cell-value validity or stored data type.'
          : 'No exact physical header match. Could be alias, absent field, or proposed-only field; inspect routes and owner workflow.';

      const key = table + '\u001f' + field;
      const manual = priorManual.get(key) || {};
      const row = [
        table, r[col(dh,'position')], field, dictionaryType, r[col(dh,'required rule')],
        r[col(dh,'uniqueness')], r[col(dh,'relationship note')], r[col(dh,'plain-language meaning')],
        r[col(dh,'schema source')], r[col(dh,'confidence')], r[col(dh,'execution eligibility')],
        liveInfo ? 'YES' : 'NO', exact ? 'YES' : 'NO', status, priorStatus || '', priorType || '',
        priorFinding || '', liveInfo ? liveInfo.headers.join(' | ') : '',
        liveInfo ? liveInfo.hash : '', liveInfo ? liveInfo.rows : '',
        tableClass, tableApproval, action,
        manual.approval_status || 'PENDING OWNER + TECHNICAL APPROVAL',
        manual.review_notes || notes
      ];
      out.push(row);
      counts[status] = (counts[status] || 0) + 1;
    });

    if (out.length !== KS_P3_FIELD_CFG.expectedDictionaryRows) {
      throw new Error('STOP: expected ' + KS_P3_FIELD_CFG.expectedDictionaryRows +
        ' usable field rows; built ' + out.length + '. No output written.');
    }

    const sh = ksP3FieldGetOwnedTab_(ss, KS_P3_FIELD_CFG.outputTab, headers);
    // Only the owned report tab is refreshed. Manual approval and notes are
    // carried forward above, keyed by canonical_table + canonical_field.
    sh.clearContents();
    sh.getRange(1, 1, 1, headers.length).setValues([headers]);
    sh.getRange(2, 1, out.length, headers.length).setValues(out);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    const filter = sh.getFilter();
    if (filter) filter.remove();
    sh.getRange(1, 1, out.length + 1, headers.length).createFilter();

    const details = {
      dictionaryRows: out.length,
      statusCounts: counts,
      preservedManualDecisionRows: priorManual.size,
      physicalValueScan: false,
      businessSchemaChanged: false,
      note: 'Header-level mapping only; no business values or schema changed.'
    };
    ksP3FieldAppendLog_(ss, 'BUILD_FIELD_MAPPING', details);
    const result = {success:true, version:KS_P3_FIELD_CFG.version,
      outputTab:KS_P3_FIELD_CFG.outputTab, ...details};
    Logger.log(JSON.stringify(result, null, 2));
    return result;
  } finally {
    lock.releaseLock();
  }
}

function ksP3FieldReadManual_(ss, expectedHeaders) {
  const sh = ss.getSheetByName(KS_P3_FIELD_CFG.outputTab);
  const result = new Map();
  if (!sh || sh.getLastRow() < 2 || sh.getLastColumn() < 1) return result;
  const actual = sh.getRange(1, 1, 1, sh.getLastColumn()).getDisplayValues()[0]
    .map(ksP3FieldNorm_);
  const tableCol = actual.indexOf('canonical_table');
  const fieldCol = actual.indexOf('canonical_field');
  const approvalCol = actual.indexOf('approval_status');
  const notesCol = actual.indexOf('review_notes');
  if ([tableCol, fieldCol, approvalCol, notesCol].some(i => i < 0)) return result;
  const data = sh.getRange(2, 1, sh.getLastRow() - 1, sh.getLastColumn()).getValues();
  data.forEach(r => {
    const t = String(r[tableCol] || '').trim();
    const f = String(r[fieldCol] || '').trim();
    if (!t || !f) return;
    result.set(t + '\u001f' + f, {
      approval_status: r[approvalCol],
      review_notes: r[notesCol]
    });
  });
  return result;
}

function ksP3VerifyFieldMapping() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ksP3FieldAssertTarget_(ss);
  const sh = ss.getSheetByName(KS_P3_FIELD_CFG.outputTab);
  if (!sh) throw new Error('Field mapping report not found.');
  const vals = sh.getDataRange().getValues();
  if (!vals.length) throw new Error('Field mapping report is empty.');
  const h = vals[0].map(ksP3FieldNorm_);
  const j = h.indexOf('mapping_status');
  if (j < 0) throw new Error('mapping_status column missing.');
  const counts = {};
  vals.slice(1).forEach(r => {
    const k = r[j] || 'UNCLASSIFIED';
    counts[k] = (counts[k] || 0) + 1;
  });
  return {
    success: vals.length === KS_P3_FIELD_CFG.expectedDictionaryRows + 1,
    tab: sh.getName(),
    fieldRows: vals.length - 1,
    columns: sh.getLastColumn(),
    statusCounts: counts,
    businessSchemaChanged: false
  };
}

/**
 * This checks the logger header and appends a test/audit event.
 * It does not repair or rewrite historical malformed log rows.
 */
function ksP3CheckMigrationLoggerAlignment() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ksP3FieldAssertTarget_(ss);
  const result = {
    success: true,
    logger: KS_P3_FIELD_CFG.migrationLogTab,
    existingRowsPreserved: true,
    historicalRowsRewritten: false,
    note: 'Header alignment checked; this function does not repair historical rows.'
  };
  ksP3FieldAppendLog_(ss, 'MIGRATION_LOGGER_ALIGNMENT_CHECK', result);
  Logger.log(JSON.stringify(result, null, 2));
  return result;
}

// Backward-compatible name. Despite the old name, this only checks alignment.
function ksP3RepairMigrationLogger() {
  return ksP3CheckMigrationLoggerAlignment();
}

function ksP3FieldAppendLog_(ss, event, details) {
  const sh = ss.getSheetByName(KS_P3_FIELD_CFG.migrationLogTab);
  if (!sh) throw new Error('Migration log missing.');
  const expected = ['timestamp','version','event','spreadsheet_id','spreadsheet_name',
    'backup_url','live_tab_count','inventory_rows','business_schema_changed','details'];
  if (sh.getLastColumn() !== expected.length) {
    throw new Error('STOP: migration log must have exactly 10 columns.');
  }
  const actual = sh.getRange(1, 1, 1, sh.getLastColumn()).getDisplayValues()[0]
    .map(ksP3FieldNorm_);
  if (actual.join('|') !== expected.join('|')) {
    throw new Error('STOP: migration log headers do not match expected 10-column schema.');
  }
  const inv = ss.getSheetByName(KS_P3_FIELD_CFG.inventoryTab);
  const invRows = inv ? Math.max(0, inv.getLastRow() - 1) : 0;
  sh.appendRow([new Date(), KS_P3_FIELD_CFG.version, event, ss.getId(), ss.getName(),
    '', ss.getSheets().length, invRows, 'NO', JSON.stringify(details)]);
}

function ksP3FieldAssertTarget_(ss) {
  if (!ss || ss.getId() !== KS_P3_FIELD_CFG.spreadsheetId ||
      !ss.getName().startsWith(KS_P3_FIELD_CFG.expectedNamePrefix)) {
    throw new Error('STOP: wrong spreadsheet. No changes made.');
  }
}

function ksP3FieldRead_(ss, name) {
  const sh = ss.getSheetByName(name);
  if (!sh) throw new Error('Required governance tab missing: ' + name);
  return sh.getDataRange().getValues();
}

function ksP3FieldNorm_(v) {
  return String(v == null ? '' : v).trim().toLowerCase();
}

function ksP3FieldGetOwnedTab_(ss, name, headers) {
  let sh = ss.getSheetByName(name);
  if (!sh) return ss.insertSheet(name);
  if (sh.getLastRow() === 0 || sh.getLastColumn() === 0) return sh;
  const actual = sh.getRange(1, 1, 1, sh.getLastColumn())
    .getDisplayValues()[0].map(v => String(v || '').trim());
  if (actual.join('\u001f') !== headers.map(String).join('\u001f')) {
    throw new Error('STOP: ' + name + ' exists with unexpected headers. No write performed.');
  }
  return sh;
}
