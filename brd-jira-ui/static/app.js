/* BRD–Jira Validator — frontend */

let _allRows = [];
let _pollTimer = null;

// Active filters
let _filterSection = '';
let _filterVStatus = '';
let _filterPriority = '';
let _filterBStatus = '';
let _filterSearch = '';

// BRD section → short code (for auto-generating requirement IDs)
const SECTION_CODES = {
  'OM': 'OM', 'Order Management': 'OM', 'Order Mgmt': 'OM',
  'Revenue': 'REV', 'Revenue & Invoice': 'REV',
  'CS': 'CS', 'Customer Success': 'CS',
  'Customer Support': 'CSP',
  'Opportunity': 'OPP', 'Opportunity Mgmt': 'OPP', 'Opportunity Management': 'OPP',
  'NPI': 'NPI',
  'Quoting': 'CPQ', 'CPQ & PDM': 'CPQ', 'CPQ': 'CPQ',
  'General': 'GEN',
  'Marketing': 'MKT',
  'Finance': 'FIN', 'Finance & Forecasting': 'FIN',
  'Engineering': 'ENG',
  'Billing': 'BIL', 'Billing Operations': 'BIL',
  'Commissions': 'COM',
  'Renewals': 'RNW',
  'Assets': 'AST', 'Assets & Entitlements': 'AST',
  'BI': 'BI', 'BI/Reporting': 'BI', 'BI / Reporting': 'BI', 'Reporting': 'BI',
};

const SECTION_ICONS = {
  'OM': '📦', 'Order Management': '📦', 'Order Mgmt': '📦',
  'Revenue': '💰', 'Revenue & Invoice': '💰',
  'CS': '🎯', 'Customer Success': '🎯',
  'Customer Support': '🎧',
  'Opportunity': '💼', 'Opportunity Mgmt': '💼', 'Opportunity Management': '💼',
  'NPI': '🚀',
  'Quoting': '📊', 'CPQ & PDM': '📊', 'CPQ': '📊',
  'General': '📋',
  'Marketing': '📣',
  'Finance': '💵', 'Finance & Forecasting': '💵',
  'Engineering': '⚙️',
  'Billing': '🧾', 'Billing Operations': '🧾',
  'Commissions': '💳',
  'Renewals': '🔄',
  'Assets': '🗃️', 'Assets & Entitlements': '🗃️',
  'BI': '📈', 'BI/Reporting': '📈', 'BI / Reporting': '📈', 'Reporting': '📈',
};

// ── Init ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initDropZone();
  initValidateButtons();
  initFilters();
  initJiraLookup();
  initDiff();
  loadHealth();

  document.getElementById('new-brd-btn').addEventListener('click', () => {
    document.getElementById('app-layout').classList.add('hidden');
    document.getElementById('landing').classList.remove('hidden');
    hideError();
    hideProgress();
    clearInterval(_pollTimer);
  });
});

// ── Health check ─────────────────────────────────────────────────────
async function loadHealth() {
  try {
    const r = await fetch('/api/health');
    const d = await r.json();
    const label = d.claude ? '🤖 Claude API' : '🔤 Keyword Analysis';
    document.getElementById('engine-badge').textContent = label;
    document.getElementById('engine-badge').classList.remove('hidden');
    document.getElementById('engine-badge-app').textContent = d.claude ? '🤖 Claude' : '🔤 Keyword';
    document.getElementById('engine-badge-app').classList.remove('hidden');
  } catch {}
}

// ── Tabs ──────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });
}

// ── Drop zone ─────────────────────────────────────────────────────────
let _selectedFile = null;

function initDropZone() {
  const zone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const fileNameEl = document.getElementById('file-name');
  const validateBtn = document.getElementById('validate-file-btn');

  function setFile(file) {
    if (!file || !file.name.endsWith('.docx')) { alert('Please select a .docx file'); return; }
    _selectedFile = file;
    fileNameEl.textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    fileNameEl.classList.remove('hidden');
    validateBtn.disabled = false;
  }

  fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
  zone.addEventListener('click', () => fileInput.click());
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('dragover');
    setFile(e.dataTransfer.files[0]);
  });
}

// ── Validate buttons ──────────────────────────────────────────────────
function initValidateButtons() {
  document.getElementById('validate-url-btn').addEventListener('click', () => {
    const url = document.getElementById('brd-url').value.trim();
    if (!url) { alert('Please enter a Google Drive URL'); return; }
    startValidation({ brd_url: url });
  });
  document.getElementById('validate-file-btn').addEventListener('click', () => {
    if (!_selectedFile) return;
    startValidation({ file: _selectedFile });
  });
}

async function startValidation(input) {
  showProgress('Starting analysis...');
  hideError();
  const fd = new FormData();
  if (input.brd_url) fd.append('brd_url', input.brd_url);
  if (input.file) fd.append('file', input.file);
  try {
    const r = await fetch('/api/validate', { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Validation failed');
    pollJob(d.job_id);
  } catch (e) {
    showError(e.message);
    hideProgress();
  }
}

function pollJob(jobId) {
  clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    try {
      const r = await fetch(`/api/job/${jobId}`);
      const d = await r.json();
      updateProgress(d.progress || 'Processing...');
      if (d.status === 'done') {
        clearInterval(_pollTimer);
        hideProgress();
        renderResults(d.result);
      } else if (d.status === 'error') {
        clearInterval(_pollTimer);
        hideProgress();
        showError(d.error || 'Analysis failed. Check server logs.');
      }
    } catch {}
  }, 1500);
}

// ── Filter event delegation ────────────────────────────────────────────
function initFilters() {
  document.addEventListener('click', e => {
    const priorityBtn = e.target.closest('.pill[data-priority]');
    if (priorityBtn) {
      _filterPriority = priorityBtn.dataset.priority;
      document.querySelectorAll('.pill[data-priority]').forEach(b => b.classList.toggle('active', b === priorityBtn));
      applyFilters(); return;
    }
    const bstatusBtn = e.target.closest('.pill[data-bstatus]');
    if (bstatusBtn) {
      _filterBStatus = bstatusBtn.dataset.bstatus;
      document.querySelectorAll('.pill[data-bstatus]').forEach(b => b.classList.toggle('active', b === bstatusBtn));
      applyFilters(); return;
    }
    const sectionItem = e.target.closest('.sidebar-item[data-section]');
    if (sectionItem) {
      _filterSection = sectionItem.dataset.section;
      document.querySelectorAll('.sidebar-item[data-section]').forEach(el => el.classList.toggle('active', el === sectionItem));
      updateContentTitle();
      applyFilters(); return;
    }
    const vstatusItem = e.target.closest('.sidebar-item[data-vstatus]');
    if (vstatusItem) {
      _filterVStatus = vstatusItem.dataset.vstatus;
      document.querySelectorAll('.sidebar-item[data-vstatus]').forEach(el => el.classList.toggle('active', el === vstatusItem));
      applyFilters(); return;
    }
  });

  document.getElementById('search-input').addEventListener('input', e => {
    _filterSearch = e.target.value.toLowerCase();
    applyFilters();
  });
}

// ── Apply all active filters ───────────────────────────────────────────
function applyFilters() {
  closeAccordion();
  const rows = document.querySelectorAll('#req-tbody tr');
  let visible = 0;
  rows.forEach(tr => {
    const row = _allRows[parseInt(tr.dataset.index)];
    if (!row) return;
    const matchSection = !_filterSection || row.section === _filterSection;
    const matchVStatus = !_filterVStatus || row.status === _filterVStatus;
    const matchPriority = !_filterPriority || (row.priority_brd || '').toLowerCase().includes(_filterPriority.toLowerCase());
    const matchBStatus = !_filterBStatus || (row.status_brd || '').toLowerCase().includes(_filterBStatus.toLowerCase());
    const matchSearch = !_filterSearch ||
      (row._req_id || '').toLowerCase().includes(_filterSearch) ||
      row.jira_ids.some(id => id.toLowerCase().includes(_filterSearch)) ||
      (row.fields.what || '').toLowerCase().includes(_filterSearch) ||
      (row.fields.functional || '').toLowerCase().includes(_filterSearch);
    const show = matchSection && matchVStatus && matchPriority && matchBStatus && matchSearch;
    tr.classList.toggle('hidden', !show);
    if (show) visible++;
  });
  document.getElementById('filter-count').textContent = `${visible} requirement${visible !== 1 ? 's' : ''}`;
  document.getElementById('no-results').classList.toggle('hidden', visible > 0);
}

function updateContentTitle() {
  document.getElementById('content-title').textContent =
    _filterSection ? `${_filterSection} Requirements` : 'All Business Requirements';
}

// ── Render results ─────────────────────────────────────────────────────
function renderResults(data) {
  _allRows = data.rows;

  // Generate sequential requirement IDs per section
  const sectionCounters = {};
  _allRows.forEach(row => {
    const code = getSectionCode(row.section);
    sectionCounters[code] = (sectionCounters[code] || 0) + 1;
    row._req_id = `${code}-${String(sectionCounters[code]).padStart(2, '0')}`;
  });

  // Summary counts
  document.getElementById('sum-total').textContent = data.total;
  document.getElementById('sum-green').textContent = data.summary.GREEN || 0;
  document.getElementById('sum-yellow').textContent = data.summary.YELLOW || 0;
  document.getElementById('sum-red').textContent = data.summary.RED || 0;
  document.getElementById('sum-nojira').textContent = data.summary.NO_JIRA || 0;

  // Sidebar sections
  const sidebarSections = document.getElementById('sidebar-sections');
  sidebarSections.innerHTML = `
    <li class="sidebar-item active" data-section="">
      <span>🏠</span> All Requirements
      <span class="sidebar-count">${data.total}</span>
    </li>`;

  const sectionGroups = {};
  _allRows.forEach(row => { sectionGroups[row.section] = (sectionGroups[row.section] || 0) + 1; });
  Object.entries(sectionGroups).sort(([a], [b]) => a.localeCompare(b)).forEach(([section, count]) => {
    const li = document.createElement('li');
    li.className = 'sidebar-item';
    li.dataset.section = section;
    li.innerHTML = `<span>${SECTION_ICONS[section] || '📄'}</span> ${esc(section)}<span class="sidebar-count">${count}</span>`;
    sidebarSections.appendChild(li);
  });

  // Build table rows
  const tbody = document.getElementById('req-tbody');
  tbody.innerHTML = '';
  _allRows.forEach(row => {
    const tr = document.createElement('tr');
    tr.dataset.index = row.index;

    const reqText = (row.fields.what || row.fields.functional || '').substring(0, 200);

    const jiraHtml = row.jira_ids.length
      ? row.jira_ids.map(id => {
          const t = row.tickets && row.tickets.find(t => t.key === id);
          const url = t ? t.url : `#`;
          return `<a href="${url}" target="_blank" class="jira-id-chip" onclick="event.stopPropagation()">${esc(id)}</a>`;
        }).join(' ')
      : '<span class="no-jira-text">No Jira</span>';

    const issuesPreview = row.issues && row.issues.length
      ? `<div class="req-issues-preview">
           ${row.issues.slice(0, 1).map(i => `<span class="issue-tag issue-${i.type}">${i.type}</span>`).join('')}
           ${row.issues.length > 1 ? `<span class="more-issues">+${row.issues.length - 1} more</span>` : ''}
         </div>`
      : '';

    tr.innerHTML = `
      <td class="col-id">
        <div class="req-id-wrap">
          <span class="req-id">${esc(row._req_id)}</span>
          <span class="val-dot val-${row.status}" title="${statusLabel(row.status)}"></span>
        </div>
        <div class="req-jira-ids">${jiraHtml}</div>
      </td>
      <td>
        <div class="req-text">${esc(reqText) || '<span class="empty-text">No requirement text</span>'}</div>
        ${issuesPreview}
      </td>
      <td class="col-priority">${priorityBadge(row.priority_brd)}</td>
      <td class="col-status">${bStatusBadge(row.status_brd)}</td>
      <td class="col-arr"><span class="expand-arrow">▶</span></td>
    `;

    tr.addEventListener('click', () => toggleAccordion(tr, row));
    tbody.appendChild(tr);
  });

  // Reset filter state
  _filterSection = ''; _filterVStatus = ''; _filterPriority = ''; _filterBStatus = ''; _filterSearch = '';
  document.getElementById('search-input').value = '';
  document.getElementById('content-title').textContent = 'All Business Requirements';
  document.querySelectorAll('.pill[data-priority]').forEach(p => p.classList.toggle('active', p.dataset.priority === ''));
  document.querySelectorAll('.pill[data-bstatus]').forEach(p => p.classList.toggle('active', p.dataset.bstatus === ''));
  document.querySelectorAll('.sidebar-item[data-vstatus]').forEach(el => el.classList.toggle('active', el.dataset.vstatus === ''));

  // Switch to app layout
  document.getElementById('landing').classList.add('hidden');
  document.getElementById('app-layout').classList.remove('hidden');

  // Show sign-off progress
  document.getElementById('signoff-progress-wrap').style.display = 'flex';
  updateSignoffProgress();

  applyFilters();
}

// ── Badge helpers ──────────────────────────────────────────────────────
function getSectionCode(section) {
  if (SECTION_CODES[section]) return SECTION_CODES[section];
  const letters = section.replace(/[^A-Z]/g, '');
  return letters.substring(0, 3) || section.substring(0, 3).toUpperCase() || 'GEN';
}

function priorityBadge(priority) {
  const p = (priority || '').trim();
  if (!p) return '<span class="empty-text">—</span>';
  const cls = p.toLowerCase().includes('must') ? 'priority-must' :
               p.toLowerCase().includes('should') ? 'priority-should' :
               p.toLowerCase().includes('nice') ? 'priority-nice' : 'priority-other';
  return `<span class="priority-badge ${cls}">${esc(p)}</span>`;
}

function bStatusBadge(status) {
  const s = (status || '').trim();
  if (!s) return '<span class="empty-text">—</span>';
  const sl = s.toLowerCase();
  const cls = sl.includes('finalized') ? 'bstatus-finalized' :
               sl.includes('review') ? 'bstatus-review' :
               sl.includes('blocked') ? 'bstatus-blocked' :
               sl.includes('refin') ? 'bstatus-refining' :
               sl.includes('incomplete') ? 'bstatus-incomplete' :
               sl.includes('not written') ? 'bstatus-notwritten' :
               sl.includes('deferred') ? 'bstatus-deferred' :
               sl.includes('cancelled') ? 'bstatus-cancelled' : 'bstatus-other';
  return `<span class="bstatus-badge ${cls}">${esc(s)}</span>`;
}

// ── Inline accordion ───────────────────────────────────────────────────
let _openAccordionTr = null;

function toggleAccordion(tr, row) {
  if (_openAccordionTr === tr) { closeAccordion(); return; }
  closeAccordion();
  _openAccordionTr = tr;
  tr.classList.add('accordion-open');
  const arrow = tr.querySelector('.expand-arrow');
  if (arrow) arrow.textContent = '▼';

  const detailTr = document.createElement('tr');
  detailTr.className = 'accordion-detail-row';
  detailTr.innerHTML = `<td colspan="5" class="accordion-td">${buildAccordionPanel(row)}</td>`;
  tr.after(detailTr);
}

function closeAccordion() {
  if (!_openAccordionTr) return;
  _openAccordionTr.classList.remove('accordion-open');
  const arrow = _openAccordionTr.querySelector('.expand-arrow');
  if (arrow) arrow.textContent = '▶';
  const next = _openAccordionTr.nextElementSibling;
  if (next && next.classList.contains('accordion-detail-row')) next.remove();
  _openAccordionTr = null;
}

function buildAccordionPanel(row) {
  const f = row.fields;
  const reqId = row._req_id || String(row.index);
  let html = '<div class="acc-panel">';

  // ── QA Analysis bar ──────────────────────────────────────────────────
  const tb   = row.testability || {};
  const acg  = row.ac_gap      || {};
  const so   = getSignoff(reqId);

  const tbClass = tb.label === 'Testable' ? 'tb-testable' :
                  tb.label === 'Needs Clarification' ? 'tb-needs' : 'tb-untestable';
  const acClass = acg.status === 'OK' ? 'acg-ok' :
                  acg.status === 'WEAK_AC' ? 'acg-weak' :
                  acg.status === 'MISALIGNED' ? 'acg-mis' :
                  acg.status === 'NO_AC' ? 'acg-no' : 'acg-na';
  const soClass = { 'Passed': 'so-passed', 'Blocked': 'so-blocked',
                    'In Testing': 'so-testing', 'Test Planned': 'so-planned' }[so.status] || 'so-default';

  const jiraAc  = (row.tickets || []).map(t => t.acceptance_criteria || '').filter(Boolean).join(' ');
  const reqText = f.what || f.functional || '';

  html += `<div class="qa-analysis-bar">
    <div class="qa-bar-left">
      <div class="qa-badge-group">
        <span class="qa-badge-label">Testability</span>
        <span class="tb-badge ${tbClass}" title="${tb.issues && tb.issues.length ? tb.issues.join(' | ') : ''}">
          ${tb.score !== undefined ? tb.score + '% · ' : ''}${esc(tb.label || '—')}
        </span>
      </div>
      <div class="qa-badge-group">
        <span class="qa-badge-label">AC Coverage</span>
        <span class="acg-badge ${acClass}" title="${esc(acg.detail || '')}">
          ${{ OK: '✅ OK', NO_AC: '❌ No AC', WEAK_AC: '⚠️ Weak AC', MISALIGNED: '⚠️ Misaligned', 'N/A': '— N/A' }[acg.status] || acg.status}
        </span>
      </div>
      <div class="qa-badge-group">
        <span class="qa-badge-label">QA Sign-off</span>
        <select class="signoff-select ${soClass}" data-req-id="${esc(reqId)}"
          onchange="setSignoff('${esc(reqId)}', this.value); this.className='signoff-select '+signoffClass(this.value)">
          ${['Not Started','Test Planned','In Testing','Passed','Blocked'].map(s =>
            `<option value="${s}"${so.status === s ? ' selected' : ''}>${s}</option>`
          ).join('')}
        </select>
      </div>
    </div>
    <div class="qa-bar-right">
      ${reqText ? `<button class="btn-gen-tests" onclick="generateTests('${esc(reqId)}', ${JSON.stringify(reqText).replace(/'/g,"\\'")} , ${JSON.stringify(jiraAc).replace(/'/g,"\\'")} , '${esc(row.section || '')}')">🤖 Generate Test Scenarios</button>` : ''}
    </div>
  </div>`;

  // Testability issues (if any)
  if (tb.issues && tb.issues.length) {
    html += `<div class="tb-issues-bar">
      <span class="tb-issues-title">Testability Gaps:</span>
      ${tb.issues.map(i => `<span class="tb-issue-chip">${esc(i)}</span>`).join('')}
    </div>`;
  }

  // Test scenarios placeholder
  html += `<div id="scenarios-${esc(reqId)}" class="scenarios-section" style="display:none;"></div>`;

  // Issues banner
  if (row.issues && row.issues.length) {
    html += `<div class="acc-issues">
      <div class="acc-issues-title">⚠️ ${row.issues.length} Issue${row.issues.length > 1 ? 's' : ''} Found</div>
      ${row.issues.map(i => `<div class="issue-item"><span class="issue-tag issue-${i.type}">${i.type}</span><span class="issue-detail">${esc(i.detail)}</span></div>`).join('')}
    </div>`;
  }

  // Main BRD fields
  const mainFields = [
    ['WHAT (REQUIREMENT)', f.what],
    ['WHY (BENEFIT)', f.why],
    ['TO-BE (DESIRED STATE)', f.to_be],
    ['FUNCTIONAL REQUIREMENTS', f.functional],
    ['ACCEPTANCE CRITERIA', f.acceptance],
    ['CONDITIONS', f.conditions],
    ['EXCEPTIONS', f.exceptions],
    ['ASSUMPTIONS', f.assumptions],
  ].filter(([, v]) => v);

  html += '<div class="acc-fields">';
  mainFields.forEach(([label, val]) => {
    html += `<div class="acc-field">
      <div class="acc-field-label">${label}</div>
      <div class="acc-field-value">${esc(val)}</div>
    </div>`;
  });
  html += '</div>';

  // Meta row: Dependencies | Who | As-Is
  const metaFields = [
    ['DEPENDENCIES', f.dependencies],
    ['WRITTEN BY / AFFECTED USERS', f.who],
    ['AS-IS STATE', f.as_is],
  ].filter(([, v]) => v);

  if (metaFields.length) {
    html += '<div class="acc-meta-row">';
    metaFields.forEach(([label, val]) => {
      html += `<div class="acc-meta-item">
        <div class="acc-field-label">${label}</div>
        <div class="acc-field-value">${esc(val)}</div>
      </div>`;
    });
    html += '</div>';
  }

  // Jira comparison (if tickets present)
  if (row.tickets && row.tickets.length) {
    const brdContent = mainFields.map(([lbl, val]) =>
      `<div class="compare-field"><div class="compare-field-label">${lbl}</div><div class="compare-field-value">${esc(val)}</div></div>`
    ).join('') || '<span class="empty-text">No structured content</span>';

    const jiraContent = row.tickets.map(t =>
      `<div class="compare-field">
        <div class="compare-field-label"><a href="${t.url}" target="_blank">${esc(t.key)}</a> — ${esc(t.issue_type)} — ${esc(t.summary.substring(0, 80))}</div>
        <div class="compare-field-value">${esc(t.description) || '<span class="empty-text">No description</span>'}</div>
        ${t.acceptance_criteria ? `<div class="compare-field-label" style="margin-top:8px">Acceptance Criteria</div><div class="compare-field-value">${esc(t.acceptance_criteria)}</div>` : ''}
      </div>`
    ).join('<hr style="border:none;border-top:1px solid #e2e8f0;margin:12px 0">');

    const parents = row.tickets.filter(t => t.parent).map(t => t.parent);
    const parentContent = parents.length
      ? parents.map(p =>
          `<div class="compare-field">
            <div class="compare-field-label"><a href="${p.url}" target="_blank">${esc(p.key)}</a> — ${esc(p.summary.substring(0, 80))}</div>
            <div class="compare-field-value">${esc(p.description) || '<span class="empty-text">No description</span>'}</div>
            ${p.acceptance_criteria ? `<div class="compare-field-label" style="margin-top:8px">Acceptance Criteria</div><div class="compare-field-value">${esc(p.acceptance_criteria)}</div>` : ''}
          </div>`
        ).join('<hr style="border:none;border-top:1px solid #e2e8f0;margin:12px 0">')
      : '<span class="empty-text">No parent ticket</span>';

    html += `<div class="acc-jira-section">
      <div class="acc-jira-title">Jira Comparison</div>
      <div class="compare-grid">
        <div class="compare-col"><div class="compare-col-header brd">BRD</div><div class="compare-col-body">${brdContent}</div></div>
        <div class="compare-col"><div class="compare-col-header jira">Jira Tickets</div><div class="compare-col-body">${jiraContent || '<span class="empty-text">No tickets</span>'}</div></div>
        <div class="compare-col"><div class="compare-col-header parent">Parent Jira</div><div class="compare-col-body">${parentContent}</div></div>
      </div>
    </div>`;
  }

  html += '</div>';
  return html;
}

// ── UI helpers ─────────────────────────────────────────────────────────
function showProgress(msg) {
  document.getElementById('progress-wrap').classList.remove('hidden');
  document.getElementById('progress-text').textContent = msg;
}
function updateProgress(msg) { document.getElementById('progress-text').textContent = msg; }
function hideProgress() { document.getElementById('progress-wrap').classList.add('hidden'); }
function showError(msg) {
  document.getElementById('error-msg').textContent = msg;
  document.getElementById('error-banner').classList.remove('hidden');
  const isAccessError = msg.includes('private') || msg.includes('access denied') || msg.includes('401') || msg.includes('403');
  const actionEl = document.getElementById('error-action');
  actionEl.classList.toggle('hidden', !isAccessError);
  if (isAccessError) {
    document.getElementById('switch-upload-btn').onclick = () => {
      document.getElementById('error-banner').classList.add('hidden');
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      document.querySelector('.tab[data-tab="upload"]').classList.add('active');
      document.getElementById('tab-upload').classList.add('active');
    };
  }
}
function hideError() { document.getElementById('error-banner').classList.add('hidden'); }

function statusLabel(s) {
  return { GREEN: '✅ Match', YELLOW: '⚠️ Partial', RED: '❌ Mismatch', NO_JIRA: '⬜ No Jira' }[s] || s;
}

function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/\n/g, '<br>');
}

// ── Jira ID Lookup ─────────────────────────────────────────────────────

function initJiraLookup() {
  const input = document.getElementById('jira-lookup-input');
  if (input) {
    input.addEventListener('keydown', e => { if (e.key === 'Enter') triggerLookup(); });
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeCompareDrawer(); });
}

async function triggerLookup() {
  const input  = document.getElementById('jira-lookup-input');
  const status = document.getElementById('jira-lookup-status');
  const raw = input.value.trim();

  // Extract Jira ID from a full URL (e.g. https://rubrik.atlassian.net/browse/SMT2-151)
  const urlMatch = raw.match(/\/browse\/([A-Za-z][A-Za-z0-9]{1,9}-\d+)/i);
  const id = urlMatch ? urlMatch[1].toUpperCase() : raw.toUpperCase();

  if (!id || !/^[A-Z][A-Z0-9]{1,9}-\d+$/.test(id)) {
    status.textContent = 'Enter a Jira ID (e.g. SMT2-151) or paste a Jira URL';
    status.className = 'jira-lookup-status lookup-error';
    return;
  }
  status.textContent = 'Fetching…';
  status.className = 'jira-lookup-status lookup-loading';
  document.getElementById('jira-lookup-btn').disabled = true;

  let fetchData = null;
  try {
    const r = await fetch(`/api/compare/${id}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || `${id} not found in Jira`);
    fetchData = d;
    status.textContent = '';
    status.className = 'jira-lookup-status';
  } catch (e) {
    status.textContent = e.message;
    status.className = 'jira-lookup-status lookup-error';
    document.getElementById('jira-lookup-btn').disabled = false;
    return;
  } finally {
    document.getElementById('jira-lookup-btn').disabled = false;
  }

  try {
    showCompareDrawer(id, fetchData.ticket, fetchData.parent);
  } catch (e) {
    console.error('showCompareDrawer error:', e);
    status.textContent = `Display error: ${e.message}`;
    status.className = 'jira-lookup-status lookup-error';
  }
}

function showCompareDrawer(jiraId, ticket, parent) {
  // Build Jira full text for comparison
  const jiraText  = [ticket.summary || '', ticket.description || '', ticket.acceptance_criteria || ''].join(' ');
  const parentText = parent ? [parent.summary || '', parent.description || '', parent.acceptance_criteria || ''].join(' ') : '';
  const jiraFull  = (jiraText + ' ' + parentText).trim();

  // Find matching BRD rows:
  // 1. Prefer rows explicitly linked by Jira ID
  // 2. Fall back to content-similarity search using Jira description/AC vs BRD text
  const idMatchedRows = _allRows.filter(r => r.jira_ids.includes(jiraId));
  const contentMatches = idMatchedRows.length ? [] : findBrdMatches(jiraFull);
  const bestMatches    = idMatchedRows.length
    ? idMatchedRows.map(r => ({ row: r, score: 100, byId: true }))
    : contentMatches;

  // Combined BRD text from best matching rows
  const brdText = bestMatches
    .flatMap(m => ['what', 'functional', 'acceptance', 'to_be', 'conditions']
      .map(k => m.row.fields[k] || '').filter(Boolean))
    .join(' ');

  const reqAnalysis = analyzeRequirements(brdText, jiraFull);
  const matchPct = reqAnalysis.total > 0
    ? Math.round(((reqAnalysis.matched.length + reqAnalysis.deviated.length * 0.5) / reqAnalysis.total) * 100)
    : 0;

  // ── Header ──
  document.getElementById('cmp-jira-id').textContent = jiraId;
  const scoreEl = document.getElementById('cmp-score-wrap');
  const scoreClass = matchPct >= 65 ? 'score-green' : matchPct >= 35 ? 'score-yellow' : 'score-red';
  scoreEl.innerHTML = `<span class="cmp-score ${scoreClass}">${matchPct}% Match</span>`;

  // ── BRD match banner ──
  const matchEl = document.getElementById('cmp-brd-match');
  if (idMatchedRows.length) {
    const row = idMatchedRows[0];
    matchEl.innerHTML = `<span class="val-dot val-${row.status}" style="display:inline-block;margin-right:4px"></span>
      Exact Jira ID match · BRD row <strong>${esc(row._req_id || '')}</strong> · Section: <strong>${esc(row.section)}</strong> · ${statusLabel(row.status)}` +
      (row.issues && row.issues.length ? ` · <span style="color:var(--red)">${row.issues.length} issue${row.issues.length > 1 ? 's' : ''} flagged</span>` : '');
    matchEl.className = 'compare-brd-match match-found';
  } else if (contentMatches.length) {
    const top = contentMatches[0];
    matchEl.innerHTML = `Content-matched BRD row <strong>${esc(top.row._req_id || '')}</strong> · Section: <strong>${esc(top.row.section)}</strong> · Similarity: <strong>${top.score}%</strong>`;
    matchEl.className = 'compare-brd-match match-found';
  } else {
    matchEl.innerHTML = !_allRows.length
      ? 'No BRD loaded — validate a BRD document first to enable content matching.'
      : 'No matching BRD requirement found for this Jira ticket.';
    matchEl.className = 'compare-brd-match match-none';
  }

  // ── BRD column ──
  const brdEl = document.getElementById('cmp-brd-body');
  if (bestMatches.length && brdText) {
    let html = '';
    bestMatches.forEach(({ row, score, byId }) => {
      const f = row.fields;
      const label = byId ? 'Linked by Jira ID' : `${score}% content similarity`;
      html += `<div style="margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #e2e8f0;">
        <div style="font-size:11px;font-weight:700;color:#64748b;margin-bottom:6px;text-transform:uppercase;letter-spacing:.4px;">
          ${esc(row._req_id || '')} · ${esc(row.section)} · <span style="color:#2563eb;">${esc(label)}</span>
        </div>`;
      ['what', 'functional', 'acceptance', 'to_be', 'conditions'].forEach(k => {
        if (!f[k]) return;
        const lbl = { what: 'Requirement', functional: 'Functional', acceptance: 'Acceptance Criteria', to_be: 'To-Be', conditions: 'Conditions' }[k];
        html += `<div style="margin-bottom:8px;">
          <div style="font-size:11px;font-weight:600;color:#94a3b8;margin-bottom:2px;">${lbl}</div>
          <div class="cmp-text">${esc(f[k])}</div>
        </div>`;
      });
      html += `</div>`;
    });
    brdEl.innerHTML = html;
  } else {
    brdEl.innerHTML = '<span class="empty-text">No matching BRD requirement found.</span>';
  }

  // ── Jira column ──
  const jiraEl = document.getElementById('cmp-jira-body');
  let jiraHtml = `<div class="cmp-ticket-title"><a href="${ticket.url}" target="_blank">${esc(jiraId)}</a> · ${esc(ticket.issue_type || '')} · ${esc((ticket.summary || '').substring(0, 80))}</div>`;

  if (ticket.description) {
    jiraHtml += `<div class="cmp-field-label">Description</div>
      <div class="cmp-text">${esc(ticket.description)}</div>`;
  }

  if (ticket.acceptance_criteria) {
    jiraHtml += `<div class="cmp-field-label" style="margin-top:12px;">Acceptance Criteria</div>
      <div class="cmp-text">${esc(ticket.acceptance_criteria)}</div>`;
  }

  if (!ticket.description && !ticket.acceptance_criteria) {
    jiraHtml += '<span class="empty-text">No description or acceptance criteria in Jira ticket.</span>';
  }

  if (parent) {
    jiraHtml += `<div class="cmp-parent-label" style="margin-top:14px;">Parent: <a href="${parent.url || '#'}" target="_blank">${esc(parent.key || '')}</a> — ${esc((parent.summary || '').substring(0, 60))}</div>`;
    if (parent.description) {
      jiraHtml += `<div class="cmp-field-label">Parent Description</div><div class="cmp-text cmp-parent-text">${esc(parent.description)}</div>`;
    }
    if (parent.acceptance_criteria) {
      jiraHtml += `<div class="cmp-field-label" style="margin-top:8px;">Parent Acceptance Criteria</div><div class="cmp-text cmp-parent-text">${esc(parent.acceptance_criteria)}</div>`;
    }
  }
  jiraEl.innerHTML = jiraHtml;

  // ── Gaps column ──
  const gapsEl = document.getElementById('cmp-gaps-body');
  let gapsHtml = '';

  if (reqAnalysis.total > 0) {
    gapsHtml += `<div class="req-status-summary">
      <div class="req-status-item">
        <span class="req-status-badge req-status-matched">✅ Matching</span>
        <span class="req-status-count">${reqAnalysis.matched.length}</span>
      </div>
      <div class="req-status-item">
        <span class="req-status-badge req-status-deviated">⚠️ Deviated</span>
        <span class="req-status-count">${reqAnalysis.deviated.length}</span>
      </div>
      <div class="req-status-item">
        <span class="req-status-badge req-status-missing">❌ Missing</span>
        <span class="req-status-count">${reqAnalysis.missing.length}</span>
      </div>
    </div>`;

    if (reqAnalysis.missing.length) {
      gapsHtml += `<div class="gap-section">
        <div class="gap-section-title gap-missing-title">Missing from Jira</div>
        ${reqAnalysis.missing.map(r => `<div class="req-item req-missing">${esc(r.text)}</div>`).join('')}
      </div>`;
    }

    if (reqAnalysis.deviated.length) {
      gapsHtml += `<div class="gap-section">
        <div class="gap-section-title gap-deviated-title">Deviated in Jira</div>
        ${reqAnalysis.deviated.map(r => `<div class="req-item req-deviated">${esc(r.text)}</div>`).join('')}
      </div>`;
    }

    if (!reqAnalysis.missing.length && !reqAnalysis.deviated.length) {
      gapsHtml += `<div class="gap-section"><div class="gap-ok">All requirements matched in Jira.</div></div>`;
    }
  }

  if (bestMatches.length && bestMatches[0].row.issues && bestMatches[0].row.issues.length) {
    gapsHtml += `<div class="gap-section">
      <div class="gap-section-title gap-issues-title">Flagged Issues</div>
      ${bestMatches[0].row.issues.map(i => `<div class="gap-issue"><span class="issue-tag issue-${i.type}">${i.type}</span><span class="gap-issue-detail">${esc(i.detail)}</span></div>`).join('')}
    </div>`;
  }

  if (!gapsHtml) gapsHtml = '<span class="empty-text">No gaps detected.</span>';
  gapsEl.innerHTML = gapsHtml;

  // ── Requirement breakdown ──
  const breakdownEl = document.getElementById('cmp-breakdown');
  if (reqAnalysis.total > 0) {
    const reqRows = reqAnalysis.all.map(r => {
      const icon  = r.status === 'matched' ? '✅' : r.status === 'deviated' ? '⚠️' : '❌';
      const label = r.status === 'matched' ? 'MATCHING' : r.status === 'deviated' ? 'DEVIATED' : 'MISSING';
      return `<div class="sent-row sent-${r.status}">
        <span class="sent-icon">${icon}</span>
        <span class="sent-text">${esc(r.text)}</span>
        <span class="req-label req-label-${r.status}">${label}</span>
      </div>`;
    }).join('');
    breakdownEl.innerHTML = `<div class="breakdown-title">Requirement Breakdown</div>${reqRows}`;
    breakdownEl.style.display = 'block';
  } else {
    breakdownEl.style.display = 'none';
  }

  document.getElementById('compare-panel').style.display = 'block';
  document.body.style.overflow = 'hidden';
}

function closeCompareDrawer() {
  const panel = document.getElementById('compare-panel');
  if (panel) panel.style.display = 'none';
  document.body.style.overflow = '';
}

// ── QA Sign-off Tracker ────────────────────────────────────────────────

const _SO_KEY = 'brd_signoff_v1';

function getSignoff(reqId) {
  try {
    return JSON.parse(localStorage.getItem(_SO_KEY) || '{}')[reqId] || { status: 'Not Started' };
  } catch { return { status: 'Not Started' }; }
}

function setSignoff(reqId, status) {
  try {
    const all = JSON.parse(localStorage.getItem(_SO_KEY) || '{}');
    all[reqId] = { status };
    localStorage.setItem(_SO_KEY, JSON.stringify(all));
  } catch {}
  updateSignoffProgress();
}

function signoffClass(status) {
  return { 'Passed': 'so-passed', 'Blocked': 'so-blocked',
           'In Testing': 'so-testing', 'Test Planned': 'so-planned' }[status] || 'so-default';
}

function updateSignoffProgress() {
  if (!_allRows.length) return;
  try {
    const all = JSON.parse(localStorage.getItem(_SO_KEY) || '{}');
    const passed  = _allRows.filter(r => (all[r._req_id] || {}).status === 'Passed').length;
    const total   = _allRows.length;
    const pct     = Math.round(passed / total * 100);
    document.getElementById('signoff-progress-text').textContent =
      `QA Sign-off: ${passed}/${total} Passed (${pct}%)`;
    document.getElementById('signoff-progress-bar').style.width = `${pct}%`;
  } catch {}
}

// ── RTM Export ─────────────────────────────────────────────────────────

function exportRTM() {
  if (typeof XLSX === 'undefined') { alert('Export library not loaded — check your internet connection and reload the page.'); return; }
  if (!_allRows.length) { alert('Load a BRD first.'); return; }
  const so = JSON.parse(localStorage.getItem(_SO_KEY) || '{}');
  const headers = [
    'Req ID','Section','Priority','BRD Status',
    'Requirement','Functional Req','Acceptance Criteria',
    'Jira Tickets','Validation Status',
    'Testability Score','Testability Label','Testability Issues',
    'AC Coverage Status','AC Coverage Detail',
    'QA Sign-off',
  ];
  const wsData = [headers];
  _allRows.forEach(row => {
    const f  = row.fields;
    const tb = row.testability || {};
    const ac = row.ac_gap      || {};
    const s  = (so[row._req_id] || {}).status || 'Not Started';
    wsData.push([
      row._req_id,
      row.section,
      row.priority_brd || '',
      row.status_brd   || '',
      f.what           || '',
      f.functional     || '',
      f.acceptance     || '',
      row.jira_ids.join(', '),
      { GREEN: 'Match', YELLOW: 'Partial', RED: 'Mismatch', NO_JIRA: 'No Jira' }[row.status] || row.status,
      tb.score !== undefined ? tb.score : '',
      tb.label  || '',
      (tb.issues || []).join('; '),
      ac.status  || '',
      ac.detail  || '',
      s,
    ]);
  });
  const ws = XLSX.utils.aoa_to_sheet(wsData);
  // Column widths
  ws['!cols'] = [8,18,12,12,40,40,30,18,12,8,16,50,14,40,14].map(w => ({ wch: w }));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'RTM');
  XLSX.writeFile(wb, 'BRD_RTM.xlsx');
}

// ── Test Scenario Generator ────────────────────────────────────────────

async function generateTests(reqId, requirementText, jiraAc, section) {
  const container = document.getElementById(`scenarios-${reqId}`);
  if (!container) return;
  container.style.display = 'block';
  container.innerHTML = `<div class="scenarios-loading">🤖 Generating test scenarios…</div>`;

  try {
    const r = await fetch('/api/generate-tests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requirement: requirementText, jira_ac: jiraAc, section }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed to generate');

    const sc = d.scenarios;
    const typeLabels = [
      ['positive',   '✅ Positive Scenarios',   'sc-positive'],
      ['negative',   '❌ Negative Scenarios',   'sc-negative'],
      ['edge_cases', '⚡ Edge Cases',            'sc-edge'],
    ];

    let html = '<div class="scenarios-wrap">';
    html += '<div class="scenarios-title">🧪 Generated Test Scenarios <button class="scenarios-close" onclick="this.closest(\'.scenarios-section\').style.display=\'none\'">✕</button></div>';

    typeLabels.forEach(([key, label, cls]) => {
      const list = sc[key] || [];
      if (!list.length) return;
      html += `<div class="sc-group ${cls}">
        <div class="sc-group-title">${label}</div>
        ${list.map((s, i) => `
          <div class="sc-item">
            <div class="sc-item-title">${i + 1}. ${esc(s.title)}</div>
            <ol class="sc-steps">${(s.steps || []).map(step => `<li>${esc(step)}</li>`).join('')}</ol>
            <div class="sc-expected"><strong>Expected:</strong> ${esc(s.expected)}</div>
          </div>`).join('')}
      </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="scenarios-error">⚠️ ${esc(e.message)}</div>`;
  }
}

// ── BRD content-based search ───────────────────────────────────────────

function findBrdMatches(jiraText, topN = 3, minScore = 8) {
  if (!jiraText || !_allRows.length) return [];
  const jiraKw = _keywords(jiraText);
  if (!jiraKw.size) return [];

  const scored = _allRows.map(row => {
    const brdText = ['what', 'functional', 'acceptance', 'to_be', 'conditions']
      .map(k => row.fields[k] || '').join(' ');
    const brdKw = _keywords(brdText);
    if (!brdKw.size) return null;
    const overlap = [...jiraKw].filter(w => brdKw.has(w)).length;
    // score = percentage of Jira keywords found in this BRD row
    const score = Math.round((overlap / jiraKw.size) * 100);
    return score >= minScore ? { row, score } : null;
  }).filter(Boolean);

  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, topN);
}

// ── Diff engine ────────────────────────────────────────────────────────

const _STOP = new Set([
  'the','a','an','is','are','was','were','and','or','in','on','at','to','of',
  'for','with','this','that','will','be','by','from','as','it','its','not',
  'no','can','do','have','has','but','if','so','when','which','who','any',
  'all','more','also','into','than','their','they','them','these','those',
  'such','each','only','been','must','shall','should','would','could','may',
  'our','your','we','he','she','his','her','their','been','being','had',
]);

function _keywords(text) {
  if (!text) return new Set();
  return new Set(
    (text.toLowerCase().match(/\b[a-zA-Z]{3,}\b/g) || []).filter(w => !_STOP.has(w))
  );
}

function computeDiff(brdText, jiraText) {
  const brdKw  = _keywords(brdText);
  const jiraKw = _keywords(jiraText);
  const matched = new Set([...brdKw].filter(w => jiraKw.has(w)));
  const missing = new Set([...brdKw].filter(w => !jiraKw.has(w)));
  const extra   = new Set([...jiraKw].filter(w => !brdKw.has(w)));
  const matchPct = brdKw.size > 0 ? Math.round((matched.size / brdKw.size) * 100) : 0;
  return { matched, missing, extra, matchPct };
}

function highlightText(text, matched, missing) {
  if (!text) return '';
  // Escape HTML first, then wrap keywords
  const escaped = String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>');
  return escaped.replace(/\b([a-zA-Z]{3,})\b/g, (word) => {
    const lw = word.toLowerCase();
    if (!_STOP.has(lw)) {
      if (matched.has(lw)) return `<mark class="hl-matched">${word}</mark>`;
      if (missing.has(lw)) return `<mark class="hl-missing">${word}</mark>`;
    }
    return word;
  });
}

function analyzeSentences(brdText, jiraText) {
  if (!brdText) return [];
  const jiraLower = (jiraText || '').toLowerCase();
  return brdText
    .split(/[.!?]+/)
    .map(s => s.trim())
    .filter(s => s.length > 25)
    .map(sentence => {
      const words = (sentence.toLowerCase().match(/\b[a-zA-Z]{4,}\b/g) || []).filter(w => !_STOP.has(w));
      if (words.length < 2) return null;
      const found = words.filter(w => jiraLower.includes(w));
      const coverage = Math.round((found.length / words.length) * 100);
      const status = coverage >= 60 ? 'matched' : coverage >= 30 ? 'partial' : 'missing';
      return { text: sentence, coverage, status };
    })
    .filter(Boolean);
}

function analyzeRequirements(brdText, jiraText) {
  if (!brdText) return { matched: [], deviated: [], missing: [], total: 0, all: [] };
  const jiraLower = (jiraText || '').toLowerCase();
  const all = brdText
    .split(/[.!?\n]+/)
    .map(s => s.trim())
    .filter(s => s.length > 20)
    .map(sentence => {
      const words = (sentence.toLowerCase().match(/\b[a-zA-Z]{4,}\b/g) || []).filter(w => !_STOP.has(w));
      if (words.length < 2) return null;
      const found = words.filter(w => jiraLower.includes(w));
      const coverage = Math.round((found.length / words.length) * 100);
      const status = coverage >= 70 ? 'matched' : coverage >= 30 ? 'deviated' : 'missing';
      return { text: sentence, coverage, status };
    })
    .filter(Boolean);
  return {
    matched:  all.filter(r => r.status === 'matched'),
    deviated: all.filter(r => r.status === 'deviated'),
    missing:  all.filter(r => r.status === 'missing'),
    total: all.length,
    all,
  };
}

// ── BRD Version Diff ─────────────────────────────────────────────────────

let _diffV1File = null;
let _diffV2File = null;
let _diffResult = null;
let _diffFilter  = 'all';

const _DIFF_FIELD_LABELS = {
  section: 'Section', what: 'Requirement', why: 'Rationale', who: 'Who',
  as_is: 'As-Is', to_be: 'To-Be', functional: 'Functional Req',
  conditions: 'Conditions', exceptions: 'Exceptions',
  assumptions: 'Assumptions', dependencies: 'Dependencies',
  acceptance: 'Acceptance Criteria', jira_ids: 'Jira Tickets',
};

function initDiff() {
  function setupDz(dzId, inputId, nameId, slotNum) {
    const dz  = document.getElementById(dzId);
    const inp = document.getElementById(inputId);
    if (!dz || !inp) return;

    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
    dz.addEventListener('drop', e => {
      e.preventDefault();
      dz.classList.remove('dragover');
      const f = e.dataTransfer.files[0];
      if (f) _setDiffFile(slotNum, f, nameId);
    });
    inp.addEventListener('change', e => {
      if (e.target.files[0]) _setDiffFile(slotNum, e.target.files[0], nameId);
    });
  }

  setupDz('diff-drop-v1', 'diff-file-v1', 'diff-name-v1', 1);
  setupDz('diff-drop-v2', 'diff-file-v2', 'diff-name-v2', 2);

  const btn = document.getElementById('diff-compare-btn');
  if (btn) btn.addEventListener('click', startDiff);
}

function _setDiffFile(slot, file, nameId) {
  if (!file.name.endsWith('.docx')) { alert('Please select a .docx file'); return; }
  if (slot === 1) _diffV1File = file; else _diffV2File = file;
  const el = document.getElementById(nameId);
  if (el) { el.textContent = `📄 ${file.name}`; el.classList.remove('hidden'); }
  const btn = document.getElementById('diff-compare-btn');
  if (btn) btn.disabled = !(_diffV1File && _diffV2File);
}

async function startDiff() {
  if (!_diffV1File || !_diffV2File) return;
  showProgress('Uploading BRD documents...');
  hideError();

  const fd = new FormData();
  fd.append('v1_file', _diffV1File);
  fd.append('v2_file', _diffV2File);

  try {
    const r = await fetch('/api/diff', { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Diff failed');
    _pollDiff(d.job_id);
  } catch (e) {
    hideProgress();
    showError(e.message);
  }
}

function _pollDiff(jobId) {
  const tick = async () => {
    try {
      const r = await fetch(`/api/job/${jobId}`);
      const d = await r.json();
      updateProgress(d.progress || 'Comparing...');
      if (d.status === 'done') {
        hideProgress();
        renderDiff(d.result);
      } else if (d.status === 'error') {
        hideProgress();
        showError(d.error || 'Diff failed');
      } else {
        setTimeout(tick, 1500);
      }
    } catch { setTimeout(tick, 2000); }
  };
  tick();
}

// ── Word-level diff ────────────────────────────────────────────────────────
function wordDiff(oldText, newText) {
  const ow = (oldText || '').trim().split(/\s+/).filter(Boolean);
  const nw = (newText || '').trim().split(/\s+/).filter(Boolean);
  const em = '<em class="diff-empty-val">—</em>';

  if (!ow.length && !nw.length) return { oldHtml: em, newHtml: em };
  if (!ow.length) return { oldHtml: em, newHtml: nw.map(w => `<ins class="d-ins">${esc(w)}</ins>`).join(' ') };
  if (!nw.length) return { oldHtml: ow.map(w => `<del class="d-del">${esc(w)}</del>`).join(' '), newHtml: em };

  // LCS
  const n = ow.length, m = nw.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      dp[i][j] = ow[i-1] === nw[j-1]
        ? dp[i-1][j-1] + 1
        : Math.max(dp[i-1][j], dp[i][j-1]);
    }
  }

  // Traceback
  const ops = [];
  let i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && ow[i-1] === nw[j-1]) {
      ops.unshift({ t: '=', ow: ow[i-1], nw: nw[j-1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
      ops.unshift({ t: '+', nw: nw[j-1] });
      j--;
    } else {
      ops.unshift({ t: '-', ow: ow[i-1] });
      i--;
    }
  }

  const oldParts = [], newParts = [];
  for (const o of ops) {
    if (o.t === '=') { oldParts.push(esc(o.ow)); newParts.push(esc(o.nw)); }
    else if (o.t === '-') oldParts.push(`<del class="d-del">${esc(o.ow)}</del>`);
    else if (o.t === '+') newParts.push(`<ins class="d-ins">${esc(o.nw)}</ins>`);
  }

  return {
    oldHtml: oldParts.join(' ') || em,
    newHtml: newParts.join(' ') || em,
  };
}

// ── Render diff results ────────────────────────────────────────────────────
function renderDiff(result) {
  _diffResult = result;
  document.getElementById('landing').classList.add('hidden');
  document.getElementById('app-layout').classList.add('hidden');
  document.getElementById('diff-layout').classList.remove('hidden');

  const { stats, affected_jira } = result;

  document.getElementById('diff-summary-bar').innerHTML = `
    <div class="diff-stat-row">
      <span class="diff-stat ds-changed">⚠️ <strong>${stats.changed}</strong> Changed</span>
      <span class="diff-stat ds-added">✅ <strong>${stats.added}</strong> Added</span>
      <span class="diff-stat ds-removed">❌ <strong>${stats.removed}</strong> Removed</span>
      <span class="diff-stat ds-unchanged">✓ <strong>${stats.unchanged}</strong> Unchanged</span>
      ${stats.affected_jira
        ? `<span class="diff-stat ds-jira">🎯 <strong>${stats.affected_jira}</strong> Jira ticket${stats.affected_jira !== 1 ? 's' : ''} need re-testing</span>`
        : ''}
    </div>
    ${affected_jira.length
      ? `<div class="diff-jira-tags">${affected_jira.map(j => `<span class="diff-jira-tag">${esc(j)}</span>`).join('')}</div>`
      : ''}`;

  const total = stats.changed + stats.added + stats.removed + stats.unchanged;
  document.getElementById('diff-filter-row').innerHTML =
    [['all', `All (${total})`],
     ['changed', `⚠️ Changed (${stats.changed})`],
     ['added', `✅ Added (${stats.added})`],
     ['removed', `❌ Removed (${stats.removed})`],
     ['unchanged', `✓ Unchanged (${stats.unchanged})`]]
    .map(([f, label]) =>
      `<button class="diff-ftab${f === 'all' ? ' active' : ''}" onclick="setDiffFilter('${f}', this)">${label}</button>`)
    .join('');

  _diffFilter = 'all';
  _renderDiffContent();
}

function setDiffFilter(filter, btn) {
  _diffFilter = filter;
  document.querySelectorAll('.diff-ftab').forEach(b => b.classList.toggle('active', b === btn));
  _renderDiffContent();
}

function _renderDiffContent() {
  if (!_diffResult) return;
  const { added, removed, changed, unchanged } = _diffResult;
  const el = document.getElementById('diff-content');

  const show = f => _diffFilter === 'all' || _diffFilter === f;
  const groups = [];

  if (show('changed') && changed.length)
    groups.push({ label: '⚠️ CHANGED', html: changed.map(_changedCard).join('') });
  if (show('added') && added.length)
    groups.push({ label: '✅ ADDED', html: added.map(_addedCard).join('') });
  if (show('removed') && removed.length)
    groups.push({ label: '❌ REMOVED', html: removed.map(_removedCard).join('') });
  if (show('unchanged') && unchanged.length)
    groups.push({ label: '✓ UNCHANGED', html: unchanged.map(_unchangedCard).join('') });

  if (!groups.length) {
    el.innerHTML = '<div class="diff-empty-msg">No items in this category.</div>';
    return;
  }

  el.innerHTML = groups.map(g =>
    `<div class="diff-group">
      <div class="diff-group-label">${g.label}</div>
      ${g.html}
    </div>`).join('');
}

function _changedCard(c) {
  const section = esc(c.v2.section || 'General');
  const jiraTags = c.jira_ids.map(j => `<span class="diff-jira-tag">${esc(j)}</span>`).join('');

  const diffsHtml = c.diffs.map(d => {
    const label = _DIFF_FIELD_LABELS[d.field] || d.field;
    const { oldHtml, newHtml } = wordDiff(d.old, d.new);
    return `<div class="diff-field-row">
      <div class="diff-field-name">${esc(label)}</div>
      <div class="diff-field-old"><span class="diff-line-badge was-badge">WAS</span> ${oldHtml}</div>
      <div class="diff-field-new"><span class="diff-line-badge now-badge">NOW</span> ${newHtml}</div>
    </div>`;
  }).join('');

  return `<div class="diff-card diff-card-changed">
    <div class="diff-card-hdr">
      <span class="diff-card-section">📍 ${section}</span>
      ${jiraTags}
      ${c.jira_ids.length ? '<span class="diff-retest-badge">⚠️ re-test</span>' : ''}
    </div>
    <div class="diff-card-body">${diffsHtml}</div>
  </div>`;
}

function _addedCard(a) {
  const section = esc(a.req.section || 'General');
  const fields  = a.req.fields || {};
  const text    = (fields.what || fields.functional || Object.values(fields).find(v => v) || '').trim();
  const jiraTags = a.jira_ids.map(j => `<span class="diff-jira-tag">${esc(j)}</span>`).join('');

  return `<div class="diff-card diff-card-added">
    <div class="diff-card-hdr">
      <span class="diff-card-section">📍 ${section}</span>
      ${jiraTags}
    </div>
    ${text ? `<div class="diff-card-text">${esc(text)}</div>` : ''}
  </div>`;
}

function _removedCard(r) {
  const section = esc(r.req.section || 'General');
  const fields  = r.req.fields || {};
  const text    = (fields.what || fields.functional || Object.values(fields).find(v => v) || '').trim();
  const jiraTags = r.jira_ids.map(j => `<span class="diff-jira-tag">${esc(j)}</span>`).join('');

  return `<div class="diff-card diff-card-removed">
    <div class="diff-card-hdr">
      <span class="diff-card-section">📍 ${section}</span>
      ${jiraTags}
      ${r.jira_ids.length ? '<span class="diff-retest-badge">removed — recheck Jira</span>' : ''}
    </div>
    ${text ? `<div class="diff-card-text diff-removed-text">${esc(text)}</div>` : ''}
  </div>`;
}

function _unchangedCard(u) {
  const section = esc(u.req.section || 'General');
  const fields  = u.req.fields || {};
  const text    = (fields.what || fields.functional || Object.values(fields).find(v => v) || '').trim();
  const snippet = text.length > 130 ? text.slice(0, 130) + '…' : text;
  const jiraTags = u.jira_ids.map(j => `<span class="diff-jira-tag diff-jira-tag-muted">${esc(j)}</span>`).join('');

  return `<div class="diff-card diff-card-unchanged">
    <div class="diff-card-hdr">
      <span class="diff-card-section" style="color:#6b7280">📍 ${section}</span>
      ${jiraTags}
    </div>
    ${snippet ? `<div class="diff-card-text" style="color:#9ca3af;font-size:12px;">${esc(snippet)}</div>` : ''}
  </div>`;
}

function backFromDiff() {
  document.getElementById('diff-layout').classList.add('hidden');
  document.getElementById('landing').classList.remove('hidden');
  // reset file slots so the user can pick new files
  _diffV1File = null;
  _diffV2File = null;
  _diffResult = null;
  ['diff-name-v1', 'diff-name-v2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.classList.add('hidden'); }
  });
  const btn = document.getElementById('diff-compare-btn');
  if (btn) btn.disabled = true;
}

function exportDiffReport() {
  if (!_diffResult || typeof XLSX === 'undefined') {
    alert('No diff data to export or XLSX library not available.');
    return;
  }
  const { added, removed, changed, unchanged, affected_jira, stats } = _diffResult;
  const wb = XLSX.utils.book_new();

  // — Summary sheet
  const summaryRows = [
    ['BRD Version Diff Report'],
    [],
    ['Category', 'Count'],
    ['Changed Requirements', stats.changed],
    ['Added Requirements', stats.added],
    ['Removed Requirements', stats.removed],
    ['Unchanged Requirements', stats.unchanged],
    [],
    ['Jira Tickets Needing Re-test', stats.affected_jira],
    ['Affected Jira IDs', affected_jira.join(', ')],
  ];
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(summaryRows), 'Summary');

  // — Changed sheet
  if (changed.length) {
    const hdr = ['Section', 'Jira IDs', 'Changed Fields', 'Field', 'Old Value', 'New Value'];
    const rows = [];
    for (const c of changed) {
      const sec   = (c.v2.section || '').trim();
      const jids  = c.jira_ids.join(', ');
      const names = c.diffs.map(d => _DIFF_FIELD_LABELS[d.field] || d.field).join(', ');
      for (const d of c.diffs)
        rows.push([sec, jids, names, _DIFF_FIELD_LABELS[d.field] || d.field, d.old, d.new]);
    }
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([hdr, ...rows]), 'Changed');
  }

  // — Added sheet
  if (added.length) {
    const hdr = ['Section', 'Requirement', 'Jira IDs'];
    const rows = added.map(a => [
      (a.req.section || '').trim(),
      ((a.req.fields || {}).what || (a.req.fields || {}).functional || '').trim(),
      a.jira_ids.join(', '),
    ]);
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([hdr, ...rows]), 'Added');
  }

  // — Removed sheet
  if (removed.length) {
    const hdr = ['Section', 'Requirement', 'Jira IDs'];
    const rows = removed.map(r => [
      (r.req.section || '').trim(),
      ((r.req.fields || {}).what || (r.req.fields || {}).functional || '').trim(),
      r.jira_ids.join(', '),
    ]);
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([hdr, ...rows]), 'Removed');
  }

  const date = new Date().toISOString().slice(0, 10);
  XLSX.writeFile(wb, `brd_diff_report_${date}.xlsx`);
}
