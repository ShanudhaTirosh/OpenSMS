"""
Authentication helpers for the OpenSMS gateway API.

- Scope model:  sms:write (send), sms:read (read history/stats), admin (key management/control)
- Failed-auth limiter keyed by the *socket* peer address. X-Forwarded-For is deliberately
  ignored: the gateway runs directly on a phone with no trusted reverse proxy, so the header
  is attacker-controlled (audit issue SEC-03).
- Per-key send limiter (audit issue SEC-07) so a leaked or buggy client cannot send unlimited SMS.
"""
import os
import time
import threading
from typing import Iterable

SCOPE_WRITE = "sms:write"
SCOPE_READ = "sms:read"
SCOPE_ADMIN = "admin"
DEFAULT_SCOPES = [SCOPE_WRITE, SCOPE_READ]
ALL_SCOPES = {SCOPE_WRITE, SCOPE_READ, SCOPE_ADMIN}

# --- failed authentication limiter (state is module-level so tests/UI can inspect it) ---
FAILED_AUTH_ATTEMPTS: dict[str, list[float]] = {}
MAX_FAILED_ATTEMPTS = 10
AUTH_LOCKOUT_WINDOW_SECONDS = 60.0
_auth_lock = threading.Lock()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Messages per key per minute. Default is generous enough for a full 100-message batch.
SEND_RATE_PER_MINUTE = _env_int("OPENSMS_SEND_RATE_PER_MIN", 300)
SEND_WINDOW_SECONDS = 60.0
_SEND_EVENTS: dict[str, list[float]] = {}
_send_lock = threading.Lock()


def client_ip(request) -> str:
    """Socket peer address only. Never trust forwarded headers."""
    return request.client.host if request.client else "unknown"


def check_lockout(ip: str, now: float | None = None) -> bool:
    """Return True if this IP is currently locked out."""
    now = now or time.time()
    with _auth_lock:
        if len(FAILED_AUTH_ATTEMPTS) > 200:
            cutoff = now - AUTH_LOCKOUT_WINDOW_SECONDS
            for k in [k for k, v in FAILED_AUTH_ATTEMPTS.items() if not v or v[-1] < cutoff]:
                FAILED_AUTH_ATTEMPTS.pop(k, None)
        attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(ip, []) if now - t < AUTH_LOCKOUT_WINDOW_SECONDS]
        FAILED_AUTH_ATTEMPTS[ip] = attempts
        return len(attempts) >= MAX_FAILED_ATTEMPTS


def record_failure(ip: str, now: float | None = None) -> None:
    now = now or time.time()
    with _auth_lock:
        FAILED_AUTH_ATTEMPTS.setdefault(ip, []).append(now)


def clear_failures(ip: str) -> None:
    with _auth_lock:
        FAILED_AUTH_ATTEMPTS.pop(ip, None)


def has_scope(client_info: dict, scope: str) -> bool:
    """admin implies every scope. Keys without scope data get the defaults."""
    scopes: Iterable[str] = client_info.get("scopes") or DEFAULT_SCOPES
    scopes = set(scopes)
    return SCOPE_ADMIN in scopes or scope in scopes


def consume_send_quota(key_id: str, count: int = 1, now: float | None = None) -> float:
    """
    Reserve `count` message slots for this key. Returns 0.0 if allowed, otherwise the number
    of seconds the caller should wait (Retry-After). Nothing is reserved when refused.
    """
    now = now or time.time()
    limit = SEND_RATE_PER_MINUTE
    if limit <= 0:  # 0 disables the limiter
        return 0.0
    with _send_lock:
        events = [t for t in _SEND_EVENTS.get(key_id, []) if now - t < SEND_WINDOW_SECONDS]
        if len(events) + count > limit:
            _SEND_EVENTS[key_id] = events
            if not events:
                return SEND_WINDOW_SECONDS  # a single request larger than the whole limit
            return max(1.0, SEND_WINDOW_SECONDS - (now - events[0]))
        events.extend([now] * count)
        _SEND_EVENTS[key_id] = events
        return 0.0


def reset_send_limiter() -> None:
    with _send_lock:
        _SEND_EVENTS.clear()
