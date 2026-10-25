"""
Regenerate docs/openapi.json from the real FastAPI app so the published spec cannot drift from the code.

    python tools/gen_openapi.py          # rewrite docs/openapi.json
    python tools/gen_openapi.py --check  # exit 1 if the file is out of date (used by the test suite)

Hand-written metadata (contact, license, servers, endpoint summaries) lives in this file.
"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("OPENSMS_ALLOW_SIMULATION", "1")

SUMMARIES = {
    ("get", "/health/"): ("Liveness probe", "No authentication required."),
    ("post", "/sms/"): ("Send one SMS", "Needs scope `sms:write`. Returns 200 after the hand-off to Android (`status` submitted/sent), 202 if still queued. `status: delivered` is the only delivery confirmation. Supports the `Idempotency-Key` header."),
    ("post", "/sms/batch/"): ("Send up to 100 SMS", "Needs scope `sms:write`. Per-message results; supports the `Idempotency-Key` header."),
    ("get", "/sms/history"): ("List messages", "Needs scope `sms:read`. Paginated with `total` and `has_more`; the trailing-slash form `/sms/history/` is also accepted."),
    ("get", "/sms/{msg_id}"): ("Get one message", "Needs scope `sms:read`. Includes per-part receipts and `delivery_confirmed`."),
    ("get", "/system/stats/"): ("Gateway statistics", "Needs scope `sms:read`."),
    ("get", "/system/sims/"): ("Active SIM slots", "Needs scope `sms:read`."),
    ("get", "/system/update/"): ("Check for app updates", "Needs scope `sms:read`."),
    ("get", "/keys/"): ("List API keys", "Needs scope `admin`. Never returns key secrets or hashes."),
    ("post", "/keys/"): ("Create an API key", "Needs scope `admin`. The secret is returned once."),
    ("delete", "/keys/{key_id}"): ("Revoke an API key", "Needs scope `admin`. A key cannot revoke itself."),
    ("get", "/llms.txt"): ("Discovery file for AI agents", "Requires a Bearer token unless the gateway runs with OPENSMS_PUBLIC_DOCS=1."),
    ("get", "/docs/markdown"): ("Markdown API reference", "Requires a Bearer token unless the gateway runs with OPENSMS_PUBLIC_DOCS=1."),
    ("post", "/control/"): ("Reserved (no-op)", "Needs scope `admin`; currently echoes its input."),
}


def build():
    from app_version import __version__
    import services.postApi as P
    spec = P.app.openapi()
    old = json.loads((ROOT / "docs" / "openapi.json").read_text())
    spec["info"] = {**old.get("info", {}), "version": __version__}
    if old.get("servers"):
        spec["servers"] = old["servers"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            hit = SUMMARIES.get((method, path))
            if hit:
                op["summary"], op["description"] = hit
    return spec


def main():
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    target = ROOT / "docs" / "openapi.json"
    if "--check" in sys.argv:
        return 0 if target.read_text() == text else 1
    target.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
