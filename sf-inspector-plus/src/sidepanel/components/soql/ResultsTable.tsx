import { useMemo, useState } from 'react';
import type { QueryResult } from '@/types/salesforce';
import { extractColumns, resolveField } from '@/utils/csv-export';

interface ResultsTableProps {
  results: QueryResult;
}

type SortConfig = { key: string; direction: 'asc' | 'desc' } | null;

export function ResultsTable({ results }: ResultsTableProps) {
  const [sortConfig, setSortConfig] = useState<SortConfig>(null);

  const columns = useMemo(() => {
    if (!results.records.length) return [];
    return extractColumns(results.records as Record<string, unknown>[]);
  }, [results.records]);

  const sortedRecords = useMemo(() => {
    const records = results.records as Record<string, unknown>[];
    if (!sortConfig) return records;

    return [...records].sort((a, b) => {
      const aVal = resolveField(a, sortConfig.key);
      const bVal = resolveField(b, sortConfig.key);
      if (!aVal && !bVal) return 0;
      if (!aVal) return 1;
      if (!bVal) return -1;
      const comparison = aVal.localeCompare(bVal, undefined, { numeric: true });
      return sortConfig.direction === 'asc' ? comparison : -comparison;
    });
  }, [results.records, sortConfig]);

  const handleSort = (key: string) => {
    setSortConfig((prev) => {
      if (prev?.key === key) {
        if (prev.direction === 'asc') return { key, direction: 'desc' };
        return null;
      }
      return { key, direction: 'asc' };
    });
  };

  const formatCell = (record: Record<string, unknown>, col: string): React.ReactNode => {
    const value = resolveField(record, col);
    if (value === '') {
      const parts = col.split('.');
      let raw: unknown = record;
      for (const part of parts) {
        if (raw == null || typeof raw !== 'object') { raw = undefined; break; }
        raw = (raw as Record<string, unknown>)[part];
      }
      if (raw == null) return <span className="null-value">null</span>;
    }
    const num = Number(value);
    if (value !== '' && !isNaN(num) && isFinite(num) && /^\d/.test(value) && !Number.isInteger(num) && value.includes('.')) {
      return String(parseFloat(num.toPrecision(12)));
    }
    return value;
  };

  const getSortIndicator = (key: string) => {
    if (sortConfig?.key !== key) return '';
    return sortConfig.direction === 'asc' ? ' \u25B2' : ' \u25BC';
  };

  const getRecordLink = (record: Record<string, unknown>): { type: string; id: string | null } => {
    const attrs = record.attributes as { type?: string; url?: string } | undefined;
    const type = attrs?.type ?? '';
    const id = (record.Id ?? record.id ?? null) as string | null;
    return { type, id };
  };

  return (
    <table>
      <thead>
        <tr>
          <th
            style={{ width: 30, textAlign: 'center', cursor: 'default' }}
            title="Row number"
          >
            #
          </th>
          <th style={{ cursor: 'default' }}>_</th>
          {columns.map((col) => (
            <th key={col} onClick={() => handleSort(col)}>
              {col}{getSortIndicator(col)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sortedRecords.map((record, rowIdx) => {
          const { type, id } = getRecordLink(record as Record<string, unknown>);
          return (
            <tr key={rowIdx}>
              <td style={{ textAlign: 'center', color: '#8c8c8c', width: 30 }}>
                {rowIdx + 1}
              </td>
              <td>
                {id ? (
                  <a href={`https://login.salesforce.com/${id}`} target="_blank" rel="noopener noreferrer">
                    {type}
                  </a>
                ) : (
                  type
                )}
              </td>
              {columns.map((col) => (
                <td key={col}>{formatCell(record as Record<string, unknown>, col)}</td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
