import type { StateCreator } from 'zustand';
import type { SObject, DescribeSObjectResult } from '@/types/salesforce';

export interface RecordSlice {
  currentRecord: SObject | null;
  objectDescribe: DescribeSObjectResult | null;
  editedFields: Record<string, unknown>;
  isEditing: boolean;
  isLoading: boolean;
  recordError: string | null;
  setCurrentRecord: (record: SObject | null) => void;
  setObjectDescribe: (describe: DescribeSObjectResult | null) => void;
  setEditedField: (field: string, value: unknown) => void;
  setIsEditing: (editing: boolean) => void;
  setIsLoading: (loading: boolean) => void;
  setRecordError: (error: string | null) => void;
  resetEdits: () => void;
}

export const createRecordSlice: StateCreator<RecordSlice> = (set) => ({
  currentRecord: null,
  objectDescribe: null,
  editedFields: {},
  isEditing: false,
  isLoading: false,
  recordError: null,
  setCurrentRecord: (record) => set({ currentRecord: record, recordError: null }),
  setObjectDescribe: (describe) => set({ objectDescribe: describe }),
  setEditedField: (field, value) =>
    set((state) => ({
      editedFields: { ...state.editedFields, [field]: value },
    })),
  setIsEditing: (editing) => set({ isEditing: editing }),
  setIsLoading: (loading) => set({ isLoading: loading }),
  setRecordError: (error) => set({ recordError: error }),
  resetEdits: () => set({ editedFields: {}, isEditing: false }),
});
