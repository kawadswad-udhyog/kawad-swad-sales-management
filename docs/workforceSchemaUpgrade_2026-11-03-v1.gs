/**
 * ============================================================================
 * KAWAD SWAD ERP - WORKFORCE SCHEMA UPGRADE SCRIPT (ADDITIVE CREATION)
 * Version: 2026-11-03-v1-canonical
 * File: docs/workforceSchemaUpgrade_2026-11-03-v1.gs
 *
 * PURPOSE:
 * Additive creation of missing workforce sheets with exact canonical headers.
 * Genuinely read-only audit and preview.
 * Strictly preserves historical ERP records and never overwrites existing data.
 *
 * CANONICAL SOURCE:
 * backend/app/sheets.py (REQUIRED_TABS)
 * ============================================================================
 */

// Authoritative Canonical Schemas for Workforce Sheets
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

// Legacy Core Schemas - Strictly Preserved and Expected As-Is
var LEGACY_WORKER_SCHEMAS = {
  "Workers": [
    "worker_id", "worker_name", "mobile", "daily_wage", "active", "notes", "created_at"
  ],
  "WorkerAttendance": [
    "attendance_id", "worker_id", "worker_name_snapshot", "attendance_date",
    "status", "daily_wage_snapshot", "wage_accrued", "notes", "created_at", "created_by"
  ]
};

/**
 * GENUINELY READ-ONLY AUDIT
 * Analyzes the workbook without creating, updating, or deleting any tabs or records.
 */
function auditWorkforceWorkbook() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var auditReport = {
    timestamp: new Date().toISOString(),
    mode: "READ_ONLY_AUDIT",
    workforce_tabs_summary: {
      total_required: Object.keys(CANONICAL_WORKFORCE_SCHEMAS).length,
      existing_canonical: 0,
      existing_with_mismatches: 0,
      missing: 0
    },
    legacy_workers_audit: {},
    tab_reports: {}
  };

  // 1. Audit Legacy Worker Tabs
  for (var legName in LEGACY_WORKER_SCHEMAS) {
    var legSheet = ss.getSheetByName(legName);
    var expected = LEGACY_WORKER_SCHEMAS[legName];
    if (!legSheet) {
      auditReport.legacy_workers_audit[legName] = { exists: false, error: "Legacy sheet missing!" };
      continue;
    }
    var legCols = legSheet.getLastColumn();
    var legHeaders = legCols > 0 ? legSheet.getRange(1, 1, 1, legCols).getValues()[0] : [];
    auditReport.legacy_workers_audit[legName] = {
      exists: true,
      data_rows: Math.max(0, legSheet.getLastRow() - 1),
      headers_match: JSON.stringify(legHeaders) === JSON.stringify(expected),
      actual_headers: legHeaders,
      expected_headers: expected
    };
  }

  // 2. Audit 16 Workforce Tabs
  for (var sheetName in CANONICAL_WORKFORCE_SCHEMAS) {
    var canonical = CANONICAL_WORKFORCE_SCHEMAS[sheetName];
    var sheet = ss.getSheetByName(sheetName);

    var rep = {
      sheet_name: sheetName,
      exists: sheet !== null,
      data_rows: 0,
      blank_header_data_cells: [],
      extra_columns: [],
      missing_canonical_columns: [],
      column_order_mismatches: [],
      is_canonical: false
    };

    if (!sheet) {
      rep.status = "MISSING_SHEET";
      auditReport.workforce_tabs_summary.missing++;
      auditReport.tab_reports[sheetName] = rep;
      continue;
    }

    var lastRow = sheet.getLastRow();
    var lastCol = sheet.getLastColumn();
    rep.data_rows = Math.max(0, lastRow - 1);

    if (lastRow === 0 || lastCol === 0) {
      rep.status = "EMPTY_SHEET_NO_HEADERS";
      auditReport.workforce_tabs_summary.existing_with_mismatches++;
      auditReport.tab_reports[sheetName] = rep;
      continue;
    }

    var headerRow = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
    var fullValues = lastRow > 1 ? sheet.getRange(2, 1, lastRow - 1, lastCol).getValues() : [];

    // Detect blank headers with non-empty data
    for (var c = 0; c < lastCol; c++) {
      var h = String(headerRow[c] || "").trim();
      if (h === "") {
        for (var r = 0; r < fullValues.length; r++) {
          var cellVal = fullValues[r][c];
          if (cellVal !== "" && cellVal !== null && cellVal !== undefined) {
            rep.blank_header_data_cells.push({ row: r + 2, col: c + 1, sample_val: String(cellVal) });
            break;
          }
        }
      }
    }

    // Compare actual headers with canonical
    var actualHeaders = headerRow.map(function(item) { return String(item || "").trim(); });

    // Missing canonical columns
    for (var i = 0; i < canonical.length; i++) {
      if (actualHeaders.indexOf(canonical[i]) === -1) {
        rep.missing_canonical_columns.push(canonical[i]);
      }
    }

    // Extra columns
    for (var j = 0; j < actualHeaders.length; j++) {
      var actH = actualHeaders[j];
      if (actH !== "" && canonical.indexOf(actH) === -1) {
        rep.extra_columns.push(actH);
      }
    }

    // Column order comparison for existing canonical columns
    for (var k = 0; k < Math.min(canonical.length, actualHeaders.length); k++) {
      if (actualHeaders[k] !== canonical[k] && actualHeaders[k] !== "") {
        rep.column_order_mismatches.push({
          pos: k + 1,
          expected: canonical[k],
          found: actualHeaders[k]
        });
      }
    }

    if (rep.missing_canonical_columns.length === 0 && rep.extra_columns.length === 0 && rep.column_order_mismatches.length === 0 && rep.blank_header_data_cells.length === 0) {
      rep.status = "EXACT_CANONICAL";
      rep.is_canonical = true;
      auditReport.workforce_tabs_summary.existing_canonical++;
    } else {
      rep.status = "SCHEMA_MISMATCH";
      auditReport.workforce_tabs_summary.existing_with_mismatches++;
    }

    auditReport.tab_reports[sheetName] = rep;
  }

  Logger.log("\n=======================================================");
  Logger.log("KAWAD SWAD ERP - WORKFORCE WORKBOOK READ-ONLY AUDIT");
  Logger.log("=======================================================\n");
  Logger.log(JSON.stringify(auditReport, null, 2));
  return auditReport;
}

/**
 * GENUINELY READ-ONLY PREVIEW
 * Previews what actions additive creation would perform. Modifies NO data.
 */
function previewWorkforceAdditiveUpgrade() {
  var audit = auditWorkforceWorkbook();
  var plan = {
    mode: "READ_ONLY_PREVIEW",
    tabs_to_create: [],
    tabs_already_present_will_not_touch: [],
    tabs_with_mismatches_require_migration_utility: []
  };

  for (var sheetName in audit.tab_reports) {
    var rep = audit.tab_reports[sheetName];
    if (!rep.exists) {
      plan.tabs_to_create.push(sheetName);
    } else if (rep.is_canonical) {
      plan.tabs_already_present_will_not_touch.push(sheetName);
    } else {
      plan.tabs_with_mismatches_require_migration_utility.push({
        sheet_name: sheetName,
        data_rows: rep.data_rows,
        missing_columns: rep.missing_canonical_columns,
        extra_columns: rep.extra_columns
      });
    }
  }

  Logger.log("\n=======================================================");
  Logger.log("ADDITIVE UPGRADE PREVIEW (READ-ONLY)");
  Logger.log("=======================================================\n");
  Logger.log(JSON.stringify(plan, null, 2));
  return plan;
}

/**
 * ADDITIVE SHEET CREATION (SAFE INITIALIZER)
 * Creates ONLY missing workforce tabs and writes canonical row-1 headers.
 * NEVER alters existing sheets or historical records.
 */
function createMissingWorkforceTabs(authorizedConfirmation) {
  if (authorizedConfirmation !== "CONFIRM_ADDITIVE_WORKFORCE_CREATION") {
    throw new Error(
      "Safety Guard Active: Pass 'CONFIRM_ADDITIVE_WORKFORCE_CREATION' to create missing tabs."
    );
  }

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var created = [];
  var skipped = [];

  for (var sheetName in CANONICAL_WORKFORCE_SCHEMAS) {
    var sheet = ss.getSheetByName(sheetName);
    var canonicalHeaders = CANONICAL_WORKFORCE_SCHEMAS[sheetName];

    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
      sheet.getRange(1, 1, 1, canonicalHeaders.length).setValues([canonicalHeaders]);
      sheet.setFrozenRows(1);
      created.push(sheetName);
    } else {
      skipped.push(sheetName);
    }
  }

  Logger.log("Created missing tabs: " + created.join(", "));
  Logger.log("Skipped existing tabs: " + skipped.join(", "));
  return { created: created, skipped: skipped };
}
