export interface QueryResult<T = Record<string, unknown>> {
  totalSize: number;
  done: boolean;
  records: T[];
  nextRecordsUrl?: string;
}

export interface SObject {
  Id: string;
  Name?: string;
  attributes: {
    type: string;
    url: string;
  };
  [key: string]: unknown;
}

export interface DescribeGlobalResult {
  sobjects: DescribeGlobalSObjectResult[];
}

export interface DescribeGlobalSObjectResult {
  name: string;
  label: string;
  labelPlural: string;
  keyPrefix: string | null;
  custom: boolean;
  customSetting: boolean;
  queryable: boolean;
  createable: boolean;
  updateable: boolean;
  deletable: boolean;
}

export interface DescribeSObjectResult {
  name: string;
  label: string;
  labelPlural: string;
  keyPrefix: string;
  custom: boolean;
  fields: FieldDescribe[];
  childRelationships: ChildRelationship[];
  recordTypeInfos: RecordTypeInfo[];
}

export interface FieldDescribe {
  name: string;
  label: string;
  type: FieldType;
  length: number;
  precision: number;
  scale: number;
  nillable: boolean;
  createable: boolean;
  updateable: boolean;
  custom: boolean;
  calculated: boolean;
  autoNumber: boolean;
  externalId: boolean;
  unique: boolean;
  defaultValue: unknown;
  picklistValues: PicklistValue[];
  referenceTo: string[];
  relationshipName: string | null;
  inlineHelpText: string | null;
  formulaTreatNullNumberAsZero: boolean;
}

export type FieldType =
  | 'string'
  | 'boolean'
  | 'int'
  | 'double'
  | 'date'
  | 'datetime'
  | 'time'
  | 'currency'
  | 'percent'
  | 'phone'
  | 'email'
  | 'url'
  | 'textarea'
  | 'picklist'
  | 'multipicklist'
  | 'reference'
  | 'id'
  | 'base64'
  | 'address'
  | 'combobox'
  | 'encryptedstring'
  | 'location'
  | 'anyType';

export interface PicklistValue {
  value: string;
  label: string;
  active: boolean;
  defaultValue: boolean;
}

export interface ChildRelationship {
  childSObject: string;
  field: string;
  relationshipName: string | null;
  cascadeDelete: boolean;
}

export interface RecordTypeInfo {
  recordTypeId: string;
  name: string;
  available: boolean;
  defaultRecordTypeMapping: boolean;
}

export interface LayoutResult {
  layouts: Layout[];
}

export interface Layout {
  id: string;
  name: string;
  sections: LayoutSection[];
}

export interface LayoutSection {
  heading: string;
  columns: number;
  rows: number;
  layoutRows: LayoutRow[];
}

export interface LayoutRow {
  layoutItems: LayoutItem[];
}

export interface LayoutItem {
  label: string;
  layoutComponents: LayoutComponent[];
  required: boolean;
  editable: boolean;
}

export interface LayoutComponent {
  type: string;
  value: string;
}
