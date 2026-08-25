/**
 * ============================================================================
 * WEEKLY STATUS MONITOR & SLACK NOTIFIER
 * ============================================================================
 * 
 * Description:
 *   Automates tracking of weekly status report emails sent across various QA tracks.
 *   - Parses Google Sheets to maintain a dynamic holiday calendar.
 *   - Monitors Gmail inbox for status updates based on track-specific criteria.
 *   - Automatically adjusts reminder/notification windows based on holidays.
 *   - Generates formatted Plain Text and HTML summaries sent to a designated Slack channel.
 * 
 * Author/Maintainer: Amara Maheshkumar (amara.maheshkumar@rubrik.com)
 * ============================================================================
 */

// ============================================================================
// CONFIGURATION SECTION
// Edit ONLY this section to update sheets, email channels, dates, or tracks.
// ============================================================================

/**
 * Global configuration object for the script.
 * @type {Object}
 */
const WEEKLY_STATUS_CONFIG = {

  // ── Google Sheet Integration (Holiday Calendar) ───────────────────────────
  /** Google Sheet ID containing the holiday calendar. */
  GOOGLE_SHEET_ID: "170Abs57xqj155DkKxqB8ZqdEjCBRdRaEB9y7yi9XwCE",
  
  /** Tab name inside the Google Sheet holding holiday dates. */
  HOLIDAY_SHEET_TAB: "Rubrik Holiday Calendar-2026",

  // ── Slack Email Channel ───────────────────────────────────────────────────
  /** Email address associated with the target Slack channel for posting alerts. */
  SLACK_CHANNEL_EMAIL: "leaves_notification-aaaasr6le65rpgxvaev54whpia@rubrikinc.slack.com",

  // ── Timezone Settings ─────────────────────────────────────────────────────
  /** Primary timezone for evaluation and reporting. */
  TIMEZONE: "Asia/Kolkata",

  // ── Test Date Override ────────────────────────────────────────────────────
  /**
   * Used strictly by runForceReminder() and runForceFinal() to simulate a
   * specific calendar day regardless of what day it actually is.
   * dryRun(), testWithDate(), and testEmailSearch() always evaluate against
   * the real system date and ignore this value.
   * Format: YYYY-MM-DD
   *
   * Examples:
   *   "2026-07-10" → Friday    → Standard Reminder logic (checks current week)
   *   "2026-07-13" → Monday    → Final Notification (checks prior week)
   *   "2026-07-09" → Thursday  → Early reminder (if Friday is a holiday)
   *   "2026-07-08" → Wednesday → Early reminder (only if both Thu & Fri are holidays)
   */
  TEST_DATE: "2026-07-27",

  // ── Track Configurations ──────────────────────────────────────────────────
  /**
   * Tracks to monitor. Track owners CC `it-qa-all@rubrik.com`.
   * Because this script runs under `amara.maheshkumar@rubrik.com` (a member of that DL),
   * all status emails land directly in the Gmail inbox.
   *
   * Properties:
   *   @property {string}   track           - Visual label of the track.
   *   @property {string}   subject_keyword - Prefix/tokens required in the email subject.
   *   @property {string[]} owners          - Display names of track owners.
   *   @property {string[]} owner_emails    - Sender email addresses to filter in Gmail.
   *   @property {Object}   [schedule]      - Optional per-track override of DEFAULT_SCHEDULE.
   */
  TRACKS: [
    {
      track:           "ProdOps",
      subject_keyword: "PRDOPS_QA-Weekly Status Report_FY27_Week_",
      owners:          ["Amara Maheshkumar", "Shashi Kumar"],
      owner_emails:    ["amara.maheshkumar@rubrik.com", "shashi.kumar2@rubrik.com"],
    },
    {
      track:           "CPQ",
      subject_keyword: "CPQ_QA-Weekly Status Report_FY27_Week_",
      owners:          ["Sumitha Alaguvel"],
      owner_emails:    ["sumitha.alaguvel@rubrik.com"],
      // CPQ sends its weekly status on Tuesday, not Friday — reminder Monday, final Tuesday.
      schedule:        { reminderWeekday: 1, finalWeekday: 2 },
    },
    {
      track:           "Customer Support",
      subject_keyword: "Customer Support_QA-Weekly Status Report_FY27_Week_",
      owners:          ["Shashirekha Thagadghar Venkatesh"],
      owner_emails:    ["shashirekha.venkatesh@rubrik.com"],
    },
    {
      track:           "SalesOps",
      subject_keyword: "SalesOps_Weekly Status Report_FY27_Week_",
      owners:          ["Sumitha Alaguvel", "Gopi Sandhireddy"],
      owner_emails:    ["sumitha.alaguvel@rubrik.com", "gopi.sandhireddy@rubrik.com"],
    },
    {
      track:           "GNA",
      subject_keyword: "GNA_QA-Weekly Status Report_FY27_Week_",
      owners:          ["Neethu Krishnan"],
      owner_emails:    ["neethu.krishnan@rubrik.com"],
    },
    {
      track:           "Marketing_and_Partner",
      subject_keyword: "Marketing_and_Partner_Weekly Status Report_FY27_Week_",
      owners:          ["Ibtesam Sanglikar"],
      owner_emails:    ["ibtesam.sanglikar@rubrik.com"],
    },
    // Note: Add RCF track configuration once subject and owner details are confirmed.
  ],
};

/**
 * Default reminder/final weekdays applied to any track without its own `schedule`.
 * Weekday numbers follow JS `Date.getDay()`: 0=Sun ... 5=Fri, 6=Sat.
 * Reminder: Friday. Final: Monday (checks the entire prior reporting window).
 */
const DEFAULT_SCHEDULE = { reminderWeekday: 5, finalWeekday: 1 };

/**
 * Resolves the effective schedule for a track, falling back to DEFAULT_SCHEDULE.
 * @param {Object} track - Track definition from CONFIG.
 * @returns {{reminderWeekday: number, finalWeekday: number}}
 */
function getTrackSchedule(track) {
  return track.schedule || DEFAULT_SCHEDULE;
}

// ============================================================================
// CORE LOGIC — DO NOT EDIT BELOW THIS LINE
// ============================================================================

// ============================================================================
// UTILITY HELPERS: DATE PARSING
// ============================================================================

/**
 * Strictly parses an "ISO-like" date string formatted as `yyyy-MM-dd`.
 * 
 * Standard `new Date(string)` constructor can silently misparse non-standard formats
 * (e.g., swapping days and months like "2026-24-07"), yielding incorrect execution windows.
 * This method validates components rigorously and throws errors on invalid formats or bounds.
 * 
 * @param {string} dateStr - Date string to parse (e.g., "2026-07-24").
 * @returns {Date} JavaScript Date instance corresponding to local midnight.
 * @throws {Error} If the string format or individual date parts are invalid.
 */
function parseStrictISODate(dateStr) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) {
    throw new Error(
      `Invalid date "${dateStr}" — expected yyyy-MM-dd format (e.g. "2026-07-24"). ` +
      `Check TEST_DATE in WEEKLY_STATUS_CONFIG.`
    );
  }
  const year  = Number(match[1]);
  const month = Number(match[2]);
  const day   = Number(match[3]);
  const date  = new Date(year, month - 1, day);

  // Validate out-of-range dates (e.g. month 13 or day 32)
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    throw new Error(
      `Invalid date "${dateStr}" — "${match[2]}" or "${match[3]}" is out of range. Expected yyyy-MM-dd (e.g. "2026-07-24").`
    );
  }
  return date;
}

// ============================================================================
// HOLIDAY MANAGEMENT LOGIC
// ============================================================================

/**
 * Connects to Google Sheets and retrieves designated company holidays.
 * Parses raw dates from column B into strict "yyyy-MM-dd" strings.
 * 
 * @returns {string[]} List of holiday date strings formatted as "yyyy-MM-dd".
 */
function readHolidays() {
  const ss    = SpreadsheetApp.openById(WEEKLY_STATUS_CONFIG.GOOGLE_SHEET_ID);
  const sheet = ss.getSheetByName(WEEKLY_STATUS_CONFIG.HOLIDAY_SHEET_TAB);
  const data  = sheet.getRange("A:E").getValues();

  const holidays = [];
  for (let i = 1; i < data.length; i++) {
    const raw = data[i][1];
    if (!raw) continue;

    let date;
    if (raw instanceof Date) {
      date = raw;
    } else {
      // Accepts "MM-DD-YYYY" or "MM/DD/YYYY". Logs unparseable dates instead of silent failure.
      const parts = String(raw).trim().split(/[-\/]/);
      if (parts.length !== 3 || parts.some((p) => !/^\d+$/.test(p))) {
        Logger.log(`   ⚠️ Skipping unparseable holiday date in row ${i + 1}: "${raw}"`);
        continue;
      }
      date = new Date(Number(parts[2]), Number(parts[0]) - 1, Number(parts[1]));
      if (isNaN(date.getTime())) {
        Logger.log(`   ⚠️ Skipping invalid holiday date in row ${i + 1}: "${raw}"`);
        continue;
      }
    }
    holidays.push(Utilities.formatDate(date, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy-MM-dd"));
  }
  return holidays;
}

/**
 * Checks whether a target date exists within the retrieved holiday list.
 * 
 * @param {string} dateStr - Date string in "yyyy-MM-dd" format.
 * @param {string[]} holidays - List of active holiday dates.
 * @returns {boolean} True if the date is a holiday.
 */
function isHoliday(dateStr, holidays) {
  return holidays.includes(dateStr);
}

/**
 * Iteratively walks backwards day-by-day from a given date as long as it encounters holidays,
 * returning the most recent working day (as "yyyy-MM-dd").
 * 
 * Ensures that multi-day holiday blocks (e.g., Thu+Fri) shift scheduled reminders to the 
 * appropriate preceding work day.
 * 
 * @param {string} dateStr - Starting date string ("yyyy-MM-dd").
 * @param {string[]} holidays - Array of holiday date strings.
 * @param {number} [maxLookbackDays=7] - Safety threshold to break infinite loops.
 * @returns {string} Target non-holiday date string ("yyyy-MM-dd").
 */
function walkBackToLastWorkingDay(dateStr, holidays, maxLookbackDays) {
  const cap = maxLookbackDays || 7;
  let current    = parseStrictISODate(dateStr);
  let currentStr = dateStr;
  let steps      = 0;

  while (isHoliday(currentStr, holidays) && steps < cap) {
    current.setDate(current.getDate() - 1);
    currentStr = Utilities.formatDate(current, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy-MM-dd");
    steps++;
  }

  if (steps >= cap) {
    Logger.log(`   ⚠️ walkBackToLastWorkingDay: hit ${cap}-day lookback cap from ${dateStr} — check the holiday calendar.`);
  }
  return currentStr;
}

// ============================================================================
// SCHEDULING LOGIC
// ============================================================================

const DAY_NAMES = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];

/**
 * Short "Reminder/Final" weekday tag (e.g. "Fri/Mon") used to keep each
 * schedule group's Slack email subject unique. Without this, two groups
 * evaluated in the same run (e.g. the default schedule and CPQ's Mon/Tue
 * schedule) can produce identical subjects, causing Gmail to thread them
 * together — the Slack channel then only surfaces whichever was sent last.
 *
 * @param {{reminderWeekday: number, finalWeekday: number}} schedule - Track schedule.
 * @returns {string} Tag like "Fri/Mon".
 */
function scheduleTag(schedule) {
  return `${DAY_NAMES[schedule.reminderWeekday].slice(0, 3)}/${DAY_NAMES[schedule.finalWeekday].slice(0, 3)}`;
}

/**
 * Evaluates execution schedule for a given track schedule, based on current weekday
 * and holiday configuration.
 *
 * Schedule Matrix (relative to `schedule.reminderWeekday` / `schedule.finalWeekday`):
 * - Reminder weekday 10 PM       → "reminder" (checks current day)
 * - Up to 2 days before reminder → "reminder" (if the reminder day, or the days
 *                                   between it and today, are holidays)
 * - Final weekday 10 PM          → "final"    (checks entire prior reporting window,
 *                                   unconditional — does not shift for holidays)
 *
 * @param {string[]} holidays - List of holiday date strings.
 * @param {{reminderWeekday: number, finalWeekday: number}} schedule - Track schedule.
 * @param {string} [overrideDate] - Optional override date string ("yyyy-MM-dd") for testing.
 * @returns {Object} Context metadata including `shouldRun`, `runType`, `todayStr`, and `reason`.
 */
function getRunInfo(holidays, schedule, overrideDate) {
  const now       = overrideDate ? null : new Date();
  const todayStr  = overrideDate || Utilities.formatDate(now, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy-MM-dd");
  const todayDate = parseStrictISODate(todayStr);
  const weekday   = todayDate.getDay(); // 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
  const { reminderWeekday, finalWeekday } = schedule;

  let shouldRun = false;
  let runType   = ""; // "reminder" | "final"
  let reason    = "";

  // Distance (in days, 0-6) looking backward from reminderWeekday to weekday.
  const daysBeforeReminder = (reminderWeekday - weekday + 7) % 7;

  if (weekday === finalWeekday) {
    // Final execution audit for this schedule — unconditional, no holiday shift.
    shouldRun = true;
    runType   = "final";
    reason    = `${DAY_NAMES[finalWeekday]} 10 PM final notification (checking last week)`;
  } else if (daysBeforeReminder <= 2) {
    // Determine the reminder weekday's date within the active window
    const reminderTarget = new Date(todayDate);
    reminderTarget.setDate(todayDate.getDate() + daysBeforeReminder);
    const targetStr = Utilities.formatDate(reminderTarget, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy-MM-dd");

    // Walk back from the target reminder day to locate the effective reminder day
    const reminderDayStr = walkBackToLastWorkingDay(targetStr, holidays);

    if (todayStr === reminderDayStr) {
      shouldRun = true;
      runType   = "reminder";
      reason    = reminderDayStr === targetStr
        ? `${DAY_NAMES[reminderWeekday]} 10 PM reminder check`
        : `Early reminder — ${DAY_NAMES[reminderWeekday]} ${targetStr} is a holiday (reminder day shifted to ${reminderDayStr})`;
    } else if (todayStr < reminderDayStr) {
      reason = `Today (${todayStr}) is before this week's reminder day (${reminderDayStr}) — not a scheduled run day`;
    } else {
      reason = `This week's reminder already went out on ${reminderDayStr} — skipping`;
    }
  } else {
    reason = `Today is ${DAY_NAMES[weekday]} — not a scheduled run day`;
  }

  return { shouldRun, runType, todayStr, reason };
}

// ============================================================================
// SEARCH WINDOW COMPUTATION
// ============================================================================

/**
 * Computes `[startStr, endStr]` bounds for email evaluation.
 *
 * Logic:
 * - "reminder" run: Start and end match today's date (1-day single check).
 * - "final" run: Calculates the schedule's reminder weekday relative to execution date
 *   (handling holiday shifts) spanning through today (the final weekday).
 *
 * @param {string} todayStr - Active run date string ("yyyy-MM-dd").
 * @param {string} runType - "reminder" or "final".
 * @param {string[]} holidays - Array of holiday dates.
 * @param {{reminderWeekday: number, finalWeekday: number}} schedule - Track schedule.
 * @returns {{startStr: string, endStr: string}} Window start and end dates.
 */
function computeSearchWindow(todayStr, runType, holidays, schedule) {
  if (runType === "final") {
    const today    = parseStrictISODate(todayStr);
    const weekday  = today.getDay();

    // Calculates most recent past occurrence of the schedule's reminder weekday relative to 'today'
    const daysBack = ((weekday - schedule.reminderWeekday + 7) % 7) || 7;
    const reminderDay = new Date(today);
    reminderDay.setDate(today.getDate() - daysBack);
    const reminderDayStr = Utilities.formatDate(reminderDay, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy-MM-dd");

    // Determine working day for window bound
    const startStr = holidays ? walkBackToLastWorkingDay(reminderDayStr, holidays) : reminderDayStr;

    return { startStr, endStr: todayStr };
  }
  return { startStr: todayStr, endStr: todayStr };
}

/**
 * Groups tracks by their effective schedule so each distinct reminder/final weekday
 * pairing can be evaluated and reported independently (e.g. CPQ's Mon/Tue schedule
 * vs. the default Fri/Mon schedule shared by the rest of the tracks).
 *
 * @param {Object[]} tracks - Track definitions from CONFIG.
 * @returns {{schedule: {reminderWeekday: number, finalWeekday: number}, tracks: Object[]}[]}
 */
function groupTracksBySchedule(tracks) {
  const groups = new Map();
  tracks.forEach((t) => {
    const schedule = getTrackSchedule(t);
    const key = `${schedule.reminderWeekday}-${schedule.finalWeekday}`;
    if (!groups.has(key)) groups.set(key, { schedule, tracks: [] });
    groups.get(key).tracks.push(t);
  });
  return Array.from(groups.values());
}

// ============================================================================
// GMAIL SEARCH INTEGRATION
// ============================================================================

/**
 * Searches Gmail inbox for status emails matching a specific track within a target date range.
 * 
 * Performs two-tier filtering:
 * 1. Gmail Search Query (`from:<email> after:<date>`): Uses extended lower bound for safety.
 * 2. In-Memory JS Range Evaluation: Compares literal `yyyy-MM-dd` date strings in `TIMEZONE` 
 *    against target boundaries to avoid timezone/thread discrepancies.
 * 
 * @param {Object} track - Individual track definition from CONFIG.
 * @param {string} startStr - Start boundary date string ("yyyy-MM-dd").
 * @param {string} endStr - End boundary date string ("yyyy-MM-dd").
 * @returns {{sent: boolean, sentBy: string|null, sentOn: string|null}} Results of the email check.
 */
function searchEmailForTrack(track, startStr, endStr) {
  // Generous 2-day buffer for query; strict verification performed downstream in JS
  const searchFrom = parseStrictISODate(startStr);
  searchFrom.setDate(searchFrom.getDate() - 2);
  const afterDate = Utilities.formatDate(searchFrom, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy/MM/dd");

  // Split key subject string into distinct lowercased search tokens
  const keyParts = track.subject_keyword
    .toLowerCase()
    .split(/[\s_\-]+/)
    .filter((p) => p.length > 2);

  Logger.log(`\n   🔍 [${track.track}] subject tokens: [${keyParts.join(", ")}]`);
  Logger.log(`   📅 Looking for emails sent between: ${startStr} and ${endStr}`);

  for (const ownerEmail of track.owner_emails) {
    const query = `from:${ownerEmail} after:${afterDate}`;
    Logger.log(`   🔍 Query: ${query}`);

    try {
      const threads = GmailApp.search(query, 0, 50);
      Logger.log(`   📬 ${threads.length} thread(s) found from ${ownerEmail}`);

      for (const thread of threads) {
        const messages = thread.getMessages();

        for (const msg of messages) {
          const msgDate    = msg.getDate();
          const msgDateStr = Utilities.formatDate(msgDate, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy-MM-dd");

          // Skip messages outside literal IST target boundary
          if (msgDateStr < startStr || msgDateStr > endStr) {
            continue; 
          }

          const subjectLower = msg.getSubject().toLowerCase();
          const isMatch      = keyParts.every((part) => subjectLower.includes(part));
          Logger.log(`   📧 [${msgDateStr}] "${msg.getSubject()}" → ${isMatch ? "✅ MATCH" : "❌ skip (subject)"}`);

          if (isMatch) {
            const fromRaw    = msg.getFrom();
            const nameMatch  = fromRaw.match(/^"?([^"<]+)"?\s*</);
            const senderName = nameMatch ? nameMatch[1].trim() : fromRaw.trim();
            const sentOn     = Utilities.formatDate(msgDate, WEEKLY_STATUS_CONFIG.TIMEZONE, "dd-MMM-yyyy hh:mm a");
            return { sent: true, sentBy: senderName, sentOn };
          }
        }
      }
    } catch (e) {
      Logger.log(`   ❌ Error searching ${ownerEmail}: ${e}`);
    }
  }

  Logger.log(`   ❌ No matching email found for ${track.track}`);
  return { sent: false, sentBy: null, sentOn: null };
}

// ============================================================================
// SLACK FORMATTING — PLAIN TEXT
// ============================================================================

/**
 * Formats results into plain text (formatted with Markdown/code blocks) suitable for Slack emails.
 * 
 * @param {Object[]} results - Aggregated track inspection results.
 * @param {Object} runInfo - Execution metadata object.
 * @returns {string} Formatted plain text message payload.
 */
function formatSlackMessage(results, runInfo) {
  const { todayStr, runType, reason } = runInfo;
  const startStr = runInfo.startStr || todayStr;
  const endStr   = runInfo.endStr   || todayStr;
  const windowText = startStr === endStr ? startStr : `${startStr} to ${endStr}`;

  let header;
  if (runType === "reminder") {
    const notSentCount = results.filter((r) => !r.sent).length;
    header =
      `*⏰ Weekly Status Email Reminder — ${todayStr}*\n` +
      `_${reason}_\n` +
      `_Checking emails sent on: ${windowText}_\n\n` +
      (notSentCount > 0
        ? `⚠️ *${notSentCount} track(s) have not sent their weekly status yet!*`
        : `✅ *All tracks have submitted their weekly status!*`);
  } else {
    header =
      `*🔔 Weekly Status Final Report — ${todayStr}*\n` +
      `_${reason}_\n` +
      `_Checking emails sent: ${windowText}_`;
  }

  // Define structured fixed-width alignment columns
  const colWidths = [4, 10, 48, 36, 13, 25, 22];
  const colNames  = ["Sno", "Track", "Subject", "Owner", "Sent or Not", "Sent By", "Sent On"];

  /** Helper to pad text content into fixed-width text columns */
  function fmtRow(cells) {
    return cells
      .map((c, i) => String(c == null ? "—" : c).substring(0, colWidths[i]).padEnd(colWidths[i]))
      .join("  ");
  }

  const separator  = colWidths.map((w) => "-".repeat(w)).join("  ");
  const tableLines = ["```", fmtRow(colNames), separator];
  
  results.forEach((r, idx) => {
    tableLines.push(fmtRow([
      String(idx + 1),
      r.track,
      r.subject_keyword,
      r.owners.join(" / "),
      r.sent ? "✅ Sent" : "❌ Not Sent",
      r.sentBy || "—",
      r.sentOn  || "—",
    ]));
  });
  tableLines.push("```");

  const sentCount    = results.filter((r) => r.sent).length;
  const notSentCount = results.length - sentCount;
  const summary      = `*Summary:* ✅ ${sentCount} Sent   ❌ ${notSentCount} Not Sent`;

  const pendingLines = results
    .filter((r) => !r.sent)
    .map((r) => `• *${r.track}* — ${r.owners.join(" / ")}`);

  const footer =
    runType === "reminder" && pendingLines.length > 0
      ? `\n_Please send your weekly status email before end of day._`
      : runType === "final" && pendingLines.length > 0
      ? `\n_These tracks did not submit a weekly status email for this week._`
      : "";

  const parts = [header, tableLines.join("\n"), summary];
  if (pendingLines.length > 0) {
    const pendingTitle = runType === "reminder" ? "*⏳ Still Pending:*" : "*❌ Not Submitted:*";
    parts.push(pendingTitle + "\n" + pendingLines.join("\n"));
  }
  if (footer) parts.push(footer);

  return parts.join("\n\n");
}

// ============================================================================
// SLACK FORMATTING — HTML
// ============================================================================

/**
 * Escapes reserved HTML special characters to prevent markup injection.
 * 
 * @param {*} value - Value to escape.
 * @returns {string} Sanitized string safe for HTML injection.
 */
function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Formats results into rich, styled HTML tables for emails sent to Slack channels.
 * 
 * @param {Object[]} results - Inspection results per track.
 * @param {Object} runInfo - Execution details object.
 * @returns {string} Complete document markup string for HTML body.
 */
function formatSlackHtmlMessage(results, runInfo) {
  const { todayStr, runType, reason } = runInfo;
  const startStr = runInfo.startStr || todayStr;
  const endStr   = runInfo.endStr   || todayStr;
  const windowText = startStr === endStr ? startStr : `${startStr} to ${endStr}`;

  const sentItems    = results.filter((r) => r.sent);
  const notSentItems = results.filter((r) => !r.sent);
  const sentCount    = sentItems.length;
  const notSentCount = notSentItems.length;

  const icon  = runType === "reminder" ? "⏰" : "🔔";
  const title = runType === "reminder"
    ? `${icon} Weekly Status Email Reminder — ${todayStr}`
    : `${icon} Weekly Status Final Report — ${todayStr}`;
  const footer = runType === "reminder" && notSentCount > 0
    ? "Please send your weekly status email before end of day."
    : runType === "final" && notSentCount > 0
    ? "These tracks did not submit a weekly status email for this week."
    : "";

  const thStyle = "padding:8px 12px;text-align:left;";
  const colHeaders = `
    <tr style="background:#2c3e50;color:#fff;">
      <th style="${thStyle}">#</th>
      <th style="${thStyle}">Track</th>
      <th style="${thStyle}">Subject</th>
      <th style="${thStyle}">Owner</th>
      <th style="${thStyle}">Status</th>
      <th style="${thStyle}">Sent By</th>
      <th style="${thStyle}">Sent On</th>
    </tr>`;

  function sectionHeader(label, bg, color, colspan) {
    return `<tr style="background:${bg};">
      <td colspan="${colspan}" style="padding:6px 12px;font-weight:bold;color:${color};font-size:13px;">${label}</td>
    </tr>`;
  }

  function makeRow(r, idx, bg, border, statClr, statTxt) {
    const td = `padding:8px 12px;border-bottom:1px solid ${border};`;
    return `<tr style="background:${bg};">
      <td style="${td}">${idx + 1}</td>
      <td style="${td}">${escapeHtml(r.track)}</td>
      <td style="${td}">${escapeHtml(r.subject_keyword)}</td>
      <td style="${td}">${escapeHtml(r.owners.join(" / "))}</td>
      <td style="${td}color:${statClr};font-weight:bold;">${statTxt}</td>
      <td style="${td}">${escapeHtml(r.sentBy || "—")}</td>
      <td style="${td}">${escapeHtml(r.sentOn  || "—")}</td>
    </tr>`;
  }

  const sentRows = sentItems.map((r, i) =>
    makeRow(r, i, "#d4edda", "#c3e6cb", "#155724", "✅ Sent")
  ).join("\n");

  const notSentRows = notSentItems.map((r, i) =>
    makeRow(r, i, "#f8d7da", "#f5c6cb", "#721c24", "❌ Not Sent")
  ).join("\n");

  const tbody =
    (sentCount > 0
      ? sectionHeader(`✅ Submitted (${sentCount})`, "#b8dfc7", "#155724", 7) + sentRows
      : "") +
    (notSentCount > 0
      ? sectionHeader(`❌ Not Submitted (${notSentCount})`, "#f1b8be", "#721c24", 7) + notSentRows
      : "");

  const pendingHtml = notSentCount > 0
    ? `<div style="margin-top:12px;">
        <strong>❌ Not Submitted:</strong>
        <ul style="margin:6px 0 0 0;">
          ${notSentItems.map((r) => `<li><strong>${escapeHtml(r.track)}</strong> — ${escapeHtml(r.owners.join(" / "))}</li>`).join("\n")}
        </ul>
       </div>`
    : "";

  return `<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:960px;margin:0 auto;padding:16px;color:#333;">
  <h2 style="margin:0 0 4px;">${escapeHtml(title)}</h2>
  <p style="margin:2px 0;color:#555;">${escapeHtml(reason)}</p>
  <p style="margin:2px 0 16px;color:#555;">Checking emails sent: ${escapeHtml(windowText)}</p>

  <table style="border-collapse:collapse;width:100%;">
    <thead>${colHeaders}</thead>
    <tbody>${tbody}</tbody>
  </table>

  <div style="margin-top:16px;padding:12px;background:#f8f9fa;border-radius:4px;">
    <strong>Summary:</strong> &nbsp;✅ ${sentCount} Sent &nbsp;&nbsp; ❌ ${notSentCount} Not Sent
  </div>

  ${pendingHtml}

  ${footer ? `<p style="color:#888;font-size:12px;margin-top:16px;border-top:1px solid #eee;padding-top:8px;">${footer}</p>` : ""}
</body></html>`;
}

// ============================================================================
// EMAIL NOTIFICATION DISPATCH
// ============================================================================

/**
 * Sends notifications via MailApp to Slack channel integration emails.
 * 
 * @param {string} subject - Email subject line.
 * @param {string} plainText - Plain text message payload.
 * @param {string} htmlBody - Rendered HTML content.
 */
function sendSlackNotification(subject, plainText, htmlBody) {
  MailApp.sendEmail({
    to:       WEEKLY_STATUS_CONFIG.SLACK_CHANNEL_EMAIL,
    subject:  subject,
    body:     plainText,
    htmlBody: htmlBody,
  });
  Logger.log("✅ Slack notification sent.");
}

// ============================================================================
// MAIN EXECUTION ENTRYPOINT
// Triggered automatically via Apps Script Time-based triggers.
// ============================================================================

/**
 * Core entrypoint execution function.
 * Utilizes LockService to guarantee concurrent instances do not issue duplicate alerts.
 */
function main() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) {
    Logger.log("⏭  Another run is already in progress — skipping to avoid a duplicate notification.");
    return;
  }

  try {
    Logger.log("=".repeat(60));
    Logger.log(`Weekly Status Checker — ${new Date().toISOString()}`);
    Logger.log("=".repeat(60));

    // Step 1: Read Google Sheet Calendar
    Logger.log("\n[1/3] Reading holiday calendar...");
    const holidays = readHolidays();
    Logger.log(`      ✅ ${holidays.length} holidays loaded`);

    // Step 2: Evaluate each schedule group independently (e.g. CPQ's Mon/Tue
    // schedule runs alongside the default Fri/Mon schedule shared by other tracks).
    const groups = groupTracksBySchedule(WEEKLY_STATUS_CONFIG.TRACKS);
    Logger.log(`\n[2/3] Checking run schedule for ${groups.length} schedule group(s)...`);

    groups.forEach(({ schedule, tracks }) => {
      Logger.log(`\n   ── Schedule [reminder:${DAY_NAMES[schedule.reminderWeekday]} / final:${DAY_NAMES[schedule.finalWeekday]}] — tracks: ${tracks.map((t) => t.track).join(", ")}`);

      const runInfo = getRunInfo(holidays, schedule);
      Logger.log(`      Today    : ${runInfo.todayStr}`);
      Logger.log(`      Run Type : ${runInfo.runType || "skip"}`);
      Logger.log(`      Reason   : ${runInfo.reason}`);

      if (!runInfo.shouldRun) {
        Logger.log("      ⏭  Skipping — not a scheduled run day for this group.");
        return;
      }

      // Step 3: Compute date range & scan inbox
      const { startStr, endStr } = computeSearchWindow(runInfo.todayStr, runInfo.runType, holidays, schedule);
      runInfo.startStr = startStr;
      runInfo.endStr   = endStr;
      Logger.log(`\n      [3/3] Searching Gmail (${startStr} to ${endStr})...`);

      const results = [];
      tracks.forEach((track) => {
        const emailResult = searchEmailForTrack(track, startStr, endStr);
        results.push({ ...track, ...emailResult });
        Logger.log(`      [${track.track}] → ${emailResult.sent ? "✅ Sent by " + emailResult.sentBy : "❌ Not Sent"}`);
      });

      // Step 4: Construct and transmit notification
      const message  = formatSlackMessage(results, runInfo);
      const htmlBody = formatSlackHtmlMessage(results, runInfo);
      Logger.log("\n--- Slack Message Preview ---\n" + message + "\n----------------------------");

      const tag = scheduleTag(schedule);
      const subject = runInfo.runType === "reminder"
        ? `⏰ Weekly Status Reminder — ${runInfo.todayStr} (${tag})`
        : `🔔 Weekly Status Final Report — ${runInfo.todayStr} (${tag})`;
      sendSlackNotification(subject, message, htmlBody);
    });

  } catch (err) {
    Logger.log(`❌ main() failed: ${err}\n${(err && err.stack) || ""}`);
    try {
      sendSlackNotification(
        "⚠️ Weekly Status Checker — Run Failed",
        `The Weekly Status Checker script failed to run.\nError: ${err}`,
        `<p>The Weekly Status Checker script failed to run.</p><p><strong>Error:</strong> ${escapeHtml(String(err))}</p>`
      );
    } catch (notifyErr) {
      Logger.log(`❌ Also failed to send the failure notification: ${notifyErr}`);
    }
    throw err;
  } finally {
    lock.releaseLock();
  }
}

// ============================================================================
// MANUAL TESTING & OVERRIDE UTILITIES
// ============================================================================

/** Forces execution under 'reminder' logic using `TEST_DATE` from CONFIG. */
function runForceReminder() { _forceRun("reminder"); }

/** Forces execution under 'final' logic using `TEST_DATE` from CONFIG. */
function runForceFinal()    { _forceRun("final");    }

/**
 * Shared helper executing forced dispatches to Slack regardless of schedule logic.
 * @param {string} runType - "reminder" or "final".
 * @private
 */
function _forceRun(runType) {
  const testDate = WEEKLY_STATUS_CONFIG.TEST_DATE;
  Logger.log(`⚡ Force run — type: ${runType} | Using TEST_DATE from CONFIG: ${testDate}`);
  const holidays = readHolidays();
  const groups   = groupTracksBySchedule(WEEKLY_STATUS_CONFIG.TRACKS);

  groups.forEach(({ schedule, tracks }) => {
    Logger.log(`\n   ── Schedule [reminder:${DAY_NAMES[schedule.reminderWeekday]} / final:${DAY_NAMES[schedule.finalWeekday]}] — tracks: ${tracks.map((t) => t.track).join(", ")}`);
    const baseInfo = getRunInfo(holidays, schedule, testDate);

    const runInfo = {
      shouldRun: true,
      runType,
      todayStr: baseInfo.todayStr,
      reason:   `⚡ Force Run (${runType}) as of ${baseInfo.todayStr}`,
    };

    const { startStr, endStr } = computeSearchWindow(runInfo.todayStr, runInfo.runType, holidays, schedule);
    runInfo.startStr = startStr;
    runInfo.endStr   = endStr;
    const results = [];
    tracks.forEach((track) => {
      const emailResult = searchEmailForTrack(track, startStr, endStr);
      results.push({ ...track, ...emailResult });
    });

    const message  = formatSlackMessage(results, runInfo);
    const htmlBody = formatSlackHtmlMessage(results, runInfo);
    Logger.log("\n--- Slack Message Preview ---\n" + message + "\n----------------------------");

    const tag = scheduleTag(schedule);
    const subject = runType === "reminder"
      ? `⏰ Weekly Status Reminder — ${runInfo.todayStr} (${tag})`
      : `🔔 Weekly Status Final Report — ${runInfo.todayStr} (${tag})`;
    sendSlackNotification(subject, message, htmlBody);
  });
}

/**
 * Evaluates configured criteria and prints formatted summaries without sending Slack notifications.
 * Always evaluates against the real system date (ignores `TEST_DATE`).
 */
function dryRun() {
  Logger.log("🔵 DRY RUN — no message will be sent to Slack.");
  Logger.log("   Using the real system date (TEST_DATE is ignored — use runForceReminder()/runForceFinal() to simulate a specific day).");
  const holidays = readHolidays();
  const groups   = groupTracksBySchedule(WEEKLY_STATUS_CONFIG.TRACKS);

  groups.forEach(({ schedule, tracks }) => {
    Logger.log(`\n   ── Schedule [reminder:${DAY_NAMES[schedule.reminderWeekday]} / final:${DAY_NAMES[schedule.finalWeekday]}] — tracks: ${tracks.map((t) => t.track).join(", ")}`);
    const runInfo = getRunInfo(holidays, schedule);

    Logger.log(`Today: ${runInfo.todayStr} | Type: ${runInfo.runType || "skip"} | ${runInfo.reason}`);

    if (!runInfo.shouldRun) {
      Logger.log("⏭  Would skip today for this group. Use runForceReminder() or runForceFinal() to test.");
      return;
    }

    const { startStr, endStr } = computeSearchWindow(runInfo.todayStr, runInfo.runType, holidays, schedule);
    runInfo.startStr = startStr;
    runInfo.endStr   = endStr;
    const results = [];
    tracks.forEach((track) => {
      const emailResult = searchEmailForTrack(track, startStr, endStr);
      results.push({ ...track, ...emailResult });
    });

    const message = formatSlackMessage(results, runInfo);
    Logger.log("\n--- Slack Message Preview ---\n" + message + "\n----------------------------");
  });
  Logger.log("🔵 DRY RUN complete. No message sent.");
}

/**
 * Runs a real-date evaluation test. Logs output without dispatching emails.
 * Always evaluates against the real system date (ignores `TEST_DATE`).
 */
function testWithDate() {
  Logger.log("🧪 Testing against the real system date (TEST_DATE is ignored — use runForceReminder()/runForceFinal() to simulate a specific day).");

  const holidays = readHolidays();
  const groups   = groupTracksBySchedule(WEEKLY_STATUS_CONFIG.TRACKS);

  groups.forEach(({ schedule, tracks }) => {
    Logger.log(`\n   ── Schedule [reminder:${DAY_NAMES[schedule.reminderWeekday]} / final:${DAY_NAMES[schedule.finalWeekday]}] — tracks: ${tracks.map((t) => t.track).join(", ")}`);
    const runInfo = getRunInfo(holidays, schedule);

    Logger.log(`   Date      : ${runInfo.todayStr}`);
    Logger.log(`   Run Type  : ${runInfo.runType || "skip"}`);
    Logger.log(`   Reason    : ${runInfo.reason}`);

    if (!runInfo.shouldRun) {
      Logger.log("⏭  Would skip on this date for this group. No email search or Slack message.");
      return;
    }

    const { startStr, endStr } = computeSearchWindow(runInfo.todayStr, runInfo.runType, holidays, schedule);
    runInfo.startStr = startStr;
    runInfo.endStr   = endStr;
    const results = [];
    tracks.forEach((track) => {
      const emailResult = searchEmailForTrack(track, startStr, endStr);
      results.push({ ...track, ...emailResult });
      Logger.log(`   [${track.track}] → ${emailResult.sent ? "✅ Sent by " + emailResult.sentBy : "❌ Not Sent"}`);
    });

    const message = formatSlackMessage(results, runInfo);
    Logger.log("\n--- Slack Message Preview ---\n" + message + "\n----------------------------");
  });
  Logger.log("🧪 Test complete. No Slack message sent.");
}

// ============================================================================
// DIAGNOSTIC HELPERS & TROUBLESHOOTING
// ============================================================================

/**
 * Diagnostic tool to verify Gmail accessibility, queries, and matched date boundaries.
 */
function testEmailSearch() {
  Logger.log("=== Email Search Diagnostic ===");
  Logger.log("Script running as : " + Session.getActiveUser().getEmail());
  Logger.log("Using real system date (TEST_DATE is ignored here).");
  Logger.log("");

  const holidays = readHolidays();
  const groups   = groupTracksBySchedule(WEEKLY_STATUS_CONFIG.TRACKS);

  groups.forEach(({ schedule, tracks }) => {
    const runInfo = getRunInfo(holidays, schedule);
    const { startStr, endStr } = computeSearchWindow(runInfo.todayStr, runInfo.runType || "reminder", holidays, schedule);

    const searchFrom = parseStrictISODate(startStr);
    searchFrom.setDate(searchFrom.getDate() - 2);
    const afterDate = Utilities.formatDate(searchFrom, WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy/MM/dd");

    Logger.log(`\n── Schedule [reminder:${DAY_NAMES[schedule.reminderWeekday]} / final:${DAY_NAMES[schedule.finalWeekday]}] — tracks: ${tracks.map((t) => t.track).join(", ")}`);
    Logger.log(`Run type          : ${runInfo.runType || "(not a scheduled run day — defaulting to reminder window)"}`);
    Logger.log(`Search window: after:${afterDate}  (then range-filter to [${startStr}, ${endStr}] in JS)`);
    Logger.log("Every message in every matching thread is listed below, with its IST calendar date.");
    Logger.log(`A 🎯 marks the ones that fall within [${startStr}, ${endStr}] — those are the only ones searchEmailForTrack() will consider.`);
    Logger.log("");

    tracks.forEach(function (track) {
      Logger.log(`── Track: ${track.track} ──`);
      track.owner_emails.forEach(function (ownerEmail) {
        const q = `from:${ownerEmail} after:${afterDate}`;
        Logger.log("Query: " + q);
        try {
          const threads = GmailApp.search(q, 0, 20);
          Logger.log("  Found: " + threads.length + " thread(s)");
          threads.forEach(function (thread) {
            thread.getMessages().forEach(function (msg) {
              const msgDateStr = Utilities.formatDate(msg.getDate(), WEEKLY_STATUS_CONFIG.TIMEZONE, "yyyy-MM-dd");
              const marker = (msgDateStr >= startStr && msgDateStr <= endStr) ? "🎯" : "  ";
              Logger.log(`  ${marker} [${msgDateStr}] Subject: ${msg.getSubject()}`);
              Logger.log(`      From: ${msg.getFrom()}`);
            });
          });
        } catch (e) {
          Logger.log("  ERROR: " + e);
        }
      });
      Logger.log("---");
    });
  });
}

/**
 * Deep diagnostic utility to debug missing message threads or user search permissions.
 */
function debugFindShashiEmail() {
  Logger.log("=== debugFindShashiEmail ===");
  Logger.log("Running as: " + Session.getActiveUser().getEmail());
  Logger.log("");

  const queries = [
    "from:shashi.kumar@rubrik.com",
    "from:shashi.kumar",
    "PRDOPS_QA Weekly Status Report",
    "Weekly Status Report FY27 Week",
    "list:it-qa-all@rubrik.com",
    "deliveredto:it-qa-all@rubrik.com",
    "to:it-qa-all@rubrik.com",
    "in:anywhere from:shashi.kumar@rubrik.com",
    "in:anywhere PRDOPS_QA Weekly Status",
  ];

  for (const q of queries) {
    try {
      const threads = GmailApp.search(q, 0, 5);
      Logger.log(`[${threads.length} results] Query: ${q}`);
      for (const t of threads) {
        const msg = t.getMessages()[0];
        Logger.log(`  Subject : ${msg.getSubject()}`);
        Logger.log(`  From    : ${msg.getFrom()}`);
        Logger.log(`  Date    : ${msg.getDate()}`);
        Logger.log(`  Labels  : ${t.getLabels().map(l => l.getName()).join(", ") || "(none)"}`);
        Logger.log("");
      }
    } catch (e) {
      Logger.log(`  ERROR: ${e}`);
    }
    Logger.log("---");
  }
}

/** Quick verification to confirm Google Sheet connection and holiday count. */
function testReadHolidays() {
  const holidays = readHolidays();
  Logger.log("✅ Total holidays loaded: " + holidays.length);
  Logger.log("First 5: " + holidays.slice(0, 5).join(", "));
}

/** Debug utility verifying active permissions and running execution context. */
function checkCurrentUser() {
  Logger.log("Script running as: " + Session.getActiveUser().getEmail());
  Logger.log("Effective user  : " + Session.getEffectiveUser().getEmail());
}

// ============================================================================
// AUTOMATED TRIGGER INSTALLATION
// ============================================================================

/**
 * Run once manually to configure automated time-driven project triggers.
 * Clears prior triggers for this script's own `main()` function only, so it
 * can safely coexist with other .gs files' triggers in the same project.
 *
 * Note: Verify Project Settings → Time zone is explicitly set to `Asia/Kolkata`.
 */
function setupTrigger() {
  // Purge only this script's own "main" triggers — leave other files' triggers untouched
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === "main")
    .forEach((t) => ScriptApp.deleteTrigger(t));

  // Schedule automated runs (Wed, Thu, Fri, Mon, Tue @ 22:00 IST)
  ScriptApp.newTrigger("main").timeBased().everyWeeks(1).onWeekDay(ScriptApp.WeekDay.WEDNESDAY).atHour(22).create();
  ScriptApp.newTrigger("main").timeBased().everyWeeks(1).onWeekDay(ScriptApp.WeekDay.THURSDAY).atHour(22).create();
  ScriptApp.newTrigger("main").timeBased().everyWeeks(1).onWeekDay(ScriptApp.WeekDay.FRIDAY).atHour(22).create();
  ScriptApp.newTrigger("main").timeBased().everyWeeks(1).onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(22).create();
  ScriptApp.newTrigger("main").timeBased().everyWeeks(1).onWeekDay(ScriptApp.WeekDay.TUESDAY).atHour(22).create();

  Logger.log("✅ Triggers installed: Wed/Thu/Fri/Mon/Tue at 10 PM IST.");
  Logger.log("   Wednesday only fires a reminder when Thursday AND Friday are both holidays (default schedule).");
  Logger.log("   Tuesday fires CPQ's final check (CPQ's own schedule: reminder Mon, final Tue).");
  Logger.log("   ⚠️  Verify: Project Settings → Time zone → Asia/Kolkata");
}