"""Stage 5: honest Tailscale status, listening modes (fail-closed), no credentials."""
import json, os, socket, subprocess, sys, textwrap
from pathlib import Path
import pytest

APP = str(Path(__file__).resolve().parent.parent / "app")
sys.path.insert(0, APP)

from services.tailscaleSvc import classify, resolve_bind_host, is_tailnet_address, probe_listener, TailscaleService


def info(*ifaces, local="192.168.1.20"):
    return {"interfaces": [{"name": n, "ip": ip} for n, ip in ifaces], "all_ips": [ip for _, ip in ifaces] or ["127.0.0.1"], "local_ip": local}


def ids(status): return {d["id"] for d in status["diagnostics"]}


# ---------------- address classification ----------------
@pytest.mark.parametrize("ip,want", [
    ("100.64.0.1", True), ("100.101.2.3", True), ("100.127.255.255", True),
    ("100.63.255.255", False), ("100.128.0.0", False), ("192.168.1.5", False), ("10.0.0.1", False),
    ("fd7a:115c:a1e0::1", True), ("fd7a:115c:a1e0:ab12:4843:cd96:6200:1", True),
    ("fd7a:115c:a1e1::1", False), ("fe80::1", False), ("junk", False), ("", False),
])
def test_is_tailnet_address(ip, want):
    assert is_tailnet_address(ip) is want


# ---------------- status decision table ----------------
def test_vpn_network_with_tailnet_address_is_connected():
    s = classify(info(("rmnet0", "100.70.1.1")), [{"interface": "tun0", "addresses": ["100.101.2.3", "fe80::1"]}])
    assert (s["state"], s["connected"], s["ip"], s["evidence"], s["interface"]) == ("connected", True, "100.101.2.3", "vpn_network", "tun0")
    assert "cgnat_ignored" in ids(s)        # the carrier address on rmnet0 was not mistaken for Tailscale

def test_carrier_cgnat_address_is_not_tailscale():
    s = classify(info(("rmnet0", "100.72.3.4")), [])
    assert s["state"] == "disconnected" and s["connected"] is False and s["ip"] is None
    assert "cgnat_ignored" in ids(s) and "disconnected" in ids(s)

def test_other_vpn_without_tailnet_address():
    s = classify(info(), [{"interface": "tun1", "addresses": ["10.8.0.2"]}])
    assert s["state"] == "other_vpn" and not s["connected"] and "other_vpn" in ids(s)

def test_ipv6_only_tailnet_address():
    s = classify(info(), [{"interface": "tun0", "addresses": ["fd7a:115c:a1e0:ab12::1"]}], bind_mode="tailscale")
    assert s["state"] == "connected" and s["ip"] is None and s["ipv6"].startswith("fd7a:115c:a1e0")
    assert "bind_blocked" in ids(s)         # tailscale-only needs an IPv4 address to bind to

def test_interface_fallback_requires_a_tunnel_interface():
    ok = classify(info(("tailscale0", "100.90.1.1")), None)
    assert ok["state"] == "connected" and ok["evidence"] == "interface"
    for name in ("wlan0", "rmnet_data1", "eth0", "ccmni0"):
        s = classify(info((name, "100.80.1.1")), None)
        assert s["state"] == "disconnected" and s["ip"] is None, name

def test_unreadable_state_is_unknown_not_disconnected():
    s = classify(info(), None)
    assert s["state"] == "unknown" and "unknown" in ids(s)

def test_no_credential_or_connection_fields_leak_into_status():
    s = classify(info(), [{"interface": "tun0", "addresses": ["100.101.2.3"]}])
    assert s["configured_key"] == "" and s["devices"] == [] and s["node_name"] is None

def test_bind_diagnostics():
    down = classify(info(), [], bind_mode="tailscale")
    assert "bind_blocked" in ids(down)
    up = classify(info(), [{"interface": "tun0", "addresses": ["100.101.2.3"]}], bind_mode="all")
    assert "bind_all" in ids(up)
    assert "bind_localhost" in ids(classify(info(), [], bind_mode="localhost"))
    live = classify(info(), [{"interface": "tun0", "addresses": ["100.101.2.3"]}], port=9292, listening=True)
    dead = classify(info(), [{"interface": "tun0", "addresses": ["100.101.2.3"]}], port=9292, listening=False)
    assert "listening" in ids(live) and "not_listening" in ids(dead)


# ---------------- bind resolution is fail-closed ----------------
def test_resolve_bind_host():
    assert resolve_bind_host("all", None) == ("0.0.0.0", None)
    assert resolve_bind_host("localhost", None) == ("127.0.0.1", None)
    assert resolve_bind_host("tailscale", "100.101.2.3") == ("100.101.2.3", None)
    assert resolve_bind_host("bogus", None) == ("0.0.0.0", None)            # unknown mode -> default
    for bad in (None, "", "192.168.1.5", "0.0.0.0", "fd7a:115c:a1e0::1"):  # never accept a non-tailnet address
        host, err = resolve_bind_host("tailscale", bad)
        assert host is None and "Tailscale" in err, bad


# ---------------- probing ----------------
def test_probe_listener_real_sockets():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    assert probe_listener("127.0.0.1", port) is True
    srv.close()
    assert probe_listener("127.0.0.1", port, timeout=0.3) is False


# ---------------- facade ----------------
def test_service_keeps_no_credentials_and_has_no_connect_api():
    assert TailscaleService.get_config_dict() == {}
    assert not hasattr(TailscaleService, "connect_tailscale_key")
    import ast
    tree = ast.parse(open(os.path.join(APP, "services", "tailscaleSvc.py")).read())
    imported = {n.names[0].name.split(".")[0] for n in tree.body if isinstance(n, ast.Import)} | \
               {n.module.split(".")[0] for n in tree.body if isinstance(n, ast.ImportFrom)}
    assert "requests" not in imported                                    # no network calls to Tailscale at all

def test_get_status_on_this_machine_is_well_formed():
    s = TailscaleService.get_status(port=9292)
    assert s["state"] in {"connected", "other_vpn", "disconnected", "unknown"}
    assert isinstance(s["diagnostics"], list) and s["diagnostics"]

def test_preferred_endpoint_respects_listening_mode(monkeypatch):
    fake = classify(info(), [{"interface": "tun0", "addresses": ["100.101.2.3"]}])
    monkeypatch.setattr(TailscaleService, "get_status", classmethod(lambda cls, **k: fake))
    assert TailscaleService.get_preferred_endpoint(9292, "all")[0] == "http://100.101.2.3:9292/sms/"
    assert TailscaleService.get_preferred_endpoint(9292, "localhost")[0] == "http://127.0.0.1:9292/sms/"
    off = classify(info(), [])
    monkeypatch.setattr(TailscaleService, "get_status", classmethod(lambda cls, **k: off))
    url, kind = TailscaleService.get_preferred_endpoint(9292, "tailscale")
    assert "<tailscale-ip>" in url and "not connected" in kind          # never advertises a LAN address in tailscale-only mode


# ---------------- the real service process logic, fail-closed (subprocess: appSvc has import side effects) ----------------
RUNNER = textwrap.dedent('''
    import sys, json, time, socket
    sys.path.insert(0, %r)
    import services.appSvc as A
    from services.tailscaleSvc import TailscaleService
    mode, port, fake_ip = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    ip = None if fake_ip == "none" else fake_ip
    TailscaleService.get_status = classmethod(lambda cls, **k: {"ip": ip, "connected": bool(ip)})
    A.api_server_control("start", port, mode)
    time.sleep(2.0)
    def reach():
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close(); return True
        except OSError:
            return False
    out = {"server": A.resp_template.get("server"), "error": A.resp_template.get("error"),
           "host": A.resp_template.get("host"), "started": A.api_started, "reach": reach(), "err_state": A.in_error_state}
    A.api_server_control("stop", port)
    print("RESULT" + json.dumps(out))
''' % APP)

def run_service(tmp_path, mode, fake_ip="none"):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path), "OPENSMS_ALLOW_SIMULATION": "1"}
    r = subprocess.run([sys.executable, "-c", RUNNER, mode, str(port), fake_ip], capture_output=True, text=True, env=env, timeout=60, cwd=tmp_path)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    assert line, r.stdout + r.stderr
    return json.loads(line[0][6:])

def test_service_all_mode_listens_everywhere(tmp_path):
    r = run_service(tmp_path, "all")
    assert r["server"] == "started" and r["host"] == "0.0.0.0" and r["reach"] is True

def test_service_localhost_mode_binds_loopback_only(tmp_path):
    r = run_service(tmp_path, "localhost")
    assert r["server"] == "started" and r["host"] == "127.0.0.1" and r["reach"] is True

def test_service_tailscale_mode_without_address_refuses_to_start(tmp_path):
    r = run_service(tmp_path, "tailscale", "none")
    assert r["server"] == "error" and "Tailscale-only" in r["error"]
    assert r["started"] is False and r["reach"] is False              # nothing listens, not even on loopback

def test_service_tailscale_mode_never_falls_back_when_bind_fails(tmp_path):
    r = run_service(tmp_path, "tailscale", "100.101.2.3")             # address not present on this machine
    assert r["server"] == "error" and r["reach"] is False


def test_service_reports_port_already_in_use(tmp_path):
    """Pre-existing defect: uvicorn's sys.exit(1) on a failed bind used to leave the UI showing 'started'."""
    hog = socket.socket(); hog.bind(("0.0.0.0", 0)); hog.listen(1)
    port = hog.getsockname()[1]
    env = {**os.environ, "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path), "OPENSMS_ALLOW_SIMULATION": "1"}
    try:
        r = subprocess.run([sys.executable, "-c", RUNNER, "all", str(port), "none"], capture_output=True, text=True,
                           env=env, timeout=60, cwd=tmp_path)
    finally:
        hog.close()
    out = json.loads([l for l in r.stdout.splitlines() if l.startswith("RESULT")][0][6:])
    assert out["server"] == "error" and "bind" in out["error"].lower() and out["started"] is False
