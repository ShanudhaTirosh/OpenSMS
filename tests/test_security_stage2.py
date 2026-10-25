"""Regression tests for audit Stage 2 (security / critical fixes)."""
import os, sys, json, gc
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import services.postApi as P
from services import authSvc
from services.dbMgr import DatabaseManager
from fastapi.testclient import TestClient

client = TestClient(P.app)


@pytest.fixture(autouse=True)
def cfg(tmp_path):
    d = tmp_path / "config"; d.mkdir()
    P.set_config_path(str(d))
    authSvc.FAILED_AUTH_ATTEMPTS.clear()
    authSvc.reset_send_limiter()
    yield d


def H(key): return {"Authorization": f"Bearer {key}"}
SMS = {"number": "+94771234567", "text": "hi"}


def test_scopes_enforced_matrix():
    P.db_mgr.add_api_key("osms_ro_key_00000000000000000000", "ro", ["sms:read"])
    P.db_mgr.add_api_key("osms_wo_key_00000000000000000000", "wo", ["sms:write"])
    ro, wo = H("osms_ro_key_00000000000000000000"), H("osms_wo_key_00000000000000000000")
    assert client.post("/sms/", json=SMS, headers=ro).status_code == 403
    assert client.post("/sms/batch/", json={"messages": [SMS]}, headers=ro).status_code == 403
    assert client.post("/sms/", json=SMS, headers=wo).status_code == 200
    assert client.get("/sms/history/", headers=wo).status_code == 403
    assert client.get("/sms/history/", headers=ro).status_code == 200
    assert client.get("/system/stats/", headers=wo).status_code == 403
    assert client.get("/keys/", headers=ro).status_code == 403
    assert client.post("/control/", json={"api": "x"}, headers=wo).status_code == 403


def test_admin_implies_all_and_key_management():
    P.db_mgr.add_api_key("osms_admin_key_000000000000000000", "adm", ["admin"])
    a = H("osms_admin_key_000000000000000000")
    assert client.post("/sms/", json=SMS, headers=a).status_code == 200
    r = client.post("/keys/", json={"name": "ci", "scopes": ["sms:write"]}, headers=a)
    assert r.status_code == 201
    new_key = r.json()["key"]
    assert client.post("/sms/", json=SMS, headers=H(new_key)).status_code == 200
    listing = client.get("/keys/", headers=a).json()["keys"]
    assert all("key_hash" not in k and "key" not in k for k in listing)  # no secrets in listing
    kid = next(k["id"] for k in listing if k["name"] == "ci")
    assert client.delete(f"/keys/{kid}", headers=a).status_code == 200
    assert client.post("/sms/", json=SMS, headers=H(new_key)).status_code == 401
    # cannot revoke itself; unknown scope rejected
    me = next(k["id"] for k in listing if k["name"] == "adm")
    assert client.delete(f"/keys/{me}", headers=a).status_code == 409
    assert client.post("/keys/", json={"name": "x", "scopes": ["root"]}, headers=a).status_code == 422


def test_revoked_key_rejected_and_generate_does_not_invalidate_others():
    k1 = P.generate_new_api_key("one"); k2 = P.generate_new_api_key("two")
    assert client.get("/system/stats/", headers=H(k1)).status_code == 200   # D3: multi-key kept
    for k in P.db_mgr.list_api_keys():
        P.db_mgr.revoke_api_key(k["id"])
    assert client.get("/system/stats/", headers=H(k1)).status_code == 401
    assert client.get("/system/stats/", headers=H(k2)).status_code == 401
    assert P.get_api_keys() == {}


def test_legacy_keys_json_migrated_once_and_not_a_fallback(cfg):
    raw = "osms_legacy_key_value_123456789"
    (cfg / "keys.json").write_text(json.dumps({P.hash_api_key(raw): {"name": "old", "created_at": 1}}))
    P.set_config_path(str(cfg))
    assert client.get("/system/stats/", headers=H(raw)).status_code == 200
    assert not (cfg / "keys.json").exists() and (cfg / "keys.json.migrated").exists()
    kid = P.db_mgr.list_api_keys()[0]["id"]
    P.db_mgr.revoke_api_key(kid)
    P.set_config_path(str(cfg))  # restart: revoked key must stay revoked
    assert client.get("/system/stats/", headers=H(raw)).status_code == 401


def test_send_rate_limit_per_key(monkeypatch):
    monkeypatch.setattr(authSvc, "SEND_RATE_PER_MINUTE", 3)
    k = P.generate_new_api_key()
    for _ in range(3):
        assert client.post("/sms/", json=SMS, headers=H(k)).status_code == 200
    r = client.post("/sms/", json=SMS, headers=H(k))
    assert r.status_code == 429 and "Retry-After" in r.headers
    other = P.generate_new_api_key("other")          # limiter is per key
    assert client.post("/sms/", json=SMS, headers=H(other)).status_code == 200
    # a batch larger than the remaining quota is refused as a whole, nothing is sent
    before = len(P.db_mgr.get_messages(limit=200))
    assert client.post("/sms/batch/", json={"messages": [SMS] * 5}, headers=H(other)).status_code == 429
    assert len(P.db_mgr.get_messages(limit=200)) == before


def test_history_route_with_and_without_slash():
    k = P.generate_new_api_key()
    for path in ("/sms/history/", "/sms/history"):
        r = client.get(path, headers=H(k))
        assert r.status_code == 200 and "messages" in r.json()


def test_text_length_cap():
    k = P.generate_new_api_key()
    r = client.post("/sms/", json={"number": "+94771234567", "text": "a" * 1601}, headers=H(k))
    assert r.status_code == 422
    r = client.post("/sms/", json={"number": "+94771234567", "text": "a" * 1600}, headers=H(k))
    assert r.status_code == 200


def test_response_does_not_claim_delivery():
    k = P.generate_new_api_key()
    body = client.post("/sms/", json=SMS, headers=H(k)).json()
    assert body["stat"] is True and body["delivery_confirmed"] is False
    msg = client.get(f"/sms/{body['id']}", headers=H(k)).json()
    assert msg["status"] == "sent" and msg["delivered_at"] is None


def test_search_wildcards_are_literal(cfg):
    db = DatabaseManager(str(cfg / "s.db"))
    db.create_message("+1000000001", "alpha"); db.create_message("+1000000002", "100% sure")
    assert len(db.get_messages(search="%")) == 1
    assert len(db.get_messages(search="_")) == 0


def test_db_connections_are_closed(cfg):
    db = DatabaseManager(str(cfg / "fd.db"))
    gc.disable()
    try:
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(300):
            db.get_metrics()
        assert len(os.listdir("/proc/self/fd")) - before <= 2
    finally:
        gc.enable()


def test_no_files_created_at_import(tmp_path_factory):
    import subprocess
    tmp_path = tmp_path_factory.mktemp("importcwd")
    code = "import sys; sys.path.insert(0, %r); import services.postApi" % str(Path(__file__).resolve().parent.parent / "app")
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, check=True)
    assert list(tmp_path.iterdir()) == []


def test_phone_masking_in_logs():
    from services.logSvc import mask_phone
    assert mask_phone("+94771234567") == "+94******567"
    assert "771234" not in mask_phone("+94771234567")
    assert mask_phone("123") == "***"
