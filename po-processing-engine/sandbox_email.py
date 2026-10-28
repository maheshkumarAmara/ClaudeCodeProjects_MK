"""Forces every email address in the engine's field values onto the sandbox domain.

Applied at the API boundary (template load, Salesforce pull, PDF generate) so
no real customer/distributor address reaches the form or a generated PDF,
whichever distributor's parser or generator produced it. The part before the
"@" is kept; only the domain is replaced. Addresses embedded in longer text
(e.g. "Reference: a@x.it + b@y.it") are rewritten in place, and the rewrite is
idempotent.
"""

import re

import config

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-]+)@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def sandbox_text(value):
    if not isinstance(value, str) or "@" not in value:
        return value
    return _EMAIL_RE.sub(lambda m: f"{m.group(1)}@{config.SANDBOX_EMAIL_DOMAIN}", value)


def sandbox_fields(fields: dict) -> dict:
    return {key: sandbox_text(value) for key, value in fields.items()}
