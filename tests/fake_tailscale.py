"""
A stand-in for libtailscale used by the tests. It implements the C API of app/native/tailscale.h with the same
observable behaviour as the real library (as read from its Go source):

  * calls return 0 on success, non-zero on failure, and tailscale_errmsg returns the last message
  * tailscale_start() returns immediately; BackendState then moves Starting -> Running, or stays NeedsLogin
    when no valid key / saved state exists. tailscale_up() would block, so tests assert nobody calls it
  * a listener is one end of a socketpair; every accepted connection is delivered as a fixed 64-byte NUL-padded
    address record plus a file descriptor (SCM_RIGHTS), exactly like the real library
  * tailscale_status_json returns a malloc()ed string the caller must free()
  * a node resumes without a key when its state directory holds a saved identity

It is NOT the real library: nothing here proves behaviour on Android or against Tailscale's servers.
"""
import ctypes
import json
import os
import socket
import sys
import threading
import time

RECORD = 64
GOOD_KEY_PREFIX = "tskey-auth-good"
if sys.platform == "win32":
    _libc = ctypes.cdll.msvcrt
else:
    _libc = ctypes.CDLL(None)
_libc.malloc.restype = ctypes.c_void_p
_libc.malloc.argtypes = [ctypes.c_size_t]


class FakeTailnet:
    """Shared 'network': nodes register their listeners; tests act as other tailnet devices."""

    def __init__(self):
        self.listeners = {}          # (ip, port) -> (python socket for the Go side)
        self.peers = {}              # peer name -> dict(ip, online, os)
        self._next = 1

    def add_peer(self, name, ip, online=True, os_name="linux"):
        self.peers[name] = {"ip": ip, "online": online, "os": os_name}

    def connect(self, ip, port, from_ip="100.64.0.77"):
        """Another device dials ip:port. Returns the client end (a socket) or raises ConnectionRefusedError."""
        if not hasattr(socket, "send_fds"):
            raise NotImplementedError("socket.send_fds is only supported on Unix")
        go_side = self.listeners.get((ip, port))
        if go_side is None:
            raise ConnectionRefusedError(f"nothing listens on {ip}:{port}")
        client, server_end = socket.socketpair()
        record = from_ip.encode().ljust(RECORD, b"\0")
        socket.send_fds(go_side, [record], [server_end.fileno()])
        server_end.close()                               # now owned by the receiver (like syscall.Close after Sendmsg)
        return client


class FakeTailscaleLib:
    def __init__(self, tailnet=None, auto_ip="100.64.0.10", up_delay=0.0, valid_prefix=GOOD_KEY_PREFIX):
        self.tailnet = tailnet or FakeTailnet()
        self.servers = {}
        self.auto_ip = auto_ip
        self.up_delay = up_delay
        self.valid_prefix = valid_prefix
        self.calls = []
        self._lock = threading.Lock()
        self._next_sd = 1
        self._listener_socks = {}

    # --- test helpers
    def server(self, sd=None):
        return self.servers[sd] if sd else next(iter(self.servers.values()))

    def _s(self, sd):
        return self.servers.get(sd)

    @staticmethod
    def _text(v):
        return v.decode() if isinstance(v, (bytes, bytearray)) else v.value.decode() if hasattr(v, "value") else str(v)

    def _fail(self, s, msg):
        s["err"] = msg
        return -1

    # --- C API
    def tailscale_new(self):
        with self._lock:
            sd = self._next_sd; self._next_sd += 1
            self.servers[sd] = {"dir": "", "hostname": "", "authkey": "", "control": "", "ephemeral": 0, "logfd": -1,
                                "started": False, "closed": False, "err": "", "t0": None, "listeners": [], "authed": False}
        self.calls.append("new")
        return sd

    def _setter(self, sd, field, value):
        s = self._s(sd)
        if s is None:
            return 9
        s[field] = self._text(value) if isinstance(value, (bytes, bytearray)) else value
        self.calls.append("set_" + field)
        return 0

    def tailscale_set_dir(self, sd, v): return self._setter(sd, "dir", v)
    def tailscale_set_hostname(self, sd, v): return self._setter(sd, "hostname", v)
    def tailscale_set_authkey(self, sd, v): return self._setter(sd, "authkey", v)
    def tailscale_set_control_url(self, sd, v): return self._setter(sd, "control", v)
    def tailscale_set_ephemeral(self, sd, v): return self._setter(sd, "ephemeral", v)
    def tailscale_set_logfd(self, sd, fd):
        s = self._s(sd)
        if s is None: return 9
        s["logfd"] = fd
        if fd >= 0:
            os.write(fd, b"fake tsnet: logging attached\n")
        return 0

    def _state_file(self, s):
        return os.path.join(s["dir"], "tailscaled.state") if s["dir"] else None

    def tailscale_start(self, sd):
        s = self._s(sd)
        if s is None: return 9
        self.calls.append("start")
        if s["started"]:
            return 0
        s["started"] = True
        s["t0"] = time.monotonic()
        sf = self._state_file(s)
        if sf and os.path.exists(sf):
            s["authed"] = True                                # resume: identity is on disk
        elif s["authkey"].startswith(self.valid_prefix):
            s["authed"] = True
            if sf:
                os.makedirs(s["dir"], exist_ok=True)
                with open(sf, "w") as f:
                    f.write("fake-node-identity")
        return 0

    def tailscale_up(self, sd):                               # blocks forever for a bad key in the real library
        raise AssertionError("tailscale_up must not be used: it cannot be cancelled")

    def tailscale_close(self, sd):
        s = self._s(sd)
        if s is None: return 9
        self.calls.append("close")
        s["closed"] = True
        for fd in list(s["listeners"]):
            try: os.close(fd)
            except OSError: pass
        s["listeners"].clear()
        for key in [k for k, v in self.tailnet.listeners.items() if v in self._listener_socks.values()]:
            pass
        for k in [k for k in self.tailnet.listeners if k[0] == self._ip_for(s)]:
            self.tailnet.listeners.pop(k, None)
        return 0

    # --- node state
    def _ip_for(self, s):
        return self.auto_ip

    def _backend_state(self, s):
        if not s["started"]:
            return "NoState"
        if not s["authed"]:
            return "NeedsLogin"
        if time.monotonic() - s["t0"] < self.up_delay:
            return "Starting"
        return "Running"

    def tailscale_getips(self, sd, buf, buflen):
        s = self._s(sd)
        if s is None: return 9
        ip = self._ip_for(s) if self._backend_state(s) == "Running" else "invalid IP"
        text = f"{ip},{'fd7a:115c:a1e0::1' if ip != 'invalid IP' else 'invalid IP'}".encode()
        ctypes.memmove(buf, text + b"\0", len(text) + 1)
        return 0

    def tailscale_status_json(self, sd, out):
        s = self._s(sd)
        if s is None: return 9
        if s["closed"]:
            return self._fail(s, "server closed")
        state = self._backend_state(s)
        running = state == "Running"
        ip = self._ip_for(s)
        body = {
            "BackendState": state,
            "AuthURL": "" if state != "NeedsLogin" else "https://login.tailscale.com/a/abc123",
            "TailscaleIPs": [ip, "fd7a:115c:a1e0::1"] if running else None,
            "Self": {"HostName": s["hostname"], "DNSName": f"{s['hostname']}.tailnet-x.ts.net.",
                     "TailscaleIPs": [ip, "fd7a:115c:a1e0::1"] if running else None, "Online": running, "OS": "android"},
            "CurrentTailnet": {"Name": "example.com", "MagicDNSSuffix": "tailnet-x.ts.net"} if running else None,
            "Peer": {f"nodekey:{i:04d}": {"HostName": n, "DNSName": f"{n}.tailnet-x.ts.net.", "TailscaleIPs": [p["ip"]],
                                          "Online": p["online"], "OS": p["os"]}
                     for i, (n, p) in enumerate(self.tailnet.peers.items())} if running else {},
            "Health": [],
        }
        data = json.dumps(body).encode()
        ptr = _libc.malloc(len(data) + 1)
        ctypes.memmove(ptr, data + b"\0", len(data) + 1)
        out._obj.value = ptr                                    # the caller must free() this
        return 0

    def tailscale_errmsg(self, sd, buf, buflen):
        s = self._s(sd)
        if s is None: return 9
        data = s["err"].encode()[: buflen - 1]
        ctypes.memmove(buf, data + b"\0", len(data) + 1)
        return 0

    # --- networking
    def tailscale_listen(self, sd, network, addr, out):
        s = self._s(sd)
        if s is None: return 9
        if self._backend_state(s) != "Running":
            return self._fail(s, "node is not running")
        port = int(self._text(addr).rsplit(":", 1)[1])
        c_side, go_side = socket.socketpair()
        fd = c_side.detach()
        self._listener_socks[fd] = go_side
        self.tailnet.listeners[(self._ip_for(s), port)] = go_side
        s["listeners"].append(fd)
        out._obj.value = fd
        self.calls.append(f"listen:{port}")
        return 0

    def tailscale_accept(self, listener_fd, out):
        if not hasattr(socket, "recv_fds"):
            return -1
        try:
            sock = socket.socket(fileno=os.dup(listener_fd))
        except OSError:
            return 9                                            # EBADF
        try:
            msg, fds, _flags, _addr = socket.recv_fds(sock, RECORD, 1, socket.MSG_WAITALL)
        except OSError:
            return -1
        finally:
            sock.close()
        if not fds:
            return -1
        out._obj.value = fds[0]
        self._last_record = msg
        return 0

    def tailscale_getremoteaddr(self, listener_fd, conn_fd, buf, buflen):
        rec = getattr(self, "_last_record", b"")
        ip = rec.split(b"\0", 1)[0]
        ctypes.memmove(buf, ip + b"\0", len(ip) + 1)
        return 0

    def tailscale_dial(self, sd, network, addr, out):
        s = self._s(sd)
        if s is None: return 9
        if self._backend_state(s) != "Running":
            return self._fail(s, "node is not running")
        ip, port = self._text(addr).rsplit(":", 1)
        try:
            client = self.tailnet.connect(ip, int(port), from_ip=self._ip_for(s))
        except ConnectionRefusedError as e:
            return self._fail(s, str(e))
        out._obj.value = client.detach()
        return 0

    def tailscale_loopback(self, *a): return -1
    def tailscale_enable_funnel_to_localhost_plaintext_http1(self, *a): return -1


def make_fake():
    """Factory used with OPENSMS_TS_FAKE=fake_tailscale:make_fake (a process-wide instance, like a loaded .so)."""
    global _SHARED
    try:
        return _SHARED
    except NameError:
        _SHARED = FakeTailscaleLib()
        return _SHARED
