"""Checks for golive_flow.py. Plain asserts, no pytest needed: ~/venv/bin/python test_golive_flow.py"""

import base64
import json
import os
import shlex
import tempfile
import time
from datetime import datetime
from pathlib import Path

import golive_flow as flow


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def raises(fn, *args):
    try:
        fn(*args)
    except flow.PayloadError:
        return True
    return False


MSG = "🚀 *Project — Live in Production!*\n\n• 🌟 *<@U123>*"

# valid payloads
ok = flow.clean_payload({"channel": "it-prodops-qa", "message": b64(MSG)})
assert ok == {"channels": ["it-prodops-qa"], "message": MSG, "b64": b64(MSG)}
assert flow.clean_payload({"channel": "#a, #b ,a", "message": b64("hi")})["channels"] == ["a", "b"]   # # stripped, deduped
assert flow.clean_payload({"channel": ["C012AB3CD"], "message": b64("hi")})["channels"] == ["C012AB3CD"]
assert flow.clean_payload({"channel": "x", "message": b64("a\x00b")})["message"] == "ab"
assert flow.clean_payload({"channel": "x", "message": "  " + b64("hi") + " "})["message"] == "hi"

# bad payloads
bad = [
    None, "text", [],
    {"channel": "", "message": b64("hi")},
    {"channel": "  ,  ", "message": b64("hi")},
    {"channel": "bad channel", "message": b64("hi")},
    {"channel": 'x"; rm -rf /', "message": b64("hi")},
    {"channel": "x$(whoami)", "message": b64("hi")},
    {"channel": "x\ny", "message": b64("hi")},
    {"channel": "a,b,c,d,e,f", "message": b64("hi")},              # more than MAX_CHANNELS
    {"channel": 5, "message": b64("hi")},
    {"channel": ["ok", 5], "message": b64("hi")},
    {"channel": "x"},                                                # no message
    {"channel": "x", "message": ""},
    {"channel": "x", "message": "not base64!!"},
    {"channel": "x", "message": 'abc"; ls'},
    {"channel": "x", "message": base64.b64encode(b"\xff\xfe\xfd").decode()},     # not UTF-8
    {"channel": "x", "message": b64("   \n ")},                       # empty after trim
    {"channel": "x", "message": b64("x" * (flow.MAX_MESSAGE_CHARS + 1))},
    {"channel": "x", "message": 5},
]
for payload in bad:
    assert raises(flow.clean_payload, payload), payload

# build_command: exact shape, one intact shell argument, nothing but base64/channel chars inside the quotes
cmd = flow.build_command(ok, Path("/tmp/r/result.json"))
assert cmd.startswith('/go-live-congrats --channel "it-prodops-qa" --message "' + ok["b64"] + '"\n')
assert "/tmp/r/result.json" in cmd
assert shlex.split(shlex.quote(cmd)) == [cmd]
assert flow.build_command({"channels": ["a", "b"], "b64": "aGk="}).split("\n")[0] == '/go-live-congrats --channel "a,b" --message "aGk="'

# prepare_run, read_result, purge_old_runs in a temporary runs folder
with tempfile.TemporaryDirectory() as tmp:
    flow.RUNS_DIR = Path(tmp) / "runs"
    run = flow.prepare_run(ok, datetime(2026, 1, 2, 3, 4, 5))
    assert run["dir"].name == "20260102_030405"
    assert (run["dir"] / "message.txt").read_text(encoding="utf-8") == MSG
    assert str(run["result_path"]) in run["command"] and run["channels"] == ["it-prodops-qa"]
    assert flow.read_result(run) is None                                    # not written yet

    run["result_path"].write_text("{not json")
    assert flow.read_result(run) is None
    run["result_path"].write_text(json.dumps({"status": "running"}))
    assert flow.read_result(run) is None
    run["result_path"].write_text(json.dumps({"status": "posted", "channels": ["it-prodops-qa", 5, "x"]}))
    assert flow.read_result(run) == {"status": "posted", "channels": ["it-prodops-qa", "x"], "error": None}
    run["result_path"].write_text(json.dumps({"status": "failed", "error": "e" * 1000}))
    result = flow.read_result(run)
    assert result["status"] == "failed" and len(result["error"]) == 300 and result["channels"] == []

    old = flow.RUNS_DIR / "old"
    old.mkdir()
    long_ago = time.time() - 10 * 86400
    os.utime(old, (long_ago, long_ago))
    flow.purge_old_runs()
    assert not old.exists() and run["dir"].exists()

print("golive_flow: all checks passed")
