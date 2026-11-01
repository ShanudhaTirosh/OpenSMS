"""
Integration test against the REAL libtailscale (Linux host build) and Tailscale's own in-process test control server.
Skipped unless OPENSMS_REAL_TS_DIR points at a directory containing libtailscale.so and libtstestcontrol.so
(the `native-tailscale` CI job builds them). It proves the Python glue works with the real C library; it does not
prove anything about Android.
"""
import os, socket, subprocess, sys, textwrap, threading, time
from pathlib import Path
import pytest

LIBDIR = os.environ.get("OPENSMS_REAL_TS_DIR")
pytestmark = pytest.mark.skipif(not LIBDIR or not (Path(LIBDIR or "x") / "libtailscale.so").exists(),
                                reason="real libtailscale not available (set OPENSMS_REAL_TS_DIR)")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

CONTROL = textwrap.dedent('''
    import ctypes, sys
    lib = ctypes.CDLL(sys.argv[1])
    buf = ctypes.create_string_buffer(4096)
    if lib.RunControl(buf, 4096) != 0:
        print("FAILED"); sys.exit(1)
    print("URL=" + buf.value.decode(), flush=True)
    sys.stdin.read()                       # run until the test closes our stdin
    lib.StopControl()
''')


@pytest.fixture(scope="module")
def control_url():
    p = subprocess.Popen([sys.executable, "-c", CONTROL, str(Path(LIBDIR) / "libtstestcontrol.so")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    line = p.stdout.readline().strip()
    assert line.startswith("URL="), line
    yield line[4:]
    p.stdin.close()
    p.wait(timeout=20)


def wait_for(pred, secs=60):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred():
            return True
        time.sleep(0.25)
    return False


def test_two_real_nodes_and_the_forwarder_end_to_end(tmp_path, control_url):
    from services import tsNative as N, tsEmbed as E
    lib, reason = None, ""
    os.environ["OPENSMS_TS_LIB"] = str(Path(LIBDIR) / "libtailscale.so")
    lib, reason = N.load_library()
    assert lib is not None, reason

    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5); api_port = srv.getsockname()[1]
    def echo():
        while True:
            try: c, _ = srv.accept()
            except OSError: return
            def h(c=c):
                while True:
                    d = c.recv(65536)
                    if not d: break
                    c.sendall(d)
                c.close()
            threading.Thread(target=h, daemon=True).start()
    threading.Thread(target=echo, daemon=True).start()

    # node A = the built-in engine of this app; the test control server needs no key
    eng = E.EmbeddedTailscale(str(tmp_path / "a"), lib_loader=lambda: (lib, ""), port=api_port, startup_timeout=90, poll=0.5)
    os.makedirs(tmp_path / "a", exist_ok=True)
    eng.connect(None, None, "opensms-a", control_url)
    assert wait_for(lambda: eng.status()["state"] in ("connected", "error", "needs_auth")), eng.status()
    st = eng.status()
    assert st["state"] == "connected", st
    assert st["ip"] and st["hostname"] == "opensms-a"

    # node B = another tailnet device that dials A's address
    b = N.NativeTailscale(lib)
    b.set_dir(str(tmp_path / "b")); b.set_hostname("device-b"); b.set_control_url(control_url); b.start()
    assert wait_for(lambda: E.parse_status(b.status_json())["backend"] == "Running")
    assert wait_for(lambda: any(p["name"] == "opensms-a" for p in E.parse_status(b.status_json())["peers"]))
    sock = b.socket_from_fd(b.dial("tcp", f"{st['ip']}:{api_port}"))
    sock.settimeout(30)
    sock.sendall(b"through the tailnet")
    assert sock.recv(100) == b"through the tailnet"
    payload = os.urandom(2_000_000); sock.sendall(payload); got = b""
    while len(got) < len(payload): got += sock.recv(65536)
    assert got == payload
    sock.close()

    assert wait_for(lambda: any(p["name"] == "device-b" for p in eng.status()["peers"]), 30)   # A sees B as a peer
    assert eng.status()["forwarded"]["accepted"] >= 1
    eng.disconnect(); b.close(); srv.close()
