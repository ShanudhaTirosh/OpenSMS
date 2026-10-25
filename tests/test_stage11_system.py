"""System diagnostics, history maintenance, and receipts being registered only by the service process."""
import sys, time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from services import diagnostics as D
from services.dbMgr import DatabaseManager


def rows(sections, label):
    return [r for s in sections for r in s["rows"] if r["label"] == label]


def healthy():
    return {"android": True, "service_alive": True, "heartbeat_age": 1.2, "server": "started", "host": "100.1.2.3", "port": 9292,
            "bind": "tailscale", "server_desired": "start", "wakelock_setting": True,
            "diag": {"receipts": True, "wakelock": True, "queue": 0},
            "perm_sms": True, "perm_phone": True, "sims": {"reliable": True, "count": 2},
            "tailscale": {"state": "connected", "ip": "100.1.2.3"}, "local_ip": "192.168.1.5",
            "db": {"messages": 12, "active_keys": 2, "schema": 2, "size_bytes": 200_000}, "version": "0.4.0",
            "repo": "ShanudhaTirosh/OpenSMS", "platform_text": "Android 14 (API 34), Python 3.11"}


def test_healthy_system_reports_ok():
    s = D.build_sections(healthy())
    assert D.overall_level(s) == D.OK
    assert rows(s, "Background service")[0]["level"] == D.OK
    assert rows(s, "Delivery tracking")[0]["level"] == D.OK and rows(s, "CPU wake lock")[0]["level"] == D.OK

def test_service_not_running_is_an_error_when_the_user_wanted_it_on():
    f = {**healthy(), "service_alive": False, "heartbeat_age": None, "server": None, "diag": {}}
    s = D.build_sections(f)
    assert rows(s, "Background service")[0]["level"] == D.ERROR and "Start Server" in rows(s, "Background service")[0]["hint"]
    assert rows(s, "API server")[0]["value"].startswith("Unknown")                  # never claims a state it cannot know
    assert rows(s, "Delivery tracking")[0]["level"] == D.INFO
    f["server_desired"] = "stop"
    assert rows(D.build_sections(f), "Background service")[0]["level"] == D.WARN      # stopped by the user: not an alarm

def test_receipts_missing_is_a_warning_with_the_consequence():
    f = healthy(); f["diag"] = {"receipts": False, "wakelock": True, "queue": 0}
    r = rows(D.build_sections(f), "Delivery tracking")[0]
    assert r["level"] == D.WARN and "Submitted" in r["hint"]

def test_permissions_and_sims():
    f = healthy(); f.update(perm_sms=False, perm_phone=False, sims={"reliable": False})
    s = D.build_sections(f)
    assert rows(s, "SMS permission")[0]["level"] == D.WARN and "Allow SMS" in rows(s, "SMS permission")[0]["hint"]
    assert "sim_slot" in rows(s, "Phone permission")[0]["hint"]
    assert rows(s, "SIM cards")[0]["level"] == D.WARN
    off = D.build_sections({"android": False})
    assert rows(off, "SMS permission")[0]["value"].startswith("Not applicable")      # desktop: no false alarms
    assert "Simulation" in rows(off, "SMS provider")[0]["value"]

def test_wakelock_checks_only_while_the_server_runs():
    f = healthy(); f["diag"]["wakelock"] = False
    assert rows(D.build_sections(f), "CPU wake lock")[0]["level"] == D.WARN
    f["wakelock_setting"] = False
    assert "Off" in rows(D.build_sections(f), "CPU wake lock")[0]["value"]
    f = healthy(); f["server"] = "stopped"
    assert rows(D.build_sections(f), "CPU wake lock") == []

def test_server_error_and_tailscale_mode_mismatch():
    f = healthy(); f.update(server="error", error="Could not bind 0.0.0.0:9292", tailscale={"state": "disconnected", "ip": None})
    s = D.build_sections(f)
    assert rows(s, "API server")[0]["level"] == D.ERROR and "Could not bind" in rows(s, "API server")[0]["value"]
    assert rows(s, "Mode check")[0]["level"] == D.ERROR
    assert D.overall_level(s) == D.ERROR

def test_no_active_key_is_flagged():
    f = healthy(); f["db"]["active_keys"] = 0
    r = rows(D.build_sections(f), "Active API keys")[0]
    assert r["level"] == D.WARN and "API tab" in r["hint"]

def test_report_text_contains_no_secrets():
    f = healthy()
    f["secret_probe"] = "osms_SHOULD_NEVER_APPEAR"; f["numbers"] = ["+94771234567"]; f["text"] = "private message"
    text = D.to_text(D.build_sections(f), "OpenSMS 0.4.0 diagnostics")
    assert text.startswith("OpenSMS 0.4.0 diagnostics") and "BACKGROUND" not in text and "GATEWAY" in text
    for forbidden in ("osms_", "+94771234567", "private message"):
        assert forbidden not in text
    assert "[OK] Background service" in text

def test_size_formatting():
    assert D._size(None) == "unknown" and D._size(2048) == "2 KB" and D._size(5 * 1024 * 1024) == "5.0 MB"


# ---------------- history maintenance ----------------
@pytest.fixture()
def db(tmp_path):
    return DatabaseManager(str(tmp_path / "m.db"))

def make(db, status, age_days, parts=1):
    mid = db.create_message("+94771234567", f"{status} {age_days}", status=status, provider="android")
    db.record_parts(mid, parts)
    ts = time.time() - age_days * 86400
    with db._conn() as c:
        c.execute("UPDATE messages SET created_at = ?, updated_at = ? WHERE id = ?", (ts, ts, mid))
    return mid

def test_purge_never_deletes_in_flight_messages(db):
    inflight = [make(db, s, 90) for s in ("queued", "submitted", "sending")]
    done = [make(db, s, 90) for s in ("sent", "delivered", "failed", "unknown")]
    assert db.purge_messages(None) == 4                                               # even "everything" skips in-flight
    for mid in inflight:
        assert db.get_message(mid) is not None and db.get_parts(mid)
    for mid in done:
        assert db.get_message(mid) is None and db.get_parts(mid) == []                # receipts removed with the message

def test_purge_older_than_cutoff_only(db):
    old = make(db, "sent", 45); new = make(db, "sent", 2); mid_old_failed = make(db, "failed", 31)
    removed = db.purge_messages(time.time() - 30 * 86400)
    assert removed == 2 and db.get_message(new) is not None
    assert db.get_message(old) is None and db.get_message(mid_old_failed) is None
    assert db.purge_messages(time.time() - 30 * 86400) == 0                           # idempotent

def test_purge_handles_many_rows_and_leaves_keys_alone(db):
    db.add_api_key("osms_keep_this_key_0123456789ab", "keep", ["sms:read"])
    for _ in range(1200):
        db.create_message("+94771234567", "bulk", status="sent")
    assert db.purge_messages(None) == 1200 and db.count_messages() == 0
    assert db.storage_stats()["active_keys"] == 1

def test_storage_stats(db):
    make(db, "sent", 1)
    st = db.storage_stats()
    assert st["messages"] == 1 and st["schema"] == DatabaseManager.SCHEMA_VERSION and st["size_bytes"] > 0


# ---------------- receipts only in the service process ----------------
def test_ui_process_does_not_register_the_receipt_receiver(tmp_path, monkeypatch):
    import services.postApi as P
    calls = []
    monkeypatch.setattr(P.smsReceipts, "register_receiver", lambda cb: calls.append(cb) or True)
    d = tmp_path / "ui"; d.mkdir()
    P.set_config_path(str(d), register_receipts=False)
    assert calls == []
    d2 = tmp_path / "svc"; d2.mkdir()
    P.set_config_path(str(d2))                                                         # default: the service registers
    assert len(calls) == 1
    P.message_svc.stop()
