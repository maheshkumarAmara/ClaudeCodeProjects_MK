import type { StateCreator } from 'zustand';
import type { DescribeGlobalSObjectResult, DescribeSObjectResult } from '@/types/salesforce';

export interface MetadataSlice {
  objectList: DescribeGlobalSObjectResult[];
  selectedObject: string | null;
  selectedObjectDescribe: DescribeSObjectResult | null;
  metadataLoading: boolean;
  metadataError: string | null;
  setObjectList: (list: DescribeGlobalSObjectResult[]) => void;
  setSelectedObject: (name: string | null) => void;
  setSelectedObjectDescribe: (describe: DescribeSObjectResult | null) => void;
  setMetadataLoading: (loading: boolean) => void;
  setMetadataError: (error: string | null) => void;
}

export const createMetadataSlice: StateCreator<MetadataSlice> = (set) => ({
  objectList: [],
  selectedObject: null,
  selectedObjectDescribe: null,
  metadataLoading: false,
  metadataError: null,
  setObjectList: (list) => set({ objectList: list }),
  setSelectedObject: (name) => set({ selectedObject: name }),
  setSelectedObjectDescribe: (describe) => set({ selectedObjectDescribe: describe }),
  setMetadataLoading: (loading) => set({ metadataLoading: loading }),
  setMetadataError: (error) => set({ metadataError: error }),
});
