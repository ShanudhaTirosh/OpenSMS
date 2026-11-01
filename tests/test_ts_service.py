"""The built-in Tailscale inside the REAL service loop (fake C library): connect, reach the real API, resume, disconnect."""
import json, os, socket, subprocess, sys, textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP, TESTS = str(ROOT / "app"), str(ROOT / "tests")

LOOP = textwrap.dedent('''
    import sys, json, time, threading, socket, os
    sys.path.insert(0, %r); sys.path.insert(0, %r)
    import services.appSvc as A
    from services.pathMgr import atomic_write_json
    from services import tsEmbed as E
    threading.Thread(target=A.app_service_thread, daemon=True).start()
    port = int(sys.argv[1]); bind = sys.argv[2]
    def resp():
        try: return json.load(open(A.resp_file))
        except Exception: return {}
    def wait(cond, secs=15):
        t0 = time.time()
        while time.time() - t0 < secs:
            if cond(): return True
            time.sleep(0.1)
        return False
    out = {}
    # 1. the UI asks for the API server and the built-in node, leaving the key in the one-shot file
    E.write_secret(A.config_dir, "authkey", "tskey-auth-good-ABCDEFGH1234", "Phone Svc", "")
    req = {"server": "start", "port": port, "bind": bind, "wakelock": False, "ts_embedded": "up", "ts_forget_id": 0}
    atomic_write_json(A.req_file, req)
    out["connected"] = wait(lambda: (resp().get("ts_embedded") or {}).get("state") == "connected")
    out["server_up"] = wait(lambda: resp().get("server") == "started")
    st = resp().get("ts_embedded") or {}
    out["ip"], out["hostname"], out["host"] = st.get("ip"), st.get("hostname"), resp().get("host")
    out["secret_left"] = os.path.exists(os.path.join(A.config_dir, E.SECRET_FILE))
    out["key_in_resp"] = "tskey-" in json.dumps(resp()) or "tskey-" in open(A.req_file).read()
    # 2. another tailnet device calls the REAL API through the node's forwarder
    lib = A.ts_engine._lib
    c = lib.tailnet.connect(st.get("ip"), port, from_ip="100.64.0.55"); c.settimeout(10)
    c.sendall(b"GET /health/ HTTP/1.1\\r\\nHost: x\\r\\nConnection: close\\r\\n\\r\\n")
    data = b""
    while True:
        d = c.recv(65536)
        if not d: break
        data += d
    out["http"] = data.split(b"\\r\\n", 1)[0].decode()
    out["body_ok"] = b'"status":"online"' in data or b'"status": "online"' in data
    # 3. simulate the service being restarted (sticky): a new engine resumes from the saved identity, no key
    A.ts_engine.disconnect()
    out["identity_kept"] = A.ts_engine.has_saved_identity()
    atomic_write_json(A.req_file, {**req, "server": "start"})
    A.ts_commands._desired_seen = "down"
    out["resumed"] = wait(lambda: (resp().get("ts_embedded") or {}).get("state") == "connected")
    # 4. the user turns it off, then forgets the device
    atomic_write_json(A.req_file, {**req, "ts_embedded": "down"})
    out["disabled"] = wait(lambda: (resp().get("ts_embedded") or {}).get("state") in ("disabled", "unavailable"))
    atomic_write_json(A.req_file, {**req, "ts_embedded": "down", "ts_forget_id": 1})
    out["forgotten"] = wait(lambda: not A.ts_engine.has_saved_identity())
    print("RESULT" + json.dumps(out))
''' % (APP, TESTS))


def run(tmp_path, bind):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path), "OPENSMS_ALLOW_SIMULATION": "1",
           "OPENSMS_TS_FAKE": "fake_tailscale:make_fake"}
    r = subprocess.run([sys.executable, "-c", LOOP, str(port), bind], capture_output=True, text=True, env=env, timeout=120, cwd=tmp_path)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    assert line, r.stdout[-2000:] + r.stderr[-2000:]
    return json.loads(line[0][6:])


@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_full_lifecycle_in_the_service_loop(tmp_path):
    out = run(tmp_path, "localhost")
    assert out["connected"] and out["server_up"], out
    assert out["ip"] == "100.64.0.10" and out["hostname"] == "phone-svc", out
    assert out["secret_left"] is False and out["key_in_resp"] is False, out          # the key never reaches request/response files
    assert out["http"] == "HTTP/1.1 200 OK" and out["body_ok"], out                  # a tailnet device reached the REAL API
    assert out["identity_kept"] and out["resumed"], out
    assert out["disabled"] and out["forgotten"], out


@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds required")
def test_tailscale_only_mode_binds_loopback_when_the_builtin_node_is_connected(tmp_path):
    out = run(tmp_path, "tailscale")
    assert out["connected"] and out["server_up"] and out["host"] == "127.0.0.1", out  # no VPN, no tailnet IP on the phone, still starts
    assert out["http"] == "HTTP/1.1 200 OK", out
