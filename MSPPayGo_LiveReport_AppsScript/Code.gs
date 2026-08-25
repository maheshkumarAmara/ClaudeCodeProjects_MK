/**
 * MSP PayGo — Sprint QA Report (live)
 *
 * Bind this script to the "MSP_PayGO_NewProject" spreadsheet
 * (Extensions > Apps Script). It reads the "JIRA - User Stories" and
 * "Sprint Breakdown" tabs live on every page load — no manual regeneration.
 */

const TAB_STORIES = 'JIRA - User Stories';
const TAB_BREAKDOWN = 'Sprint Breakdown';
const SPRINT_ORDER = ['Sprint 1', 'Sprint 2', 'Sprint 3'];

// After Deploy > New deployment > Web app, paste the resulting /exec URL here.
// (ScriptApp.getService().getUrl() returns a /dev test URL — not the production
// one — when called from a menu click instead of from inside doGet.)
const WEB_APP_URL = '';

function doGet() {
  const template = HtmlService.createTemplateFromFile('report');
  template.data = getReportData();
  return template.evaluate()
    .setTitle('MSP PayGo — Sprint QA Report')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('QA Report')
    .addItem('Open Live Report', 'openReportDialog')
    .addToUi();
}

function openReportDialog() {
  const url = WEB_APP_URL || ScriptApp.getService().getUrl();
  const body = url
    ? '<p style="margin:0 0 14px;font-size:13px;color:#444;">Opens the live QA report in a new tab. It always reflects the current sheet data.</p>' +
      '<a href="' + url + '" target="_blank" style="display:inline-block;background:#0b5cff;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-size:13px;">Open Report ↗</a>'
    : '<p style="margin:0;font-size:13px;color:#444;">No web app deployment found yet. In the Apps Script editor, use <b>Deploy &gt; New deployment &gt; Web app</b> first, then paste the resulting URL into WEB_APP_URL at the top of Code.gs.</p>';
  const html = HtmlService.createHtmlOutput(
    '<div style="font-family:system-ui;padding:16px;text-align:center;">' + body + '</div>'
  ).setWidth(340).setHeight(130);
  SpreadsheetApp.getUi().showModalDialog(html, 'MSP PayGo QA Report');
}

function getReportData() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const storiesSheet = ss.getSheetByName(TAB_STORIES);
  const breakdownSheet = ss.getSheetByName(TAB_BREAKDOWN);

  const stories = parseStories(storiesSheet);
  const trend = parseTrend(breakdownSheet);

  return {
    sprintStages: stories.sprintStages,
    detail: stories.detail,
    totalStories: stories.totalStories,
    dates: trend.dates,
    trend: trend.trend,
    missingDatesNote: trend.missingDatesNote,
    generatedAt: Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "d MMM yyyy, h:mm a"),
    generatedAtMillis: new Date().getTime(),
  };
}

// ---------- "JIRA - User Stories" tab ----------

function sprintKeyFor(raw) {
  const s = String(raw || '').trim();
  if (!s) return null;
  const exact = SPRINT_ORDER.filter(name => name.toLowerCase() === s.toLowerCase());
  if (exact.length) return exact[0];
  const m = s.match(/(?:sprint|sp)\s*([123])\b/i);
  return m ? 'Sprint ' + m[1] : null;
}

function parseStories(sheet) {
  const values = sheet.getDataRange().getValues();
  const header = values[0].map(h => String(h).trim().toLowerCase());
  const colStatus = header.indexOf('status');
  const colSprint = header.indexOf('sprint');

  const bySprint = {};
  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    const status = String(row[colStatus] || '').trim();
    const sprintKey = sprintKeyFor(row[colSprint]);
    if (!status || !sprintKey) continue;
    if (!bySprint[sprintKey]) bySprint[sprintKey] = { total: 0, statusCounts: {} };
    bySprint[sprintKey].total++;
    bySprint[sprintKey].statusCounts[status] = (bySprint[sprintKey].statusCounts[status] || 0) + 1;
  }

  const sprintStages = [];
  const detail = [];
  let totalStories = 0;

  SPRINT_ORDER.forEach(name => {
    const s = bySprint[name];
    if (!s) return;
    totalStories += s.total;

    const done = s.statusCounts['QA Completed'] || 0;
    const inprog = s.statusCounts['QA In Progress'] || 0;
    const ready = s.statusCounts['Ready for QA'] || 0;
    const other = s.total - done - inprog - ready;
    sprintStages.push({ name: name, total: s.total, other: other, ready: ready, inprog: inprog, done: done });

    const rows = Object.keys(s.statusCounts)
      .map(status => [status, s.statusCounts[status]])
      .sort((a, b) => b[1] - a[1]);
    detail.push({ sprint: name, total: s.total, rows: rows });
  });

  return { sprintStages: sprintStages, detail: detail, totalStories: totalStories };
}

// ---------- "Sprint Breakdown" tab (date-wise tracking table) ----------

function toDateKey(val) {
  if (Object.prototype.toString.call(val) === '[object Date]') {
    return Utilities.formatDate(val, Session.getScriptTimeZone(), 'dd/MM/yyyy');
  }
  const s = String(val || '').trim();
  return /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(s) ? s : null;
}

function formatShortDate(dateKey) {
  const parts = dateKey.split('/');
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return parseInt(parts[0], 10) + ' ' + months[parseInt(parts[1], 10) - 1];
}

function toPercent(val) {
  if (val === '' || val === null || val === undefined) return null;
  if (typeof val === 'number') {
    const pct = val <= 1 ? val * 100 : val;
    return Math.round(pct * 100) / 100;
  }
  const s = String(val).trim();
  if (!s) return null;
  const n = parseFloat(s.replace('%', ''));
  return isNaN(n) ? null : Math.round(n * 100) / 100;
}

/**
 * Layout: repeating blocks of a date-header row (col B) followed by
 * "Sprint 1"/"Sprint 2"/"Sprint 3" rows (col B) with their % value in col C.
 */
function parseTrend(sheet) {
  const values = sheet.getDataRange().getValues();
  const trendMap = {};
  const order = [];
  let currentDate = null;

  for (let r = 0; r < values.length; r++) {
    const colB = values[r][1];
    const colC = values[r][2];
    const dateKey = toDateKey(colB);
    if (dateKey) {
      currentDate = dateKey;
      if (!trendMap[currentDate]) {
        trendMap[currentDate] = {};
        order.push(currentDate);
      }
      continue;
    }
    if (!currentDate) continue;
    const label = String(colB || '').trim();
    const sprintKey = sprintKeyFor(label);
    if (sprintKey) {
      trendMap[currentDate][sprintKey] = toPercent(colC);
    }
  }

  const complete = order.filter(d => SPRINT_ORDER.every(name => trendMap[d][name] != null));
  const incomplete = order.filter(d => complete.indexOf(d) === -1);

  const dates = complete.map(formatShortDate);
  const trend = { 'Sprint 1': [], 'Sprint 2': [], 'Sprint 3': [] };
  complete.forEach(d => {
    SPRINT_ORDER.forEach(name => trend[name].push(trendMap[d][name]));
  });

  const missingDatesNote = incomplete.length
    ? incomplete.map(formatShortDate).join(', ') + ' not yet recorded in the source sheet at generation time.'
    : 'All tracked dates are fully recorded.';

  return { dates: dates, trend: trend, missingDatesNote: missingDatesNote };
}
