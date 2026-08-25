export function recordsToCsv(
  records: Record<string, unknown>[],
  columns?: string[]
): string {
  if (records.length === 0) return '';

  const cols = columns ?? extractColumns(records);
  const header = [escapeCsvField('_'), ...cols.map(escapeCsvField)].join(',');

  const rows = records.map((record) => {
    const type = escapeCsvField(getObjectType(record));
    const fields = cols.map((col) => escapeCsvField(resolveField(record, col)));
    return [type, ...fields].join(',');
  });

  return [header, ...rows].join('\n');
}

export function extractColumns(records: Record<string, unknown>[]): string[] {
  const cols = new Set<string>();
  for (const record of records) {
    flattenKeys(record, '', cols);
  }
  cols.delete('attributes');
  return Array.from(cols);
}

function flattenKeys(
  obj: Record<string, unknown>,
  prefix: string,
  keys: Set<string>
): void {
  for (const key of Object.keys(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    const value = obj[key];
    if (value && typeof value === 'object' && !Array.isArray(value) && key !== 'attributes') {
      flattenKeys(value as Record<string, unknown>, fullKey, keys);
    } else if (key !== 'attributes') {
      keys.add(fullKey);
    }
  }
}

export function resolveField(obj: Record<string, unknown>, path: string): string {
  const parts = path.split('.');
  let current: unknown = obj;
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return '';
    current = (current as Record<string, unknown>)[part];
  }
  if (current == null) return '';
  return String(current);
}

function getObjectType(record: Record<string, unknown>): string {
  const attrs = record.attributes as { type?: string } | undefined;
  return attrs?.type ? `[${attrs.type}]` : '';
}

function escapeCsvField(value: string): string {
  if (value.includes(',') || value.includes('"') || value.includes('\n')) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function quoteExcel(value: string): string {
  return `"${value.replace(/"/g, '""').replace(/\t/g, ' ').replace(/\n/g, ' ')}"`;
}

export function recordsToExcel(
  records: Record<string, unknown>[],
  columns?: string[]
): string {
  if (records.length === 0) return '';

  const cols = columns ?? extractColumns(records);
  const header = [quoteExcel('_'), ...cols.map(quoteExcel)].join('\t');

  const rows = records.map((record) => {
    const type = quoteExcel(getObjectType(record));
    const fields = cols.map((col) => quoteExcel(resolveField(record, col)));
    return [type, ...fields].join('\t');
  });

  return [header, ...rows].join('\n');
}

export function recordsToJson(records: Record<string, unknown>[]): string {
  const cleaned = records.map((r) => {
    const obj: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(r)) {
      if (k !== 'attributes') obj[k] = v;
    }
    return obj;
  });
  return JSON.stringify(cleaned, null, 2);
}

export function downloadCsv(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function downloadJson(data: unknown, filename: string): void {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
