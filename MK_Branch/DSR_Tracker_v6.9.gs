/**
 * @fileoverview Automates DSR tracking — checks Gmail, logs results, sends reminders.
 * @version 6.9
 *
 * Fix history:
 *   6.5 – renamed getHolidayName → getDSRHolidayName (cross-file GAS scope collision)
 *   6.6 – (broken) per-person from: queries fail for group-delivered mail
 *   6.7 – (broken) removed trailing underscore from subject query → 0 results
 *   6.8 – restored trailing underscore (required for Gmail to match this pattern);
 *          added fallback from:email search for members not found by subject search
 *   6.9 – fixed reminder emails being silently skipped: reminder dedup was reusing the
 *          "already logged to sheet today" flag, which gets set on the FIRST run that
 *          detects NOT_SENT (which can happen hours before the 22:00–23:00 reminder
 *          window opens). That caused later runs during the window to bail out before
 *          ever queuing the reminder. Reminder dedup is now tracked independently via
 *          PropertiesService, set only once the email is actually sent.
 */

//================================================================================================
//==================================== CONFIGURATION =============================================
//================================================================================================

var CONFIG = {
  dailyLogsSpreadsheetId: "170Abs57xqj155DkKxqB8ZqdEjCBRdRaEB9y7yi9XwCE",
  dailyLogsSheetName: "Daily DSR Logs",
  holidayCalendarSheetName: "Rubrik Holiday Calendar-" + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy"),
  monthlyLeaveSpreadsheetId: "1c2Cq5wR-JFeS0rXuYY4KVVB8ofZgmMEPxGF4LLvDh2c",
  monthlyLeaveSheetName: Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "MMMM yyyy"),

  QA_NAMES: [
    "Ashwini Koppad", "Bhavani Marupaka","Ashish Samar",
    "Karthik Surada","US Mahesh Reddy", "Urati Sai Krishna",
  ],

  userEmails: {
    "Ashwini Koppad":    "ashwini.koppad@rubrik.com",
    "Ashish Samar":      "ashish.samar@rubrik.com",
    "Bhavani Marupaka":  "bhavani.marupaka@rubrik.com",
    "Karthik Surada":    "karthik.surada@rubrik.com",
    //"Raja Cherukuri":     "raja.cherukuri@rubrik.com",
    "US Mahesh Reddy":   "usmahesh.reddy@rubrik.com",
    "Urati Sai Krishna": "urati.krishna@rubrik.com",
  },

  reminderCc: "akash.prakash@rubrik.com,it-prodops-qa@rubrik.com",
  reminderStartTime: "22:00",
  reminderEndTime: "23:00",

  // ---- Back-date testing ----
  // Set TEST_MODE: true and OVERRIDE_DATE to the date you want to check (dd-MM-yyyy).
  // Revert by setting TEST_MODE: false — OVERRIDE_DATE is ignored in production.
  TEST_MODE:     false,
  OVERRIDE_DATE: " ",        // e.g. "25-06-2026"

  secondaryLogsSpreadsheetId: "1Ef8tppUggKn7RXl6H7trRe4Ig82wz_Tx6CaKCkwMyhM",
  secondaryLogsSheetName: Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "MMMM yyyy"),
};

var STATUS = {
  SENT: "Sent", NOT_SENT: "Not Sent", LEAVE: "Leave", HOLIDAY: "Holiday", NA: "NA"
};

var COLORS = {
  HEADER_BLUE:     "#0000FF",
  SENT_WHITE:      "#FFFFFF",
  NOT_SENT_ORANGE: "#FFC000",
  LEAVE_GOLD:      "#FFA500",
  WEEKEND_YELLOW:  "#FFFF00",
  HOLIDAY_MAGENTA: "#FF00FF",
  ERROR_RED:       "#FF4136",
  FONT_WHITE:      "#FFFFFF",
  FONT_BLACK:      "#000000"
};

var LEAVE_CODES = {
  "PL":   "Planned Leave",
  "UNPL": "Unplanned Leave",
  "H":    "Leave",
  "N/A":  "Not Applicable"
};

//================================================================================================
//==================================== MAIN FUNCTION =============================================
//================================================================================================

function checkQADailyReportAllSenders() {
  var todayDate = new Date();
  if (CONFIG.TEST_MODE && CONFIG.OVERRIDE_DATE) {
    var dp = CONFIG.OVERRIDE_DATE.split("-");
    todayDate = new Date(parseInt(dp[2]), parseInt(dp[1]) - 1, parseInt(dp[0]));
    console.warn("⚠️  TEST MODE ACTIVE — checking back date: " + CONFIG.OVERRIDE_DATE + " (reminders suppressed)");
  }
  var formattedDate = Utilities.formatDate(todayDate, Session.getScriptTimeZone(), "dd-MM-yyyy");
  var targetDay     = todayDate.getDate();
  cleanupOldReminderFlags(formattedDate);

  console.log("DSR Check started for: " + formattedDate);

  try {
    var dailyLogsSS = SpreadsheetApp.openById(CONFIG.dailyLogsSpreadsheetId);
    var leaveSS     = SpreadsheetApp.openById(CONFIG.monthlyLeaveSpreadsheetId);
    var secondarySS = CONFIG.secondaryLogsSpreadsheetId
                        ? SpreadsheetApp.openById(CONFIG.secondaryLogsSpreadsheetId)
                        : null;

    var logSheet = dailyLogsSS.getSheetByName(CONFIG.dailyLogsSheetName);
    if (!logSheet) throw new Error("Primary log sheet not found.");

    // Derive sheet tab names from todayDate so TEST_MODE back-dates use the correct month's tab.
    // Leave tracker tabs use abbreviated month ("Jun 2026" = "MMM yyyy").
    // Secondary matrix tabs are INCONSISTENTLY named: some use full month ("July 2026"), some abbreviated ("Jun 2026").
    // Try both formats and use whichever tab actually exists.
    var leaveSheetName = Utilities.formatDate(todayDate, Session.getScriptTimeZone(), "MMM yyyy");
    var secondarySheetName = (function() {
      if (!secondarySS) return "";
      var tz    = Session.getScriptTimeZone();
      var short = Utilities.formatDate(todayDate, tz, "MMM yyyy");   // e.g. "Jul 2026", "Aug 2026" ← preferred
      var full  = Utilities.formatDate(todayDate, tz, "MMMM yyyy");  // e.g. "July 2026" ← fallback
      if (secondarySS.getSheetByName(short)) { console.log("Secondary tab found: " + short); return short; }
      if (secondarySS.getSheetByName(full))  { console.log("Secondary tab found: " + full);  return full; }
      console.warn("Secondary matrix: no tab found for '" + short + "' or '" + full + "'");
      return short;
    })();
    var matrixUpdater = createMatrixUpdater(secondarySS, secondarySheetName, targetDay);
    var todaysLoggedMessages = getTodaysLoggedMessages(logSheet, formattedDate);

    // ---- STEP 1: Weekend check ----
    if (todayDate.getDay() === 0 || todayDate.getDay() === 6) {
      var dayName = Utilities.formatDate(todayDate, Session.getScriptTimeZone(), "EEEE");
      if (!todaysLoggedMessages.has(dayName)) {
        appendFormattedRow(
          logSheet,
          [formattedDate, "DSR not required: " + dayName, "", STATUS.NA],
          COLORS.WEEKEND_YELLOW, COLORS.FONT_BLACK
        );
      }
      console.log("Weekend (" + dayName + ") — DSR check skipped.");
      return;
    }

    // ---- STEP 2: Holiday check ----
    var holidayName = getDSRHolidayName(
      dailyLogsSS.getSheetByName(CONFIG.holidayCalendarSheetName),
      formattedDate
    );
    if (holidayName) {
      if (!todaysLoggedMessages.has(holidayName)) {
        appendFormattedRow(
          logSheet,
          [formattedDate, "Holiday: " + holidayName, "", STATUS.HOLIDAY],
          COLORS.HOLIDAY_MAGENTA, COLORS.FONT_WHITE
        );
      }
      console.log("Holiday (" + holidayName + ") — DSR check skipped.");
      return;
    }

    // ---- STEP 3 & 4: Per-member leave / DSR check ----
    var dsrThreadsBySender = searchAllDsrEmails(formattedDate);
    var leaveSheet = leaveSS.getSheetByName(leaveSheetName);
    if (!leaveSheet) console.warn("Leave sheet '" + leaveSheetName + "' not found — leave data skipped.");
    var leaveMap = readLeaveTrackerForDate(leaveSheet, targetDay);

    var rowsToLog       = [];
    var formatsToApply  = [];
    var membersToRemind = [];
    var sentList    = [];
    var notSentList = [];
    var leaveList   = [];

    CONFIG.QA_NAMES.forEach(function(name) {
      var result = processSingleMember(
        name, formattedDate, dsrThreadsBySender, leaveMap, todaysLoggedMessages
      );

      matrixUpdater.update(name, result.status);  // always update matrix, even if already logged

      // Always track status for the summary — regardless of whether already logged
      if      (result.status === STATUS.SENT)     { sentList.push(name); }
      else if (result.status === STATUS.NOT_SENT) { notSentList.push(name); }
      else if (result.status === STATUS.LEAVE)    { leaveList.push(name); }

      if (result.shouldLog && result.rowToLog) {
        rowsToLog.push(result.rowToLog);
        formatsToApply.push(result.format);
      }

      // Reminder dedup is independent of sheet-row dedup — the row can get logged
      // hours before the 22:00–23:00 window opens (see v6.9 fix history above), so
      // we only skip the reminder if the EMAIL itself was already sent today.
      if (result.status === STATUS.NOT_SENT && !hasReminderBeenSentToday(name, formattedDate)) {
        membersToRemind.push(name);
      }
    });

    matrixUpdater.flush();

    // ---- Execution summary ----
    console.log("---------- DSR Summary: " + formattedDate + " ----------");
    console.log("Sent     (" + sentList.length    + ") : " + (sentList.join(", ")    || "None"));
    console.log("Not Sent (" + notSentList.length + ") : " + (notSentList.join(", ") || "None"));
    console.log("On Leave (" + leaveList.length   + ") : " + (leaveList.join(", ")   || "None"));
    console.log("---------------------------------------------------");

    if (rowsToLog.length > 0) {
      var bgMatrix = [], fontMatrix = [];
      formatsToApply.forEach(function(f) {
        bgMatrix.push([f.bgColor, f.bgColor, f.bgColor, f.bgColor]);
        fontMatrix.push([f.fontColor, f.fontColor, f.fontColor, f.fontColor]);
      });
      logSheet.getRange(logSheet.getLastRow() + 1, 1, rowsToLog.length, 4)
        .setValues(rowsToLog)
        .setBackgrounds(bgMatrix)
        .setFontColors(fontMatrix)
        .setHorizontalAlignment("center")
        .setBorder(true, true, true, true, true, true);
    }

    if (membersToRemind.length > 0 && isWithinReminderWindow() && !CONFIG.TEST_MODE) {
      membersToRemind.forEach(function(name) {
        sendReminderEmail(name, formattedDate);
        markReminderSent(name, formattedDate);
      });
    } else if (membersToRemind.length > 0 && CONFIG.TEST_MODE) {
      console.log("TEST MODE — reminder emails suppressed for: " + membersToRemind.join(", "));
    }

  } catch (e) {
    console.error("DSR check failed: " + e.message + "\nStack: " + e.stack);
  }
}

//================================================================================================
//============================== GMAIL SEARCH ====================================================
//================================================================================================

function searchAllDsrEmails(dateStr) {
  var results = {};
  CONFIG.QA_NAMES.forEach(function(n) { results[n] = []; });

  // Pre-build reverse map for O(1) email → name lookup during thread matching
  var emailToName = {};
  CONFIG.QA_NAMES.forEach(function(n) {
    var e = (CONFIG.userEmails[n] || '').toLowerCase();
    if (e) emailToName[e] = n;
  });

  // Step 1: Broad subject search.
  // Two queries cover both subject formats in use:
  //   Format A: "QA-Daily Status Report_DD-MM-YYYY_ Name"  (space after underscore — Gmail finds word boundary)
  //   Format B: "QA-Daily Status Report_DD-MM-YYYY_Name"   (no space — Gmail treats _Name as one token, needs separate query)
  // Trailing underscore in queryA is required (removing it caused 0 results in v6.7).
  var queryA = 'subject:"QA-Daily Status Report_' + dateStr + '_" in:anywhere';
  var queryB = 'subject:"QA-Daily Status Report_' + dateStr + '" in:anywhere';
  var rawA = GmailApp.search(queryA, 0, 30);
  var rawB = GmailApp.search(queryB, 0, 30);
  var seenIds = {};
  var threads = [];
  rawA.concat(rawB).forEach(function(t) {
    if (!seenIds[t.getId()]) { seenIds[t.getId()] = true; threads.push(t); }
  });
  console.log("Subject search → " + threads.length + " thread(s) [withUnderscore=" + rawA.length + ", withoutUnderscore=" + rawB.length + "] | " + queryA + " | " + queryB);

  threads.forEach(function(t) {
    console.log("  Thread subject: [" + t.getFirstMessageSubject() + "]");
    var messages = t.getMessages();
    for (var m = 0; m < messages.length; m++) {
      var rawFrom     = messages[m].getFrom();
      var fromLower   = rawFrom.toLowerCase();
      var angleMatch  = rawFrom.match(/<([^>]+)>/);
      var senderEmail = angleMatch ? angleMatch[1].toLowerCase() : fromLower.trim();

      console.log("  Thread: from=[" + senderEmail + "] subject=[" + messages[m].getSubject() + "]");

      var matched = false;
      var name = emailToName[senderEmail];
      if (!name) {
        CONFIG.QA_NAMES.some(function(n) {
          var configEmail = (CONFIG.userEmails[n] || '').toLowerCase();
          if (configEmail && fromLower.includes(configEmail)) { name = n; return true; }
        });
      }
      if (name && results[name].indexOf(t) === -1) {
        results[name].push(t);
        matched = true;
        console.log("    -> Matched: " + name);
      }

      if (matched) break;
    }
  });

  // Step 2: Fallback for any member still not found.
  // Uses from:email + full-text keyword — avoids subject: operator which breaks
  // combined GmailApp queries (confirmed broken in v6.6).
  var dp          = dateStr.split("-");
  var gmailAfter  = dp[2] + "/" + dp[1] + "/" + dp[0];
  var tomorrow    = new Date(parseInt(dp[2]), parseInt(dp[1]) - 1, parseInt(dp[0]) + 1);
  var gmailBefore = Utilities.formatDate(tomorrow, Session.getScriptTimeZone(), "yyyy/MM/dd");

  CONFIG.QA_NAMES.forEach(function(n) {
    if (results[n].length > 0) return;
    var email = CONFIG.userEmails[n];
    if (!email) return;

    // Omit phrase constraint — combined from:+phrase+date queries are unreliable in GmailApp (v6.6).
    // Subject verification is done in code below to avoid Gmail tokenization issues with hyphens/underscores.
    var fallback = 'from:' + email + ' after:' + gmailAfter + ' before:' + gmailBefore + ' in:anywhere';
    var candidateThreads = GmailApp.search(fallback, 0, 10);
    var fallbackThreads = candidateThreads.filter(function(t) {
      var subj = t.getFirstMessageSubject().toLowerCase();
      return subj.indexOf('qa-daily status report') !== -1 && subj.indexOf(dateStr) !== -1;
    });
    console.log("  Fallback [" + n + "]: " + candidateThreads.length + " candidate(s) → " + fallbackThreads.length + " matched | " + fallback);
    if (fallbackThreads.length > 0) {
      results[n] = fallbackThreads;
    }
  });

  // Step 3: Summary
  CONFIG.QA_NAMES.forEach(function(n) {
    console.log(n + " : " + results[n].length + " thread(s)");
  });

  return results;
}

//================================================================================================
//============================== CORE HELPERS ====================================================
//================================================================================================

function normalizeName(name) {
  return name ? name.toString().toLowerCase().trim() : "";
}

function getDSRHolidayName(sheet, dateStr) {
  if (!sheet) return null;
  try {
    var data = sheet.getDataRange().getValues();
    for (var i = 1; i < data.length; i++) {
      var cell    = data[i][1];
      var cellStr = (cell instanceof Date)
        ? Utilities.formatDate(cell, Session.getScriptTimeZone(), "dd-MM-yyyy")
        : String(cell).trim();
      if (cellStr === dateStr) return String(data[i][0]);
    }
  } catch (e) {
    console.warn("DSR holiday check skipped: " + e.message);
  }
  return null;
}

function readLeaveTrackerForDate(sheet, targetDay) {
  var leaveMap = {};
  if (!sheet) return leaveMap;
  try {
    var data = sheet.getDataRange().getValues();
    if (data.length < 3) return leaveMap;

    // Leave tracker structure (confirmed from sheet screenshot + execution log):
    //   Row 1 (data[0]): "su", count, "Mon", "Tue", "Wed" ... — day-of-week abbreviations, NOT dates
    //   Row 2 (data[1]): "Name", "Actual WD", Date(Jun 1), Date(Jun 2) ... — actual Date objects
    //   Row 3+ (data[2]+): employee rows with leave codes
    var header = data[1];
    var col    = -1;

    // Log both header rows once so the format is visible in the execution log
    var row1Sample = data[0].slice(0, 6).map(function(v) { return '"' + v + '" [' + (v instanceof Date ? "Date" : typeof v) + ']'; });
    var row2Sample = header.slice(0, 6).map(function(v)  { return '"' + v + '" [' + (v instanceof Date ? "Date" : typeof v) + ']'; });
    console.log("Leave row 1 (day names): " + row1Sample.join(", "));
    console.log("Leave row 2 (dates):     " + row2Sample.join(", "));

    for (var i = 0; i < header.length; i++) {
      var h = header[i];
      if (h instanceof Date && h.getDate() === targetDay) { col = i; break; }
      if (typeof h === "number" && h === targetDay)        { col = i; break; }
      if (typeof h === "string") {
        // Handles "Jun 25, 2026" format stored as text in the sheet
        var parsed = new Date(h);
        if (!isNaN(parsed.getTime()) && parsed.getDate() === targetDay) { col = i; break; }
      }
    }

    console.log("Leave tracker: day=" + targetDay + " → col=" + col + " (sheet=" + sheet.getName() + ")");
    if (col === -1) {
      console.warn("No column found for day " + targetDay + " in leave sheet '" + sheet.getName() + "' — leave data skipped.");
      return leaveMap;
    }

    // Employee rows start at data[2] (row 3 in the sheet)
    for (var r = 2; r < data.length; r++) {
      var rawName = String(data[r][0] || "").trim();
      if (!rawName) continue;
      var code = String(data[r][col] || "").trim().toUpperCase();
      if (LEAVE_CODES[code]) {
        leaveMap[normalizeName(rawName)] = LEAVE_CODES[code];
        console.log("Leave detected: " + rawName + " → " + code + " (" + LEAVE_CODES[code] + ")");
      }
    }
  } catch (e) {
    console.warn("Leave check skipped: " + e.message);
  }
  return leaveMap;
}

function processSingleMember(name, dateStr, threads, leaveMap, logged) {
  var userThreads = threads[name];
  var leaveDesc   = leaveMap[normalizeName(name)];

  var status = STATUS.NOT_SENT;
  var color  = COLORS.NOT_SENT_ORANGE;
  var time   = "";
  var msg    = "DSR not received from " + name;

  if (leaveDesc) {
    status = STATUS.LEAVE;
    color  = COLORS.LEAVE_GOLD;
    msg    = "DSR skip: " + name + " on " + leaveDesc;
  } else if (userThreads && userThreads.length > 0) {
    status = STATUS.SENT;
    color  = COLORS.SENT_WHITE;
    time   = Utilities.formatDate(
               userThreads[0].getLastMessageDate(),
               Session.getScriptTimeZone(),
               "hh:mm a"
             );
    msg    = name;
  }

  return {
    status:    status,
    shouldLog: !logged.has(msg),
    format:    { bgColor: color, fontColor: COLORS.FONT_BLACK },
    rowToLog:  [dateStr, msg, time, status]
  };
}

function createMatrixUpdater(ss, sheetName, day) {
  if (!ss) return { update: function() {}, flush: function() {} };
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    console.warn("Secondary matrix sheet '" + sheetName + "' not found — matrix updates skipped.");
    return { update: function() {}, flush: function() {} };
  }

  var data = sheet.getDataRange().getValues();
  if (data.length < 2) return { update: function() {}, flush: function() {} };

  // Secondary sheet structure (same layout as leave tracker):
  //   Row 1 (data[0]): "21.00", day-of-week abbreviations ("Fri", "Mon", "Tue" ...)
  //   Row 2 (data[1]): "Name", "Actual WD", Date(Jun 5), Date(Jun 8) ... — actual dates
  //   Row 3+ (data[2]+): employee rows
  var header = data[1];
  var col    = -1;

  // Log both header rows so date format is visible in execution log
  var row1Sample = data[0].slice(0, 6).map(function(v) { return '"' + v + '" [' + (v instanceof Date ? "Date" : typeof v) + ']'; });
  var row2Sample = header.slice(0, 6).map(function(v)  { return '"' + v + '" [' + (v instanceof Date ? "Date" : typeof v) + ']'; });
  console.log("Matrix row 1 (day names): " + row1Sample.join(", "));
  console.log("Matrix row 2 (dates):     " + row2Sample.join(", "));

  for (var i = 0; i < header.length; i++) {
    var h = header[i];
    if (h instanceof Date && h.getDate() === day) { col = i; break; }
    if (typeof h === "number" && h === day)        { col = i; break; }
    if (typeof h === "string") {
      // Handles "Jun 25, 2026" format stored as text in the sheet
      var parsed = new Date(h);
      if (!isNaN(parsed.getTime()) && parsed.getDate() === day) { col = i; break; }
    }
  }

  console.log("Matrix updater: day=" + day + " → col=" + col + " (sheet=" + sheetName + ")");
  if (col === -1) {
    console.warn("No column found for day " + day + " in secondary matrix '" + sheetName + "' — updates skipped.");
  }

  // Pre-build name → row index map (1-based) to avoid O(n) scan per update
  var nameToRow = {};
  for (var r = 0; r < data.length; r++) {
    nameToRow[normalizeName(data[r][0])] = r + 1;
  }

  var pending = {};

  return {
    update: function(name, status) {
      pending[name] = status;
    },
    flush: function() {
      if (col === -1) return;
      Object.keys(pending).forEach(function(name) {
        var row = nameToRow[normalizeName(name)];
        if (row !== undefined) {
          console.log("Matrix write: " + name + " → row " + row + ", col " + (col + 1) + " = " + pending[name]);
          sheet.getRange(row, col + 1).setValue(pending[name]);
        } else {
          console.warn("Matrix: '" + name + "' not found in sheet rows — skipped.");
        }
      });
    }
  };
}

function getTodaysLoggedMessages(sheet, dateStr) {
  var messages = new Set();
  var lastRow = sheet.getLastRow();
  if (lastRow < 1) return messages;

  sheet.getRange(1, 1, lastRow, 2).getValues().forEach(function(r) {
    var d = (r[0] instanceof Date)
      ? Utilities.formatDate(r[0], Session.getScriptTimeZone(), "dd-MM-yyyy")
      : String(r[0]);
    if (d === dateStr) messages.add(r[1]);
  });
  return messages;
}

function appendFormattedRow(sheet, row, bg, font) {
  sheet.appendRow(row);
  sheet.getRange(sheet.getLastRow(), 1, 1, 4)
    .setBackground(bg)
    .setFontColor(font)
    .setHorizontalAlignment("center")
    .setBorder(true, true, true, true, true, true);
}

//================================================================================================
//============================== REMINDER EMAIL ==================================================
//================================================================================================

function isWithinReminderWindow() {
  var current = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "HH:mm");
  return current >= CONFIG.reminderStartTime && current <= CONFIG.reminderEndTime;
}

function sendReminderEmail(name, dateStr) {
  if (CONFIG.TEST_MODE) {
    console.log("TEST MODE — email to " + name + " blocked inside sendReminderEmail.");
    return;
  }
  var email = CONFIG.userEmails[name];
  if (!email) { console.warn("No email configured for: " + name); return; }

  var parts     = name.split(" ");
  var firstName = parts[0];
  var subject   = "Reminder: QA-Daily Status Report Pending for " + dateStr;
  var body      = "Hello " + firstName + ",\n\n"
    + "This is an automated reminder that we have not yet received your Daily Status Report for "
    + dateStr + ".\n\n"
    + "If you have already sent it, please disregard this message.\n\n"
    + "Thank you,\nAutomated QA-DSR Bot";

  var options = {};
  if (CONFIG.reminderCc && CONFIG.reminderCc.trim()) options.cc = CONFIG.reminderCc;

  try {
    GmailApp.sendEmail(email, subject, body, options);
    console.log("Reminder sent to: " + name + " (" + email + ")");
  } catch (e) {
    console.error("Failed to send reminder to " + name + ": " + e.message);
  }
}

function hasReminderBeenSentToday(name, dateStr) {
  return PropertiesService.getScriptProperties()
    .getProperty("reminded_" + dateStr + "_" + name) === "true";
}

function markReminderSent(name, dateStr) {
  PropertiesService.getScriptProperties()
    .setProperty("reminded_" + dateStr + "_" + name, "true");
}

function cleanupOldReminderFlags(dateStr) {
  var props = PropertiesService.getScriptProperties();
  var all = props.getProperties();
  Object.keys(all).forEach(function(k) {
    if (k.indexOf("reminded_") === 0 && k.indexOf("reminded_" + dateStr + "_") !== 0) {
      props.deleteProperty(k);
    }
  });
}
