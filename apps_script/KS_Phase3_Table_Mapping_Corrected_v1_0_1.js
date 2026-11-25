/**
 * KAWAD SWAD ERP - PHASE 3 WORKSTREAM 2
 * Canonical-to-physical table mapping register
 * Corrected version: 1.0.1
 *
 * RUN:
 *   ksP3BuildTableMapping()
 * VERIFY:
 *   ksP3VerifyTableMapping()
 *
 * SAFETY:
 * - Exact target workbook ID and name-prefix checks.
 * - Reads governance registers and structural inventory only.
 * - Does not read business row values.
 * - Writes only KS_P3_TABLE_MAPPING and KS_P3_MIGRATION_LOG.
 * - Preserves all manual decision columns on reruns by matching live_tab_name.
 * - Adds canonical tables missing from live inventory as CANONICAL_MISSING rows.
 * - Does not create, rename, delete, clear, or restructure business tabs.
 * - Does not approve, merge, retire, or migrate any business table.
 */

const KS_P3_MAP_CFG = Object.freeze({
  spreadsheetId: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  expectedNamePrefix: 'Kawad_Swad_Sales_Management_Google_Sheets',
  inventoryTab: 'KS_P3_LIVE_INVENTORY',
  registryTab: 'KS_P1_TABLE_REGISTRY',
  phase2RulesTab: 'KS_P2_MASTER_DATA_RULES',
  phase2PreflightTab: 'KS_P2_LIVE_PREFLIGHT',
  mappingTab: 'KS_P3_TABLE_MAPPING',
  migrationLogTab: 'KS_P3_MIGRATION_LOG',
  version: '1.0.1'
});

function ksP3BuildTableMapping() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    ksP3MapAssertTarget_(ss);

    const inv = ksP3MapRead_(ss, KS_P3_MAP_CFG.inventoryTab);
    const reg = ksP3MapRead_(ss, KS_P3_MAP_CFG.registryTab);
    const rules = ksP3MapRead_(ss, KS_P3_MAP_CFG.phase2RulesTab);
    const p2 = ksP3MapRead_(ss, KS_P3_MAP_CFG.phase2PreflightTab);

    if (inv.length < 1 || reg.length < 1) {
      throw new Error('STOP: required governance register missing/empty.');
    }

    const invH = inv[0].map(ksP3MapNorm_);
    const regH = reg[0].map(ksP3MapNorm_);
    const ruleH = rules.length ? rules[0].map(ksP3MapNorm_) : [];
    const p2H = p2.length ? p2[0].map(ksP3MapNorm_) : [];
    const idx = (h, n) => h.indexOf(ksP3MapNorm_(n));

    const requiredInv = [
      'sheet_name','data_rows_approx','last_row','last_column',
      'nonblank_header_count','physical_headers'
    ];
    const requiredReg = [
      'table','group','priority','purpose / record grain','owner role',
      'proposed field count','backend contract?','backend file refs',
      'finalization status','safe action'
    ];
    requiredInv.forEach(x => {
      if (idx(invH, x) < 0) throw new Error('STOP: inventory column missing: ' + x);
    });
    requiredReg.forEach(x => {
      if (idx(regH, x) < 0) throw new Error('STOP: registry column missing: ' + x);
    });

    const inventory = new Map();
    const duplicateInventoryNames = [];
    inv.slice(1).filter(r => r[idx(invH, 'sheet_name')]).forEach(r => {
      const name = String(r[idx(invH, 'sheet_name')]).trim();
      if (inventory.has(name)) duplicateInventoryNames.push(name);
      inventory.set(name, r);
    });
    if (duplicateInventoryNames.length) {
      throw new Error('STOP: duplicate sheet names in inventory: ' +
        duplicateInventoryNames.join(', '));
    }

    const canonical = new Map();
    const duplicateCanonicalNames = [];
    reg.slice(1).filter(r => r[idx(regH, 'table')]).forEach(r => {
      const name = String(r[idx(regH, 'table')]).trim();
      if (canonical.has(name)) duplicateCanonicalNames.push(name);
      canonical.set(name, r);
    });
    if (duplicateCanonicalNames.length) {
      throw new Error('STOP: duplicate canonical table names: ' +
        duplicateCanonicalNames.join(', '));
    }

    const phase2Rules = new Map();
    if (rules.length) {
      const tabCol = idx(ruleH, 'existing_tab');
      rules.slice(1).filter(r => tabCol >= 0 && r[tabCol]).forEach(r => {
        phase2Rules.set(String(r[tabCol]).trim(), r);
      });
    }

    const p2Set = new Set();
    if (p2.length) {
      const nameCol = idx(p2H, 'sheet_name');
      p2.slice(1).filter(r => nameCol >= 0 && r[nameCol]).forEach(r => {
        p2Set.add(String(r[nameCol]).trim());
      });
    }

    const headers = [
      'live_tab_name','mapping_class','canonical_group','priority','record_purpose',
      'owner_role','approx_data_rows','last_row','last_column','live_header_count',
      'live_headers','backend_contract','backend_file_references','phase1_finalization_status',
      'phase1_safe_action','phase2_decision','authority_or_role','dependency_review',
      'proposed_action','approval_status','review_notes'
    ];

    // Preserve manual decision columns from the existing mapping register.
    const oldManual = ksP3MapReadExistingManual_(ss, headers);

    const rows = [];
    const names = Array.from(inventory.keys()).sort((a, b) => a.localeCompare(b));

    names.forEach(name => {
      const ir = inventory.get(name);
      const cr = canonical.get(name);
      const rr = phase2Rules.get(name);
      const get = (row, h, key) => {
        const j = idx(h, key);
        return j < 0 || row[j] == null ? '' : row[j];
      };

      let cls, purpose = '', owner = '', group = '', priority = '';
      let contract = '', refs = '', finalStatus = '', safeAction = '';

      if (cr) {
        cls = 'CANONICAL_TABLE';
        group = get(cr, regH, 'group');
        priority = get(cr, regH, 'priority');
        purpose = get(cr, regH, 'purpose / record grain');
        owner = get(cr, regH, 'owner role');
        contract = get(cr, regH, 'backend contract?');
        refs = get(cr, regH, 'backend file refs');
        finalStatus = get(cr, regH, 'finalization status');
        safeAction = get(cr, regH, 'safe action');
      } else {
        cls = 'EXTRA_TAB_REVIEW';
        purpose = 'Not listed in the canonical registry; classify from workflow and code usage.';
        owner = 'To be confirmed';
      }

      const phase2Decision = rr && idx(ruleH, 'phase2_decision') >= 0
        ? (rr[idx(ruleH, 'phase2_decision')] || '') : '';
      let authority = 'UNCONFIRMED: map actual read/write paths before assigning authority';
      if (rr && String(phase2Decision).indexOf('KEEP') === 0) {
        authority = 'Phase 2 decision recorded; verify ownership and route usage';
      }

      const specialAuthority = {
        Sales: 'Sales transaction authority; preserve existing records',
        SaleItems: 'Sales line-item authority; preserve existing records',
        Payments: 'Payment-event authority; preserve existing records',
        JournalHeaders: 'Accounting journal header authority',
        JournalLines: 'Accounting journal line authority',
        Products: 'Existing product master; do not create a parallel master',
        Users: 'ERP user directory; restricted employee data',
        AuthUsers: 'Authentication authority; highly restricted',
        Workers: 'Factory workforce records; distinct from login users',
        IdAllocations: 'Existing ID allocation registry; preserve historical allocations',
        Settings: 'Configuration authority; setting_value remains TEXT'
      };
      if (specialAuthority[name]) authority = specialAuthority[name];

      const notes = cr
        ? 'Canonical name match only. Route usage, record authority and dependencies still require verification.'
        : (p2Set.has(name)
          ? 'Present in Phase 2 preflight but outside canonical registry; classify as runtime/control/support/legacy only after review.'
          : 'Present in Phase 3 inventory but absent from canonical registry and Phase 2 preflight; investigate origin.');

      const generated = [
        name, cls, group, priority, purpose, owner,
        ir[idx(invH, 'data_rows_approx')],
        ir[idx(invH, 'last_row')],
        ir[idx(invH, 'last_column')],
        ir[idx(invH, 'nonblank_header_count')],
        ir[idx(invH, 'physical_headers')],
        contract, refs, finalStatus, safeAction
      ];
      const manualDefaults = [
        phase2Decision,
        authority,
        'PENDING: inspect backend read/write references and parent-child dependencies',
        'PRESERVE; classify before any rename/merge/retirement',
        'PENDING OWNER + TECHNICAL REVIEW',
        notes
      ];
      const prior = oldManual.get(name);
      const manual = prior
        ? prior.map((v, i) => v === '' || v === null ? manualDefaults[i] : v)
        : manualDefaults;
      rows.push(generated.concat(manual));
    });

    // Include canonical registry entries absent from the physical live inventory.
    Array.from(canonical.keys()).sort((a, b) => a.localeCompare(b)).forEach(name => {
      if (inventory.has(name)) return;
      const cr = canonical.get(name);
      const get = (key) => {
        const j = idx(regH, key);
        return j < 0 || cr[j] == null ? '' : cr[j];
      };
      const generated = [
        name, 'CANONICAL_MISSING', get('group'), get('priority'),
        get('purpose / record grain'), get('owner role'),
        '', '', '', '', '', get('backend contract?'), get('backend file refs'),
        get('finalization status'), get('safe action')
      ];
      const defaults = [
        '', 'No physical tab found in current inventory; verify live workbook and registry.',
        'PENDING: investigate missing canonical tab and backend dependencies',
        'DO NOT CREATE until owner and technical approval',
        'PENDING OWNER + TECHNICAL REVIEW',
        'Canonical registry entry has no matching physical tab in inventory.'
      ];
      const prior = oldManual.get(name);
      rows.push(generated.concat(prior
        ? prior.map((v, i) => v === '' || v === null ? defaults[i] : v)
        : defaults));
    });

    const mapping = ksP3MapGetOwnedTab_(ss, KS_P3_MAP_CFG.mappingTab, headers);
    // Safe replacement is limited to the explicitly owned mapping tab.
    // Manual decision columns have already been carried forward by key.
    mapping.clearContents();
    mapping.getRange(1, 1, 1, headers.length).setValues([headers]);
    if (rows.length) {
      mapping.getRange(2, 1, rows.length, headers.length).setValues(rows);
    }
    mapping.setFrozenRows(1);
    mapping.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    mapping.autoResizeColumns(1, headers.length);
    const oldFilter = mapping.getFilter();
    if (oldFilter) oldFilter.remove();
    mapping.getRange(1, 1, Math.max(1, rows.length + 1), headers.length).createFilter();

    const extraCount = rows.filter(r => r[1] === 'EXTRA_TAB_REVIEW').length;
    const missingCount = rows.filter(r => r[1] === 'CANONICAL_MISSING').length;
    const log = ksP3MapGetLog_(ss);
    log.appendRow([
      new Date(), KS_P3_MAP_CFG.version, 'BUILD_CANONICAL_TABLE_MAPPING',
      'Rebuilt mapping register; preserved manual decision columns; no business schema changed.',
      JSON.stringify({
        mappedRows: rows.length,
        canonicalMatches: rows.filter(r => r[1] === 'CANONICAL_TABLE').length,
        extraTabsForReview: extraCount,
        canonicalMissing: missingCount,
        preservedManualRows: oldManual.size,
        businessSchemaChanged: false
      })
    ]);

    const result = {
      success: true,
      version: KS_P3_MAP_CFG.version,
      mappedRows: rows.length,
      canonicalMatches: rows.filter(r => r[1] === 'CANONICAL_TABLE').length,
      extraTabsForReview: extraCount,
      canonicalMissing: missingCount,
      preservedManualRows: oldManual.size,
      mappingTab: KS_P3_MAP_CFG.mappingTab,
      businessSchemaChanged: false
    };
    Logger.log(JSON.stringify(result, null, 2));
    return result;
  } finally {
    lock.releaseLock();
  }
}

function ksP3MapReadExistingManual_(ss, expectedHeaders) {
  const sh = ss.getSheetByName(KS_P3_MAP_CFG.mappingTab);
  const result = new Map();
  if (!sh || sh.getLastRow() < 2 || sh.getLastColumn() < expectedHeaders.length) return result;

  const actualHeaders = sh.getRange(1, 1, 1, sh.getLastColumn())
    .getDisplayValues()[0].map(ksP3MapNorm_);
  const keyCol = actualHeaders.indexOf('live_tab_name');
  if (keyCol < 0) return result;

  const manualNames = [
    'phase2_decision','authority_or_role','dependency_review',
    'proposed_action','approval_status','review_notes'
  ];
  const manualCols = manualNames.map(n => actualHeaders.indexOf(ksP3MapNorm_(n)));
  if (manualCols.some(i => i < 0)) return result;

  const data = sh.getRange(2, 1, sh.getLastRow() - 1, sh.getLastColumn()).getValues();
  data.forEach(row => {
    const key = String(row[keyCol] || '').trim();
    if (!key) return;
    result.set(key, manualCols.map(i => row[i]));
  });
  return result;
}

function ksP3VerifyTableMapping() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ksP3MapAssertTarget_(ss);
  const sh = ss.getSheetByName(KS_P3_MAP_CFG.mappingTab);
  if (!sh) throw new Error('Mapping register not found.');
  const values = sh.getDataRange().getValues();
  if (!values.length) throw new Error('Mapping register is empty.');
  const header = values[0];
  const classCol = header.indexOf('mapping_class');
  const count = cls => classCol < 0 ? 0 :
    values.slice(1).filter(r => r[classCol] === cls).length;
  const result = {
    success: true,
    tab: sh.getName(),
    rows: Math.max(0, sh.getLastRow() - 1),
    columns: sh.getLastColumn(),
    canonicalMatches: count('CANONICAL_TABLE'),
    extraTabsForReview: count('EXTRA_TAB_REVIEW'),
    canonicalMissing: count('CANONICAL_MISSING'),
    note: 'Verification only. No business tabs or records changed.'
  };
  Logger.log(JSON.stringify(result, null, 2));
  return result;
}

function ksP3MapAssertTarget_(ss) {
  if (!ss || ss.getId() !== KS_P3_MAP_CFG.spreadsheetId ||
      !ss.getName().startsWith(KS_P3_MAP_CFG.expectedNamePrefix)) {
    throw new Error('STOP: wrong spreadsheet. No changes made.');
  }
}

function ksP3MapRead_(ss, name) {
  const sh = ss.getSheetByName(name);
  if (!sh) throw new Error('Required register missing: ' + name);
  return sh.getDataRange().getValues();
}

function ksP3MapNorm_(v) {
  return String(v == null ? '' : v).trim().toLowerCase();
}

function ksP3MapGetOwnedTab_(ss, name, expectedHeaders) {
  let sh = ss.getSheetByName(name);
  if (sh) {
    if (sh.getLastRow() > 0 && sh.getLastColumn() > 0) {
      const existing = sh.getRange(1, 1, 1, sh.getLastColumn())
        .getDisplayValues()[0].map(v => String(v || '').trim());
      const expected = expectedHeaders.map(String);
      if (existing.join('\u001f') !== expected.join('\u001f')) {
        throw new Error('STOP: ' + name +
          ' exists with unexpected headers. No write performed.');
      }
    }
  } else {
    sh = ss.insertSheet(name);
  }
  return sh;
}

function ksP3MapGetLog_(ss) {
  const sh = ss.getSheetByName(KS_P3_MAP_CFG.migrationLogTab);
  if (!sh) throw new Error('Migration log missing.');
  if (sh.getLastRow() < 1 || sh.getLastColumn() < 1) {
    throw new Error('Migration log has no header. No mapping write performed.');
  }
  const h = sh.getRange(1, 1, 1, sh.getLastColumn())
    .getDisplayValues()[0].map(ksP3MapNorm_);
  if (h.indexOf('timestamp') < 0 || h.indexOf('version') < 0) {
    throw new Error('Migration log header mismatch. No mapping write performed.');
  }
  return sh;
}
