import os
import sys
import json
import pytest
from pathlib import Path

# Add app directory to sys.path
app_dir = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(app_dir))

from services.postApi import (
    app,
    set_config_path,
    generate_new_api_key,
    get_api_keys,
    SmsData,
    BatchSmsData,
    FAILED_AUTH_ATTEMPTS
)
from services.logSvc import LogService
from services.pathMgr import atomic_write_json, get_device_ip_addresses

from fastapi.testclient import TestClient



client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_temp_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    set_config_path(str(config_dir))
    FAILED_AUTH_ATTEMPTS.clear()
    yield config_dir

def test_health_check():
    response = client.get("/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["app"] == "OpenSMS"

def test_api_key_generation_and_verification():
    raw_key = generate_new_api_key()
    assert raw_key.startswith("osms_")
    keys = get_api_keys()
    assert len(keys) == 1
    import services.postApi as post_mod
    assert post_mod.db_mgr.verify_api_key(raw_key) is not None
    # SQLite is the single source of truth: no plaintext/legacy key file is written
    assert not (Path(post_mod.config_dir) / "keys.json").exists()

def test_unauthenticated_sms_fails():
    response = client.post("/sms/", json={"number": "+1234567890", "text": "Test"})
    assert response.status_code == 401

def test_invalid_api_key_fails():
    response = client.post(
        "/sms/",
        headers={"Authorization": "Bearer invalid-token"},
        json={"number": "+1234567890", "text": "Test"}
    )
    assert response.status_code == 401

def test_authenticated_sms_success():
    raw_key = generate_new_api_key()
    response = client.post(
        "/sms/",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"number": "+1234567890", "text": "Hello world!"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["stat"] is True
    assert "+1234567890" in data["message"]

def test_batch_sms_endpoint():
    raw_key = generate_new_api_key()
    batch_payload = {
        "messages": [
            {"number": "+1112223334", "text": "Batch Msg 1"},
            {"number": "+1112223335", "text": "Batch Msg 2"}
        ]
    }
    response = client.post(
        "/sms/batch/",
        headers={"Authorization": f"Bearer {raw_key}"},
        json=batch_payload
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["successful"] == 2

def test_phone_number_validation():
    # Valid phone formats
    valid1 = SmsData(number="+1 (555) 019-2834", text="Hello")
    assert valid1.number == "+1 (555) 019-2834"

    # Invalid phone formats (too short, bad characters)
    with pytest.raises(ValueError):
        SmsData(number="123", text="Hello")

    with pytest.raises(ValueError):
        SmsData(number="phone_number_string", text="Hello")

    with pytest.raises(ValueError):
        SmsData(number="+1234567890", text="")

def test_rate_limiting_on_repeated_failed_logins():
    # Attempt 10 failed logins
    for _ in range(10):
        client.post(
            "/sms/",
            headers={"Authorization": "Bearer bad-key"},
            json={"number": "+1234567890", "text": "Test"}
        )

    # 11th attempt should trigger 429 Too Many Requests
    blocked_response = client.post(
        "/sms/",
        headers={"Authorization": "Bearer bad-key"},
        json={"number": "+1234567890", "text": "Test"}
    )
    assert blocked_response.status_code == 429

def test_atomic_write_json(tmp_path):
    target_file = tmp_path / "test.json"
    data = {"hello": "world", "status": 200}
    atomic_write_json(str(target_file), data)

    assert target_file.exists()
    with open(target_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data

def test_log_service(tmp_path):
    log_svc = LogService("test_app", "linux")
    log_svc.base_path = str(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_svc.log_path = str(log_dir / "api_logs.log")

    log_svc.write_log("Message 1")
    log_svc.write_log("Message 2")

    logs = log_svc.get_api_logs()
    assert len(logs) == 2
    assert "Message 1" in logs[0]
    assert "Message 2" in logs[1]

    log_svc.clear_logs()
    assert len(log_svc.get_api_logs()) == 0

def test_device_ip_discovery():
    ips = get_device_ip_addresses()
    assert isinstance(ips, list)
    assert len(ips) >= 1

def test_phone_sanitization():
    from services.smsApi import sanitize_phone_number
    assert sanitize_phone_number("+1 (555) 019-2834") == "+15550192834"
    assert sanitize_phone_number("077-123-4567") == "0771234567"
    assert sanitize_phone_number("+44 20 7946 0991") == "+442079460991"
    assert sanitize_phone_number("") == ""

def test_sms_segmentation_calculation():
    from services.smsApi import calculate_sms_segments
    # Short GSM-7
    gsm_short = calculate_sms_segments("Hello world!")
    assert gsm_short["encoding"] == "GSM-7"
    assert gsm_short["segments"] == 1
    assert gsm_short["remaining"] == 160 - 12

    # Long GSM-7 (161 chars)
    gsm_long = calculate_sms_segments("A" * 161)
    assert gsm_long["encoding"] == "GSM-7"
    assert gsm_long["segments"] == 2

    # Unicode with emoji (UCS-2)
    unicode_msg = calculate_sms_segments("Hello 🚀")
    assert "UCS-2" in unicode_msg["encoding"]
    assert unicode_msg["segments"] == 1

def test_tailscale_ip_detection():
    from services.pathMgr import is_tailscale_ip
    assert is_tailscale_ip("100.85.24.12") is True
    assert is_tailscale_ip("100.64.0.1") is True
    assert is_tailscale_ip("100.127.255.254") is True
    assert is_tailscale_ip("100.128.0.1") is False  # Outside 100.64.0.0/10
    assert is_tailscale_ip("192.168.1.100") is False
    assert is_tailscale_ip("127.0.0.1") is False
    assert is_tailscale_ip("invalid_ip") is False

def test_tailscale_service_snippets():
    from services.tailscaleSvc import TailscaleService
    snippets = TailscaleService.generate_code_snippets(
        endpoint="http://100.85.12.34:9292/sms/",
        api_key="osms_test_key_123",
        phone="+1234567890",
        text="Test message"
    )
    assert "curl" in snippets
    assert "python" in snippets
    assert "nodejs" in snippets
    assert "osms_test_key_123" in snippets["curl"]
    assert "http://100.85.12.34:9292/sms/" in snippets["python"]

def test_batch_sms_max_limit():
    from services.postApi import SmsData
    valid_msgs = [SmsData(number="+1234567890", text="Test") for _ in range(5)]
    batch = BatchSmsData(messages=valid_msgs)
    assert len(batch.messages) == 5

    # Exceeding 100 should raise ValueError
    too_many = [SmsData(number="+1234567890", text="Test") for _ in range(101)]
    with pytest.raises(ValueError):
        BatchSmsData(messages=too_many)

    with pytest.raises(ValueError):
        BatchSmsData(messages=[])

def test_phone_number_validation_non_digits():
    # Strings without sufficient digits must fail validation
    with pytest.raises(ValueError):
        SmsData(number="-------", text="Hello")

    with pytest.raises(ValueError):
        SmsData(number="+       ", text="Hello")

    with pytest.raises(ValueError):
        SmsData(number="()()()()", text="Hello")

    with pytest.raises(ValueError):
        SmsData(number="+12345", text="Hello")  # Only 5 digits

def test_phone_sanitization_empty_or_non_digits():
    from services.smsApi import sanitize_phone_number
    assert sanitize_phone_number("+") == ""
    assert sanitize_phone_number("+   ") == ""
    assert sanitize_phone_number("+abc") == ""
    assert sanitize_phone_number("---") == ""
    assert sanitize_phone_number("+1 (555) 019-2834") == "+15550192834"

def test_tailscale_endpoint_fallback_never_none(monkeypatch):
    from services.tailscaleSvc import TailscaleService
    import services.tailscaleSvc as ts_mod

    # Mock get_network_interfaces_info to return None for local_ip and tailscale_ip
    monkeypatch.setattr(
        ts_mod,
        "get_network_interfaces_info",
        lambda: {
            "tailscale_ip": None,
            "local_ip": None,
            "cellular_ip": None,
            "all_ips": ["127.0.0.1"],
            "interfaces": []
        }
    )
    endpoint, net_type = TailscaleService.get_preferred_endpoint(9292)
    assert endpoint == "http://127.0.0.1:9292/sms/"
    assert "None" not in endpoint

def test_rate_limiting_ignores_forwarded_for():
    # X-Forwarded-For is attacker-controlled: rotating it must NOT evade the lockout (SEC-03)
    for i in range(10):
        client.post(
            "/sms/",
            headers={"Authorization": "Bearer bad-key", "X-Forwarded-For": f"203.0.113.{i}"},
            json={"number": "+1234567890", "text": "Test"}
        )
    res = client.post(
        "/sms/",
        headers={"Authorization": "Bearer bad-key", "X-Forwarded-For": "198.51.100.77"},
        json={"number": "+1234567890", "text": "Test"}
    )
    assert res.status_code == 429

# (removed in audit Stage 5: asserted the fake in-app Tailscale 'connect' behaviour; see tests/test_stage5_tailscale.py)

# (removed in audit Stage 5: asserted the fake in-app Tailscale 'connect' behaviour; see tests/test_stage5_tailscale.py)

# (removed in audit Stage 5: asserted the fake in-app Tailscale 'connect' behaviour; see tests/test_stage5_tailscale.py)

def test_db_manager_crud_and_metrics(tmp_path):
    from services.dbMgr import DatabaseManager
    db_file = str(tmp_path / "test_opensms.db")
    db = DatabaseManager(db_file)

    msg_id = db.create_message(
        recipient="+15551234567",
        text="Test persistence",
        encoding="GSM-7",
        segments=1,
        sim_slot=0,
        status="queued"
    )
    assert msg_id is not None
    record = db.get_message(msg_id)
    assert record["recipient"] == "+15551234567"
    assert record["status"] == "queued"

    db.update_message_status(msg_id, "sent")
    updated = db.get_message(msg_id)
    assert updated["status"] == "sent"
    # "sent" is only a hand-off to the telephony layer, never a delivery confirmation (SMS-01)
    assert updated["delivered_at"] is None
    db.update_message_status(msg_id, "delivered")
    assert db.get_message(msg_id)["delivered_at"] is not None

    metrics = db.get_metrics()
    assert metrics["sent_today"] >= 1
    assert metrics["success_rate"] == 100.0

def test_db_manager_multi_key():
    raw_key = "osms_test_key_abc_123456"
    raw_key2 = "osms_test_key_xyz_789012"

    import services.postApi as post_mod
    db = post_mod.db_mgr

    id1 = db.add_api_key(raw_key, name="Home Assistant", scopes=["sms:write"])
    db.add_api_key(raw_key2, name="Grafana Alerts", scopes=["sms:read"])

    v1 = db.verify_api_key(raw_key)
    assert v1 is not None
    assert v1["name"] == "Home Assistant"

    v2 = db.verify_api_key(raw_key2)
    assert v2 is not None
    assert v2["name"] == "Grafana Alerts"

    keys = db.list_api_keys()
    assert len(keys) >= 2

    # Revoke id1
    db.revoke_api_key(id1)
    assert db.verify_api_key(raw_key) is None
    assert db.verify_api_key(raw_key2) is not None

def test_semver_parsing_and_comparison():
    from services.updateMgr import parse_semver, is_newer_version
    assert parse_semver("v0.3.0") == (0, 3, 0)
    assert parse_semver("0.4.1") == (0, 4, 1)
    assert parse_semver("v1.0.0-rc1") == (1, 0, 0)

    assert is_newer_version("0.3.0", "v0.4.0") is True
    assert is_newer_version("0.4.0", "v0.4.0") is False
    assert is_newer_version("0.5.0", "v0.4.0") is False
    assert is_newer_version("0.3.0", "0.3.1") is True

def test_new_api_endpoints():
    raw_key = generate_new_api_key("Test App")
    headers = {"Authorization": f"Bearer {raw_key}"}

    # 1. Send SMS and get ID
    sms_res = client.post(
        "/sms/",
        headers=headers,
        json={"number": "+1234567890", "text": "Testing new endpoints"}
    )
    assert sms_res.status_code == 200
    msg_id = sms_res.json().get("id")
    assert msg_id is not None

    # 2. Get SMS status by ID
    get_res = client.get(f"/sms/{msg_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == msg_id
    assert get_res.json()["status"] == "sent"

    # 3. Get history
    hist_res = client.get("/sms/history/", headers=headers)
    assert hist_res.status_code == 200
    assert hist_res.json()["count"] >= 1

    # 4. Get system stats
    stats_res = client.get("/system/stats/", headers=headers)
    assert stats_res.status_code == 200
    assert "metrics" in stats_res.json()

    # 5. Get system sims
    sims_res = client.get("/system/sims/", headers=headers)
    assert sims_res.status_code == 200
    assert len(sims_res.json()["sims"]) >= 1

def test_update_manager_check_and_download(tmp_path, monkeypatch):
    from services.updateMgr import UpdateManager
    import requests

    class MockResponse:
        def __init__(self, status_code, json_data, content=b""):
            self.status_code = status_code
            self._json = json_data
            self.content = content
            self.headers = {"content-length": str(len(content))}

        def json(self):
            return self._json

        def iter_content(self, chunk_size=65536):
            yield self.content

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_release = {
        "tag_name": "v0.5.0",
        "name": "OpenSMS v0.5.0",
        "body": "Exciting new features and bug fixes!",
        "html_url": "https://github.com/ShanudhaTirosh/OpenSMS/releases/tag/v0.5.0",
        "assets": [
            {
                "name": "OpenSMS-v0.5.0-release.apk",
                "browser_download_url": "https://github.com/ShanudhaTirosh/OpenSMS/releases/download/v0.5.0/OpenSMS.apk",
                "size": 1024
            }
        ]
    }

    def mock_get(url, *args, **kwargs):
        if "releases/latest" in url:
            return MockResponse(200, mock_release)
        elif "download" in url:
            return MockResponse(200, {}, content=b"PK\x03\x04mock_apk_binary_payload")
        return MockResponse(404, {})

    monkeypatch.setattr(requests, "get", mock_get)

    # 1. Check for updates
    res = UpdateManager.check_for_updates("0.4.0")
    assert res["success"] is True
    assert res["has_update"] is True
    assert res["latest_version"] == "0.5.0"
    assert res["apk_url"] is not None

    # 2. Download APK
    dest_file = str(tmp_path / "test_update.apk")
    progress_reported = []
    def on_prog(pct, dl, tot):
        progress_reported.append(pct)

    dl_res = UpdateManager.download_apk(res["apk_url"], dest_file, progress_callback=on_prog)
    assert dl_res["success"] is True
    assert os.path.exists(dest_file)
    assert len(progress_reported) > 0
    assert progress_reported[-1] == 100.0

    # 3. Install simulation (desktop returns success simulation)
    inst_res = UpdateManager.install_apk(dest_file)
    assert inst_res["success"] is True

def test_ai_doc_endpoints_require_auth_by_default():
    for path in ("/llms.txt", "/docs/markdown", "/docs/ai"):
        assert client.get(path).status_code == 401
    key = generate_new_api_key()
    h = {"Authorization": f"Bearer {key}"}
    for path in ("/llms.txt", "/docs/markdown", "/docs/ai"):
        res = client.get(path, headers=h)
        assert res.status_code == 200
        assert "OpenSMS" in res.text
    # interactive docs / openapi are disabled unless OPENSMS_PUBLIC_DOCS=1
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
