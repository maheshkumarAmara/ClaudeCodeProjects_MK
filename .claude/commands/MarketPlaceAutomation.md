The user has provided input: $ARGUMENTS

Extract from the input:
- PROVIDER: first token (AWS/AWS_Partner/GCP_Direct/GCP_Partner/Azure/Azure_Partner)
- QUOTE: second token (keep as-is, or prepend Q- if no Q- prefix)
- TO: value after `to:` prefix
- CC: value(s) after `cc:` prefix (comma-join if multiple)
- DATA: value after `--data ` (the base64 string, or empty string if absent)

**Immediately run this exact bash command** (substitute the extracted values):

```bash
python3 /Users/Amara.Maheshkumar/Documents/ClaudeCodeProjects/.claude/commands/render_marketplace_email.py --provider PROVIDER --quote QUOTE --data DATA
```

The command outputs JSON: `{"subject":"...","html":"..."}`.

**Immediately call `send_email`** with:
- to: TO value
- cc: CC value (omit parameter if empty)
- subject: the `subject` field from JSON
- body: the `html` field from JSON
- body_type: `html`

**Then confirm** in one line: provider · quote · to · cc (if any).
