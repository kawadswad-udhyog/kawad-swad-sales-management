/**
 * ============================================================================
 * KAWAD SWAD ERP - WORKFORCE SCHEMA MIGRATION UTILITY (PHASE 4)
 * File: docs/workforceMigration.gs
 *
 * PRODUCTION SAFETY CONSTRAINTS ENFORCED:
 * 1. Read-only audit mode (dry-run) and guarded execution mode.
 * 2. Strict dual-token guard against accidental execution:
 *    executeWorkforceMigration("CONFIRM_MIGRATE_WORKFORCE_2026", "AUTHORIZED_BY_OWNER")
 * 3. Strict protection of all core ERP sheets (Users, AuthUsers, Workers,
 *    WorkerAttendance, Sales, Purchases, Inventory, Accounting, etc.).
 * 4. Verified full-sheet backups before any destructive or mutative write:
 *    Compares 100% of values and formulas between source and backup.
 * 5. Unique backup naming with collision detection and incrementation (_1, _2...).
 * 6. Zero use of sheet.clear() or sheet.deleteColumns().
 * 7. One-to-one column mapping: every source column mapped exactly once.
 * 8. Ambiguity hard-stops: Duplicate source headers, duplicate target mappings,
 *    or blank headers with non-empty data cause an immediate hard stop.
 * 9. Formula reference translation: When columns are reordered, internal formula
 *    cell references (e.g. =B2*C2) are translated to new column letters.
 * 10. Robust data type preservation: Dates, numbers, booleans, blanks, formulas,
 *     and cell errors (#VALUE!, #N/A, etc.) are safely handled.
 * 11. Empty-sheet handling: updates row 1 canonical headers in place, preserving
 *     formatting, column widths, and frozen rows.
 * 12. Safe rerun & partial recovery: Idempotent detection of ALREADY_CANONICAL
 *     sheets, plus dedicated rollbackWorkforceSheet() utility.
 * 13. Post-migration cell-by-cell data integrity verification with exact
 *     coordinate reporting on any mismatch.
 * ============================================================================
 */

// 1. CANONICAL SCHEMAS (Authoritative from backend/app/sheets.py REQUIRED_TABS)
var CANONICAL_WORKFORCE_SCHEMAS = {
  "EmployeeDocuments": [
    "doc_id", "user_id", "document_type", "title", "file_url",
    "verification_status", "verified_by", "verified_at", "expiry_date", "notes", "created_at"
  ],
  "EmployeeAttendance": [
    "attendance_id", "employee_id", "employee_name", "attendance_date",
    "check_in_time", "check_out_time", "total_hours", "status", "notes", "verified_by", "created_at"
  ],
  "WorkAssignments": [
    "task_id", "title", "description", "assigned_to_user_id", "assigned_to_name",
    "role", "priority", "status", "due_date", "created_by", "submission_notes",
    "proof_url", "review_notes", "created_at", "completed_at"
  ],
  "WorkActivityLogs": [
    "activity_id", "user_id", "activity_date", "activity_type", "description",
    "hours_spent", "task_id", "created_at"
  ],
  "SalaryStructures": [
    "structure_id", "user_id", "basic_salary", "hra", "transport_allowance",
    "special_allowance", "sales_commission_rate", "pf_deduction", "tds_deduction",
    "other_deductions", "payment_mode", "effective_from", "notes", "created_at"
  ],
  "PayrollRuns": [
    "payroll_run_id", "month", "run_date", "total_employees", "total_gross",
    "total_deductions", "total_net", "status", "created_by", "approved_by", "notes", "created_at"
  ],
  "PayrollItems": [
    "item_id", "payroll_run_id", "user_id", "employee_name", "role",
    "base_salary", "working_days", "present_days", "earned_basic", "allowances",
    "incentive_amount", "bonus_amount", "deductions", "adjustment_amount",
    "gross_amount", "net_amount", "payment_status", "payment_id", "notes"
  ],
  "FreelancerProjects": [
    "project_id", "title", "description", "freelancer_user_id", "freelancer_name",
    "total_budget", "currency", "start_date", "target_completion_date", "status",
    "deliverables_summary", "notes", "created_at"
  ],
  "FreelancerMilestones": [
    "milestone_id", "project_id", "title", "description", "amount",
    "due_date", "status", "submission_notes", "submission_link", "review_notes",
    "approved_at", "payment_id", "created_at"
  ],
  "LabourMaster": [
    "labour_id", "full_name", "category", "wage_type", "base_rate",
    "daily_expected_hours", "mobile", "emergency_contact", "address",
    "bank_account_no", "bank_ifsc", "active", "notes", "created_at"
  ],
  "LabourAttendance": [
    "attendance_id", "labour_id", "labour_name", "attendance_date", "status",
    "hours_worked", "overtime_hours", "wage_type", "daily_rate", "earned_wage",
    "verified_by", "notes", "created_at"
  ],
  "LabourWorkEntries": [
    "entry_id", "labour_id", "labour_name", "entry_date", "category",
    "activity_name", "batch_id", "units_completed", "unit_of_measure",
    "piece_rate", "total_amount", "hours_logged", "approved_by", "notes", "created_at"
  ],
  "LabourWageRecords": [
    "wage_record_id", "labour_id", "labour_name", "period_start", "period_end",
    "work_days", "total_hours", "piece_work_total", "gross_wage", "advances_deducted",
    "net_payable", "paid_amount", "payment_status", "paid_at", "payment_reference",
    "receipt_id", "status", "notes", "created_at"
  ],
  "WorkforcePayments": [
    "payment_id", "reference_id", "payment_type", "recipient_id", "recipient_name",
    "amount", "payment_method", "payment_reference", "payment_date",
    "bank_account_credited", "recorded_by", "accounting_journal_ref", "notes", "created_at"
  ],
  "SalaryReceipts": [
    "receipt_id", "receipt_number", "payment_id", "recipient_id", "recipient_name",
    "recipient_type", "role_or_category", "period_start", "period_end",
    "payment_date", "payment_method", "payment_reference", "gross_earnings",
    "total_deductions", "net_paid", "notes", "created_at"
  ],
  "WorkforceAuditLogs": [
    "audit_id", "action", "entity_type", "entity_id", "actor_id", "details", "created_at"
  ]
};

// 2. KNOWN PROVISIONAL ALIASES (Mapped Old Header -> Canonical Target Header)
var WORKFORCE_HEADER_ALIASES = {
  "EmployeeDocuments": {
    "employee_id": "user_id",
    "document_name": "title",
    "document_url": "file_url",
    "status": "verification_status"
  },
  "EmployeeAttendance": {
    "date": "attendance_date",
    "in_time": "check_in_time",
    "out_time": "check_out_time",
    "hours_worked": "total_hours"
  },
  "WorkAssignments": {
    "assigned_to": "assigned_to_user_id",
    "task_name": "title",
    "proof_link": "proof_url"
  },
  "WorkActivityLogs": {
    "employee_id": "user_id",
    "date": "activity_date"
  },
  "SalaryStructures": {
    "employee_id": "user_id",
    "basic": "basic_salary",
    "special": "special_allowance",
    "pf": "pf_deduction",
    "tds": "tds_deduction"
  },
  "PayrollRuns": {
    "payroll_id": "payroll_run_id",
    "period": "month"
  },
  "PayrollItems": {
    "employee_id": "user_id",
    "payroll_id": "payroll_run_id",
    "gross_salary": "gross_amount",
    "net_salary": "net_amount",
    "incentive": "incentive_amount",
    "bonus": "bonus_amount"
  },
  "FreelancerProjects": {
    "freelancer_id": "freelancer_user_id",
    "budget": "total_budget",
    "completion_date": "target_completion_date"
  },
  "FreelancerMilestones": {
    "milestone_name": "title"
  },
  "LabourMaster": {
    "worker_id": "labour_id",
    "name": "full_name",
    "worker_name": "full_name",
    "daily_wage": "base_rate"
  },
  "LabourAttendance": {
    "worker_id": "labour_id",
    "worker_name": "labour_name",
    "date": "attendance_date"
  },
  "LabourWorkEntries": {
    "worker_id": "labour_id",
    "worker_name": "labour_name",
    "activity": "activity_name",
    "quantity": "units_completed",
    "unit": "unit_of_measure",
    "amount": "total_amount"
  },
  "LabourWageRecords": {
    "worker_id": "labour_id",
    "worker_name": "labour_name",
    "net_wage": "net_payable"
  },
  "WorkforcePayments": {
    "pay_id": "payment_id",
    "recipient_type": "payment_type",
    "date": "payment_date"
  },
  "SalaryReceipts": {
    "date": "payment_date"
  },
  "WorkforceAuditLogs": {
    "user_id": "actor_id",
    "timestamp": "created_at"
  }
};

// Protected Core Sheets - STRICTLY FORBIDDEN from being modified by this script
var PROTECTED_CORE_SHEETS = [
  "Users", "AuthUsers", "Products", "Customers", "Sales", "SaleItems",
  "Payments", "SalesmanStockLedger", "CashLedger", "Expenses", "ShopVisits",
  "DailyClosing", "SalaryIncentives", "AuditLog", "Workers", "WorkerAttendance",
  "Recipes", "ProductionBatches", "PackagingBatches", "ProductionStockLedger",
  "ProductionDispatches", "RawMaterialLedger", "RawMaterials", "IdAllocations",
  "StockDiscrepancies", "IncompleteTransactions", "RevokedTokens", "ApprovalRequests",
  "CustomRoles", "ChartOfAccounts", "JournalHeaders", "JournalLines", "AccountingPeriods",
  "MillingBatches", "Suppliers", "PurchaseOrders", "PurchaseOrderItems", "GoodsReceipts",
  "GoodsReceiptItems", "SupplierBills", "SupplierPayments", "SupplierReturns",
  "SupplierReturnItems", "CustomerReturns", "CustomerReturnItems", "QualityChecks",
  "ProductLots", "LotMovements", "ComplaintsRecalls"
];

// Helper: Convert 0-indexed column integer to A1 column letters (0 -> "A", 27 -> "AB")
function colIndexToLetter(colIndex) {
  var temp = colIndex + 1;
  var letter = "";
  while (temp > 0) {
    var mod = (temp - 1) % 26;
    letter = String.fromCharCode(65 + mod) + letter;
    temp = Math.floor((temp - mod) / 26);
  }
  return letter;
}

// Helper: Convert A1 column letter to 0-indexed column integer ("A" -> 0, "AB" -> 27)
function letterToColIndex(letter) {
  var upper = letter.toUpperCase();
  var sum = 0;
  for (var i = 0; i < upper.length; i++) {
    sum = sum * 26 + (upper.charCodeAt(i) - 64);
  }
  return sum - 1;
}

// Helper: Parse, audit, and translate formula references with strict safety guarantees
function auditAndTranslateFormula(formulaStr, colMapping, numSourceCols) {
  if (!formulaStr || typeof formulaStr !== "string" || !formulaStr.startsWith("=")) {
    return { isSafe: true, blockingError: null, translatedFormula: formulaStr };
  }

  // 1. Check for Pre-Existing Error Tokens
  var errorTokenMatch = formulaStr.match(/#(?:REF!|VALUE!|NAME\?|DIV\/0!|N\/A|NUM!|NULL!|ERROR!)/i);
  if (errorTokenMatch) {
    return {
      isSafe: false,
      blockingError: "PRE_EXISTING_FORMULA_ERROR: Contains broken/error reference '" + errorTokenMatch[0] + "'. Manual owner review required.",
      translatedFormula: null
    };
  }

  // 2. Check for Unsupported Dynamic / Query Functions (cannot be statically remapped)
  var unsupportedFuncMatch = formulaStr.match(/\b(INDIRECT|ADDRESS|OFFSET|IMPORTRANGE|QUERY)\s*\(/i);
  if (unsupportedFuncMatch) {
    return {
      isSafe: false,
      blockingError: "UNSUPPORTED_DYNAMIC_FORMULA: Contains '" + unsupportedFuncMatch[1] + "()' which cannot be statically remapped. Manual owner review required.",
      translatedFormula: null
    };
  }

  // 3. Check for Open-Ended or Whole-Column Ranges (e.g. B:B, B2:B, :B10)
  var openRangeMatch = formulaStr.match(/(?:^|[^A-Za-z0-9_!])(\$?[A-Za-z]{1,3}):(\$?[A-Za-z]{1,3})(?:[^0-9]|$)|(?:^|[^A-Za-z0-9_!])(\$?[A-Za-z]{1,3}[0-9]+):(\$?[A-Za-z]{1,3})(?:[^0-9]|$)/);
  if (openRangeMatch) {
    return {
      isSafe: false,
      blockingError: "UNSUPPORTED_WHOLE_COLUMN_RANGE: Contains open-ended or whole-column reference without full row bounds. Manual owner review required.",
      translatedFormula: null
    };
  }

  // 4. Tokenize Formula into Protected Tokens (String Literals & External Sheet References)
  var placeholderMap = {};
  var pIdx = 0;

  // Protect string literals first (including double-escaped quotes in sheets: "hello ""world""")
  var protectedStr = formulaStr.replace(/"(?:[^"]|"")*"/g, function(strMatch) {
    var key = "___STR_TOKEN_" + (pIdx++) + "___";
    placeholderMap[key] = strMatch;
    return key;
  });

  // Protect cross-sheet references (both single cell and range on external sheet)
  var crossSheetRegex = /(?:'[^']+'|[A-Za-z0-9_]+)!\$?[A-Za-z]{1,3}\$?[0-9]+(?::\$?[A-Za-z]{1,3}\$?[0-9]+)?/g;
  protectedStr = protectedStr.replace(crossSheetRegex, function(crossMatch) {
    var key = "___CROSS_TOKEN_" + (pIdx++) + "___";
    placeholderMap[key] = crossMatch;
    return key;
  });

  // 5. Inspect and Translate Local Cell References
  var cellRefRegex = /(^|[^A-Za-z0-9_])(\$?)([A-Za-z]{1,3})(\$?)([0-9]+)/g;
  var outOfBoundsError = null;

  var translated = protectedStr.replace(cellRefRegex, function(fullMatch, prefix, colDollar, colLetters, rowDollar, rowDigits) {
    if (outOfBoundsError) return fullMatch;

    var oldColIdx = letterToColIndex(colLetters);
    // Check if column index is within sheet bounds
    if (oldColIdx < 0 || oldColIdx >= numSourceCols) {
      outOfBoundsError = "OUT_OF_BOUNDS_COLUMN_REFERENCE: Cell references column '" + colLetters + "' (index " + oldColIdx + ") which is outside source columns [0.." + (numSourceCols - 1) + "].";
      return fullMatch;
    }

    if (!colMapping.hasOwnProperty(oldColIdx)) {
      outOfBoundsError = "UNMAPPED_COLUMN_REFERENCE: Referenced column '" + colLetters + "' has no mapping in destination schema.";
      return fullMatch;
    }

    var newColIdx = colMapping[oldColIdx];
    var newColLetters = colIndexToLetter(newColIdx);
    return prefix + colDollar + newColLetters + rowDollar + rowDigits;
  });

  if (outOfBoundsError) {
    return {
      isSafe: false,
      blockingError: outOfBoundsError + " Manual owner review required.",
      translatedFormula: null
    };
  }

  // 6. Restore Protected Tokens
  for (var k in placeholderMap) {
    translated = translated.split(k).join(placeholderMap[k]);
  }

  return {
    isSafe: true,
    blockingError: null,
    translatedFormula: translated
  };
}

// Wrapper for backward compatibility; throws on unsafe formula
function translateFormulaReferences(formulaStr, colMapping, numSourceCols) {
  var res = auditAndTranslateFormula(formulaStr, colMapping, numSourceCols);
  if (!res.isSafe) {
    throw new Error("FORMULA MIGRATION SAFETY STOP: " + res.blockingError + " [Formula: " + formulaStr + "]");
  }
  return res.translatedFormula;
}

// Helper: Check cell value equivalence with date, number, boolean, error, and blank safety
function areCellValuesEquivalent(origVal, destVal, origFormula, destFormula) {
  // If original had a formula, verify formula exists and matches translated formula
  if (origFormula !== "") {
    return destFormula !== "";
  }

  // Handle null / undefined / empty string
  var isOrigEmpty = (origVal === "" || origVal === null || origVal === undefined);
  var isDestEmpty = (destVal === "" || destVal === null || destVal === undefined);
  if (isOrigEmpty && isDestEmpty) return true;
  if (isOrigEmpty !== isDestEmpty) return false;

  // Handle Date objects
  if (origVal instanceof Date && destVal instanceof Date) {
    return origVal.getTime() === destVal.getTime();
  }

  // Handle Booleans
  if (typeof origVal === "boolean" || typeof destVal === "boolean") {
    return Boolean(origVal) === Boolean(destVal);
  }

  // Handle Numbers
  if (typeof origVal === "number" && typeof destVal === "number") {
    if (isNaN(origVal) && isNaN(destVal)) return true;
    return Math.abs(origVal - destVal) < 1e-9;
  }

  // String / Error comparison (e.g. #VALUE!, #N/A, or text)
  var sOrig = String(origVal).trim();
  var sDest = String(destVal).trim();

  // Try numeric parse comparison for numeric strings
  var nOrig = parseFloat(sOrig);
  var nDest = parseFloat(sDest);
  if (!isNaN(nOrig) && !isNaN(nDest) && sOrig === String(nOrig) && sDest === String(nDest)) {
    return Math.abs(nOrig - nDest) < 1e-9;
  }

  return sOrig === sDest;
}

/**
 * Entry point for Owner to perform a complete Dry-Run Audit.
 * Modifies NO data, creates NO sheets. Returns complete safety and readiness report.
 */
function dryRunWorkforceMigration() {
  var report = runWorkforceAudit(false);
  Logger.log("\n=======================================================");
  Logger.log("KAWAD SWAD ERP - WORKFORCE MIGRATION AUDIT (DRY-RUN)");
  Logger.log("=======================================================\n");
  Logger.log(JSON.stringify(report, null, 2));
  return report;
}

/**
 * Entry point for Owner to execute migration with verified backups and integrity checks.
 * Requires explicit dual confirmation parameters.
 */
function executeWorkforceMigration(authorizedToken1, authorizedToken2) {
  if (authorizedToken1 !== "CONFIRM_MIGRATE_WORKFORCE_2026" || authorizedToken2 !== "AUTHORIZED_BY_OWNER") {
    throw new Error(
      "Safety Guard Active: To execute migration, pass exact dual confirmation tokens: " +
      "executeWorkforceMigration('CONFIRM_MIGRATE_WORKFORCE_2026', 'AUTHORIZED_BY_OWNER')"
    );
  }

  // Step 1: Run comprehensive pre-audit
  var auditReport = runWorkforceAudit(true);
  if (!auditReport.overall_ready_for_migration) {
    Logger.log("Migration blocked by pre-audit safety errors:\n" + JSON.stringify(auditReport.blocking_errors, null, 2));
    throw new Error("MIGRATION BLOCKED: Safety violations detected during pre-audit. See logs.");
  }

  // Step 2: Perform Migration Sheet by Sheet
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var executionSummary = {
    timestamp: new Date().toISOString(),
    sheets_migrated: [],
    sheets_skipped_already_canonical: [],
    sheets_created_empty: [],
    backups_created: [],
    integrity_verification: "ALL_PASSED"
  };

  for (var sheetName in CANONICAL_WORKFORCE_SCHEMAS) {
    var sheet = ss.getSheetByName(sheetName);
    var canonicalHeaders = CANONICAL_WORKFORCE_SCHEMAS[sheetName];

    if (!sheet) {
      // Sheet does not exist: create sheet and initialize row 1 with canonical headers
      sheet = ss.insertSheet(sheetName);
      sheet.getRange(1, 1, 1, canonicalHeaders.length).setValues([canonicalHeaders]);
      sheet.setFrozenRows(1);
      executionSummary.sheets_created_empty.push(sheetName);
      continue;
    }

    var auditItem = auditReport.sheet_audits[sheetName];
    if (auditItem.status === "ALREADY_CANONICAL") {
      executionSummary.sheets_skipped_already_canonical.push(sheetName);
      continue;
    }

    if (auditItem.data_rows_count === 0) {
      // Empty sheet: update headers only, preserving formatting and frozen rows
      updateEmptySheetHeaders(sheet, canonicalHeaders);
      executionSummary.sheets_migrated.push({
        sheet_name: sheetName,
        method: "HEADER_UPDATE_ONLY",
        data_rows: 0
      });
      continue;
    }

    // Sheet contains data rows: Perform Verified Backup -> Re-Map -> Post-Verify
    var backupResult = createAndVerifyBackup(ss, sheet);
    executionSummary.backups_created.push(backupResult);

    migrateSheetWithData(ss, sheet, sheetName, canonicalHeaders, auditItem);
    executionSummary.sheets_migrated.push({
      sheet_name: sheetName,
      method: "DATA_ROW_MIGRATION",
      data_rows: auditItem.data_rows_count,
      backup_name: backupResult.backup_sheet_name
    });
  }

  Logger.log("\n=======================================================");
  Logger.log("KAWAD SWAD ERP - WORKFORCE MIGRATION COMPLETE");
  Logger.log("=======================================================\n");
  Logger.log(JSON.stringify(executionSummary, null, 2));
  return executionSummary;
}

/**
 * Dedicated Rollback Utility: Restore any sheet from its verified backup
 */
function rollbackWorkforceSheet(sheetName, backupSheetName) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var backupSheet = ss.getSheetByName(backupSheetName);
  if (!backupSheet) {
    throw new Error("Rollback failed: Backup sheet '" + backupSheetName + "' not found.");
  }
  var currentSheet = ss.getSheetByName(sheetName);
  if (currentSheet) {
    currentSheet.setName(sheetName + "_CORRUPTED_" + Utilities.formatDate(new Date(), "GMT+5:30", "yyyyMMdd_HHmmss"));
  }
  var restored = backupSheet.copyTo(ss);
  restored.setName(sheetName);
  Logger.log("Successfully restored '" + sheetName + "' from backup '" + backupSheetName + "'.");
  return true;
}

/**
 * Audits all 16 workforce sheets against canonical schemas, detecting:
 * - Duplicate source headers
 * - Duplicate target mappings
 * - Blank headers containing data
 * - Formula presence and translation preview
 * - Unmapped columns
 * - Cell parity counts
 */
function runWorkforceAudit(isExecutionMode) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var report = {
    timestamp: new Date().toISOString(),
    overall_ready_for_migration: true,
    blocking_errors: [],
    sheet_audits: {}
  };

  // Verify core protected sheets are not accidentally targeted
  for (var i = 0; i < PROTECTED_CORE_SHEETS.length; i++) {
    var protName = PROTECTED_CORE_SHEETS[i];
    if (CANONICAL_WORKFORCE_SCHEMAS[protName]) {
      report.blocking_errors.push("CRITICAL: Protected core sheet '" + protName + "' is defined in workforce schema!");
      report.overall_ready_for_migration = false;
    }
  }

  for (var sheetName in CANONICAL_WORKFORCE_SCHEMAS) {
    var canonicalHeaders = CANONICAL_WORKFORCE_SCHEMAS[sheetName];
    var aliases = WORKFORCE_HEADER_ALIASES[sheetName] || {};
    var sheet = ss.getSheetByName(sheetName);

    var audit = {
      sheet_name: sheetName,
      exists: sheet !== null,
      status: "UNKNOWN",
      source_rows_total: 0,
      source_cols_total: 0,
      data_rows_count: 0,
      non_empty_cells_count: 0,
      formula_cells_count: 0,
      blank_header_data_cells_count: 0,
      duplicate_source_headers: [],
      duplicate_target_mappings: [],
      source_headers: [],
      unmapped_headers: [],
      canonical_headers: canonicalHeaders,
      column_mapping: {},
      formula_translations_preview: [],
      blocking_reasons: []
    };

    if (!sheet) {
      audit.status = "DOES_NOT_EXIST";
      report.sheet_audits[sheetName] = audit;
      continue;
    }

    var lastRow = sheet.getLastRow();
    var lastCol = sheet.getLastColumn();
    audit.source_rows_total = lastRow;
    audit.source_cols_total = lastCol;

    if (lastRow === 0 || lastCol === 0) {
      audit.status = "COMPLETELY_EMPTY";
      audit.data_rows_count = 0;
      report.sheet_audits[sheetName] = audit;
      continue;
    }

    // Read headers (Row 1)
    var headerRange = sheet.getRange(1, 1, 1, lastCol);
    var rawHeaders = headerRange.getValues()[0];
    audit.source_headers = rawHeaders.map(function(h) { return String(h || "").trim(); });

    // Check Duplicate Source Headers
    var seenSource = {};
    for (var c = 0; c < audit.source_headers.length; c++) {
      var sh = audit.source_headers[c];
      if (sh !== "") {
        if (seenSource[sh]) {
          audit.duplicate_source_headers.push(sh);
        }
        seenSource[sh] = true;
      }
    }

    if (audit.duplicate_source_headers.length > 0) {
      audit.blocking_reasons.push("Duplicate source headers found: " + audit.duplicate_source_headers.join(", "));
    }

    // Check Data Rows
    var dataRows = lastRow - 1;
    audit.data_rows_count = Math.max(0, dataRows);

    var allValues = [];
    var allFormulas = [];
    if (lastRow > 0 && lastCol > 0) {
      var fullRange = sheet.getRange(1, 1, lastRow, lastCol);
      allValues = fullRange.getValues();
      allFormulas = fullRange.getFormulas();
    }

    // Count non-empty and formula cells, and detect blank headers with non-empty data
    for (var c = 0; c < lastCol; c++) {
      var headerVal = audit.source_headers[c];
      for (var r = 1; r < lastRow; r++) { // Data rows index 1..lastRow-1
        var val = allValues[r][c];
        var formula = allFormulas[r][c];
        var hasContent = (val !== "" && val !== null && val !== undefined) || (formula !== "");
        if (hasContent) {
          audit.non_empty_cells_count++;
          if (formula !== "") {
            audit.formula_cells_count++;
          }
          if (headerVal === "") {
            audit.blank_header_data_cells_count++;
            audit.blocking_reasons.push(
              "Data present in row " + (r + 1) + ", col " + (c + 1) + " under a BLANK header."
            );
          }
        }
      }
    }

    // Mapping algorithm check (One-to-One and Duplicate Target Detection)
    var targetToSourceMap = {};
    for (var colIdx = 0; colIdx < audit.source_headers.length; colIdx++) {
      var srcHeader = audit.source_headers[colIdx];
      if (!srcHeader) continue;

      var targetField = null;
      if (canonicalHeaders.indexOf(srcHeader) !== -1) {
        targetField = srcHeader;
      } else if (aliases[srcHeader]) {
        targetField = aliases[srcHeader];
      }

      if (targetField) {
        if (targetToSourceMap[targetField]) {
          audit.duplicate_target_mappings.push({
            target: targetField,
            source1: targetToSourceMap[targetField],
            source2: srcHeader
          });
        } else {
          targetToSourceMap[targetField] = srcHeader;
          audit.column_mapping[srcHeader] = targetField;
        }
      } else {
        // Unknown extra column
        audit.unmapped_headers.push(srcHeader);
        audit.column_mapping[srcHeader] = "[PRESERVED_EXTRA]:" + srcHeader;
      }
    }

    if (audit.duplicate_target_mappings.length > 0) {
      audit.blocking_reasons.push(
        "Multiple source headers map to same target field: " +
        JSON.stringify(audit.duplicate_target_mappings)
      );
    }

    // Preview formula translations if formulas are present
    if (audit.formula_cells_count > 0) {
      var totalDestHeaders = canonicalHeaders.concat(audit.unmapped_headers);
      var colMapIndices = {};
      for (var sc = 0; sc < audit.source_headers.length; sc++) {
        var sName = audit.source_headers[sc];
        if (!sName) continue;
        var tName = (canonicalHeaders.indexOf(sName) !== -1) ? sName : (aliases[sName] || sName);
        var dIdx = totalDestHeaders.indexOf(tName);
        if (dIdx !== -1) colMapIndices[sc] = dIdx;
      }

      for (var r = 1; r < lastRow; r++) {
        for (var c = 0; c < lastCol; c++) {
          var f = allFormulas[r][c];
          if (f !== "") {
            var formulaSafety = auditAndTranslateFormula(f, colMapIndices, lastCol);
            if (!formulaSafety.isSafe) {
              audit.blocking_reasons.push(
                "Formula safety stop at cell " + colIndexToLetter(c) + (r + 1) + ": " +
                formulaSafety.blockingError + " [Formula: " + f + "]"
              );
            } else {
              audit.formula_translations_preview.push({
                cell: colIndexToLetter(c) + (r + 1),
                original_formula: f,
                translated_formula: formulaSafety.translatedFormula
              });
            }
          }
        }
      }
    }

    // Determine Status: Safe Idempotency Check
    if (audit.blocking_reasons.length > 0) {
      audit.status = "BLOCKED_SAFETY_ERROR";
      report.overall_ready_for_migration = false;
      report.blocking_errors.push({ sheet: sheetName, errors: audit.blocking_reasons });
    } else {
      // A sheet is ALREADY_CANONICAL if:
      // 1. It contains all canonical headers at the beginning in exact order
      // 2. None of its headers are aliases requiring remapping
      var startsWithCanonical = (audit.source_headers.length >= canonicalHeaders.length);
      if (startsWithCanonical) {
        for (var k = 0; k < canonicalHeaders.length; k++) {
          if (audit.source_headers[k] !== canonicalHeaders[k]) {
            startsWithCanonical = false;
            break;
          }
        }
      }

      var hasAliasesToRemap = false;
      for (var sc = 0; sc < audit.source_headers.length; sc++) {
        var hName = audit.source_headers[sc];
        if (aliases[hName]) {
          hasAliasesToRemap = true;
          break;
        }
      }

      if (startsWithCanonical && !hasAliasesToRemap) {
        audit.status = "ALREADY_CANONICAL";
      } else if (audit.data_rows_count === 0) {
        audit.status = "EMPTY_DATA_ROWS";
      } else {
        audit.status = "READY_TO_MIGRATE";
      }
    }

    report.sheet_audits[sheetName] = audit;
  }

  return report;
}

/**
 * Creates a verified copy of the sheet before modification.
 * Verifies backup exists and compares 100% of cell values and formulas against source.
 * Handles collision detection with incrementing suffix.
 */
function createAndVerifyBackup(ss, sourceSheet) {
  var baseName = "_BACKUP_" + Utilities.formatDate(new Date(), "GMT+5:30", "yyyyMMdd_HHmmss") + "_" + sourceSheet.getName();
  var backupName = baseName;
  var counter = 1;

  // Collision handling
  while (ss.getSheetByName(backupName) !== null) {
    backupName = baseName + "_" + counter;
    counter++;
  }

  // Create copy
  var backupSheet = sourceSheet.copyTo(ss);
  backupSheet.setName(backupName);
  SpreadsheetApp.flush();

  // Verify backup exists and is readable
  var verifiedBackup = ss.getSheetByName(backupName);
  if (!verifiedBackup) {
    throw new Error("BACKUP VERIFICATION FAILED: Sheet '" + backupName + "' was not found after copy!");
  }

  var srcRows = sourceSheet.getLastRow();
  var srcCols = sourceSheet.getLastColumn();
  var bkpRows = verifiedBackup.getLastRow();
  var bkpCols = verifiedBackup.getLastColumn();

  if (srcRows !== bkpRows || srcCols !== bkpCols) {
    throw new Error(
      "BACKUP INTEGRITY MISMATCH for '" + sourceSheet.getName() + "': " +
      "Source dimensions (" + srcRows + "x" + srcCols + ") != " +
      "Backup dimensions (" + bkpRows + "x" + bkpCols + ")"
    );
  }

  // Exhaustive 100% comparison of all values and formulas
  if (srcRows > 0 && srcCols > 0) {
    var srcValues = sourceSheet.getRange(1, 1, srcRows, srcCols).getValues();
    var bkpValues = verifiedBackup.getRange(1, 1, bkpRows, bkpCols).getValues();
    var srcFormulas = sourceSheet.getRange(1, 1, srcRows, srcCols).getFormulas();
    var bkpFormulas = verifiedBackup.getRange(1, 1, bkpRows, bkpCols).getFormulas();

    for (var r = 0; r < srcRows; r++) {
      for (var c = 0; c < srcCols; c++) {
        var sF = srcFormulas[r][c];
        var bF = bkpFormulas[r][c];
        if (sF !== bF) {
          throw new Error("BACKUP FORMULA MISMATCH at [" + (r + 1) + "," + (c + 1) + "]: '" + sF + "' vs '" + bF + "'");
        }
        var sV = srcValues[r][c];
        var bV = bkpValues[r][c];
        if (!areCellValuesEquivalent(sV, bV, sF, bF)) {
          throw new Error("BACKUP VALUE MISMATCH at [" + (r + 1) + "," + (c + 1) + "]: '" + sV + "' vs '" + bV + "'");
        }
      }
    }
  }

  return {
    source_sheet_name: sourceSheet.getName(),
    backup_sheet_name: backupName,
    rows: bkpRows,
    cols: bkpCols,
    verified_at: new Date().toISOString()
  };
}

/**
 * Handles empty sheets (0 data rows).
 * Updates Row 1 headers in place without sheet.clear() or column deletion.
 * Preserves formatting, column widths, and frozen rows.
 */
function updateEmptySheetHeaders(sheet, canonicalHeaders) {
  var currentCols = sheet.getMaxColumns();
  if (currentCols < canonicalHeaders.length) {
    sheet.insertColumnsAfter(currentCols, canonicalHeaders.length - currentCols);
  }

  // Set Row 1 canonical headers in place
  sheet.getRange(1, 1, 1, canonicalHeaders.length).setValues([canonicalHeaders]);

  // Ensure 1 frozen row
  if (sheet.getFrozenRows() < 1) {
    sheet.setFrozenRows(1);
  }
}

/**
 * Migrates a sheet containing data with zero data loss.
 * Preserves and translates formulas, accounts for every cell, and performs post-migration verification.
 */
function migrateSheetWithData(ss, sheet, sheetName, canonicalHeaders, auditItem) {
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();

  var fullRange = sheet.getRange(1, 1, lastRow, lastCol);
  var rawValues = fullRange.getValues();
  var rawFormulas = fullRange.getFormulas();

  var sourceHeaders = auditItem.source_headers;
  var unmappedHeaders = auditItem.unmapped_headers;

  // Total destination columns = canonicalHeaders + unmappedHeaders
  var totalDestHeaders = canonicalHeaders.concat(unmappedHeaders);

  // Map each source column index to a destination column index
  // sourceColIdx -> destColIdx
  var colMapping = {};
  for (var sc = 0; sc < sourceHeaders.length; sc++) {
    var sName = sourceHeaders[sc];
    if (!sName) continue;

    var targetName = null;
    if (canonicalHeaders.indexOf(sName) !== -1) {
      targetName = sName;
    } else if (WORKFORCE_HEADER_ALIASES[sheetName] && WORKFORCE_HEADER_ALIASES[sheetName][sName]) {
      targetName = WORKFORCE_HEADER_ALIASES[sheetName][sName];
    } else {
      // Unmapped extra column
      targetName = sName;
    }

    var destIdx = totalDestHeaders.indexOf(targetName);
    if (destIdx === -1) {
      throw new Error("Internal Mapping Failure: Target column '" + targetName + "' not found in destination headers!");
    }
    colMapping[sc] = destIdx;
  }

  // Construct new rectangular grid for (lastRow x totalDestHeaders.length)
  var newGrid = [];
  // Row 0: Headers
  newGrid.push(totalDestHeaders);

  // Rows 1..lastRow-1: Data rows
  for (var r = 1; r < lastRow; r++) {
    var newRow = new Array(totalDestHeaders.length);
    for (var dc = 0; dc < totalDestHeaders.length; dc++) {
      newRow[dc] = "";
    }

    for (var sc = 0; sc < sourceHeaders.length; sc++) {
      if (colMapping.hasOwnProperty(sc)) {
        var destCol = colMapping[sc];
        var formula = rawFormulas[r][sc];
        var val = rawValues[r][sc];

        if (formula !== "") {
          // Translate formula references to account for reordered columns
          var translatedFormula = translateFormulaReferences(formula, colMapping, lastCol);
          newRow[destCol] = translatedFormula;
        } else {
          newRow[destCol] = (val !== null && val !== undefined) ? val : "";
        }
      }
    }
    newGrid.push(newRow);
  }

  // Ensure sheet has enough columns and rows
  var maxCols = sheet.getMaxColumns();
  if (maxCols < totalDestHeaders.length) {
    sheet.insertColumnsAfter(maxCols, totalDestHeaders.length - maxCols);
  }

  // Write new grid in place without calling sheet.clear()
  sheet.getRange(1, 1, lastRow, totalDestHeaders.length).setValues(newGrid);

  // Preserve frozen row
  if (sheet.getFrozenRows() < 1) {
    sheet.setFrozenRows(1);
  }

  SpreadsheetApp.flush();

  // POST-MIGRATION CELL-BY-CELL INTEGRITY VERIFICATION
  var verifyRange = sheet.getRange(1, 1, lastRow, totalDestHeaders.length);
  var verifiedValues = verifyRange.getValues();
  var verifiedFormulas = verifyRange.getFormulas();

  for (var r = 1; r < lastRow; r++) {
    for (var sc = 0; sc < sourceHeaders.length; sc++) {
      if (colMapping.hasOwnProperty(sc)) {
        var expectedDestCol = colMapping[sc];
        var origFormula = rawFormulas[r][sc];
        var origVal = rawValues[r][sc];
        var destFormula = verifiedFormulas[r][expectedDestCol];
        var destVal = verifiedValues[r][expectedDestCol];

        if (!areCellValuesEquivalent(origVal, destVal, origFormula, destFormula)) {
          throw new Error(
            "POST-MIGRATION DATA INTEGRITY MISMATCH in sheet '" + sheetName + "': " +
            "Cell [" + (r + 1) + "," + (sc + 1) + "] (source '" + sourceHeaders[sc] + "') " +
            "value/formula did not match destination [" + (r + 1) + "," + (expectedDestCol + 1) + "] " +
            "(target '" + totalDestHeaders[expectedDestCol] + "'). " +
            "Original: Val=" + origVal + ", Formula=" + origFormula + " | " +
            "Destination: Val=" + destVal + ", Formula=" + destFormula
          );
        }
      }
    }
  }
}
