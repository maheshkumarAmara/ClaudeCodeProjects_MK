import type { Message, SessionInfo, ApiRequestPayload, DescribeField } from '@/types/messages';

const SESSION_STORAGE_KEY = 'sfip_sessions';
const storage = chrome.storage.session ?? chrome.storage.local;

function toApiHost(instanceUrl: string): string {
  try {
    const url = new URL(instanceUrl);
    if (url.hostname.endsWith('.lightning.force.com')) {
      url.hostname = url.hostname.replace('.lightning.force.com', '.my.salesforce.com');
    }
    return url.origin;
  } catch {
    return instanceUrl;
  }
}

async function getFreshSid(instanceUrl: string): Promise<string | null> {
  const apiHost = toApiHost(instanceUrl);
  try {
    const cookie = await chrome.cookies.get({ url: apiHost, name: 'sid' });
    if (cookie?.value) return cookie.value;
  } catch { /* cookies API not available */ }

  try {
    const cookie = await chrome.cookies.get({ url: instanceUrl, name: 'sid' });
    if (cookie?.value) return cookie.value;
  } catch { /* fallback failed */ }

  return null;
}

async function loadSessions(): Promise<Map<string, SessionInfo>> {
  try {
    const result = await storage.get(SESSION_STORAGE_KEY);
    const data = result[SESSION_STORAGE_KEY] as Record<string, SessionInfo> | undefined;
    if (!data) return new Map();
    return new Map(Object.entries(data));
  } catch {
    return new Map();
  }
}

async function saveSessions(sessions: Map<string, SessionInfo>): Promise<void> {
  try {
    await storage.set({
      [SESSION_STORAGE_KEY]: Object.fromEntries(sessions),
    });
  } catch (err) {
    console.error('Failed to save sessions:', err);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  console.log('SF Inspector Plus installed');
});

let inspectorTabId: number | null = null;
let sourceTabId: number | null = null;

chrome.action.onClicked.addListener(async (clickedTab) => {
  sourceTabId = clickedTab.id ?? null;

  if (inspectorTabId !== null) {
    try {
      await chrome.tabs.update(inspectorTabId, { active: true });
      return;
    } catch {
      inspectorTabId = null;
    }
  }

  const tab = await chrome.tabs.create({
    url: chrome.runtime.getURL('src/sidepanel/index.html'),
  });
  inspectorTabId = tab.id ?? null;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === inspectorTabId) inspectorTabId = null;
  if (tabId === sourceTabId) sourceTabId = null;
});

chrome.runtime.onMessage.addListener(
  (message: Message, sender, sendResponse) => {
    handleMessage(message, sender).then(sendResponse).catch((err) => {
      console.error('Message handler error:', err);
      sendResponse({ error: err instanceof Error ? err.message : 'Internal error' });
    });
    return true;
  }
);

async function handleMessage(message: Message, sender: chrome.runtime.MessageSender): Promise<unknown> {
  switch (message.type) {
    case 'SESSION_EXTRACTED':
      return handleSessionExtracted(message.payload);

    case 'SESSION_REQUEST':
      return handleSessionRequest(sender);

    case 'SESSION_EXPIRED':
      return handleSessionExpired();

    case 'API_REQUEST':
      return handleApiRequest(message.payload);

    case 'DESCRIBE_REQUEST':
      return handleDescribeRequest(message.payload.objectName);

    default:
      return { error: 'Unknown message type' };
  }
}

async function handleSessionExtracted(session: SessionInfo): Promise<{ success: boolean }> {
  const sessions = await loadSessions();
  sessions.set(session.instanceUrl, session);
  await saveSessions(sessions);
  console.log(`Session stored for ${session.instanceUrl}`);
  return { success: true };
}

async function getSalesforceOrigin(): Promise<string | null> {
  if (sourceTabId !== null) {
    try {
      const tab = await chrome.tabs.get(sourceTabId);
      if (tab?.url) {
        const origin = new URL(tab.url).origin;
        if (!origin.startsWith('chrome')) return origin;
      }
    } catch { /* tab may have been closed */ }
  }

  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (activeTab?.url) {
    try {
      const origin = new URL(activeTab.url).origin;
      if (!origin.startsWith('chrome')) return origin;
    } catch { /* invalid URL */ }
  }

  const sfTabs = await chrome.tabs.query({ url: ['https://*.salesforce.com/*', 'https://*.force.com/*'] });
  if (sfTabs.length > 0 && sfTabs[0].url) {
    try {
      return new URL(sfTabs[0].url).origin;
    } catch { /* invalid URL */ }
  }

  return null;
}

async function findSession(): Promise<SessionInfo | null> {
  const sessions = await loadSessions();
  if (sessions.size === 0) return null;

  const origin = await getSalesforceOrigin();

  if (origin) {
    for (const [instanceUrl, session] of sessions) {
      if (origin === instanceUrl) return session;
    }

    for (const [instanceUrl, session] of sessions) {
      try {
        const storedHost = new URL(instanceUrl).hostname;
        const originHost = new URL(origin).hostname;
        const storedParts = storedHost.split('.');
        const originParts = originHost.split('.');
        if (
          storedParts[0] === originParts[0] ||
          storedHost === originHost ||
          originHost.endsWith('.' + storedHost) ||
          storedHost.endsWith('.' + originHost)
        ) {
          return session;
        }
      } catch {
        continue;
      }
    }
  }

  const [firstSession] = sessions.values();
  return firstSession ?? null;
}

async function requestSessionFromSalesforceTabs(): Promise<void> {
  const targets: number[] = [];

  if (sourceTabId !== null) targets.push(sourceTabId);

  const sfTabs = await chrome.tabs.query({ url: ['https://*.salesforce.com/*', 'https://*.force.com/*'] });
  for (const t of sfTabs) {
    if (t.id && !targets.includes(t.id)) targets.push(t.id);
  }

  for (const id of targets) {
    try {
      await chrome.tabs.sendMessage(id, { type: 'SESSION_REQUEST' });
    } catch { /* content script not loaded */ }
  }
}

async function handleSessionRequest(_sender: chrome.runtime.MessageSender): Promise<SessionInfo | null> {
  const session = await findSession();
  if (session) return session;

  await requestSessionFromSalesforceTabs();
  await new Promise((r) => setTimeout(r, 500));
  return findSession();
}

function handleSessionExpired(): { success: boolean } {
  console.log('Session expired, requesting re-extraction');
  requestSessionFromSalesforceTabs();
  return { success: true };
}

async function handleDescribeRequest(
  objectName: string
): Promise<{ payload: DescribeField[] | null; error?: string }> {
  const session = await findSession();
  if (!session) {
    return { payload: null, error: 'No active session. Navigate to a Salesforce page and refresh.' };
  }

  const freshSid = await getFreshSid(session.instanceUrl) || session.sid;
  const apiHost = toApiHost(session.instanceUrl);

  try {
    const response = await fetch(
      `${apiHost}/services/data/v${session.apiVersion}/sobjects/${objectName}/describe`,
      {
        headers: {
          Authorization: `Bearer ${freshSid}`,
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      return { payload: null, error: `HTTP ${response.status}` };
    }

    const data = await response.json();
    const fields: DescribeField[] = data.fields.map((f: Record<string, unknown>) => ({
      name: f.name,
      label: f.label,
      type: f.type,
      length: f.length,
      precision: f.precision,
      scale: f.scale,
      referenceTo: f.referenceTo,
      custom: f.custom,
      calculated: f.calculated,
      autoNumber: f.autoNumber,
      updateable: f.updateable,
      externalId: f.externalId,
      unique: f.unique,
      nillable: f.nillable,
      relationshipName: f.relationshipName,
      calculatedFormula: f.calculatedFormula,
    }));

    return { payload: fields };
  } catch (err) {
    return { payload: null, error: err instanceof Error ? err.message : 'Unknown error' };
  }
}

async function handleApiRequest(
  payload: ApiRequestPayload
): Promise<{ id: string; status: number; body: unknown; error?: string }> {
  const session = await findSession();
  if (!session) {
    return { id: payload.id, status: 401, body: null, error: 'No active session. Navigate to a Salesforce page and refresh.' };
  }

  const freshSid = await getFreshSid(session.instanceUrl) || session.sid;
  const apiHost = toApiHost(session.instanceUrl);

  try {
    const fetchOptions: RequestInit = {
      method: payload.method,
      headers: {
        Authorization: `Bearer ${freshSid}`,
        'Content-Type': 'application/json',
      },
    };

    if (payload.body && payload.method !== 'GET' && payload.method !== 'HEAD') {
      fetchOptions.body = payload.body;
    }

    const response = await fetch(`${apiHost}${payload.path}`, fetchOptions);

    let body: unknown = null;
    const contentType = response.headers.get('content-type');
    if (contentType?.includes('application/json')) {
      body = await response.json();
    } else if (response.status !== 204) {
      const text = await response.text();
      if (text) {
        if (text.trimStart().startsWith('<')) {
          return { id: payload.id, status: 401, body: null, error: 'Session expired. Refresh the Salesforce page and try again.' };
        }
        try {
          body = JSON.parse(text);
        } catch {
          body = text;
        }
      }
    }

    return { id: payload.id, status: response.status, body };
  } catch (err) {
    return {
      id: payload.id,
      status: 0,
      body: null,
      error: err instanceof Error ? err.message : 'Unknown error',
    };
  }
}
