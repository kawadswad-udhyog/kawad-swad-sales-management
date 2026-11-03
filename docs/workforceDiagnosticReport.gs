/**
 * ============================================================================
 * KAWAD SWAD ERP - WORKFORCE LIVE DIAGNOSTIC REPORT (READ-ONLY)
 * File: docs/workforceDiagnosticReport.gs
 *
 * PURPOSE:
 * Produces an exhaustive, code-level diagnostic report of all 16 workforce sheets
 * and legacy labor sheets in the Google Sheets workbook prior to any schema migration.
 *
 * CANONICAL SCHEMA AUTHORITY:
 * backend/app/sheets.py -> REQUIRED_TABS
 *
 * SAFETY GUARANTEES:
 * 1. Strictly 100% read-only.
 * 2. Zero sheet creation (no insertSheet).
 * 3. Zero cell mutation (no setValue, setValues, appendRow, clear, delete).
 * 4. Zero formatting or metadata changes.
 * 5. Does not inspect private payload values beyond non-empty cell counts and formula counts.
 * 6. Completely safe to run at any time in the live Google Apps Script editor.
 *
 * USAGE:
 * In Google Apps Script Editor:
 * - Run all sheets: generateWorkforceLiveDiagnosticReport()
 * - Run single sheet: generateWorkforceLiveDiagnosticReport("WorkAssignments")
 * ============================================================================
 */

// 1. Authoritative Canonical Schemas (backend/app/sheets.py -> REQUIRED_TABS)
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

// 2. Authoritative Legacy Schemas (backend/app/sheets.py -> REQUIRED_TABS)
var LEGACY_WORKER_SCHEMAS = {
  "Workers": [
    "worker_id", "worker_name", "mobile", "daily_wage", "active", "notes", "created_at"
  ],
  "WorkerAttendance": [
    "attendance_id", "worker_id", "worker_name_snapshot", "attendance_date",
    "status", "daily_wage_snapshot", "wage_accrued", "notes", "created_at", "created_by"
  ]
};

// 3. Known Provisional Aliases (SUGGESTIONS ONLY - NOT AUTOMATICALLY ENFORCED)
var CANDIDATE_PROVISIONAL_ALIASES = {
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

// Helper: Convert 0-indexed column integer to A1 letter ("A", "B", ... "AA")
function diagColIndexToLetter(idx) {
  var temp = idx + 1;
  var letter = "";
  while (temp > 0) {
    var mod = (temp - 1) % 26;
    letter = String.fromCharCode(65 + mod) + letter;
    temp = Math.floor((temp - mod) / 26);
  }
  return letter;
}

/**
 * MAIN DIAGNOSTIC ENTRY POINT
 * Strictly read-only analysis of live Google Sheets workbook.
 *
 * @param {string} [targetSheetName] Optional: single sheet name to diagnose
 * @return {Object} Compact diagnostic report object
 */
function generateWorkforceLiveDiagnosticReport(targetSheetName) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var allSheets = ss.getSheets();

  var report = {
    timestamp: new Date().toISOString(),
    spreadsheet_id: ss.getId(),
    spreadsheet_name: ss.getName(),
    mode: "STRICTLY_READ_ONLY_DIAGNOSTIC",
    summary: {
      total_workbook_tabs: allSheets.length,
      total_workforce_tabs_target: Object.keys(CANONICAL_WORKFORCE_SCHEMAS).length,
      existing_workforce_tabs: 0,
      missing_workforce_tabs: [],
      total_workforce_data_rows: 0,
      total_workforce_formula_cells: 0
    },
    legacy_sheets: {},
    workforce_sheets: {}
  };

  // Determine tabs to evaluate
  var tabsToProcess = [];
  if (targetSheetName && typeof targetSheetName === "string" && targetSheetName.trim() !== "") {
    var cleanedTarget = targetSheetName.trim();
    tabsToProcess = [cleanedTarget];
  } else {
    tabsToProcess = Object.keys(CANONICAL_WORKFORCE_SCHEMAS);
  }

  // 1. Diagnose Legacy Sheets (Workers, WorkerAttendance)
  for (var legName in LEGACY_WORKER_SCHEMAS) {
    var legExpected = LEGACY_WORKER_SCHEMAS[legName];
    var legSheet = ss.getSheetByName(legName);
    if (!legSheet) {
      report.legacy_sheets[legName] = {
        sheet_name: legName,
        exists: false,
        expected_columns_count: legExpected.length,
        canonical_expected_headers: legExpected
      };
      continue;
    }

    var legLastRow = legSheet.getLastRow();
    var legLastCol = legSheet.getLastColumn();
    var legHeaders = [];
    var legFormulasCount = 0;

    if (legLastCol > 0) {
      var hRow = legSheet.getRange(1, 1, 1, legLastCol).getValues()[0];
      for (var hc = 0; hc < hRow.length; hc++) {
        legHeaders.push(String(hRow[hc] || "").trim());
      }
    }

    if (legLastRow > 1 && legLastCol > 0) {
      var fGrid = legSheet.getRange(2, 1, legLastRow - 1, legLastCol).getFormulas();
      for (var fr = 0; fr < fGrid.length; fr++) {
        for (var fc = 0; fc < fGrid[fr].length; fc++) {
          if (fGrid[fr][fc] !== "") legFormulasCount++;
        }
      }
    }

    report.legacy_sheets[legName] = {
      sheet_name: legName,
      exists: true,
      data_rows_count: Math.max(0, legLastRow - 1),
      total_columns: legLastCol,
      actual_headers: legHeaders,
      expected_columns_count: legExpected.length,
      canonical_expected_headers: legExpected,
      formula_cells_count: legFormulasCount,
      headers_match_canonical: JSON.stringify(legHeaders) === JSON.stringify(legExpected)
    };
  }

  // 2. Diagnose Workforce Sheets
  for (var t = 0; t < tabsToProcess.length; t++) {
    var sheetName = tabsToProcess[t];
    var canonicalExpected = CANONICAL_WORKFORCE_SCHEMAS[sheetName] || [];
    var candidateAliases = CANDIDATE_PROVISIONAL_ALIASES[sheetName] || {};
    var sheet = ss.getSheetByName(sheetName);

    if (!sheet) {
      report.summary.missing_workforce_tabs.push(sheetName);
      report.workforce_sheets[sheetName] = {
        sheet_name: sheetName,
        exists: false,
        canonical_expected_headers: canonicalExpected,
        candidate_mappings_suggestions_only: []
      };
      continue;
    }

    report.summary.existing_workforce_tabs++;

    var lastRow = sheet.getLastRow();
    var lastCol = sheet.getLastColumn();
    var dataRowCount = Math.max(0, lastRow - 1);
    report.summary.total_workforce_data_rows += dataRowCount;

    var actualHeaders = [];
    var headerPositions = [];
    var headerCounts = {};
    var duplicateHeaders = [];

    if (lastCol > 0) {
      var headerRowVals = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
      for (var colIdx = 0; colIdx < headerRowVals.length; colIdx++) {
        var rawH = headerRowVals[colIdx];
        var cleanH = (rawH !== null && rawH !== undefined) ? String(rawH).trim() : "";
        actualHeaders.push(cleanH);
        headerPositions.push({
          column_number: colIdx + 1,
          column_letter: diagColIndexToLetter(colIdx),
          header_name: cleanH
        });

        if (cleanH !== "") {
          headerCounts[cleanH] = (headerCounts[cleanH] || 0) + 1;
        }
      }

      for (var hKey in headerCounts) {
        if (headerCounts[hKey] > 1) {
          duplicateHeaders.push(hKey);
        }
      }
    }

    // Inspect non-empty cells and formulas per column
    var colNonEmptyCounts = [];
    var colFormulaCounts = [];
    var blankHeadersWithData = [];
    var sheetFormulaTotal = 0;

    var dataValues = [];
    var dataFormulas = [];
    if (dataRowCount > 0 && lastCol > 0) {
      dataValues = sheet.getRange(2, 1, dataRowCount, lastCol).getValues();
      dataFormulas = sheet.getRange(2, 1, dataRowCount, lastCol).getFormulas();
    }

    for (var c = 0; c < lastCol; c++) {
      var hName = actualHeaders[c] || "";
      var colLetter = diagColIndexToLetter(c);
      var nonEmptyCount = 0;
      var formulaCount = 0;

      for (var r = 0; r < dataRowCount; r++) {
        var v = dataValues[r][c];
        var f = dataFormulas[r][c];
        var isFilled = (v !== "" && v !== null && v !== undefined) || (f !== "");
        if (isFilled) nonEmptyCount++;
        if (f !== "") {
          formulaCount++;
          sheetFormulaTotal++;
        }
      }

      colNonEmptyCounts.push({
        column_number: c + 1,
        column_letter: colLetter,
        header: hName,
        non_empty_count: nonEmptyCount
      });

      colFormulaCounts.push({
        column_number: c + 1,
        column_letter: colLetter,
        header: hName,
        formula_count: formulaCount
      });

      if (hName === "" && nonEmptyCount > 0) {
        blankHeadersWithData.push({
          column_number: c + 1,
          column_letter: colLetter,
          non_empty_data_rows_count: nonEmptyCount
        });
      }
    }

    report.summary.total_workforce_formula_cells += sheetFormulaTotal;

    // Detect missing canonical headers & extra/provisional headers
    var missingCanonical = [];
    for (var ch = 0; ch < canonicalExpected.length; ch++) {
      var cField = canonicalExpected[ch];
      if (actualHeaders.indexOf(cField) === -1) {
        missingCanonical.push(cField);
      }
    }

    var extraHeaders = [];
    for (var ah = 0; ah < actualHeaders.length; ah++) {
      var actH = actualHeaders[ah];
      if (actH !== "" && canonicalExpected.indexOf(actH) === -1) {
        extraHeaders.push(actH);
      }
    }

    // Check header order mismatch
    var headerOrderMismatches = false;
    var presentCanonicalInActual = [];
    for (var ah2 = 0; ah2 < actualHeaders.length; ah2++) {
      var curH = actualHeaders[ah2];
      if (canonicalExpected.indexOf(curH) !== -1) {
        presentCanonicalInActual.push(curH);
      }
    }
    // Check if relative ordering in presentCanonicalInActual matches canonicalExpected
    var lastExpectedIdx = -1;
    for (var p = 0; p < presentCanonicalInActual.length; p++) {
      var currentExpectedIdx = canonicalExpected.indexOf(presentCanonicalInActual[p]);
      if (currentExpectedIdx < lastExpectedIdx) {
        headerOrderMismatches = true;
        break;
      }
      lastExpectedIdx = currentExpectedIdx;
    }

    // Candidate old-to-new header mappings (MARK CLEARLY AS SUGGESTIONS ONLY)
    var candidateSuggestions = [];
    for (var sc = 0; sc < actualHeaders.length; sc++) {
      var sHeader = actualHeaders[sc];
      if (!sHeader) continue;

      if (canonicalExpected.indexOf(sHeader) !== -1) {
        candidateSuggestions.push({
          source_header: sHeader,
          source_column: diagColIndexToLetter(sc),
          suggested_target: sHeader,
          status: "EXACT_CANONICAL_MATCH",
          note: "Source column already matches canonical target name."
        });
      } else if (candidateAliases[sHeader]) {
        candidateSuggestions.push({
          source_header: sHeader,
          source_column: diagColIndexToLetter(sc),
          suggested_target: candidateAliases[sHeader],
          status: "SUGGESTION_ONLY_PROVISIONAL_ALIAS",
          note: "SUGGESTION ONLY: Known alias match; requires owner review before applying."
        });
      } else {
        candidateSuggestions.push({
          source_header: sHeader,
          source_column: diagColIndexToLetter(sc),
          suggested_target: "[PRESERVED_EXTRA]:" + sHeader,
          status: "SUGGESTION_ONLY_UNMAPPED_EXTRA",
          note: "SUGGESTION ONLY: Extra/unknown column; will be preserved at end of sheet."
        });
      }
    }

    report.workforce_sheets[sheetName] = {
      sheet_name: sheetName,
      exists: true,
      data_rows_count: dataRowCount,
      total_columns: lastCol,
      actual_headers: actualHeaders,
      header_positions: headerPositions,
      canonical_expected_headers: canonicalExpected,
      non_empty_cells_per_column: colNonEmptyCounts,
      formula_counts_per_column: colFormulaCounts,
      total_formula_cells: sheetFormulaTotal,
      duplicate_headers: duplicateHeaders,
      blank_headers_containing_data: blankHeadersWithData,
      missing_canonical_headers: missingCanonical,
      extra_or_provisional_headers: extraHeaders,
      header_order_mismatches: headerOrderMismatches,
      candidate_mappings_suggestions_only: candidateSuggestions
    };
  }

  // 3. Log Output in Safe Batches to Avoid Logger.log() Size Limits
  Logger.log("\n=======================================================");
  Logger.log("KAWAD SWAD ERP: WORKFORCE LIVE DIAGNOSTIC REPORT");
  Logger.log("=======================================================");
  Logger.log("Timestamp: " + report.timestamp);
  Logger.log("Workbook: " + report.spreadsheet_name + " (" + report.spreadsheet_id + ")");
  Logger.log("Total Tabs: " + report.summary.total_workbook_tabs);
  Logger.log("Workforce Tabs Target: " + report.summary.total_workforce_tabs_target);
  Logger.log("Existing Workforce Tabs: " + report.summary.existing_workforce_tabs);
  Logger.log("Missing Workforce Tabs: " + JSON.stringify(report.summary.missing_workforce_tabs));
  Logger.log("Total Workforce Data Rows: " + report.summary.total_workforce_data_rows);
  Logger.log("Total Workforce Formula Cells: " + report.summary.total_workforce_formula_cells);
  Logger.log("-------------------------------------------------------");

  // Log Legacy summary
  for (var legK in report.legacy_sheets) {
    var lData = report.legacy_sheets[legK];
    Logger.log("[LEGACY TAB] " + legK + " | Exists: " + lData.exists +
      " | Data Rows: " + (lData.data_rows_count || 0) +
      " | Actual Cols: " + (lData.total_columns || 0) +
      " | Expected Cols: " + lData.expected_columns_count +
      " | Headers Canonical: " + (lData.headers_match_canonical ? "YES" : "NO"));
  }

  // Log each workforce sheet individually to guarantee no truncation
  for (var wName in report.workforce_sheets) {
    var wData = report.workforce_sheets[wName];
    if (!wData.exists) {
      Logger.log("\n[WORKFORCE SHEET MISSING] " + wName);
      continue;
    }

    Logger.log("\n-------------------------------------------------------");
    Logger.log("[WORKFORCE SHEET] " + wName);
    Logger.log("  Data Rows: " + wData.data_rows_count + " | Total Columns: " + wData.total_columns);
    Logger.log("  Formulas Total: " + wData.total_formula_cells);
    Logger.log("  Duplicate Headers: " + (wData.duplicate_headers.length > 0 ? JSON.stringify(wData.duplicate_headers) : "None"));
    Logger.log("  Blank Headers With Data: " + (wData.blank_headers_containing_data.length > 0 ? JSON.stringify(wData.blank_headers_containing_data) : "None"));
    Logger.log("  Missing Canonical Headers (" + wData.missing_canonical_headers.length + "): " + JSON.stringify(wData.missing_canonical_headers));
    Logger.log("  Extra/Provisional Headers (" + wData.extra_or_provisional_headers.length + "): " + JSON.stringify(wData.extra_or_provisional_headers));
    Logger.log("  Header Order Mismatch: " + (wData.header_order_mismatches ? "YES" : "NO"));
    Logger.log("  Candidate Suggestions: " + JSON.stringify(wData.candidate_mappings_suggestions_only));
  }

  Logger.log("\n=======================================================");
  Logger.log("END OF WORKFORCE LIVE DIAGNOSTIC REPORT");
  Logger.log("=======================================================\n");

  return report;
}
