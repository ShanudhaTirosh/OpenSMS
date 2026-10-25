"""ARCH-01: request-file watcher (no needless reads, back-off) and concurrent atomic writes."""
import json, os, sys, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from services.reqWatch import RequestWatcher
from services.pathMgr import atomic_write_json


def write(p, obj):
    atomic_write_json(str(p), obj)


def test_reads_only_when_the_file_changes(tmp_path):
    p = tmp_path / "request.json"
    w = RequestWatcher(str(p))
    reads = []
    orig = w._read
    w._read = lambda: (reads.append(1), orig())[1]
    assert w.poll() is None and reads == []                       # missing file: nothing to read
    write(p, {"server": "start", "port": 9292})
    assert w.poll() == {"server": "start", "port": 9292} and len(reads) == 1
    for _ in range(50):
        assert w.poll() is None                                  # unchanged: no read at all
    assert len(reads) == 1
    write(p, {"server": "stop", "port": 9292, "bind": "all"})    # different size -> detected
    assert w.poll()["server"] == "stop" and len(reads) == 2

def test_same_size_rewrite_is_detected_through_mtime(tmp_path):
    p = tmp_path / "request.json"; w = RequestWatcher(str(p))
    write(p, {"port": 1111}); assert w.poll() == {"port": 1111}
    st = os.stat(p)
    write(p, {"port": 2222})                                      # same byte length
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    assert w.poll() == {"port": 2222}

def test_half_written_or_invalid_file_is_retried(tmp_path):
    p = tmp_path / "request.json"; w = RequestWatcher(str(p))
    p.write_text('{"server": "sta')                              # torn write
    assert w.poll() is None
    p.write_text('["not", "a", "dict"]')
    assert w.poll() is None
    write(p, {"server": "start"})
    assert w.poll() == {"server": "start"}                       # recovered, nothing lost

def test_polling_backs_off_when_idle_and_resets_on_activity(tmp_path):
    now = [0.0]
    p = tmp_path / "request.json"
    w = RequestWatcher(str(p), fast=0.2, slow=1.0, idle_after=10.0, clock=lambda: now[0])
    assert w.next_sleep() == 0.2
    now[0] = 9.9; assert w.next_sleep() == 0.2
    now[0] = 10.1; assert w.next_sleep() == 1.0                   # idle: poll slowly
    write(p, {"server": "start"}); assert w.poll()                # a command arrives
    assert w.next_sleep() == 0.2                                  # fast again
    now[0] = 25.0; assert w.next_sleep() == 1.0

def test_concurrent_writers_never_corrupt_the_file_or_leave_temp_files(tmp_path, capsys):
    p = tmp_path / "config.json"
    write(p, {"n": -1})
    stop = threading.Event(); bad = []

    def reader():
        while not stop.is_set():
            try:
                json.loads(p.read_text())
            except (ValueError, OSError) as e:
                bad.append(repr(e))

    def writer(i):
        for j in range(40):
            write(p, {"writer": i, "n": j, "pad": "x" * (i * 37)})

    rt = threading.Thread(target=reader); rt.start()
    ws = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
    [t.start() for t in ws]; [t.join() for t in ws]
    stop.set(); rt.join()
    assert bad == [], bad[:3]
    assert "Error atomic writing" not in capsys.readouterr().out
    assert sorted(x.name for x in tmp_path.iterdir()) == ["config.json"]       # no leftover .tmp files
    assert json.loads(p.read_text())["n"] == 39

def test_failed_write_cleans_up_its_temp_file(tmp_path, monkeypatch, capsys):
    p = tmp_path / "x.json"
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    write(p, {"a": 1})
    assert "Error atomic writing" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


# ---------------- the real service loop, end to end (subprocess: appSvc has import side effects) ----------------
import socket, subprocess, textwrap
APP = str(Path(__file__).resolve().parent.parent / "app")
LOOP = textwrap.dedent('''
    import sys, json, time, threading, socket
    sys.path.insert(0, %r)
    import services.appSvc as A
    from services.pathMgr import atomic_write_json
    port = int(sys.argv[1])
    A._req_watcher.idle_after = 0.0                     # worst case: already in slow (1 s) polling mode
    threading.Thread(target=A.app_service_thread, daemon=True).start()
    def reach():
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close(); return True
        except OSError:
            return False
    def wait(cond, secs):
        t0 = time.time()
        while time.time() - t0 < secs:
            if cond(): return round(time.time() - t0, 2)
            time.sleep(0.05)
        return None
    atomic_write_json(A.req_file, {"server": "start", "port": port, "bind": "localhost"})
    up = wait(reach, 8)
    resp = json.load(open(A.resp_file)) if up is not None else {}
    atomic_write_json(A.req_file, {"server": "stop", "port": port, "bind": "localhost"})
    down = wait(lambda: not reach(), 8)
    print("RESULT" + json.dumps({"up_after": up, "down_after": down, "resp_server": resp.get("server")}))
''' % APP)


def test_service_loop_starts_and_stops_the_server_from_the_request_file(tmp_path):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path), "OPENSMS_ALLOW_SIMULATION": "1"}
    r = subprocess.run([sys.executable, "-c", LOOP, str(port)], capture_output=True, text=True, env=env, timeout=90, cwd=tmp_path)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    assert line, r.stdout + r.stderr
    out = json.loads(line[0][6:])
    assert out["up_after"] is not None and out["up_after"] < 4, out          # command picked up despite slow polling
    assert out["resp_server"] == "started"
    assert out["down_after"] is not None and out["down_after"] < 4, out
