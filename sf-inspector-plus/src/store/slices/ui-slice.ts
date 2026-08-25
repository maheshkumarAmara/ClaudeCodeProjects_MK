import type { StateCreator } from 'zustand';

export type ActiveTab = 'soql' | 'import' | 'record' | 'metadata' | 'settings';

export interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info';
}

export interface UiSlice {
  activeTab: ActiveTab;
  toasts: Toast[];
  setActiveTab: (tab: ActiveTab) => void;
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

export const createUiSlice: StateCreator<UiSlice> = (set) => ({
  activeTab: 'soql',
  toasts: [],
  setActiveTab: (tab) => set({ activeTab: tab }),
  addToast: (toast) =>
    set((state) => ({
      toasts: [...state.toasts, { ...toast, id: crypto.randomUUID() }],
    })),
  removeToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),
});
