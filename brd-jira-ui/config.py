import os
from pathlib import Path
from dotenv import load_dotenv

# Load from local .env first, then jira-dashboard/.env as fallback
_here = Path(__file__).parent
load_dotenv(_here / '.env')
if not os.getenv('JIRA_URL'):
    load_dotenv(_here.parent / 'jira-dashboard' / '.env')

JIRA_URL        = os.getenv('JIRA_URL', '').rstrip('/')
JIRA_EMAIL      = os.getenv('JIRA_EMAIL', '')
JIRA_API_TOKEN  = os.getenv('JIRA_API_TOKEN', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
GDRIVE_TOKEN_FILE = Path.home() / '.gdrive-mcp-token.json'
# Optional: paste any valid Google access token with drive.readonly scope.
# Get one via: gcloud auth print-access-token  (if gcloud is installed)
# or copy from the MCP server logs. Overrides the token file when set.
GOOGLE_ACCESS_TOKEN = os.getenv('GOOGLE_ACCESS_TOKEN', '')

def validate():
    missing = []
    if not JIRA_URL:       missing.append('JIRA_URL')
    if not JIRA_EMAIL:     missing.append('JIRA_EMAIL')
    if not JIRA_API_TOKEN: missing.append('JIRA_API_TOKEN')
    if missing:
        raise RuntimeError(f"Missing config: {', '.join(missing)}. Add to brd-jira-ui/.env")
