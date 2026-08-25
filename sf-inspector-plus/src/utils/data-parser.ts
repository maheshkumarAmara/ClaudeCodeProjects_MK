export interface ParsedData {
  columns: string[];
  records: Record<string, string>[];
}

export function parseExcel(text: string): ParsedData {
  const lines = text.split('\n').filter((l) => l.trim());
  if (lines.length === 0) return { columns: [], records: [] };

  const columns = lines[0].split('\t').map((c) => c.trim());
  const records = lines.slice(1).map((line) => {
    const values = line.split('\t');
    const record: Record<string, string> = {};
    columns.forEach((col, i) => {
      record[col] = (values[i] ?? '').trim();
    });
    return record;
  });

  return { columns, records };
}

export function parseCsv(text: string): ParsedData {
  const lines = parseCsvLines(text);
  if (lines.length === 0) return { columns: [], records: [] };

  const columns = lines[0].map((c) => c.trim());
  const records = lines.slice(1).map((values) => {
    const record: Record<string, string> = {};
    columns.forEach((col, i) => {
      record[col] = (values[i] ?? '').trim();
    });
    return record;
  });

  return { columns, records };
}

function parseCsvLines(text: string): string[][] {
  const results: string[][] = [];
  let current: string[] = [];
  let field = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < text.length && text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        current.push(field);
        field = '';
      } else if (ch === '\n' || (ch === '\r' && text[i + 1] === '\n')) {
        current.push(field);
        field = '';
        if (current.some((f) => f.trim())) results.push(current);
        current = [];
        if (ch === '\r') i++;
      } else {
        field += ch;
      }
    }
  }

  current.push(field);
  if (current.some((f) => f.trim())) results.push(current);

  return results;
}

export function parseJsonImport(text: string): ParsedData {
  const data = JSON.parse(text);
  if (!Array.isArray(data) || data.length === 0) {
    return { columns: [], records: [] };
  }

  const columnSet = new Set<string>();
  for (const item of data) {
    if (typeof item === 'object' && item !== null) {
      Object.keys(item).forEach((k) => columnSet.add(k));
    }
  }

  const columns = Array.from(columnSet);
  const records = data.map((item) => {
    const record: Record<string, string> = {};
    columns.forEach((col) => {
      const val = item[col];
      record[col] = val == null ? '' : String(val);
    });
    return record;
  });

  return { columns, records };
}

export type ImportFormat = 'excel' | 'csv' | 'json';

export function parseData(text: string, format: ImportFormat): ParsedData {
  switch (format) {
    case 'excel':
      return parseExcel(text);
    case 'csv':
      return parseCsv(text);
    case 'json':
      return parseJsonImport(text);
  }
}
