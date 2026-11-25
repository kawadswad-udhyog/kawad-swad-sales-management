/**
 * KAWAD SWAD ERP - MANUFACTURING, QUALITY HOLD/RELEASE & PACKAGING ENGINE
 * Blueprint Version: 2.0 | Enforces POL-003..005, POL-010, POL-011, REQ-001, REQ-021..030, REQ-039
 * Wired strictly to hydrated ProductionOrders, MaterialConsumption, ProductionOutputs,
 * ProcessLosses, FinishedGoodsQualityChecks, HoldReleaseRecords, PackagingOutputs,
 * PackagingLosses, InventoryLots, and InventoryMovements headers.
 */

/**
 * 1. Creates a Production Order linked to an approved RecipeVersion (POL-010).
 */
function ksCreateProductionOrder(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.PRODUCTION], 'ksCreateProductionOrder');

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.product_id || !payload.recipe_id || !payload.recipe_version_id) {
    throw new Error('product_id, recipe_id, and approved recipe_version_id are required (POL-010).');
  }
  const plannedQty = Number(payload.planned_quantity_kg);
  if (!(plannedQty > 0)) throw new Error('planned_quantity_kg must be > 0.');

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const poAlloc = ksAllocateId('ProductionOrders', payload.nonce + '_PO');
  const poId = poAlloc.allocated_id;

  const poRecord = {
    record_id: poId,
    production_order_id: poId,
    order_number: payload.order_number || poId,
    production_plan_id: payload.production_plan_id || '',
    product_id: String(payload.product_id).trim(),
    recipe_id: String(payload.recipe_id).trim(),
    recipe_version_id: String(payload.recipe_version_id).trim(),
    planned_quantity_kg: plannedQty,
    scheduled_start: payload.scheduled_start || nowIso,
    scheduled_end: payload.scheduled_end || '',
    actual_start: payload.actual_start || '',
    actual_end: '',
    supervisor_user_id: payload.supervisor_user_id || ctx.user_id,
    status: 'APPROVED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'ProductionOrders', poRecord, 'production_order_id', [
    'production_order_id', 'product_id', 'recipe_version_id', 'planned_quantity_kg'
  ]);

  ksLogAudit_('PRODUCTION_ORDER_CREATED', 'ProductionOrders', poId, {
    actor_user_id: ctx.user_id,
    field_changed: 'planned_quantity_kg',
    new_value: plannedQty + ' KG',
    reason: 'RecipeVersion=' + poRecord.recipe_version_id
  });

  return { success: true, production_order_id: poId, planned_quantity_kg: plannedQty };
}

/**
 * 2. Records Raw Material Consumption against a Production Batch & Lot,
 * and posts a PRODUCTION_ISSUE outbound movement in InventoryMovements (POL-005, REQ-026, REQ-039).
 */
function ksRecordProductionConsumption(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PRODUCTION, KS_ROLES.STORE], 'ksRecordProductionConsumption');

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.production_batch_id || !payload.raw_material_id || !payload.inventory_lot_id) {
    throw new Error('production_batch_id, raw_material_id, and inventory_lot_id are required for traceability.');
  }

  const plannedQty = Number(payload.planned_quantity) || 0;
  const actualQty = Number(payload.actual_quantity);
  if (!(actualQty > 0)) throw new Error('actual_quantity must be > 0.');
  const unit = String(payload.unit || 'KG').trim();

  // Verify lot has sufficient movement-led balance before issuing (POL-005)
  const lotBal = ksGetMovementLedStockBalance(payload.raw_material_id, payload.inventory_lot_id);
  if (lotBal.balance < actualQty) {
    const msg = 'Insufficient stock in lot ' + payload.inventory_lot_id + ': available=' + lotBal.balance + ', requested=' + actualQty;
    ksLogException_('HIGH', 'ksRecordProductionConsumption', 'InventoryMovements', payload.inventory_lot_id, msg, payload);
    throw new Error(msg);
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const consAlloc = ksAllocateId('MaterialConsumption', payload.nonce + '_MCON');
  const movAlloc = ksAllocateId('InventoryMovements', payload.nonce + '_MOV');
  const consId = consAlloc.allocated_id;
  const movId = movAlloc.allocated_id;
  const varianceQty = Math.round((actualQty - plannedQty) * 1000) / 1000;

  const consRecord = {
    record_id: consId,
    consumption_id: consId,
    production_batch_id: String(payload.production_batch_id).trim(),
    material_issue_id: payload.material_issue_id || '',
    raw_material_id: String(payload.raw_material_id).trim(),
    inventory_lot_id: String(payload.inventory_lot_id).trim(),
    planned_quantity: plannedQty,
    actual_quantity: actualQty,
    unit: unit,
    variance_quantity: varianceQty,
    recorded_by: ctx.user_id,
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  const movRecord = {
    record_id: movId,
    movement_id: movId,
    movement_datetime: nowIso,
    item_type: 'RAW_MATERIAL',
    item_id: consRecord.raw_material_id,
    inventory_lot_id: consRecord.inventory_lot_id,
    movement_type: 'PRODUCTION_ISSUE',
    quantity_in: 0,
    quantity_out: actualQty,
    unit: unit,
    from_location_id: payload.warehouse_id || 'WH-MAIN',
    to_location_id: 'PRODUCTION_FLOOR',
    reference_type: 'PRODUCTION_BATCH',
    reference_id: consRecord.production_batch_id,
    unit_cost: Number(payload.unit_cost) || 0,
    total_cost: Math.round(actualQty * (Number(payload.unit_cost) || 0) * 100) / 100,
    performed_by: ctx.user_id,
    approved_by: '',
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: 'Consumption ' + consId
  };

  ksAppendAndVerifyRow_(ss, 'MaterialConsumption', consRecord, 'consumption_id', ['consumption_id', 'production_batch_id', 'actual_quantity']);
  ksAppendAndVerifyRow_(ss, 'InventoryMovements', movRecord, 'movement_id', ['movement_id', 'inventory_lot_id', 'movement_type']);

  ksLogAudit_('MATERIAL_CONSUMED', 'MaterialConsumption', consId, {
    actor_user_id: ctx.user_id,
    field_changed: 'actual_quantity',
    new_value: actualQty + ' ' + unit + ' (var=' + varianceQty + ')',
    related_record_id: movId
  });

  return { success: true, consumption_id: consId, movement_id: movId, variance_quantity: varianceQty };
}

/**
 * 3. Records Bulk Production Output & Process Loss.
 * Bulk output lot defaults to PENDING_QC (cannot be sold until Quality releases it per DB-05 & POL-011).
 */
function ksRecordProductionOutputAndLoss(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PRODUCTION], 'ksRecordProductionOutputAndLoss');

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.production_batch_id || !payload.product_id) throw new Error('production_batch_id and product_id are required.');
  const outputQty = Number(payload.output_quantity_kg);
  if (!(outputQty > 0)) throw new Error('output_quantity_kg must be > 0.');

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();

  // Create bulk output lot in PENDING_QC status
  const lotRes = ksCreateInventoryLotAndReceipt({
    nonce: payload.nonce + '_BULK',
    item_type: 'BULK_FG',
    item_id: payload.product_id,
    lot_number: payload.output_lot_number || ('BULK-' + payload.production_batch_id),
    quantity_received: outputQty,
    unit: 'KG',
    unit_cost: Number(payload.unit_cost) || 0,
    quality_status: 'PENDING_QC',
    movement_type: 'PRODUCTION_OUTPUT',
    from_location_id: 'PRODUCTION_FLOOR',
    warehouse_id: payload.warehouse_id || 'WH-BULK-HOLD',
    reference_type: 'PRODUCTION_BATCH',
    reference_id: payload.production_batch_id,
    notes: 'Bulk output awaiting quality release'
  });

  const outAlloc = ksAllocateId('ProductionOutputs', payload.nonce + '_POUT');
  const outId = outAlloc.allocated_id;

  const outRecord = {
    record_id: outId,
    production_output_id: outId,
    production_batch_id: String(payload.production_batch_id).trim(),
    product_id: String(payload.product_id).trim(),
    output_lot_id: lotRes.inventory_lot_id,
    output_type: 'BULK_FINISHED',
    quantity: outputQty,
    unit: 'KG',
    quality_status: 'PENDING_QC',
    recorded_by: ctx.user_id,
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'ProductionOutputs', outRecord, 'production_output_id', ['production_output_id', 'production_batch_id', 'output_lot_id']);

  let lossId = '';
  const lossQty = Number(payload.loss_quantity_kg) || 0;
  if (lossQty > 0) {
    const lossAlloc = ksAllocateId('ProcessLosses', payload.nonce + '_PLOSS');
    lossId = lossAlloc.allocated_id;
    const lossRecord = {
      record_id: lossId,
      process_loss_id: lossId,
      production_batch_id: String(payload.production_batch_id).trim(),
      process_stage: payload.loss_stage || 'DRYING_AND_MILLING',
      loss_type: payload.loss_type || 'PROCESS_WASTAGE',
      quantity: lossQty,
      unit: 'KG',
      reason: String(payload.loss_reason || 'Standard process moisture/trim loss').trim(),
      approved_by: '',
      status: 'RECORDED',
      created_at: nowIso,
      created_by: ctx.user_id,
      notes: ''
    };
    ksAppendAndVerifyRow_(ss, 'ProcessLosses', lossRecord, 'process_loss_id', ['process_loss_id', 'production_batch_id', 'quantity']);
  }

  return {
    success: true,
    production_output_id: outId,
    output_lot_id: lotRes.inventory_lot_id,
    process_loss_id: lossId,
    quality_status: 'PENDING_QC'
  };
}

/**
 * 4. Independent Quality Inspection & Lot Release (POL-011 Segregation of Duties).
 * Production Supervisors cannot call this unless explicitly granted QUALITY or OWNER_ADMIN role.
 */
function ksRecordQualityRelease(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.QUALITY], 'ksRecordQualityRelease');

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.product_lot_id || !payload.release_status) {
    throw new Error('product_lot_id and release_status (RELEASED | ON_HOLD | REJECTED) are required.');
  }

  const decision = String(payload.release_status).trim().toUpperCase();
  if (!['RELEASED', 'ON_HOLD', 'REJECTED'].includes(decision)) {
    throw new Error('Invalid release_status: ' + decision);
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const qcAlloc = ksAllocateId('FinishedGoodsQualityChecks', payload.nonce + '_FGQC');
  const qcId = qcAlloc.allocated_id;

  const qcRecord = {
    record_id: qcId,
    finished_qc_id: qcId,
    product_lot_id: String(payload.product_lot_id).trim(),
    check_datetime: nowIso,
    parameter_name: payload.parameter_name || 'MOISTURE_AND_SENSORY',
    measured_value: String(payload.measured_value || 'PASS').trim(),
    unit: payload.unit || '',
    result: decision === 'RELEASED' ? 'PASS' : 'FAIL',
    checked_by: ctx.user_id,
    release_status: decision,
    approved_by: ctx.user_id,
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'FinishedGoodsQualityChecks', qcRecord, 'finished_qc_id', ['finished_qc_id', 'product_lot_id', 'release_status']);

  // Update quality_status on the matching InventoryLots row
  const lotSheet = ss.getSheetByName('InventoryLots');
  const { headerMap } = ksGetHeaderMap_(lotSheet, ['inventory_lot_id', 'quality_status']);
  const lastRow = lotSheet.getLastRow();
  let updatedLot = false;

  if (lastRow >= 2) {
    const lotIds = lotSheet.getRange(2, headerMap['inventory_lot_id'], lastRow - 1, 1).getValues();
    for (let i = 0; i < lotIds.length; i++) {
      if (String(lotIds[i][0]).trim() === qcRecord.product_lot_id) {
        lotSheet.getRange(i + 2, headerMap['quality_status']).setValue(decision);
        updatedLot = true;
        break;
      }
    }
  }

  if (!updatedLot) {
    throw new Error('Lot "' + qcRecord.product_lot_id + '" not found in InventoryLots.');
  }

  ksLogAudit_('QUALITY_RELEASE_DECISION', 'InventoryLots', qcRecord.product_lot_id, {
    actor_user_id: ctx.user_id,
    field_changed: 'quality_status',
    old_value: 'PENDING_QC',
    new_value: decision,
    approved_by_user_id: ctx.user_id,
    related_record_id: qcId
  });

  return { success: true, finished_qc_id: qcId, product_lot_id: qcRecord.product_lot_id, release_status: decision };
}

/**
 * 5. Converts Released Bulk Lot into Packaged Retail SKUs (200g, 500g, 1000g) (Section 2.4, REQ-029).
 */
function ksRecordPackagingOutput(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PACKAGING], 'ksRecordPackagingOutput');

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.packaging_batch_id || !payload.bulk_lot_id || !payload.product_id || !payload.sku) {
    throw new Error('packaging_batch_id, bulk_lot_id, product_id, and sku are required.');
  }

  const packWeightG = Number(payload.pack_weight_g);
  const packetCount = Number(payload.packet_count);
  if (![200, 500, 1000].includes(packWeightG)) {
    throw new Error('Retail pack_weight_g must be 200, 500, or 1000 grams (per retail rule).');
  }
  if (!(packetCount > 0)) throw new Error('packet_count must be > 0.');

  const netWeightKg = Math.round(((packWeightG * packetCount) / 1000) * 1000) / 1000;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();

  // Verify source bulk lot is RELEASED before packaging
  const lotSheet = ss.getSheetByName('InventoryLots');
  const { headerMap } = ksGetHeaderMap_(lotSheet, ['inventory_lot_id', 'quality_status']);
  const lotRows = lotSheet.getRange(2, 1, Math.max(1, lotSheet.getLastRow() - 1), lotSheet.getLastColumn()).getValues();
  const bulkRow = lotRows.find(r => String(r[headerMap['inventory_lot_id'] - 1]).trim() === String(payload.bulk_lot_id).trim());
  if (!bulkRow) throw new Error('Source bulk_lot_id "' + payload.bulk_lot_id + '" not found.');
  if (String(bulkRow[headerMap['quality_status'] - 1]).trim() !== 'RELEASED') {
    throw new Error('Quality Gate Blocked: Bulk lot "' + payload.bulk_lot_id + '" is not RELEASED (DB-05 / POL-011).');
  }

  // 1. Issue bulk weight out of InventoryMovements
  const bulkOutAlloc = ksAllocateId('InventoryMovements', payload.nonce + '_BULK_OUT');
  ksAppendAndVerifyRow_(ss, 'InventoryMovements', {
    record_id: bulkOutAlloc.allocated_id,
    movement_id: bulkOutAlloc.allocated_id,
    movement_datetime: nowIso,
    item_type: 'BULK_FG',
    item_id: payload.product_id,
    inventory_lot_id: payload.bulk_lot_id,
    movement_type: 'PACKAGING_ISSUE',
    quantity_in: 0,
    quantity_out: netWeightKg,
    unit: 'KG',
    from_location_id: payload.from_warehouse_id || 'WH-BULK',
    to_location_id: 'PACKAGING_LINE',
    reference_type: 'PACKAGING_BATCH',
    reference_id: payload.packaging_batch_id,
    unit_cost: 0,
    total_cost: 0,
    performed_by: ctx.user_id,
    approved_by: '',
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: 'Issued for SKU ' + payload.sku
  }, 'movement_id', ['movement_id', 'inventory_lot_id']);

  // 2. Create finished packaged SKU lot & movement
  const fgLotRes = ksCreateInventoryLotAndReceipt({
    nonce: payload.nonce + '_FG_PKT',
    item_type: 'PACKAGED_SKU',
    item_id: payload.sku,
    lot_number: payload.fg_lot_number || ('FG-' + payload.packaging_batch_id),
    quantity_received: packetCount,
    unit: 'PKT',
    unit_cost: Number(payload.unit_cost) || 0,
    quality_status: 'RELEASED',
    movement_type: 'PACKAGING_OUTPUT',
    from_location_id: 'PACKAGING_LINE',
    warehouse_id: payload.to_warehouse_id || 'WH-FG-MAIN',
    reference_type: 'PACKAGING_BATCH',
    reference_id: payload.packaging_batch_id,
    notes: 'Packaged from bulk lot ' + payload.bulk_lot_id
  });

  // 3. Record PackagingOutputs line
  const pkOutAlloc = ksAllocateId('PackagingOutputs', payload.nonce + '_PKOUT');
  const pkOutId = pkOutAlloc.allocated_id;
  ksAppendAndVerifyRow_(ss, 'PackagingOutputs', {
    record_id: pkOutId,
    packaging_output_id: pkOutId,
    packaging_batch_id: String(payload.packaging_batch_id).trim(),
    product_id: String(payload.product_id).trim(),
    sku: String(payload.sku).trim(),
    product_lot_id: fgLotRes.inventory_lot_id,
    pack_weight_g: packWeightG,
    packet_count: packetCount,
    net_weight_kg: netWeightKg,
    recorded_by: ctx.user_id,
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: 'Source bulk lot: ' + payload.bulk_lot_id
  }, 'packaging_output_id', ['packaging_output_id', 'packaging_batch_id', 'sku', 'packet_count']);

  return {
    success: true,
    packaging_output_id: pkOutId,
    finished_sku_lot_id: fgLotRes.inventory_lot_id,
    packet_count: packetCount,
    net_weight_kg: netWeightKg
  };
}

/**
 * End-to-End Phase G Disposable-Copy Verification Test for Production -> QC Release -> Packaging.
 */
function ksRunPhaseGProductionAndPackagingTest() {
  // 1. Create Production Order
  const po = ksCreateProductionOrder({
    nonce: 'TEST_PO_001',
    product_id: 'PRD-MMP',
    recipe_id: 'RCP-MMP',
    recipe_version_id: 'RCP-MMP-V1',
    planned_quantity_kg: 100
  });

  // 2. Consume 60 KG from our earlier test raw material lot (LOT-20261118-00001)
  const cons = ksRecordProductionConsumption({
    nonce: 'TEST_MCON_001',
    production_batch_id: po.production_order_id,
    raw_material_id: 'RM-TEST-MOONG-DAL',
    inventory_lot_id: 'LOT-20261118-00001',
    planned_quantity: 60,
    actual_quantity: 60,
    unit: 'KG',
    unit_cost: 92.5
  });

  // 3. Record 95 KG Bulk Production Output + 5 KG Process Loss (held as PENDING_QC)
  const out = ksRecordProductionOutputAndLoss({
    nonce: 'TEST_POUT_001',
    production_batch_id: po.production_order_id,
    product_id: 'PRD-MMP',
    output_quantity_kg: 95,
    loss_quantity_kg: 5,
    loss_stage: 'DRYING',
    loss_reason: 'Standard moisture evaporation'
  });

  // 4. Independent Quality Release of Bulk Lot
  const qc = ksRecordQualityRelease({
    nonce: 'TEST_FGQC_001',
    product_lot_id: out.output_lot_id,
    release_status: 'RELEASED',
    measured_value: 'Moisture 11.2% - PASS'
  });

  // 5. Convert 50 KG of Released Bulk Lot into 250 x 200g packets (KS-MMP-200)
  const pkg = ksRecordPackagingOutput({
    nonce: 'TEST_PKOUT_001',
    packaging_batch_id: 'PKB-TEST-001',
    bulk_lot_id: out.output_lot_id,
    product_id: 'PRD-MMP',
    sku: 'KS-MMP-200',
    pack_weight_g: 200,
    packet_count: 250
  });

  Logger.log('Phase G Production & Packaging Test Passed: ' + JSON.stringify({ po: po, cons: cons, out: out, qc: qc, pkg: pkg }));
}