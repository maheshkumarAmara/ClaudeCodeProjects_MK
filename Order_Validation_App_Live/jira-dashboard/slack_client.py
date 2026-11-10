import requests
import time

from jira_client import _session as _jira_session, JIRA_URL, get_settings_value

_SLACK_API = "https://slack.com/api"

# In-memory cache: email → slack_user_id  (TTL 1 hour)
_slack_user_cache: dict = {}
_slack_user_cache_ts: dict = {}
_SLACK_USER_TTL = 3600


def _get_token() -> str:
    token = get_settings_value("slack_bot_token", "")
    if not token:
        raise ValueError("Slack bot token is not configured. Please add it in the Slack settings.")
    return token


def get_jira_user_email(account_id: str) -> str | None:
    """Fetch a Jira user's email address by accountId."""
    try:
        resp = _jira_session.get(
            f"{JIRA_URL}/rest/api/3/user",
            params={"accountId": account_id, "expand": ""},
        )
        resp.raise_for_status()
        return resp.json().get("emailAddress")
    except Exception:
        return None


def _find_slack_user_by_email(token: str, email: str) -> str | None:
    """Return Slack user ID for the given email, or None if not found."""
    now = time.monotonic()
    cached_ts = _slack_user_cache_ts.get(email, 0)
    if now - cached_ts < _SLACK_USER_TTL and email in _slack_user_cache:
        return _slack_user_cache[email]

    resp = requests.get(
        f"{_SLACK_API}/users.lookupByEmail",
        headers={"Authorization": f"Bearer {token}"},
        params={"email": email},
        timeout=10,
    )
    data = resp.json()
    if data.get("ok") and data.get("user"):
        user_id = data["user"]["id"]
        _slack_user_cache[email] = user_id
        _slack_user_cache_ts[email] = now
        return user_id

    _slack_user_cache[email] = None
    _slack_user_cache_ts[email] = now
    return None


def _open_dm_channel(token: str, user_id: str) -> str:
    """Open a DM channel with a user and return the channel ID."""
    resp = requests.post(
        f"{_SLACK_API}/conversations.open",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"users": user_id},
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"conversations.open failed: {data.get('error')}")
    return data["channel"]["id"]


def _post_message(token: str, channel: str, text: str) -> dict:
    resp = requests.post(
        f"{_SLACK_API}/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "text": text, "mrkdwn": True},
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"chat.postMessage failed: {data.get('error')}")
    return data


def send_ping_dm(account_id: str, qa_name: str, issue_key: str,
                 summary: str, jira_url: str, status: str, days: int) -> dict:
    """
    Resolve account_id → email → Slack user ID, then send a DM.
    Returns {"ok": True} or raises on failure.
    """
    token = _get_token()

    email = get_jira_user_email(account_id)
    if not email:
        raise ValueError(f"Could not retrieve email for Jira user {account_id!r}.")

    user_id = _find_slack_user_by_email(token, email)
    if not user_id:
        raise ValueError(
            f"No Slack user found for email {email!r}. "
            "Make sure the user's Jira email matches their Slack account."
        )

    message = (
        f"Hi {qa_name}! 👋\n\n"
        f"You've been pinged from the *ProdOps QA Dashboard*.\n\n"
        f"*Issue:* <{jira_url}|{issue_key}> — {summary}\n"
        f"*Current Status:* {status}   |   *Days in status:* {days}\n\n"
        f"Please provide a status update at your earliest. Thank you! 🙏"
    )

    channel = _open_dm_channel(token, user_id)
    _post_message(token, channel, message)
    return {"ok": True, "slackUserId": user_id, "email": email}
