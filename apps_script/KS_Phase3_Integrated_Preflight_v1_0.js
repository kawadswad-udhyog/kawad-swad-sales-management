/**
 * KAWAD SWAD ERP - PHASE 3 INTEGRATED PREFLIGHT
 * Version 1.0
 *
 * REQUIRED: Add the three corrected v1.0.1 source files to the SAME Apps Script
 * project before running this orchestrator:
 *   1) KS_Phase3_Migration_Control_Corrected_v1_0_1.gs
 *   2) KS_Phase3_Table_Mapping_Corrected_v1_0_1.gs
 *   3) KS_Phase3_Field_Mapping_Corrected_v1_0_1.gs
 *
 * RUN ONLY: KS_PHASE3_INTEGRATED_PREFLIGHT
 *
 * This runs governance/preflight reports in dependency order. It does NOT
 * migrate, create, rename, delete, clear, or modify business tabs/records.
 * The first step creates a full Drive backup before writing the control tabs.
 * Each component manages its own document lock. This orchestrator deliberately
 * does not hold a lock while calling them.
 */
function KS_PHASE3_INTEGRATED_PREFLIGHT() {
  const required = [
    'ksP3InstallMigrationControl', 'ksP3VerifyMigrationControl',
    'ksP3BuildTableMapping', 'ksP3VerifyTableMapping',
    'ksP3BuildFieldMapping', 'ksP3VerifyFieldMapping',
    'ksP3CheckMigrationLoggerAlignment'
  ];
  const missing = required.filter(name => typeof this[name] !== 'function');
  if (missing.length) {
    throw new Error('STOP: Add all three corrected Phase 3 source files first. Missing functions: ' + missing.join(', '));
  }

  const report = {
    version: '1.0',
    startedAt: new Date().toISOString(),
    workbookId: SpreadsheetApp.getActiveSpreadsheet().getId(),
    steps: [],
    businessSchemaChanged: false,
    status: 'RUNNING'
  };

  function runStep(label, fn) {
    const result = fn();
    report.steps.push({ step: label, success: result && result.success !== false, result: result || null });
    if (!result || result.success === false) {
      throw new Error('STOP: ' + label + ' did not pass. Inspect execution log before retrying.');
    }
    return result;
  }

  try {
    // Step 1: structural inventory + backup + preserved migration plan.
    runStep('1_CONTROL_AND_LIVE_INVENTORY', ksP3InstallMigrationControl);
    runStep('1A_VERIFY_CONTROL', ksP3VerifyMigrationControl);

    // Step 2: canonical table mapping, based on the fresh inventory.
    runStep('2_TABLE_MAPPING', ksP3BuildTableMapping);
    runStep('2A_VERIFY_TABLE_MAPPING', ksP3VerifyTableMapping);

    // Step 3: 3,074-row field mapping, based on the table map.
    runStep('3_FIELD_MAPPING', ksP3BuildFieldMapping);
    runStep('3A_VERIFY_FIELD_MAPPING', ksP3VerifyFieldMapping);

    // Step 4: append-only logger header alignment check.
    runStep('4_LOGGER_ALIGNMENT_CHECK', ksP3CheckMigrationLoggerAlignment);

    report.status = 'PREFLIGHT_REPORTS_BUILT';
  } catch (err) {
    report.status = 'STOPPED_WITH_ERROR';
    report.error = String(err && err.stack ? err.stack : err);
    report.finishedAt = new Date().toISOString();
    Logger.log('KS_PHASE3_INTEGRATED_PREFLIGHT_RESULT\n' + JSON.stringify(report, null, 2));
    throw err;
  }

  report.finishedAt = new Date().toISOString();
  report.nextGate = 'Review table/field mapping reports and obtain explicit business approvals. No business schema migration has been performed.';
  Logger.log('KS_PHASE3_INTEGRATED_PREFLIGHT_RESULT\n' + JSON.stringify(report, null, 2));
  return report;
}
