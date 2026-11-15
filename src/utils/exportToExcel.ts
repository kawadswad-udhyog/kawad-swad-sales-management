import type { Cell, Row } from 'write-excel-file/browser';

function toCell(val: unknown): Cell {
  if (val === null || val === undefined || val === '') {
    return { value: '', type: String };
  }
  if (typeof val === 'number' && Number.isFinite(val)) {
    return { value: val, type: Number };
  }
  if (typeof val === 'boolean') {
    return { value: val, type: Boolean };
  }
  if (val instanceof Date && !Number.isNaN(val.getTime())) {
    return { value: val, type: Date };
  }
  return { value: String(val), type: String };
}

export async function exportSheetToExcel(
  sheetName: string,
  data: object[],
  headers?: string[]
): Promise<void> {
  const { default: writeXlsxFile } = await import('write-excel-file/browser');

  const keys =
    headers && headers.length > 0
      ? headers
      : data.length > 0
      ? Object.keys(data[0] as Record<string, unknown>)
      : ['Notice'];

  const headerRow: Row = keys.map((k) => ({
    value: k,
    type: String,
    fontWeight: 'bold',
  }));

  const dataRows: Row[] =
    data.length > 0
      ? data.map((item) => {
          const row = item as Record<string, unknown>;
          return keys.map((key) => toCell(row[key]));
        })
      : [];

  const columns = keys.map((key) => {
    let maxLen = key.length;
    data.forEach((item) => {
      const row = item as Record<string, unknown>;
      const valStr = String(row[key] ?? '');
      if (valStr.length > maxLen) {
        maxLen = Math.min(valStr.length, 45);
      }
    });
    return { width: Math.max(maxLen + 3, 12) };
  });

  await writeXlsxFile([headerRow, ...dataRows], {
    sheet: sheetName.slice(0, 31),
    columns,
  }).toFile(`${sheetName}.xlsx`);
}
