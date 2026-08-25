import type { StateCreator } from 'zustand';
import type { QueryResult } from '@/types/salesforce';

export interface QueryHistoryEntry {
  soql: string;
  timestamp: number;
  orgId: string;
  rowCount: number;
  starred: boolean;
}

export interface SavedQuery {
  id: string;
  name: string;
  soql: string;
  orgId: string;
  createdAt: number;
}

export interface QuerySlice {
  currentSoql: string;
  queryResults: QueryResult | null;
  queryHistory: QueryHistoryEntry[];
  savedQueries: SavedQuery[];
  isExecuting: boolean;
  queryError: string | null;
  setCurrentSoql: (soql: string) => void;
  setQueryResults: (results: QueryResult | null) => void;
  addToHistory: (entry: Omit<QueryHistoryEntry, 'starred'>) => void;
  toggleHistoryStarred: (index: number) => void;
  saveQuery: (name: string, soql: string, orgId: string) => void;
  deleteSavedQuery: (id: string) => void;
  updateSavedQuery: (id: string, updates: Partial<Pick<SavedQuery, 'name' | 'soql'>>) => void;
  setIsExecuting: (executing: boolean) => void;
  setQueryError: (error: string | null) => void;
  clearResults: () => void;
}

const MAX_HISTORY = 100;

export const createQuerySlice: StateCreator<QuerySlice> = (set) => ({
  currentSoql: '',
  queryResults: null,
  queryHistory: [],
  savedQueries: [],
  isExecuting: false,
  queryError: null,
  setCurrentSoql: (soql) => set({ currentSoql: soql }),
  setQueryResults: (results) => set({ queryResults: results, queryError: null }),
  addToHistory: (entry) =>
    set((state) => {
      const newEntry = { ...entry, starred: false };
      const updated = [newEntry, ...state.queryHistory];
      const starred = updated.filter((e) => e.starred);
      const unstarred = updated.filter((e) => !e.starred);
      return {
        queryHistory: [...starred, ...unstarred.slice(0, MAX_HISTORY - starred.length)],
      };
    }),
  toggleHistoryStarred: (index) =>
    set((state) => ({
      queryHistory: state.queryHistory.map((entry, i) =>
        i === index ? { ...entry, starred: !entry.starred } : entry
      ),
    })),
  saveQuery: (name, soql, orgId) =>
    set((state) => ({
      savedQueries: [
        ...state.savedQueries,
        { id: crypto.randomUUID(), name, soql, orgId, createdAt: Date.now() },
      ],
    })),
  deleteSavedQuery: (id) =>
    set((state) => ({
      savedQueries: state.savedQueries.filter((q) => q.id !== id),
    })),
  updateSavedQuery: (id, updates) =>
    set((state) => ({
      savedQueries: state.savedQueries.map((q) =>
        q.id === id ? { ...q, ...updates } : q
      ),
    })),
  setIsExecuting: (executing) => set({ isExecuting: executing }),
  setQueryError: (error) => set({ queryError: error }),
  clearResults: () => set({ queryResults: null, queryError: null }),
});
