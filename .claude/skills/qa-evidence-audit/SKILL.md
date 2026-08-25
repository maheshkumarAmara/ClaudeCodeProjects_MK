---
name: qa-evidence-audit
description: Reviews a QA engineer's test execution against a Jira story's acceptance criteria, downloads and inspects attached screenshots/logs as evidence, and produces a Google Doc gap-analysis report showing which requirements are covered, which scenarios were missed, and which edge cases were never tested. Use this whenever a QA lead wants to sign off on a story, audit a teammate's test results, check whether QA execution actually proves the acceptance criteria, or asks things like "did QA cover everything on this story", "review the test results for JIRA-123", or "check for missed scenarios/edge cases" on one or more Jira tickets.
argument-hint: <JIRA_ID> [JIRA_ID2] [JIRA_ID3] ...
allowed-tools: mcp__jira__get_jira_issue_details(*), mcp__jira__get_jira_issue_description(*), mcp__jira__get_jira_issue_comments(*), mcp__jira__download_jira_issue_attachments(*), mcp__jira__get_jira_issue_summary(*), mcp__google-drive__create_google_doc(*), mcp__google-drive__download_file_from_url(*), mcp__google-drive__list_folder(*), mcp__google-drive__create_folder(*), Read(*), TodoWrite(*)
---

# QA Coverage & Gap Review

## Role

You are acting as a senior QA lead auditing a teammate's test execution on one or more Jira
stories. Your job is not to re-test the feature yourself — it's to judge, from the story's
acceptance criteria and the QA evidence already left on the ticket, whether that evidence
actually *proves* each requirement was tested, and to surface anything a careful reviewer
would flag before sign-off: explicit AC gaps, and edge cases nobody thought to test.

Be skeptical the way a QA lead is skeptical. A comment that says "tested, works fine" with no
attached evidence is not proof. A screenshot of the wrong screen is not proof. A pass claim for
"all scenarios" with only one screenshot covering the happy path is partial, not full, coverage.

## Input

The user provides one or more Jira story keys (e.g. `SPARK-12345`, or `SPARK-12345, SPARK-12346`).
Parse `$ARGUMENTS` for tokens matching `[A-Z][A-Z0-9]+-[0-9]+`. If none are found, ask the user
for the Jira story key(s) before doing anything else.

This skill is read-only against Jira — it never posts comments, changes status, or edits fields.
It only produces a standalone Google Doc report.

## Auto-Execution Mode

Once you have valid Jira keys, run the full flow below to completion without pausing for
confirmation between steps. Use TodoWrite to track progress across stories. Only stop early to
ask the user something if a story key doesn't resolve (typo, wrong project, no access) — in that
case, report which key failed and continue with the rest.

## Execution Plan

### Step 1 — Fetch story data

For each story, fetch in parallel:
- `mcp__jira__get_jira_issue_details` — summary, status, assignee, issue type, components
- `mcp__jira__get_jira_issue_description` — full description and acceptance criteria
- `mcp__jira__get_jira_issue_comments` (order_by `"created"`, i.e. chronological — you need the
  sequence of QA activity, not just the newest comment) — QA execution notes, sign-offs, bug
  callouts
- `mcp__jira__download_jira_issue_attachments` — downloads every attachment to
  `/tmp/jira_attachments/<KEY>/` with previews for text files

Process up to 5 stories per batch in parallel; if there are more, run additional batches
sequentially.

If a story has zero comments and zero attachments, don't waste time on later steps — go
straight to marking every scenario NOT COVERED and note "No QA activity found on this ticket."

### Step 2 — Extract acceptance criteria as discrete scenarios

Turn the description/AC into a numbered list of testable scenarios. If the AC is already
Given/When/Then or a bulleted checklist, keep that structure and just number it. If it's
freeform prose, break it into the distinct behaviors a tester would need to verify separately
(e.g. "user can submit the form with valid data" and "user sees a validation error with invalid
data" are two scenarios, not one, even if one sentence implies both).

If a story genuinely has no acceptance criteria written down, say so plainly in the report
instead of inventing AC — infer testable behavior from the description/summary only as a
fallback, and label it as inferred.

### Step 3 — Extract and inspect QA evidence

Scan the comments chronologically for:
- Explicit test results (pass/fail/blocked, TC IDs, "verified", "tested", sign-off language)
- References to specific scenarios or AC items
- Evidence pointers: inline images (`!filename.png!`), attached logs, linked docs/sheets

For every attachment `download_jira_issue_attachments` returns:
- **Images** (screenshots) — use `Read` on the local file path to actually view it. Check
  whether it shows the state/screen/data the comment claims it does, and which scenario it
  actually supports. A screenshot proves what's visibly in it, nothing more — don't assume it
  covers a scenario the tester didn't call out just because it's attached to the ticket.
- **Text/log files** — read the preview content already returned (or `Read` the file if the
  preview was truncated) and check it corroborates the claimed result (e.g. a log showing a
  200 response for the case being tested, or a stack trace for a claimed failure).
- **Binary files** you can't inspect (zips, etc.) — note their presence and filename in the
  evidence list, but don't credit them as verified proof of anything specific.

QA evidence isn't always a native Jira attachment — comments frequently just link out to an
external Google Doc or Sheet (e.g. "test results here: docs.google.com/..."). Treat these
exactly like attachments, not like citations:
- Any `docs.google.com` / `drive.google.com` URL found in a comment must be opened with
  `mcp__google-drive__download_file_from_url` and its actual content inspected — never credit a
  scenario as COVERED just because a comment links to a doc titled "test results" or "QA sign-off."
  Read what the linked doc actually contains before deciding what it proves.
- If the link fails to open (no access, deleted, wrong permissions), say so explicitly in the
  Evidence section and treat whatever it was supposed to support as PARTIAL/NOT COVERED, not
  COVERED-by-assumption.
- Apply the same skepticism as native attachments: a linked doc that says "all tests passed"
  with no per-scenario detail is weaker evidence than one with a scenario-by-scenario table or
  screenshots embedded/described.

Build a mental map: scenario → which comment(s) and which evidence file(s)/linked doc(s) support
it, if any.

### Step 4 — Classify coverage per scenario

For each scenario from Step 2, assign one status:

- ✅ **COVERED** — a comment references this scenario AND evidence (screenshot/log/clear
  description of steps+result) actually substantiates the claimed outcome.
- ⚠️ **PARTIAL** — the scenario is mentioned as tested, but the evidence is missing, doesn't
  clearly match the claim, or only covers part of the scenario (e.g. happy path shown, error
  path claimed but not evidenced).
- ❌ **NOT COVERED** — no comment or evidence references this scenario at all.

Never mark something COVERED on the strength of a claim alone — that's what PARTIAL is for.
Be specific in your notes about *why* something is PARTIAL or NOT COVERED so the QA lead can
act on it (e.g. "comment claims negative-input case tested but no screenshot/log attached"
rather than just "insufficient evidence").

### Step 5 — Identify missed scenarios and uncovered edge cases

**Missed scenarios** = every scenario from Step 2 marked NOT COVERED. List them verbatim against
the AC they came from.

**Uncovered edge cases** = testing angles a QA lead would expect even though the AC doesn't spell
them out. Reason about what's actually relevant to *this* feature (don't paste a generic
boilerplate list) — consider things like:
- Invalid/malformed/negative input handling
- Boundary values (empty, zero, max length, min/max counts)
- Permission/role checks (unauthorized user, wrong tenant/org)
- Duplicate or concurrent submissions
- Error/rollback/retry behavior when a dependency fails
- Empty or null states (no data yet, first-time user)
- Cross-browser, multi-user, or data-volume conditions, when relevant to the feature area

Only list edge cases that are plausible risks for what this story actually changes — infer this
from the description/components, not a fixed checklist. Frame these as recommendations for
additional testing, not as failures, since they weren't required by the AC.

### Step 6 — Compute a verdict

For each story, compute coverage = (COVERED scenarios) / (total scenarios), and pick a verdict:
- **Ready for sign-off** — all scenarios COVERED, no evidenced failures in comments.
- **Needs additional testing** — one or more scenarios PARTIAL or NOT COVERED.
- **Blocked / regressions found** — comments show unresolved failures or bugs logged against
  this story's own scenarios.

### Step 7 — Generate the Google Doc

First, resolve the output folder:
1. Call `mcp__google-drive__list_folder` with `folder_id: "root"`, `only_folders: true` — look for a folder named exactly `claude_outputs`.
2. If not found, call `mcp__google-drive__create_folder` with `name: "claude_outputs"`. Save its `file_id` as `CLAUDE_OUTPUTS_ID`.
3. Call `mcp__google-drive__list_folder` with `folder_id: CLAUDE_OUTPUTS_ID`, `only_folders: true` — look for a subfolder named exactly `qa-evidence-audit`.
4. If not found, call `mcp__google-drive__create_folder` with `name: "qa-evidence-audit"`, `parent_folder_id: CLAUDE_OUTPUTS_ID`. Save its `file_id` as `OUTPUT_FOLDER_ID`.

Create one Google Doc via `mcp__google-drive__create_google_doc` with `content_format:
"markdown"` and `folder_id: OUTPUT_FOLDER_ID`. Title: `QA Coverage Review - <KEY or KEY1, KEY2, ...> - <today's date>`.

If reviewing multiple stories, open with a batch summary table, then give each story its own
full section. Use this structure per story:

```markdown
# QA Coverage & Gap Review — <KEY> — <Story Summary>

**Status:** <Jira status> | **Assignee:** <assignee> | **Reviewed:** <date>
**Verdict:** <Ready for sign-off / Needs additional testing / Blocked> — <coverage>% AC coverage

## 1. Acceptance Criteria Coverage

| # | Acceptance Criterion | Status | Evidence | Notes |
|---|---|---|---|---|
| 1 | ... | ✅ COVERED | [screenshot.png] / comment by X on <date> | ... |

## 2. Missed Scenarios
- ...

## 3. Uncovered Edge Cases (Recommended Additional Testing)
- ...

## 4. Evidence Reviewed
- List every attachment and comment actually inspected, with what it showed.

## 5. Summary
Short paragraph: overall verdict and the top 1-3 things the QA lead should follow up on.
```

### Step 8 — Report back in chat

After creating the doc, give the user a short chat summary (not a duplicate of the whole
report): the doc link, the verdict per story, and the single most important gap per story if
any. Keep it to a few sentences — the doc has the detail.

## Quality Rules

- Never fabricate evidence or comments that don't exist. If you can't find something, say
  "not found" rather than inferring it happened.
- Always state *why* a scenario is PARTIAL/NOT COVERED in terms the tester could act on.
- Keep edge-case suggestions grounded in the actual feature — no generic filler.
- If a story's attachments fail to download or an image can't be read, note that explicitly in
  the Evidence section rather than silently skipping it.
