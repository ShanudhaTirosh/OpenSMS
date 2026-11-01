"""Built-in Tailscale: keys, secret hand-off, forwarder, controller state machine, command bridge (fake C library)."""
import json, os, socket, stat, sys, threading, time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app")); sys.path.insert(0, str(ROOT / "tests"))
from services import tsEmbed as E, tsNative as N
from fake_tailscale import FakeTailscaleLib

GOOD = "tskey-auth-good-ABCDEFGH1234"
API = "tskey-api-kABCDEFGH1234567890"


# =============================================================================== keys
@pytest.mark.parametrize("text,kind", [(GOOD, "authkey"), ("  " + GOOD + "\n", "authkey"), (API, "apikey"), ("tskey-auth-kXYZ123456-abcdef", "authkey")])
def test_classify_accepts_auth_and_api_keys(text, kind):
    assert E.classify_key(text)[0] == kind and E.classify_key(text)[1] == text.strip()

@pytest.mark.parametrize("bad", ["", "   ", "hello", "tskey-auth-", "tskey-auth-short", "tskey-api-x", "tskey-client-abc123456-secret", "abc tskey-auth-good-1234567890"])
def test_classify_rejects_everything_else_with_a_helpful_message(bad):
    with pytest.raises(E.KeyProblem) as e:
        E.classify_key(bad)
    assert "tskey" in str(e.value) or "Paste" in str(e.value)
    assert bad.strip() == "" or bad not in str(e.value) or len(bad) < 12                 # never echoes what was typed

def test_redact_removes_every_key_shape():
    t = f"failed with {GOOD} and {API} and tskey-client-zzz-999 and TSKEY-AUTH-abc12345"
    r = E.redact(t)
    for secret in (GOOD, API, "tskey-client-zzz-999", "TSKEY-AUTH-abc12345"):
        assert secret not in r
    assert r.count("tskey-***") == 4

@pytest.mark.parametrize("raw,want", [("My Phone!", "my-phone"), ("  OPEN_SMS  ", "open-sms"), ("---", "opensms"), ("", "opensms"), ("a" * 80, "a" * 63), ("ünï", "n"), ("üï", "opensms"), ("-x-", "x")])
def test_hostname_cleaning(raw, want):
    assert E.clean_hostname(raw) == want

@pytest.mark.parametrize("url,ok", [("", True), ("https://hs.example.com", True), ("http://192.168.1.5:8080/", True), ("ftp://x", False), ("hs.example.com", False), ("https://", False)])
def test_control_url_validation(url, ok):
    if ok:
        out = E.validate_control_url(url)
        assert out is None or not out.endswith("/")
    else:
        with pytest.raises(E.KeyProblem):
            E.validate_control_url(url)


class Http:
    def __init__(self, status=200, body=None, exc=None):
        self.status, self.body, self.exc, self.calls = status, body if body is not None else {"key": "tskey-auth-minted-0123456789"}, exc, []
    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers, timeout))
        if self.exc: raise self.exc
        class R: pass
        r = R(); r.status_code = self.status; r.json = lambda: self.body
        return r

def test_mint_creates_a_single_use_short_lived_preauthorised_key():
    http = Http()
    key = E.mint_auth_key(API, "my-phone", http=http)
    url, body, headers, timeout = http.calls[0]
    assert key == "tskey-auth-minted-0123456789" and url.endswith("/tailnet/-/keys") and url.startswith("https://api.tailscale.com/")
    c = body["capabilities"]["devices"]["create"]
    assert c == {"reusable": False, "ephemeral": False, "preauthorized": True} and body["expirySeconds"] <= 600
    assert headers["Authorization"] == f"Bearer {API}" and timeout and "my-phone" in body["description"]

@pytest.mark.parametrize("status,needle", [(401, "rejected"), (403, "not allowed"), (404, "tailnet"), (429, "rate"), (500, "HTTP 500")])
def test_mint_errors_are_explained_and_never_contain_the_token(status, needle):
    with pytest.raises(E.KeyProblem) as e:
        E.mint_auth_key(API, "h", http=Http(status=status))
    assert needle in str(e.value) and API not in str(e.value)

def test_mint_network_failure_and_bad_responses():
    with pytest.raises(E.KeyProblem) as e:
        E.mint_auth_key(API, "h", http=Http(exc=RuntimeError(f"boom {API}")))
    assert API not in str(e.value) and "internet" in str(e.value)
    for body in ({}, {"key": "not-a-key"}, {"key": ""}):
        with pytest.raises(E.KeyProblem, match="did not return an auth key"):
            E.mint_auth_key(API, "h", http=Http(body=body))


# =============================================================================== secret hand-off
def test_secret_is_private_one_shot_and_shredded(tmp_path, monkeypatch):
    E.write_secret(str(tmp_path), "authkey", GOOD, "phone", "")
    p = tmp_path / E.SECRET_FILE
    if sys.platform != "win32":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    seen = []
    real_remove = os.remove
    monkeypatch.setattr(os, "remove", lambda path: (seen.append(Path(path).read_bytes()), real_remove(path)))
    data = E.take_secret(str(tmp_path))
    assert data == {"kind": "authkey", "value": GOOD, "hostname": "phone", "control_url": ""}
    assert not p.exists() and E.take_secret(str(tmp_path)) is None
    assert seen and set(seen[0]) == {0}                                                 # overwritten with zeros first
    assert not list(tmp_path.glob("*.tmp"))

def test_take_secret_with_garbage_still_removes_it(tmp_path):
    (tmp_path / E.SECRET_FILE).write_text("{not json")
    assert E.take_secret(str(tmp_path)) is None and not (tmp_path / E.SECRET_FILE).exists()


# =============================================================================== helpers for node tests
def echo_server():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(32)
    port = srv.getsockname()[1]
    def serve():
        while True:
            try: c, _ = srv.accept()
            except OSError: return
            def h(c=c):
                try:
                    while True:
                        d = c.recv(65536)
                        if not d: break
                        c.sendall(d)
                finally:
                    c.close()
            threading.Thread(target=h, daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()
    class Handle:
        def __init__(self): self.sock = srv
        def close(self):                                     # shutdown() wakes the blocked accept(); close() alone does not
            try: srv.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            srv.close()
    return port, Handle()

def wait_for(pred, secs=5.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred(): return True
        time.sleep(0.02)
    return False

def make_engine(tmp_path, lib=None, port=9292, **kw):
    lib = lib or FakeTailscaleLib()
    opts = dict(startup_timeout=3.0, auth_grace=0.3, poll=0.02, monitor_interval=0.1, log=lambda m: None)
    opts.update(kw)
    eng = E.EmbeddedTailscale(str(tmp_path), lib_loader=lambda: (lib, ""), port=port, **opts)
    return eng, lib


# =============================================================================== forwarder
@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_tailnet_device_reaches_the_local_api_through_the_forwarder(tmp_path):
    api_port, api = echo_server()
    eng, lib = make_engine(tmp_path, port=api_port)
    eng.connect("authkey", GOOD, "Phone One")
    assert wait_for(lambda: eng.status()["state"] == "connected")
    st = eng.status()
    assert st["ip"] == "100.64.0.10" and st["hostname"] == "phone-one" and st["tailnet"] == "example.com"
    c = lib.tailnet.connect("100.64.0.10", api_port, from_ip="100.64.0.55")           # another device on the tailnet
    c.sendall(b"GET /health/ HTTP/1.1\r\n\r\n")
    c.settimeout(3); assert c.recv(100).startswith(b"GET /health/")
    big = os.urandom(1_000_000)
    c.sendall(big); got = b""
    while len(got) < len(big): got += c.recv(65536)
    assert got == big                                                                  # 1 MB round trip, intact
    c.close(); eng.disconnect(); api.close()
    assert eng.status()["state"] in ("disabled", "unavailable")

@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_large_simultaneous_transfers_in_both_directions_do_not_deadlock():
    """A client pushing a big request while the server pushes a big response must not stall the relay."""
    lib = FakeTailscaleLib(); node = N.NativeTailscale(lib); node.set_authkey(GOOD); node.start()
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]
    SIZE = 3_000_000
    received = {}
    def server():
        c, _ = srv.accept()
        got = bytearray()
        sender = threading.Thread(target=lambda: c.sendall(b"S" * SIZE), daemon=True); sender.start()   # talks while listening
        while len(got) < SIZE:
            d = c.recv(65536)
            if not d: break
            got += d
        received["server"] = len(got); sender.join(); c.shutdown(socket.SHUT_WR)
    threading.Thread(target=server, daemon=True).start()
    f = E.Forwarder(node, lambda: port, idle_timeout=10, log=lambda m: None); f.start(9292)
    c = lib.tailnet.connect("100.64.0.10", 9292); c.settimeout(10)
    up = threading.Thread(target=lambda: c.sendall(b"C" * SIZE), daemon=True); up.start()
    got = 0
    while got < SIZE:
        d = c.recv(65536)
        if not d: break
        got += len(d)
    up.join(10)
    assert wait_for(lambda: "server" in received, 10)
    assert got == SIZE and received.get("server") == SIZE
    f.stop(); srv.close()

@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_half_close_is_passed_through():
    lib = FakeTailscaleLib(); node = N.NativeTailscale(lib); node.set_authkey(GOOD); node.start()
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]
    def server():
        c, _ = srv.accept()
        data = b""
        while True:                                          # reads until the client half-closes, THEN answers
            d = c.recv(100)
            if not d: break
            data += d
        c.sendall(b"got:" + data); c.close()
    threading.Thread(target=server, daemon=True).start()
    f = E.Forwarder(node, lambda: port, idle_timeout=10, log=lambda m: None); f.start(9292)
    c = lib.tailnet.connect("100.64.0.10", 9292); c.settimeout(5)
    c.sendall(b"request"); c.shutdown(socket.SHUT_WR)
    out = b""
    while True:
        d = c.recv(100)
        if not d: break
        out += d
    assert out == b"got:request"
    f.stop(); srv.close()

@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_concurrent_clients_and_connection_cap(tmp_path):
    api_port, api = echo_server()
    eng, lib = make_engine(tmp_path, port=api_port)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected")
    clients = [lib.tailnet.connect("100.64.0.10", api_port) for _ in range(12)]
    for i, c in enumerate(clients):
        c.sendall(f"hello {i}".encode())
    for i, c in enumerate(clients):
        c.settimeout(3); assert c.recv(32) == f"hello {i}".encode()
    assert wait_for(lambda: eng.status()["forwarded"]["accepted"] == 12) and eng.status()["forwarded"]["active"] == 12
    for c in clients: c.close()
    assert wait_for(lambda: eng.status()["forwarded"]["active"] == 0)
    eng.disconnect(); api.close()

@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_forwarder_refuses_beyond_the_cap_and_survives_a_dead_upstream():
    lib = FakeTailscaleLib(); node = N.NativeTailscale(lib); node.set_authkey(GOOD); node.start()
    api_port, api = echo_server()
    f = E.Forwarder(node, lambda: api_port, max_conns=2, idle_timeout=5, log=lambda m: None)
    f.start(9292)
    cs = [lib.tailnet.connect("100.64.0.10", 9292) for _ in range(4)]
    assert wait_for(lambda: f.stats["accepted"] == 2 and f.stats["refused"] == 2)
    for c in cs: c.close()
    api.close()                                                                         # API goes away
    wait_for(lambda: f.stats["active"] == 0)
    dead = lib.tailnet.connect("100.64.0.10", 9292); dead.settimeout(3)
    assert dead.recv(10) == b"" and wait_for(lambda: f.stats["failed"] >= 1)             # clean close, no hang
    f.stop()

@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_idle_connections_are_closed():
    lib = FakeTailscaleLib(); node = N.NativeTailscale(lib); node.set_authkey(GOOD); node.start()
    api_port, api = echo_server()
    f = E.Forwarder(node, lambda: api_port, idle_timeout=0.6, log=lambda m: None); f.start(9292)
    c = lib.tailnet.connect("100.64.0.10", 9292); c.settimeout(5)
    assert c.recv(10) == b""                                                            # closed by the idle timeout
    f.stop(); api.close()

def test_forwarder_stop_closes_the_listener():
    lib = FakeTailscaleLib(); node = N.NativeTailscale(lib); node.set_authkey(GOOD); node.start()
    f = E.Forwarder(node, lambda: 1, log=lambda m: None); f.start(9292); f.stop()
    assert f._thread is None or not f._thread.is_alive()


# =============================================================================== controller
def test_bad_key_ends_in_needs_auth_and_releases_the_node(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect("authkey", "tskey-auth-WRONG-1234567890")
    assert wait_for(lambda: eng.status()["state"] == "needs_auth")
    st = eng.status()
    assert "did not accept the key" in st["message"] and not st["ip"] and not eng.active or wait_for(lambda: not eng.active)
    assert "close" in lib.calls and not any(c.startswith("listen") for c in lib.calls)
    assert "up" not in lib.calls

def test_no_key_and_no_saved_identity_asks_for_a_key(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect()
    assert wait_for(lambda: eng.status()["state"] == "needs_auth")
    assert "Enter an auth key" in eng.status()["message"]

def test_resume_without_a_key_after_a_restart(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect("authkey", GOOD, "phone"); assert wait_for(lambda: eng.status()["state"] == "connected")
    eng.disconnect()
    assert eng.has_saved_identity()
    eng2, _ = make_engine(tmp_path, lib=lib)                                            # a new process, same state dir
    eng2.connect()                                                                      # no key
    assert wait_for(lambda: eng2.status()["state"] == "connected") and eng2.status()["hostname"] == "phone"
    eng2.disconnect()

def test_api_token_is_used_once_to_mint_a_key_and_never_stored(tmp_path):
    http = Http(body={"key": "tskey-auth-good-MINTED0123456789"})
    eng, lib = make_engine(tmp_path, http=http)
    eng.connect("apikey", API, "phone")
    assert wait_for(lambda: eng.status()["state"] == "connected")
    assert len(http.calls) == 1
    eng.disconnect()
    blob = b""
    for p in tmp_path.rglob("*"):
        if p.is_file(): blob += p.read_bytes()
    assert API.encode() not in blob and b"tskey-auth-good-MINTED" not in blob           # nothing secret on disk
    assert API not in json.dumps(eng.status())

def test_failed_minting_is_an_error_without_the_token(tmp_path):
    eng, lib = make_engine(tmp_path, http=Http(status=401))
    eng.connect("apikey", API)
    assert wait_for(lambda: eng.status()["state"] == "error")
    assert "rejected" in eng.status()["error"] and API not in json.dumps(eng.status()) and not lib.servers

def test_slow_start_then_running(tmp_path):
    eng, lib = make_engine(tmp_path, lib=FakeTailscaleLib(up_delay=0.3))
    eng.connect("authkey", GOOD)
    assert wait_for(lambda: eng.status()["state"] == "starting", 1.0)
    assert wait_for(lambda: eng.status()["state"] == "connected", 3.0)

def test_startup_timeout_is_an_error(tmp_path):
    eng, lib = make_engine(tmp_path, lib=FakeTailscaleLib(up_delay=60), startup_timeout=0.4)
    eng.connect("authkey", GOOD)
    assert wait_for(lambda: eng.status()["state"] == "error")
    assert "Timed out" in eng.status()["error"] and "close" in lib.calls

def test_missing_library_is_reported_and_never_raises(tmp_path):
    eng = E.EmbeddedTailscale(str(tmp_path), lib_loader=lambda: (None, "not included in this build"))
    eng.connect("authkey", GOOD)
    st = eng.status()
    assert st["available"] is False and st["state"] == "unavailable" and "not included" in st["reason"]
    eng.disconnect()

def test_forget_removes_identity_and_secret(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected")
    E.write_secret(str(tmp_path), "authkey", GOOD)
    eng.disconnect(forget=True)
    assert not eng.has_saved_identity() and not (tmp_path / "tsnet").exists() and not (tmp_path / E.SECRET_FILE).exists()

def test_port_change_relistens(tmp_path):
    eng, lib = make_engine(tmp_path, port=9292)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected")
    eng.set_port(9393)
    assert wait_for(lambda: "listen:9393" in lib.calls) and eng.status()["port"] == 9393
    eng.disconnect()

def test_monitor_shows_peers_and_notices_key_expiry(tmp_path):
    lib = FakeTailscaleLib(); lib.tailnet.add_peer("laptop", "100.64.0.5"); lib.tailnet.add_peer("nas", "100.64.0.6", online=False)
    eng, _ = make_engine(tmp_path, lib=lib)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected")
    st = eng.status()
    assert [p["name"] for p in st["peers"]] == ["laptop", "nas"] and st["online_peers"] == 1 and st["peer_count"] == 2   # online first
    lib.tailnet.add_peer("phone2", "100.64.0.7")
    assert wait_for(lambda: eng.status()["peer_count"] == 3)                            # monitor refreshes
    lib.server()["authed"] = False                                                      # key expired on the server side
    assert wait_for(lambda: eng.status()["state"] == "needs_auth")
    assert "sign in again" in eng.status()["message"]
    eng.disconnect()

def test_connecting_twice_runs_only_one_engine(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect("authkey", GOOD); eng.connect("authkey", GOOD)
    assert wait_for(lambda: eng.status()["state"] == "connected")
    time.sleep(0.3)
    assert eng.status()["state"] == "connected"
    live = [s for s in lib.servers.values() if not s["closed"]]
    assert len(live) == 1
    eng.disconnect()

def test_unexpected_errors_in_the_thread_become_an_error_state(tmp_path):
    class Boom(N.NativeTailscale):
        def start(self): raise RuntimeError("kaboom")
    eng = E.EmbeddedTailscale(str(tmp_path), lib_loader=lambda: (FakeTailscaleLib(), ""), node_factory=Boom, poll=0.02, log=lambda m: None)
    eng.connect("authkey", GOOD)
    assert wait_for(lambda: eng.status()["state"] == "error") and "kaboom" in eng.status()["error"]

def test_log_is_private_rotated_and_redacted(tmp_path):
    eng, lib = make_engine(tmp_path)
    (tmp_path / "tsnet.log").write_bytes(b"x" * (E.MAX_LOG_BYTES + 10))
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected")
    assert (tmp_path / "tsnet.log.1").exists()
    if sys.platform != "win32":
        assert stat.S_IMODE((tmp_path / "tsnet.log").stat().st_mode) == 0o600
    with open(tmp_path / "tsnet.log", "a") as f: f.write(f"auth with {GOOD} and {API}\n")
    tail = eng.log_tail()
    assert GOOD not in tail and API not in tail and "tskey-***" in tail and "logging attached" in tail
    eng.disconnect()

def test_state_dir_is_private(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected")
    if sys.platform != "win32":
        assert stat.S_IMODE((tmp_path / "tsnet").stat().st_mode) == 0o700
    eng.disconnect()

def test_parse_status_is_defensive():
    assert E.parse_status({})["backend"] == "" and E.parse_status({})["peers"] == []
    p = E.parse_status({"BackendState": "Running", "TailscaleIPs": ["fd7a::1", "100.1.2.3"], "Peer": {"k": {"DNSName": "box.t.ts.net.", "Online": True}}})
    assert p["ip"] == "100.1.2.3" and p["ip6"] == "fd7a::1" and p["peers"][0]["name"] == "box"


# =============================================================================== command bridge
class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t

def test_up_with_a_secret_connects_and_consumes_it(tmp_path):
    eng, lib = make_engine(tmp_path); clock = Clock(); cmd = E.EmbeddedCommands(eng, str(tmp_path), clock)
    E.write_secret(str(tmp_path), "authkey", GOOD, "Phone")
    cmd.apply({"ts_embedded": "up"}, 9292)
    assert wait_for(lambda: eng.status()["state"] == "connected") and not (tmp_path / E.SECRET_FILE).exists()
    cmd.apply({"ts_embedded": "up"}, 9292); cmd.apply({"ts_embedded": "up"}, 9292)       # repeated ticks change nothing
    assert len([s for s in lib.servers.values() if not s["closed"]]) == 1
    cmd.apply({"ts_embedded": "down"}, 9292)
    assert eng.status()["state"] in ("disabled", "unavailable") and not eng.active

def test_up_without_key_or_identity_asks_once(tmp_path):
    eng, lib = make_engine(tmp_path); cmd = E.EmbeddedCommands(eng, str(tmp_path), Clock())
    for _ in range(5): cmd.apply({"ts_embedded": "up"}, 9292)
    assert eng.status()["state"] == "needs_auth" and not lib.servers                       # nothing started, no thrashing

def test_up_resumes_from_identity_after_a_service_restart(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected"); eng.disconnect()
    eng2, _ = make_engine(tmp_path, lib=lib); cmd = E.EmbeddedCommands(eng2, str(tmp_path), Clock())
    cmd.apply({"ts_embedded": "up"}, 9292)                                                 # sticky restart: request.json says up
    assert wait_for(lambda: eng2.status()["state"] == "connected")
    eng2.disconnect()

def test_a_new_key_replaces_a_running_connection(tmp_path):
    eng, lib = make_engine(tmp_path); cmd = E.EmbeddedCommands(eng, str(tmp_path), Clock())
    E.write_secret(str(tmp_path), "authkey", GOOD, "one"); cmd.apply({"ts_embedded": "up"}, 9292)
    assert wait_for(lambda: eng.status()["state"] == "connected")
    E.write_secret(str(tmp_path), "authkey", "tskey-auth-good-SECOND123456", "two"); cmd.apply({"ts_embedded": "up"}, 9292)
    assert wait_for(lambda: eng.status()["hostname"] == "two" and eng.status()["state"] == "connected")
    assert len([s for s in lib.servers.values() if not s["closed"]]) == 1
    eng.disconnect()

def test_forget_runs_once_per_id(tmp_path):
    eng, lib = make_engine(tmp_path); cmd = E.EmbeddedCommands(eng, str(tmp_path), Clock())
    E.write_secret(str(tmp_path), "authkey", GOOD); cmd.apply({"ts_embedded": "up"}, 9292)
    assert wait_for(lambda: eng.status()["state"] == "connected")
    cmd.apply({"ts_embedded": "down", "ts_forget_id": 1}, 9292)
    assert not eng.has_saved_identity()
    E.write_secret(str(tmp_path), "authkey", GOOD); cmd.apply({"ts_embedded": "up", "ts_forget_id": 1}, 9292)   # same id: not forgotten again
    assert wait_for(lambda: eng.status()["state"] == "connected") and eng.has_saved_identity()
    eng.disconnect()

def test_invalid_key_in_the_secret_is_an_error_and_the_secret_is_still_deleted(tmp_path):
    eng, lib = make_engine(tmp_path); cmd = E.EmbeddedCommands(eng, str(tmp_path), Clock())
    E.write_secret(str(tmp_path), "authkey", "hello world")
    cmd.apply({"ts_embedded": "up"}, 9292)
    assert eng.status()["state"] == "error" and "does not look like" in eng.status()["error"]
    assert not (tmp_path / E.SECRET_FILE).exists() and not lib.servers

def test_transient_errors_are_retried_only_with_a_saved_identity(tmp_path):
    eng, lib = make_engine(tmp_path); clock = Clock(); cmd = E.EmbeddedCommands(eng, str(tmp_path), clock)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected"); eng.disconnect()
    cmd.apply({"ts_embedded": "up"}, 9292); assert wait_for(lambda: eng.status()["state"] == "connected")
    eng._set("error", error="network is unreachable"); eng.disconnect(quiet=True); eng._set("error", error="network is unreachable")
    cmd.apply({"ts_embedded": "up"}, 9292); n = len(lib.servers)
    clock.t = 30; cmd.apply({"ts_embedded": "up"}, 9292); assert len(lib.servers) == n          # too early
    clock.t = 31 + E.EmbeddedCommands.RETRY_SECONDS; cmd.apply({"ts_embedded": "up"}, 9292)
    assert wait_for(lambda: eng.status()["state"] == "connected")
    eng.disconnect()


# =============================================================================== crash guard
def test_crash_guard_blocks_after_repeated_unclean_ends_and_user_can_override(tmp_path):
    clock = {"t": 1000.0}
    def guard(): return E.CrashGuard(str(tmp_path / "g.json"), threshold=3, window=1800, clock=lambda: clock["t"])
    g = guard(); assert not g.blocked
    for i in range(3):                       # three service runs in a row end with the engine still marked active
        g.engine_started(); clock["t"] += 60
        g = guard()                          # the next service process starts and finds the marker
        assert g.unclean_count == i + 1
    assert g.blocked
    g.reset(); assert not g.blocked and not guard().blocked

def test_crash_guard_forgets_old_incidents_and_clean_stops(tmp_path):
    clock = {"t": 0.0}
    mk = lambda: E.CrashGuard(str(tmp_path / "g.json"), threshold=2, window=100, clock=lambda: clock["t"])
    g = mk(); g.engine_started(); clock["t"] = 10; g = mk(); assert g.unclean_count == 1
    clock["t"] = 500; g = mk(); assert g.unclean_count == 0                      # outside the window
    g.engine_started(); clock["t"] = 510; g = mk(); g.engine_started(); g.engine_stopped_cleanly()
    assert mk().unclean_count == 0                                              # a clean stop clears the history
    (tmp_path / "g.json").write_text("garbage"); assert not mk().blocked        # corrupt file never blocks

def test_engine_does_not_resume_automatically_when_blocked(tmp_path):
    eng, lib = make_engine(tmp_path)
    eng.connect("authkey", GOOD); assert wait_for(lambda: eng.status()["state"] == "connected")
    eng.disconnect(quiet=True)                                                  # NOT a clean stop: simulates the service dying
    eng.guard.engine_started()
    for _ in range(3):                                                          # three unclean service lives
        eng2, _ = make_engine(tmp_path, lib=lib)
        eng2.guard.engine_started()
    blocked, _ = make_engine(tmp_path, lib=lib)
    assert blocked.guard.blocked
    n = len(lib.servers)
    blocked.connect()                                                           # automatic resume
    st = blocked.status()
    assert st["state"] == "error" and "ended unexpectedly" in st["error"] and "times" in st["error"] and blocked.guard.unclean_count >= 3 and len(lib.servers) == n
    blocked.connect("authkey", GOOD, user_initiated=True)                       # the user explicitly asks again
    assert wait_for(lambda: blocked.status()["state"] == "connected") and not blocked.guard.blocked
    blocked.disconnect()

def test_commands_treat_a_typed_key_as_user_initiated(tmp_path):
    eng, lib = make_engine(tmp_path)
    for _ in range(3):
        eng.guard.engine_started(); eng.guard = E.CrashGuard(str(tmp_path / "tsnet_guard.json"))
    assert eng.guard.blocked
    cmd = E.EmbeddedCommands(eng, str(tmp_path), Clock())
    E.write_secret(str(tmp_path), "authkey", GOOD, "p")
    cmd.apply({"ts_embedded": "up"}, 9292)
    assert wait_for(lambda: eng.status()["state"] == "connected")
    eng.disconnect()

def test_clean_failures_do_not_count_as_crashes(tmp_path):
    for _ in range(4):
        eng, lib = make_engine(tmp_path)
        eng.connect("authkey", "tskey-auth-WRONG-1234567890")
        assert wait_for(lambda: eng.status()["state"] == "needs_auth")
        time.sleep(0.05)
    assert not E.CrashGuard(str(tmp_path / "tsnet_guard.json")).blocked
