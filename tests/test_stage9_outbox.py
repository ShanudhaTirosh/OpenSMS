"""In-app sending goes through the service queue (outbox): safety, idempotency and an end-to-end run."""
import json, os, subprocess, sys, textwrap, time
from pathlib import Path
import pytest

APP = str(Path(__file__).resolve().parent.parent / "app")
sys.path.insert(0, APP)

import services.postApi as P
from services.outbox import write_outbox, drain_outbox, OutboxRetry, outbox_dir, validate_outgoing
from services import messageSvc
from services.smsApi import SubmitResult


@pytest.fixture(autouse=True)
def cfg(tmp_path):
    d = tmp_path / "config"; d.mkdir()
    P.set_config_path(str(d))
    yield str(d)
    P.message_svc.stop()


def wait_status(mid, wanted, secs=5):
    t0 = time.time()
    while time.time() - t0 < secs:
        m = P.db_mgr.get_message(mid)
        if m and m["status"] in wanted:
            return m
        time.sleep(0.05)
    return P.db_mgr.get_message(mid)


# ---------------- writing ----------------
def test_write_validates_like_the_api(cfg):
    for bad_number, bad_text in [("abc", "hi"), ("", "hi"), ("+94771234567", ""), ("+94771234567", "   "), ("+94771234567", "x" * 1601)]:
        with pytest.raises(ValueError):
            write_outbox(cfg, bad_number, bad_text)
    assert not os.path.exists(outbox_dir(cfg)) or os.listdir(outbox_dir(cfg)) == []
    mid = write_outbox(cfg, "+94 77 123-4567", "hello")
    payload = json.load(open(os.path.join(outbox_dir(cfg), f"{mid}.json")))
    assert payload["number"].replace(" ", "").replace("-", "") == "+94771234567" and payload["text"] == "hello"   # formatting is cleaned at send time, as in the API
    assert validate_outgoing("+94771234567", "ok")[2] is None
    assert validate_outgoing("zz", "ok")[2]                       # an explanation, not an exception


# ---------------- draining ----------------
def test_drain_consumes_and_removes_items(cfg):
    ids = [write_outbox(cfg, "+94771234567", f"m{i}") for i in range(3)]
    seen = []
    assert drain_outbox(cfg, lambda p: seen.append(p["id"])) == 3
    assert sorted(seen) == sorted(ids) and os.listdir(outbox_dir(cfg)) == []

def test_partial_files_are_ignored_and_malformed_ones_quarantined(cfg):
    os.makedirs(outbox_dir(cfg), exist_ok=True)
    Path(outbox_dir(cfg), "x.123.4.tmp").write_text('{"id": "half')               # an in-progress atomic write
    Path(outbox_dir(cfg), "broken.json").write_text("{not json")
    Path(outbox_dir(cfg), "list.json").write_text("[1,2]")
    seen = []
    assert drain_outbox(cfg, seen.append) == 0 and seen == []
    names = sorted(os.listdir(outbox_dir(cfg)))
    assert names == ["broken.bad", "list.bad", "x.123.4.tmp"]                      # nothing retried forever, nothing lost silently

def test_retry_keeps_the_file_and_order(cfg):
    write_outbox(cfg, "+94771234567", "first"); time.sleep(0.01); write_outbox(cfg, "+94771234567", "second")
    calls = []
    def handler(p):
        calls.append(p["text"])
        raise OutboxRetry()
    assert drain_outbox(cfg, handler) == 0
    assert calls == [calls[0]] and len(os.listdir(outbox_dir(cfg))) == 2          # stopped at the first, kept both
    assert drain_outbox(cfg, lambda p: None) == 2

def test_handler_exception_quarantines_only_that_item(cfg):
    write_outbox(cfg, "+94771234567", "boom"); time.sleep(0.01); write_outbox(cfg, "+94771234567", "fine")
    seen = []
    def handler(p):
        if p["text"] == "boom":
            raise RuntimeError("bad item")
        seen.append(p["text"])
    assert drain_outbox(cfg, handler) == 1 and seen == ["fine"]
    assert sorted(n.rsplit(".", 1)[1] for n in os.listdir(outbox_dir(cfg))) == ["bad"]


# ---------------- acceptance into the pipeline ----------------
def test_accepted_message_flows_through_the_normal_lifecycle(cfg):
    mid = write_outbox(cfg, "+94771234567", "from the app")
    assert drain_outbox(cfg, P.accept_local_message) == 1
    m = wait_status(mid, {"sent", "failed"})
    assert m["status"] == "sent" and m["provider"] == "simulated" and m["recipient"] == "+94771234567"
    assert P.db_mgr.get_parts(mid)[0]["sent_ok"] == 1                              # receipts bookkeeping exists

def test_crash_between_accept_and_file_removal_never_sends_twice(cfg):
    calls = []
    class Counting:
        name = "android"; supports_receipts = True
        def submit(self, msg_id, phone, text, sim_slot=-1):
            calls.append(msg_id); return SubmitResult(True, parts=1)
    P.message_svc.provider = Counting()
    mid = write_outbox(cfg, "+94771234567", "once")
    path = os.path.join(outbox_dir(cfg), f"{mid}.json")
    payload = json.load(open(path))
    P.accept_local_message(payload)                                                # accepted ...
    wait_status(mid, {"submitted"})
    assert os.path.exists(path)                                                    # ... but the file was never removed (crash)
    assert drain_outbox(cfg, P.accept_local_message) == 1                          # restart: file is seen again
    time.sleep(0.3)
    assert calls == [mid] and P.db_mgr.count_messages() == 1                       # still exactly one send, one row

def test_inactive_sim_becomes_a_failed_row_with_the_reason(cfg):
    class Never:
        name = "android"; supports_receipts = True
        def submit(self, *a, **k): raise AssertionError("must not be called")
    P.message_svc.provider = Never()
    mid = write_outbox(cfg, "+94771234567", "x", sim_slot=7)
    assert drain_outbox(cfg, P.accept_local_message) == 1
    m = P.db_mgr.get_message(mid)
    assert m["status"] == "failed" and "SIM slot 7" in m["carrier_error"]

def test_full_queue_leaves_the_file_for_a_later_pass(cfg, monkeypatch):
    monkeypatch.setattr(messageSvc, "QUEUE_MAX", 0)
    mid = write_outbox(cfg, "+94771234567", "later")
    assert drain_outbox(cfg, P.accept_local_message) == 0
    assert os.path.exists(os.path.join(outbox_dir(cfg), f"{mid}.json")) and P.db_mgr.count_messages() == 0
    monkeypatch.setattr(messageSvc, "QUEUE_MAX", 1000)
    assert drain_outbox(cfg, P.accept_local_message) == 1 and P.db_mgr.count_messages() == 1

def test_foreign_or_bad_ids_cannot_collide_with_existing_messages(cfg):
    existing = P.db_mgr.create_message("+94770000001", "old", status="delivered", provider="android")
    assert drain_outbox(cfg, P.accept_local_message) == 0
    os.makedirs(outbox_dir(cfg), exist_ok=True)
    Path(outbox_dir(cfg), "x.json").write_text(json.dumps({"id": "not-a-uuid", "number": "+94771234567", "text": "hi"}))
    assert drain_outbox(cfg, P.accept_local_message) == 1                          # bad id -> a fresh uuid, not a crash
    assert P.db_mgr.get_message(existing)["status"] == "delivered"                 # untouched
    assert P.db_mgr.count_messages() == 2


# ---------------- end to end through the real service loop ----------------
LOOP = textwrap.dedent('''
    import sys, json, time, threading, uuid
    sys.path.insert(0, %r)
    import services.appSvc as A
    from services.outbox import write_outbox
    from services.dbMgr import DatabaseManager
    threading.Thread(target=A.app_service_thread, daemon=True).start()
    time.sleep(1.0)
    ids = [write_outbox(A.config_dir, "+94771234567", f"e2e {i}") for i in range(3)]
    db = DatabaseManager.get_instance(A.config_dir)
    t0 = time.time(); out = {}
    while time.time() - t0 < 12:
        out = {i: (db.get_message(i) or {}).get("status") for i in ids}
        if all(v == "sent" for v in out.values()): break
        time.sleep(0.1)
    import os
    left = [n for n in os.listdir(os.path.join(A.config_dir, "outbox"))]
    print("RESULT" + json.dumps({"statuses": list(out.values()), "left": left, "took": round(time.time() - t0, 2)}))
''' % APP)


def test_service_loop_delivers_in_app_messages_end_to_end(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path), "OPENSMS_ALLOW_SIMULATION": "1"}
    r = subprocess.run([sys.executable, "-c", LOOP], capture_output=True, text=True, env=env, timeout=90, cwd=tmp_path)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    assert line, r.stdout + r.stderr
    out = json.loads(line[0][6:])
    assert out["statuses"] == ["sent", "sent", "sent"] and out["left"] == [], out
