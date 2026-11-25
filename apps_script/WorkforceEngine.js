/**
 * KAWAD SWAD ERP - WORKFORCE, ATTENDANCE, GIG-WORKER & FIXED-SALARY PAYROLL ENGINE
 * Blueprint Version: 2.0 | Enforces POL-003..004, POL-008, POL-011..013, DB-10, REQ-003, REQ-023, REQ-050..059
 * Supports both:
 *   1. GIG / PIECE-RATE / DAILY WORKERS (verified ProductionWorkerEntries -> payout)
 *   2. FIXED SALARIED EMPLOYEES (monthly/periodic salary + approved overtime - advance recovery -> payout)
 * Confidential salary/bank operations are strictly restricted to OWNER_ADMIN (POL-012).
 */

const KS_WORKFORCE_TABLES = Object.freeze([
  'Employees',
  'LeaveRecords',
  'ShiftSchedules',
  'OvertimeRecords',
  'IncentiveRules',
  'SalaryPayments',
  'EmployeeAdvances',
  'EmployeeGrievances',
  'TrainingRecords',
  'WorkplaceSafetyRecords',
  'ProductionWorkerEntries'
]);

function ksInspectWorkforceHeaders() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  Logger.log('=== SCHEMA INSPECTION: WORKFORCE (' + KS_WORKFORCE_TABLES.length + ' tables) ===');
  KS_WORKFORCE_TABLES.forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) {
      Logger.log('[MISSING TAB] ' + tabName);
      return;
    }
    const lastCol = sh.getLastColumn();
    const headers = lastCol > 0 ? sh.getRange(1, 1, 1, lastCol).getValues()[0] : [];
    Logger.log('[OK] ' + tabName + ' (rows=' + sh.getLastRow() + ', cols=' + lastCol + '): ' + JSON.stringify(headers));
  });
}

function ksHydrateWorkforceTables() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksHydrateWorkforceTables');
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dict = ksLoadDictionaryIndex_();
  let hydratedCount = 0;

  KS_WORKFORCE_TABLES.forEach(tabName => {
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
        reason: 'Hydrated ' + missing.length + ' workforce fields from ' + KS_DICTIONARY_TAB
      });
    }
  });

  SpreadsheetApp.flush();
  Logger.log('Hydrated ' + hydratedCount + ' workforce tables.');
  return hydratedCount;
}

/**
 * 1. Registers an Employee or Gig Worker in Employees (REQ-050, POL-012).
 * employment_type must be: FIXED_SALARIED | GIG_WORKER | DAILY_WAGE | CONTRACT
 */
function ksRegisterWorkerOrEmployee(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.HR], 'ksRegisterWorkerOrEmployee');

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.full_name || !payload.employment_type || !payload.designation) {
    throw new Error('full_name, employment_type, and designation are required (REQ-050).');
  }

  const empType = String(payload.employment_type).trim().toUpperCase();
  if (!['FIXED_SALARIED', 'GIG_WORKER', 'DAILY_WAGE', 'CONTRACT'].includes(empType)) {
    throw new Error('Invalid employment_type "' + empType + '". Use FIXED_SALARIED, GIG_WORKER, DAILY_WAGE, or CONTRACT.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const alloc = ksAllocateId('Employees', payload.nonce + '_EMP');
  const empId = alloc.allocated_id;

  const empRecord = {
    record_id: empId,
    employee_id: empId,
    employee_code: payload.employee_code || empId,
    full_name: String(payload.full_name).trim(),
    mobile: String(payload.mobile || '').trim(),
    email: String(payload.email || '').trim(),
    designation: String(payload.designation).trim(),
    department: String(payload.department || 'PRODUCTION').trim(),
    employment_type: empType,
    joining_date: payload.joining_date || nowIso.slice(0, 10),
    exit_date: '',
    employment_status: 'ACTIVE',
    reporting_manager_id: payload.reporting_manager_id || '',
    address: payload.address || '',
    emergency_contact: payload.emergency_contact || '',
    bank_details_reference: payload.bank_details_reference || '', // Store Drive/vault ref, never raw passwords/secrets (POL-012)
    active: true,
    status: 'ACTIVE',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'Employees', empRecord, 'employee_id', ['employee_id', 'full_name', 'employment_type']);

  ksLogAudit_('EMPLOYEE_REGISTERED', 'Employees', empId, {
    actor_user_id: ctx.user_id,
    field_changed: 'employment_type',
    new_value: empType + ' (' + empRecord.designation + ')'
  });

  return { success: true, employee_id: empId, employment_type: empType };
}

/**
 * 2. Records Gig / Piece-Rate / Daily Worker Activity (REQ-023, POL-013).
 * Starts as SUBMITTED unless verified_by supervisor is supplied.
 */
function ksRecordWorkerProductionEntry(payload) {
  const ctx = ksRequireRole_(
    [KS_ROLES.OWNER_ADMIN, KS_ROLES.PA, KS_ROLES.PRODUCTION, KS_ROLES.HR],
    'ksRecordWorkerProductionEntry'
  );

  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.production_batch_id || !payload.employee_id || !payload.work_date || !payload.task_type) {
    throw new Error('production_batch_id, employee_id, work_date, and task_type are required (REQ-023).');
  }

  const hoursWorked = Number(payload.hours_worked) || 0;
  const unitsCompleted = Number(payload.units_completed) || 0;
  if (hoursWorked <= 0 && unitsCompleted <= 0) {
    throw new Error('Either hours_worked or units_completed must be > 0 (POL-013).');
  }

  const rate = Number(payload.rate) || 0;
  const isPieceRate = (String(payload.pay_basis || '').toUpperCase() === 'PIECE' || (unitsCompleted > 0 && hoursWorked === 0));
  const basisQty = isPieceRate ? unitsCompleted : hoursWorked;
  const amount = Math.round(basisQty * rate * 100) / 100;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const alloc = ksAllocateId('ProductionWorkerEntries', payload.nonce + '_PWE');
  const entryId = alloc.allocated_id;

  const record = {
    record_id: entryId,
    worker_entry_id: entryId,
    production_batch_id: String(payload.production_batch_id).trim(),
    employee_id: String(payload.employee_id).trim(),
    work_date: payload.work_date,
    task_type: String(payload.task_type).trim(),
    hours_worked: hoursWorked,
    units_completed: unitsCompleted,
    rate: rate,
    amount: amount,
    verified_by: payload.verified_by || '',
    status: payload.verified_by ? 'VERIFIED' : 'SUBMITTED',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'ProductionWorkerEntries', record, 'worker_entry_id', [
    'worker_entry_id', 'production_batch_id', 'employee_id', 'work_date', 'task_type'
  ]);

  ksLogAudit_('WORKER_PRODUCTION_LOGGED', 'ProductionWorkerEntries', entryId, {
    actor_user_id: ctx.user_id,
    field_changed: 'task_type',
    new_value: record.task_type + ' (hrs=' + hoursWorked + ', units=' + unitsCompleted + ')',
    related_record_id: record.production_batch_id
  });

  return { success: true, worker_entry_id: entryId, calculated_amount: amount, status: record.status };
}

/**
 * 3. Supervisor Verification of Gig Worker Entry (Segregation of Duties: REQ-023 & POL-011).
 */
function ksVerifyWorkerProductionEntry(workerEntryId) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PRODUCTION], 'ksVerifyWorkerProductionEntry');
  if (!workerEntryId) throw new Error('workerEntryId is required.');

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName('ProductionWorkerEntries');
  const { headerMap } = ksGetHeaderMap_(sh, ['worker_entry_id', 'verified_by', 'status', 'updated_at', 'updated_by']);
  const lastRow = sh.getLastRow();
  if (lastRow < 2) throw new Error('No records in ProductionWorkerEntries.');

  const ids = sh.getRange(2, headerMap['worker_entry_id'], lastRow - 1, 1).getValues();
  for (let i = 0; i < ids.length; i++) {
    if (String(ids[i][0]).trim() === String(workerEntryId).trim()) {
      const rowNum = i + 2;
      const nowIso = ksNowIso_();
      sh.getRange(rowNum, headerMap['verified_by']).setValue(ctx.user_id);
      sh.getRange(rowNum, headerMap['status']).setValue('VERIFIED');
      sh.getRange(rowNum, headerMap['updated_at']).setValue(nowIso);
      sh.getRange(rowNum, headerMap['updated_by']).setValue(ctx.user_id);
      SpreadsheetApp.flush();

      ksLogAudit_('WORKER_ENTRY_VERIFIED', 'ProductionWorkerEntries', workerEntryId, {
        actor_user_id: ctx.user_id,
        field_changed: 'status',
        old_value: 'SUBMITTED',
        new_value: 'VERIFIED',
        approved_by_user_id: ctx.user_id
      });

      return { success: true, worker_entry_id: workerEntryId, verified_by: ctx.user_id, status: 'VERIFIED' };
    }
  }
  throw new Error('Worker entry "' + workerEntryId + '" not found.');
}

/**
 * 4. Records an Employee Advance / Loan Disbursement (REQ-056, POL-006).
 */
function ksRecordEmployeeAdvance(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.ACCOUNTS], 'ksRecordEmployeeAdvance');
  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.employee_id || !(Number(payload.amount) > 0)) {
    throw new Error('employee_id and positive advance amount are required.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const alloc = ksAllocateId('EmployeeAdvances', payload.nonce + '_EADV');
  const advId = alloc.allocated_id;
  const amt = Math.round(Number(payload.amount) * 100) / 100;

  const advRecord = {
    record_id: advId,
    employee_advance_id: advId,
    employee_id: String(payload.employee_id).trim(),
    period_start: payload.period_start || nowIso.slice(0, 10),
    period_end: payload.period_end || '',
    record_date: payload.record_date || nowIso.slice(0, 10),
    quantity_or_days: 1,
    amount: amt,
    approval_status: 'APPROVED',
    approved_by: ctx.user_id,
    payment_status: 'DISBURSED',
    status: 'OPEN_BALANCE',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: payload.notes || ''
  };

  ksAppendAndVerifyRow_(ss, 'EmployeeAdvances', advRecord, 'employee_advance_id', ['employee_advance_id', 'employee_id', 'amount']);

  // Post double-entry accounting voucher: Debit Employee Advances (Asset), Credit Cash/Bank
  ksPostBalancedJournalVoucher({
    nonce: payload.nonce + '_JV',
    reference_type: 'EMPLOYEE_ADVANCE',
    reference_id: advId,
    record_date: advRecord.record_date,
    description: 'Employee advance disbursed: ' + advId,
    lines: [
      { dr_cr: 'DEBIT', account_code: '1150-EMPLOYEE-ADVANCES', amount: amt, description: 'Advance ' + advId },
      { dr_cr: 'CREDIT', account_code: payload.payment_account || '1110-PETTY-CASH', amount: amt, description: 'Advance payout ' + advId }
    ]
  });

  return { success: true, employee_advance_id: advId, amount: amt };
}

/**
 * 5. Processes a Gig-Worker Payout from VERIFIED ProductionWorkerEntries (OWNER_ADMIN only per POL-012).
 * Marks settled entries as PAID so they can never be double-paid (REQ-081).
 */
function ksProcessGigWorkerPayout(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksProcessGigWorkerPayout');
  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.employee_id || !payload.period_start || !payload.period_end) {
    throw new Error('employee_id, period_start, and period_end are required.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const pweSheet = ss.getSheetByName('ProductionWorkerEntries');
  const { headerMap } = ksGetHeaderMap_(pweSheet, ['worker_entry_id', 'employee_id', 'work_date', 'amount', 'status', 'updated_at', 'updated_by']);
  const lastRow = pweSheet.getLastRow();
  if (lastRow < 2) throw new Error('No entries found in ProductionWorkerEntries.');

  const rows = pweSheet.getRange(2, 1, lastRow - 1, pweSheet.getLastColumn()).getValues();
  const matchedRows = [];
  let totalGrossPaise = 0;

  rows.forEach((r, idx) => {
    const emp = String(r[headerMap['employee_id'] - 1]).trim();
    const st = String(r[headerMap['status'] - 1]).trim().toUpperCase();
    const rawDate = r[headerMap['work_date'] - 1];
    const wDate = rawDate instanceof Date
      ? Utilities.formatDate(rawDate, KS_CONFIG.TIMEZONE, 'yyyy-MM-dd')
      : String(rawDate).slice(0, 10);

    // Strictly include ONLY supervisor-VERIFIED entries within the date window (REQ-023 & POL-011)
    if (emp === String(payload.employee_id).trim() && st === 'VERIFIED' && wDate >= payload.period_start && wDate <= payload.period_end) {
      const amt = Number(r[headerMap['amount'] - 1]) || 0;
      totalGrossPaise += Math.round(amt * 100);
      matchedRows.push({ rowNum: idx + 2, entryId: r[headerMap['worker_entry_id'] - 1] });
    }
  });

  if (matchedRows.length === 0 || totalGrossPaise <= 0) {
    throw new Error('No VERIFIED unpaid gig-worker entries found for ' + payload.employee_id + ' in period ' + payload.period_start + '..' + payload.period_end);
  }

  const advanceRecoveryPaise = Math.round((Number(payload.advance_recovery) || 0) * 100);
  if (advanceRecoveryPaise > totalGrossPaise) {
    throw new Error('Advance recovery cannot exceed gross gig earnings.');
  }

  const grossRupees = totalGrossPaise / 100;
  const recoveryRupees = advanceRecoveryPaise / 100;
  const netPayableRupees = (totalGrossPaise - advanceRecoveryPaise) / 100;

  const nowIso = ksNowIso_();
  const payDate = payload.payment_date || nowIso.slice(0, 10);
  const salAlloc = ksAllocateId('SalaryPayments', payload.nonce + '_GIGPAY');
  const payId = salAlloc.allocated_id;

  const payRecord = {
    record_id: payId,
    salary_payment_id: payId,
    party_type: 'GIG_WORKER',
    party_id: String(payload.employee_id).trim(),
    reference_type: 'GIG_PERIOD_' + payload.period_start + '_TO_' + payload.period_end,
    reference_id: matchedRows.map(m => m.entryId).join(','),
    transaction_date: payDate,
    payment_method: payload.payment_method || 'CASH',
    amount: netPayableRupees,
    reference_number: payload.reference_number || payId,
    recorded_by: ctx.user_id,
    status: 'PAID',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: 'Gross=' + grossRupees + ', AdvRecovery=' + recoveryRupees + ', Entries=' + matchedRows.length
  };

  ksAppendAndVerifyRow_(ss, 'SalaryPayments', payRecord, 'salary_payment_id', ['salary_payment_id', 'party_id', 'amount']);

  // Mark included ProductionWorkerEntries as PAID so they cannot be paid twice
  matchedRows.forEach(m => {
    pweSheet.getRange(m.rowNum, headerMap['status']).setValue('PAID');
    pweSheet.getRange(m.rowNum, headerMap['updated_at']).setValue(nowIso);
    pweSheet.getRange(m.rowNum, headerMap['updated_by']).setValue(ctx.user_id);
  });

  // Post balanced double-entry accounting lines
  const jvLines = [
    { dr_cr: 'DEBIT', account_code: '5120-DIRECT-PRODUCTION-LABOUR', amount: grossRupees, description: 'Gig labour payout ' + payId },
    { dr_cr: 'CREDIT', account_code: payload.payment_account || '1110-PETTY-CASH', amount: netPayableRupees, description: 'Net cash/bank paid ' + payId }
  ];
  if (recoveryRupees > 0) {
    jvLines.push({ dr_cr: 'CREDIT', account_code: '1150-EMPLOYEE-ADVANCES', amount: recoveryRupees, description: 'Advance recovery ' + payId });
  }

  const jv = ksPostBalancedJournalVoucher({
    nonce: payload.nonce + '_JV',
    reference_type: 'GIG_WAGE_PAYOUT',
    reference_id: payId,
    record_date: payDate,
    description: 'Gig worker payout ' + payId + ' (' + matchedRows.length + ' verified entries)',
    lines: jvLines
  });

  return {
    success: true,
    salary_payment_id: payId,
    party_type: 'GIG_WORKER',
    entries_settled: matchedRows.length,
    gross_amount: grossRupees,
    advance_recovery: recoveryRupees,
    net_paid: netPayableRupees,
    journal_voucher_id: jv.journal_voucher_id
  };
}

/**
 * 6. Processes a Fixed-Salary Employee Payroll Payout (OWNER_ADMIN only per POL-012).
 */
function ksProcessFixedEmployeeSalary(payload) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksProcessFixedEmployeeSalary');
  if (!payload || !payload.nonce) throw new Error('Idempotency nonce is required.');
  if (!payload.employee_id || !payload.salary_month) {
    throw new Error('employee_id and salary_month (e.g., 2026-11) are required.');
  }

  const baseSalary = Number(payload.base_salary) || 0;
  const overtimeAmt = Number(payload.overtime_amount) || 0;
  const incentiveAmt = Number(payload.incentive_amount) || 0;
  const unpaidLeaveDed = Number(payload.unpaid_leave_deduction) || 0;
  const advanceRecovery = Number(payload.advance_recovery) || 0;

  if (baseSalary <= 0) throw new Error('base_salary must be > 0.');

  const grossPaise = Math.round((baseSalary + overtimeAmt + incentiveAmt - unpaidLeaveDed) * 100);
  const recoveryPaise = Math.round(advanceRecovery * 100);
  if (grossPaise <= 0 || recoveryPaise > grossPaise) {
    throw new Error('Invalid net salary calculation: verify deductions and advance recovery.');
  }

  const grossRupees = grossPaise / 100;
  const recoveryRupees = recoveryPaise / 100;
  const netPaidRupees = (grossPaise - recoveryPaise) / 100;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nowIso = ksNowIso_();
  const payDate = payload.payment_date || nowIso.slice(0, 10);
  const salAlloc = ksAllocateId('SalaryPayments', payload.nonce + '_FIXPAY');
  const payId = salAlloc.allocated_id;

  const payRecord = {
    record_id: payId,
    salary_payment_id: payId,
    party_type: 'FIXED_EMPLOYEE',
    party_id: String(payload.employee_id).trim(),
    reference_type: 'MONTHLY_SALARY_' + payload.salary_month,
    reference_id: payload.salary_month,
    transaction_date: payDate,
    payment_method: payload.payment_method || 'BANK_TRANSFER',
    amount: netPaidRupees,
    reference_number: payload.reference_number || payId,
    recorded_by: ctx.user_id,
    status: 'PAID',
    created_at: nowIso,
    created_by: ctx.user_id,
    notes: 'Base=' + baseSalary + ', OT=' + overtimeAmt + ', Inc=' + incentiveAmt + ', LeaveDed=' + unpaidLeaveDed + ', AdvRec=' + recoveryRupees
  };

  ksAppendAndVerifyRow_(ss, 'SalaryPayments', payRecord, 'salary_payment_id', ['salary_payment_id', 'party_id', 'amount']);

  const expenseAcct = payload.department_expense_account || '5250-SALARIES-AND-WAGES';
  const jvLines = [
    { dr_cr: 'DEBIT', account_code: expenseAcct, amount: grossRupees, description: 'Monthly salary ' + payload.salary_month + ' (' + payId + ')' },
    { dr_cr: 'CREDIT', account_code: payload.payment_account || '1120-BANK-MAIN', amount: netPaidRupees, description: 'Net salary transfer ' + payId }
  ];
  if (recoveryRupees > 0) {
    jvLines.push({ dr_cr: 'CREDIT', account_code: '1150-EMPLOYEE-ADVANCES', amount: recoveryRupees, description: 'Advance recovery ' + payId });
  }

  const jv = ksPostBalancedJournalVoucher({
    nonce: payload.nonce + '_JV',
    reference_type: 'FIXED_SALARY_PAYOUT',
    reference_id: payId,
    record_date: payDate,
    description: 'Fixed employee salary ' + payload.salary_month + ' (' + payId + ')',
    lines: jvLines
  });

  return {
    success: true,
    salary_payment_id: payId,
    party_type: 'FIXED_EMPLOYEE',
    gross_salary: grossRupees,
    advance_recovery: recoveryRupees,
    net_paid: netPaidRupees,
    journal_voucher_id: jv.journal_voucher_id
  };
}

/**
 * End-to-End Phase G Verification Test for Both Gig Workers and Fixed Employees.
 */
function ksRunPhaseGWorkforceTest() {
  const today = ksNowIso_().slice(0, 10);

  // A. Test Gig Worker Flow: Register -> Log Piece-Rate Output -> Supervisor Verify -> Payout
  const gigEmp = ksRegisterWorkerOrEmployee({
    nonce: 'TEST_EMP_GIG_001',
    full_name: 'Ramesh Kumar (Rolling)',
    designation: 'Papad Roller',
    department: 'PRODUCTION',
    employment_type: 'GIG_WORKER'
  });

  const gigWork = ksRecordWorkerProductionEntry({
    nonce: 'TEST_PWE_001',
    production_batch_id: 'PO-20261118-00001',
    employee_id: gigEmp.employee_id,
    work_date: today,
    task_type: 'PAPAD_ROLLING',
    units_completed: 40,
    pay_basis: 'PIECE',
    rate: 15 // INR 15/kg -> INR 600
  });

  ksVerifyWorkerProductionEntry(gigWork.worker_entry_id);

  const gigPay = ksProcessGigWorkerPayout({
    nonce: 'TEST_GIGPAY_001',
    employee_id: gigEmp.employee_id,
    period_start: today,
    period_end: today,
    payment_method: 'CASH'
  });

  // B. Test Fixed Employee Flow: Register -> Advance -> Monthly Salary Payout with Advance Recovery
  const fixEmp = ksRegisterWorkerOrEmployee({
    nonce: 'TEST_EMP_FIX_001',
    full_name: 'Suresh Sharma',
    designation: 'Factory Supervisor',
    department: 'PRODUCTION',
    employment_type: 'FIXED_SALARIED'
  });

  ksRecordEmployeeAdvance({
    nonce: 'TEST_ADV_001',
    employee_id: fixEmp.employee_id,
    amount: 2000,
    notes: 'Mid-month cash advance'
  });

  const fixPay = ksProcessFixedEmployeeSalary({
    nonce: 'TEST_FIXPAY_001',
    employee_id: fixEmp.employee_id,
    salary_month: today.slice(0, 7),
    base_salary: 18000,
    overtime_amount: 1200,
    advance_recovery: 2000,
    payment_method: 'BANK_TRANSFER'
  });

  Logger.log('Phase G Workforce Test Passed (Gig + Fixed): ' + JSON.stringify({ gigPay: gigPay, fixPay: fixPay }));
}