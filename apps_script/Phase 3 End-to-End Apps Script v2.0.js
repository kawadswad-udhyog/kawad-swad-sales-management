/**
 * KAWAD SWAD ERP | PHASE 3 END-TO-END MASTER ROLLOUT
 * Version 2.0.0 | Controlled batches 2-5
 *
 * Google Sheets remains the authoritative business record.
 * This package does NOT change existing business headers, rename/delete/reorder tabs,
 * rewrite historical IDs, create users, access AuthUsers, or enforce unresolved FKs.
 *
 * IMPORTANT:
 * - First approved Product/Customer/Supplier committed through intake is the real ID-allocation test.
 *   No dummy ID is burned. An allocation claim is never recycled.
 * - RawMaterials use owner-supplied semantic IDs. Generic RWM allocation is disabled.
 * - ScriptLock protects this Apps Script project only. It is NOT a distributed lock across
 *   backend instances or other Apps Script projects. Use a single writer for ID creation.
 * - Relationship and workflow audits are readiness reports, not automatic FK enforcement.
 */

const KS3R = Object.freeze({
  VERSION: '2.0.0',
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME: 'Kawad_Swad_Sales_Management_Google_Sheets',
  CONTROL: 'KS_P3_ROLLOUT_CONTROL',
  INTAKE: 'KS_P3_MASTER_INTAKE',
  FOUNDATION_AUDIT: 'KS_P3_FOUNDATION_AUDIT',
  ID_AUDIT: 'KS_P3_ID_ALLOCATION_AUDIT',
  MASTER_AUDIT: 'KS_P3_MASTER_VALIDATION',
  REL_AUDIT: 'KS_P3_RELATIONSHIP_AUDIT',
  WORKFLOW_AUDIT: 'KS_P3_WORKFLOW_READINESS',
  EVENT: 'KS_P3_ROLLOUT_EVENTS',
  ID_HEADERS: ['allocation_id','tab_name','allocated_id','nonce','created_at'],
  INTAKE_HEADERS: ['entity','approval_status','record_json','created_id','commit_status','commit_note','committed_at'],
  TABLES: {
    Products: {id:'product_id', prefix:'PRD', required:['sku','product_name','category','variant','pack_weight_g','selling_unit'], unique:['sku']},
    Customers: {id:'customer_id', prefix:'CUS', required:['customer_type','shopkeeper_name','mobile'], unique:[]},
    Suppliers: {id:'supplier_id', prefix:'SUP', required:['supplier_name'], unique:[]},
    RawMaterials: {id:'raw_material_id', prefix:null, required:['raw_material_id','material_name','unit'], unique:[]}
  },
  HEADERS: {
    Products:['product_id','sku','product_name','category','variant','pack_weight_g','selling_unit','retail_pack_only','active','notes'],
    RawMaterials:['raw_material_id','material_name','unit','opening_stock','current_stock','minimum_stock','active','notes','rate_per_unit','rate_status','category','created_at','created_by'],
    Customers:['customer_id','customer_type','shop_name','shopkeeper_name','mobile','alternate_mobile','address','locality_area','city','map_location','active','created_at','notes','gstin'],
    Suppliers:['supplier_id','supplier_name','contact_person','mobile','email','address','city','gstin','payment_terms_days','opening_balance','active','notes','created_at','created_by']
  },
  WORKFLOWS: [
    ['Recipes','product_id','Products','product_id'],
    ['ProductionBatches','product_id','Products','product_id'],
    ['ProductionBatches','recipe_id','Recipes','recipe_id'],
    ['SaleItems','product_id','Products','product_id'],
    ['SaleItems','sale_id','Sales','sale_id'],
    ['Sales','customer_id','Customers','customer_id'],
    ['Payments','sale_id','Sales','sale_id'],
    ['PurchaseOrders','supplier_id','Suppliers','supplier_id'],
    ['SupplierBills','supplier_id','Suppliers','supplier_id'],
    ['RawMaterialLedger','raw_material_id','RawMaterials','raw_material_id'],
    ['ProductionStockLedger','product_id','Products','product_id']
  ]
});

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Kawad Swad | Phase 3 Rollout')
    .addItem('0. Install control and intake tabs', 'KS3R_INSTALL_CONTROLS')
    .addItem('1. Run complete read-only preflight', 'KS3R_RUN_ALL_AUDITS')
    .addSeparator()
    .addItem('2. Review and approve ID policy', 'KS3R_APPROVE_ID_POLICY')
    .addItem('2. Run ID allocation dry-run', 'KS3R_ID_DRY_RUN')
    .addSeparator()
    .addItem('3. Commit approved intake rows', 'KS3R_COMMIT_APPROVED_INTAKE')
    .addItem('4. Run master data validation', 'KS3R_MASTER_VALIDATION')
    .addItem('4. Run relationship audit', 'KS3R_RELATIONSHIP_AUDIT')
    .addItem('5. Run operational workflow readiness', 'KS3R_WORKFLOW_READINESS')
    .addToUi();
}

function ks3rSs_() {
  const ss=SpreadsheetApp.getActiveSpreadsheet();
  if(!ss || ss.getId()!==KS3R.SPREADSHEET_ID || ss.getName()!==KS3R.EXPECTED_NAME)
    throw new Error('SAFETY STOP: wrong spreadsheet ID or name. No action taken.');
  return ss;
}
function ks3rSheet_(ss,n){const s=ss.getSheetByName(n);if(!s)throw new Error('Required tab missing: '+n);return s;}
function ks3rHeaders_(sh){
  const n=sh.getLastColumn(); if(n<1)throw new Error(sh.getName()+' has no headers.');
  const a=sh.getRange(1,1,1,n).getDisplayValues()[0].map(x=>String(x).trim()); const m={};
  a.forEach((h,i)=>{if(!h)throw new Error(sh.getName()+' blank header at '+(i+1));if(m[h])throw new Error(sh.getName()+' duplicate header '+h);m[h]=i+1;});return m;
}
function ks3rNeedHeaders_(sh,expected){const m=ks3rHeaders_(sh);const miss=expected.filter(h=>!m[h]);if(miss.length)throw new Error('STOP '+sh.getName()+' missing headers: '+miss.join(', '));return m;}
function ks3rReport_(ss,name,headers,rows){let s=ss.getSheetByName(name);if(!s)s=ss.insertSheet(name);s.clearContents();s.getRange(1,1,1,headers.length).setValues([headers]);if(rows.length)s.getRange(2,1,rows.length,headers.length).setValues(rows);s.setFrozenRows(1);s.autoResizeColumns(1,headers.length);}
function ks3rLog_(ss,action,detail){let s=ss.getSheetByName(KS3R.EVENT);const h=['event_at','actor','action','detail'];if(!s){s=ss.insertSheet(KS3R.EVENT);s.appendRow(h);}else ks3rNeedHeaders_(s,h);s.appendRow([new Date(),Session.getActiveUser().getEmail()||'UNAVAILABLE',action,detail||'']);}
function ks3rLastDataRow_(sh,idCol){const last=sh.getLastRow();if(last<2)return 1;const v=sh.getRange(2,idCol,last-1,1).getDisplayValues();for(let i=v.length-1;i>=0;i--)if(String(v[i][0]).trim())return i+2;return 1;}
function ks3rNonblank_(sh,col){const last=sh.getLastRow();if(last<2)return [];return sh.getRange(2,col,last-1,1).getDisplayValues().map(r=>String(r[0]).trim()).filter(Boolean);}
function ks3rDupes_(arr){const seen=new Set(),d=new Set();arr.forEach(x=>{if(seen.has(x))d.add(x);seen.add(x);});return Array.from(d);}

function KS3R_INSTALL_CONTROLS(){
  const ss=ks3rSs_();
  let c=ss.getSheetByName(KS3R.CONTROL);if(!c){c=ss.insertSheet(KS3R.CONTROL);c.getRange(1,1,1,3).setValues([['control_key','control_value','description']]);c.setFrozenRows(1);}
  let i=ss.getSheetByName(KS3R.INTAKE);if(!i){i=ss.insertSheet(KS3R.INTAKE);i.getRange(1,1,1,KS3R.INTAKE_HEADERS.length).setValues([KS3R.INTAKE_HEADERS]);i.setFrozenRows(1);i.getRange('A:A').setNote('Products, Customers, Suppliers, RawMaterials only. Do not enter Users/AuthUsers.');i.getRange('B:B').setNote('Set APPROVED only after owner review.');i.getRange('C:C').setNote('JSON object with keys matching the exact live sheet headers. Do not supply product/customer/supplier ID. RawMaterials requires owner-supplied semantic raw_material_id.');}
  ks3rLog_(ss,'INSTALL_CONTROLS','Created missing control/intake tabs only; existing tabs and business records untouched.');
  SpreadsheetApp.getUi().alert('Control and intake tabs are ready. No business records were created or changed.');
}

function KS3R_RUN_ALL_AUDITS(){
  const ss=ks3rSs_();const out=[];
  ['IdAllocations','Products','RawMaterials','Customers','Suppliers','Users'].forEach(n=>{
    const sh=ks3rSheet_(ss,n);const m=ks3rHeaders_(sh);const expected=n==='IdAllocations'?KS3R.ID_HEADERS:(KS3R.HEADERS[n]||['user_id','full_name','role','mobile','email','active']);
    const miss=expected.filter(h=>!m[h]);
    let count='NOT_SCANNED';
    if(n!=='Users' && m[expected[0]])count=ks3rNonblank_(sh,m[expected[0]]).length;
    out.push([n,sh.getLastColumn(),Object.keys(m).length,miss.join(', '),count,miss.length?'BLOCKED':'HEADER_OK']);
  });
  ks3rReport_(ss,KS3R.FOUNDATION_AUDIT,['tab_name','physical_columns','header_count','missing_headers','nonblank_id_count','result'],out);
  ks3rLog_(ss,'READ_ONLY_PREFLIGHT','Audited master headers and ID-column counts. Users rows were not read; AuthUsers was not accessed.');
  KS3R_ID_DRY_RUN();KS3R_MASTER_VALIDATION();KS3R_RELATIONSHIP_AUDIT();KS3R_WORKFLOW_READINESS();
  Logger.log('KS3R_ALL_AUDITS_COMPLETE '+JSON.stringify({tabs:out.length,usersDataRead:false,authUsersDataRead:false,businessSchemaChanged:false}));
}

function KS3R_APPROVE_ID_POLICY(){
  const ui=SpreadsheetApp.getUi();const ss=ks3rSs_();
  const msg='Before approving, confirm you have reviewed the pre-reset backup and reconciled all historical IDs/IdAllocations claims for Products, Customers, and Suppliers. The previous Phase 3 ID audit recorded 342 claims across 11 tabs. If this history is not reconciled, select NO.\n\nThen approve the following ID policy?\n\n1. Preserve all historical IDs exactly.\n2. New Products=PRD-000001 sequence; Customers=CUS-000001; Suppliers=SUP-000001.\n3. Check both business ID column and IdAllocations claims before allocation.\n4. Never reuse abandoned reservations.\n5. RawMaterials require owner-supplied semantic IDs; no generic RWM sequence.\n6. ScriptLock protects only this Apps Script project. Use a single writer; it is not distributed atomic locking.\n7. No automatic FK enforcement or data repair.\n\nThis approval does not approve any master record data.';
  if(ui.alert('Owner approval: ID policy',msg,ui.ButtonSet.YES_NO)!==ui.Button.YES){ui.alert('No policy approval recorded. ID creation remains blocked.');return;}
  let c=ss.getSheetByName(KS3R.CONTROL);if(!c){KS3R_INSTALL_CONTROLS();c=ks3rSheet_(ss,KS3R.CONTROL);}
  ks3rNeedHeaders_(c,['control_key','control_value','description']);
  const vals=c.getDataRange().getDisplayValues();let row=vals.findIndex((r,i)=>i>0&&r[0]==='ID_POLICY_APPROVED');
  const stamp=new Date().toISOString();
  const records=[['ID_HISTORY_RECONCILED','YES','Owner confirms pre-reset backup and historical allocation claims were reviewed and reconciled on '+stamp],['ID_POLICY_APPROVED','YES','Owner approved prefixes, no-reuse policy, semantic RawMaterials exception, and single-writer limitation on '+stamp]];
  records.forEach(record=>{const v=c.getDataRange().getDisplayValues();const ix=v.findIndex((r,i)=>i>0&&r[0]===record[0]);if(ix>0)c.getRange(ix+1,1,1,3).setValues([record]);else c.appendRow(record);});
  ks3rLog_(ss,'ID_POLICY_APPROVED','Owner confirmed proposed ID policy.');
  ui.alert('ID policy approval recorded. Run the ID dry-run before committing any intake row.');
}
function ks3rPolicyApproved_(ss){const c=ss.getSheetByName(KS3R.CONTROL);if(!c)return false;const v=c.getDataRange().getDisplayValues();const ok=k=>v.some((r,i)=>i>0&&r[0]===k&&r[1]==='YES');return ok('ID_POLICY_APPROVED')&&ok('ID_HISTORY_RECONCILED');}

function KS3R_ID_DRY_RUN(){
  const ss=ks3rSs_();const a=ks3rSheet_(ss,'IdAllocations');const am=ks3rNeedHeaders_(a,KS3R.ID_HEADERS);const rows=[];
  ['Products','Customers','Suppliers'].forEach(t=>{
    const sh=ks3rSheet_(ss,t),cfg=KS3R.TABLES[t],m=ks3rNeedHeaders_(sh,[cfg.id]);
    const business=ks3rNonblank_(sh,m[cfg.id]);const ledgerLast=a.getLastRow();
    const ledgerRows=ledgerLast<2?[]:a.getRange(2,1,ledgerLast-1,5).getDisplayValues();
    const claims=ledgerRows.filter(r=>String(r[am.tab_name-1])===t).map(r=>String(r[am.allocated_id-1]).trim()).filter(Boolean);
    const all=business.concat(claims);
    const seq=all.map(x=>{const z=String(x).match(new RegExp('^'+cfg.prefix+'-(\\d+)$'));return z?Number(z[1]):0;});
    const next=Math.max(0,...seq)+1;rows.push([t,cfg.prefix+'-'+String(next).padStart(6,'0'),business.length,claims.length,ks3rDupes_(business).join(', '),'DRY_RUN_ONLY']);
  });
  rows.push(['RawMaterials','MANUAL_SEMANTIC_ID',ks3rNonblank_(ks3rSheet_(ss,'RawMaterials'),1).length,0,'','AUTO_ALLOCATION_DISABLED']);
  ks3rReport_(ss,KS3R.ID_AUDIT,['entity','next_candidate_id','business_id_count','ledger_claim_count_all_tabs','duplicate_business_ids','status'],rows);
  Logger.log('KS3R_ID_DRY_RUN '+JSON.stringify({rows:rows,policyApproved:ks3rPolicyApproved_(ss),noReservationWritten:true}));
}

function ks3rReserve_(ss,table,lockAlreadyHeld){
  if(!ks3rPolicyApproved_(ss))throw new Error('ID policy not approved. Use menu 2. Review and approve ID policy.');
  const cfg=KS3R.TABLES[table];if(!cfg||!cfg.prefix)throw new Error('Automatic allocation disabled for '+table);
  const lock=LockService.getScriptLock();if(!lockAlreadyHeld && !lock.tryLock(20000))throw new Error('Could not obtain project lock. Retry later.');
  try{
    const sh=ks3rSheet_(ss,table),idCol=ks3rNeedHeaders_(sh,[cfg.id])[cfg.id];const led=ks3rSheet_(ss,'IdAllocations'),lm=ks3rNeedHeaders_(led,KS3R.ID_HEADERS);
    const business=ks3rNonblank_(sh,idCol);const last=led.getLastRow();const ledgerRows=last<2?[]:led.getRange(2,1,last-1,5).getDisplayValues();
    const claims=ledgerRows.filter(r=>String(r[lm.tab_name-1])===table).map(r=>String(r[lm.allocated_id-1]).trim()).filter(Boolean);
    const combined=business.concat(claims);const dup=ks3rDupes_(combined);if(dup.length)throw new Error('Duplicate ID detected in '+table+': '+dup.join(', '));
    const re=new RegExp('^'+cfg.prefix+'-(\\d+)$');let max=0;combined.forEach(x=>{const m=String(x).match(re);if(m)max=Math.max(max,Number(m[1]));});
    const id=cfg.prefix+'-'+String(max+1).padStart(6,'0');const nonce=Utilities.getUuid();const allocationId='ALC-'+nonce;
    led.appendRow([allocationId,table,id,nonce,new Date()]);
    SpreadsheetApp.flush();
    const check=led.getRange(led.getLastRow(),1,1,5).getDisplayValues()[0];if(check[2]!==id||check[1]!==table)throw new Error('Read-after-write verification failed. Do not reuse this ID.');
    return id;
  } finally {if(!lockAlreadyHeld)lock.releaseLock();}
}

function KS3R_COMMIT_APPROVED_INTAKE(){
  const ss=ks3rSs_();if(!ks3rPolicyApproved_(ss))throw new Error('ID policy approval required before committing master records.');
  const intake=ks3rSheet_(ss,KS3R.INTAKE);ks3rNeedHeaders_(intake,KS3R.INTAKE_HEADERS);const im=ks3rHeaders_(intake);const last=intake.getLastRow();if(last<2){SpreadsheetApp.getUi().alert('Intake is empty. No records to commit.');return;}
  const ui=SpreadsheetApp.getUi();if(ui.alert('Commit approved master data','Only rows marked APPROVED will be appended. Existing records will not be edited. RawMaterials IDs must be semantic owner-supplied IDs. Continue?',ui.ButtonSet.YES_NO)!==ui.Button.YES)return;
  const lock=LockService.getScriptLock();if(!lock.tryLock(20000))throw new Error('Could not obtain project lock.');let done=0,failed=0;
  try{
    const values=intake.getRange(2,1,last-1,KS3R.INTAKE_HEADERS.length).getValues();
    values.forEach((r,idx)=>{
      const sheetRow=idx+2;const entity=String(r[im.entity-1]||'').trim();const approval=String(r[im.approval_status-1]||'').trim().toUpperCase();const status=String(r[im.commit_status-1]||'').trim();
      if(approval!=='APPROVED'||status==='COMMITTED')return;
      try{
        if(!KS3R.TABLES[entity])throw new Error('Unsupported entity. Allowed: Products, Customers, Suppliers, RawMaterials.');
        const obj=JSON.parse(String(r[im.record_json-1]||'{}'));if(!obj||typeof obj!=='object'||Array.isArray(obj))throw new Error('record_json must be a JSON object.');
        const sh=ks3rSheet_(ss,entity);const expected=KS3R.HEADERS[entity];const hm=ks3rNeedHeaders_(sh,expected);const cfg=KS3R.TABLES[entity];
        cfg.required.forEach(k=>{if(obj[k]===undefined||obj[k]===null||String(obj[k]).trim()==='')throw new Error('Missing required field: '+k);});
        if(entity==='Products'){
          const skus=ks3rNonblank_(sh,hm.sku).map(x=>x.toUpperCase());if(skus.includes(String(obj.sku).trim().toUpperCase()))throw new Error('SKU already exists: '+obj.sku);
        }
        let id;
        if(entity==='RawMaterials'){
          id=String(obj.raw_material_id||'').trim();if(!/^RM-[A-Z0-9][A-Z0-9_-]*$/i.test(id))throw new Error('RawMaterials requires an approved semantic ID such as RM-MOONG-FLOUR. Generic RWM IDs are disabled.');
          const ids=ks3rNonblank_(sh,hm.raw_material_id);if(ids.includes(id))throw new Error('Raw material ID already exists: '+id);
        } else {id=ks3rReserve_(ss,entity,true);}
        const row=Array(expected.length).fill('');expected.forEach((h,i)=>{if(h===cfg.id)row[i]=id;else if(obj[h]!==undefined)row[i]=obj[h];});
        if(entity==='Products' && obj.active===undefined)row[hm.active-1]=true;
        if(entity==='Customers' && obj.active===undefined)row[hm.active-1]=true;
        if(entity==='Suppliers' && obj.active===undefined)row[hm.active-1]=true;
        if(entity==='RawMaterials'){
          if(obj.active===undefined)row[hm.active-1]=true;
          if(obj.created_at===undefined)row[hm.created_at-1]=new Date();
          if(obj.created_by===undefined)row[hm.created_by-1]=Session.getActiveUser().getEmail()||'UNAVAILABLE';
        }
        sh.appendRow(row);SpreadsheetApp.flush();
        const createdRow=sh.getLastRow();const verify=String(sh.getRange(createdRow,hm[cfg.id]).getDisplayValue()).trim();if(verify!==id)throw new Error('Business row read-after-write verification failed. Reserved ID will not be reused.');
        intake.getRange(sheetRow,im.created_id).setValue(id);intake.getRange(sheetRow,im.commit_status).setValue('COMMITTED');intake.getRange(sheetRow,im.commit_note).setValue('Appended to '+entity+' row '+createdRow);intake.getRange(sheetRow,im.committed_at).setValue(new Date());done++;
        ks3rLog_(ss,'MASTER_RECORD_CREATED',entity+' '+id+' appended at row '+createdRow);
      }catch(e){intake.getRange(sheetRow,im.commit_status).setValue('ERROR');intake.getRange(sheetRow,im.commit_note).setValue(String(e.message||e));failed++;}
    });
  } finally {lock.releaseLock();}
  Logger.log('KS3R_INTAKE_COMMIT '+JSON.stringify({committed:done,failed:failed,existingRecordsEdited:false,authUsersAccessed:false}));
  ui.alert('Intake run finished. Committed: '+done+'. Errors: '+failed+'. Review commit_status and commit_note in '+KS3R.INTAKE+'.');
}

function KS3R_MASTER_VALIDATION(){
  const ss=ks3rSs_();const out=[];
  Object.keys(KS3R.HEADERS).forEach(t=>{
    const sh=ks3rSheet_(ss,t),m=ks3rNeedHeaders_(sh,KS3R.HEADERS[t]);const ids=ks3rNonblank_(sh,m[KS3R.TABLES[t].id]);const dup=ks3rDupes_(ids);
    out.push([t,ids.length,ids.filter(x=>!x).length,dup.length,dup.join(', '),dup.length?'FAIL_DUPLICATE_ID':'PASS_ID_UNIQUENESS']);
    if(t==='Products'){const skus=ks3rNonblank_(sh,m.sku);const sd=ks3rDupes_(skus.map(x=>x.toUpperCase()));out.push(['Products.SKU',skus.length,0,sd.length,sd.join(', '),sd.length?'FAIL_DUPLICATE_SKU':'PASS_SKU_UNIQUENESS']);}
  });
  ks3rReport_(ss,KS3R.MASTER_AUDIT,['entity_or_key','nonblank_count','blank_count_in_id_scan','duplicate_count','duplicates','result'],out);
  Logger.log('KS3R_MASTER_VALIDATION '+JSON.stringify({checks:out.length,usersDataRead:false,authUsersDataRead:false}));
}

function KS3R_RELATIONSHIP_AUDIT(){
  const ss=ks3rSs_();const out=[];
  KS3R.WORKFLOWS.forEach(x=>{
    const [child,cf,parent,pf]=x;const cs=ss.getSheetByName(child),ps=ss.getSheetByName(parent);
    if(!cs||!ps){out.push([child,cf,parent,pf,'BLOCKED_TAB_MISSING','','','No enforcement']);return;}
    const cm=ks3rHeaders_(cs),pm=ks3rHeaders_(ps);if(!cm[cf]||!pm[pf]){out.push([child,cf,parent,pf,'BLOCKED_HEADER_MISSING','','','No enforcement']);return;}
    const pvals=ks3rNonblank_(ps,pm[pf]);const dup=ks3rDupes_(pvals);const pset=new Set(pvals);const cvals=ks3rNonblank_(cs,cm[cf]);const orphans=cvals.filter(v=>!pset.has(v));
    const status=dup.length?'BLOCKED_PARENT_DUPLICATES':orphans.length?'BLOCKED_ORPHANS':'OBSERVED_ZERO_ORPHANS';
    out.push([child,cf,parent,pf,status,pvals.length,cvals.length, 'Read-only audit. No FK enforcement. Parent duplicate count='+dup.length+'; orphan count='+orphans.length]);
  });
  ks3rReport_(ss,KS3R.REL_AUDIT,['child_table','child_field','parent_table','parent_field','result','parent_key_count','child_reference_count','notes'],out);
  Logger.log('KS3R_RELATIONSHIP_AUDIT '+JSON.stringify({relationships:out.length,foreignKeyEnforcementActivated:false}));
}

function KS3R_WORKFLOW_READINESS(){
  const ss=ks3rSs_();const out=[];
  const checks=[['Products','product_id'],['Products','sku'],['Customers','customer_id'],['Suppliers','supplier_id'],['RawMaterials','raw_material_id'],['Recipes','product_id'],['ProductionBatches','product_id'],['ProductionBatches','recipe_id'],['Sales','customer_id'],['SaleItems','product_id'],['SaleItems','sale_id'],['Payments','sale_id'],['PurchaseOrders','supplier_id'],['SupplierBills','supplier_id'],['RawMaterialLedger','raw_material_id'],['ProductionStockLedger','product_id']];
  checks.forEach(([t,f])=>{const sh=ss.getSheetByName(t);if(!sh){out.push([t,f,'TAB_MISSING','BLOCKED']);return;}const m=ks3rHeaders_(sh);out.push([t,f,m[f]?'HEADER_PRESENT':'FIELD_MISSING',m[f]?'READY_FOR_DATA_LEVEL_TEST':'BLOCKED_SCHEMA_OR_ALIAS_REVIEW']);});
  out.push(['ERP backend / API','master-reference validation','Not changed by this Apps Script package','REQUIRES_SEPARATE_CODE_INTEGRATION_AND_TESTS']);
  out.push(['Foreign-key enforcement','all 41 proposed relationships','Package 3 reports unresolved physical key mappings','BLOCKED_PENDING_OWNER_APPROVAL']);
  ks3rReport_(ss,KS3R.WORKFLOW_AUDIT,['workflow_area','reference_field','observation','readiness'],out);
  Logger.log('KS3R_WORKFLOW_READINESS '+JSON.stringify({checks:out.length,backendCodeChanged:false,foreignKeyEnforcementActivated:false}));
}
