"""Stage 6: presentation logic for the Messages / API screens (no Kivy needed)."""
import datetime, sys, time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from services import uiFormat as U
from services.dbMgr import DatabaseManager


@pytest.fixture()
def db(tmp_path):
    return DatabaseManager(str(tmp_path / "ui.db"))


def test_every_status_has_a_distinct_label_and_help():
    labels = set()
    for s in ("queued", "submitted", "sent", "delivered", "failed", "unknown"):
        i = U.status_info(s)
        assert i["label"] and i["help"] and i["icon"] and len(i["color"]) == 4
        labels.add(i["label"])
    assert len(labels) == 6
    assert U.status_info("weird")["label"] == "Weird"          # never crashes on unexpected data
    assert U.status_info(None)["label"] == "?"

def test_sent_help_does_not_claim_delivery():
    assert "report" in U.status_info("sent")["help"].lower()
    assert "confirmed" in U.status_info("delivered")["help"].lower()

def test_format_time_buckets():
    now = datetime.datetime(2026, 10, 23, 15, 0).astimezone()
    ts = lambda **kw: (now - datetime.timedelta(**kw)).timestamp()
    assert U.format_time(ts(minutes=30), now) == "Today 14:30"
    assert U.format_time(ts(days=1), now).startswith("Yesterday ")
    assert U.format_time(ts(days=20), now).split()[1] == "Oct" or U.format_time(ts(days=20), now).split()[1] == "Sep"
    assert U.format_time(ts(days=400), now).split()[-1] == "2025"
    assert U.format_time(None) == "-" and U.format_time(0) == "-"

def test_shorten_collapses_whitespace_and_truncates():
    assert U.shorten("a\n\n b   c") == "a b c"
    out = U.shorten("x" * 200, 20)
    assert len(out) == 20 and out.endswith("\u2026")

def test_parts_summary():
    assert U.parts_summary({}, []) == "-"
    msg = {"parts_expected": 3}
    parts = [{"sent_ok": 1, "delivery": "delivered"}, {"sent_ok": 1, "delivery": None}, {"sent_ok": 0, "delivery": None}]
    s = U.parts_summary(msg, parts)
    assert s == "3 parts: 2/3 sent, 1/3 delivered, 1 failed"
    assert U.parts_summary({"parts_expected": 1}, [{"sent_ok": 1}]) == "1 part: 1/1 sent, 0/1 delivered"

def test_describe_message_never_invents_delivery():
    base = {"id": "m1", "recipient": "+94771234567", "status": "sent", "created_at": time.time(), "updated_at": time.time(),
            "delivered_at": None, "encoding": "GSM-7", "segments": 1, "sim_slot": -1, "provider": "android", "carrier_error": None}
    rows = dict(U.describe_message(base, []))
    assert rows["Delivered at"] == "Not confirmed" and rows["SIM"] == "Default" and "Reason" not in rows
    failed = dict(U.describe_message({**base, "status": "failed", "carrier_error": "Radio is off"}, []))
    assert failed["Reason"] == "Radio is off"
    sim = dict(U.describe_message({**base, "provider": "simulated", "sim_slot": 1}, []))
    assert "nothing was sent" in sim["Provider"] and sim["SIM"] == "Slot 2"

def test_fetch_messages_paging_filter_and_search(db):
    for i in range(30):
        db.create_message(f"+9477000{i:04d}", f"hello {i}", status="sent" if i % 2 else "failed")
    p1 = U.fetch_messages(db, offset=0, limit=10)
    assert len(p1["rows"]) == 10 and p1["total"] == 30 and p1["has_more"] and p1["range_text"] == "Showing 10 of 30"
    p3 = U.fetch_messages(db, offset=20, limit=10)
    assert not p3["has_more"] and p3["range_text"] == "Showing 30 of 30"
    assert U.fetch_messages(db, status="failed")["total"] == 15
    assert U.fetch_messages(db, status="bogus")["total"] == 30            # unknown filter -> all
    assert U.fetch_messages(db, search="hello 7")["total"] == 1
    assert U.fetch_messages(db, search="%")["total"] == 0                 # wildcard is literal
    empty = U.fetch_messages(db, search="nothing-matches")
    assert empty["rows"] == [] and empty["range_text"] == "No messages" and not empty["has_more"]

def test_key_rows_and_scope_text(db):
    raw = "osms_ui_test_key_0123456789abcdef"
    db.add_api_key(raw, "Home server", ["sms:write", "sms:read"])
    db.add_api_key("osms_admin_key_0123456789abcdef", "Ops", ["admin"])
    keys = {k["name"]: U.key_row(k) for k in db.list_api_keys()}
    assert keys["Home server"]["scopes"] == "Send, Read" and keys["Home server"]["state"] == "Active"
    assert keys["Home server"]["last_used"] == "Never used" and keys["Ops"]["scopes"] == "Admin"
    db.verify_api_key(raw)                                                # records last use
    kid = next(k["id"] for k in db.list_api_keys() if k["name"] == "Home server")
    db.revoke_api_key(kid)
    after = {k["name"]: U.key_row(k) for k in db.list_api_keys()}
    assert after["Home server"]["state"] == "Revoked" and not after["Home server"]["active"]
    assert after["Home server"]["last_used"].startswith(("Today", "Yesterday"))
    assert "key_hash" not in after["Home server"] and raw not in str(after)   # nothing secret reaches the UI model
    assert U.scopes_text([]) == "No scopes" and U.scopes_text(["x"]) == "x"

def test_key_name_validation():
    assert U.valid_key_name("") and U.valid_key_name("   ") and U.valid_key_name("x" * 65)
    assert U.valid_key_name("CI server") is None
