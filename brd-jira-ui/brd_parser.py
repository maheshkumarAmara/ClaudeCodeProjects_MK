import re
import ssl
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from io import BytesIO

import docx

JIRA_PAT = re.compile(r'\b([A-Z][A-Z0-9]{1,9}-\d+)\b')

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
    'order mgmt': 'OM', 'order management': 'OM', ' om ': 'OM', 'om\n': 'OM',
    'quoting': 'Quoting', 'cpq': 'Quoting', 'quote': 'Quoting',
    'revenue': 'Revenue', 'billing': 'Revenue', 'rev rec': 'Revenue',
    'cs': 'CS', 'customer success': 'CS', 'customer support': 'CS',
    'opportunity': 'Opportunity', 'opp mgmt': 'Opportunity',
    'npi': 'NPI', 'new product': 'NPI',
    'marketing': 'Marketing', 'mktg': 'Marketing',
}


def normalize_section(raw: str) -> str:
    if not raw:
        return 'General'
    key = f' {raw.strip().lower()} '
    for k, v in SECTION_MAP.items():
        if k in key:
            return v
    return raw.strip().title()[:30] or 'General'


def parse_fields(text: str) -> dict:
    fields = {}
    for name, pat in FIELD_RE.items():
        m = pat.search(text)
        fields[name] = m.group(1).strip()[:1000] if m else ''
    return fields


def extract_jira_ids(text: str) -> list:
    return list(dict.fromkeys(JIRA_PAT.findall(text)))


def _parse_document(doc) -> list:
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    requirements = []
    current_section = 'General'
    para_buffer, current_ids, freeform_count, table_count = [], [], 0, 0

    def flush_para():
        nonlocal para_buffer, current_ids, freeform_count
        if not current_ids or not para_buffer:
            para_buffer, current_ids = [], []
            return
        text = '\n'.join(para_buffer)
        fields = parse_fields(text)
        if any(fields.get(k) for k in ('what', 'functional', 'acceptance', 'to_be')):
            who_section = normalize_section(fields.get('who', ''))
            section = who_section if who_section != 'General' else current_section
            requirements.append({
                'source': f'freeform_{freeform_count}',
                'jira_ids': current_ids,
                'section': section,
                'status_brd': '',
                'priority_brd': '',
                'fields': fields,
            })
        freeform_count += 1
        para_buffer, current_ids = [], []

    for block in doc.element.body:
        tag = block.tag

        if tag == qn('w:p'):
            para = DocxParagraph(block, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or '').lower()
            if 'heading' in style:
                flush_para()
                current_section = text[:50]
                continue
            ids = extract_jira_ids(text)
            if ids and len(text) < 150:
                flush_para()
                current_ids = ids
                para_buffer = [text]
            elif current_ids:
                para_buffer.append(text)
                if len(para_buffer) > 40:
                    flush_para()

        elif tag == qn('w:tbl'):
            flush_para()
            table = DocxTable(block, doc)
            for row_idx, row in enumerate(table.rows):
                cells = [cell.text.strip() for cell in row.cells]
                if not cells or all(not c for c in cells):
                    continue

                # Use the longest cell as the requirement description
                desc_idx = max(range(len(cells)), key=lambda i: len(cells[i])) if cells else 0
                req_cell = cells[desc_idx] if cells else ''

                # Priority 1: non-first, non-description cells (e.g. JIRA Story column).
                # cells[0] is typically the BRD row number (e.g. "ORDB-01") which matches
                # the Jira ID regex but is NOT a real ticket — skip it as primary source.
                jira_ids = []
                for i in range(1, len(cells)):
                    if i != desc_idx:
                        jira_ids.extend(extract_jira_ids(cells[i]))
                jira_ids = list(dict.fromkeys(jira_ids))

                # Priority 2: description cell may embed Jira references
                if not jira_ids:
                    jira_ids = extract_jira_ids(req_cell)

                # Priority 3: first cell only as last resort
                if not jira_ids:
                    jira_ids = extract_jira_ids(cells[0])
                fields = parse_fields(req_cell)

                # Fallback: if no structured labels found, treat the plain text as 'what'
                if not any(fields.get(k) for k in ('what', 'functional', 'acceptance', 'to_be')):
                    plain = req_cell.strip()
                    if plain and len(plain) > 20:
                        fields['what'] = plain[:1000]

                has_content = any(fields.get(k) for k in ('what', 'functional', 'acceptance', 'to_be'))
                if not jira_ids and not has_content:
                    continue
                if row_idx == 0 and not jira_ids and len(req_cell) < 60:
                    continue

                who_section = normalize_section(fields.get('who', ''))
                section = who_section if who_section != 'General' else current_section

                # Assign status/priority from small cells, excluding the ID cell (0)
                # and the description cell (desc_idx) to avoid polluting them
                small_cells = [cells[i] for i in range(1, len(cells)) if i != desc_idx]
                status_brd = (small_cells[0] if len(small_cells) > 0 else '')[:30]
                priority_brd = (small_cells[1] if len(small_cells) > 1 else '')[:30]

                requirements.append({
                    'source': f'table_{table_count}_row_{row_idx}',
                    'jira_ids': jira_ids,
                    'section': section,
                    'status_brd': status_brd,
                    'priority_brd': priority_brd,
                    'fields': fields,
                })
            table_count += 1

    flush_para()
    return requirements


def parse_from_bytes(file_bytes: bytes) -> list:
    doc = docx.Document(BytesIO(file_bytes))
    return _parse_document(doc)


def parse_from_url(url: str) -> list:
    """Download a Google Doc/docx and parse it.

    Tries authenticated Drive API first, then falls back to public export URL.
    Both require the document to be accessible to the authenticated account or
    shared publicly ("Anyone with the link").
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    file_id_m = re.search(r'/d/([a-zA-Z0-9_-]{20,})', url)
    if not file_id_m:
        raise ValueError(f"Cannot extract file ID from URL: {url}")
    file_id = file_id_m.group(1)

    is_google_doc = 'docs.google.com/document' in url

    # ── Build auth token ──────────────────────────────────────────────
    # Priority 1: GOOGLE_ACCESS_TOKEN env var (easiest override)
    import config as _cfg
    token = _cfg.GOOGLE_ACCESS_TOKEN.strip()
    token_source = 'env var GOOGLE_ACCESS_TOKEN' if token else ''
    auth_error_detail = ''

    # Priority 2: MCP token file
    if not token:
        token_file = Path.home() / '.gdrive-mcp-token.json'
        if token_file.exists():
            try:
                td = json.loads(token_file.read_text())
                expires_at = td.get('expires_at', 0)
                if not isinstance(expires_at, (int, float)):
                    expires_at = 0
                if expires_at < time.time() + 60:
                    body = urllib.parse.urlencode({
                        'client_id': td['client_id'],
                        'client_secret': td['client_secret'],
                        'refresh_token': td['refresh_token'],
                        'grant_type': 'refresh_token',
                    }).encode()
                    rv = json.loads(urllib.request.urlopen(
                        urllib.request.Request(
                            td.get('token_uri', 'https://oauth2.googleapis.com/token'),
                            data=body,
                            headers={'Content-Type': 'application/x-www-form-urlencoded'},
                            method='POST'),
                        context=ctx).read())
                    td['access_token'] = rv['access_token']
                    td['expires_at'] = time.time() + rv.get('expires_in', 3600)
                    token_file.write_text(json.dumps(td))
                token = td.get('access_token') or td.get('token', '')
                token_source = 'MCP token file'
            except Exception as e:
                auth_error_detail = f'Token file error: {e}'

    headers = {'Authorization': f'Bearer {token}'} if token else {}

    # ── Try authenticated download ────────────────────────────────────
    if headers:
        if is_google_doc:
            dl_url = (
                f'https://www.googleapis.com/drive/v3/files/{file_id}/export'
                '?mimeType=application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            try:
                meta_req = urllib.request.Request(
                    f'https://www.googleapis.com/drive/v3/files/{file_id}?fields=mimeType',
                    headers=headers)
                meta = json.loads(urllib.request.urlopen(meta_req, context=ctx).read())
                mime = meta.get('mimeType', '')
            except Exception:
                mime = ''
            dl_url = (
                f'https://www.googleapis.com/drive/v3/files/{file_id}/export'
                '?mimeType=application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                if 'google-apps.document' in mime
                else f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media'
            )
        try:
            resp = urllib.request.urlopen(
                urllib.request.Request(dl_url, headers=headers), context=ctx)
            return parse_from_bytes(resp.read())
        except urllib.error.HTTPError as e:
            body_text = ''
            try:
                body_text = e.read().decode(errors='replace')[:300]
            except Exception:
                pass
            if e.code in (401, 403):
                auth_error_detail = (
                    f'Drive API returned HTTP {e.code} using {token_source}. '
                    f'The token likely has "drive.file" scope only (not "drive.readonly"). '
                    f'Detail: {body_text}'
                )
            # Fall through to public URL

    # ── Public export URL (works when doc is shared "Anyone with the link") ──
    public_url = (
        f'https://docs.google.com/document/d/{file_id}/export?format=docx'
        if is_google_doc
        else f'https://drive.google.com/uc?export=download&id={file_id}'
    )
    try:
        resp = urllib.request.urlopen(
            urllib.request.Request(public_url), context=ctx)
        return parse_from_bytes(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            scope_hint = (
                '\n\nScope fix: add GOOGLE_ACCESS_TOKEN to brd-jira-ui/.env\n'
                '  • Run: gcloud auth print-access-token  (requires gcloud CLI)\n'
                '  • Or go to https://developers.google.com/oauthplayground, '
                'select "Google Drive API v3 → drive.readonly", get a token, paste it in .env'
            )
            detail = f'\n\nAuth detail: {auth_error_detail}' if auth_error_detail else ''
            raise RuntimeError(
                "This Google Doc is private — access denied.\n\n"
                "Fix options:\n"
                "• Upload the file: open the doc → File → Download → Microsoft Word (.docx) → use the 'Upload .docx' tab\n"
                "• Or make it public: Share → Anyone with the link → Viewer"
                + scope_hint + detail
            )
        raise
