import {
  compositeInsert,
  compositeUpdate,
  compositeUpsert,
  compositeDelete,
} from './salesforce-api';
import type { CompositeResult } from './salesforce-api';
import type { ImportAction } from '@/store/slices/import-slice';
import type { FieldMapping, ImportRecordResult } from '@/store/slices/import-slice';

interface BatchUpdate {
  index: number;
  update: Partial<ImportRecordResult>;
}

export interface ImportOptions {
  objectName: string;
  action: ImportAction;
  externalIdField: string;
  batchSize: number;
  threads: number;
  fieldMappings: FieldMapping[];
  records: Record<string, string>[];
  onBatchUpdate: (updates: BatchUpdate[]) => void;
  shouldCancel: () => boolean;
}

function mapRecord(
  record: Record<string, string>,
  mappings: FieldMapping[]
): Record<string, unknown> {
  const mapped: Record<string, unknown> = {};
  for (const m of mappings) {
    if (!m.sfField) continue;
    const val = record[m.column];
    if (val === undefined) continue;
    mapped[m.sfField] = val === '' ? null : val;
  }
  return mapped;
}

function chunk<T>(arr: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

async function executeBatch(
  batch: { index: number; record: Record<string, string> }[],
  options: ImportOptions
): Promise<BatchUpdate[]> {
  const { action, objectName, externalIdField, fieldMappings } = options;
  const updates: BatchUpdate[] = [];

  batch.forEach((b) => {
    updates.push({ index: b.index, update: { status: 'processing' } });
  });
  options.onBatchUpdate(updates);

  try {
    let results: CompositeResult[];
    const mappedRecords = batch.map((b) => mapRecord(b.record, fieldMappings));

    switch (action) {
      case 'Insert':
        results = await compositeInsert(objectName, mappedRecords);
        break;
      case 'Update':
        results = await compositeUpdate(objectName, mappedRecords);
        break;
      case 'Upsert':
        results = await compositeUpsert(objectName, externalIdField, mappedRecords);
        break;
      case 'Delete': {
        const ids = mappedRecords.map((r) => String(r.Id ?? r.id ?? '')).filter(Boolean);
        if (ids.length === 0) {
          return batch.map((b) => ({
            index: b.index,
            update: { status: 'failed' as const, error: 'No Id field found' },
          }));
        }
        results = await compositeDelete(ids);
        break;
      }
    }

    return batch.map((b, i) => {
      const result = results[i];
      if (result?.success) {
        return { index: b.index, update: { status: 'succeeded' as const, id: result.id ?? undefined } };
      } else {
        const errorMsg = result?.errors?.map((e) => e.message).join('; ') ?? 'Unknown error';
        return { index: b.index, update: { status: 'failed' as const, error: errorMsg } };
      }
    });
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : 'Batch failed';
    return batch.map((b) => ({
      index: b.index,
      update: { status: 'failed' as const, error: errorMsg },
    }));
  }
}

export async function runImport(options: ImportOptions): Promise<void> {
  const { records, batchSize, threads } = options;

  const indexedRecords = records.map((record, index) => ({ index, record }));
  const batches = chunk(indexedRecords, Math.min(batchSize, 200));

  let batchIndex = 0;

  while (batchIndex < batches.length) {
    if (options.shouldCancel()) break;

    const windowSize = Math.min(threads, batches.length - batchIndex);
    const window = batches.slice(batchIndex, batchIndex + windowSize);

    const batchPromises = window.map((batch) => executeBatch(batch, options));
    const batchResults = await Promise.all(batchPromises);

    for (const updates of batchResults) {
      options.onBatchUpdate(updates);
    }

    batchIndex += windowSize;
  }
}

export function autoMapFields(
  columns: string[],
  sfFields: { name: string; label: string }[]
): FieldMapping[] {
  return columns.map((col) => {
    const colLower = col.toLowerCase().trim();

    const exactMatch = sfFields.find((f) => f.name.toLowerCase() === colLower);
    if (exactMatch) return { column: col, sfField: exactMatch.name };

    const labelMatch = sfFields.find((f) => f.label.toLowerCase() === colLower);
    if (labelMatch) return { column: col, sfField: labelMatch.name };

    const partialMatch = sfFields.find(
      (f) =>
        f.name.toLowerCase().replace(/__c$/, '').replace(/_/g, '') ===
        colLower.replace(/\s+/g, '').replace(/_/g, '')
    );
    if (partialMatch) return { column: col, sfField: partialMatch.name };

    return { column: col, sfField: '' };
  });
}
