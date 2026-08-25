import { create } from 'zustand';
import { persist, type StorageValue } from 'zustand/middleware';
import { createSessionSlice, type SessionSlice } from './slices/session-slice';
import { createQuerySlice, type QuerySlice } from './slices/query-slice';
import { createRecordSlice, type RecordSlice } from './slices/record-slice';
import { createMetadataSlice, type MetadataSlice } from './slices/metadata-slice';
import { createUiSlice, type UiSlice } from './slices/ui-slice';
import { createImportSlice, type ImportSlice } from './slices/import-slice';

export type StoreState = SessionSlice & QuerySlice & RecordSlice & MetadataSlice & UiSlice & ImportSlice;

const chromeStorage = {
  getItem: async (name: string): Promise<StorageValue<StoreState> | null> => {
    const result = await chrome.storage.local.get(name);
    const raw = result[name] as string | undefined;
    if (raw == null) return null;
    return JSON.parse(raw) as StorageValue<StoreState>;
  },
  setItem: async (name: string, value: StorageValue<StoreState>): Promise<void> => {
    await chrome.storage.local.set({ [name]: JSON.stringify(value) });
  },
  removeItem: async (name: string): Promise<void> => {
    await chrome.storage.local.remove(name);
  },
};

export const useStore = create<StoreState>()(
  persist(
    (...a) => ({
      ...createSessionSlice(...a),
      ...createQuerySlice(...a),
      ...createRecordSlice(...a),
      ...createMetadataSlice(...a),
      ...createUiSlice(...a),
      ...createImportSlice(...a),
    }),
    {
      name: 'sf-inspector-plus',
      storage: chromeStorage,
      partialize: (state) => ({
        queryHistory: state.queryHistory,
        savedQueries: state.savedQueries,
        activeTab: state.activeTab,
      }) as unknown as StoreState,
    }
  )
);
