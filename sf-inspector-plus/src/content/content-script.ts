import type { SessionInfo, DescribeField } from '@/types/messages';

// ── Session extraction ──

function extractSession(): SessionInfo | null {
  const cookies = document.cookie.split(';').reduce<Record<string, string>>((acc, cookie) => {
    const trimmed = cookie.trim();
    const eqIndex = trimmed.indexOf('=');
    if (eqIndex < 1) return acc;
    const key = trimmed.substring(0, eqIndex).trim();
    const value = trimmed.substring(eqIndex + 1).trim();
    if (key && value) acc[key] = value;
    return acc;
  }, {});

  const sid = cookies['sid'];
  if (!sid) return null;

  return {
    sid,
    instanceUrl: window.location.origin,
    orgId: sid.substring(0, 15),
    userId: '',
    apiVersion: '60.0',
  };
}

function sendSession(): void {
  const session = extractSession();
  if (session) {
    chrome.runtime.sendMessage({ type: 'SESSION_EXTRACTED', payload: session });
  }
}

sendSession();

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'SESSION_REQUEST') {
    sendSession();
  }
});

// ── URL navigation observer ──

let lastUrl = location.href;
const urlObserver = new MutationObserver(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    const match = location.pathname.match(/\/lightning\/r\/(\w+)\/(\w{15,18})\/view/);
    chrome.runtime.sendMessage({
      type: 'PAGE_NAVIGATED',
      payload: {
        url: location.href,
        objectName: match?.[1],
        recordId: match?.[2],
      },
    });

    if (apiNamesVisible) {
      setTimeout(() => applyApiNames(), 1500);
    }
  }
});

urlObserver.observe(document.body, { childList: true, subtree: true });

// ── Show API Name feature ──

let apiNamesVisible = false;
let cachedDescribes = new Map<string, DescribeField[]>();
const BADGE_CLASS = 'sfip-api-name-badge';
const TOOLTIP_CLASS = 'sfip-field-tooltip';

function injectStyles(): void {
  if (document.getElementById('sfip-inline-styles')) return;

  const style = document.createElement('style');
  style.id = 'sfip-inline-styles';
  style.textContent = `
    .${BADGE_CLASS} {
      display: inline-block;
      background: linear-gradient(135deg, #032d60, #0176d3);
      color: #fff;
      font-size: 10px;
      font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
      padding: 1px 5px;
      border-radius: 3px;
      margin-left: 4px;
      vertical-align: middle;
      line-height: 1.4;
      font-weight: 500;
      letter-spacing: 0.2px;
      cursor: pointer;
      transition: opacity 0.15s;
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .${BADGE_CLASS}:hover {
      opacity: 0.85;
    }

    .${BADGE_CLASS}.custom-field {
      background: linear-gradient(135deg, #6b21a8, #9333ea);
    }

    .${BADGE_CLASS}.formula-field {
      background: linear-gradient(135deg, #b45309, #f59e0b);
      color: #1c1917;
    }

    .${TOOLTIP_CLASS} {
      position: absolute;
      z-index: 10000;
      background: #032d60;
      color: #fff;
      font-size: 11px;
      font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
      padding: 8px 12px;
      border-radius: 6px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
      max-width: 320px;
      word-wrap: break-word;
      white-space: pre-wrap;
      line-height: 1.5;
      pointer-events: none;
    }

    .${TOOLTIP_CLASS} .tt-label {
      color: #93c5fd;
      font-size: 10px;
    }

    .${TOOLTIP_CLASS} .tt-value {
      color: #fff;
      font-weight: 600;
    }

    .${TOOLTIP_CLASS} .tt-row {
      margin-bottom: 3px;
    }

    .${TOOLTIP_CLASS} .tt-formula {
      margin-top: 4px;
      padding-top: 4px;
      border-top: 1px solid rgba(255,255,255,0.2);
      color: #fde68a;
      font-size: 10px;
    }

    #sfip-toggle-btn {
      position: fixed;
      bottom: 12px;
      right: 12px;
      z-index: 99999;
      width: 42px;
      height: 42px;
      border-radius: 50%;
      border: 2px solid #fff;
      background: #0176d3;
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      font-family: SFMono-Regular, Consolas, monospace;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s, transform 0.15s;
      line-height: 1;
    }

    #sfip-toggle-btn:hover {
      background: #032d60;
      transform: scale(1.08);
    }

    #sfip-toggle-btn.active {
      background: #2e844a;
      border-color: #fff;
    }

    #sfip-toggle-btn.active:hover {
      background: #1b5e20;
    }
  `;
  document.head.appendChild(style);
}

function createToggleButton(): void {
  if (document.getElementById('sfip-toggle-btn')) return;

  injectStyles();

  const btn = document.createElement('button');
  btn.id = 'sfip-toggle-btn';
  btn.textContent = 'API';
  btn.title = 'Toggle API field names (SF Inspector Plus)';
  btn.addEventListener('click', toggleApiNames);
  document.body.appendChild(btn);
}

async function toggleApiNames(): Promise<void> {
  const btn = document.getElementById('sfip-toggle-btn');

  if (apiNamesVisible) {
    removeApiNames();
    apiNamesVisible = false;
    btn?.classList.remove('active');
  } else {
    apiNamesVisible = true;
    btn?.classList.add('active');
    await applyApiNames();
  }
}

function getObjectNameFromUrl(): string | null {
  const match = location.pathname.match(/\/lightning\/r\/([A-Za-z_]\w*)\/\w{15,18}\/view/);
  if (match) return match[1];

  const setupMatch = location.pathname.match(/\/lightning\/setup\/ObjectManager\/([A-Za-z_]\w*)\//);
  if (setupMatch) return setupMatch[1];

  return null;
}

async function fetchDescribe(objectName: string): Promise<DescribeField[]> {
  if (cachedDescribes.has(objectName)) {
    return cachedDescribes.get(objectName)!;
  }

  const response = await chrome.runtime.sendMessage({
    type: 'DESCRIBE_REQUEST',
    payload: { objectName },
  });

  if (response?.payload) {
    cachedDescribes.set(objectName, response.payload);
    return response.payload;
  }

  throw new Error(response?.error || 'Failed to describe object');
}

function buildLabelMap(fields: DescribeField[]): Map<string, DescribeField[]> {
  const map = new Map<string, DescribeField[]>();
  for (const field of fields) {
    const label = field.label.trim().toLowerCase();
    if (!map.has(label)) {
      map.set(label, []);
    }
    map.get(label)!.push(field);
  }
  return map;
}

async function applyApiNames(): Promise<void> {
  const objectName = getObjectNameFromUrl();
  if (!objectName) return;

  let fields: DescribeField[];
  try {
    fields = await fetchDescribe(objectName);
  } catch {
    return;
  }

  const labelMap = buildLabelMap(fields);

  removeApiNames();

  // Lightning Experience field labels selectors
  const labelSelectors = [
    'span.test-id__field-label',
    '.slds-form-element__label',
    'label.slds-form-element__label',
    '.slds-form-element__legend',
    'th.labelCol',
    'td.labelCol',
    '.uiLabel',
    'records-record-layout-item .slds-form-element__label',
    '.forceOutputLookup .slds-form-element__label',
    'records-highlights-details-item .slds-text-title',
    'lightning-output-field .slds-form-element__label',
    'lightning-input-field .slds-form-element__label',
  ];

  const selector = labelSelectors.join(', ');
  const labelElements = document.querySelectorAll(selector);

  labelElements.forEach((el) => {
    const text = extractLabelText(el).trim().toLowerCase();
    if (!text) return;

    let matchedFields = labelMap.get(text);
    if (!matchedFields) {
      for (const [label, flds] of labelMap) {
        if (label.endsWith(text) || text.endsWith(label)) {
          matchedFields = flds;
          break;
        }
      }
    }

    if (!matchedFields || matchedFields.length === 0) return;

    for (const field of matchedFields) {
      const badge = document.createElement('span');
      badge.className = BADGE_CLASS;
      if (field.custom) badge.classList.add('custom-field');
      if (field.calculated || field.calculatedFormula) badge.classList.add('formula-field');
      badge.textContent = field.name;
      badge.title = field.name;

      badge.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard.writeText(field.name);
        showCopiedFeedback(badge);
      });

      badge.addEventListener('mouseenter', (e) => showFieldTooltip(e, field));
      badge.addEventListener('mouseleave', hideFieldTooltip);

      el.appendChild(badge);
    }
  });
}

function extractLabelText(el: Element): string {
  let text = '';
  for (const node of el.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      text += node.textContent || '';
    }
  }

  if (!text.trim()) {
    const firstTextEl = el.querySelector('span:not(.sfip-api-name-badge)');
    if (firstTextEl) {
      text = firstTextEl.textContent || '';
    }
  }

  if (!text.trim()) {
    text = el.textContent || '';
    text = text.replace(/\bsfip\b/gi, '').trim();
  }

  return text;
}

function removeApiNames(): void {
  document.querySelectorAll(`.${BADGE_CLASS}`).forEach((el) => el.remove());
  hideFieldTooltip();
}

function showCopiedFeedback(badge: HTMLElement): void {
  const original = badge.textContent;
  badge.textContent = 'Copied!';
  badge.style.background = '#2e844a';
  setTimeout(() => {
    badge.textContent = original;
    badge.style.background = '';
  }, 1200);
}

let currentTooltip: HTMLElement | null = null;

function showFieldTooltip(e: MouseEvent, field: DescribeField): void {
  hideFieldTooltip();

  const tooltip = document.createElement('div');
  tooltip.className = TOOLTIP_CLASS;

  let typeInfo = field.type;
  if (field.type === 'reference') {
    typeInfo += ' [' + field.referenceTo.join(', ') + ']';
  } else if (field.length > 0) {
    typeInfo += ` (${field.length})`;
  }
  if (field.precision > 0 || field.scale > 0) {
    typeInfo += ` (${field.precision}, ${field.scale})`;
  }

  const rows = [
    { label: 'API Name', value: field.name },
    { label: 'Type', value: typeInfo },
    { label: 'Flags', value: [
      field.custom ? 'Custom' : 'Standard',
      field.updateable ? 'Editable' : 'Read-only',
      field.nillable ? 'Nillable' : 'Required',
      field.externalId ? 'ExtId' : '',
      field.unique ? 'Unique' : '',
      field.autoNumber ? 'Auto' : '',
    ].filter(Boolean).join(', ') },
  ];

  tooltip.innerHTML = rows
    .map((r) => `<div class="tt-row"><span class="tt-label">${r.label}:</span> <span class="tt-value">${r.value}</span></div>`)
    .join('');

  if (field.calculatedFormula) {
    tooltip.innerHTML += `<div class="tt-formula">Formula: ${field.calculatedFormula}</div>`;
  }

  document.body.appendChild(tooltip);

  const rect = (e.target as HTMLElement).getBoundingClientRect();
  tooltip.style.left = Math.min(rect.left, window.innerWidth - tooltip.offsetWidth - 8) + 'px';
  tooltip.style.top = (rect.bottom + 6 + window.scrollY) + 'px';

  currentTooltip = tooltip;
}

function hideFieldTooltip(): void {
  currentTooltip?.remove();
  currentTooltip = null;
}

// ── Initialize ──

createToggleButton();
