"""Docs must not drift from the code: generated spec, duplicated files, and claims we corrected during the audit."""
import re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "app"))


def test_openapi_json_matches_the_running_app():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_openapi.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, "docs/openapi.json is stale: run `python tools/gen_openapi.py`"


def test_llms_txt_copies_are_identical():
    assert (ROOT / "llms.txt").read_text() == (DOCS / "llms.txt").read_text()


def test_documented_statuses_exist_in_the_code():
    from services.uiFormat import STATUS_STYLE
    known = set(STATUS_STYLE)
    ref = (DOCS / "api-reference.md").read_text()
    section = ref[ref.index("## Message lifecycle"):]
    documented = set(re.findall(r"^\| `([a-z]+)` \|", section, re.M)) - {"status"}   # "status" is the table header
    assert documented == known


STALE = [
    r"sms:send",                       # the real scope is sms:write
    r"msg_9f3b81ca7d2e4018",           # ids are UUIDs
    r"\b5 failed (authentication|authorization)",   # the limit is 10
    r"500 Internal Server Error[^\n]*(cellular|modem|Cellular)",   # hand-off failures are 502
    r"zero-config",                    # Tailscale needs the official app, set up by the user
    r"Tailscale Mesh Connected",
    r"FileProvider`\.",                # no FileProvider is declared
]


def test_corrected_claims_do_not_come_back():
    files = [ROOT / "README.md", ROOT / "llms.txt", *DOCS.glob("*.md"), *DOCS.glob("*.txt"), DOCS / "index.html"]
    offenders = []
    for f in files:
        if f.name in ("device-test-plan.md",):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for pat in STALE:
            if re.search(pat, text):
                offenders.append((f.name, pat))
    assert not offenders, offenders


def test_tailscale_doc_matches_the_code_constants():
    from services import tailscaleSvc as T
    doc = (DOCS / "tailscale.md").read_text()
    assert "100.64.0.0/10" in doc and str(T._TS_V6) in doc
    for mode in T.BIND_MODES:
        assert mode in ("all", "tailscale", "localhost")
