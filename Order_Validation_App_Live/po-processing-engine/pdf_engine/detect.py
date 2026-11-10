"""Works out which distributor a purchase order PDF / JSON belongs to.

The JSON names its distributor outright (`Distributor_Name`, `Bill_To_Name`,
`meta.distributor`), so it is checked first. The PDF is searched for a keyword that
identifies each distributor. Anything unknown or ambiguous returns None so the caller
asks the user, rather than guessing.
"""

import json
import re

import pdfplumber

import distributors

# Distributor slug -> words that identify it, lower-case with only letters, digits and
# dots (see _squash). Matched against the JSON's name fields and the PDF's text.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "Arrow (Netherlands)": ("arrowecsb", "arrowecs", "arrownetherlands"),
    "arrow-ecs-sau": ("arrowecssau", "arrowecsspain"),
    "ADN Distribution GmbH": ("advanceddigitalnetwork", "adn.de", "adndistribution"),
    "Computer Gross spa": ("computergross",),
    "Exclusive Networks (Norway)": ("exclusivenetworksnorway", "exclusivenetworksas"),
    "exclusive-networks-south-africa": ("exclusivenetworkssouthafrica", "businessconnexion"),
    "HCL America, Inc.": ("hclamerica",),
    "Ingram Micro Canada": ("ingrammicro",),
    "Innocom Ltd": ("innocom",),
    "iValue InfoSolutions Limited": ("ivalue",),
    "Networld Corporation": ("networldcorp", "networld"),
    "NextGen Distribution Pty Ltd": ("nextgen",),
    "NOX Co.,LTD.": ("noxco", "nox.co"),
    "Carahsoft Technology Corp": ("carahsoft",),
}

# Where the JSON states the distributor, most specific first.
JSON_NAME_KEYS = ("distributorname", "distributor", "billtoname", "vendorname", "suppliername")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", str(text).lower())


def _collapse(text: str) -> str:
    """Every run of a repeated character becomes one: generated POs keep the original
    text under the new text, so some print "RRuubbrriikk" or "rrruuubbbrrriiikkk"."""
    return re.sub(r"(.)\1+", r"\1", text)


def _matches(text: str) -> list[str]:
    """Slugs whose keyword is in `text`; a slug is dropped when a longer keyword of another
    slug also matches, so 'arrowecssau' wins over the shorter 'arrowecs'."""
    plain = _squash(text)
    collapsed = _collapse(plain)
    hits: list[tuple[str, int]] = []
    for slug, words in KEYWORDS.items():
        if distributors.get(slug) is None:
            continue
        found = [w for w in words if w in plain or _collapse(w) in collapsed]
        if found:
            hits.append((slug, max(len(w) for w in found)))
    if not hits:
        return []
    best = max(length for _, length in hits)
    return [slug for slug, length in hits if length == best]


def from_json(json_text: str) -> str | None:
    try:
        data = json.loads(json_text)
    except ValueError:
        return None
    # The name fields can sit at the top level or inside purchase_order / meta.
    scopes = [data] if isinstance(data, dict) else []
    if isinstance(data, dict):
        scopes += [v for v in data.values() if isinstance(v, dict)]
    for key in JSON_NAME_KEYS:
        for scope in scopes:
            for k, v in scope.items():
                if _squash(k) == key and isinstance(v, str) and v.strip():
                    found = _matches(v)
                    if len(found) == 1:
                        return found[0]
    meta = data.get("meta") if isinstance(data, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("distributor"), str):
        found = _matches(meta["distributor"].replace("/", " ").replace("_", " "))
        if len(found) == 1:
            return found[0]
    return None


def from_pdf(path) -> str | None:
    try:
        with pdfplumber.open(path) as pdf:
            text = " ".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        return None
    found = _matches(text)
    return found[0] if len(found) == 1 else None


def detect(pdf_path=None, json_text: str | None = None) -> dict:
    """{'slug': ..., 'source': 'json' | 'pdf' | None, 'json': slug|None, 'pdf': slug|None, 'conflict': bool}"""
    from_j = from_json(json_text) if json_text else None
    from_p = from_pdf(pdf_path) if pdf_path else None
    slug = from_j or from_p
    return {
        "slug": slug,
        "source": "json" if from_j else ("pdf" if from_p else None),
        "json": from_j,
        "pdf": from_p,
        "conflict": bool(from_j and from_p and from_j != from_p),
    }
