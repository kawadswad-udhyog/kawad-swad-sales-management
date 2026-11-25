/**
 * KAWAD SWAD - READ-ONLY WORKBOOK AUDIT
 * Version: 1.0
 *
 * Reads the spreadsheet bound to this Apps Script project.
 * No spreadsheet or Drive write methods are used.
 *
 * Output is split into small JSON chunks in the Execution log to make it easier
 * to copy. Header candidates are based on the row (within the first five rows)
 * containing the largest number of non-empty cells. The raw first five rows
 * are included so the header decision can be checked by a human.
 */
function KS_RUN_READ_ONLY_WORKBOOK_AUDIT() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error(
      'No active bound spreadsheet was found. Open this script from the intended Kawad Swad spreadsheet.'
    );
  }

  var sheets = ss.getSheets();
  var report = {
    auditName: 'KAWAD_SWAD_READ_ONLY_WORKBOOK_AUDIT',
    auditVersion: '1.0',
    generatedAt: new Date().toISOString(),
    spreadsheetName: ss.getName(),
    spreadsheetId: ss.getId(),
    spreadsheetUrl: ss.getUrl(),
    sheetCount: sheets.length,
    headerDetection: 'Candidate row is the densest non-empty row among the first five rows; human review required.',
    writeOperationsPerformed: false,
    sheets: []
  };

  var totalUsedRows = 0;
  var totalUsedColumns = 0;
  var emptySheets = 0;
  var sheetsWithDuplicateHeaders = 0;
  var sheetsWithBlankHeaderCells = 0;
  var possiblePlaceholderSheets = 0;
  var sheetsWithReadErrors = 0;

  for (var i = 0; i < sheets.length; i++) {
    var sh = sheets[i];
    var item = {
      sheetIndex: i + 1,
      sheetName: sh.getName(),
      lastRowWithContent: sh.getLastRow(),
      lastColumnWithContent: sh.getLastColumn(),
      frozenRows: sh.getFrozenRows(),
      frozenColumns: sh.getFrozenColumns(),
      candidateHeaderRow: null,
      candidateHeaders: [],
      blankHeaderColumnNumbers: [],
      duplicateHeaders: [],
      possibleGenericPlaceholder: false,
      firstFiveRows: [],
      status: 'READ_OK'
    };

    try {
      var lastRow = item.lastRowWithContent;
      var lastCol = item.lastColumnWithContent;
      totalUsedRows += lastRow;
      totalUsedColumns += lastCol;

      if (lastRow === 0 || lastCol === 0) {
        emptySheets++;
        item.status = 'EMPTY_OR_NO_CONTENT_RANGE';
        report.sheets.push(item);
        continue;
      }

      var rowsToRead = Math.min(5, lastRow);
      var topRows = sh.getRange(1, 1, rowsToRead, lastCol).getDisplayValues();
      item.firstFiveRows = topRows;

      // Choose the densest row as a candidate only. This is not an approval.
      var candidateIndex = 0;
      var bestCount = -1;
      for (var r = 0; r < topRows.length; r++) {
        var count = 0;
        for (var c = 0; c < topRows[r].length; c++) {
          if (String(topRows[r][c] == null ? '' : topRows[r][c]).trim() !== '') count++;
        }
        if (count > bestCount) {
          bestCount = count;
          candidateIndex = r;
        }
      }

      item.candidateHeaderRow = candidateIndex + 1;
      var headers = topRows[candidateIndex].map(function (v) {
        return String(v == null ? '' : v).trim();
      });
      item.candidateHeaders = headers;

      var seen = {};
      var duplicateSet = {};
      var blankColumns = [];
      var nonBlankHeaders = [];
      var allGeneric = true;
      var genericCount = 0;

      for (var h = 0; h < headers.length; h++) {
        var original = headers[h];
        var normalized = original.toLowerCase().replace(/\s+/g, ' ').trim();

        if (!normalized) {
          blankColumns.push(h + 1);
          allGeneric = false;
          continue;
        }

        nonBlankHeaders.push(original);
        if (seen[normalized]) duplicateSet[normalized] = true;
        seen[normalized] = true;

        if (/^(field|column|col|header|unnamed|blank)[ _-]*\d*$/i.test(original)) {
          genericCount++;
        } else {
          allGeneric = false;
        }
      }

      item.blankHeaderColumnNumbers = blankColumns;
      item.duplicateHeaders = Object.keys(duplicateSet);
      item.possibleGenericPlaceholder = nonBlankHeaders.length > 0 && allGeneric && genericCount >= 2;
      item.candidateHeaderNonBlankCount = nonBlankHeaders.length;
      item.candidateHeaderBlankCount = blankColumns.length;
      item.dataRowExtentAfterCandidate = Math.max(0, lastRow - item.candidateHeaderRow);
      item.note = 'dataRowExtentAfterCandidate is a row-range estimate, not a verified non-empty business-record count.';

      if (blankColumns.length) sheetsWithBlankHeaderCells++;
      if (item.duplicateHeaders.length) sheetsWithDuplicateHeaders++;
      if (item.possibleGenericPlaceholder) possiblePlaceholderSheets++;

      report.sheets.push(item);
    } catch (err) {
      sheetsWithReadErrors++;
      item.status = 'READ_ERROR';
      item.error = String(err && err.message ? err.message : err);
      report.sheets.push(item);
    }
  }

  report.summary = {
    sheetCount: sheets.length,
    emptyOrNoContentRangeSheets: emptySheets,
    sheetsWithBlankCandidateHeaderCells: sheetsWithBlankHeaderCells,
    sheetsWithDuplicateCandidateHeaders: sheetsWithDuplicateHeaders,
    possibleGenericPlaceholderSheets: possiblePlaceholderSheets,
    sheetsWithReadErrors: sheetsWithReadErrors,
    sumOfLastRowsAcrossSheets: totalUsedRows,
    sumOfLastColumnsAcrossSheets: totalUsedColumns,
    recordCountsVerified: false,
    writeOperationsPerformed: false
  };

  var json = JSON.stringify(report);
  var chunkSize = 4500;
  var totalChunks = Math.ceil(json.length / chunkSize);

  Logger.log('KS_AUDIT_START ' + JSON.stringify({
    auditName: report.auditName,
    auditVersion: report.auditVersion,
    spreadsheetName: report.spreadsheetName,
    spreadsheetId: report.spreadsheetId,
    sheetCount: report.sheetCount,
    writeOperationsPerformed: false
  }));

  Logger.log('KS_AUDIT_SUMMARY ' + JSON.stringify(report.summary));

  for (var p = 0; p < totalChunks; p++) {
    var part = json.substring(p * chunkSize, Math.min((p + 1) * chunkSize, json.length));
    Logger.log('KS_AUDIT_REPORT_PART ' + (p + 1) + '/' + totalChunks + ' ' + part);
  }

  Logger.log('KS_AUDIT_END ' + JSON.stringify({
    spreadsheetId: report.spreadsheetId,
    sheetCount: report.sheetCount,
    totalChunks: totalChunks,
    writeOperationsPerformed: false
  }));

  return report;
}