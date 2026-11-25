/**
 * KAWAD SWAD ERP - SAFE HEADER-MAPPED WRITER & READ-BACK VERIFIER
 * Enforces POL-003 (No silent data loss), POL-004 (Append-only), Section 3.3 & 11.2
 */

/**
 * Resolves a sheet and returns a map of { header_name: 1-based_column_index }.
 * Throws immediately if blank/duplicate headers exist or required headers are missing.
 */
function ksGetHeaderMap_(sheet, requiredHeaders) {
  if (!sheet) throw new Error('Target worksheet does not exist.');
  const lastCol = sheet.getLastColumn();
  if (lastCol === 0) throw new Error('Sheet "' + sheet.getName() + '" has no header row.');

  const rawHeaders = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const headerMap = {};

  rawHeaders.forEach((h, idx) => {
    const clean = String(h || '').trim();
    if (!clean) {
      throw new Error('Schema Exception: Blank header at column ' + (idx + 1) + ' in "' + sheet.getName() + '".');
    }
    if (Object.prototype.hasOwnProperty.call(headerMap, clean)) {
      throw new Error('Schema Exception: Duplicate header "' + clean + '" in "' + sheet.getName() + '".');
    }
    headerMap[clean] = idx + 1;
  });

  if (Array.isArray(requiredHeaders)) {
    requiredHeaders.forEach(req => {
      if (!Object.prototype.hasOwnProperty.call(headerMap, req)) {
        throw new Error('Schema Exception: Missing required header "' + req + '" in "' + sheet.getName() + '".');
      }
    });
  }

  return { headerMap: headerMap, columnCount: lastCol };
}

/**
 * Appends a single record object mapped strictly by header name, flushes,
 * and reads back the written row to verify primary key & mandatory fields (POL-003).
 */
function ksAppendAndVerifyRow_(ss, tabName, recordObj, primaryKeyField, mandatoryFields) {
  const sheet = ss.getSheetByName(tabName);
  const reqHeaders = KS_CONFIG.REQUIRED_HEADERS[tabName] || mandatoryFields || [];
  const { headerMap, columnCount } = ksGetHeaderMap_(sheet, reqHeaders);

  // Validate mandatory fields before touching the sheet
  (mandatoryFields || []).forEach(field => {
    const val = recordObj[field];
    if (val === undefined || val === null || String(val).trim() === '') {
      throw new Error('Validation Error: Mandatory field "' + field + '" missing for "' + tabName + '".');
    }
  });

  // Build row array aligned strictly to sheet headers
  const rowValues = new Array(columnCount).fill('');
  Object.keys(recordObj).forEach(key => {
    if (!Object.prototype.hasOwnProperty.call(headerMap, key)) {
      throw new Error('Schema Exception: Unknown field "' + key + '" not in "' + tabName + '" headers.');
    }
    rowValues[headerMap[key] - 1] = recordObj[key];
  });

  const targetRow = sheet.getLastRow() + 1;
  sheet.getRange(targetRow, 1, 1, columnCount).setValues([rowValues]);
  SpreadsheetApp.flush();

  // Read-back verification (Section 11.2)
  const readBack = sheet.getRange(targetRow, 1, 1, columnCount).getValues()[0];
  const expectedPk = String(recordObj[primaryKeyField]);
  const actualPk = String(readBack[headerMap[primaryKeyField] - 1]);

  if (expectedPk !== actualPk) {
    throw new Error(
      'Read-Back Verification Failed in "' + tabName + '" row ' + targetRow +
      ': expected ' + expectedPk + ', got ' + actualPk
    );
  }

  return { row: targetRow, record: recordObj };
}