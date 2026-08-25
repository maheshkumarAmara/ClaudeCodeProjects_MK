import type { StateCreator } from 'zustand';
import type { ImportFormat } from '@/utils/data-parser';

export type ImportAction = 'Insert' | 'Update' | 'Upsert' | 'Delete';

export interface FieldMapping {
  column: string;
  sfField: string;
}

export interface ImportRecordResult {
  index: number;
  status: 'queued' | 'processing' | 'succeeded' | 'failed';
  id?: string;
  error?: string;
}

export interface ImportSlice {
  importObjectName: string;
  importAction: ImportAction;
  importFormat: ImportFormat;
  importData: string;
  importBatchSize: number;
  importThreads: number;
  importExternalIdField: string;
  importFieldMappings: FieldMapping[];
  importResults: ImportRecordResult[];
  importIsRunning: boolean;
  importError: string | null;
  setImportObjectName: (name: string) => void;
  setImportAction: (action: ImportAction) => void;
  setImportFormat: (format: ImportFormat) => void;
  setImportData: (data: string) => void;
  setImportBatchSize: (size: number) => void;
  setImportThreads: (threads: number) => void;
  setImportExternalIdField: (field: string) => void;
  setImportFieldMappings: (mappings: FieldMapping[]) => void;
  setImportResults: (results: ImportRecordResult[]) => void;
  updateImportResult: (index: number, update: Partial<ImportRecordResult>) => void;
  updateImportResultsBatch: (updates: { index: number; update: Partial<ImportRecordResult> }[]) => void;
  setImportIsRunning: (running: boolean) => void;
  setImportError: (error: string | null) => void;
  resetImport: () => void;
}

export const createImportSlice: StateCreator<ImportSlice> = (set) => ({
  importObjectName: '',
  importAction: 'Insert',
  importFormat: 'excel',
  importData: '',
  importBatchSize: 200,
  importThreads: 6,
  importExternalIdField: '',
  importFieldMappings: [],
  importResults: [],
  importIsRunning: false,
  importError: null,
  setImportObjectName: (name) => set({ importObjectName: name }),
  setImportAction: (action) => set({ importAction: action }),
  setImportFormat: (format) => set({ importFormat: format }),
  setImportData: (data) => set({ importData: data }),
  setImportBatchSize: (size) => set({ importBatchSize: Math.min(200, Math.max(1, size)) }),
  setImportThreads: (threads) => set({ importThreads: Math.min(10, Math.max(1, threads)) }),
  setImportExternalIdField: (field) => set({ importExternalIdField: field }),
  setImportFieldMappings: (mappings) => set({ importFieldMappings: mappings }),
  setImportResults: (results) => set({ importResults: results }),
  updateImportResult: (index, update) =>
    set((state) => ({
      importResults: state.importResults.map((r) =>
        r.index === index ? { ...r, ...update } : r
      ),
    })),
  updateImportResultsBatch: (updates) =>
    set((state) => {
      const updateMap = new Map(updates.map((u) => [u.index, u.update]));
      return {
        importResults: state.importResults.map((r) => {
          const u = updateMap.get(r.index);
          return u ? { ...r, ...u } : r;
        }),
      };
    }),
  setImportIsRunning: (running) => set({ importIsRunning: running }),
  setImportError: (error) => set({ importError: error }),
  resetImport: () =>
    set({
      importObjectName: '',
      importAction: 'Insert',
      importFormat: 'excel',
      importData: '',
      importBatchSize: 200,
      importThreads: 6,
      importExternalIdField: '',
      importFieldMappings: [],
      importResults: [],
      importIsRunning: false,
      importError: null,
    }),
});
