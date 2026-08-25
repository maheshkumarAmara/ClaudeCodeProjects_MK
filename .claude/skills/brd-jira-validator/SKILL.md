---
name: brd-jira-validator
description: Compare BRD requirements (Google Drive Word doc) against linked Jira tickets. Parses BRD tables and free-form text, extracts Jira IDs per row, fetches each ticket + parent description, performs 3-way comparison (BRD vs Jira vs Parent Jira), and generates a color-coded Google Sheet highlighting mismatches. Use when asked to validate BRD vs Jira, check requirement alignment, compare BRD to Jira tickets, or audit requirements coverage.
argument-hint: <BRD_GOOGLE_DRIVE_URL> [jira=<JIRA_TICKET_URL_or_KEY>]
allowed-tools: Bash(python3 *), Bash(pip3 *), Bash(pip *), Read(*), mcp__google-drive__create_google_sheet(*), mcp__google-drive__update_sheet_values(*), mcp__google-drive__update_sheet_cell_color(*), mcp__google-drive__add_sheet_tab(*), mcp__google-drive__add_sheet_hyperlink(*), mcp__google-drive__list_folder(*), mcp__google-drive__create_folder(*)
---

## Role

You are a QA requirements analyst. Your job is to detect gaps and contradictions between a BRD and its corresponding Jira tickets — before defects slip through.

---

## Input

The user provided: **$ARGUMENTS**

Parse from `$ARGUMENTS`:
- `BRD_URL` — Google Drive URL of the Word document (.docx). Required. It is the first URL-like argument.
- `JIRA_KEY` — Optional. A specific Jira ticket to investigate in depth. Parsed from `jira=<value>` or a bare Jira key/URL.

If `BRD_URL` is missing, ask:
```
Please provide the Google Drive URL of the BRD Word document:
```

---

## Step 1 — Download BRD + Parse + Fetch Jira Data (python3 call #1)

Replace `<<BRD_URL>>` with the actual URL before running.

```python
import json, ssl, urllib.request, urllib.parse, re, sys, time, base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import docx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-docx', '-q'])
    import docx

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BRD_URL = "<<BRD_URL>>"

# ── Extract Google Drive file ID ───────────────────────────────────
def extract_file_id(url):
    m = re.search(r'/d/([a-zA-Z0-9_-]{20,})', url)
    if m: return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]{20,})', url)
    if m: return m.group(1)
    raise ValueError(f"Cannot extract file ID from: {url}")

file_id = extract_file_id(BRD_URL)

# ── Refresh Drive OAuth token ──────────────────────────────────────
td = json.loads(Path.home().joinpath('.gdrive-mcp-token.json').read_text('utf-8'))
if td.get('expires_at', 0) < time.time() + 60:
    body = urllib.parse.urlencode({
        'client_id': td['client_id'], 'client_secret': td['client_secret'],
        'refresh_token': td['refresh_token'], 'grant_type': 'refresh_token',
    }).encode()
    rv = json.loads(urllib.request.urlopen(
        urllib.request.Request(
            td.get('token_uri', 'https://oauth2.googleapis.com/token'),
            data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST'),
        context=ctx).read())
    td['access_token'] = rv['access_token']
    td['expires_at'] = time.time() + rv.get('expires_in', 3600)
    Path.home().joinpath('.gdrive-mcp-token.json').write_text(json.dumps(td))
ACCESS_TOKEN = td['access_token']

# ── Download raw .docx binary from Google Drive ────────────────────
print(f"Downloading BRD (file_id={file_id})...")

# First check file metadata to confirm it's downloadable
meta_req = urllib.request.Request(
    f'https://www.googleapis.com/drive/v3/files/{file_id}?fields=name,mimeType,size',
    headers={'Authorization': f'Bearer {ACCESS_TOKEN}'}
)
try:
    meta = json.loads(urllib.request.urlopen(meta_req, context=ctx).read())
    print(f"  File: {meta.get('name')} | Type: {meta.get('mimeType')} | Size: {meta.get('size', '?')} bytes")
    mime = meta.get('mimeType', '')
except Exception as e:
    print(f"  Warning: could not get metadata: {e}")
    mime = ''

# If it's a Google Doc, export as docx; if it's a native docx, download directly
if 'google-apps.document' in mime:
    dl_url = f'https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType=application/vnd.openxmlformats-officedocument.wordprocessingml.document'
else:
    dl_url = f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media'

resp = urllib.request.urlopen(
    urllib.request.Request(dl_url, headers={'Authorization': f'Bearer {ACCESS_TOKEN}'}),
    context=ctx
)
docx_bytes = resp.read()
docx_path = '/tmp/brd_validator.docx'
with open(docx_path, 'wb') as f:
    f.write(docx_bytes)
print(f"  Saved {len(docx_bytes):,} bytes → {docx_path}")

# ── Parse .docx ────────────────────────────────────────────────────
doc = docx.Document(docx_path)

JIRA_PAT = re.compile(r'\b([A-Z][A-Z0-9]{1,9}-\d+)\b')

# Structured BRD field labels and their regex patterns
FIELD_RE = {
    'what':         re.compile(r'What\s*\(requirement\)\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Why|Who|As-is|To-Be|Functional|Conditions?|Exceptions?|Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'why':          re.compile(r'Why\s*\(benefits?\)\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Who|As-is|To-Be|Functional|Conditions?|Exceptions?|Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'who':          re.compile(r'Who\s*\(affected\s*users?\)\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:As-is|To-Be|Functional|Conditions?|Exceptions?|Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'as_is':        re.compile(r'As-is\s*\(current[- ]state\)\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:To-Be|Functional|Conditions?|Exceptions?|Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'to_be':        re.compile(r'To-Be\s*\(desired[- ]state\)\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Functional|Conditions?|Exceptions?|Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'functional':   re.compile(r'Functional\s*Requirements?\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Conditions?|Exceptions?|Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'conditions':   re.compile(r'Conditions?\s*\(criteria[^)]*\)\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Exceptions?|Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'exceptions':   re.compile(r'Exceptions?\s*\(criteria[^)]*\)\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Assumptions?|Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'assumptions':  re.compile(r'Assumptions?\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Dependencies?|Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'dependencies': re.compile(r'Dependencies?\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Acceptance|Written)|$)', re.DOTALL | re.IGNORECASE),
    'acceptance':   re.compile(r'Acceptance\s*Criteria\s*[:\-]\s*(.*?)(?=\n\s*(?:\*\*)?(?:Written)|$)', re.DOTALL | re.IGNORECASE),
}

SECTION_MAP = {
    'order mgmt': 'OM', 'order management': 'OM', 'om': 'OM',
    'quoting': 'Quoting', 'cpq': 'Quoting', 'quote': 'Quoting',
    'revenue': 'Revenue', 'billing': 'Revenue', 'rev rec': 'Revenue',
    'cs': 'CS', 'customer success': 'CS', 'customer support': 'CS',
    'opportunity': 'Opportunity', 'opp': 'Opportunity',
    'npi': 'NPI', 'new product': 'NPI',
    'marketing': 'Marketing', 'mktg': 'Marketing',
}

def normalize_section(raw):
    if not raw: return 'General'
    key = raw.strip().lower()
    for k, v in SECTION_MAP.items():
        if k in key: return v
    return raw.strip().title()[:30] or 'General'

def parse_fields(text):
    fields = {}
    for name, pat in FIELD_RE.items():
        m = pat.search(text)
        fields[name] = m.group(1).strip()[:1000] if m else ''
    return fields

def extract_jira_ids(text):
    return list(dict.fromkeys(JIRA_PAT.findall(text)))

requirements = []

# ── Parse table rows ───────────────────────────────────────────────
print("Parsing BRD tables...")
for table_idx, table in enumerate(doc.tables):
    for row_idx, row in enumerate(table.rows):
        cells = [cell.text.strip() for cell in row.cells]
        if not cells or all(not c for c in cells): continue

        # Heuristic: skip pure header rows (first row, no Jira IDs, short cells)
        first_cell = cells[0]
        jira_ids = extract_jira_ids(first_cell)

        # Also look for Jira IDs in second cell if first has none
        if not jira_ids and len(cells) > 1:
            jira_ids = extract_jira_ids(cells[1])

        # Requirement text is usually the last (or largest) cell
        req_cell = max(cells, key=len) if cells else ''
        fields = parse_fields(req_cell)

        # Skip if no content worth keeping
        has_content = any(fields.get(k) for k in ('what', 'functional', 'acceptance', 'to_be'))
        if not jira_ids and not has_content:
            continue

        # Skip header row patterns
        if row_idx == 0 and not jira_ids and len(req_cell) < 60:
            continue

        section = normalize_section(fields.get('who', ''))
        status_cell = cells[1] if len(cells) > 1 else ''
        priority_cell = cells[2] if len(cells) > 2 else ''

        requirements.append({
            'source': f'table_{table_idx}_row_{row_idx}',
            'jira_ids': jira_ids,
            'section': section,
            'status_brd': status_cell[:30],
            'priority_brd': priority_cell[:30],
            'fields': fields,
        })

# ── Parse free-form paragraphs (outside tables) ────────────────────
print("Parsing BRD free-form sections...")
para_buffer = []
current_jira_ids = []
current_section = 'General'
para_req_count = 0

def flush_para_buffer():
    global para_buffer, current_jira_ids
    if not current_jira_ids or not para_buffer:
        para_buffer = []
        current_jira_ids = []
        return
    full_text = '\n'.join(para_buffer)
    fields = parse_fields(full_text)
    has_content = any(fields.get(k) for k in ('what', 'functional', 'acceptance', 'to_be'))
    if has_content:
        section = normalize_section(fields.get('who', current_section))
        requirements.append({
            'source': f'freeform_{para_req_count}',
            'jira_ids': current_jira_ids,
            'section': section,
            'status_brd': '',
            'priority_brd': '',
            'fields': fields,
        })
    para_buffer = []
    current_jira_ids = []

for para in doc.paragraphs:
    text = para.text.strip()
    if not text: continue
    style = (para.style.name or '').lower()

    # Detect section headings
    if 'heading' in style:
        flush_para_buffer()
        current_section = text[:50]
        continue

    # Detect new requirement block: paragraph has Jira IDs and is short
    ids_in_para = extract_jira_ids(text)
    if ids_in_para and len(text) < 150:
        flush_para_buffer()
        para_req_count += 1
        current_jira_ids = ids_in_para
        para_buffer = [text]
    elif current_jira_ids:
        para_buffer.append(text)
        if len(para_buffer) > 40:  # safety flush
            flush_para_buffer()

flush_para_buffer()

print(f"  Found {len(requirements)} total requirements ({sum(1 for r in requirements if 'table' in r['source'])} from tables, {sum(1 for r in requirements if 'freeform' in r['source'])} free-form)")

# ── Load Jira credentials ──────────────────────────────────────────
jira_url = jira_email = jira_token = ''

# Priority 1: jira-dashboard/.env in CWD
for env_path in [Path.cwd() / 'jira-dashboard' / '.env', Path.cwd() / '.env']:
    if env_path.exists():
        for line in env_path.read_text(errors='replace').splitlines():
            if not line.strip() or line.strip().startswith('#'): continue
            if '=' not in line: continue
            k, _, v = line.partition('=')
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == 'JIRA_URL' and not jira_url: jira_url = v
            if k == 'JIRA_EMAIL' and not jira_email: jira_email = v
            if k == 'JIRA_API_TOKEN' and not jira_token: jira_token = v
        if jira_url: break

# Priority 2: ~/.mcp.conf.yaml
if not jira_url:
    try:
        conf = (Path.home() / '.mcp.conf.yaml').read_text(errors='replace')
        m = re.search(r"jira:.*?url:\s*['\"]([^'\"]+)['\"]", conf, re.DOTALL)
        if m: jira_url = m.group(1).strip("'\"")
        m = re.search(r'jira:.*?user:\s*([^\s\n]+)', conf, re.DOTALL)
        if m: jira_email = m.group(1).strip("'\"")
        m = re.search(r'jira:.*?token:\s*([^\s\n]+)', conf, re.DOTALL)
        if m: jira_token = m.group(1).strip("'\"")
    except Exception as e:
        print(f"  Could not read ~/.mcp.conf.yaml: {e}")

if not (jira_url and jira_email and jira_token):
    print("ERROR: Jira credentials not found. Ensure jira-dashboard/.env has JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN.")
    sys.exit(1)

print(f"Jira: {jira_url}")
jira_b64 = base64.b64encode(f'{jira_email}:{jira_token}'.encode()).decode()

def jira_get(key):
    url = (
        f'{jira_url}/rest/api/3/issue/{key}'
        '?fields=summary,description,parent,issuetype,'
        'customfield_10701,customfield_10702,customfield_10703'
    )
    req = urllib.request.Request(
        url, headers={'Authorization': f'Basic {jira_b64}', 'Accept': 'application/json'}
    )
    try:
        return json.loads(urllib.request.urlopen(req, context=ctx).read())
    except urllib.error.HTTPError as e:
        print(f"  Jira HTTP {e.code} for {key}")
        return None
    except Exception as e:
        print(f"  Jira error for {key}: {e}")
        return None

def adf_to_text(node):
    """Recursively extract plain text from Atlassian Document Format."""
    if not node: return ''
    texts = []
    def walk(n):
        if isinstance(n, dict):
            if n.get('type') == 'text':
                texts.append(n.get('text', ''))
            elif n.get('type') in ('hardBreak', 'rule'):
                texts.append('\n')
            for c in n.get('content', []):
                walk(c)
        elif isinstance(n, list):
            for item in n: walk(item)
    walk(node)
    return ' '.join(t for t in texts if t.strip()).strip()

# ── Collect all unique Jira IDs ────────────────────────────────────
all_ids = list(dict.fromkeys(jid for r in requirements for jid in r['jira_ids']))
print(f"\nFetching {len(all_ids)} Jira tickets...")

jira_cache = {}
parent_ids_to_fetch = set()

def fetch_ticket(key):
    issue = jira_get(key)
    if not issue:
        return key, None
    f = issue.get('fields', {})
    parent_key = (f.get('parent') or {}).get('key')
    return key, {
        'key': key,
        'summary': f.get('summary', ''),
        'description': adf_to_text(f.get('description')),
        'acceptance_criteria': adf_to_text(f.get('customfield_10701')),
        'parent_key': parent_key,
        'issue_type': (f.get('issuetype') or {}).get('name', ''),
    }

with ThreadPoolExecutor(max_workers=6) as ex:
    for key, data in ex.map(fetch_ticket, all_ids):
        jira_cache[key] = data
        if data and data.get('parent_key'):
            parent_ids_to_fetch.add(data['parent_key'])
        status = 'OK' if data else 'NOT FOUND'
        print(f"  {key}: {status}")

# ── Fetch parent tickets ───────────────────────────────────────────
parent_cache = {}
parent_ids_new = parent_ids_to_fetch - set(jira_cache.keys())
if parent_ids_new:
    print(f"\nFetching {len(parent_ids_new)} parent tickets...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        for key, data in ex.map(fetch_ticket, sorted(parent_ids_new)):
            parent_cache[key] = data
            status = 'OK' if data else 'NOT FOUND'
            print(f"  {key} (parent): {status}")

# ── Save output ────────────────────────────────────────────────────
sections = sorted(set(r['section'] for r in requirements))
output = {
    'requirements': requirements,
    'jira_cache': jira_cache,
    'parent_cache': parent_cache,
    'sections': sections,
    'jira_base_url': jira_url,
}
Path('/tmp/brd_analysis.json').write_text(
    json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8'
)

print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRD Parse + Jira Fetch — Complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Requirements : {len(requirements)}
Jira tickets : {sum(1 for v in jira_cache.values() if v)} / {len(all_ids)} found
Parent tickets: {sum(1 for v in parent_cache.values() if v)} / {len(parent_cache)} found
Sections     : {', '.join(sections) or 'None detected'}
Output       : /tmp/brd_analysis.json
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
```

---

## Step 2 — Analyze Mismatches (Claude)

Read `/tmp/brd_analysis.json` using the Read tool.

For **each requirement** in `requirements`:

**Gather the three sources:**
1. **BRD**: `fields.what` + `fields.functional` + `fields.acceptance` + `fields.to_be` + `fields.conditions`
2. **Jira tickets**: For each ID in `jira_ids`, look up `jira_cache[id]` → `description` + `acceptance_criteria`
3. **Parent Jira**: For each Jira ticket that has a `parent_key`, look up `parent_cache[parent_key]` → `description` + `acceptance_criteria`

**Classify each requirement row:**

| Status | Meaning |
|--------|---------|
| `GREEN` | Jira adequately covers the BRD requirement; no contradiction with parent |
| `YELLOW` | Partial: some BRD requirements are present but others are missing/vague; or minor inconsistency with parent |
| `RED` | Clear contradiction between BRD ↔ Jira, or between child Jira ↔ parent Jira; or Jira is missing critical requirements from BRD |
| `NO_JIRA` | BRD row has no linked Jira IDs |

**For RED and YELLOW rows, document issues specifically:**
- What the BRD says (quote the relevant field)
- What the Jira says (or "not mentioned")
- What the parent Jira says (if applicable)
- The exact type of mismatch: `MISSING`, `CONTRADICTION`, `PARENT_CONFLICT`, `INCOMPLETE`

**Build result list:**
```json
[
  {
    "req_index": 0,
    "jira_ids": ["ORDB-02", "GTMIT-569"],
    "section": "OM",
    "status": "RED",
    "brd_summary": "Automated PO Validation via EDI/Glynt",
    "brd_acceptance": "All PayGo deals can go through EDI/Glynt and be validated accurately",
    "jira_description_summary": "...",
    "parent_description_summary": "...",
    "issues": [
      {
        "type": "MISSING",
        "detail": "BRD specifies 'PO lines should validate against Primary Quote Lines' — this condition is not mentioned in ORDB-02 description"
      }
    ]
  }
]
```

After classifying all rows, count: total, GREEN, YELLOW, RED, NO_JIRA.

---

## Step 3 — Generate Google Sheet Report

### Step 3a — Create Google Sheet

First, resolve the output folder:
1. Call `mcp__google-drive__list_folder` with `folder_id: "root"`, `only_folders: true` — look for a folder named exactly `claude_outputs`.
2. If not found, call `mcp__google-drive__create_folder` with `name: "claude_outputs"`. Save its `file_id` as `CLAUDE_OUTPUTS_ID`.
3. Call `mcp__google-drive__list_folder` with `folder_id: CLAUDE_OUTPUTS_ID`, `only_folders: true` — look for a subfolder named exactly `brd-jira-validator`.
4. If not found, call `mcp__google-drive__create_folder` with `name: "brd-jira-validator"`, `parent_folder_id: CLAUDE_OUTPUTS_ID`. Save its `file_id` as `OUTPUT_FOLDER_ID`.

Call `mcp__google-drive__create_google_sheet` with:
- `title`: `BRD-Jira Validation — {today's date}`
- `headers`: `["Section", "Jira ID(s)", "BRD Requirement", "BRD Acceptance Criteria", "Jira Description", "Parent Jira Description", "Status", "Issues Found"]`
- `rows`: All requirement rows, one per row, truncating cell values to 500 chars max
- `folder_id`: `OUTPUT_FOLDER_ID`

Save the returned `file_id`.

### Step 3b — Color-code status column and row backgrounds

For each data row (starting at row index 1, since row 0 is headers), call `mcp__google-drive__update_sheet_cell_color` twice per row:

**Status cell (column G = index 6) — bold color:**
- GREEN: `bg_red=0.56, bg_green=0.77, bg_blue=0.49`
- YELLOW: `bg_red=0.98, bg_green=0.84, bg_blue=0.17`
- RED: `bg_red=0.91, bg_green=0.27, bg_blue=0.27`
- NO_JIRA: `bg_red=0.75, bg_green=0.75, bg_blue=0.75`

**Full row (columns A–H = indices 0–7) — light tint:**
- GREEN: `bg_red=0.85, bg_green=0.93, bg_blue=0.83`
- YELLOW: `bg_red=1.0, bg_green=0.96, bg_blue=0.8`
- RED: `bg_red=0.98, bg_green=0.87, bg_blue=0.87`
- NO_JIRA: `bg_red=0.95, bg_green=0.95, bg_blue=0.95`

> **Performance note:** Batch color calls by status group. For example, apply RED row background to all RED rows at once if they are contiguous; otherwise call per-row. Do not skip coloring.

### Step 3c — Add section tabs

For each unique section in `sections` (from the analysis JSON):
1. Call `mcp__google-drive__add_sheet_tab` with `title=<section_name>`
2. Call `mcp__google-drive__update_sheet_values` to write the header row + filtered rows for that section only
3. Color the status cells for that tab using the same rules as Step 3b

---

## Step 4 — Present Summary

After the sheet is created, output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRD-Jira Validation Complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Requirements scanned : {total}
✅ GREEN  (Full Match) : {green_count}
⚠️  YELLOW (Partial)   : {yellow_count}
❌ RED    (Mismatch)   : {red_count}
⬜ NO_JIRA (Not linked): {no_jira_count}

Sections: {comma-separated list}
Report: {web_view_link from create_google_sheet}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Then list all RED and YELLOW issues grouped by section:

```
SECTION: OM
  ❌ ORDB-02, GTMIT-569 — MISSING: BRD requires PO line validation against Primary Quote Lines; not found in Jira description
  ⚠️  ORDB-05 — INCOMPLETE: Jira covers As-is state but does not address the acceptance criteria

SECTION: Quoting
  ❌ SFCPQ-12 — CONTRADICTION: BRD says system validates without manual touch; parent Jira (SFCPQ-8) still includes manual review step
```

---

## Handling a Specific Jira Investigation (Optional)

If the user provided `JIRA_KEY` in arguments:

After Step 2, do a **deep-dive analysis** on that specific ticket only:

1. Find its matching BRD requirement (by Jira ID match in `requirements`)
2. Show the full BRD requirement text for that row (all fields)
3. Show the full Jira description + acceptance criteria
4. Show the full parent Jira description + acceptance criteria
5. Do a field-by-field comparison table:

```
Field               | BRD                    | Jira                   | Parent Jira            | Match?
What (requirement)  | Automated PO Validation | PO Validation feature  | EDI/Glynt Integration  | ⚠️ Partial
Acceptance Criteria | All PayGo deals...      | Not specified          | All deals validated... | ❌ Missing in Jira
Functional Req      | EDI/Glynt Stage POs... | Stage PO via Glynt...  | EDI integration...     | ✅ Match
```

Present this before generating the Google Sheet.
