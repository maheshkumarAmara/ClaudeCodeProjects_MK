import base64
import json
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import config

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

_b64 = base64.b64encode(f'{config.JIRA_EMAIL}:{config.JIRA_API_TOKEN}'.encode()).decode()
_HEADERS = {'Authorization': f'Basic {_b64}', 'Accept': 'application/json'}
_FIELDS = 'summary,description,parent,issuetype,customfield_10701,customfield_10702,customfield_10703'


def _get(key: str) -> dict | None:
    url = f'{config.JIRA_URL}/rest/api/3/issue/{key}?fields={_FIELDS}'
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        return json.loads(urllib.request.urlopen(req, context=ctx).read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


def _adf_to_text(node) -> str:
    if not node:
        return ''
    texts = []

    def walk(n):
        if isinstance(n, dict):
            if n.get('type') == 'text':
                texts.append(n.get('text', ''))
            elif n.get('type') in ('hardBreak', 'rule'):
                texts.append(' ')
            for c in n.get('content', []):
                walk(c)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return ' '.join(t for t in texts if t.strip()).strip()


def _parse_issue(raw: dict | None, key: str) -> dict | None:
    if not raw:
        return None
    f = raw.get('fields', {})
    return {
        'key': key,
        'summary': f.get('summary', ''),
        'description': _adf_to_text(f.get('description')),
        'acceptance_criteria': _adf_to_text(f.get('customfield_10701')),
        'parent_key': (f.get('parent') or {}).get('key'),
        'issue_type': (f.get('issuetype') or {}).get('name', ''),
        'url': f'{config.JIRA_URL}/browse/{key}',
    }


def fetch_tickets(jira_ids: list[str]) -> tuple[dict, dict]:
    """
    Fetch all tickets and their parents.
    Returns (ticket_cache, parent_cache) dicts keyed by Jira key.
    """
    ticket_cache: dict = {}
    parent_ids: set = set()

    def fetch_one(key):
        raw = _get(key)
        return key, _parse_issue(raw, key)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for key, data in ex.map(fetch_one, jira_ids):
            ticket_cache[key] = data
            if data and data.get('parent_key'):
                parent_ids.add(data['parent_key'])

    # Fetch parents not already in cache
    parent_cache: dict = {}
    new_parent_ids = parent_ids - set(ticket_cache.keys())
    if new_parent_ids:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for key, data in ex.map(fetch_one, sorted(new_parent_ids)):
                parent_cache[key] = data

    return ticket_cache, parent_cache
