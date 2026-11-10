"""Checks for tcr_flow.py. Plain asserts, no pytest needed: ~/venv/bin/python test_tcr_flow.py"""

import json
import shlex
import tempfile
import time
from datetime import datetime
from pathlib import Path

import tcr_flow as flow


def raises(fn, *args):
    try:
        fn(*args)
    except flow.InputError:
        return True
    return False


# parse_ticket: keys and URLs
assert flow.parse_ticket("PRDOPS-722") == "PRDOPS-722"
assert flow.parse_ticket("  prdops-722 ") == "PRDOPS-722"
assert flow.parse_ticket(f"https://{flow.JIRA_HOST}/browse/PRDOPS-1054") == "PRDOPS-1054"
assert flow.parse_ticket(f"https://{flow.JIRA_HOST}/browse/PRDOPS-1054?focusedCommentId=1") == "PRDOPS-1054"
assert flow.parse_ticket(f"https://{flow.JIRA_HOST}/jira/software/projects/PRDOPS/boards/1?selectedIssue=PRDOPS-9") == "PRDOPS-9"
for bad in ("", "   ", "PRDOPS", "722", "PRDOPS-", "PRDOPS-722\nrm -rf /", "PRDOPS-722; ls", "$(whoami)",
            "http://" + flow.JIRA_HOST + "/browse/PRDOPS-1",           # not https
            "https://evil.example.com/browse/PRDOPS-1",                 # wrong host
            f"https://{flow.JIRA_HOST}.evil.com/browse/PRDOPS-1",       # host suffix trick
            f"https://{flow.JIRA_HOST}/wiki/spaces/X", None, 5):
    assert raises(flow.parse_ticket, bad), bad

# clean_input / clean_text
assert flow.clean_input("PRDOPS-1", "") == {"ticket": "PRDOPS-1", "text": ""}
assert flow.clean_input("", "  a story  ") == {"ticket": None, "text": "a story"}
assert flow.clean_input("PRDOPS-1", "ctx\x00x")["text"] == "ctxx"
assert raises(flow.clean_input, "", "")
assert raises(flow.clean_input, None, None)
assert raises(flow.clean_input, "nope", "")
assert raises(flow.clean_text, "x" * (flow.MAX_TEXT_CHARS + 1))

# build_command: overrides, result path, and one intact shell argument
cmd = flow.build_command({"ticket": "PRDOPS-1", "text": ""}, False, True, None, Path("/tmp/r/result.json"))
assert cmd.startswith("/test-case-review PRDOPS-1\n")
assert "POST_JIRA_COMMENT=false" in cmd and "POST_SLACK_NOTIFICATION=true" in cmd
assert "/tmp/r/result.json" in cmd
assert shlex.split(shlex.quote(cmd)) == [cmd]
pasted_only = flow.build_command({"ticket": None, "text": "x"}, True, True, Path("/tmp/r/pasted.txt"), None)
assert pasted_only.startswith("/test-case-review Review the story") and "/tmp/r/pasted.txt" in pasted_only
assert "result.json" not in pasted_only

# config_defaults
with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "config.txt"
    cfg.write_text("# POST_JIRA_COMMENT=false\nPOST_JIRA_COMMENT=false\nPOST_SLACK_NOTIFICATION=true\n")
    assert flow.config_defaults(cfg) == {"POST_JIRA_COMMENT": False, "POST_SLACK_NOTIFICATION": True}
    cfg.write_text("SLACK_CHANNEL=x\n")
    assert flow.config_defaults(cfg) == {"POST_JIRA_COMMENT": True, "POST_SLACK_NOTIFICATION": True}
    assert flow.config_defaults(Path(tmp) / "missing.txt") == {"POST_JIRA_COMMENT": True, "POST_SLACK_NOTIFICATION": True}

# prepare_run + read_result + purge, in a temporary runs folder
with tempfile.TemporaryDirectory() as tmp:
    flow.RUNS_DIR = Path(tmp) / "runs"
    run = flow.prepare_run({"ticket": "PRDOPS-1", "text": "extra context"}, True, False, datetime(2026, 1, 2, 3, 4, 5))
    assert run["dir"].name == "20260102_030405"
    assert (run["dir"] / "pasted.txt").read_text() == "extra context"
    assert str(run["dir"] / "pasted.txt") in run["command"] and str(run["result_path"]) in run["command"]
    assert flow.read_result(run) is None                                    # not written yet

    run["result_path"].write_text("{not json")
    assert flow.read_result(run) is None                                    # unreadable
    run["result_path"].write_text(json.dumps({"status": "running"}))
    assert flow.read_result(run) is None                                    # wrong status
    run["result_path"].write_text(json.dumps({"status": "done", "doc_url": "https://docs.google.com/document/d/abc/edit",
                                              "verdict": "CONDITIONAL GO", "coverage": 67}))
    assert flow.read_result(run) == {"doc_url": "https://docs.google.com/document/d/abc/edit",
                                     "verdict": "CONDITIONAL GO", "coverage": 67}
    run["result_path"].write_text(json.dumps({"status": "done", "doc_url": "https://evil.example.com/x",
                                              "verdict": "MAYBE", "coverage": True}))
    assert flow.read_result(run) == {"doc_url": None, "verdict": None, "coverage": None}   # nothing untrusted passes

    old = flow.RUNS_DIR / "old"
    old.mkdir()
    long_ago = time.time() - 10 * 86400
    import os
    os.utime(old, (long_ago, long_ago))
    flow.purge_old_runs()
    assert not old.exists() and run["dir"].exists()

print("tcr_flow: all checks passed")
