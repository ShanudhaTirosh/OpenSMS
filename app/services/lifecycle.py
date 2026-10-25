"""
Gateway lifecycle rules shared by the UI and the service (pure functions, unit tested).

Goals: the gateway keeps running when the app is closed, reopening the app must not change its state, and it
only stops when the user stops it.
"""
import time
from typing import Optional

HEARTBEAT_SECONDS = 3.0      # the service refreshes resp.json at least this often
FRESH_SECONDS = 12.0         # a status older than this is not trusted (service dead or not started)


def desired_server_state(config: dict) -> str:
    """'start' if the user left the gateway running (or enabled auto-start), else 'stop'."""
    return "start" if (config.get("server_desired") == "start" or config.get("boot")) else "stop"


def initial_request(config: dict, port: int, bind: str) -> dict:
    """The request.json written when the app opens. It restores the user's last choice instead of forcing 'stop'."""
    return {
        "port": int(port),
        "server": desired_server_state(config),
        "bind": bind,
        "wakelock": bool(config.get("wakelock", True)),
    }


def resp_is_fresh(resp: Optional[dict], now: Optional[float] = None, max_age: float = FRESH_SECONDS) -> bool:
    """True when `resp` carries a recent service heartbeat (`ts`)."""
    if not isinstance(resp, dict):
        return False
    ts = resp.get("ts")
    if not isinstance(ts, (int, float)):
        return False
    return 0 <= (now if now is not None else time.time()) - ts <= max_age


def wakelock_wanted(server_started: bool, req: dict) -> bool:
    """Hold the lock only while the server runs and the user has not turned the setting off."""
    return bool(server_started and req.get("wakelock", True))
