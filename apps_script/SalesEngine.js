/**
 * KAWAD SWAD ERP - SALES, INVOICING, DISPATCH & RECEIPTS ENGINE
 * Blueprint Version: 2.0 | Enforces POL-003..007, REQ-002, REQ-012, REQ-019, REQ-020, REQ-040..048
 * Wired strictly to hydrated SalesOrders, SalesOrderItems, SalesInvoices, SalesInvoiceItems,
 * CustomerPayments, CustomerPaymentAllocations, and InventoryMovements headers.
 */

/**
 * Creates a Sales Order + line items with price/tax snapshots and idempotency protection.
 */
function ksCreateSalesOrder(payload) {
  const ctx = ksRequireRole_(
    [KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.SALES, KS_ROLES.FIELD_SALESMAN],
    'ksCreateSalesOrder'
  );

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.customer_id) throw new Error('customer_id is required.');
  if (!Array.isArray(payload.items) || payload.items.length === 0) {
    throw new Error('At least one line item is required.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();

  const soAlloc = ksAllocateId('SalesOrders', payload.nonce + '_SO');
  const soId = soAlloc.allocated_id;

  let subtotal = 0;
  let totalDiscount = 0;
  let totalTax = 0;

  const preparedLines = payload.items.map((item, idx) => {
    const qty = Number(item.quantity);
    const unitPrice = Number(item.unit_price);
    const disc = Number(item.discount_amount) || 0;
    const taxRate = Number(item.tax_rate) || 0; // Unconfirmed GST rates remain 0 unless explicitly configured (POL-016)

    if (!(qty > 0)) throw new Error('Line ' + (idx + 1) + ': quantity must be > 0.');
    if (unitPrice < 0) throw new Error('Line ' + (idx + 1) + ': unit_price cannot be negative.');

    const lineGross = Math.round(qty * unitPrice * 100) / 100;
    const taxable = Math.round((lineGross - disc) * 100) / 100;
    const lineTax = Math.round(taxable * (taxRate / 100) * 100) / 100;
    const lineTotal = Math.round((taxable + lineTax) * 100) / 100;

    subtotal += lineGross;
    totalDiscount += disc;
    totalTax += lineTax;

    const lineAlloc = ksAllocateId('SalesOrderItems', payload.nonce + '_SOI_' + (idx + 1));
    return {
      record_id: lineAlloc.allocated_id,
      sales_order_item_id: lineAlloc.allocated_id,
      sales_order_id: soId,
      product_id: String(item.product_id || '').trim(),
      sku: String(item.sku || '').trim(),
      product_name_snapshot: String(item.product_name_snapshot || '').trim(),
      pack_weight_g: Number(item.pack_weight_g) || '',
      quantity: qty,
      unit_price: unitPrice,
      discount_amount: disc,
      tax_rate: taxRate,
      line_total: lineTotal,
      inventory_lot_id: String(item.inventory_lot_id || '').trim(),
      status: 'OPEN',
      created_at: nowIso,
      created_by: ctx.user_id,
      notes: item.notes || ''
    };
  });

  const shippingAmt = Number(payload.shipping_amount) || 0;
  const grandTotal = Math.round((subtotal - totalDiscount + totalTax + shippingAmt) * 100) / 100;

  const soRecord = {
    record_id: soId,
    sales_order_id: soId,
    order_number: payload.order_number || soId,
    order_datetime: nowIso,
    channel_id: payload.channel_id || 'DIRECT',
    customer_id: String(payload.customer_id).trim(),
    customer_name_snapshot: String(payload.customer_name_snapshot || '').trim(),
    customer_phone_snapshot: String(payload.customer_phone_snapshot || '').trim(),
    billing_address_json: payload.billing_address_json || '',
    shipping_address_json: payload.shipping_address_json || '',
    subtotal: Math.round(subtotal * 100) / 100,
    discount_amount: Math.round(totalDiscount * 100) / 100,
    tax_amount: Math.round(totalTax * 100) / 100,
    shipping_amount: shippingAmt,
    grand_total: grandTotal,
    payment_status: 'UNPAID',
    fulfilment_status: 'PENDING',
    external_order_id: payload.external_order_id || '',
    status: 'CONFIRMED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  try {
    ksAppendAndVerifyRow_(ss, 'SalesOrders', soRecord, 'sales_order_id', ['sales_order_id', 'customer_id', 'grand_total']);
    preparedLines.forEach(line => {
      ksAppendAndVerifyRow_(ss, 'SalesOrderItems', line, 'sales_order_item_id', ['sales_order_item_id', 'sales_order_id', 'quantity']);
    });

    ksLogAudit_('SALES_ORDER_CREATED', 'SalesOrders', soId, {
      actor_user_id: ctx.user_id,
      field_changed: 'grand_total',
      new_value: String(grandTotal),
      reason: 'Created order with ' + preparedLines.length + ' items'
    });

    return { success: true, sales_order_id: soId, grand_total: grandTotal, line_count: preparedLines.length };
  } catch (e) {
    ksLogException_('CRITICAL', 'ksCreateSalesOrder', 'SalesOrders', soId, e.message, payload);
    throw e;
  }
}

/**
 * Issues a distinct Sales Invoice from a Sales Order (POL-007: Order != Invoice).
 */
function ksCreateSalesInvoice(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.ACCOUNTS], 'ksCreateSalesInvoice');
  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.sales_order_id || !payload.customer_id) throw new Error('sales_order_id and customer_id are required.');

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const invAlloc = ksAllocateId('SalesInvoices', payload.nonce + '_INV');
  const invId = invAlloc.allocated_id;

  const taxable = Number(payload.taxable_value) || 0;
  const cgst = Number(payload.cgst_amount) || 0;
  const sgst = Number(payload.sgst_amount) || 0;
  const igst = Number(payload.igst_amount) || 0;
  const totalTax = Math.round((cgst + sgst + igst) * 100) / 100;
  const invTotal = Math.round((taxable + totalTax) * 100) / 100;

  const invRecord = {
    record_id: invId,
    sales_invoice_id: invId,
    invoice_number: payload.invoice_number || invId,
    sales_order_id: String(payload.sales_order_id).trim(),
    invoice_date: payload.invoice_date || nowIso.slice(0, 10),
    customer_id: String(payload.customer_id).trim(),
    billing_gstin: payload.billing_gstin || '',
    place_of_supply: payload.place_of_supply || '',
    taxable_value: taxable,
    cgst_amount: cgst,
    sgst_amount: sgst,
    igst_amount: igst,
    total_tax: totalTax,
    invoice_total: invTotal,
    irn: payload.irn || '',
    e_way_bill_number: payload.e_way_bill_number || '',
    status: 'ISSUED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'SalesInvoices', invRecord, 'sales_invoice_id', ['sales_invoice_id', 'sales_order_id', 'invoice_total']);

  (payload.items || []).forEach((item, idx) => {
    const itemAlloc = ksAllocateId('SalesInvoiceItems', payload.nonce + '_INVI_' + (idx + 1));
    const lineRec = {
      record_id: itemAlloc.allocated_id,
      sales_invoice_item_id: itemAlloc.allocated_id,
      parent_record_id: invId,
      line_number: idx + 1,
      item_type: item.item_type || 'PACKAGED_SKU',
      item_id: String(item.item_id || '').trim(),
      description: String(item.description || '').trim(),
      quantity: Number(item.quantity) || 0,
      unit: item.unit || 'PKT',
      unit_rate: Number(item.unit_rate) || 0,
      tax_rate: Number(item.tax_rate) || 0,
      line_amount: Number(item.line_amount) || 0,
      status: 'ISSUED',
      created_at: nowIso,
      created_by: ctx.user_id,
      notes: item.notes || ''
    };
    ksAppendAndVerifyRow_(ss, 'SalesInvoiceItems', lineRec, 'sales_invoice_item_id', ['sales_invoice_item_id', 'parent_record_id']);
  });

  ksLogAudit_('SALES_INVOICE_ISSUED', 'SalesInvoices', invId, {
    actor_user_id: ctx.user_id,
    field_changed: 'invoice_total',
    new_value: String(invTotal),
    related_record_id: payload.sales_order_id
  });

  return { success: true, sales_invoice_id: invId, invoice_total: invTotal };
}

/**
 * Records a Customer Receipt and explicit Invoice Allocation (POL-006, REQ-020, REQ-065).
 */
function ksRecordCustomerReceiptAndAllocation(payload) {
  const ctx = ksRequireRole_(
    [KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.ACCOUNTS, KS_ROLES.FIELD_SALESMAN],
    'ksRecordCustomerReceiptAndAllocation'
  );

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.customer_id) throw new Error('customer_id is required.');
  const amountReceived = Number(payload.amount_received);
  if (!(amountReceived > 0)) throw new Error('amount_received must be > 0.');

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const rcptAlloc = ksAllocateId('CustomerPayments', payload.nonce + '_RCPT');
  const rcptId = rcptAlloc.allocated_id;

  const gatewayFee = Number(payload.gateway_fee) || 0;
  const netSettlement = Math.round((amountReceived - gatewayFee) * 100) / 100;

  const rcptRecord = {
    record_id: rcptId,
    customer_payment_id: rcptId,
    customer_id: String(payload.customer_id).trim(),
    sales_order_id: payload.sales_order_id || '',
    sales_invoice_id: payload.sales_invoice_id || '',
    payment_date: payload.payment_date || nowIso.slice(0, 10),
    payment_method_id: payload.payment_method_id || 'CASH',
    amount_received: amountReceived,
    transaction_reference: payload.transaction_reference || '',
    gateway_fee: gatewayFee,
    net_settlement: netSettlement,
    status: payload.status || 'COMPLETED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'CustomerPayments', rcptRecord, 'customer_payment_id', ['customer_payment_id', 'customer_id', 'amount_received']);

  let allocId = '';
  if (payload.sales_invoice_id) {
    const allocAmount = Number(payload.allocated_amount) || amountReceived;
    if (allocAmount > amountReceived) {
      throw new Error('Allocated amount (' + allocAmount + ') cannot exceed received amount (' + amountReceived + ').');
    }
    const aAlloc = ksAllocateId('CustomerPaymentAllocations', payload.nonce + '_RCPTA');
    allocId = aAlloc.allocated_id;

    const allocRecord = {
      record_id: allocId,
      customer_payment_allocation_id: allocId,
      party_type: 'CUSTOMER',
      party_id: String(payload.customer_id).trim(),
      reference_type: 'SALES_INVOICE',
      reference_id: String(payload.sales_invoice_id).trim(),
      transaction_date: rcptRecord.payment_date,
      payment_method: rcptRecord.payment_method_id,
      amount: allocAmount,
      reference_number: rcptId,
      recorded_by: ctx.user_id,
      status: 'ALLOCATED',
      created_at: nowIso,
      created_by: ctx.user_id,
      notes: payload.notes || ''
    };
    ksAppendAndVerifyRow_(ss, 'CustomerPaymentAllocations', allocRecord, 'customer_payment_allocation_id', ['customer_payment_allocation_id', 'reference_id', 'amount']);
  }

  ksLogAudit_('CUSTOMER_RECEIPT_RECORDED', 'CustomerPayments', rcptId, {
    actor_user_id: ctx.user_id,
    field_changed: 'amount_received',
    new_value: String(amountReceived),
    related_record_id: payload.sales_invoice_id || payload.sales_order_id || ''
  });

  return { success: true, customer_payment_id: rcptId, allocation_id: allocId, net_settlement: netSettlement };
}