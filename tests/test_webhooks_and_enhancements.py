"""Tests for OpenSMS 0.5.5 enhancements:
- Event Webhooks CRUD & Async Dispatcher
- HMAC-SHA256 signature generation
- Battery & power telemetry
- Single-pass SQLite metrics optimization
- UI navigation handlers
"""
import sys
import ast
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import services.postApi as P
from services import authSvc
from services.dbMgr import DatabaseManager
from services.webhookSvc import build_signature, send_webhook_request, dispatch_event
from services.batterySvc import get_battery_info

client = TestClient(P.app)


@pytest.fixture(autouse=True)
def cfg(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    P.set_config_path(str(d))
    authSvc.FAILED_AUTH_ATTEMPTS.clear()
    authSvc.reset_send_limiter()
    yield d


def H(k, **extra):
    return {"Authorization": f"Bearer {k}", **extra}


# ---------------- Webhook Database CRUD & Optimization ----------------

def test_webhook_db_crud(tmp_path):
    db_file = str(tmp_path / "test_opensms.db")
    db = DatabaseManager(db_file)

    # 1. Add webhook
    wh_id = db.add_webhook(
        url="https://api.example.com/webhook",
        events=["sms.sent", "sms.delivered"],
        secret="a" * 32,
    )
    assert isinstance(wh_id, str)
    assert len(wh_id) > 10

    # 2. List webhooks
    webhooks = db.list_webhooks()
    assert len(webhooks) == 1
    wh = webhooks[0]
    assert wh["id"] == wh_id
    assert wh["url"] == "https://api.example.com/webhook"
    assert wh["events"] == ["sms.sent", "sms.delivered"]
    assert wh["is_active"] in (1, True)

    # 3. Get webhook by id
    fetched = db.get_webhook(wh_id, include_secret=True)
    assert fetched is not None
    assert fetched["id"] == wh_id
    assert fetched["secret"] == "a" * 32

    # 4. Filter active webhooks for specific event
    sent_subs = db.get_active_webhooks_for_event("sms.sent")
    assert len(sent_subs) == 1
    assert sent_subs[0]["id"] == wh_id

    failed_subs = db.get_active_webhooks_for_event("sms.failed")
    assert len(failed_subs) == 0

    # 5. Database maintenance/optimize
    db.optimize_db()

    # 6. Delete webhook
    deleted = db.delete_webhook(wh_id)
    assert deleted is True
    assert db.get_webhook(wh_id) is None
    assert len(db.list_webhooks()) == 0


def test_db_metrics_single_pass(tmp_path):
    db_file = str(tmp_path / "test_metrics.db")
    db = DatabaseManager(db_file)

    # Add messages with various statuses
    db.create_message(recipient="+1111111111", text="test 1", sim_slot=0, status="queued")
    db.create_message(recipient="+2222222222", text="test 2", sim_slot=0, status="sent")
    db.create_message(recipient="+3333333333", text="test 3", sim_slot=0, status="delivered")
    db.create_message(recipient="+4444444444", text="test 4", sim_slot=0, status="failed")

    metrics = db.get_metrics()
    # sent_today counts sent + delivered = 2
    assert metrics["sent_today"] == 2
    # failed_today = 1
    assert metrics["failed_today"] == 1
    # queue_depth = 1 (queued)
    assert metrics["queue_depth"] == 1
    # total = 3 (sent + delivered + failed), 2 / 3 = 66.7%
    assert metrics["success_rate"] == 66.7


# ---------------- Webhook Dispatcher & Cryptography ----------------

def test_webhook_signature():
    secret = "my-secret-key-123456"
    payload = b'{"event":"sms.sent","id":"123"}'
    sig1 = build_signature(payload, secret)
    sig2 = build_signature(payload, secret)
    assert sig1 == sig2
    assert len(sig1) == 64  # SHA-256 hex digest length

    # Different secret or payload gives different signature
    assert build_signature(payload, "other-secret") != sig1
    assert build_signature(b'{"other":true}', secret) != sig1


@patch("services.webhookSvc.requests.post")
def test_webhook_send(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    success, code, err = send_webhook_request(
        url="https://example.com/callback",
        payload={"event": "sms.sent", "id": "123"},
        secret="test-secret-at-least-16-chars",
    )
    assert success is True
    assert code == 200
    assert err is None
    assert mock_post.called
    kwargs = mock_post.call_args[1]
    assert kwargs["headers"]["X-OpenSMS-Event"] == "sms.sent"
    assert "sha256=" in kwargs["headers"]["X-OpenSMS-Signature"]


def test_dispatch_event_end_to_end(tmp_path):
    import time
    db_file = str(tmp_path / "test_dispatch.db")
    db = DatabaseManager(db_file)
    db.add_webhook("https://example.com/events", events=["sms.sent"], secret="secret1234567890")

    with patch("services.webhookSvc.send_webhook_request", return_value=(True, 200, None)) as mock_send:
        dispatch_event(db, "sms.sent", {"id": "msg-123", "status": "sent"})
        time.sleep(0.1)
        assert mock_send.called


# ---------------- Battery Telemetry ----------------

def test_battery_info():
    info = get_battery_info()
    assert isinstance(info, dict)
    assert "available" in info
    assert "charging" in info
    assert "plugged" in info
    assert "percentage" in info
    assert isinstance(info["charging"], bool)


# ---------------- API Endpoints ----------------

def test_system_stats_endpoint(cfg):
    k = P.generate_new_api_key("AdminKey", ["admin", "sms:read"])
    r = client.get("/system/stats/", headers=H(k))
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "0.5.5"
    assert "battery" in data
    assert "available" in data["battery"]
    assert "charging" in data["battery"]
    assert "plugged" in data["battery"]


def test_webhooks_api_lifecycle(cfg):
    admin_key = P.generate_new_api_key("AdminKey", ["admin"])
    read_only_key = P.generate_new_api_key("ReadOnly", ["sms:read"])

    # 1. Non-admin forbidden
    r = client.get("/webhooks/", headers=H(read_only_key))
    assert r.status_code == 403

    # 2. List empty webhooks
    r = client.get("/webhooks/", headers=H(admin_key))
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["webhooks"] == []

    # 3. Validation failure: bad URL
    r = client.post("/webhooks/", json={
        "url": "not-a-valid-url",
        "events": ["sms.sent"],
        "secret": "valid-secret-16-chars-long",
    }, headers=H(admin_key))
    assert r.status_code == 422

    # 4. Validation failure: secret too long (>128 chars)
    r = client.post("/webhooks/", json={
        "url": "https://example.com/webhook",
        "events": ["sms.sent"],
        "secret": "x" * 129,
    }, headers=H(admin_key))
    assert r.status_code == 422

    # 5. Validation failure: invalid event name
    r = client.post("/webhooks/", json={
        "url": "https://example.com/webhook",
        "events": ["sms.invalid_event"],
        "secret": "valid-secret-16-chars-long",
    }, headers=H(admin_key))
    assert r.status_code == 422

    # 6. Create valid webhook
    r = client.post("/webhooks/", json={
        "url": "https://example.com/sms-events",
        "events": ["sms.sent", "sms.delivered"],
        "secret": "my-secret-key-that-is-long-enough",
    }, headers=H(admin_key))
    assert r.status_code == 201
    created = r.json()
    assert len(created["id"]) > 10
    assert created["url"] == "https://example.com/sms-events"
    assert created["events"] == ["sms.sent", "sms.delivered"]
    wh_id = created["id"]

    # 7. Test webhook dispatch
    with patch("services.webhookSvc.send_webhook_request", return_value=(True, 200, None)):
        r = client.post(f"/webhooks/test/{wh_id}", headers=H(admin_key))
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert r.json()["status_code"] == 200

    # 8. Delete webhook
    r = client.delete(f"/webhooks/{wh_id}", headers=H(admin_key))
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert r.json()["id"] == wh_id

    # 9. Test deleted webhook returns 404
    r = client.post(f"/webhooks/test/{wh_id}", headers=H(admin_key))
    assert r.status_code == 404


# ---------------- UI & Navigation Handlers ----------------

def test_ui_drawer_and_navigation_handlers():
    main_py = ROOT / "app" / "main.py"
    tree = ast.parse(main_py.read_text(encoding="utf-8"))

    app_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "OpenSmsApp":
            app_class = node
            break
    assert app_class is not None, "OpenSmsApp class not found in main.py"

    method_names = {n.name for n in app_class.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "goto_logs_screen" in method_names
    assert "open_test_sms_from_drawer" in method_names
    assert "open_about_from_drawer" in method_names
    assert "_get_active_endpoint" in method_names
