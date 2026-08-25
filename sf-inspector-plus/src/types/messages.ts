export interface SessionInfo {
  sid: string;
  instanceUrl: string;
  orgId: string;
  userId: string;
  apiVersion: string;
}

export type Message =
  | { type: 'SESSION_EXTRACTED'; payload: SessionInfo }
  | { type: 'SESSION_EXPIRED' }
  | { type: 'SESSION_REQUEST' }
  | { type: 'SESSION_RESPONSE'; payload: SessionInfo | null }
  | { type: 'PAGE_NAVIGATED'; payload: { url: string; recordId?: string; objectName?: string } }
  | { type: 'API_REQUEST'; payload: ApiRequestPayload }
  | { type: 'API_RESPONSE'; payload: ApiResponsePayload }
  | { type: 'OPEN_RECORD'; payload: { recordId: string; objectName: string } }
  | { type: 'DESCRIBE_REQUEST'; payload: { objectName: string } }
  | { type: 'DESCRIBE_RESPONSE'; payload: DescribeField[] | null; error?: string };

export interface DescribeField {
  name: string;
  label: string;
  type: string;
  length: number;
  precision: number;
  scale: number;
  referenceTo: string[];
  custom: boolean;
  calculated: boolean;
  autoNumber: boolean;
  updateable: boolean;
  externalId: boolean;
  unique: boolean;
  nillable: boolean;
  relationshipName: string | null;
  calculatedFormula: string | null;
}

export interface ApiRequestPayload {
  id: string;
  method: string;
  path: string;
  body?: string;
}

export interface ApiResponsePayload {
  id: string;
  status: number;
  body: unknown;
  error?: string;
}
