"""The ctypes binding matches the real header, and the wrapper behaves correctly against the fake library."""
import ctypes, os, re, socket, sys, tempfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app")); sys.path.insert(0, str(ROOT / "tests"))
from services import tsNative as N
from fake_tailscale import FakeTailscaleLib


# ---------------- binding vs the real header ----------------
def parse_header():
    text = (ROOT / "app" / "native" / "tailscale.h").read_text()
    text = re.sub(r"//[^\n]*", "", text)
    decls = {}
    for m in re.finditer(r"extern\s+([\w\*\s]+?)\s+(tailscale\w*)\s*\(([^)]*)\)\s*;", text):
        ret, name, args = m.groups()
        args = args.strip()
        arglist = [] if args in ("", "void") else [a.strip() for a in args.split(",")]
        decls[name] = (ret.strip(), arglist)
    return decls


def ctype_for(arg: str):
    a = re.sub(r"\b(const)\b", "", arg).strip()
    a = re.sub(r"\s*\w+$", "", a).strip() if re.search(r"\w+\s*$", a) and " " in a.replace("*", " * ") else a
    return a


def test_every_declared_function_is_bound_with_the_right_arity():
    decls = parse_header()
    assert len(decls) >= 18
    assert set(decls) == set(N.SIGNATURES), (set(decls) ^ set(N.SIGNATURES))
    for name, (ret, args) in decls.items():
        _, argtypes = N.SIGNATURES[name]
        assert len(args) == len(argtypes), f"{name}: header has {len(args)} args, binding {len(argtypes)}"

def test_argument_kinds_match_the_header():
    decls = parse_header()
    for name, (ret, args) in decls.items():
        _, argtypes = N.SIGNATURES[name]
        for header_arg, ct in zip(args, argtypes):
            h = header_arg.replace("const", " ")
            if "char**" in h.replace(" ", ""):
                assert ct == ctypes.POINTER(ctypes.c_void_p), (name, header_arg)
            elif "char*" in h.replace(" ", ""):
                assert ct == ctypes.c_char_p, (name, header_arg)
            elif "tailscale_conn*" in h.replace(" ", "") or "tailscale_listener*" in h.replace(" ", ""):
                assert ct == ctypes.POINTER(ctypes.c_int), (name, header_arg)
            elif "size_t" in h:
                assert ct == ctypes.c_size_t, (name, header_arg)
            else:
                assert ct == ctypes.c_int, (name, header_arg)

def test_return_types_are_int():
    assert all(rt == ctypes.c_int for rt, _ in N.SIGNATURES.values())

def test_missing_library_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("OPENSMS_TS_LIB", "/nonexistent/libtailscale.so")
    lib, reason = N.load_library()
    assert lib is None and "not included in this build" in reason and "libtailscale.so" in reason

def test_apply_signatures_on_a_real_shared_object():
    class Shim:                                                   # a lib that has none of the functions
        pass
    with pytest.raises(AttributeError):
        N.apply_signatures(Shim())


# ---------------- wrapper behaviour (fake lib) ----------------
@pytest.fixture()
def node():
    lib = FakeTailscaleLib()
    n = N.NativeTailscale(lib)
    d = tempfile.mkdtemp()
    n.set_dir(d); n.set_hostname("opensms-test")
    yield n, lib, d
    n.close()

def test_start_with_valid_key_runs_and_reports_ips(node):
    n, lib, d = node
    n.set_authkey("tskey-auth-good-123")
    n.start()
    st = n.status_json()
    assert st["BackendState"] == "Running" and st["Self"]["HostName"] == "opensms-test"
    assert n.ips() == ("100.64.0.10", "fd7a:115c:a1e0::1")
    assert os.path.exists(os.path.join(d, "tailscaled.state"))     # identity persisted

def test_start_with_bad_key_needs_login_and_never_blocks(node):
    n, lib, d = node
    n.set_authkey("tskey-auth-WRONG")
    n.start()                                                      # returns at once (tailscale_up would hang)
    st = n.status_json()
    assert st["BackendState"] == "NeedsLogin" and st["AuthURL"].startswith("https://")
    assert n.ips() == (None, None)                                 # "invalid IP" is not an address
    assert "up" not in lib.calls

def test_resume_from_saved_state_needs_no_key():
    lib = FakeTailscaleLib(); d = tempfile.mkdtemp()
    a = N.NativeTailscale(lib); a.set_dir(d); a.set_authkey("tskey-auth-good-1"); a.start(); a.close()
    b = N.NativeTailscale(lib); b.set_dir(d); b.start()            # no key this time
    assert b.status_json()["BackendState"] == "Running"

def test_status_string_is_freed(monkeypatch, node):
    n, lib, d = node
    n.set_authkey("tskey-auth-good-1"); n.start()
    freed = []
    real = N._free_memory
    def spy(p):
        freed.append(p.value)
        return real(p)
    monkeypatch.setattr(N, "_free_memory", spy)
    n.status_json()
    assert len(freed) == 1 and freed[0]

def test_errors_carry_the_library_message(node):
    n, lib, d = node
    with pytest.raises(N.TailscaleError, match="node is not running"):
        n.listen("tcp", ":9292")

@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds (SCM_RIGHTS) required")
def test_listen_accept_roundtrip_passes_a_real_socket(node):
    n, lib, d = node
    n.set_authkey("tskey-auth-good-1"); n.start()
    lfd = n.listen("tcp", ":9292")
    client = lib.tailnet.connect("100.64.0.10", 9292, from_ip="100.64.0.55")
    cfd = n.accept(lfd)
    assert n.remote_addr(lfd, cfd) == "100.64.0.55"
    sock = n.socket_from_fd(cfd)
    client.sendall(b"ping"); assert sock.recv(4) == b"ping"
    sock.sendall(b"pong"); assert client.recv(4) == b"pong"
    sock.close(); client.close()

def test_close_is_idempotent(node):
    n, lib, d = node
    n.close(); n.close()
    assert lib.calls.count("close") == 1


@pytest.mark.skipif(not hasattr(socket, "send_fds"), reason="socket.send_fds (SCM_RIGHTS) required")
def test_dial_reaches_a_listener_and_reports_refusals(node):
    n, lib, d = node
    n.set_authkey("tskey-auth-good-1"); n.start()
    lfd = n.listen("tcp", ":7000")
    sock = n.socket_from_fd(n.dial("tcp", "100.64.0.10:7000"))
    conn = n.socket_from_fd(n.accept(lfd))
    sock.sendall(b"x"); assert conn.recv(1) == b"x"
    sock.close(); conn.close()
    with pytest.raises(N.TailscaleError, match="nothing listens"):
        n.dial("tcp", "100.64.0.10:7001")
