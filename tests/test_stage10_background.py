"""The gateway keeps running when the app closes and only stops when the user stops it."""
import ast, json, os, socket, subprocess, sys, textwrap
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from services.lifecycle import desired_server_state, initial_request, resp_is_fresh, wakelock_wanted, FRESH_SECONDS, HEARTBEAT_SECONDS
from services.wakeLock import WakeLockController


# ---------------- pure lifecycle rules ----------------
@pytest.mark.parametrize("cfg,want", [
    ({}, "stop"), ({"server_desired": "stop"}, "stop"), ({"server_desired": "start"}, "start"),
    ({"boot": True}, "start"), ({"boot": True, "server_desired": "stop"}, "start"), ({"server_desired": "bogus"}, "stop"),
])
def test_desired_state(cfg, want):
    assert desired_server_state(cfg) == want

def test_reopening_the_app_restores_the_last_choice_instead_of_forcing_stop():
    running = initial_request({"server_desired": "start", "wakelock": False}, 9393, "tailscale")
    assert running == {"port": 9393, "server": "start", "bind": "tailscale", "wakelock": False}
    assert initial_request({}, 9292, "all")["server"] == "stop"
    assert initial_request({}, 9292, "all")["wakelock"] is True                     # default on

def test_status_freshness():
    assert resp_is_fresh({"ts": 100.0}, now=105.0)
    assert resp_is_fresh({"ts": 100.0}, now=100.0 + FRESH_SECONDS)
    assert not resp_is_fresh({"ts": 100.0}, now=100.0 + FRESH_SECONDS + 0.1)       # service died: not trusted
    assert not resp_is_fresh({"ts": 200.0}, now=100.0)                              # clock went backwards
    for bad in (None, {}, {"server": "started"}, {"ts": "x"}, [], "ts"):
        assert not resp_is_fresh(bad, now=1.0)
    assert HEARTBEAT_SECONDS * 3 < FRESH_SECONDS                                    # several missed beats before "stale"

def test_wakelock_only_while_the_server_runs_and_the_setting_is_on():
    assert wakelock_wanted(True, {}) and wakelock_wanted(True, {"wakelock": True})
    assert not wakelock_wanted(True, {"wakelock": False})
    assert not wakelock_wanted(False, {"wakelock": True})


# ---------------- wake lock controller ----------------
class FakeLock:
    def __init__(self): self.acquired = 0; self.released = 0; self.held = False
    def acquire(self): self.acquired += 1; self.held = True
    def release(self): self.released += 1; self.held = False
    def isHeld(self): return self.held

def test_wakelock_acquired_once_and_released_once():
    made = []
    def factory(): made.append(FakeLock()); return made[-1]
    c = WakeLockController(factory)
    for _ in range(5): c.update(True)
    assert len(made) == 1 and made[0].acquired == 1 and c.held
    for _ in range(5): c.update(False)
    assert made[0].released == 1 and not c.held
    c.update(True)
    assert len(made) == 2 and made[1].acquired == 1                                  # a new session gets a new lock

def test_wakelock_failures_never_propagate():
    def boom(): raise RuntimeError("no PowerManager")
    c = WakeLockController(boom); c.update(True); assert not c.held                  # retried on the next update
    c = WakeLockController(lambda: None); c.update(True); assert not c.held
    class BadRelease(FakeLock):
        def release(self): raise RuntimeError("already released")
    c = WakeLockController(BadRelease); c.update(True); c.update(False); assert not c.held

def test_wakelock_not_released_if_not_held():
    lock = FakeLock()
    c = WakeLockController(lambda: lock); c.update(True); lock.held = False; c.update(False)
    assert lock.released == 0                                                         # isHeld() False -> no double release


# ---------------- build + app configuration ----------------
def test_service_is_sticky_and_not_a_timed_datasync_service():
    spec = (APP / "buildozer.spec").read_text()
    line = next(l for l in spec.splitlines() if l.startswith("services ="))
    opts = line.split(":")
    assert "foreground" in opts and "sticky" in opts                                  # restarted by Android; survives swipe-away
    assert "foregroundServiceType=specialUse" in opts
    assert "dataSync" not in line and "FOREGROUND_SERVICE_DATA_SYNC" not in spec      # Android 15+: dataSync stops after 6 h
    assert "android.permission.FOREGROUND_SERVICE_SPECIAL_USE" in spec

def test_closing_the_app_does_not_stop_the_service():
    tree = ast.parse((APP / "main.py").read_text())
    on_stop = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "on_stop")
    called = {c.func.attr for c in ast.walk(on_stop) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "stop_service" not in called

def test_only_the_stop_button_stops_the_service():
    tree = ast.parse((APP / "main.py").read_text())
    callers = set()
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for c in ast.walk(fn):
            if isinstance(c, ast.Attribute) and c.attr == "stop_service":
                callers.add(fn.name)
    assert callers == {"resp_check_loop"}, callers          # only the status loop, and only after the user's Stop (flag below)
    src = (APP / "main.py").read_text()
    assert "_stop_service_when_stopped = platform == \"android\"" in src             # set only in the user's Stop path

def test_launch_restores_state_and_keeps_the_status_file():
    src = (APP / "main.py").read_text()
    assert "initial_request(" in src
    on_start = src[src.index("    def on_start(self):"):src.index("    def update_network_addresses")]
    assert "os.remove(self.resp_path)" not in on_start                                # a running service's status must survive a relaunch
    assert on_start.count("self.write_request()") == 1                                # written once, after the settings are loaded


# ---------------- the real service loop ----------------
LOOP = textwrap.dedent('''
    import sys, json, time, threading, socket
    sys.path.insert(0, %r)
    import services.appSvc as A
    from services.pathMgr import atomic_write_json
    from services.lifecycle import initial_request, resp_is_fresh
    threading.Thread(target=A.app_service_thread, daemon=True).start()
    port = int(sys.argv[1])
    def reach():
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close(); return True
        except OSError:
            return False
    def wait(cond, secs):
        t0 = time.time()
        while time.time() - t0 < secs:
            if cond(): return True
            time.sleep(0.05)
        return False
    cfg = {"server_desired": "start", "wakelock": True}
    req = initial_request(cfg, port, "localhost")
    atomic_write_json(A.req_file, req)
    up = wait(reach, 8)
    # heartbeat: the status file's timestamp keeps advancing while the service idles
    stamps = set()
    t0 = time.time()
    while time.time() - t0 < 7.5:
        try: stamps.add(json.load(open(A.resp_file))["ts"])
        except Exception: pass
        time.sleep(0.25)
    fresh = resp_is_fresh(json.load(open(A.resp_file)))
    # the user closes and reopens the app: it rewrites the same request. The server must not blink.
    gaps = 0
    for _ in range(3):
        atomic_write_json(A.req_file, initial_request(cfg, port, "localhost"))
        t1 = time.time()
        while time.time() - t1 < 1.2:
            if not reach(): gaps += 1
            time.sleep(0.05)
    still_up = reach()
    # the user presses Stop
    atomic_write_json(A.req_file, {**req, "server": "stop"})
    stopped = wait(lambda: not reach(), 8)
    print("RESULT" + json.dumps({"up": up, "heartbeats": len(stamps), "fresh": fresh, "gaps": gaps, "still_up": still_up, "stopped": stopped}))
''' % str(APP))


def test_service_heartbeats_and_survives_the_app_reopening(tmp_path):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path), "OPENSMS_ALLOW_SIMULATION": "1"}
    r = subprocess.run([sys.executable, "-c", LOOP, str(port)], capture_output=True, text=True, env=env, timeout=120, cwd=tmp_path)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    assert line, r.stdout + r.stderr
    out = json.loads(line[0][6:])
    assert out["up"] is True, out
    assert out["heartbeats"] >= 2 and out["fresh"] is True, out                      # ~every 3 s, so >= 2 distinct stamps in 7.5 s
    assert out["gaps"] == 0 and out["still_up"] is True, out                         # reopening the app never interrupts the server
    assert out["stopped"] is True, out                                               # ...but Stop really stops it
