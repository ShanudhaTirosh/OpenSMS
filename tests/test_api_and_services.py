import os
import sys
import tempfile
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
    hash_api_key,
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
    hashed = hash_api_key(raw_key)
    assert hashed in keys

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
