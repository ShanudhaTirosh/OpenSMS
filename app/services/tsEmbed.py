"""
Built-in Tailscale (experimental): this app joins your tailnet itself, in the background service, with no VPN
permission and no Tailscale app, and forwards tailnet connections to the local API.

    other tailnet device --WireGuard--> [this phone: embedded node :PORT] --> 127.0.0.1:PORT (the OpenSMS API)

Pieces: key handling (an auth key, or an API token used once to mint a short-lived auth key and never stored),
a one-shot secret hand-off from the UI, the connection forwarder, the controller state machine and the command
bridge used by the service loop. The native library is wrapped by tsNative.py; if it is not part of the build
everything reports "unavailable" instead of failing.
"""
import json
import os
import re
import select
import shutil
import socket
import threading
import time
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from services import tsNative

# ----------------------------------------------------------------------------------------------- keys
_AUTH_RE = re.compile(r"^tskey-auth-[A-Za-z0-9_-]{8,}$")
_API_RE = re.compile(r"^tskey-api-[A-Za-z0-9_-]{8,}$")
_SECRET_RE = re.compile(r"tskey-[a-z]+-[A-Za-z0-9_-]+", re.I)
TAILSCALE_API = "https://api.tailscale.com/api/v2"


class KeyProblem(Exception):
    """A key could not be used. The message is safe to show: it never contains the key."""


def redact(text) -> str:
    return _SECRET_RE.sub("tskey-***", str(text))


def classify_key(text: str) -> Tuple[str, str]:
    """('authkey'|'apikey', cleaned key). Raises KeyProblem with a helpful message otherwise."""
    value = (text or "").strip()
    if not value:
        raise KeyProblem("Paste an auth key (tskey-auth-...) or an API access token (tskey-api-...).")
    if _AUTH_RE.match(value):
        return "authkey", value
    if _API_RE.match(value):
        return "apikey", value
    if value.startswith("tskey-client-"):
        raise KeyProblem("OAuth client secrets (tskey-client-...) are not supported. Create an auth key "
                         "(Settings > Keys > Generate auth key) or an API access token instead.")
    raise KeyProblem("That does not look like a Tailscale key. Auth keys start with tskey-auth-, "
                     "API access tokens with tskey-api-.")


def clean_hostname(name: Optional[str], fallback: str = "opensms") -> str:
    """A valid DNS label: lowercase letters, digits and hyphens, 1-63 characters, no leading/trailing hyphen."""
    s = re.sub(r"[^a-z0-9-]+", "-", (name or "").strip().lower()).strip("-")[:63].strip("-")
    return s or fallback


def validate_control_url(url: Optional[str]) -> Optional[str]:
    """Optional custom control server (e.g. Headscale). Returns the cleaned URL or None; raises KeyProblem."""
    url = (url or "").strip()
    if not url:
        return None
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise KeyProblem("The control server URL must look like https://headscale.example.com")
    return url.rstrip("/")


def mint_auth_key(api_token: str, hostname: str, http=None, timeout: float = 15.0, expiry_seconds: int = 600) -> str:
    """
    Use an API access token ONCE to create a single-use, pre-authorised, short-lived auth key for this device.
    The token is never stored or logged. `http` is the requests module (injectable for tests).
    """
    if http is None:
        import requests as http
    body = {
        "capabilities": {"devices": {"create": {"reusable": False, "ephemeral": False, "preauthorized": True}}},
        "expirySeconds": int(expiry_seconds),
        "description": f"OpenSMS built-in node {hostname}",
    }
    try:
        r = http.post(f"{TAILSCALE_API}/tailnet/-/keys", json=body, timeout=timeout,
                      headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"})
    except Exception as e:                                       # network errors never echo the token
        raise KeyProblem(f"Could not reach the Tailscale API: {redact(e.__class__.__name__)}. Check the internet connection.")
    code = getattr(r, "status_code", 0)
    if code == 401:
        raise KeyProblem("The API access token was rejected (invalid or expired). Create a new one in the Tailscale admin console.")
    if code == 403:
        raise KeyProblem("The API access token is not allowed to create auth keys.")
    if code == 404:
        raise KeyProblem("Tailscale could not find the tailnet for this token.")
    if code == 429:
        raise KeyProblem("Tailscale is rate limiting requests. Wait a minute and try again.")
    if code < 200 or code >= 300:
        raise KeyProblem(f"The Tailscale API returned an error (HTTP {code}).")
    try:
        key = r.json().get("key", "")
    except Exception:
        key = ""
    if not _AUTH_RE.match(key or ""):
        raise KeyProblem("The Tailscale API did not return an auth key.")
    return key


# ------------------------------------------------------------------------------------- secret hand-off
SECRET_FILE = "ts_secret.json"


def write_secret(config_dir: str, kind: str, value: str, hostname: str = "", control_url: str = "") -> None:
    """UI side: leave the key for the service in a private one-shot file (mode 0600). It is never put in request.json."""
    os.makedirs(config_dir, exist_ok=True)
    path = os.path.join(config_dir, SECRET_FILE)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"kind": kind, "value": value, "hostname": hostname, "control_url": control_url}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def take_secret(config_dir: str) -> Optional[dict]:
    """Service side: read the one-shot file, overwrite it with zeros and delete it. None if there is none."""
    path = os.path.join(config_dir, SECRET_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    try:
        if os.path.exists(path):
            size = os.path.getsize(path)
            with open(path, "r+b") as f:
                f.write(b"\0" * size)
                f.flush()
                os.fsync(f.fileno())
            os.remove(path)
    except OSError:
        pass
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------------------------------ forwarder
def _pump(a: socket.socket, b: socket.socket, idle_timeout: float) -> None:
    """
    Relay bytes both ways until both directions are finished or nothing moved for idle_timeout seconds.
    Each direction has its own thread, so a peer that is slow to read in one direction can never stall the
    other (a single-threaded relay with blocking sends deadlocks on large simultaneous transfers).
    """
    state = {"last": time.monotonic(), "stop": False}

    def copy(src: socket.socket, dst: socket.socket) -> None:
        while not state["stop"]:
            try:
                ready, _, _ = select.select([src], [], [], 1.0)
            except (OSError, ValueError):
                break
            if not ready:
                if time.monotonic() - state["last"] > idle_timeout:
                    state["stop"] = True
                    break
                continue
            try:
                data = src.recv(65536)
            except OSError:
                break
            if not data:
                try:
                    dst.shutdown(socket.SHUT_WR)               # pass the end-of-stream on, keep the other direction open
                except OSError:
                    pass
                return
            state["last"] = time.monotonic()
            try:
                dst.sendall(data)                              # blocks only this direction while dst is slow
            except OSError:
                break
            state["last"] = time.monotonic()
        state["stop"] = True
        for s in (src, dst):                                   # wake the other direction up
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    t = threading.Thread(target=copy, args=(b, a), daemon=True)
    t.start()
    copy(a, b)
    t.join()


class Forwarder:
    """Accepts tailnet connections on the embedded node and relays each one to 127.0.0.1:<api port>."""

    def __init__(self, node: "tsNative.NativeTailscale", port_getter: Callable[[], int], max_conns: int = 64,
                 idle_timeout: float = 120.0, connect_timeout: float = 3.0, log: Callable[[str], None] = print):
        self.node = node
        self.port_getter = port_getter
        self.max_conns = max_conns
        self.idle_timeout = idle_timeout
        self.connect_timeout = connect_timeout
        self.log = log
        self.stats = {"accepted": 0, "active": 0, "refused": 0, "failed": 0}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lfd: Optional[int] = None
        self._lock = threading.Lock()

    def start(self, listen_port: int) -> None:
        self._lfd = self.node.listen("tcp", f":{int(listen_port)}")
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, name="ts-forwarder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        lfd, self._lfd = self._lfd, None
        if lfd is not None:
            try:
                os.close(lfd)                                      # closing the listener fd tears the listener down
            except OSError:
                pass
        t = self._thread
        if t and t.is_alive():
            t.join(2.0)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            lfd = self._lfd
            if lfd is None:
                return
            try:
                ready, _, _ = select.select([lfd], [], [], 0.5)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            try:
                cfd = self.node.accept(lfd)
            except (tsNative.TailscaleError, OSError) as e:
                if not self._stop.is_set():
                    self.log(f"Tailscale forwarder: accept failed: {redact(e)}")
                return
            try:
                conn = self.node.socket_from_fd(cfd)
            except OSError:
                continue
            with self._lock:
                if self.stats["active"] >= self.max_conns:
                    self.stats["refused"] += 1
                    conn.close()
                    continue
                self.stats["active"] += 1
                self.stats["accepted"] += 1
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        upstream = None
        try:
            try:
                upstream = socket.create_connection(("127.0.0.1", int(self.port_getter())), timeout=self.connect_timeout)
            except OSError:
                with self._lock:
                    self.stats["failed"] += 1
                return                                             # the API is not listening: just close the tunnel side
            upstream.settimeout(None)
            conn.settimeout(None)
            _pump(conn, upstream, self.idle_timeout)
        finally:
            for s in (conn, upstream):
                try:
                    if s is not None:
                        s.close()
                except OSError:
                    pass
            with self._lock:
                self.stats["active"] -= 1


# ---------------------------------------------------------------------------------------- crash guard
class CrashGuard:
    """
    A native library inside a sticky service can take the whole service down. While the engine is active a marker is
    kept; if the service starts and finds it still set, the previous run ended unexpectedly (crash, or killed by
    Android). After `threshold` such ends within `window` seconds the engine is blocked until the user explicitly
    asks again, so a crash can never turn into an endless crash/restart loop.
    """

    def __init__(self, path: str, threshold: int = 3, window: float = 1800.0, clock: Callable[[], float] = time.time):
        self.path, self.threshold, self.window, self._clock = path, threshold, window, clock
        data = self._load()
        now = self._clock()
        stamps = [t for t in data.get("unclean", []) if now - t < self.window]
        if data.get("active"):
            stamps.append(now)                          # the previous service process never stopped the engine cleanly
        self._data = {"active": False, "unclean": stamps}
        self._save()

    @property
    def blocked(self) -> bool:
        return len(self._data["unclean"]) >= self.threshold

    @property
    def unclean_count(self) -> int:
        return len(self._data["unclean"])

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError:
            pass

    def engine_started(self) -> None:
        self._data["active"] = True
        self._save()

    def engine_stopped_cleanly(self) -> None:
        self._data["active"] = False
        self._data["unclean"] = []                       # a clean stop proves the engine can run: forget past incidents
        self._save()

    def reset(self) -> None:
        self._data = {"active": False, "unclean": []}
        self._save()


# ------------------------------------------------------------------------------------------ controller
STATE_FILE = "tailscaled.state"
STATES = ("unavailable", "disabled", "starting", "connected", "needs_auth", "needs_approval", "error")
MAX_LOG_BYTES = 512 * 1024


def parse_status(st: dict) -> dict:
    """Reduce tsnet's ipnstate.Status JSON to what the UI needs. Defensive: any field may be missing."""
    me = st.get("Self") or {}
    ips = me.get("TailscaleIPs") or st.get("TailscaleIPs") or []
    v4 = next((i for i in ips if ":" not in i), None)
    v6 = next((i for i in ips if ":" in i), None)
    peers = []
    for p in (st.get("Peer") or {}).values():
        pips = p.get("TailscaleIPs") or []
        peers.append({"name": p.get("HostName") or (p.get("DNSName") or "").split(".")[0] or "?",
                      "ip": next((i for i in pips if ":" not in i), pips[0] if pips else ""),
                      "online": bool(p.get("Online")), "os": p.get("OS") or ""})
    peers.sort(key=lambda p: (not p["online"], p["name"].lower()))
    tailnet = (st.get("CurrentTailnet") or {})
    return {
        "backend": st.get("BackendState") or "",
        "ip": v4, "ip6": v6,
        "hostname": me.get("HostName") or "",
        "dns_name": (me.get("DNSName") or "").rstrip("."),
        "tailnet": tailnet.get("Name") or "",
        "auth_url": st.get("AuthURL") or "",
        "peers": peers,
        "health": [str(h) for h in (st.get("Health") or [])][:5],
    }


class EmbeddedTailscale:
    def __init__(self, config_dir: str, lib_loader=tsNative.load_library, node_factory=tsNative.NativeTailscale,
                 port: int = 9292, startup_timeout: float = 90.0, auth_grace: float = 25.0, poll: float = 1.0,
                 monitor_interval: float = 5.0, http=None, log: Callable[[str], None] = print):
        self.config_dir = config_dir
        self.state_dir = os.path.join(config_dir, "tsnet")
        self.log_path = os.path.join(config_dir, "tsnet.log")
        self._lib_loader, self._node_factory = lib_loader, node_factory
        self.port = int(port)
        self.startup_timeout, self.auth_grace, self.poll, self.monitor_interval = startup_timeout, auth_grace, poll, monitor_interval
        self._http, self._log = http, log
        self.guard = CrashGuard(os.path.join(config_dir, "tsnet_guard.json"))
        self._lock = threading.Lock()
        self._gen = 0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._node = None
        self._fwd: Optional[Forwarder] = None
        self._lib, self._reason = None, ""
        self._st: Dict = self._blank("disabled")

    # ---------------------------------------------------------------- status
    def _blank(self, state: str, error: str = "", message: str = "") -> Dict:
        return {"state": state, "error": error, "message": message, "ip": None, "ip6": None, "hostname": "", "dns_name": "",
                "tailnet": "", "auth_url": "", "peers": [], "health": [], "since": time.time()}

    def _set(self, state: str, error: str = "", message: str = "", **extra) -> None:
        with self._lock:
            keep = {k: v for k, v in self._st.items() if k in ("hostname",)} if state in ("starting", "disabled") else {}
            self._st = {**self._blank(state, redact(error), message), **keep, **extra}

    def available(self) -> Tuple[bool, str]:
        if self._lib is None and not self._reason:
            self._lib, self._reason = self._lib_loader()
        return self._lib is not None, self._reason

    def status(self) -> Dict:
        ok, reason = self.available()
        with self._lock:
            st = dict(self._st)
        st["available"] = ok
        st["reason"] = "" if ok else reason
        if not ok and st["state"] == "disabled":
            st["state"] = "unavailable"
        st["port"] = self.port
        st["saved_identity"] = self.has_saved_identity()
        st["forwarded"] = dict(self._fwd.stats) if self._fwd else {"accepted": 0, "active": 0, "refused": 0, "failed": 0}
        st["peer_count"] = len(st["peers"])
        st["online_peers"] = sum(1 for p in st["peers"] if p["online"])
        return st

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def has_saved_identity(self) -> bool:
        return os.path.exists(os.path.join(self.state_dir, STATE_FILE))

    def _saved_settings(self) -> Dict:
        try:
            with open(os.path.join(self.state_dir, "opensms.json"), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    # ---------------------------------------------------------------- commands
    def connect(self, kind: Optional[str] = None, value: Optional[str] = None, hostname: str = "", control_url: str = "",
                user_initiated: bool = False) -> None:
        """Start (or restart) the node. With no key it resumes from the saved identity. Returns immediately.
        `user_initiated` (the user pressed Connect) lifts the crash guard; an automatic resume never does."""
        ok, reason = self.available()
        if not ok:
            self._set("unavailable", error=reason)
            return
        if user_initiated:
            self.guard.reset()
        elif self.guard.blocked:
            self._set("error", error=f"The built-in Tailscale was switched off because the background service ended unexpectedly "
                      f"{self.guard.unclean_count} times while it was running. Press Connect to try again; if it keeps happening, "
                      "send the diagnostics report.")
            return
        self.disconnect(forget=False, quiet=True)
        saved = self._saved_settings()
        host = clean_hostname(hostname or saved.get("hostname") or "", fallback="opensms")
        ctrl = control_url or saved.get("control_url") or ""
        with self._lock:
            self._gen += 1
            gen = self._gen
        self._stop = threading.Event()
        self._set("starting", message="Starting...", hostname=host)
        self._thread = threading.Thread(target=self._run, args=(gen, kind, value, host, ctrl), name="ts-embedded", daemon=True)
        self._thread.start()

    def disconnect(self, forget: bool = False, quiet: bool = False) -> None:
        with self._lock:
            self._gen += 1                                          # any running thread becomes stale
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(5.0)
        self._teardown()
        self._thread = None
        if not quiet:
            self.guard.engine_stopped_cleanly()
        if forget:
            shutil.rmtree(self.state_dir, ignore_errors=True)
            for name in (SECRET_FILE,):
                try:
                    os.remove(os.path.join(self.config_dir, name))
                except OSError:
                    pass
        if not quiet:
            self._set("disabled", message="Not connected")

    def set_port(self, port: int) -> None:
        port = int(port)
        if port == self.port:
            return
        self.port = port
        if self._fwd is not None and self._node is not None and self._st.get("state") == "connected":
            try:
                self._fwd.stop()
                self._fwd = Forwarder(self._node, lambda: self.port, log=self._log)
                self._fwd.start(self.port)
            except tsNative.TailscaleError as e:
                self._set("error", error=f"Could not listen on port {port}: {e}")

    def _teardown(self) -> None:
        fwd, self._fwd = self._fwd, None
        node, self._node = self._node, None
        if fwd is not None:
            fwd.stop()
        if node is not None:
            try:
                node.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- engine thread
    def _rotate_log(self) -> None:
        try:
            if os.path.getsize(self.log_path) > MAX_LOG_BYTES:
                os.replace(self.log_path, self.log_path + ".1")
        except OSError:
            pass

    def _run(self, gen: int, kind: Optional[str], value: Optional[str], hostname: str, control_url: str) -> None:
        def stale() -> bool:
            return gen != self._gen or self._stop.is_set()
        try:
            authkey = None
            if kind == "apikey":
                self._set("starting", message="Creating a one-time auth key...", hostname=hostname)
                authkey = mint_auth_key(value, hostname, http=self._http)
            elif kind == "authkey":
                authkey = value
            value = None
            if stale():
                return
            os.makedirs(self.state_dir, mode=0o700, exist_ok=True)
            with open(os.path.join(self.state_dir, "opensms.json"), "w", encoding="utf-8") as f:
                json.dump({"hostname": hostname, "control_url": control_url}, f)
            node = self._node_factory(self._lib)
            self.guard.engine_started()                              # from here a crash leaves the marker set
            self._node = node
            node.set_dir(self.state_dir)
            node.set_hostname(hostname)
            node.set_ephemeral(False)
            if control_url:
                node.set_control_url(control_url)
            if authkey:
                node.set_authkey(authkey)
                authkey = None
            self._rotate_log()
            logfd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            node.set_logfd(os.dup(logfd))                           # Go owns the dup; ours is closed below
            os.close(logfd)
            node.start()
            had_key = kind in ("authkey", "apikey")
            self._follow(gen, node, had_key, hostname, stale)
        except KeyProblem as e:
            if gen == self._gen:
                self._set("error", error=str(e))
        except tsNative.TailscaleError as e:
            if gen == self._gen:
                self._set("error", error=str(e))
        except Exception as e:                                       # never let the engine thread kill the service
            if gen == self._gen:
                self._set("error", error=f"Unexpected error: {e.__class__.__name__}: {e}")

    def _follow(self, gen, node, had_key: bool, hostname: str, stale) -> None:
        t0 = time.monotonic()
        while not stale():
            parsed = parse_status(node.status_json())
            backend = parsed["backend"]
            if backend == "Running" and parsed["ip"]:
                self._on_running(gen, node, parsed)
                return
            if backend == "NeedsMachineAuth":
                self._set("needs_approval", message="Waiting for an admin to approve this device in the Tailscale admin console.",
                          hostname=parsed["hostname"] or hostname)
            elif backend == "NeedsLogin":
                waited = time.monotonic() - t0
                if not had_key:
                    self._set("needs_auth", message="Enter an auth key to connect this device.", hostname=hostname)
                    self._teardown_after_failure(gen)
                    return
                if waited > self.auth_grace:
                    self._set("needs_auth", message="Tailscale did not accept the key (it may be expired, already used, "
                              "or for another tailnet). Create a new one and try again.", hostname=hostname)
                    self._teardown_after_failure(gen)
                    return
            elif time.monotonic() - t0 > self.startup_timeout:
                self._set("error", error="Timed out waiting for Tailscale to connect. Check the internet connection; "
                          "see the diagnostics log on the System screen.")
                self._teardown_after_failure(gen)
                return
            time.sleep(self.poll)

    def _teardown_after_failure(self, gen) -> None:
        if gen == self._gen:
            self._teardown()
            self.guard.engine_stopped_cleanly()

    def _on_running(self, gen, node, parsed) -> None:
        fwd = Forwarder(node, lambda: self.port, log=self._log)
        try:
            fwd.start(self.port)
        except tsNative.TailscaleError as e:
            self._set("error", error=f"Connected, but could not listen on port {self.port}: {e}")
            return
        self._fwd = fwd
        self._publish_connected(parsed)
        while gen == self._gen and not self._stop.is_set():                # monitor: peers, expiry, reconnects
            if self._stop.wait(self.monitor_interval):
                break
            try:
                parsed = parse_status(node.status_json())
            except tsNative.TailscaleError:
                continue
            if parsed["backend"] == "Running" and parsed["ip"]:
                self._publish_connected(parsed)
            elif parsed["backend"] in ("NeedsLogin", "NeedsMachineAuth"):
                self._set("needs_auth" if parsed["backend"] == "NeedsLogin" else "needs_approval",
                          message="The device needs to sign in again: its key may have expired. Enter a new auth key.",
                          hostname=parsed["hostname"])
            else:
                self._set("starting", message="Reconnecting...", hostname=parsed["hostname"])

    def _publish_connected(self, parsed) -> None:
        self._set("connected", message="Connected", ip=parsed["ip"], ip6=parsed["ip6"], hostname=parsed["hostname"],
                  dns_name=parsed["dns_name"], tailnet=parsed["tailnet"], peers=parsed["peers"], health=parsed["health"])

    # ---------------------------------------------------------------- diagnostics
    def log_tail(self, lines: int = 40) -> str:
        """Last lines of the engine log with every key pattern redacted (safe to copy into a bug report)."""
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 16384))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            return ""
        return redact("\n".join(text.splitlines()[-lines:]))


# ------------------------------------------------------------------------------------- service bridge
class EmbeddedCommands:
    """Applies the UI's wishes (request.json: ts_embedded, ts_forget_id + the secret file) to the controller."""

    RETRY_SECONDS = 60.0

    def __init__(self, engine: EmbeddedTailscale, config_dir: str, clock: Callable[[], float] = time.monotonic):
        self.engine, self.config_dir, self._clock = engine, config_dir, clock
        self._last_forget = 0
        self._blocked_since: Optional[float] = None
        self._desired_seen = "down"

    def apply(self, req: dict, port: int) -> None:
        e = self.engine
        e.set_port(port)
        desired = "up" if req.get("ts_embedded") == "up" else "down"
        forget_id = int(req.get("ts_forget_id", 0) or 0)
        if forget_id != self._last_forget:
            self._last_forget = forget_id
            if forget_id > 0:
                e.disconnect(forget=True)
                self._blocked_since = None
                return
        if desired == "down":
            if e.active or e.status()["state"] not in ("disabled", "unavailable"):
                e.disconnect()
            self._desired_seen = "down"
            return
        # desired == "up"
        secret = take_secret(self.config_dir)
        if secret:
            try:
                kind, value = classify_key(secret.get("value", ""))
                ctrl = validate_control_url(secret.get("control_url"))
            except KeyProblem as ex:
                e._set("error", error=str(ex))
                return
            e.connect(kind, value, secret.get("hostname", ""), ctrl or "", user_initiated=True)
            self._blocked_since = None
            self._desired_seen = "up"
            return
        state = e.status()["state"]
        if e.active or state in ("connected", "starting"):
            self._desired_seen = "up"
            return
        if self._desired_seen == "down" or (state in ("disabled",)):
            self._desired_seen = "up"
            if e.has_saved_identity():
                e.connect()                                           # resume without a key
            else:
                e._set("needs_auth", message="Enter an auth key to connect this device.")
            return
        if state == "error" and e.has_saved_identity():               # transient failure: retry now and then
            now = self._clock()
            if self._blocked_since is None:
                self._blocked_since = now
            elif now - self._blocked_since >= self.RETRY_SECONDS:
                self._blocked_since = None
                e.connect()
