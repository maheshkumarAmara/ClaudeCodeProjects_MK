"""
BRD Version Diff — compares two parsed BRD requirement lists.
Uses keyword-based similarity to match requirements across versions,
then field-level diffing to classify each as added/removed/changed/unchanged.
"""
import re

_STOP = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'in', 'on',
         'at', 'to', 'of', 'for', 'with', 'this', 'that', 'will', 'be', 'by',
         'from', 'as', 'it', 'its', 'not', 'no', 'can', 'do', 'have', 'has',
         'been', 'being', 'had', 'would', 'could', 'should', 'shall', 'must'}

_FIELDS = ['what', 'why', 'who', 'as_is', 'to_be', 'functional', 'conditions',
           'exceptions', 'assumptions', 'dependencies', 'acceptance']

_MATCH_THRESHOLD = 0.28  # minimum Jaccard similarity to pair two requirements


def _keywords(text: str) -> set:
    return {w for w in re.findall(r'\b[a-zA-Z]{4,}\b', (text or '').lower())
            if w not in _STOP}


def _req_text(req: dict) -> str:
    """Concatenate all text fields for similarity scoring."""
    fields = req.get('fields', {})
    parts = [req.get('section', '')]
    for k in _FIELDS:
        v = (fields.get(k) or '').strip()
        if v:
            parts.append(v)
    return ' '.join(filter(None, parts))


def _similarity(text_a: str, text_b: str) -> float:
    """Jaccard similarity on keyword sets."""
    kw_a = _keywords(text_a)
    kw_b = _keywords(text_b)
    if not kw_a and not kw_b:
        return 1.0
    if not kw_a or not kw_b:
        return 0.0
    return len(kw_a & kw_b) / len(kw_a | kw_b)


def _section_bonus(r1: dict, r2: dict) -> float:
    """Small bonus when requirements share the same section."""
    s1 = (r1.get('section') or '').strip().lower()
    s2 = (r2.get('section') or '').strip().lower()
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 0.10
    if s1 in s2 or s2 in s1:
        return 0.05
    return 0.0


def _field_diffs(f1: dict, f2: dict) -> list:
    """Return list of {field, old, new} for fields that changed."""
    diffs = []
    for k in _FIELDS:
        old = (f1.get(k) or '').strip()
        new = (f2.get(k) or '').strip()
        if old != new:
            diffs.append({'field': k, 'old': old, 'new': new})
    return diffs


def diff_brds(reqs_v1: list, reqs_v2: list) -> dict:
    """
    Compare two lists of parsed BRD requirements.

    Greedy similarity matching pairs each v2 requirement with its closest v1
    counterpart (above the threshold). Unmatched v1 → removed, unmatched v2 →
    added. Matched pairs are diffed field-by-field.

    Returns:
        {added, removed, changed, unchanged, affected_jira, stats}
    """
    n1, n2 = len(reqs_v1), len(reqs_v2)
    texts_v1 = [_req_text(r) for r in reqs_v1]
    texts_v2 = [_req_text(r) for r in reqs_v2]

    # Build full similarity matrix (clamped to 1.0)
    sim = [
        [min(_similarity(texts_v1[i], texts_v2[j]) + _section_bonus(reqs_v1[i], reqs_v2[j]), 1.0)
         for j in range(n2)]
        for i in range(n1)
    ]

    # Greedy matching: highest score first, each index used at most once
    pairs = sorted(
        ((sim[i][j], i, j) for i in range(n1) for j in range(n2)),
        key=lambda x: -x[0],
    )
    matched_v1: dict[int, int] = {}  # i → j
    matched_v2: dict[int, int] = {}  # j → i
    for score, i, j in pairs:
        if score < _MATCH_THRESHOLD:
            break
        if i not in matched_v1 and j not in matched_v2:
            matched_v1[i] = j
            matched_v2[j] = i

    added, removed, changed, unchanged = [], [], [], []
    affected_jira: set = set()

    # Unmatched v1 → removed
    for i in range(n1):
        if i not in matched_v1:
            jids = reqs_v1[i].get('jira_ids', [])
            removed.append({'type': 'removed', 'req': reqs_v1[i], 'jira_ids': jids})
            affected_jira.update(jids)

    # Unmatched v2 → added
    for j in range(n2):
        if j not in matched_v2:
            jids = reqs_v2[j].get('jira_ids', [])
            added.append({'type': 'added', 'req': reqs_v2[j], 'jira_ids': jids})
            affected_jira.update(jids)

    # Matched pairs → changed or unchanged
    for i, j in matched_v1.items():
        r1, r2 = reqs_v1[i], reqs_v2[j]
        f1, f2 = r1.get('fields', {}), r2.get('fields', {})
        diffs = _field_diffs(f1, f2)

        # Section rename
        sec1 = (r1.get('section') or '').strip()
        sec2 = (r2.get('section') or '').strip()
        if sec1 != sec2:
            diffs.insert(0, {'field': 'section', 'old': sec1, 'new': sec2})

        # Jira ID changes
        jids1 = set(r1.get('jira_ids', []))
        jids2 = set(r2.get('jira_ids', []))
        if jids1 != jids2:
            diffs.append({
                'field': 'jira_ids',
                'old': ', '.join(sorted(jids1)),
                'new': ', '.join(sorted(jids2)),
            })

        all_jids = list(jids1 | jids2)
        score = round(sim[i][j], 3)

        if diffs:
            changed.append({
                'type': 'changed',
                'v1': r1, 'v2': r2,
                'diffs': diffs,
                'similarity': score,
                'jira_ids': all_jids,
            })
            affected_jira.update(all_jids)
        else:
            unchanged.append({
                'type': 'unchanged',
                'req': r2,
                'similarity': score,
                'jira_ids': all_jids,
            })

    return {
        'added': added,
        'removed': removed,
        'changed': changed,
        'unchanged': unchanged,
        'affected_jira': sorted(affected_jira),
        'stats': {
            'total_v1': n1,
            'total_v2': n2,
            'added': len(added),
            'removed': len(removed),
            'changed': len(changed),
            'unchanged': len(unchanged),
            'affected_jira': len(affected_jira),
        },
    }
