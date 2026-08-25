---
name: mid-year-project-collator
description: Scrapes your own Jira, Confluence, Slack, Google Drive, Gmail, and Calendar activity for the Mid-Year OPE window (Feb 1 - Jul 31, 2026), clusters it into quarter-organized projects, identifies stakeholders, flags where AI tools influenced outcomes, drafts your two self-assessment answers, and writes a self-contained, Rubrik-branded HTML dashboard you can open in any browser. Use when someone wants to prep for their mid-year check-in, wants a "project collator," wants to see everything they worked on this half, or wants a self-assessment dashboard, and is working in Claude Code rather than Claude Cowork.
---

# Mid-Year Project Collator & OPE Self-Assessment Prep (Claude Code edition)

Builds a "what did I actually work on this half" dashboard for an individual Rubrikan, so they can write a strong Mid-Year OPE self-assessment without trying to remember six months of work from scratch. Pulls from every MCP tool the person has connected, groups the raw activity into projects organized by quarter (Q1, Q2, or both), identifies who they worked with on each one, drafts a starting self-assessment, and writes it all to a single self-contained HTML file the employee opens directly in their browser.

This is a personal-use skill: it only ever surfaces the signed-in employee's own activity. It never touches Workday and never submits anything — the employee always reviews and edits before using anything in their real self-assessment.

**This is the Claude Code adaptation of a Claude Cowork skill of the same name.** The two differ in three ways, all covered below: (1) MCP connectors are whatever the person has added to Claude Code themselves, not managed Cowork connectors, so tool names vary and must be discovered at runtime; (2) the output is a plain HTML file written to disk, not a persisted Cowork artifact; (3) the self-assessment draft is generated once, during this run, and baked into the file as editable starting text — there is no in-browser "regenerate" button calling back to Claude, since a static HTML file has no live connection to a model.

## Prerequisites: MCP servers

Claude Code has no built-in connectors — the person needs to add MCP servers themselves before this skill can pull real data. Point them at:

- **Jira / Confluence**: Atlassian's official MCP server, or `claude mcp add` pointing at any Jira/Confluence MCP integration they have access to.
- **Slack**: an MCP server such as Slack's own MCP integration (OAuth-based).
- **Google Drive / Gmail / Calendar**: a Google Workspace MCP server (several exist; any one that exposes search/list tools for Drive, Gmail, and Calendar works).

Exact setup commands and tool names vary by which MCP server implementation someone installs, so don't hardcode assumptions. If none are connected yet, say so plainly and offer to proceed with whatever subset is available rather than blocking — Jira/Confluence access is commonly missing for non-Engineering roles, and that's fine.

## Config (edit this block each review cycle)

```
WINDOW_START = 2026-02-01
WINDOW_END   = 2026-07-31
CYCLE_NAME   = "Mid-Year OPE FY27"
SELF_ASSESSMENT_OPENS = 2026-08-17
SELF_ASSESSMENT_DUE   = 2026-09-03 (11:59pm PT)
```

Cycle-specific copy (employee name, window, deadlines, question text) lives in the `CYCLE` object inside the template's script — edit that object each cycle rather than the markup. Quarter boundaries live in the `QUARTERS` array (Q1 = Feb–Apr, Q2 = May–Jul, plus a third "Both quarters" option for work that spanned the whole window) — adjust only if the fiscal quarter boundaries actually differ.

## Brand (always use this — do not substitute other colors)

- Navy (primary): `#050550`
- Teal (accent): `#00C7C7`
- Teal, darker, for text-on-white (readability): `#006d6d`
- Light teal tint for panel backgrounds: `#f0fdfd`
- 5-step navy → teal ramp for project accent colors / legend: `#050550`, `#04366e`, `#03668c`, `#0197a9`, `#00c7c7`
- Source-type colors (mix bars, badges, search matching): Slack `#050550`, Drive `#00C7C7`, Gmail `#16217a`, Calendar `#006d6d`, Jira `#0b1f66`, Confluence `#049a9a`, Zoom `#0e7490` (only if a Zoom MCP tool is actually confirmed — see Step 1)
- Stakeholder avatar colors: hash the name to a hue, constrained to the teal→navy band (175–265°) so avatars stay on-brand — see `nameColor()` in the template.

## Steps

### 1. Discover what's actually connected

List your available tools and identify which MCP servers are live for Jira, Confluence, Slack, Google Drive, Gmail, and Google Calendar (and Zoom, if present — don't assume it exists, confirm a real tool name first). Note the exact tool names you find; you'll use them directly in Step 3 instead of any hardcoded example. Skip anything not connected and note it as "not connected" in the dashboard's source badges — never fail the whole run because one source is missing.

State the review window from Config and proceed without asking a clarifying question unless something is genuinely ambiguous (e.g. the person started mid-window, or wants a shorter lookback).

### 2. Identify the employee across systems

- Jira: look for a "current user" / "whoami" style tool to get the account ID, display name, and email. If Jira access 401s or isn't connected, skip it.
- Everything else typically runs as the signed-in employee already, so "me" filters apply directly.

### 3. Pull raw activity per source

Using whatever tools you found in Step 1, gather each source's activity for the window (Feb 1 – Jul 31, 2026 by default):

- **Jira** — issues where the employee is assignee or reporter, updated within the window.
- **Confluence** — pages authored/edited by the employee, or matching the Jira project keys/epics found above (best-effort keyword search, since there's rarely a built-in "pages I edited" filter).
- **Slack** — messages from the employee in the window; also search for messages containing links, since those tend to be strong project signals (shared docs, PRs, decisions).
- **Google Drive** — files owned by or last modified by the employee within the window.
- **Gmail** — emails sent by the employee in the window (treat as a weak signal — subject lines only — useful for catching external/customer-facing work).
- **Google Calendar** — events on the employee's primary calendar in the window. This is your best source of **stakeholders and timing**: recurring meeting series are strong project signals, and event dates help you estimate which quarter a project belongs to. Pull in modest chunks if the tool has response-size limits.
- **Zoom** (if confirmed) — meetings/recordings in the window; attendees feed stakeholders, AI Companion summaries feed the AI-involvement flag.

### 4. Normalize

Turn every result into a common shape: `{ source, title, url/link, date, snippet, people: [] }`. Keep each item's date — you'll need it for quarter assignment.

### 5. Cluster into projects

Group normalized items into projects using, in order of reliability: shared Jira project/epic key → shared Confluence space or matching keywords in titles → shared Slack channel or repeated keyword → recurring Calendar meeting series title. This is fuzzy grouping — use your own judgment. Aim for 4-8 projects; merge duplicates under different naming, and put true one-offs in an "Other / smaller contributions" bucket.

For each project, produce:
- name
- **quarter**: `"q1"` (Feb–Apr), `"q2"` (May–Jul), or `"both"` if the work clearly spanned the whole window. First-pass estimate — the person can correct it via a dropdown on each card afterward, so don't agonize over borderline cases. Only use `"both"` when the evidence genuinely spans both quarters.
- **role**: the employee's own contribution type on this specific project (e.g. "Program Lead," "Reviewer," "Contributor") — infer from evidence, don't default everything to "Lead."
- a 1-2 sentence summary of what it was and the employee's role
- impact/outcome notes (only what's evidenced — no invented metrics)
- **stakeholders**: dedup people across the cluster, label the relationship if obvious (e.g. "manager," "frequent collaborator"), leave blank if not obvious
- source items (type + title + link + date)
- an `ai_flag` (true if any item mentions Claude, Cowork, ChatGPT, Copilot, NotebookLM, Zoom AI Companion, "AI-generated," "automat," "prompt," etc.)

### 6. Draft the self-assessment now, during this run

Unlike the Cowork version of this skill (which calls a live in-browser model), the HTML file this skill produces has no way to call Claude after it's written — it's a static file with no server behind it. So the two self-assessment answers must be drafted by you, right now, as part of this conversation, using the project data you just built:

- Question 1: "Based on goals for the past quarter/half year, describe top achievements, their impact, and how AI was used to influence outcomes."
- Question 2: "What are the most important areas of focus for success in the quarter/half year ahead — in performance, development, and ways of working?"

Write first-person answers grounded in each project's role/summary/impact. For Question 1, lead with the highest-impact projects, state impact concretely, and call out any project where `ai_flag` is true, describing what the AI involvement looked like. For Question 2, if the data doesn't support clear forward-looking goals, use a short bracketed placeholder like "[Add your focus areas here]" rather than inventing goals.

Put the result into `INITIAL_DRAFT = { q1: "...", q2: "..." }` in the template — this is what pre-fills the two textareas when the dashboard opens. It's still fully editable in the browser; edits just persist to that browser's `localStorage`, not back to you. **If the employee wants a regenerated draft after editing project fields**, the only path is to tell you (Claude Code) what changed — either paste the edited text back into the conversation, or just re-run this skill — and you rebuild the file with a fresh `INITIAL_DRAFT`. Say this plainly when you hand off the file so nobody expects a live "Generate" button to work.

### 7. Write the dashboard file

Use your file-write tool to save the HTML below to disk — ask the person where (current directory, Desktop, a specific path) if it's not obvious — with the `CYCLE` and `DATA` objects populated from your real synthesized data, and `INITIAL_DRAFT` populated from Step 6. Don't call any MCP tools from inside the HTML itself; it's meant to be opened as a plain local file, no server or live connection required.

**Do not change** the CSS colors, the instructions banner, the editable-field styling, the modal structure, the five clickable stat cards, the quarter grouping (Q1 / Q2 / Both quarters), the stakeholder directory, the feedback request template, the avatar split (circle = filter, name = feedback), the empty-state handling, or the try/catch guards around `localStorage`. These came from direct user feedback on the Cowork version and fixed real problems found in testing — the only intentional removal versus that version is the live `askClaude` call, replaced by the pre-baked `INITIAL_DRAFT` described in Step 6.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Mid-Year Project Dashboard</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; background: #f5f5f7; color: #1f1f23;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 14px; line-height: 1.5;
  }
  .wrap { max-width: 1040px; margin: 0 auto; }
  :focus-visible { outline: 2px solid #00C7C7; outline-offset: 2px; }

  .hero {
    background: linear-gradient(135deg, #050550 0%, #0a2a6e 55%, #045c66 100%);
    color: #fff; border-radius: 16px; padding: 22px 26px; margin-bottom: 20px;
    box-shadow: 0 4px 18px rgba(5,5,80,0.3);
    border-bottom: 4px solid #00C7C7;
  }
  .hero h1 { font-size: 22px; margin: 0 0 4px; }
  .hero .meta { color: #a9f2f2; font-size: 13px; }
  .badges { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; }
  .badge { padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .badge.on { background: #00C7C7; color: #050550; }
  .badge.off { background: rgba(255,255,255,0.55); color: #050550; }

  .instructions-banner {
    display: flex; gap: 10px; align-items: flex-start; background: #f0fdfd; border: 1px solid #b9ecec;
    border-radius: 12px; padding: 12px 16px; margin-bottom: 18px; font-size: 13px; color: #044; line-height: 1.5;
  }
  .instructions-banner .icon { font-size: 18px; line-height: 1.3; }
  .instructions-banner strong { color: #050550; }

  .stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 18px 0; }
  button.stat {
    background: #fff; border: 1px solid #e5e5ea; border-radius: 12px; padding: 14px 10px; text-align: center;
    font: inherit; cursor: pointer; appearance: none; color: inherit; width: 100%;
  }
  button.stat:hover { border-color: #00C7C7; box-shadow: 0 2px 10px rgba(0,199,199,0.15); }
  .stat .icon { font-size: 18px; }
  .stat .num { font-size: 21px; font-weight: 700; color: #006d6d; margin-top: 2px; }
  .stat .label { font-size: 11px; color: #63636c; margin-top: 2px; }
  .stat .hint { font-size: 9.5px; color: #00969b; margin-top: 3px; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; }

  .controls { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; align-items: center; }
  .controls input, .controls select {
    padding: 7px 10px; border: 1px solid #d8d8de; border-radius: 8px; font-size: 13px; background: #fff;
  }
  .controls input[type=text] { flex: 1; min-width: 180px; }
  .result-count { font-size: 12px; color: #63636c; margin: 0 0 10px; }

  .active-filters { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
  .filter-chip {
    display: inline-flex; align-items: center; gap: 6px; background: #050550; color: #fff;
    font-size: 12px; padding: 4px 6px 4px 10px; border-radius: 999px;
  }
  .filter-chip button {
    background: none; border: none; color: #00C7C7; cursor: pointer; font-weight: 700;
    font-size: 14px; line-height: 1; padding: 2px 4px; appearance: none;
  }

  .legend-strip { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; font-size: 12px; color: #444; }
  .legend-strip button.legend-btn {
    display: inline-flex; align-items: center; gap: 6px; background: #fff; border: 1px solid #e5e5ea;
    padding: 4px 10px; border-radius: 999px; cursor: pointer; font: inherit; color: #444; appearance: none;
  }
  .legend-strip button.legend-btn[aria-pressed="true"] { background: #f0fdfd; border-color: #00C7C7; box-shadow: 0 0 0 1px #00C7C7 inset; color: #050550; font-weight: 600; }
  .legend-dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

  .empty-state {
    text-align: center; padding: 40px 20px; color: #63636c; background: #fff;
    border: 1px dashed #d8d8de; border-radius: 12px; margin-bottom: 14px;
  }
  .empty-state .big { font-size: 28px; margin-bottom: 6px; }
  .empty-state button { margin-top: 12px; }

  .quarter-section { margin-bottom: 6px; }
  .quarter-header {
    font-size: 14px; font-weight: 700; color: #050550; margin: 22px 0 10px; padding-bottom: 6px;
    border-bottom: 2px solid #00C7C7; display: flex; align-items: center; gap: 8px;
  }
  .quarter-header .count {
    font-size: 11.5px; font-weight: 600; color: #63636c; background: #f0fdfd; padding: 2px 8px; border-radius: 999px;
  }

  .card {
    background: #fff; border: 1px solid #e5e5ea; border-left: 6px solid #ccc; border-radius: 12px;
    padding: 16px 18px; margin-bottom: 14px; transition: box-shadow .15s ease;
  }
  .card:hover { box-shadow: 0 3px 14px rgba(0,0,0,0.06); }
  .card.highlight { box-shadow: 0 0 0 3px #00C7C7; }
  .card h3 { margin: 0 0 6px; font-size: 16px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .ai-tag { background: #050550; color: #00C7C7; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
  .role-badge {
    display: inline-block; background: #fff; color: #050550; font-size: 11.5px; font-weight: 600;
    padding: 3px 10px; border-radius: 999px; margin: 2px 6px 8px 0; cursor: text; border: 1px dashed #9aa7b8;
  }
  .role-badge:before { content: "✏️ "; font-size: 10px; }
  .role-badge:hover { border-color: #00C7C7; }
  .role-badge:focus { outline: 2px solid #00C7C7; outline-offset: 1px; background: #fff; border-style: solid; }
  .quarter-select {
    display: inline-block; font-size: 11.5px; font-weight: 600; padding: 3px 8px; border-radius: 999px;
    margin: 2px 0 8px; border: 1px dashed #9aa7b8; background: #fff; color: #050550; cursor: pointer; font-family: inherit;
  }
  .quarter-select:hover { border-color: #00C7C7; }
  .quarter-select:focus { outline: 2px solid #00C7C7; outline-offset: 1px; border-style: solid; }
  .field-label { font-size: 10.5px; font-weight: 700; color: #8a8a92; text-transform: uppercase; letter-spacing: .04em; margin: 8px 0 3px; }
  .edit-summary, .edit-impact {
    display: block; width: 100%; font: inherit; color: #333; border: 1px dashed #c7ccd4; background: #fafbfc;
    border-radius: 6px; padding: 7px 9px; margin: 2px 0 8px; resize: none; overflow: hidden;
  }
  .edit-summary:hover, .edit-impact:hover { border-color: #00C7C7; }
  .edit-summary:focus, .edit-impact:focus { border: 1px solid #00C7C7; background: #fff; box-shadow: 0 0 0 3px rgba(0,199,199,0.15); }
  .impact-wrap { background: #f0fdfd; border-left: 3px solid #00C7C7; border-radius: 4px; padding: 2px 4px 6px; margin-bottom: 10px; }
  .impact-wrap .edit-impact { font-size: 13px; color: #444; margin: 4px 4px; background: #fff; }
  .impact-wrap .impact-label { font-size: 11.5px; font-weight: 700; color: #006d6d; margin: 6px 0 0 6px; text-transform: uppercase; letter-spacing: .03em; }

  .mixbar { display: flex; height: 8px; border-radius: 6px; overflow: hidden; margin-bottom: 12px; background: #eee; }
  .mixbar div { height: 100%; }

  .avatars { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
  .avatar-chip {
    display: flex; align-items: center; background: #f4f5f7; border: 1px solid transparent;
    border-radius: 999px; overflow: hidden;
  }
  .avatar-chip.active { border-color: #00C7C7; background: #f0fdfd; }
  .avatar-circle-btn {
    border: none; background: transparent; padding: 3px 3px 3px 3px; cursor: pointer; display: flex;
    align-items: center; appearance: none;
  }
  .avatar-circle {
    width: 24px; height: 24px; border-radius: 50%; color: #fff; font-size: 10.5px; font-weight: 700;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  }
  .avatar-name-btn {
    border: none; background: transparent; padding: 3px 10px 3px 4px; cursor: pointer; font: inherit;
    font-size: 12px; color: #33415c; appearance: none; text-decoration: underline dotted; text-underline-offset: 2px;
  }
  .avatar-name-btn:hover { color: #006d6d; }
  .avatar-name-btn .rel { color: #8a94a6; font-weight: 400; text-decoration: none; }

  details.sources summary { cursor: pointer; font-size: 12.5px; color: #6b6b74; font-weight: 600; list-style: none; }
  details.sources summary::-webkit-details-marker { display: none; }
  details.sources summary:before { content: "▸ "; }
  details.sources[open] summary:before { content: "▾ "; }
  details.sources ul { margin: 8px 0 0; padding-left: 4px; list-style: none; }
  details.sources li { margin-bottom: 6px; font-size: 12.5px; display: flex; align-items: center; gap: 6px; }
  details.sources a { color: #2563eb; text-decoration: none; }
  details.sources a:hover { text-decoration: underline; }
  .src-icon { font-size: 13px; }

  .other-box { background: #fff; border: 1px dashed #d8d8de; border-radius: 12px; padding: 14px 18px; margin-bottom: 14px; color: #555; font-size: 13px; }

  .draft-label { display: inline-block; background: #00C7C7; color: #050550; font-weight: 700; font-size: 11px; padding: 2px 8px; border-radius: 999px; margin-bottom: 10px; }
  .draft-note { font-size: 12px; color: #63636c; margin: 4px 0 16px; }
  .draft-q { font-weight: 600; margin: 14px 0 6px; font-size: 13px; }
  textarea {
    width: 100%; min-height: 220px; padding: 10px; border-radius: 8px; border: 1px solid #d8d8de;
    font-family: inherit; font-size: 13px; resize: vertical; overflow-y: hidden;
  }
  .copy-btn { margin-top: 6px; padding: 6px 12px; border-radius: 7px; border: 1px solid #050550; color: #050550; background: #fff; cursor: pointer; font-size: 12.5px; font-weight: 600; appearance: none; display: inline-block; text-decoration: none; }
  .copy-btn:hover { background: #00C7C7; border-color: #00C7C7; color: #050550; }

  .fab {
    position: fixed; bottom: 22px; right: 22px; z-index: 40;
    padding: 14px 22px; border-radius: 999px; border: none; background: #050550; color: #00C7C7;
    font-weight: 700; font-size: 14px; cursor: pointer; appearance: none;
    box-shadow: 0 6px 20px rgba(5,5,80,0.35); display: flex; align-items: center; gap: 8px;
  }
  .fab:hover { background: #0a2a6e; }

  .modal-overlay {
    position: fixed; inset: 0; background: rgba(5,5,20,0.5); z-index: 50;
    display: flex; align-items: center; justify-content: center; padding: 24px;
  }
  .modal-box {
    background: #fff; border-radius: 16px; padding: 24px; max-width: 640px; width: 100%;
    max-height: 85vh; overflow-y: auto; position: relative; box-shadow: 0 20px 60px rgba(0,0,0,0.3);
  }
  .modal-box h2 { margin-top: 0; font-size: 17px; color: #050550; }
  .modal-close {
    position: absolute; top: 14px; right: 14px; width: 30px; height: 30px; border-radius: 50%;
    border: none; background: #f0fdfd; color: #050550; font-size: 16px; cursor: pointer; appearance: none;
    display: flex; align-items: center; justify-content: center;
  }
  .modal-close:hover { background: #00C7C7; }
  footer { margin-top: 26px; font-size: 12px; color: #7a7a82; border-top: 1px solid #e5e5ea; padding-top: 14px; }
  footer .warn { color: #92400e; margin-top: 6px; }
  .hidden { display: none !important; }

  .directory-list { max-height: 50vh; overflow-y: auto; margin-top: 10px; }
  .directory-row { display: flex; align-items: center; gap: 10px; padding: 10px 4px; border-bottom: 1px solid #eee; }
  .directory-row:last-child { border-bottom: none; }
  .directory-info { flex: 1; min-width: 0; }
  .directory-name { font-weight: 600; font-size: 13.5px; color: #050550; }
  .directory-rel { font-size: 11.5px; color: #8a94a6; font-weight: 400; }
  .directory-projects { font-size: 11.5px; color: #63636c; margin-top: 2px; }
  .directory-actions { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
  .directory-actions button { padding: 5px 10px; font-size: 11.5px; margin-top: 0; white-space: nowrap; }
  .feedback-subject {
    font-weight: 600; font-size: 13.5px; color: #050550; padding: 8px 10px; background: #f0fdfd;
    border-radius: 8px; margin-bottom: 4px;
  }
  .feedback-actions { display: flex; gap: 8px; flex-wrap: wrap; }

  @media (max-width: 760px) { .stats { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 480px) { .stats { grid-template-columns: repeat(2, 1fr); } body { padding: 14px; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1 id="heroTitle">Mid-Year Project Dashboard</h1>
    <div class="meta" id="heroMeta"></div>
    <div class="badges" id="sourceBadges"></div>
  </div>

  <div class="instructions-banner">
    <span class="icon">📝</span>
    <div><strong>How to use this dashboard:</strong> Projects below are grouped by quarter — click any stat card up top to explore (view all, expand sources, browse stakeholders, filter to AI work). Click a stakeholder's <strong>name</strong> to request feedback from them, or their avatar to see everything you worked on together. Edit any role, quarter, summary, or impact text directly on the card — your edits are saved in this browser. Click <strong>"View Self-Assessment Draft"</strong> to see the starting draft Claude Code wrote for you; to regenerate it after editing fields, paste your changes back to Claude Code and ask it to rebuild this file.</div>
  </div>

  <div class="stats" id="statBar"></div>

  <div class="controls">
    <input type="text" id="searchBox" aria-label="Search projects, sources, or people" placeholder="Search projects, sources, people…">
    <select id="quarterFilter" aria-label="Filter by quarter">
      <option value="all">All quarters</option>
    </select>
    <select id="aiFilter" aria-label="Filter by AI involvement">
      <option value="all">All projects</option>
      <option value="ai">AI-involved only</option>
    </select>
  </div>

  <div class="active-filters" id="activeFilters"></div>
  <div class="result-count" id="resultCount" aria-live="polite"></div>

  <div class="legend-strip" id="legendStrip"></div>

  <div id="emptyState" class="empty-state hidden"></div>

  <div id="projectList"></div>

  <div class="other-box" id="otherBox"></div>

  <footer>
    <div id="footerDeadline"></div>
    <div class="warn">Before pasting any of this into an external AI tool, remove confidential Rubrik data or customer PII per Rubrik's AI policy.</div>
  </footer>
</div>

<button class="fab" id="generateBtn" type="button">📄 View Self-Assessment Draft</button>

<div class="modal-overlay hidden" id="assessmentModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
  <div class="modal-box">
    <button class="modal-close" type="button" aria-label="Close">×</button>
    <h2 id="modalTitle">Self-Assessment Draft</h2>
    <span class="draft-label">Draft — review and edit before using in Workday</span>
    <div class="draft-note">Generated by Claude Code from your project data when this file was built. Edits here are saved in this browser only — to regenerate from scratch, ask Claude Code to rebuild this file.</div>

    <div class="draft-q" id="q1Label"></div>
    <textarea id="q1" aria-label="Draft answer to question 1"></textarea>
    <button class="copy-btn" data-target="q1" type="button">Copy answer</button>

    <div class="draft-q" id="q2Label"></div>
    <textarea id="q2" aria-label="Draft answer to question 2"></textarea>
    <button class="copy-btn" data-target="q2" type="button">Copy answer</button>
  </div>
</div>

<div class="modal-overlay hidden" id="stakeholderModal" role="dialog" aria-modal="true" aria-labelledby="stakeholderModalTitle">
  <div class="modal-box">
    <button class="modal-close" type="button" aria-label="Close">×</button>
    <h2 id="stakeholderModalTitle">Stakeholder Directory</h2>
    <span class="draft-label" style="background:#f0fdfd;color:#006d6d;">Everyone you worked with this half</span>
    <div class="directory-list" id="directoryList"></div>
  </div>
</div>

<div class="modal-overlay hidden" id="feedbackModal" role="dialog" aria-modal="true" aria-labelledby="feedbackModalTitle">
  <div class="modal-box">
    <button class="modal-close" type="button" aria-label="Close">×</button>
    <h2 id="feedbackModalTitle">Request Feedback</h2>
    <span class="draft-label">Editable template — personalize before sending</span>

    <div class="field-label">Subject</div>
    <div class="feedback-subject" id="feedbackSubject"></div>

    <div class="field-label">Message</div>
    <textarea id="feedbackBody" aria-label="Feedback request message"></textarea>

    <div class="feedback-actions">
      <button class="copy-btn" id="feedbackCopyBtn" type="button">Copy message</button>
      <a class="copy-btn" id="feedbackMailtoBtn" href="#" target="_blank" rel="noopener">Open in email</a>
    </div>
  </div>
</div>

<script>
const SRC_ICON = { Slack: "💬", Drive: "📄", Gmail: "✉️", Calendar: "📅", Jira: "🎫", Confluence: "📘", Zoom: "🎥" };
const TYPE_COLORS = { Slack: "#050550", Drive: "#00C7C7", Gmail: "#16217a", Calendar: "#006d6d", Jira: "#0b1f66", Confluence: "#049a9a", Zoom: "#0e7490" };

const QUARTERS = [
  { id: 'q1', label: 'Q1 · Feb – Apr 2026', shortLabel: 'Q1 (Feb–Apr)' },
  { id: 'q2', label: 'Q2 · May – Jul 2026', shortLabel: 'Q2 (May–Jul)' },
  { id: 'both', label: 'Spanned Both Quarters (Feb – Jul 2026)', shortLabel: 'Both quarters' }
];

const CYCLE = {
  employeeName: "Employee Name",
  cycleName: "Mid-Year OPE FY27",
  windowLabel: "Feb 1 – Jul 31, 2026",
  generatedDate: "Generated date",
  assessmentWindow: "Aug 17 – Sep 3, 2026",
  assessmentDue: "Sep 3, 2026, 11:59pm PT",
  q1: "Based on goals for the past quarter/half year, describe top achievements, their impact, and how AI was used to influence outcomes.",
  q2: "What are the most important areas of focus for success in the quarter/half year ahead — in performance, development, and ways of working?"
};

// Written by Claude Code during Step 6 of the skill run — the starting draft,
// grounded only in the DATA.projects content below. Fully editable in-browser.
const INITIAL_DRAFT = {
  q1: "[Claude Code fills this in from the real project data during the skill run.]",
  q2: "[Claude Code fills this in from the real project data during the skill run.]"
};

// EXAMPLE DATA — replace with this employee's real synthesized output from Steps 1-6.
const DATA = {
  sources: [
    { name: "Jira", connected: false, note: "not connected" },
    { name: "Confluence", connected: false, note: "not connected" },
    { name: "Slack", connected: true },
    { name: "Google Drive", connected: true },
    { name: "Gmail", connected: true },
    { name: "Google Calendar", connected: true }
  ],
  projects: [
    {
      name: "Example Project Name",
      color: "#050550",
      quarter: "q1",
      role: "The employee's own role/contribution type, e.g. Program Lead, Contributor, Reviewer",
      summary: "1-2 sentence summary of what this was and the employee's role.",
      impact: "Concrete, evidenced impact/outcome notes — no invented metrics.",
      ai: true,
      stakeholders: [
        { name: "Person One", rel: "manager" },
        { name: "Person Two", rel: "frequent collaborator" }
      ],
      sources: [
        { type: "Slack", label: "Descriptive label for the item", url: "https://..." },
        { type: "Drive", label: "Doc/sheet/deck title", url: "https://..." },
        { type: "Calendar", label: "Recurring meeting name", url: "" }
      ]
    }
  ],
  other: "Short note on smaller/ERG/culture contributions that don't merit a full project card."
};

let activeStakeholder = null;
let activeProject = null;
let lastFocusedBeforeModal = null;
let currentModalId = null;

function initials(name) { return name.split(/\s+/).map(w => w[0]).join('').slice(0,2).toUpperCase(); }
function nameColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  const hue = 175 + (Math.abs(hash) % 90);
  return `hsl(${hue}, 60%, 32%)`;
}

function renderCycleText() {
  document.title = `${CYCLE.employeeName} — ${CYCLE.cycleName} Dashboard`;
  document.getElementById('heroTitle').textContent = `${CYCLE.cycleName} Project Dashboard — ${CYCLE.employeeName}`;
  document.getElementById('heroMeta').textContent = `Window: ${CYCLE.windowLabel} · Generated ${CYCLE.generatedDate}`;
  document.getElementById('q1Label').textContent = `Q1. ${CYCLE.q1}`;
  document.getElementById('q2Label').textContent = `Q2. ${CYCLE.q2}`;
  document.getElementById('footerDeadline').textContent =
    `Self-Assessment window: ${CYCLE.assessmentWindow} (Workday deadline ${CYCLE.assessmentDue}).`;
}

function renderBadges() {
  const el = document.getElementById('sourceBadges');
  el.innerHTML = DATA.sources.map(s =>
    `<span class="badge ${s.connected ? 'on' : 'off'}">${s.name}${s.connected ? '' : ' · ' + s.note}</span>`
  ).join('');
}

function normalizeQuarters() {
  const validIds = QUARTERS.map(q => q.id);
  DATA.projects.forEach(p => { if (!validIds.includes(p.quarter)) p.quarter = validIds[0]; });
}

function computeByType() {
  const byType = {};
  DATA.projects.forEach(p => p.sources.forEach(s => byType[s.type] = (byType[s.type]||0)+1));
  return byType;
}

function renderStats(byType) {
  const el = document.getElementById('statBar');
  const total = DATA.projects.length;
  const aiCount = DATA.projects.filter(p => p.ai).length;
  const srcCount = Object.values(byType).reduce((a,b)=>a+b,0);
  const peopleSet = new Set();
  DATA.projects.forEach(p => p.stakeholders.forEach(s => peopleSet.add(s.name)));
  const topType = Object.entries(byType).sort((a,b)=>b[1]-a[1])[0];
  el.innerHTML = `
    <button type="button" class="stat" id="statProjectsBtn">
      <div class="icon">🗂️</div><div class="num">${total}</div><div class="label">Projects</div><div class="hint">View all</div>
    </button>
    <button type="button" class="stat" id="statSourcesBtn">
      <div class="icon">🔗</div><div class="num">${srcCount}</div><div class="label">Source items linked</div><div class="hint">Expand all</div>
    </button>
    <button type="button" class="stat" id="statStakeholdersBtn">
      <div class="icon">🧑‍🤝‍🧑</div><div class="num">${peopleSet.size}</div><div class="label">Stakeholders</div><div class="hint">Directory</div>
    </button>
    <button type="button" class="stat" id="statAiBtn">
      <div class="icon">🤖</div><div class="num">${aiCount}</div><div class="label">Projects w/ AI use</div><div class="hint">Filter</div>
    </button>
    <button type="button" class="stat" id="statTopTypeBtn" data-type="${topType ? topType[0] : ''}">
      <div class="icon">${topType ? (SRC_ICON[topType[0]] || '📌') : '📌'}</div><div class="num">${topType ? topType[0] : '—'}</div><div class="label">Top source type</div><div class="hint">Filter</div>
    </button>
  `;
}

function bindStatClicks() {
  const pBtn = document.getElementById('statProjectsBtn');
  if (pBtn) pBtn.addEventListener('click', () => {
    clearAllFilters();
    document.getElementById('projectList').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  const sBtn = document.getElementById('statSourcesBtn');
  if (sBtn) sBtn.addEventListener('click', () => {
    const detailsEls = document.querySelectorAll('#projectList details.sources');
    const anyClosed = Array.from(detailsEls).some(d => !d.open);
    detailsEls.forEach(d => { d.open = anyClosed; });
  });
  const stBtn = document.getElementById('statStakeholdersBtn');
  if (stBtn) stBtn.addEventListener('click', openStakeholderDirectory);
  const aiBtn = document.getElementById('statAiBtn');
  if (aiBtn) aiBtn.addEventListener('click', () => {
    document.getElementById('aiFilter').value = 'ai';
    applyFilters();
    document.getElementById('projectList').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  const topBtn = document.getElementById('statTopTypeBtn');
  if (topBtn) topBtn.addEventListener('click', () => {
    const type = topBtn.dataset.type;
    if (!type) return;
    document.getElementById('searchBox').value = type.toLowerCase();
    applyFilters();
    document.getElementById('projectList').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

function renderLegend() {
  const el = document.getElementById('legendStrip');
  el.innerHTML = DATA.projects.map((p, i) =>
    `<button type="button" class="legend-btn" data-project-index="${i}" aria-pressed="${activeProject===p.name}">
       <span class="legend-dot" style="background:${p.color}"></span>${p.name.split('(')[0].trim()}
     </button>`
  ).join('');
}

function mixBar(p) {
  const counts = {};
  p.sources.forEach(s => counts[s.type] = (counts[s.type]||0) + 1);
  const total = p.sources.length;
  const segs = Object.entries(counts).map(([t,c]) =>
    `<div style="width:${(c/total*100).toFixed(1)}%; background:${TYPE_COLORS[t]||'#999'}" title="${t}: ${c}"></div>`
  ).join('');
  return `<div class="mixbar">${segs}</div>`;
}

function avatarItem(s) {
  const bg = nameColor(s.name);
  const safe = s.name.replace(/"/g,'');
  const pressed = activeStakeholder === s.name;
  return `<span class="avatar-chip${pressed ? ' active' : ''}" data-stakeholder="${safe}">
    <button type="button" class="avatar-circle-btn" data-stakeholder="${safe}" aria-label="Filter projects with ${safe}" aria-pressed="${pressed}">
      <span class="avatar-circle" style="background:${bg}">${initials(s.name)}</span>
    </button>
    <button type="button" class="avatar-name-btn" data-stakeholder="${safe}" aria-label="Request feedback from ${safe}">
      ${s.name}${s.rel ? ` <span class="rel">· ${s.rel}</span>` : ''}
    </button>
  </span>`;
}

function sourceItem(s) {
  const icon = SRC_ICON[s.type] || '🔹';
  const label = s.url ? `<a href="${s.url}" target="_blank" rel="noopener">${s.label}</a>` : s.label;
  return `<li><span class="src-icon">${icon}</span>${label}</li>`;
}

function computeBlob(p) {
  return (p.name+' '+p.role+' '+p.summary+' '+p.impact+' '+p.stakeholders.map(s=>s.name).join(' ')+' '+p.sources.map(s=>s.label).join(' ')+' '+p.sources.map(s=>s.type).join(' ')).toLowerCase().replace(/"/g,'');
}

function projectCard(p, i) {
  return `
    <div class="card" style="border-left-color:${p.color}" data-index="${i}" data-name="${p.name.toLowerCase()}" data-ai="${p.ai}" data-quarter="${p.quarter}" data-people="${p.stakeholders.map(s=>s.name).join('|')}" data-blob="${computeBlob(p)}">
      <h3><span style="color:${p.color}">●</span> ${p.name} ${p.ai ? '<span class="ai-tag">🤖 AI involved</span>' : ''}</h3>
      <span class="role-badge" contenteditable="true" data-index="${i}" aria-label="Your role in this project">${p.role || 'Add your role…'}</span>
      <select class="quarter-select" data-index="${i}" aria-label="Which quarter this project happened in">
        ${QUARTERS.map(q => `<option value="${q.id}" ${p.quarter===q.id?'selected':''}>${q.shortLabel}</option>`).join('')}
      </select>
      <textarea class="edit-summary" data-index="${i}" data-field="summary" aria-label="Project summary (editable)">${p.summary}</textarea>
      <div class="impact-wrap">
        <div class="impact-label">Impact</div>
        <textarea class="edit-impact" data-index="${i}" data-field="impact" aria-label="Project impact (editable)">${p.impact}</textarea>
      </div>
      ${mixBar(p)}
      <div class="avatars">${p.stakeholders.map(avatarItem).join('')}</div>
      <details class="sources">
        <summary>${p.sources.length} linked source item${p.sources.length===1?'':'s'}</summary>
        <ul>${p.sources.map(sourceItem).join('')}</ul>
      </details>
    </div>
  `;
}

function renderProjects() {
  const container = document.getElementById('projectList');
  let html = '';
  QUARTERS.forEach(q => {
    const inQuarter = DATA.projects.map((p, i) => ({ p, i })).filter(({ p }) => p.quarter === q.id);
    if (inQuarter.length === 0) return;
    html += `<div class="quarter-section" data-quarter="${q.id}">
      <div class="quarter-header">${q.label} <span class="count">${inQuarter.length} project${inQuarter.length===1?'':'s'}</span></div>
      ${inQuarter.map(({ p, i }) => projectCard(p, i)).join('')}
    </div>`;
  });
  container.innerHTML = html;
  document.getElementById('otherBox').innerHTML = DATA.other ? `<strong>Other / smaller contributions:</strong> ${DATA.other}` : '';
  document.querySelectorAll('#projectList .edit-summary, #projectList .edit-impact').forEach(autoGrow);
}

function restoreProjectEdits() {
  DATA.projects.forEach((p, i) => {
    try {
      const savedSummary = localStorage.getItem(`mypd_p${i}_summary`);
      const savedImpact = localStorage.getItem(`mypd_p${i}_impact`);
      const savedRole = localStorage.getItem(`mypd_p${i}_role`);
      const savedQuarter = localStorage.getItem(`mypd_p${i}_quarter`);
      if (savedSummary !== null) p.summary = savedSummary;
      if (savedImpact !== null) p.impact = savedImpact;
      if (savedRole !== null) p.role = savedRole;
      if (savedQuarter && QUARTERS.some(q => q.id === savedQuarter)) p.quarter = savedQuarter;
    } catch (e) { /* storage unavailable, keep defaults */ }
  });
}

function renderActiveFilters() {
  const el = document.getElementById('activeFilters');
  const chips = [];
  if (activeProject) chips.push(`<span class="filter-chip">Project: ${activeProject} <button type="button" data-clear="project" aria-label="Clear project filter">×</button></span>`);
  if (activeStakeholder) chips.push(`<span class="filter-chip">With: ${activeStakeholder} <button type="button" data-clear="stakeholder" aria-label="Clear stakeholder filter">×</button></span>`);
  el.innerHTML = chips.join('');
}

function applyFilters() {
  const q = document.getElementById('searchBox').value.toLowerCase().trim();
  const aiOnly = document.getElementById('aiFilter').value === 'ai';
  const quarterVal = document.getElementById('quarterFilter').value;
  const cards = Array.from(document.querySelectorAll('#projectList .card'));
  let visibleCount = 0;

  cards.forEach(card => {
    const matchesText = !q || card.dataset.blob.includes(q);
    const matchesAi = !aiOnly || card.dataset.ai === 'true';
    const matchesProject = !activeProject || card.dataset.name === activeProject.toLowerCase();
    const matchesStakeholder = !activeStakeholder || card.dataset.people.split('|').includes(activeStakeholder);
    const matchesQuarter = quarterVal === 'all' || card.dataset.quarter === quarterVal;
    const visible = matchesText && matchesAi && matchesProject && matchesStakeholder && matchesQuarter;
    card.classList.toggle('hidden', !visible);
    if (visible) visibleCount++;
  });

  document.querySelectorAll('#projectList .quarter-section').forEach(section => {
    const hasVisible = !!section.querySelector('.card:not(.hidden)');
    section.classList.toggle('hidden', !hasVisible);
  });

  renderActiveFilters();

  const emptyEl = document.getElementById('emptyState');
  const totalProjects = DATA.projects.length;
  if (totalProjects === 0) {
    emptyEl.innerHTML = `<div class="big">🗒️</div><div>No activity found for this window.</div>
      <div style="font-size:12.5px;margin-top:4px;">Check that your MCP connectors are set up, then re-run the skill.</div>`;
    emptyEl.classList.remove('hidden');
  } else if (visibleCount === 0) {
    emptyEl.innerHTML = `<div class="big">🔍</div><div>No projects match your current filters.</div>
      <button type="button" class="copy-btn" id="clearAllBtn">Clear filters</button>`;
    emptyEl.classList.remove('hidden');
  } else {
    emptyEl.classList.add('hidden');
  }

  document.getElementById('resultCount').textContent =
    totalProjects === 0 ? '' : `Showing ${visibleCount} of ${totalProjects} project${totalProjects===1?'':'s'}`;

  try {
    localStorage.setItem('mypd_search', q);
    localStorage.setItem('mypd_aiFilter', document.getElementById('aiFilter').value);
    localStorage.setItem('mypd_quarterFilter', quarterVal);
  } catch (e) { /* storage unavailable, ignore */ }

  const clearBtn = document.getElementById('clearAllBtn');
  if (clearBtn) clearBtn.addEventListener('click', clearAllFilters);
}

function clearAllFilters() {
  document.getElementById('searchBox').value = '';
  document.getElementById('aiFilter').value = 'all';
  document.getElementById('quarterFilter').value = 'all';
  activeProject = null;
  activeStakeholder = null;
  renderLegend();
  bindLegendClicks();
  applyFilters();
}

function autoGrow(el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }

function populateQuarterFilter() {
  const sel = document.getElementById('quarterFilter');
  QUARTERS.forEach(q => {
    const opt = document.createElement('option');
    opt.value = q.id;
    opt.textContent = q.label;
    sel.appendChild(opt);
  });
}

function restorePrefs() {
  let q = null, ai = null, quarterSaved = null, q1saved = null, q2saved = null;
  try {
    q = localStorage.getItem('mypd_search');
    ai = localStorage.getItem('mypd_aiFilter');
    quarterSaved = localStorage.getItem('mypd_quarterFilter');
    q1saved = localStorage.getItem('mypd_q1');
    q2saved = localStorage.getItem('mypd_q2');
  } catch (e) { /* storage unavailable, fall back to defaults */ }
  if (q) document.getElementById('searchBox').value = q;
  if (ai) document.getElementById('aiFilter').value = ai;
  if (quarterSaved) document.getElementById('quarterFilter').value = quarterSaved;
  const q1 = document.getElementById('q1');
  const q2 = document.getElementById('q2');
  q1.value = q1saved !== null ? q1saved : INITIAL_DRAFT.q1;
  q2.value = q2saved !== null ? q2saved : INITIAL_DRAFT.q2;
  autoGrow(q1);
  autoGrow(q2);
}

function bindLegendClicks() {
  document.getElementById('legendStrip').querySelectorAll('.legend-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.projectIndex);
      const proj = DATA.projects[idx];
      activeProject = activeProject === proj.name ? null : proj.name;
      renderLegend();
      bindLegendClicks();
      applyFilters();
      if (activeProject) {
        const card = document.querySelector(`#projectList .card[data-name="${proj.name.toLowerCase()}"]`);
        if (card) {
          card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          card.classList.add('highlight');
          setTimeout(() => card.classList.remove('highlight'), 1500);
        }
      }
    });
  });
}

function openModal(id) {
  currentModalId = id;
  const modal = document.getElementById(id);
  lastFocusedBeforeModal = document.activeElement;
  modal.classList.remove('hidden');
  const closeBtn = modal.querySelector('.modal-close');
  if (closeBtn) closeBtn.focus();
}

function closeModal(id) {
  const targetId = id || currentModalId;
  if (!targetId) return;
  const modal = document.getElementById(targetId);
  if (modal) modal.classList.add('hidden');
  if (lastFocusedBeforeModal && typeof lastFocusedBeforeModal.focus === 'function') lastFocusedBeforeModal.focus();
  currentModalId = null;
}

function initModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  const closeBtn = modal.querySelector('.modal-close');
  if (closeBtn) closeBtn.addEventListener('click', () => closeModal(id));
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(id); });
}

function buildStakeholderDirectory() {
  const map = new Map();
  DATA.projects.forEach(p => {
    p.stakeholders.forEach(s => {
      if (!map.has(s.name)) map.set(s.name, { name: s.name, rel: s.rel || '', projects: [] });
      const entry = map.get(s.name);
      if (!entry.rel && s.rel) entry.rel = s.rel;
      if (!entry.projects.includes(p.name)) entry.projects.push(p.name);
    });
  });
  return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
}

function openStakeholderDirectory() {
  const list = buildStakeholderDirectory();
  const container = document.getElementById('directoryList');
  if (list.length === 0) {
    container.innerHTML = `<div class="directory-row">No stakeholders found yet.</div>`;
  } else {
    container.innerHTML = list.map(s => `
      <div class="directory-row">
        <span class="avatar-circle" style="background:${nameColor(s.name)}">${initials(s.name)}</span>
        <div class="directory-info">
          <div class="directory-name">${s.name}${s.rel ? ` <span class="directory-rel">· ${s.rel}</span>` : ''}</div>
          <div class="directory-projects">${s.projects.join(', ')}</div>
        </div>
        <div class="directory-actions">
          <button type="button" class="copy-btn" data-directory-filter="${s.name.replace(/"/g,'')}">View projects</button>
          <button type="button" class="copy-btn" data-directory-feedback="${s.name.replace(/"/g,'')}">Request feedback</button>
        </div>
      </div>
    `).join('');
  }
  openModal('stakeholderModal');
}

function stakeholderProjects(name) {
  return DATA.projects.filter(p => p.stakeholders.some(s => s.name === name)).map(p => p.name);
}

function buildFeedbackTemplate(name) {
  const projects = stakeholderProjects(name);
  const firstName = name.split(' ')[0];
  let projectList;
  if (projects.length === 0) projectList = 'a few things this half';
  else if (projects.length === 1) projectList = projects[0];
  else projectList = projects.slice(0, -1).join(', ') + ' and ' + projects[projects.length - 1];

  const subject = `Feedback request for my ${CYCLE.cycleName}`;
  const body = `Hi ${firstName},\n\nI'm working on my ${CYCLE.cycleName} self-assessment (due ${CYCLE.assessmentDue}), and since we worked together on ${projectList}, I'd really appreciate any feedback you're willing to share.\n\nIf you're open to giving me feedback to help me learn and grow, please let me know so I can send you a request in the Workday Feedback Tool. My manager will then be able to include it in my mid-year check-in.\n\nBest,\n${CYCLE.employeeName}`;
  return { subject, body };
}

function openFeedbackModal(name) {
  const { subject, body } = buildFeedbackTemplate(name);
  document.getElementById('feedbackModalTitle').textContent = `Request Feedback — ${name}`;
  document.getElementById('feedbackSubject').textContent = subject;
  const bodyEl = document.getElementById('feedbackBody');
  bodyEl.value = body;
  document.getElementById('feedbackMailtoBtn').href = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  openModal('feedbackModal');
  autoGrow(bodyEl);
}

document.getElementById('searchBox').addEventListener('input', applyFilters);
document.getElementById('aiFilter').addEventListener('change', applyFilters);
document.getElementById('quarterFilter').addEventListener('change', applyFilters);
document.getElementById('q1').addEventListener('input', e => {
  autoGrow(e.target);
  try { localStorage.setItem('mypd_q1', e.target.value); } catch (err) {}
});
document.getElementById('q2').addEventListener('input', e => {
  autoGrow(e.target);
  try { localStorage.setItem('mypd_q2', e.target.value); } catch (err) {}
});
document.querySelectorAll('.copy-btn[data-target]').forEach(btn => {
  btn.addEventListener('click', () => {
    const ta = document.getElementById(btn.dataset.target);
    navigator.clipboard.writeText(ta.value).then(() => {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = orig, 1200);
    }).catch(() => {
      ta.select();
      btn.textContent = 'Select the text above and press Ctrl/Cmd+C';
      setTimeout(() => btn.textContent = 'Copy answer', 2200);
    });
  });
});
document.getElementById('feedbackCopyBtn').addEventListener('click', () => {
  const subject = document.getElementById('feedbackSubject').textContent;
  const body = document.getElementById('feedbackBody').value;
  const combined = `Subject: ${subject}\n\n${body}`;
  const btn = document.getElementById('feedbackCopyBtn');
  navigator.clipboard.writeText(combined).then(() => {
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = orig, 1200);
  }).catch(() => {
    document.getElementById('feedbackBody').select();
    btn.textContent = 'Select the text above and press Ctrl/Cmd+C';
    setTimeout(() => btn.textContent = 'Copy message', 2200);
  });
});
document.getElementById('projectList').addEventListener('click', e => {
  const nameBtn = e.target.closest('.avatar-name-btn');
  if (nameBtn) { openFeedbackModal(nameBtn.dataset.stakeholder); return; }
  const circleBtn = e.target.closest('.avatar-circle-btn');
  if (circleBtn) {
    const name = circleBtn.dataset.stakeholder;
    activeStakeholder = activeStakeholder === name ? null : name;
    document.querySelectorAll('#projectList .avatar-chip').forEach(chip => {
      chip.classList.toggle('active', chip.dataset.stakeholder === activeStakeholder);
    });
    document.querySelectorAll('#projectList .avatar-circle-btn').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.stakeholder === activeStakeholder));
    });
    applyFilters();
  }
});
document.getElementById('projectList').addEventListener('input', e => {
  const el = e.target;
  const idx = Number(el.dataset.index);
  if (Number.isNaN(idx)) return;
  const proj = DATA.projects[idx];
  if (!proj) return;
  if (el.classList.contains('edit-summary')) {
    proj.summary = el.value;
    autoGrow(el);
    try { localStorage.setItem(`mypd_p${idx}_summary`, el.value); } catch (err) {}
  } else if (el.classList.contains('edit-impact')) {
    proj.impact = el.value;
    autoGrow(el);
    try { localStorage.setItem(`mypd_p${idx}_impact`, el.value); } catch (err) {}
  } else if (el.classList.contains('role-badge')) {
    proj.role = el.textContent.trim();
    try { localStorage.setItem(`mypd_p${idx}_role`, proj.role); } catch (err) {}
  } else {
    return;
  }
  const card = el.closest('.card');
  if (card) card.dataset.blob = computeBlob(proj);
});
document.getElementById('projectList').addEventListener('change', e => {
  const sel = e.target.closest('.quarter-select');
  if (!sel) return;
  const idx = Number(sel.dataset.index);
  if (Number.isNaN(idx)) return;
  const proj = DATA.projects[idx];
  if (!proj) return;
  proj.quarter = sel.value;
  try { localStorage.setItem(`mypd_p${idx}_quarter`, proj.quarter); } catch (err) {}
  renderProjects();
  applyFilters();
});
document.getElementById('directoryList').addEventListener('click', e => {
  const filterBtn = e.target.closest('[data-directory-filter]');
  const feedbackBtn = e.target.closest('[data-directory-feedback]');
  if (filterBtn) {
    const name = filterBtn.dataset.directoryFilter;
    activeStakeholder = activeStakeholder === name ? null : name;
    closeModal('stakeholderModal');
    document.querySelectorAll('#projectList .avatar-chip').forEach(chip => {
      chip.classList.toggle('active', chip.dataset.stakeholder === activeStakeholder);
    });
    document.querySelectorAll('#projectList .avatar-circle-btn').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.stakeholder === activeStakeholder));
    });
    applyFilters();
    document.getElementById('projectList').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (feedbackBtn) {
    closeModal('stakeholderModal');
    openFeedbackModal(feedbackBtn.dataset.directoryFeedback);
  }
});
document.getElementById('generateBtn').addEventListener('click', () => openModal('assessmentModal'));
document.getElementById('activeFilters').addEventListener('click', e => {
  const btn = e.target.closest('button[data-clear]');
  if (!btn) return;
  if (btn.dataset.clear === 'project') activeProject = null;
  if (btn.dataset.clear === 'stakeholder') activeStakeholder = null;
  renderLegend();
  bindLegendClicks();
  document.querySelectorAll('#projectList .avatar-chip').forEach(chip => {
    chip.classList.toggle('active', chip.dataset.stakeholder === activeStakeholder);
  });
  document.querySelectorAll('#projectList .avatar-circle-btn').forEach(b => {
    b.setAttribute('aria-pressed', String(b.dataset.stakeholder === activeStakeholder));
  });
  applyFilters();
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  ['assessmentModal', 'stakeholderModal', 'feedbackModal'].forEach(id => {
    const m = document.getElementById(id);
    if (m && !m.classList.contains('hidden')) closeModal(id);
  });
});

populateQuarterFilter();
renderCycleText();
normalizeQuarters();
restoreProjectEdits();
const byType = computeByType();
renderBadges();
renderStats(byType);
bindStatClicks();
renderLegend();
bindLegendClicks();
renderProjects();
initModal('assessmentModal');
initModal('stakeholderModal');
initModal('feedbackModal');
restorePrefs();
applyFilters();
</script>
</body>
</html>
```

### 8. Hand it off

Tell the person where the file was saved and how to open it (double-click it, or `open <path>` on macOS / `start <path>` on Windows — any modern browser works, no server needed). Also read the two drafted self-assessment answers back to them directly in the terminal, since the "regenerate" loop for this static file runs through you, not a button in the browser. Mention which connectors weren't available, and flag that quarter assignments are a first-pass estimate they can adjust via the dropdown on each card.

## Rules

- Only ever surface the signed-in employee's own activity and the people they worked with on it — never pull or display another employee's private data, feedback, or ratings.
- Never write to Workday, never auto-submit the self-assessment, never send any feedback request or email on the employee's behalf — the "Request Feedback" template is for the employee to review, personalize, and send themselves.
- Never post anything to Slack/Jira/Confluence/Zoom as part of this skill.
- Always label the self-assessment text clearly as a draft the employee must review before submitting.
- Don't invent metrics, outcomes, stakeholder relationships, or employee roles not evidenced by the actual data pulled. Quarter assignment is the one exception where a best-effort guess is acceptable, since it's clearly editable and doesn't misrepresent facts about the work itself.
- If an MCP connector isn't set up, skip it and say so in the dashboard's source badges — don't block the whole run.
- Always use Rubrik's brand colors (`#050550` navy, `#00C7C7` teal, and the derived shades above) — don't fall back to generic/default colors.
- Keep the template's structure intact: the instructions banner, editable role/quarter/summary/impact fields, the floating button + modal, the five clickable stat cards, quarter-grouped sections (Q1 / Q2 / Both quarters), the Stakeholder Directory modal, the Feedback Request modal and its consent-based template, click-to-filter legend and avatars, the empty-state handling, and the try/catch storage guards. Do not reintroduce charts, and do not try to wire the "View Self-Assessment Draft" button back up to a live model call — a static HTML file has no such connection; the draft is baked in at build time by you.
- This skill is scoped to Mid-Year OPE only — do not extend it to Annual OPE or other cycles without an explicit request.
- If asked to run this for someone other than the signed-in employee, decline and explain this skill is scoped to self-use only.
