"""
ctypes binding for libtailscale (https://github.com/tailscale/libtailscale), Tailscale embedded in this process.

The C contract is app/native/tailscale.h. `SIGNATURES` below must match it exactly: a unit test parses the header and
compares every function and argument count. Everything else (state machine, forwarding, keys) lives in tsEmbed.py.

Facts about the library this wrapper is built around (read from its source):
  * every call returns 0 on success; the message of the last failure is available through tailscale_errmsg
  * tailscale_up() blocks with no way to cancel it, and tailscale_close() is a no-op for a server that was never
    "started". So the controller uses tailscale_start() + status polling instead of tailscale_up()
  * tailscale_status_json() returns a malloc()ed string that the caller must free()
  * tailscale_set_logfd() hands the descriptor to Go, which wraps it with os.NewFile: pass a dup() and never close it
  * a listener is one end of a socketpair (poll it, then accept); an accepted connection is a plain socket fd
"""
import ctypes
import os
import socket
import sys
from ctypes import POINTER, c_char_p, c_int, c_size_t, c_void_p
from typing import List, Optional, Tuple

def _free_memory(ptr: c_void_p) -> None:
    if sys.platform == "win32":
        ctypes.cdll.msvcrt.free(ptr)
    else:
        ctypes.CDLL(None).free(ptr)

SIGNATURES = {
    "tailscale_new": (c_int, []),
    "tailscale_start": (c_int, [c_int]),
    "tailscale_up": (c_int, [c_int]),
    "tailscale_close": (c_int, [c_int]),
    "tailscale_set_dir": (c_int, [c_int, c_char_p]),
    "tailscale_set_hostname": (c_int, [c_int, c_char_p]),
    "tailscale_set_authkey": (c_int, [c_int, c_char_p]),
    "tailscale_set_control_url": (c_int, [c_int, c_char_p]),
    "tailscale_set_ephemeral": (c_int, [c_int, c_int]),
    "tailscale_set_logfd": (c_int, [c_int, c_int]),
    "tailscale_getips": (c_int, [c_int, c_char_p, c_size_t]),
    "tailscale_dial": (c_int, [c_int, c_char_p, c_char_p, POINTER(c_int)]),
    "tailscale_listen": (c_int, [c_int, c_char_p, c_char_p, POINTER(c_int)]),
    "tailscale_getremoteaddr": (c_int, [c_int, c_int, c_char_p, c_size_t]),
    "tailscale_accept": (c_int, [c_int, POINTER(c_int)]),
    "tailscale_loopback": (c_int, [c_int, c_char_p, c_size_t, c_char_p, c_char_p]),
    "tailscale_status_json": (c_int, [c_int, POINTER(c_void_p)]),
    "tailscale_enable_funnel_to_localhost_plaintext_http1": (c_int, [c_int, c_int]),
    "tailscale_errmsg": (c_int, [c_int, c_char_p, c_size_t]),
}

ERRMSG_LEN = 1024


class TailscaleError(Exception):
    """A libtailscale call failed. `str(e)` is the library's own message (never contains a key)."""


def apply_signatures(lib) -> None:
    for name, (restype, argtypes) in SIGNATURES.items():
        fn = getattr(lib, name)
        fn.restype = restype
        fn.argtypes = argtypes


def candidate_library_paths() -> List[str]:
    """Where libtailscale.so may live. Android puts add_libs files into the app's native library directory."""
    paths = []
    override = os.environ.get("OPENSMS_TS_LIB")
    if override:
        paths.append(override)
    paths.append("libtailscale.so")                      # resolved by the Android linker from the app's lib directory
    try:                                                 # explicit path as a second chance
        from services.smsApi import get_android_context
        ctx = get_android_context()
        if ctx is not None:
            paths.append(os.path.join(str(ctx.getApplicationInfo().nativeLibraryDir), "libtailscale.so"))
    except Exception:
        pass
    return paths


def load_library() -> Tuple[Optional[object], str]:
    """(lib, reason). lib is None when the built-in engine is not part of this build or failed to load."""
    fake = os.environ.get("OPENSMS_TS_FAKE")            # development/tests only: "package.module:factory"
    if fake:
        import importlib
        module, _, attr = fake.partition(":")
        return getattr(importlib.import_module(module), attr or "make_fake")(), ""
    errors = []
    for path in candidate_library_paths():
        try:
            lib = ctypes.CDLL(path)
            apply_signatures(lib)
            return lib, ""
        except (OSError, AttributeError) as e:
            errors.append(f"{path}: {e}")
    return None, ("The built-in Tailscale engine is not included in this build (libtailscale.so was not found). "
                  "See docs/tailscale.md, 'Built-in Tailscale'. Tried: " + "; ".join(errors))


class NativeTailscale:
    """Pythonic wrapper over one libtailscale server handle. All errors become TailscaleError."""

    def __init__(self, lib):
        self._lib = lib
        self.sd = lib.tailscale_new()
        if self.sd < 0:
            raise TailscaleError("tailscale_new failed")
        self.closed = False

    # ---- helpers
    def _err(self) -> str:
        buf = ctypes.create_string_buffer(ERRMSG_LEN)
        try:
            self._lib.tailscale_errmsg(self.sd, buf, ERRMSG_LEN)
        except Exception:
            return "unknown error"
        return buf.value.decode("utf-8", "replace") or "unknown error"

    def _check(self, rc: int, what: str) -> None:
        if rc != 0:
            raise TailscaleError(f"{what} failed: {self._err()}")

    # ---- configuration (before start)
    def set_dir(self, path: str) -> None:
        self._check(self._lib.tailscale_set_dir(self.sd, path.encode()), "set_dir")

    def set_hostname(self, name: str) -> None:
        self._check(self._lib.tailscale_set_hostname(self.sd, name.encode()), "set_hostname")

    def set_authkey(self, key: str) -> None:
        self._check(self._lib.tailscale_set_authkey(self.sd, key.encode()), "set_authkey")

    def set_control_url(self, url: str) -> None:
        self._check(self._lib.tailscale_set_control_url(self.sd, url.encode()), "set_control_url")

    def set_ephemeral(self, value: bool) -> None:
        self._check(self._lib.tailscale_set_ephemeral(self.sd, 1 if value else 0), "set_ephemeral")

    def set_logfd(self, fd: int) -> None:
        self._check(self._lib.tailscale_set_logfd(self.sd, fd), "set_logfd")

    # ---- lifecycle
    def start(self) -> None:
        """Non-blocking start (use status() to follow progress). Preferred over up(), which cannot be cancelled."""
        self._check(self._lib.tailscale_start(self.sd), "start")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._lib.tailscale_close(self.sd)

    # ---- information
    def ips(self) -> Tuple[Optional[str], Optional[str]]:
        buf = ctypes.create_string_buffer(128)
        if self._lib.tailscale_getips(self.sd, buf, 128) != 0:
            return None, None
        v4 = v6 = None
        for part in buf.value.decode().split(","):
            part = part.strip()
            if not part or part in ("invalid IP", "<invalid IP>"):
                continue
            if ":" in part:
                v6 = v6 or part
            else:
                v4 = v4 or part
        return v4, v6

    def status_json(self) -> dict:
        import json
        out = c_void_p()
        self._check(self._lib.tailscale_status_json(self.sd, ctypes.byref(out)), "status")
        if not out.value:
            return {}
        try:
            return json.loads(ctypes.string_at(out.value).decode("utf-8", "replace"))
        finally:
            _free_memory(c_void_p(out.value))      # the library allocated it with malloc

    # ---- networking
    def listen(self, network: str, addr: str) -> int:
        out = c_int(-1)
        self._check(self._lib.tailscale_listen(self.sd, network.encode(), addr.encode(), ctypes.byref(out)), "listen")
        return out.value

    def dial(self, network: str, addr: str) -> int:
        """Connect to a tailnet address ("100.x.y.z:port"); returns a plain stream-socket fd."""
        out = c_int(-1)
        self._check(self._lib.tailscale_dial(self.sd, network.encode(), addr.encode(), ctypes.byref(out)), "dial")
        return out.value

    def accept(self, listener_fd: int) -> int:
        out = c_int(-1)
        self._check(self._lib.tailscale_accept(listener_fd, ctypes.byref(out)), "accept")
        return out.value

    def remote_addr(self, listener_fd: int, conn_fd: int) -> str:
        buf = ctypes.create_string_buffer(128)
        if self._lib.tailscale_getremoteaddr(listener_fd, conn_fd, buf, 128) != 0:
            return ""
        return buf.value.decode("utf-8", "replace")

    @staticmethod
    def socket_from_fd(fd: int) -> socket.socket:
        """Wrap an accepted connection (a plain stream socket owned by us from now on)."""
        return socket.socket(fileno=fd)
