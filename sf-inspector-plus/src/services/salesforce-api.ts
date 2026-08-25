import type { ApiResponsePayload } from '@/types/messages';
import type {
  QueryResult,
  SObject,
  DescribeGlobalResult,
  DescribeSObjectResult,
} from '@/types/salesforce';

let requestCounter = 0;

async function apiRequest(
  method: string,
  path: string,
  body?: unknown
): Promise<ApiResponsePayload> {
  const id = String(++requestCounter);
  try {
    const response = await chrome.runtime.sendMessage({
      type: 'API_REQUEST',
      payload: { id, method, path, body: body ? JSON.stringify(body) : undefined },
    });
    if (!response) {
      return { id, status: 0, body: null, error: 'No response from service worker. Try refreshing the Salesforce page.' };
    }
    return response as ApiResponsePayload;
  } catch (err) {
    return { id, status: 0, body: null, error: err instanceof Error ? err.message : 'Message sending failed' };
  }
}

export class SalesforceApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    const detail = typeof body === 'string' ? body : '';
    super(detail ? `${detail}` : `Salesforce API error (${status})`);
    this.status = status;
    this.body = body;
  }
}

async function checkedRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await apiRequest(method, path, body);
  if (response.error || response.status >= 400) {
    let errorDetail = response.error ?? '';
    const b = response.body;
    if (Array.isArray(b) && b.length > 0 && b[0]?.message) {
      errorDetail = b.map((e: { message: string }) => e.message).join('; ');
    } else if (b && typeof b === 'object' && 'message' in (b as Record<string, unknown>)) {
      errorDetail = String((b as Record<string, string>).message);
    }
    throw new SalesforceApiError(response.status, errorDetail || response.body);
  }
  return response.body as T;
}

export interface QueryOptions {
  apiVersion?: string;
  useToolingApi?: boolean;
  includeDeleted?: boolean;
}

export async function query<T = Record<string, unknown>>(
  soql: string,
  options: QueryOptions = {}
): Promise<QueryResult<T>> {
  const { apiVersion = '60.0', useToolingApi = false, includeDeleted = false } = options;
  const endpoint = useToolingApi ? 'tooling/query' : includeDeleted ? 'queryAll' : 'query';
  const getUrl = `/services/data/v${apiVersion}/${endpoint}?q=${encodeURIComponent(soql)}`;

  if (getUrl.length <= 2000) {
    return checkedRequest<QueryResult<T>>('GET', getUrl);
  }

  return checkedRequest<QueryResult<T>>(
    'POST',
    `/services/data/v${apiVersion}/${endpoint}`,
    { query: soql }
  );
}

export async function queryMore<T = Record<string, unknown>>(
  nextRecordsUrl: string
): Promise<QueryResult<T>> {
  return checkedRequest<QueryResult<T>>('GET', nextRecordsUrl);
}

export async function describeGlobal(apiVersion = '60.0'): Promise<DescribeGlobalResult> {
  return checkedRequest<DescribeGlobalResult>(
    'GET',
    `/services/data/v${apiVersion}/sobjects/`
  );
}

export async function describeSObject(
  objectName: string,
  apiVersion = '60.0'
): Promise<DescribeSObjectResult> {
  return checkedRequest<DescribeSObjectResult>(
    'GET',
    `/services/data/v${apiVersion}/sobjects/${objectName}/describe`
  );
}

export async function getRecord(
  objectName: string,
  recordId: string,
  fields: string[],
  apiVersion = '60.0'
): Promise<SObject> {
  return checkedRequest<SObject>(
    'GET',
    `/services/data/v${apiVersion}/sobjects/${objectName}/${recordId}?fields=${fields.join(',')}`
  );
}

export async function updateRecord(
  objectName: string,
  recordId: string,
  data: Record<string, unknown>,
  apiVersion = '60.0'
): Promise<void> {
  await apiRequest(
    'PATCH',
    `/services/data/v${apiVersion}/sobjects/${objectName}/${recordId}`,
    data
  );
}

export async function deleteRecord(
  objectName: string,
  recordId: string,
  apiVersion = '60.0'
): Promise<void> {
  await checkedRequest<void>(
    'DELETE',
    `/services/data/v${apiVersion}/sobjects/${objectName}/${recordId}`
  );
}

export async function toolingQuery<T = Record<string, unknown>>(
  soql: string,
  apiVersion = '60.0'
): Promise<QueryResult<T>> {
  return checkedRequest<QueryResult<T>>(
    'GET',
    `/services/data/v${apiVersion}/tooling/query?q=${encodeURIComponent(soql)}`
  );
}

export interface CompositeResult {
  id: string | null;
  success: boolean;
  errors: { statusCode: string; message: string; fields: string[] }[];
}

export async function compositeInsert(
  objectName: string,
  records: Record<string, unknown>[],
  apiVersion = '60.0'
): Promise<CompositeResult[]> {
  const body = {
    allOrNone: false,
    records: records.map((r) => ({ attributes: { type: objectName }, ...r })),
  };
  return checkedRequest<CompositeResult[]>(
    'POST',
    `/services/data/v${apiVersion}/composite/sobjects`,
    body
  );
}

export async function compositeUpdate(
  objectName: string,
  records: Record<string, unknown>[],
  apiVersion = '60.0'
): Promise<CompositeResult[]> {
  const body = {
    allOrNone: false,
    records: records.map((r) => ({ attributes: { type: objectName }, ...r })),
  };
  return checkedRequest<CompositeResult[]>(
    'PATCH',
    `/services/data/v${apiVersion}/composite/sobjects`,
    body
  );
}

export async function compositeUpsert(
  objectName: string,
  externalIdField: string,
  records: Record<string, unknown>[],
  apiVersion = '60.0'
): Promise<CompositeResult[]> {
  const body = {
    allOrNone: false,
    records: records.map((r) => ({ attributes: { type: objectName }, ...r })),
  };
  return checkedRequest<CompositeResult[]>(
    'PATCH',
    `/services/data/v${apiVersion}/composite/sobjects/${objectName}/${externalIdField}`,
    body
  );
}

export async function compositeDelete(
  ids: string[],
  apiVersion = '60.0'
): Promise<CompositeResult[]> {
  return checkedRequest<CompositeResult[]>(
    'DELETE',
    `/services/data/v${apiVersion}/composite/sobjects?ids=${ids.join(',')}&allOrNone=false`
  );
}
