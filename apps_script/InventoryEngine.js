/**
 * KAWAD SWAD ERP - INVENTORY LOT & MOVEMENT ENGINE
 * Blueprint Version: 2.0 | Enforces POL-003, POL-004, POL-005, REQ-004, REQ-034..039
 * Wired to hydrated InventoryLots & InventoryMovements tables.
 */

const KS_MOVEMENT_TYPES = Object.freeze([
  'OPENING_BALANCE',
  'PURCHASE_RECEIPT',
  'PRODUCTION_ISSUE',
  'PRODUCTION_OUTPUT',
  'PACKAGING_ISSUE',
  'PACKAGING_OUTPUT',
  'SALES_DISPATCH',
  'SALES_RETURN',
  'TRANSFER_OUT',
  'TRANSFER_IN',
  'DAMAGE_WRITE_OFF',
  'EXPIRY_WRITE_OFF',
  'APPROVED_ADJUSTMENT'
]);

/**
 * Creates a new traceable inventory lot (raw material, bulk output, or finished SKU)
 * and posts its initial movement record atomically with read-back verification.
 */
function ksCreateInventoryLotAndReceipt(payload) {
  const ctx = ksRequireRole_(
    [KS_ROLES.OWNER_ADMIN, KS_ROLES.STORE, KS_ROLES.PROCUREMENT, KS_ROLES.PRODUCTION, KS_ROLES.PACKAGING],
    'ksCreateInventoryLotAndReceipt'
  );

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.item_type || !payload.item_id) throw new Error('item_type and item_id are required.');
  const qty = Number(payload.quantity_received);
  if (!(qty > 0)) throw new Error('quantity_received must be greater than 0.');
  if (!payload.unit) throw new Error('unit is required.');

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const unitCost = Number(payload.unit_cost) || 0;
  const totalCost = Math.round(qty * unitCost * 100) / 100;

  // 1. Allocate idempotent Lot ID and Movement ID
  const lotAlloc = ksAllocateId('InventoryLots', payload.nonce + '_LOT');
  const movAlloc = ksAllocateId('InventoryMovements', payload.nonce + '_MOV');
  const lotId = lotAlloc.allocated_id;
  const movId = movAlloc.allocated_id;

  const lotRecord = {
    record_id: lotId,
    inventory_lot_id: lotId,
    item_type: String(payload.item_type).trim().toUpperCase(), // RAW_MATERIAL | BULK_FG | PACKAGED_SKU | PACKAGING_MAT
    item_id: String(payload.item_id).trim(),
    lot_number: payload.lot_number || lotId,
    supplier_lot_number: payload.supplier_lot_number || '',
    manufacture_date: payload.manufacture_date || '',
    received_date: payload.received_date || nowIso.slice(0, 10),
    expiry_date: payload.expiry_date || '',
    warehouse_id: payload.warehouse_id || 'WH-MAIN',
    storage_location_id: payload.storage_location_id || '',
    quantity_received: qty,
    quantity_available: qty,
    unit: String(payload.unit).trim(),
    unit_cost: unitCost,
    quality_status: payload.quality_status || 'PENDING_QC', // Held from sale until RELEASED (POL-005 / DB-05)
    status: 'ACTIVE',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  const movRecord = {
    record_id: movId,
    movement_id: movId,
    movement_datetime: nowIso,
    item_type: lotRecord.item_type,
    item_id: lotRecord.item_id,
    inventory_lot_id: lotId,
    movement_type: payload.movement_type || 'PURCHASE_RECEIPT',
    quantity_in: qty,
    quantity_out: 0,
    unit: lotRecord.unit,
    from_location_id: payload.from_location_id || 'EXTERNAL_SUPPLIER',
    to_location_id: lotRecord.warehouse_id,
    reference_type: payload.reference_type || 'GRN',
    reference_id: payload.reference_id || '',
    unit_cost: unitCost,
    total_cost: totalCost,
    performed_by: ctx.user_id,
    approved_by: payload.approved_by || '',
    status: 'POSTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  try {
    ksAppendAndVerifyRow_(ss, 'InventoryLots', lotRecord, 'inventory_lot_id', ['inventory_lot_id', 'item_id', 'unit']);
    ksAppendAndVerifyRow_(ss, 'InventoryMovements', movRecord, 'movement_id', ['movement_id', 'inventory_lot_id', 'movement_type']);

    ksLogAudit_('STOCK_RECEIPT_POSTED', 'InventoryLots', lotId, {
      actor_user_id: ctx.user_id,
      field_changed: 'quantity_in',
      new_value: qty + ' ' + lotRecord.unit,
      reason: movRecord.movement_type + ' (' + lotRecord.quality_status + ')',
      related_record_id: movId
    });

    return {
      success: true,
      inventory_lot_id: lotId,
      movement_id: movId,
      quality_status: lotRecord.quality_status
    };
  } catch (e) {
    ksLogException_('CRITICAL', 'ksCreateInventoryLotAndReceipt', 'InventoryLots', lotId, e.message, payload);
    throw e;
  }
}

/**
 * Calculates live movement-led stock balance for an item_id (and optional lot_id)
 * directly from posted rows in InventoryMovements (POL-005 & Section 3.7).
 */
function ksGetMovementLedStockBalance(itemId, optionalLotId) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const movSheet = ss.getSheetByName('InventoryMovements');
  const { headerMap } = ksGetHeaderMap_(movSheet, ['item_id', 'inventory_lot_id', 'quantity_in', 'quantity_out', 'status']);
  const lastRow = movSheet.getLastRow();
  if (lastRow < 2) return { item_id: itemId, lot_id: optionalLotId || 'ALL', total_in: 0, total_out: 0, balance: 0 };

  const data = movSheet.getRange(2, 1, lastRow - 1, movSheet.getLastColumn()).getValues();
  let totalIn = 0;
  let totalOut = 0;

  data.forEach(r => {
    if (String(r[headerMap['status'] - 1]).trim() !== 'POSTED') return;
    if (String(r[headerMap['item_id'] - 1]).trim() !== String(itemId).trim()) return;
    if (optionalLotId && String(r[headerMap['inventory_lot_id'] - 1]).trim() !== String(optionalLotId).trim()) return;

    totalIn += Number(r[headerMap['quantity_in'] - 1]) || 0;
    totalOut += Number(r[headerMap['quantity_out'] - 1]) || 0;
  });

  return {
    item_id: itemId,
    lot_id: optionalLotId || 'ALL',
    total_in: Math.round(totalIn * 1000) / 1000,
    total_out: Math.round(totalOut * 1000) / 1000,
    balance: Math.round((totalIn - totalOut) * 1000) / 1000
  };
}

/**
 * Phase G Disposable-Copy Verification Test for Inventory Engine.
 */
function ksRunPhaseGInventoryTest() {
  const res = ksCreateInventoryLotAndReceipt({
    nonce: 'TEST_INV_RECEIPT_001',
    item_type: 'RAW_MATERIAL',
    item_id: 'RM-TEST-MOONG-DAL',
    lot_number: 'LOT-2026-001',
    quantity_received: 500,
    unit: 'KG',
    unit_cost: 92.5,
    quality_status: 'RELEASED',
    notes: 'Phase G Inventory Engine test receipt'
  });

  const bal = ksGetMovementLedStockBalance('RM-TEST-MOONG-DAL', res.inventory_lot_id);
  Logger.log('Inventory Test Result: ' + JSON.stringify(res) + ' | Derived Balance: ' + JSON.stringify(bal));
}