# test-case-review — setup for a new environment

This skill folder (`SKILL.md`, `config.txt`, `scripts/`) is portable on its
own, but a few things live *outside* this folder or are specific to the
machine/workspace it was built on. If you're copying or sharing this skill
with someone else, they'll need the following before it fully works.

## 1. Files in this folder (all required, all portable)

```
SKILL.md                      # the skill instructions (no setup needed)
config.txt                    # workspace-specific settings (see below)
README.md                     # this file
scripts/post_jira_comment.py  # Step 6's Jira REST comment poster
scripts/requirements.txt      # its Python dependencies
```

Copy the whole folder as-is. Nothing in `SKILL.md` or
`scripts/post_jira_comment.py` hardcodes a username or machine-specific path
— the skill is invoked with its own base directory each time, and the
script's own location is resolved relative to itself.

## 2. Python dependencies (for Step 6's Jira comment script)

```
pip install -r scripts/requirements.txt
```

Installs `requests` and `python-dotenv`. Without these, Step 6 fails with
`ModuleNotFoundError` the first time it runs.

## 3. Jira REST credentials (for Step 6 — NOT included, must be created)

Step 6 posts Jira comments via direct REST API (the `mcp__jira__add_jira_issue_comment`
tool's project allowlist excludes PRDOPS). To do that it reuses the
`jira-dashboard` project's own credentials file, expected at:

```
<repo-root>/jira-dashboard/.env
```

(four directories up from `scripts/post_jira_comment.py` — i.e. a sibling
of the `.claude/` folder this skill lives under).

That file is **git-ignored on purpose** (it holds a personal Jira API
token) and will NOT come along when this skill is copied, shared, or
pulled from git. A new user must create their own `jira-dashboard/.env`
with:

```
JIRA_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=<a Jira API token from https://id.atlassian.com/manage-profile/security/api-tokens>
```

If this file is missing, `post_jira_comment.py` now fails with a message
explaining exactly this. To skip Step 6 instead of setting this up, set
`POST_JIRA_COMMENT=false` in `config.txt`.

## 4. config.txt — workspace-specific values to review/replace

| Key | What it is | Needs changing when... |
|-----|------------|------------------------|
| `SLACK_CHANNEL` | Default channel for the Step 7 summary post | The new user is on a different Slack workspace, or just wants a different channel |
| `DOC_FOLDER_ID` | Google Drive folder Step 5's doc is saved into, pre-shared to `Rubrik, Inc.` domain readers | The new user is outside Rubrik's Google Workspace, or wants their own folder/sharing — create a new folder, share it the way you want, and paste its ID in here |
| `POST_JIRA_COMMENT` | Toggles Step 6 on/off | Set `false` to skip Jira commenting entirely (e.g. no `.env` set up yet) |
| `POST_SLACK_NOTIFICATION` | Toggles Step 7 on/off | Set `false` to skip the Slack post entirely |

## 5. MCP tool access (not a file, but required)

The skill calls Jira, Google Drive, Confluence, and Slack MCP tools
directly (not just the REST script in Step 6). Whoever runs this skill
needs those MCP servers connected and authenticated in their own Claude
Code session — this is a per-user Claude Code setting, not something this
folder can carry with it.

## 6. If sharing via git

As of this writing, `.claude/skills/test-case-review/` is **untracked** in
this repo's git history (`git status` shows it as `??`). If you intend to
share this skill by pushing it, `git add` and commit the folder first —
copying the files to someone's machine without using git works too, and
needs nothing from this section.
