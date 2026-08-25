"""
3-way comparison: BRD requirement vs Jira description vs Parent Jira description.
Uses Claude API when ANTHROPIC_API_KEY is set; falls back to keyword heuristics.
"""
import json
import re
import time

import anthropic

import config

def _get_client() -> anthropic.Anthropic:
    """Return a shared Anthropic client with extended timeout and auto-retry."""
    return anthropic.Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        timeout=300.0,
        max_retries=3,
    )


def _call_with_retry(fn, retries: int = 3, base_delay: float = 2.0):
    """Call fn(), retrying on timeout/connection errors with exponential backoff."""
    for attempt in range(retries):
        try:
            return fn()
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise RuntimeError("unreachable")

_STOP = {'the','a','an','is','are','was','were','and','or','in','on','at','to','of',
         'for','with','this','that','will','be','by','from','as','it','its','not','no',
         'can','do','have','has','been','being','had','would','could','should','shall','must'}


def _testability_score(fields: dict) -> dict:
    """Heuristic testability score (0-100) for a BRD requirement."""
    text = ' '.join(filter(None, [
        fields.get('what', ''), fields.get('functional', ''),
        fields.get('acceptance', ''), fields.get('conditions', ''), fields.get('to_be', ''),
    ])).lower()

    score = 100
    issues = []

    has_measurable = bool(re.search(
        r'\b\d+\s*(%|seconds?|minutes?|hours?|days?|ms|gb|mb|kb|items?|users?|records?|chars?|clicks?)\b', text
    ))
    if not has_measurable:
        has_measurable = bool(re.search(
            r'\b(at least|at most|within|more than|less than|minimum|maximum|exactly|no more than)\b', text
        ))
    if not has_measurable:
        score -= 20
        issues.append('No measurable criteria — add thresholds, counts, or time limits')

    has_conditions = bool(re.search(r'\b(when|if|given|then|should|must|shall)\b', text))
    if not has_conditions:
        score -= 15
        issues.append('No clear conditions — add when/if/then language')

    if not fields.get('acceptance', '').strip():
        score -= 20
        issues.append('No acceptance criteria defined')

    vague = [w for w in ['appropriate','reasonable','efficient','user-friendly','fast','good',
                          'nice','easy','simple','quick','smooth','seamless','intuitive']
             if re.search(rf'\b{w}\b', text)]
    if vague:
        score -= min(len(vague) * 10, 20)
        issues.append(f'Vague language: {", ".join(vague[:3])} — replace with specific criteria')

    has_edge = bool(re.search(
        r'\b(exception|error|fail|invalid|edge|boundary|overflow|timeout|empty|null|none|missing)\b', text
    ))
    if not has_edge and not fields.get('exceptions', '').strip():
        score -= 10
        issues.append('No edge cases or exceptions defined')

    score = max(0, min(100, score))
    label = 'Testable' if score >= 70 else 'Needs Clarification' if score >= 40 else 'Not Testable'
    return {'score': score, 'label': label, 'issues': issues}


def _ac_gap(jira_ids: list, jira_cache: dict, fields: dict) -> dict:
    """Check acceptance criteria quality in linked Jira tickets."""
    if not jira_ids:
        return {'status': 'N/A', 'detail': 'No Jira ticket linked'}

    brd_ac = fields.get('acceptance', '').strip()
    missing, weak, all_ac = [], [], []

    for jid in jira_ids:
        t = jira_cache.get(jid)
        if not t:
            continue
        ac = t.get('acceptance_criteria', '').strip()
        if not ac:
            missing.append(jid)
        elif len(ac) < 80:
            weak.append(jid)
        else:
            all_ac.append(ac)

    if missing:
        return {'status': 'NO_AC', 'detail': f'No acceptance criteria in: {", ".join(missing)}'}
    if weak:
        return {'status': 'WEAK_AC', 'detail': f'Very short AC in: {", ".join(weak)}'}

    if brd_ac and all_ac:
        brd_kw = {w for w in re.findall(r'\b[a-zA-Z]{3,}\b', brd_ac.lower()) if w not in _STOP}
        jira_kw = {w for w in re.findall(r'\b[a-zA-Z]{3,}\b', ' '.join(all_ac).lower()) if w not in _STOP}
        overlap = len(brd_kw & jira_kw) / len(brd_kw) if brd_kw else 1.0
        if overlap < 0.4:
            return {'status': 'MISALIGNED',
                    'detail': f'Jira AC covers only {int(overlap*100)}% of BRD AC keywords'}

    return {'status': 'OK', 'detail': 'Acceptance criteria present and aligned'}


def _brd_text(fields: dict) -> str:
    parts = []
    for k in ('what', 'functional', 'acceptance', 'to_be', 'conditions'):
        v = fields.get(k, '').strip()
        if v:
            parts.append(f"{k.upper()}: {v}")
    return '\n'.join(parts)


def _claude_analyze(items: list[dict]) -> list[dict]:
    """Batch analyze all requirements in a single Claude API call."""
    client = _get_client()

    blocks = []
    for i, item in enumerate(items):
        jira_ids = item.get('jira_ids', [])
        if not jira_ids:
            blocks.append(f"[REQ {i}] NO_JIRA — no Jira ticket linked")
            continue
        brd = item.get('brd_text', '')[:600]
        jira = item.get('jira_text', '')[:600]
        parent = item.get('parent_text', '')[:400]
        blocks.append(
            f"[REQ {i}] Jira: {', '.join(jira_ids)}\n"
            f"BRD: {brd}\n"
            f"Jira description: {jira or '(empty)'}\n"
            f"Parent Jira: {parent or '(none)'}"
        )

    prompt = (
        "You are a QA analyst checking if Jira tickets properly capture BRD requirements.\n\n"
        "For each [REQ N] below, return:\n"
        "- status: GREEN (Jira fully covers BRD), YELLOW (partial or minor gaps), "
        "RED (major gaps or contradictions with BRD or parent), NO_JIRA (no ticket)\n"
        "- issues: list of {type, detail} — types: MISSING, CONTRADICTION, PARENT_CONFLICT, INCOMPLETE\n\n"
        + '\n\n'.join(blocks) +
        "\n\nReturn ONLY a JSON array: "
        '[{"req_index":0,"status":"GREEN","issues":[]},...]\n'
        "No explanation, no markdown fences."
    )

    response = _call_with_retry(lambda: client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system="You are a requirements analyst. Return valid JSON only.",
        messages=[{"role": "user", "content": prompt}],
    ))

    raw = response.content[0].text.strip()
    # Strip code fences if present
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if m:
        raw = m.group(1)
    return json.loads(raw)


def _keyword_analyze(items: list[dict]) -> list[dict]:
    """Heuristic fallback when Claude API is unavailable."""
    results = []
    STOP = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'in',
            'on', 'at', 'to', 'of', 'for', 'with', 'this', 'that', 'will',
            'be', 'by', 'from', 'as', 'it', 'its', 'not', 'no', 'can', 'do'}

    def keywords(text: str) -> set:
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        return {w for w in words if w not in STOP}

    for i, item in enumerate(items):
        jira_ids = item.get('jira_ids', [])
        if not jira_ids:
            results.append({'req_index': i, 'status': 'NO_JIRA', 'issues': []})
            continue

        brd_kw = keywords(item.get('brd_text', ''))
        jira_kw = keywords(item.get('jira_text', '') + ' ' + item.get('parent_text', ''))

        if not brd_kw:
            results.append({'req_index': i, 'status': 'NO_JIRA', 'issues': [
                {'type': 'INCOMPLETE', 'detail': 'BRD requirement has no structured content'}
            ]})
            continue

        if not item.get('jira_text'):
            results.append({'req_index': i, 'status': 'RED', 'issues': [
                {'type': 'MISSING', 'detail': 'Jira ticket has no description'}
            ]})
            continue

        overlap = len(brd_kw & jira_kw) / len(brd_kw) if brd_kw else 0
        issues = []

        # Check acceptance criteria specifically
        ac = item.get('brd_acceptance', '')
        if ac and ac.lower() not in (item.get('jira_text', '') + item.get('parent_text', '')).lower():
            ac_kw = keywords(ac)
            ac_overlap = len(ac_kw & jira_kw) / len(ac_kw) if ac_kw else 0
            if ac_overlap < 0.4:
                issues.append({'type': 'MISSING', 'detail': f'Acceptance criteria not reflected in Jira: "{ac[:120]}..."'})

        if overlap > 0.65 and not issues:
            status = 'GREEN'
        elif overlap > 0.35:
            status = 'YELLOW'
            issues.insert(0, {'type': 'INCOMPLETE', 'detail': f'Only {int(overlap*100)}% of BRD keywords found in Jira description'})
        else:
            status = 'RED'
            issues.insert(0, {'type': 'MISSING', 'detail': f'Low coverage ({int(overlap*100)}%): many BRD requirements not reflected in Jira'})

        results.append({'req_index': i, 'status': status, 'issues': issues})

    return results


def analyze(requirements: list[dict], jira_cache: dict, parent_cache: dict) -> list[dict]:
    """
    Main entry point. Builds context for each requirement then calls
    Claude (if key available) or heuristics. Enriches every result with
    testability score and AC gap analysis.
    """
    items = []
    for req in requirements:
        jira_texts = []
        parent_texts = []
        for jid in req.get('jira_ids', []):
            ticket = jira_cache.get(jid)
            if ticket:
                jira_texts.append(ticket.get('description', ''))
                jira_texts.append(ticket.get('acceptance_criteria', ''))
                pk = ticket.get('parent_key')
                if pk:
                    parent = parent_cache.get(pk) or jira_cache.get(pk)
                    if parent:
                        parent_texts.append(parent.get('description', ''))
                        parent_texts.append(parent.get('acceptance_criteria', ''))

        fields = req.get('fields', {})
        items.append({
            'jira_ids': req.get('jira_ids', []),
            'brd_text': _brd_text(fields),
            'brd_acceptance': fields.get('acceptance', ''),
            'jira_text': ' '.join(filter(None, jira_texts))[:1200],
            'parent_text': ' '.join(filter(None, parent_texts))[:800],
            '_fields': fields,
        })

    if config.ANTHROPIC_API_KEY:
        try:
            results = _claude_analyze(items)
        except Exception as e:
            print(f"Claude analysis failed ({e}), falling back to heuristics")
            results = _keyword_analyze(items)
    else:
        results = _keyword_analyze(items)

    # Enrich every result with testability + AC gap (no API needed)
    for result in results:
        idx = result.get('req_index', 0)
        if idx < len(items):
            item = items[idx]
            result['testability'] = _testability_score(item['_fields'])
            result['ac_gap'] = _ac_gap(item['jira_ids'], jira_cache, item['_fields'])

    return results


def generate_test_scenarios(requirement: str, jira_ac: str, section: str) -> dict:
    """Generate structured test scenarios via Claude for a single BRD requirement."""
    if not config.ANTHROPIC_API_KEY:
        return None

    client = _get_client()

    prompt = (
        f"You are a Senior QA Engineer. Generate comprehensive test scenarios.\n\n"
        f"Section: {section}\n"
        f"Requirement: {requirement}\n"
        + (f"Jira Acceptance Criteria: {jira_ac}\n" if jira_ac else "") +
        "\nReturn ONLY this JSON (no markdown, no explanation):\n"
        '{"positive":[{"title":"...","steps":["..."],"expected":"..."}],'
        '"negative":[{"title":"...","steps":["..."],"expected":"..."}],'
        '"edge_cases":[{"title":"...","steps":["..."],"expected":"..."}]}'
    )

    response = _call_with_retry(lambda: client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    ))
    raw = response.content[0].text.strip()
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if m:
        raw = m.group(1)
    return json.loads(raw)
