"""Stage 4: message lifecycle, receipts, queue, SIM validation, segmentation (mock provider only)."""
import sys, time, threading
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import services.postApi as P
from services import authSvc, messageSvc
from services.messageSvc import resolve_status, MessageService
from services.smsApi import SubmitResult, calculate_sms_segments
from services.smsReceipts import classify_tp_status, describe_sent_result
from fastapi.testclient import TestClient

client = TestClient(P.app)
SMS = {"number": "+94771234567", "text": "hello"}


class MockProvider:
    """Behaves like the Android provider: hands off, then results arrive later as receipts."""
    name = "android"
    supports_receipts = True

    def __init__(self, parts=1, fail_numbers=(), delay=0.0, during_submit=None):
        self.parts, self.fail_numbers, self.delay, self.during_submit = parts, set(fail_numbers), delay, during_submit
        self.calls = []

    def submit(self, msg_id, phone, text, sim_slot=-1):
        self.calls.append((msg_id, phone))
        if self.delay:
            time.sleep(self.delay)
        if phone in self.fail_numbers:
            return SubmitResult(False, error="Invalid destination")
        if self.during_submit:
            self.during_submit(msg_id)            # receipt arriving before the worker's bookkeeping
        return SubmitResult(True, parts=self.parts)


@pytest.fixture(autouse=True)
def cfg(tmp_path):
    d = tmp_path / "config"; d.mkdir()
    P.set_config_path(str(d))
    authSvc.FAILED_AUTH_ATTEMPTS.clear(); authSvc.reset_send_limiter()
    yield
    P.message_svc.stop()


def H(k, **x): return {"Authorization": f"Bearer {k}", **x}
def use(provider): P.message_svc.provider = provider; return provider
def svc(): return P.message_svc
def row(mid): return P.db_mgr.get_message(mid)
def send(k, body=SMS, **hdr): return client.post("/sms/", json=body, headers=H(k, **hdr))


# ---------------- pure state machine ----------------
def part(i, sent=None, delivery=None, err=None): return {"part": i, "sent_ok": sent, "sent_error": err, "delivery": delivery}

@pytest.mark.parametrize("current,expected,parts,want", [
    ("submitted", 1, [], "submitted"),
    ("submitted", 1, [part(0, sent=1)], "sent"),
    ("submitted", 3, [part(0, 1), part(1, 1)], "submitted"),                    # one part still unknown
    ("submitted", 3, [part(i, 1) for i in range(3)], "sent"),
    ("sent", 3, [part(0, 1, "delivered"), part(1, 1), part(2, 1)], "sent"),     # partial delivery is not delivered
    ("sent", 2, [part(0, 1, "delivered"), part(1, 1, "delivered")], "delivered"),
    ("submitted", 1, [part(0, None, "delivered")], "delivered"),                 # report arrived before sent receipt
    ("sent", 1, [part(0, 1, "pending")], "sent"),
    ("submitted", 2, [part(0, 1), part(1, 0, err="No cellular service")], "failed"),
    ("sent", 1, [part(0, 1, "failed")], "failed"),
    ("delivered", 1, [part(0, 1, "delivered")], "delivered"),
    ("failed", 1, [part(0, 1, "delivered")], "failed"),                          # terminal, never resurrected
    ("submitted", None, [part(0, 1)], "submitted"),                              # part count not known yet
])
def test_resolve_status(current, expected, parts, want):
    assert resolve_status(current, expected, parts)[0] == want

def test_failed_status_carries_the_radio_error():
    assert resolve_status("submitted", 1, [part(0, 0, err="Radio is off")]) == ("failed", "Radio is off")

def test_tp_status_and_sent_code_mapping():
    assert classify_tp_status(0x00) == "delivered" and classify_tp_status(0x1F) == "delivered"
    assert classify_tp_status(0x20) == "pending" and classify_tp_status(0x3F) == "pending"
    assert classify_tp_status(0x40) == "failed" and classify_tp_status(0x7F) == "failed"
    assert classify_tp_status(-1) == "unknown" and classify_tp_status(None) == "unknown"
    assert describe_sent_result(-1) == (True, None)
    assert describe_sent_result(2) == (False, "Radio is off (airplane mode?)")
    assert describe_sent_result(4)[0] is False and "service" in describe_sent_result(4)[1]
    assert "999" in describe_sent_result(999)[1]


# ---------------- end-to-end lifecycle ----------------
def test_lifecycle_submitted_sent_delivered():
    k = P.generate_new_api_key(); use(MockProvider())
    r = send(k)
    assert r.status_code == 200 and r.json()["status"] == "submitted" and r.json()["delivery_confirmed"] is False
    mid = r.json()["id"]
    assert row(mid)["status"] == "submitted" and row(mid)["delivered_at"] is None
    svc().on_receipt("sent", mid, 0, True, None, None)
    assert row(mid)["status"] == "sent" and row(mid)["delivered_at"] is None
    svc().on_receipt("delivered", mid, 0, None, None, "delivered")
    d = client.get(f"/sms/{mid}", headers=H(k)).json()
    assert d["status"] == "delivered" and d["delivered_at"] is not None and d["delivery_confirmed"] is True
    assert d["parts"][0]["delivery"] == "delivered" and d["provider"] == "android"

def test_multipart_needs_every_part():
    k = P.generate_new_api_key(); use(MockProvider(parts=3))
    mid = send(k, {**SMS, "text": "x" * 400}).json()["id"]
    svc().on_receipt("sent", mid, 0, True, None, None); svc().on_receipt("sent", mid, 2, True, None, None)
    assert row(mid)["status"] == "submitted"
    svc().on_receipt("sent", mid, 1, True, None, None)
    assert row(mid)["status"] == "sent"
    for i in (0, 1):
        svc().on_receipt("delivered", mid, i, None, None, "delivered")
    assert row(mid)["status"] == "sent" and row(mid)["delivered_at"] is None
    svc().on_receipt("delivered", mid, 2, None, None, "delivered")
    assert row(mid)["status"] == "delivered"

def test_radio_failure_marks_failed_with_reason():
    k = P.generate_new_api_key(); use(MockProvider())
    mid = send(k).json()["id"]
    svc().on_receipt("sent", mid, 0, False, "Radio is off (airplane mode?)", None)
    m = row(mid)
    assert m["status"] == "failed" and "Radio is off" in m["carrier_error"] and m["delivered_at"] is None

def test_unknown_or_pending_delivery_reports_never_mark_delivered():
    k = P.generate_new_api_key(); use(MockProvider())
    mid = send(k).json()["id"]
    svc().on_receipt("sent", mid, 0, True, None, None)
    svc().on_receipt("delivered", mid, 0, None, None, "unknown")     # no PDU
    svc().on_receipt("delivered", mid, 0, None, None, "pending")
    assert row(mid)["status"] == "sent"
    svc().on_receipt("delivered", mid, 0, None, None, "failed")
    assert row(mid)["status"] == "failed"

def test_receipt_arriving_during_submit_is_not_lost():
    k = P.generate_new_api_key()
    use(MockProvider(during_submit=lambda mid: svc().on_receipt("sent", mid, 0, True, None, None)))
    r = send(k)
    assert r.status_code == 200 and row(r.json()["id"])["status"] == "sent"

def test_provider_rejection_returns_502_and_marks_failed():
    k = P.generate_new_api_key(); use(MockProvider(fail_numbers={"+94771234567"}))
    r = send(k)
    assert r.status_code == 502 and r.json()["error"]["code"] == "delivery_failed"
    assert "Invalid destination" in r.json()["detail"]
    m = P.db_mgr.get_messages(limit=1)[0]
    assert m["status"] == "failed" and m["carrier_error"] == "Invalid destination"

def test_batch_reports_each_message_individually():
    k = P.generate_new_api_key(); use(MockProvider(fail_numbers={"+94770000002"}))
    body = {"messages": [{"number": "+94770000001", "text": "a"}, {"number": "+94770000002", "text": "b"},
                         {"number": "+94770000003", "text": "c"}]}
    j = client.post("/sms/batch/", json=body, headers=H(k)).json()
    assert (j["total"], j["successful"], j["failed"]) == (3, 2, 1)
    assert [r["status"] for r in j["results"]] == ["submitted", "failed", "submitted"]
    assert j["results"][1]["error"] == "Invalid destination"


# ---------------- queue behaviour ----------------
def test_slow_provider_gives_202_then_completes(monkeypatch):
    monkeypatch.setattr(P, "SUBMIT_WAIT_SECONDS", 0.2)
    k = P.generate_new_api_key(); use(MockProvider(delay=0.8))
    r = send(k)
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["stat"] is True
    mid = r.json()["id"]
    for _ in range(40):
        if row(mid)["status"] == "submitted": break
        time.sleep(0.1)
    assert row(mid)["status"] == "submitted"

def test_event_loop_is_not_blocked_by_a_slow_send():
    k = P.generate_new_api_key(); use(MockProvider(delay=1.0))
    t = threading.Thread(target=lambda: send(k)); t.start()
    time.sleep(0.3)
    t0 = time.time(); r = client.get("/health/"); took = time.time() - t0
    t.join()
    assert r.status_code == 200 and took < 0.5

def test_queue_full_returns_503_and_stores_nothing(monkeypatch):
    k = P.generate_new_api_key(); use(MockProvider())
    monkeypatch.setattr(messageSvc, "QUEUE_MAX", 2)
    body = {"messages": [SMS, SMS, SMS]}
    r = client.post("/sms/batch/", json=body, headers=H(k))
    assert r.status_code == 503 and r.json()["error"]["code"] == "queue_full" and "Retry-After" in r.headers
    assert P.db_mgr.count_messages() == 0

def test_restart_recovers_queued_and_flags_ambiguous_messages():
    qid = P.db_mgr.create_message("+94770000009", "was queued", status="queued", provider="android")
    sid = P.db_mgr.create_message("+94770000008", "was sending", status="sending", provider="android")
    mock = MockProvider()
    s2 = MessageService(P.db_mgr, mock, pacing=0); s2.start()
    for _ in range(40):
        if P.db_mgr.get_message(qid)["status"] == "submitted": break
        time.sleep(0.05)
    s2.stop()
    assert P.db_mgr.get_message(qid)["status"] == "submitted" and mock.calls[0][1] == "+94770000009"
    ambiguous = P.db_mgr.get_message(sid)
    assert ambiguous["status"] == "unknown" and "may or may not" in ambiguous["carrier_error"]
    assert len(mock.calls) == 1            # the ambiguous message is NOT re-sent

def test_watchdog_only_for_real_provider():
    k = P.generate_new_api_key(); use(MockProvider())
    mid = send(k).json()["id"]
    assert svc().run_watchdog(now=time.time()) == 0                       # not old enough
    assert svc().run_watchdog(now=time.time() + 3600) == 1
    assert row(mid)["status"] == "unknown"
    sim = MessageService(P.db_mgr, P.get_provider(), pacing=0)            # simulated: never guesses
    assert sim.run_watchdog(now=time.time() + 3600) == 0

def test_metrics_count_in_flight_messages():
    k = P.generate_new_api_key(); use(MockProvider())
    send(k)
    assert P.db_mgr.get_metrics()["queue_depth"] == 1                      # 'submitted' is still in flight


# ---------------- validation / safety ----------------
def test_invalid_sim_slot_rejected_before_anything_is_stored():
    k = P.generate_new_api_key(); mock = use(MockProvider())
    r = send(k, {**SMS, "sim_slot": 7})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_sim_slot"
    r = client.post("/sms/batch/", json={"messages": [SMS, {**SMS, "sim_slot": 7}]}, headers=H(k))
    assert r.status_code == 422
    assert P.db_mgr.count_messages() == 0 and mock.calls == []
    assert send(k, {**SMS, "sim_slot": 0}).status_code == 200

def test_simulation_is_refused_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("OPENSMS_ALLOW_SIMULATION", raising=False)
    k = P.generate_new_api_key()
    r = send(k)
    assert r.status_code == 502 and "simulation is disabled" in r.json()["detail"]
    monkeypatch.setenv("OPENSMS_ALLOW_SIMULATION", "1")
    r = send(k)
    assert r.status_code == 200
    assert row(r.json()["id"])["provider"] == "simulated"                 # never mistaken for a real send


# ---------------- segmentation ----------------
@pytest.mark.parametrize("text,enc,segs,units", [
    ("", "GSM-7", 0, 0),
    ("Hello world!", "GSM-7", 1, 12),
    ("A" * 160, "GSM-7", 1, 160),
    ("A" * 161, "GSM-7", 2, 161),
    ("A" * 306, "GSM-7", 2, 306),
    ("A" * 307, "GSM-7", 3, 307),
    ("€" * 10, "GSM-7", 1, 20),                      # extension char: GSM-7, 2 septets each
    ("[" * 81, "GSM-7", 2, 162),                      # 81 x 2 septets > 160
    ("`", "UCS-2 (Unicode)", 1, 1),                  # backtick is not in the GSM alphabet
    ("😀" * 35, "UCS-2 (Unicode)", 1, 70),            # emoji = 2 UTF-16 units
    ("😀" * 36, "UCS-2 (Unicode)", 2, 72),
    ("ශ්‍රී" * 20, "UCS-2 (Unicode)", 2, None),
])
def test_segment_estimates(text, enc, segs, units):
    r = calculate_sms_segments(text)
    assert r["encoding"] == enc and r["segments"] == segs
    if units is not None:
        assert r["units"] == units

def test_extension_char_is_not_split_across_segments():
    text = "A" * 152 + "€"      # 152 + 2 = 154 > 153 so the euro moves to segment 2 (but total 154 <= 160 -> single)
    assert calculate_sms_segments(text)["segments"] == 1
    text = "A" * 160 + "€"      # multi-part: 160 'A' -> seg 1 (153) + 7 'A' + 2 = 9 -> 2 segments
    assert calculate_sms_segments(text)["segments"] == 2
    text = "A" * 152 + "€" + "A" * 200
    r = calculate_sms_segments(text)
    assert r["units"] == 354 and r["segments"] == 3


# ---------------- SIM validation must not guess when Android cannot be asked ----------------
def test_sim_validation_refuses_to_guess_without_the_phone_permission(monkeypatch):
    from services import smsApi
    monkeypatch.setattr(smsApi, "platform", "android")
    monkeypatch.setattr(smsApi, "autoclass", object())
    placeholder = [{"slot": 0, "placeholder": True}]
    monkeypatch.setattr(smsApi, "get_active_sims_with_status", lambda: (placeholder, False))
    smsApi.validate_sim_slot(-1)                                  # default SIM never needs the SIM list
    with pytest.raises(ValueError, match="Phone permission"):
        smsApi.validate_sim_slot(1)
    with pytest.raises(ValueError, match="Phone permission"):
        smsApi.validate_sim_slot(0)                               # a placeholder cannot confirm even slot 0

def test_sim_validation_with_a_real_sim_list(monkeypatch):
    from services import smsApi
    monkeypatch.setattr(smsApi, "platform", "android")
    monkeypatch.setattr(smsApi, "autoclass", object())
    monkeypatch.setattr(smsApi, "get_active_sims_with_status", lambda: ([{"slot": 0}, {"slot": 1}], True))
    smsApi.validate_sim_slot(0); smsApi.validate_sim_slot(1)
    with pytest.raises(ValueError, match="not active"):
        smsApi.validate_sim_slot(2)
    monkeypatch.setattr(smsApi, "get_active_sims_with_status", lambda: ([], True))   # answered: no SIM inserted
    with pytest.raises(ValueError, match="not active"):
        smsApi.validate_sim_slot(0)

def test_sims_endpoint_reports_reliability():
    k = P.generate_new_api_key()
    j = client.get("/system/sims/", headers=H(k)).json()
    assert j["reliable"] is False and j["sims"][0]["placeholder"] is True      # off-device: only a placeholder exists
