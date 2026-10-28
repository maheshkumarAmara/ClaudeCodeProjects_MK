---
name: testcase-review
description: >-
  Review test cases for a feature, ticket, or user story and identify gaps.
  Use when someone shares a Jira ticket, user story, or feature description
  and asks for a test case review, missing scenarios, or coverage gaps.
  Trigger phrases: "review my test cases", "what am I missing", "check coverage",
  "test case review for", or sharing a ticket/story and asking about testing.
---

# Test Case Reviewer

Reviews test cases for a feature or ticket. When a Jira story is provided,
automatically finds test case subtasks, reads existing test cases, checks
coverage against acceptance criteria, and produces a structured Google Doc
showing what is covered and what is missing. By default also posts a
summary to Slack and adds a comment on the subtask tagging the assignee —
either can be turned off via `POST_JIRA_COMMENT` / `POST_SLACK_NOTIFICATION`
in this skill's `config.txt`.

## Input

Accept any of the following:
- A Jira ticket/story URL or key (e.g. PRDOPS-722) — full enhanced flow with subtask lookup
- A pasted feature description or user story — generate test case suggestions from scratch
- A list of existing test cases pasted directly — review and gap-analyse them

If only a ticket number or URL is given, always start by fetching the full
ticket details and searching for test case subtasks before proceeding.

## Speed

This skill involves many tool calls across Jira, Google Drive, and
Confluence. These rules are MANDATORY, not aspirational — every one of them
cuts wall-clock time without cutting analysis scope. Never skip a source to
save time (Step 2's four sources are all still required); the speedup comes
from doing the same reads concurrently, in fewer round trips, and from not
narrating the same content twice — not from reading or writing less.

- **Parallelize independent lookups — one message, many tool calls.** Any
  calls that don't depend on each other's output MUST go in the same
  message. This specifically means:
  - All test-case subtasks' description + comments + dev-info calls fire
    together, across ALL subtasks at once — never process subtask 1 fully
    (description, comments, docs) before starting subtask 2. Kick off every
    subtask's reads in the same batch.
  - Every Google Doc / Confluence link discovered while reading comments is
    fetched in one batched round, not one-by-one as each is noticed.
  - Step 3b's regression-candidate detail fetches all go in one batch call.
  - Step 3b's JQL searches start in parallel with Step 2, not after it —
    Step 3b only depends on Step 1's component/field names.
- **Batch Jira fetches.** When reading more than 2-3 issues (subtasks,
  regression candidates), use `get_jira_issues_with_changelog_batch` with a
  comma-separated key list instead of one `get_jira_issue_details` call per
  issue.
- **Batch attachment downloads.** Use `download_jira_issue_attachments`
  (downloads every attachment on an issue in one call) instead of looping
  a per-file `download_attachment` call for each image.
- **Cap regression-search depth.** See the limit in Step 3b — don't fetch
  full details for every JQL hit.
- **Don't generate the same content twice.** Step 4's chat summary is a
  progress display, not a deliverable — the Google Doc is the deliverable.
  Keep Step 4 condensed (counts, verdict, top 2-3 risks only) and put the
  full per-GAP write-up (steps, preconditions, expected result) only in the
  Step 5 doc. Writing that full detail out twice roughly doubles generation
  time for zero functional benefit.

## Steps

### Step 1 — Fetch the story

Read the Jira ticket:
- Summary, description, and acceptance criteria
- Opportunity type, scope, out-of-scope items
- Any mix-and-match scenario matrices in the description
- Any documents linked directly under the description or Acceptance Criteria
  section -- e.g. a "Test case Document"/"Use Cases" link or a "Design
  Document" link. These are distinct from subtask-linked docs (Step 2) and
  often contain the authoritative business-logic table the plain-text
  description only summarizes. Open and read them in full now; do not treat
  the description's prose summary as sufficient on its own when a linked
  doc with the full logic table is right there.
- ALL comments in full — read every comment chronologically

While reading comments, track the resolution status of every issue, defect,
or blocker mentioned:
- If a comment says a bug/defect is fixed, resolved, or closed → mark it as
  RESOLVED and do NOT flag it as an open gap in the review
- If a comment says testing is blocked by an issue → check later comments to
  see if the blocker was resolved before flagging it as a risk
- If a defect was found in UAT but a later comment confirms it was fixed and
  re-tested → treat it as ✅ Covered, not a gap
- Only flag issues as open risks if the LATEST comments confirm they are
  still unresolved

This prevents the skill from raising stale defects that have already been
fixed as if they are still open issues.

### Step 2 — Find test case subtasks and read ALL content

Search for child subtasks of the story. Look for subtasks whose summary
contains any of: "test case", "test design", "TC", "QA", "testing scenarios".

**Exclusion:** Do NOT treat a subtask literally titled "Test Execution" (or
matching that summary pattern) as a test case source. Test Execution subtasks
track run status and pass/fail evidence for cases that already exist elsewhere
(Test Case Design subtask, linked sheet, etc.) — pulling from them risks
double-counting or treating execution notes as newly defined test cases.
Skip them entirely in this step; do not extract TC-IDs from them.

For each subtask found, extract test cases from ALL of the following sources
in order. Do not stop after one source — read all of them:

**Source A — Subtask description (text)**
Read the full description of the subtask. If it contains test case text,
extract each test case and assign a TC-ID.

**Source B — Subtask comments**
Call get_jira_issue_comments on every test case subtask. Read ALL comments
chronologically. Look for:
- Test cases written directly in comment text
- Google Doc links (docs.google.com) — fetch these immediately (see Source C)
- Confluence links — fetch these immediately
- Mentions of external test evidence with a URL
- Screenshots described in text ("attached screenshot shows...")
Note: comments often contain the most up-to-date test case information,
especially when the description was never filled in.

**Source C1 — Google Sheets (test case tracker) found in the Test Case Design subtask**
Many teams keep test cases in one shared, multi-tab Google Sheet (one tab per
sprint) rather than a per-story doc. Do NOT assume the sheet's default/first
tab is the right one — that tab is almost always a different, more recent
sprint. Follow this exact procedure:

1. Extract the Google Sheet URL from the Test Case Design subtask (description
   or comments) and pull the `gid=` value from the URL — this is the specific
   tab the link points to.
2. Call list_sheet_tabs on the sheet to get every tab's sheet_id and title.
3. Match the `gid` from the URL against a tab's sheet_id to identify the exact
   tab to read. If the URL has no gid, or the match fails, fall back to the
   story's Sprint / Fix Version field from the Jira ticket (e.g. Sprint 14 →
   look for a tab titled "...Sprint 14") to pick the tab.
4. Read only that specific tab's contents — not the whole spreadsheet, and
   not tab index 0 by default.
5. That tab likely contains test cases for MANY stories, not just this one.
   Filter its rows down to only those whose Ticket# / story key column matches
   this story's Jira key (e.g. PRDOPS-1054). Ignore all other rows.
6. For each matching row, extract the test case (its own Test Case No# /
   TC-ID if the sheet already assigns one, title, description, steps,
   expected result, and any QA Status / execution result columns).
7. If zero rows match the story key on the identified tab, say so explicitly
   ("No rows in [tab name] matched [story key]") rather than silently
   reporting no test cases — this is different from the sheet having no
   test cases at all, and should prompt a check of whether the tab/gid
   match was correct.

**Source C2 — Google Docs and other external links found in comments or description**
For every Google Doc URL (not a Sheet) found in the subtask description or comments:
- Use google-drive tools to fetch and read the full document content
- Extract all test cases, scenarios, pass/fail results, and execution dates
- Map each test case found to a TC-ID
- Note the doc title and link as the source

For Confluence URLs: use confluence tools to fetch and read the page content.

**Source D — Image and screenshot attachments**
Check the subtask for image attachments (screenshots of test cases, test
evidence tables, execution results).

For each image attachment found:
1. Download the attachment using the Jira download_attachment tool
2. Read the image using vision — extract all visible text including:
   - Test case titles and IDs
   - Steps listed in the screenshot
   - Pass/Fail status per test case
   - Any comments or annotations visible in the image
3. Assign TC-IDs to test cases extracted from images, noting the source
   as "[subtask key] — image attachment: [filename]"

If an image cannot be read or is unclear, note it as:
"⚠️ Image attachment [filename] found but could not be fully read —
manual review recommended."

**After reading all sources:**
- Assign a sequential TC-ID to each unique test case found across all sources
  (format: TC-001, TC-002, TC-003 ... continuing across all subtasks)
- Note the source of each TC-ID (description / comment / Google Doc / image)
- Note the subtask key, summary, assignee, and all TC-IDs mapped

If no test cases are found after checking ALL sources (description, comments,
linked docs, and attachments), only then note "No test cases found" and
proceed to Step 3 using the story's acceptance criteria as the baseline.

If no subtasks are found at all, note this and proceed to Step 3 using only
the story's acceptance criteria and description as the baseline.

### Step 3 — Extract and analyse coverage

Build a full picture of the feature by combining:
- Acceptance criteria from the story (read directly from the Jira ticket)
- The test cases pulled from the tracker sheet in Step 2, Source C1 — already
  filtered down to only this story's rows

The comparison is always: **Jira acceptance criteria (the requirement) vs.
the story's rows in the test case tracker sheet (what was actually tested)**.
Do not compare against unrelated stories' rows on the same tab, and do not
substitute the sheet's own pass/fail status for this comparison — a row can
be marked "Pass" in the sheet and still not actually address a given
acceptance criterion; judge coverage by what the test case's steps and
expected result actually verify, not by its status column alone.

For each acceptance criterion and scenario from the story, determine:
- ✅ Covered — a test case in the subtasks explicitly addresses this scenario.
  Always reference the TC-ID (e.g. "Covered by TC-003")
- ⚠️ Partially covered — a test case exists but doesn't fully address it.
  Reference the TC-ID and explain exactly what is missing from it
  (e.g. "TC-005 covers the happy path but does not test the Administrator
  role condition separately")
- ❌ Not covered — no test case exists for this scenario. Assign a new
  gap ID in format GAP-001, GAP-002 ... for each missing case

Then identify additional gaps not in the acceptance criteria, each with a GAP-ID.

**Priority rating for every GAP:**
Assign a priority based on business impact:
- P1 — Critical: core business flow, data integrity, SOX/compliance, or blocks UAT sign-off
- P2 — High: important scenario likely to occur in production, notable risk if missed
- P3 — Medium: edge case or low-frequency scenario, good to have but not blocking

**Assignee for every GAP:**
Suggest who should own the GAP based on:
- The assignee of the Test Case Design or Test Execution subtask (primary)
- If subtask has no assignee, use the story assignee
- If neither is available, write "Unassigned"

**For every gap (GAP-ID), write a fully detailed test case using EXACTLY this format:**

FORMATTING RULE: Use plain markdown **bold** (double asterisks) for ALL labels
below -- do NOT use Unicode bold characters. The Google Doc tools used by this
skill (create_google_doc / update_google_doc_content with content_format="markdown")
render markdown bold reliably. Unicode bold characters are error-prone to type
correctly in a single pass and have caused garbled labels in past runs -- build
each GAP block programmatically (e.g. via a script or template) rather than
hand-typing the Unicode glyphs, and visually verify the rendered text before
writing it into the doc.

Use this EXACT format for every GAP in the Google Doc:

  **GAP-001** | [Category] | [Scenario Title]
  Priority: [P1 / P2 / P3] -- [Critical / High / Medium]: [one line reason]

  **Assigned To**: [assignee name or "Unassigned"]

  **Scenario**: [one line describing the scenario]

  **Preconditions**:
  - [precondition 1]
  - [precondition 2]

  **Test Data Required**:
  - [specific record, field value, or setup needed before executing this test]

  **Steps**:
  1. [specific action]
  2. [specific action]
  3. [specific action]

  **Expected Result**:
  [exact expected outcome written on the line BELOW the label]

  Why this matters: [1 sentence on the risk if not tested]

  ---

Use content_format="markdown" for all other formatting (headings, tables, bullet lists).

Categories to cover for gaps:

**Happy path gaps**
- Standard successful flows end-to-end not yet covered
- All acceptance criteria paths verified

**Edge case gaps**
- Boundary values: test minimum AND maximum values explicitly
  (e.g. "quantity = 0", "quantity = max allowed + 1")
- Empty/null inputs: what happens when optional fields are left blank
- Whitespace-only inputs: field appears filled but contains only spaces
- Special characters in text fields: e.g. apostrophes, ampersands, Unicode
- Large data volumes: performance or truncation issues
- Inactive/expired/pending states of related records
- Field cleared after previously being populated

**Negative scenario gaps**
- Invalid input: exact invalid value, exact expected error message
- Unauthorised access: specific role that should be blocked and what they see
- Missing required fields: which field, what error appears
- Concurrent submissions: two users submitting the same record simultaneously
- Race conditions: same order triggered twice within milliseconds
- System or service unavailable: what the user sees, does data persist

**Environment / configuration gaps**
- Different org types: test each relevant type (Commercial, Gov, Private, Edu)
  with the specific behaviour expected per org
- Different user roles/profiles: list each role separately as its own test case
- QA vs UAT sandbox: known configuration differences that could affect behaviour

**Integration point gaps**
- Downstream triggers: exactly which system, what event triggers it, what
  the expected outcome in the downstream system is
- API error responses: specific HTTP codes or error payloads expected
- Regression: specific existing flow that could be broken, with exact steps

**Do NOT raise as GAPs — Jira hygiene / process observations**
Things like an empty Test Case Design/Test Execution subtask description, a
test evidence doc not being linked from the subtask or story, or the ticket
status not yet reflecting "QA Completed" are process/traceability
observations, not test coverage gaps — nothing is untested, the evidence is
just stored somewhere the skill had to be told about directly. Never give
these a GAP-ID, a priority, an assignee, or a full test-case write-up (no
Preconditions/Steps/Expected Result — there is nothing to execute). If worth
mentioning at all, fold it into the Feature Summary or Test Case Subtask(s)
list in Step 5 as a one-line note (e.g. "evidence doc is not linked in
PRDOPS-1742") — never as its own section or table row, and never counted in
the Coverage Score or the ❌ Not Covered count.

### Step 3b — Regression risk check

Search Jira for stories, bugs, or defects that could be impacted by this
story's changes. Use the following JQL patterns:

  - Same component: component = "[component from story]" AND status != Done
  - Same field names: text ~ "[key field name]" AND type = Bug AND created >= -90d
  - Related stories in the same epic or sprint if identifiable

**Depth cap:** if a JQL search returns more than 8 matches, take only the
top 8 by most-recently-updated and note "[N] additional matches not
individually reviewed — narrow further if needed." For the matches you do
review, do NOT stop at the title -- fetch each ticket's full description and
acceptance criteria, the same depth of read as Step 1 does for the parent
story. Fetch all of them in one batch call (`get_jira_issues_with_changelog_batch`
with the comma-separated keys) rather than one `get_jira_issue_details` call
per ticket. A title or component match alone is not enough to judge
regression risk; the real question is whether that ticket's own requirements
conflict with, depend on, or assume the pre-change behaviour that this story
is altering.

Before making that conflict judgement, also check the PARENT story's own
description/Acceptance Criteria section for any linked "Test case Document",
"Use Cases" document, or "Design Document" (these often appear as inline
links directly under Acceptance Criteria, not just in subtask comments).
If present and not already fetched in Step 1, open and read them in full --
they typically contain the authoritative business-logic table (e.g. the
Early/On Time/Late date-policy matrix) that the plain-text description only
summarizes. Use this full table, not just the description's prose summary,
as the reference when judging whether a related ticket's AC actually
conflicts with this story's change -- a described conflict that turns out to
be already covered by a row in that table is not a real regression risk.

For each match found, assess using its actual description/AC content:
- Is this ticket actively in progress or recently resolved?
- Does its description or AC explicitly rely on the specific field, trigger,
  date logic, or system behaviour that this story changes?
- Could this story's change break, contradict, or alter an assumption stated
  in that ticket's own acceptance criteria -- not just "touches the same area"?
- If the other ticket is itself a Bug/defect, does its root cause description
  reference the same logic path this story modifies?

Only flag tickets that represent a genuine regression risk based on this
deeper read — not every ticket in the same project, and not every ticket
that merely shares a component or field name without an actual conflict in
its stated requirements. For each risk found, note:
  ⚠️ [Ticket key] — [Title] — [Why this could regress, citing the specific
  line/requirement from that ticket's description or AC that creates the
  conflict — not just "same component"]

If a related ticket is found by search but its description/AC shows no real
conflict once read in full, do not list it as a regression risk — note in
the review's working notes that it was checked and ruled out, so the doc
only surfaces genuine risks.

If no related tickets found after searching, state:
  "No regression risk identified after Jira search."

### Step 4 — Show findings summary in chat

Display a summary in chat as the skill runs (no confirmation needed — continue
automatically to Step 5):
- Number of subtasks found and TC-IDs assigned to existing test cases
- Coverage Score: X% (covered / total scenarios)
- Coverage breakdown: how many scenarios are ✅ covered / ⚠️ partial / ❌ missing
- Go / No-Go / Conditional Go verdict (see criteria below)
- Full detailed list of all GAP-IDs with priority, assignee, and complete test case steps
- Covered scenarios mapped to their TC-IDs
- Regression risk summary (related tickets or fields that could be impacted)
- Top 2–3 risk areas

Do not ask for confirmation. Proceed immediately to Step 5.

**Coverage Score calculation:**
  Coverage Score = (✅ Covered + 0.5 × ⚠️ Partial) / Total AC scenarios × 100
  Round to nearest whole number. Show as: "Coverage Score: 67%"

**Go / No-Go / Conditional Go verdict criteria:**
- 🟢 GO — Coverage Score ≥ 80% AND no P1 gaps AND no open blockers
- 🟡 CONDITIONAL GO — Coverage Score 50–79% OR has P2 gaps but no P1 gaps
  AND no open blockers. State conditions that must be met before release.
- 🔴 NO-GO — Coverage Score < 50% OR has any open P1 gaps OR has unresolved
  blockers. State what must be fixed before UAT sign-off.

**Regression risk check:**
Search Jira for stories or bugs that touch the same fields, components, or
systems mentioned in this story. Flag any active or recently closed tickets
that could indicate regression risk. List them as:
  ⚠️ Regression risk: [ticket key] — [why it could be affected]
If nothing found, state: "No related regression risk identified."

### Step 5 — Create Google Doc

Create the doc inside the folder named by `DOC_FOLDER_ID` in this skill's
`config.txt` (read that file rather than hardcoding the ID) — pass it as
`folder_id` to `create_google_doc`. That folder is shared once with the
team, so every doc created inside it automatically inherits that access;
this is what lets Step 5 skip the manual per-document sharing step your
team used to need. If `DOC_FOLDER_ID` is missing or the create call fails
because the folder no longer exists, fall back to creating the doc in the
user's My Drive root and tell the user the folder needs to be recreated and
reshared (see config.txt's comment for how) — never fail the whole review
over a missing folder.

Create a Google Doc titled: "[Ticket Key] — Test Case Review"

Structure:

  # [Ticket Key] — Test Case Review

  𝗗𝗮𝘁𝗲: [today]

  𝗦𝘁𝗼𝗿𝘆: [Jira link]

  𝗦𝘁𝗮𝘁𝘂𝘀: [current ticket status]

  𝗧𝗲𝘀𝘁 𝗖𝗮𝘀𝗲 𝗦𝘂𝗯𝘁𝗮𝘀𝗸(𝘀):
  - [subtask key and link] (Status) — note
  - [subtask key and link] (Status) — note

  𝗧𝗖-𝗜𝗗𝘀 𝗮𝘀𝘀𝗶𝗴𝗻𝗲𝗱: [e.g. TC-001 to TC-012]

  𝗚𝗔𝗣-𝗜𝗗𝘀 𝗶𝗱𝗲𝗻𝘁𝗶𝗳𝗶𝗲𝗱: [e.g. GAP-001 to GAP-009]

  𝗥𝗲𝘃𝗶𝗲𝘄𝗲𝗱 𝗯𝘆: Claude (Cowork)

  ---

  ## 🎯 QA Summary Dashboard

  | Metric | Value |
  |--------|-------|
  | Coverage Score | X% |
  | ✅ Covered | N scenarios |
  | ⚠️ Partially Covered | N scenarios |
  | ❌ Not Covered | N gaps |
  | P1 Gaps (Critical) | N |
  | P2 Gaps (High) | N |
  | P3 Gaps (Medium) | N |
  | Regression Risks | N related tickets |

  ## 🚦 QA Verdict: [GO / CONDITIONAL GO / NO-GO]
  [One paragraph explaining the verdict — what is covered, what is missing,
  and what conditions must be met before UAT sign-off or release.
  Written in plain English for the Release Manager and business stakeholders
  to read without needing to understand the full test details.]

  ---

  ## Feature Summary
  [2–3 sentence summary]

  ## Existing Test Cases (from subtasks)
  | TC-ID | Subtask | Source | Test Case Title | Status |
  |-------|---------|--------|-----------------|--------|
  | TC-001 | PRDOPS-1220 | Description / Comment / Google Doc / Image | [title] | [Pass/Fail/Not Run] |
  ...

  Note: Source column must always identify exactly where the test case was
  found — description, comment (date), Google Doc (link), or image (filename).

  ## Coverage Analysis

  ### ✅ Covered
  | AC / Scenario | TC-ID | Test Environment | Actual Result | Execution Date | Notes |
  |---------------|-------|-----------------|---------------|----------------|-------|
  | [scenario] | TC-003 | QA / UAT / Production | [what actually happened — e.g. "Manual Fulfilment set to TRUE as expected"] | [date test was run] | [any additional notes] |

  For every covered scenario, populate:
  - Test Environment: which environment the test was executed in (QA / UAT / Production)
  - Actual Result: the exact observed outcome in plain English — not just "Pass". Write what the system did.
  - Execution Date: the date the test was run (from the evidence doc or Jira comments)

  ### ⚠️ Partially Covered
  | AC / Scenario | TC-ID | Test Environment | Actual Result | What's Missing |
  |---------------|-------|-----------------|---------------|----------------|
  | [scenario] | TC-005 | QA | [what was observed] | [what condition or variation was not tested] |

  ### ❌ Not Covered — Detailed Gap Analysis

  (use the GAP format with Unicode bold labels, Priority, Assignee, and
  Test Data Required as defined in Step 3)

  ## ⚠️ Regression Risk
  | Related Ticket | Relationship | Risk |
  |----------------|-------------|------|
  | [TICKET-123] | Same field/component | [why it could regress] |

  If no regression risks found: "No related regression risk identified."

  ## Risk Areas
  [Top 2–3 risk areas with explanation — focus on P1 gaps and open blockers]

### Step 6 — Add Jira comment on the test case subtask

Read `POST_JIRA_COMMENT` from this skill's `config.txt` first. If it is set
to `false`, skip this step entirely — do not post a comment — and say so in
the Step 4/7 summaries (e.g. "💬 Jira comment skipped — disabled in
config.txt"). Treat it as `true` if the key is missing from the file.

The `mcp__jira__add_jira_issue_comment` tool only works on a fixed project
allowlist that excludes PRDOPS (see reference_jira_comment_tool_restrictions
memory), so this step posts directly against the Jira REST API instead —
the same approach used for jira-dashboard's `add_comment`, using the
jira-dashboard project's own `.env` credentials. This works on any project
the account can comment on, not just the allowlisted ones.

1. Write the comment body (everything after the mention/intro line) as
   markdown to a temp file, e.g. `/tmp/tcr_comment_<ISSUE_KEY>.md`:

  ```
  Review doc: [Google Doc link](<actual Google Doc URL>)

  **Summary:**
  - ✅ **Covered:** [N] scenarios (TC-IDs: [list])
  - ⚠️ **Partially covered:** [N] scenarios (TC-IDs: [list])
  - ❌ **Not covered:** [N] gaps (GAP-001 to GAP-N)

  **Key gaps:**
  - [GAP-ID]: [one-line description]
  - [GAP-ID]: [one-line description]
  ```

2. Post it with the helper script (resolves the subtask's QA Contact field
   automatically for the @mention, falling back to the assignee if QA
   Contact is empty, and to "Hi team," if neither is set). The script lives
   at `scripts/post_jira_comment.py` inside *this skill's own directory* —
   use the base directory given for this skill invocation rather than a
   hardcoded path, so the skill still works if it's copied or shared to a
   different machine, user, or checkout location:

  ```
  python3 <this-skill's-directory>/scripts/post_jira_comment.py \
    <SUBTASK_KEY> /tmp/tcr_comment_<ISSUE_KEY>.md
  ```

   See this skill's `README.md` for the one-time setup (`.env` credentials,
   Python deps) a new environment needs before this step will work.

3. The script prints the comment ID and a direct link on success — confirm
   the exit code was 0 before treating the comment as posted. If it fails,
   show the user the exact error and the comment body so they can post it
   manually rather than silently skipping.

### Step 7 — Post to Slack

Read `POST_SLACK_NOTIFICATION` from this skill's `config.txt` first. If it
is set to `false`, skip this step entirely — do not post to Slack — and
note it in the Step 4 summary (e.g. "📣 Slack post skipped — disabled in
config.txt"). Treat it as `true` if the key is missing from the file.

Send a message to the channel the user specifies (ask if not given, default
is the `SLACK_CHANNEL` value in this skill's `config.txt` -- read that file
for the current default rather than assuming a channel name). Slack uses
single-asterisk *bold* (not
markdown **bold**) -- use single asterisks for every bolded label below.
Format:

  🧪 *Test Case Review: [Ticket Key] — [Summary]*

  🚦 *Verdict: [GO / CONDITIONAL GO / NO-GO]*
  📊 *Coverage Score:* X% · ✅ [N] covered · ⚠️ [N] partial · ❌ [N] gaps
  🔴 P1 Gaps: [N] · 🟡 P2 Gaps: [N] · 🟢 P3 Gaps: [N]
  🔖 *TC-IDs:* TC-001 to TC-[N] | Gaps: GAP-001 to GAP-[N]
  ⚠️ *Regression risks:* [N] related tickets flagged

  *Key risks:* [1–2 sentence summary of top P1 gaps or blockers]

  📄 *Review doc:* [Google Doc link]
  💬 *Jira comment:* posted on [subtask key] tagging *[QA Contact name, or assignee if no QA Contact set]* (or, if posting failed: `💬 Comment failed to post on [subtask key] — [error]`)

## Rules

- Run end-to-end automatically once a Jira ID is provided — no manual
  confirmation or intervention required at any step
- Always read ALL comments chronologically before finalising gaps — never
  flag a defect or blocker as open if later comments confirm it was resolved
- In Google Docs, Preconditions:, Steps:, and Expected Result: MUST each be
  on their own separate line with **bold** markdown and nothing else on that line.
  Content goes on the NEXT line. The GAP heading (####) handles the scenario name.
  Never write **Preconditions:** text on the same line — it will not render bold.
- Before Step 6, check `POST_JIRA_COMMENT` in config.txt — if `false`, skip
  posting the Jira comment entirely for this run
- When posting is not disabled, always post the Step 6 Jira comment via
  `scripts/post_jira_comment.py` (direct REST API) — never use
  `mcp__jira__add_jira_issue_comment` for this step, since its allowlist
  excludes PRDOPS
- Before Step 7, check `POST_SLACK_NOTIFICATION` in config.txt — if `false`,
  skip the Slack post entirely for this run
- When not disabled, post to Slack automatically after the Google Doc is created
- Always assign TC-IDs to existing test cases found in subtasks
- Always read ALL four sources for every subtask: description, comments,
  linked Google Docs/Confluence pages, and image attachments — never stop
  after just reading the description
- For every Google Doc link found in comments or description, fetch and read
  it using google-drive tools before concluding no test cases exist
- For every image attachment, download and read it using vision to extract
  test case text — note the filename as the source
- Always assign GAP-IDs to every missing test case identified
- Every GAP must have Priority (P1/P2/P3), Assigned To, Test Data Required,
  full steps, preconditions, and expected result — never write a one-line gap
- Never create a GAP for Jira hygiene/process issues (empty subtask
  descriptions, an evidence doc not linked in Jira, status not updated to
  "QA Completed"). These aren't coverage gaps — at most, note them in one
  line in the Feature Summary or subtask list, never as a GAP-ID
- Always calculate and display the Coverage Score and Go/No-Go verdict
- Always run a Jira regression search before finalising the review —
  search for tickets touching the same fields, components, or systems
- Never invent test cases — base all suggestions on the story's acceptance
  criteria, description, or inferable integration points; flag uncertain
  ones as "verify if applicable"
- If the story has no acceptance criteria or description, ask the user to
  paste the details before proceeding
- The Jira comment (Step 6) tags the subtask's QA Contact field first; only
  fall back to the assignee if QA Contact is empty, and to "team" if neither
  is set
- Default Slack channel is the `SLACK_CHANNEL` value in this skill's
  `config.txt` file, unless the user says otherwise -- read config.txt at
  Step 7 rather than hardcoding a channel name, so the default can be
  changed by editing config.txt alone
- Save the Google Doc into the `DOC_FOLDER_ID` folder from config.txt by
  default (so it inherits that folder's sharing and needs no manual
  per-document share step), unless the user specifies a different folder
- If no test case subtasks are found, still complete the review using the
  story's acceptance criteria, assign GAP-IDs from GAP-001, and note the
  absence of subtasks in the doc
