import * as XLSX from 'xlsx';

export function exportSheetToExcel(
  sheetName: string,
  data: object[],
  headers?: string[]
): void {
  const wb = XLSX.utils.book_new();

  let ws: XLSX.WorkSheet;
  if (headers && headers.length > 0) {
    // Map objects to specified header order
    const orderedRows = data.map((item) => {
      const row = item as Record<string, unknown>;
      const obj: Record<string, unknown> = {};
      headers.forEach((h) => {
        obj[h] = row[h] ?? '';
      });
      return obj;
    });
    ws = XLSX.utils.json_to_sheet(orderedRows, { header: headers });
  } else {
    ws = XLSX.utils.json_to_sheet(data);
  }

  // Calculate auto column widths
  const colWidths: { wch: number }[] = [];
  if (data.length > 0) {
    const firstRow = data[0] as Record<string, unknown>;
    const keys = headers || Object.keys(firstRow);
    keys.forEach((key) => {
      let maxLen = key.length;
      data.forEach((item) => {
        const row = item as Record<string, unknown>;
        const valStr = String(row[key] ?? '');
        if (valStr.length > maxLen) {
          maxLen = Math.min(valStr.length, 45);
        }
      });
      colWidths.push({ wch: Math.max(maxLen + 3, 12) });
    });
    ws['!cols'] = colWidths;
  }

  XLSX.utils.book_append_sheet(wb, ws, sheetName.slice(0, 31));
  XLSX.writeFile(wb, `${sheetName}.xlsx`);
}
