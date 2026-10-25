"""Stage 3: idempotency, schema migrations, unified error envelope, pagination totals."""
import sys, sqlite3, time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import services.postApi as P
from services import authSvc
from services.dbMgr import DatabaseManager
from fastapi.testclient import TestClient

client = TestClient(P.app)
SMS = {"number": "+94771234567", "text": "hello"}


@pytest.fixture(autouse=True)
def cfg(tmp_path):
    d = tmp_path / "config"; d.mkdir()
    P.set_config_path(str(d))
    authSvc.FAILED_AUTH_ATTEMPTS.clear(); authSvc.reset_send_limiter()
    yield d


def H(k, **extra): return {"Authorization": f"Bearer {k}", **extra}
def count(): return P.db_mgr.count_messages()


# ---------------- idempotency ----------------
def test_same_idempotency_key_sends_once_and_replays():
    k = P.generate_new_api_key()
    r1 = client.post("/sms/", json=SMS, headers=H(k, **{"Idempotency-Key": "order-1"}))
    r2 = client.post("/sms/", json=SMS, headers=H(k, **{"Idempotency-Key": "order-1"}))
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()                       # same message id returned
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert "Idempotent-Replay" not in r1.headers
    assert count() == 1


def test_without_header_behaviour_is_unchanged():
    k = P.generate_new_api_key()
    client.post("/sms/", json=SMS, headers=H(k)); client.post("/sms/", json=SMS, headers=H(k))
    assert count() == 2


def test_key_reuse_with_different_body_is_rejected():
    k = P.generate_new_api_key()
    client.post("/sms/", json=SMS, headers=H(k, **{"Idempotency-Key": "a"}))
    r = client.post("/sms/", json={**SMS, "text": "different"}, headers=H(k, **{"Idempotency-Key": "a"}))
    assert r.status_code == 422 and r.json()["error"]["code"] == "idempotency_key_reuse"
    assert count() == 1


def test_idempotency_keys_are_scoped_per_api_key():
    k1, k2 = P.generate_new_api_key("a"), P.generate_new_api_key("b")
    client.post("/sms/", json=SMS, headers=H(k1, **{"Idempotency-Key": "same"}))
    client.post("/sms/", json=SMS, headers=H(k2, **{"Idempotency-Key": "same"}))
    assert count() == 2


def test_batch_idempotent_and_does_not_consume_quota_on_replay(monkeypatch):
    monkeypatch.setattr(authSvc, "SEND_RATE_PER_MINUTE", 4)
    k = P.generate_new_api_key()
    body = {"messages": [SMS, SMS, SMS]}
    h = H(k, **{"Idempotency-Key": "batch-1"})
    assert client.post("/sms/batch/", json=body, headers=h).status_code == 200
    for _ in range(3):   # replays must not hit the 4/min limit
        assert client.post("/sms/batch/", json=body, headers=h).status_code == 200
    assert count() == 3


def test_failed_send_releases_key_so_retry_can_succeed(monkeypatch):
    k = P.generate_new_api_key()
    from services.smsApi import SubmitResult
    P.message_svc.provider.submit = lambda *a, **kw: SubmitResult(False, error="radio off")
    h = H(k, **{"Idempotency-Key": "retry-me"})
    r = client.post("/sms/", json=SMS, headers=h)
    assert r.status_code == 502 and "radio off" in r.json()["detail"]
    P.message_svc.provider.submit = lambda mid, *a, **kw: SubmitResult(True, parts=1, synthetic_sent=True)
    assert client.post("/sms/", json=SMS, headers=h).status_code == 200


def test_in_progress_key_returns_409_and_stale_one_can_be_taken_over():
    k = P.generate_new_api_key()
    kid = P.db_mgr.list_api_keys()[0]["id"]
    import hashlib, json
    h = hashlib.sha256(json.dumps(["sms", P.SmsData(**SMS).model_dump()], sort_keys=True, default=str).encode()).hexdigest()
    assert P.db_mgr.idem_begin(kid, "busy", h)[0] == "new"
    r = client.post("/sms/", json=SMS, headers=H(k, **{"Idempotency-Key": "busy"}))
    assert r.status_code == 409 and r.json()["error"]["code"] == "request_in_progress"
    assert count() == 0
    with P.db_mgr._conn() as c:   # simulate a crashed owner from 20 minutes ago
        c.execute("UPDATE idempotency SET created_at = ?", (time.time() - 1200,))
    assert client.post("/sms/", json=SMS, headers=H(k, **{"Idempotency-Key": "busy"})).status_code == 200


@pytest.mark.parametrize("bad", ["", "has space", "x" * 129, "semi;colon"])
def test_invalid_idempotency_key_format(bad):
    k = P.generate_new_api_key()
    r = client.post("/sms/", json=SMS, headers=H(k, **{"Idempotency-Key": bad}))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_idempotency_key"


# ---------------- error envelope ----------------
def test_error_envelope_is_additive():
    r = client.post("/sms/", json=SMS)
    assert r.status_code == 401
    assert isinstance(r.json()["detail"], str)                    # legacy field preserved
    assert r.json()["error"]["code"] == "unauthorized"

    k = P.generate_new_api_key()
    r = client.post("/sms/", json={"number": "abc", "text": "x"}, headers=H(k))
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)                   # legacy FastAPI shape preserved
    assert r.json()["error"]["code"] == "validation_error" and "number" in r.json()["error"]["message"]

    assert client.get("/sms/does-not-exist", headers=H(k)).json()["error"]["code"] == "not_found"
    assert client.get("/nope", headers=H(k)).json()["error"]["code"] == "not_found"


def test_rate_limit_errors_carry_retry_after(monkeypatch):
    monkeypatch.setattr(authSvc, "SEND_RATE_PER_MINUTE", 1)
    k = P.generate_new_api_key()
    client.post("/sms/", json=SMS, headers=H(k))
    r = client.post("/sms/", json=SMS, headers=H(k))
    assert r.status_code == 429 and r.json()["error"]["code"] == "send_rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


def test_insufficient_scope_code():
    P.db_mgr.add_api_key("osms_ro_stage3_0000000000000000", "ro", ["sms:read"])
    r = client.post("/sms/", json=SMS, headers=H("osms_ro_stage3_0000000000000000"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_scope"


# ---------------- pagination ----------------
def test_history_total_and_has_more():
    k = P.generate_new_api_key()
    for i in range(5):
        client.post("/sms/", json={**SMS, "text": f"m{i}"}, headers=H(k))
    j = client.get("/sms/history/?limit=2&offset=0", headers=H(k)).json()
    assert (j["count"], j["total"], j["has_more"]) == (2, 5, True)
    j = client.get("/sms/history/?limit=2&offset=4", headers=H(k)).json()
    assert (j["count"], j["total"], j["has_more"]) == (1, 5, False)
    j = client.get("/sms/history/?search=m3", headers=H(k)).json()
    assert j["total"] == 1
    assert client.get("/sms/history/?limit=500", headers=H(k)).status_code == 422


# ---------------- migrations ----------------
V040_SCHEMA = """
CREATE TABLE messages (id TEXT PRIMARY KEY, recipient TEXT NOT NULL, text TEXT NOT NULL,
  encoding TEXT DEFAULT 'GSM-7', segments INTEGER DEFAULT 1, sim_slot INTEGER DEFAULT -1,
  status TEXT DEFAULT 'queued', carrier_error TEXT DEFAULT NULL, batch_id TEXT DEFAULT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL, delivered_at REAL DEFAULT NULL);
CREATE TABLE api_keys (id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT UNIQUE NOT NULL,
  prefix TEXT NOT NULL, scopes TEXT DEFAULT '["sms:write", "sms:read"]', created_at REAL NOT NULL,
  last_used_at REAL DEFAULT NULL, is_active INTEGER DEFAULT 1);
CREATE TABLE webhooks (id TEXT PRIMARY KEY, url TEXT NOT NULL, events TEXT, secret TEXT,
  is_active INTEGER DEFAULT 1, created_at REAL NOT NULL);
"""

def test_migration_from_v040_database_preserves_data(tmp_path):
    f = tmp_path / "old.db"
    c = sqlite3.connect(f); c.executescript(V040_SCHEMA)
    c.execute("INSERT INTO messages (id, recipient, text, status, created_at, updated_at) VALUES ('m1','+1555','old msg','sent',1,1)")
    c.execute("INSERT INTO api_keys (id, name, key_hash, prefix, created_at) VALUES ('k1','legacy','h1','osms_',1)")
    c.commit(); assert c.execute("PRAGMA user_version").fetchone()[0] == 0; c.close()

    db = DatabaseManager(str(f))
    assert db.get_schema_version() == DatabaseManager.SCHEMA_VERSION
    assert db.get_message("m1")["text"] == "old msg"                # data intact
    assert db.list_api_keys()[0]["name"] == "legacy"
    assert db.idem_begin("k1", "x", "h")[0] == "new"                # new table usable
    DatabaseManager(str(f))                                          # re-open is a no-op
    assert db.get_schema_version() == DatabaseManager.SCHEMA_VERSION


def test_refuses_database_from_a_newer_version(tmp_path):
    f = tmp_path / "future.db"
    c = sqlite3.connect(f); c.executescript(V040_SCHEMA); c.execute("PRAGMA user_version = 99"); c.commit(); c.close()
    with pytest.raises(RuntimeError, match="newer"):
        DatabaseManager(str(f))


def test_concurrent_requests_with_same_key_send_once():
    from concurrent.futures import ThreadPoolExecutor
    k = P.generate_new_api_key()
    def go(_):
        c = TestClient(P.app)
        return c.post("/sms/", json=SMS, headers=H(k, **{"Idempotency-Key": "race"})).status_code
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(go, range(8)))
    assert count() == 1                       # exactly one SMS regardless of interleaving
    assert set(codes) <= {200, 409}           # others replay (200) or are told it is in progress (409)
    assert codes.count(200) >= 1
