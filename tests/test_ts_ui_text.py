import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from services.tsUiText import describe_embedded as d


def test_service_not_running_disables_everything():
    r = d({})
    assert not r["can_connect"] and "Start Server" in r["detail"] and "service not running" in r["title"]

def test_library_missing_is_explained_and_nothing_is_offered():
    r = d({"state": "unavailable", "available": False, "reason": "libtailscale.so was not found"})
    assert not r["can_connect"] and not r["can_forget"] and "not in this build" in r["title"] and "libtailscale" in r["detail"]

def test_off_connecting_and_problem_states():
    assert d({"state": "disabled", "available": True})["can_connect"] and "auth key" in d({"state": "disabled"})["detail"]
    r = d({"state": "starting", "message": "Creating a one-time auth key..."})
    assert "connecting" in r["title"] and "one-time" in r["detail"] and r["can_disconnect"]
    r = d({"state": "needs_auth", "message": "Tailscale did not accept the key"})
    assert "key needed" in r["title"] and "did not accept" in r["detail"] and not r["can_disconnect"]
    assert "approval" in d({"state": "needs_approval"})["title"] and d({"state": "needs_approval"})["can_disconnect"]
    r = d({"state": "error", "error": "Timed out"})
    assert "problem" in r["title"] and r["detail"] == "Timed out" and r["can_connect"]

def test_connected_shows_address_endpoint_and_peers():
    st = {"state": "connected", "ip": "100.64.0.10", "dns_name": "phone.tailnet.ts.net", "tailnet": "example.com", "saved_identity": True,
          "peers": [{"name": "laptop", "ip": "100.64.0.5", "online": True}, {"name": "nas", "ip": "100.64.0.6", "online": False}],
          "forwarded": {"accepted": 3}}
    r = d(st, port=9292)
    assert r["connected"] and r["can_disconnect"] and r["can_forget"] and not r["can_connect"]   # fields hidden while connected
    assert r["ip"] == "100.64.0.10" and r["endpoint"] == "http://100.64.0.10:9292/sms/" and "phone.tailnet.ts.net" in r["detail"] and "3 connection(s)" in r["detail"]
    assert "\u25cf laptop" in r["peers_text"] and "\u25cb nas" in r["peers_text"]
    many = d({**st, "peers": [{"name": f"p{i}", "ip": "", "online": True} for i in range(12)]})
    assert "+4 more" in many["peers_text"]
    assert "No other devices" in d({**st, "peers": []})["peers_text"]

def test_secrets_never_appear_in_the_texts():
    r = d({"state": "error", "error": "tskey-auth-secretsecret123 failed", "message": "tskey-api-abcdefgh12345 rejected"})
    assert "tskey-auth-secretsecret123" not in r["detail"] and "tskey-***" in r["detail"]
    r = d({"state": "needs_auth", "message": "bad key tskey-auth-abcdefgh12345"})
    assert "tskey-auth-abcdefgh12345" not in r["detail"]
