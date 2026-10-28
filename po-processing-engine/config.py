import os
from pathlib import Path

from dotenv import load_dotenv

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

# Distributor ("disti") slug -> display name.
# Each slug has a matching subfolder under data/templates/ and data/generated/.
DISTRIBUTORS = {
    "pt-synnex-metrodata-indonesia": "PT. Synnex Metrodata Indonesia",
    "pt-ecs-indo-jaya": "PT. ECS Indo Jaya",
    "hcl": "HCL POs",
    "exclusive-networks-turkey": "Exclusive Networks Turkey",
    "exclusive-networks-south-africa": "Exclusive Networks (South Africa)",
    "arrow-ecs-sau": "ARROW E.C.S., SAU",
    # Slugs for these match their data/templates/ folder names exactly.
    "ADN Distribution GmbH": "ADN Distribution GmbH",
    "Arrow (Netherlands)": "Arrow ECS BV (Netherlands)",
    "Computer Gross spa": "Computer Gross spa",
    "Exclusive Networks (Norway)": "Exclusive Networks (Norway)",
    "HCL America, Inc.": "HCL America, Inc.",
    "Ingram Micro Canada": "Ingram Micro Canada",
    "Innocom Ltd": "Innocom Ltd",
    "iValue InfoSolutions Limited": "iValue InfoSolutions Limited",
    "Networld Corporation": "Networld Corporation",
    "NextGen Distribution Pty Ltd": "NextGen Distribution Pty Ltd",
    "NOX Co.,LTD.": "NOX Co.,LTD.",
}
