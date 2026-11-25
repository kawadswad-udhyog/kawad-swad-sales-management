/**
 * KAWAD SWAD ERP - SHEETS-FIRST MASTER DATA FOUNDATION
 * Version: 1.0.0
 *
 * Scope:
 * - Google Sheets is the authoritative record for this interim stage.
 * - Uses LockService + IdAllocations claims for master IDs.
 * - Supports Products, RawMaterials, Customers and Suppliers manual ID reservation.
 * - Audits master-sheet headers and duplicate existing IDs (except AuthUsers).
 * - Does not read AuthUsers data or write to Users/AuthUsers.
 * - Does not create sample records, alter headers, rename/delete tabs, or change existing rows.
 *
 * IMPORTANT:
 * - Install in the bound Kawad_Swad_Sales_Management_Google_Sheets project.
 * - Do not use alongside another active allocator that writes to IdAllocations.
 * - Backend must later call the same allocator endpoint or replace it under a coordinated cutover.
 */

const KS_MD1 = Object.freeze({
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  NAME_PREFIX: 'Kawad_Swad_Sales_Management_Google_Sheets',
  REPORT_TAB: 'KS_P3_BATCH1_SHEETS_FOUNDATION_AUDIT',
  ALLOC_TAB: 'IdAllocations',
  ALLOC_HEADERS: ['allocation_id','tab_name','allocated_id','nonce','created_at'],
  TARGETS: {
    Products:    { prefix: 'PRD', idHeader: 'product_id', skuHeader: 'sku', allowManual: true },
    RawMaterials:{ prefix: 'RWM', idHeader: 'raw_material_id', allowManual: true },
    Customers:   { prefix: 'CUS', idHeader: 'customer_id', allowManual: true },
    Suppliers:   { prefix: 'SUP', idHeader: 'supplier_id', allowManual: true },
    Users:       { prefix: 'USR', idHeader: 'user_id', allowManual: false }
  },
  AUDIT_TABS: ['Settings','IdAllocations','Products','RawMaterials','Customers','Suppliers','Users']
});

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Kawad Swad | Phase 3')
    .addItem('Run Master Foundation Audit','KS_P3_SHEETS_MASTER_AUDIT')
    .addItem('Reserve Master ID','KS_P3_RESERVE_MASTER_ID')
    .addToUi();
}

function KS_P3_SHEETS_MASTER_AUDIT() {
  const ss = ksMdAssertWorkbook_();
  const rows = [];
  KS_MD1.AUDIT_TABS.forEach(name => {
    const sh = ss.getSheetByName(name);
    if (!sh) {
      rows.push([name,'MISSING',0,'','','NOT_CHECKED','STOP','Required tab missing']);
      return;
    }
    const lastCol = sh.getLastColumn();
    const headers = lastCol ? sh.getRange(1,1,1,lastCol).getDisplayValues()[0].map(v => String(v).trim()) : [];
    const nonblank = headers.filter(Boolean);
    const dupes = nonblank.filter((v,i,a) => a.indexOf(v) !== i);
    const rowsCount = Math.max(0, sh.getLastRow()-1);
    let idCheck = 'NOT_APPLICABLE';
    let note = 'Header/dimension audit only.';
    if (name === 'AuthUsers') {
      idCheck = 'NOT_SCANNED';
      note = 'AuthUsers is intentionally excluded. No credentials or authentication rows read.';
    } else if (name === 'Users') {
      idCheck = 'NOT_SCANNED';
      note = 'User rows not scanned by this utility. User creation remains restricted.';
    } else {
      const idCol = name === 'Products' ? 'product_id' :
        name === 'RawMaterials' ? 'raw_material_id' :
        name === 'Customers' ? 'customer_id' :
        name === 'Suppliers' ? 'supplier_id' : '';
      if (idCol && rowsCount > 0 && headers.includes(idCol)) {
        const vals = sh.getRange(2, headers.indexOf(idCol)+1, rowsCount, 1).getDisplayValues().flat().map(v=>String(v).trim()).filter(Boolean);
        const seen = new Set(), d = new Set();
        vals.forEach(v => { if(seen.has(v)) d.add(v); seen.add(v); });
        idCheck = d.size ? 'DUPLICATES_FOUND:'+d.size : 'NO_DUPLICATES_IN_SCANNED_ID_COLUMN';
        note = 'Only ID column inspected; no other business values evaluated.';
      } else if (idCol) {
        idCheck = rowsCount === 0 ? 'NO_DATA_ROWS' : 'ID_HEADER_MISSING';
      }
    }
    rows.push([name,'YES',lastCol,nonblank.length,dupes.join(' | '),idCheck,
      dupes.length ? 'REVIEW_REQUIRED' : 'STRUCTURE_REVIEW',note]);
  });

  const report = ksMdGetOrCreate_(ss, KS_MD1.REPORT_TAB);
  report.clearContents();
  const headers = ['tab_name','tab_exists','physical_column_count','nonblank_header_count',
    'duplicate_headers','id_check','result','notes'];
  report.getRange(1,1,1,headers.length).setValues([headers]);
  if (rows.length) report.getRange(2,1,rows.length,headers.length).setValues(rows);
  report.setFrozenRows(1);
  report.autoResizeColumns(1,headers.length);
  const result = {
    success:true, status:'SHEETS_MASTER_FOUNDATION_AUDIT_COMPLETE',
    auditedTabs:KS_MD1.AUDIT_TABS.length,
    authUsersDataRead:false, usersDataRead:false,
    businessSchemaChanged:false, reportTab:KS_MD1.REPORT_TAB,
    note:'Audit report written. No business tabs, headers, or records were changed.'
  };
  Logger.log('KS_P3_SHEETS_MASTER_AUDIT_RESULT '+JSON.stringify(result));
  return result;
}

/**
 * Manual interim reservation. The ID is claimed in IdAllocations only.
 * It does NOT create a Products/RawMaterials/Customers/Suppliers row.
 */
function KS_P3_RESERVE_MASTER_ID() {
  const ui = SpreadsheetApp.getUi();
  const choices = ['Products','RawMaterials','Customers','Suppliers'];
  const response = ui.prompt(
    'Reserve Master ID',
    'Enter one exact sheet name:\n'+choices.join('\n')+
    '\n\nUsers/AuthUsers are excluded from manual reservation.',
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;
  const tab = response.getResponseText().trim();
  if (!choices.includes(tab)) throw new Error('Unsupported or restricted master tab: '+tab);
  const allocated = ksMdAllocate_(tab);
  ui.alert('ID reserved successfully', allocated+'\n\nA claim was appended to IdAllocations. No master record was created.', ui.ButtonSet.OK);
  return allocated;
}

function ksMdAllocate_(tabName) {
  const cfg = KS_MD1.TARGETS[tabName];
  if (!cfg || !cfg.allowManual) throw new Error('ID allocation is not enabled for this tab.');
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = ksMdAssertWorkbook_();
    const target = ss.getSheetByName(tabName);
    const alloc = ss.getSheetByName(KS_MD1.ALLOC_TAB);
    if (!target || !alloc) throw new Error('Target tab or IdAllocations is missing.');
    ksMdAssertHeaders_(alloc, KS_MD1.ALLOC_HEADERS);

    const headers = target.getRange(1,1,1,target.getLastColumn()).getDisplayValues()[0].map(v=>String(v).trim());
    const idIndex = headers.indexOf(cfg.idHeader);
    if (idIndex < 0) throw new Error('Required ID header missing: '+cfg.idHeader);

    const existing = new Set();
    const last = target.getLastRow();
    if (last > 1) target.getRange(2,idIndex+1,last-1,1).getDisplayValues().flat()
      .map(v=>String(v).trim()).filter(Boolean).forEach(v=>existing.add(v));

    const allocLast = alloc.getLastRow();
    const claimRows = allocLast > 1 ? alloc.getRange(2,1,allocLast-1,5).getDisplayValues() : [];
    let highest = 0;
    const re = new RegExp('^'+cfg.prefix+'-(\\d{6})$');
    existing.forEach(v=>{const m=v.match(re); if(m) highest=Math.max(highest,Number(m[1]));});
    claimRows.forEach(r=>{
      if (String(r[1]).trim()===tabName) {
        const m=String(r[2]).trim().match(re);
        if(m) highest=Math.max(highest,Number(m[1]));
      }
    });

    const candidate = cfg.prefix+'-'+String(highest+1).padStart(6,'0');
    if (existing.has(candidate) || claimRows.some(r=>String(r[1]).trim()===tabName && String(r[2]).trim()===candidate)) {
      throw new Error('Candidate ID already exists. Run audit and investigate; no claim written.');
    }
    const nonce = Utilities.getUuid().replace(/-/g,'');
    const allocationId = 'ALC-'+nonce.slice(0,12).toUpperCase();
    const timestamp = new Date();
    alloc.appendRow([allocationId,tabName,candidate,nonce,timestamp]);
    SpreadsheetApp.flush();

    const verifyLast = alloc.getLastRow();
    const verify = alloc.getRange(verifyLast,1,1,5).getDisplayValues()[0];
    if (verify[0] !== allocationId || verify[2] !== candidate || verify[3] !== nonce) {
      throw new Error('Allocation claim verification failed. Do not use the candidate ID.');
    }
    return candidate;
  } finally {
    lock.releaseLock();
  }
}

function ksMdAssertWorkbook_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss || ss.getId() !== KS_MD1.SPREADSHEET_ID ||
      !ss.getName().startsWith(KS_MD1.NAME_PREFIX)) {
    throw new Error('STOP: This script is not bound to the expected Kawad Swad workbook.');
  }
  return ss;
}
function ksMdAssertHeaders_(sh, expected) {
  const actual = sh.getRange(1,1,1,Math.max(sh.getLastColumn(),expected.length))
    .getDisplayValues()[0].map(v=>String(v).trim());
  if (expected.some((h,i)=>actual[i]!==h)) {
    throw new Error('STOP: IdAllocations headers do not exactly match expected five-column contract. No allocation written.');
  }
}
function ksMdGetOrCreate_(ss,name) {
  let sh=ss.getSheetByName(name);
  if(!sh) sh=ss.insertSheet(name);
  return sh;
}
