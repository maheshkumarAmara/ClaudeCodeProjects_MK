"""Checks for the .edi support in pov_page.py. Plain asserts: ~/venv/bin/python test_pov_edi.py"""

import tempfile
from pathlib import Path

import pov_page as pp

ISA = "ISA*00*          *00*          *ZZ*DISTRIBUTOR    *ZZ*RUBRIK         *261106*1015*U*00401*000000123*0*T*>~"
GOOD = ISA + "GS*PO*D*R*20261106*1015*123*X*004010~ST*850*0001~BEG*00*SA*PO1**20261106~SE*3*0001~GE*1*123~IEA*1*000000123~"

# validate_edi
assert pp.validate_edi(GOOD.encode()) is None
assert pp.validate_edi(("﻿" + GOOD).encode("utf-8")) is None                       # BOM
assert pp.validate_edi(("\n  " + GOOD.replace("~", "~\r\n")).encode()) is None          # leading blank, line breaks
alt = GOOD.replace("*", "|")                                                            # another element separator
assert pp.validate_edi(alt.encode()) is None
for bad in (b"", b"hello world", b"%PDF-1.7 ...", b'{"qty": 1}', b"\xff\xfe\x00\x01",
            ISA.encode(),                                                              # header only: no ST*850
            GOOD.replace("ST*850", "ST*810").encode(),                                 # an invoice, not a PO
            GOOD[:50].encode()):                                                       # truncated header
    assert pp.validate_edi(bad), bad

# save_run: the uploaded name never reaches the command; order.edi, in a tool-less temp folder
class Up:
    def __init__(self, name, data): self.name, self._d, self.size = name, data, len(data)
    def getvalue(self): return self._d

with tempfile.TemporaryDirectory() as tmp:
    cfg = pp.PovConfig(skill="pov_EDI", title="t", accepts_json=False, accepts_edi=True, description="d", repo_root=Path(tmp))
    assert cfg.extra_name == "EDI"
    run = pp.save_run(cfg, Up("PO 840329.pdf", b"%PDF"), Up("01_079756758USTST_850_205466498_20261110_0110.edi", GOOD.encode()), "UAT")
    names = [p.name for p in run["files"]]
    assert names == ["po.pdf", "order.edi"], names
    assert (run["dir"] / "order.edi").read_bytes() == GOOD.encode()
    assert run["command"].startswith("/pov_EDI '") and run["command"].endswith("order.edi' Env: UAT"), run["command"]
    assert "USTST" not in run["command"]
    # EDI only (no PO): still saved
    run2 = pp.save_run(cfg, None, Up("x.edi", GOOD.encode()), "QA", now=None)
    assert [p.name for p in run2["files"]] == ["order.edi"]

    # JSON and PO-only configs are unchanged
    jcfg = pp.PovConfig(skill="povAgent", title="t", accepts_json=True, description="d", repo_root=Path(tmp))
    assert jcfg.extra_name == "JSON" and not jcfg.accepts_edi
    r = pp.save_run(jcfg, Up("a.pdf", b"x"), Up("o.json", b"{}"), "QA")
    assert [p.name for p in r["files"]] == ["po.pdf", "order.json"]
    pcfg = pp.PovConfig(skill="pov", title="t", accepts_json=False, description="d", repo_root=Path(tmp))
    assert pcfg.extra_name == ""
    r = pp.save_run(pcfg, Up("a.pdf", b"x"), Up("o.edi", GOOD.encode()), "QA")
    assert [p.name for p in r["files"]] == ["po.pdf"]            # a PO-only skill ignores a second file

print("pov_page .edi support: all checks passed")
