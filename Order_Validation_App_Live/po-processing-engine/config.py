import os
from pathlib import Path

from dotenv import load_dotenv

import distributors

BASE_DIR = Path(__file__).parent
os.chdir(BASE_DIR)

load_dotenv()

PORT = int(os.getenv("PORT", "8010"))
UPLOADS_DIR = BASE_DIR / "data" / "uploads"
TEMPLATES_DIR = BASE_DIR / "data" / "templates"
GENERATED_DIR = BASE_DIR / "data" / "generated"

# Every email address shown or printed by the engine has its domain forced to
# this value (the part before the "@" is kept) -- see sandbox_email.py.
SANDBOX_EMAIL_DOMAIN = "sandbox.com"

SALESFORCE_ORG_ALIAS = os.getenv("SALESFORCE_ORG_ALIAS", "rbkqa")

# Salesforce org aliases selectable from the UI's "Pull from Salesforce" panel,
# mapped to a short display label. Must match aliases already authenticated
# via the `sf` CLI (see `sf org list`).
SALESFORCE_ORGS = {
    "rbkqa": "QA",
    "uat-org": "UAT",
}

# Distributor ("disti") slug -> display name, in dropdown order.
# Each slug has a matching subfolder under data/templates/ and data/generated/.
# The list itself lives in distributors.py -- add new distributors there.
DISTRIBUTORS = distributors.names()
