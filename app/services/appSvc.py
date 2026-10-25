try:
    from kivy.utils import platform
except ImportError:
    import sys
    if sys.platform.startswith("win"):
        platform = "win"
    elif sys.platform.startswith("linux"):
        platform = "linux"
    else:
        platform = "unknown"


from os.path import join, exists
from threading import Thread

import time
import sys

# local imports
from services.postApi import PosiApiServer, set_config_path, set_api_os, set_api_logger, accept_local_message
from services.logSvc import LogService
from services.reqWatch import RequestWatcher
from services.outbox import drain_outbox
from services.wakeLock import WakeLockController, android_wakelock_factory
from services.lifecycle import HEARTBEAT_SECONDS, wakelock_wanted
from services import smsReceipts
from services import postApi as _postApi
from services.tailscaleSvc import TailscaleService, resolve_bind_host, normalize_bind_mode, BIND_ALL

# global vars
app_name = "opensms"
resp_template = {
    "server": "none",
}
req_data = {}
api_started = False
log_obj = LogService(app_name, platform)

## OS specific setups
# for android
if platform == "android":
    from android.storage import app_storage_path
    from jnius import autoclass  # noqa: F401  (kept: initialises pyjnius early in the service process)
    base_path = app_storage_path()
#for other platforms like windows or linux
else:
    from services.pathMgr import get_user_data_dir
    base_path = get_user_data_dir(app_name)

config_dir = join(base_path, 'config')
if not exists(config_dir):
    import os
    os.makedirs(config_dir, exist_ok=True)
set_config_path(config_dir)
set_api_os(platform)
set_api_logger(log_obj)
req_file = join(config_dir, "request.json")
resp_file = join(config_dir, "resp.json")

## global obj
app_api_server = PosiApiServer()
in_error_state = False
bind_blocked_at = None   # when a fail-closed bind error happened (retried every 10 s)

def on_server_control_event(event_type: str, detail: str = ""):
    global api_started
    global resp_template
    global in_error_state
    print(f"Server control event: {event_type} - {detail}")
    if "error" in event_type:
        api_started = False
        in_error_state = True
        resp_template["server"] = "error"
        resp_template["error"] = detail
        write_resp()

def on_kivy_activity_event(stat: bool = True, count: int = 1):
    global resp_template
    resp_template["last_activity"] = time.time()
    resp_template["last_stat"] = stat
    write_resp()

app_api_server.set_control_caller(on_server_control_event)
app_api_server.set_kivy_caller(on_kivy_activity_event)

## functions
def write_resp():
    """ Write the response json on file atomically. """
    global resp_template
    from services.pathMgr import atomic_write_json
    resp_template["ts"] = time.time()
    atomic_write_json(resp_file, resp_template)

_req_watcher = RequestWatcher(req_file)

def read_req_file():
    """ Pick up new instructions from the main app. The file is only read when it changed. """
    global req_data
    data = _req_watcher.poll()
    if data is not None:
        req_data = data

def api_server_control(api_stat: str, port: int = 9292, bind_mode: str = BIND_ALL):
    """ Turns API server on/off """
    global api_started
    global resp_template
    global in_error_state
    global bind_blocked_at
    print(f"Service control: {api_stat} on port {port}")
    if api_stat == "stop":
        in_error_state = False
        app_api_server.stop()
        api_started = False
        resp_template["server"] = "stopped"
        resp_template["port"] = port
        resp_template.pop("error", None)
    elif api_stat == "start":
        in_error_state = False
        bind_mode = normalize_bind_mode(bind_mode)
        tailnet_ip = TailscaleService.get_status()["ip"] if bind_mode != BIND_ALL else None
        host, bind_error = resolve_bind_host(bind_mode, tailnet_ip)
        if bind_error:
            # Fail closed: never fall back to listening on every interface.
            api_started = False
            in_error_state = True
            resp_template["server"] = "error"
            resp_template["error"] = bind_error
            resp_template["bind"] = bind_mode
            bind_blocked_at = time.time()
            Thread(target=write_resp, daemon=True).start()
            return
        app_api_server.host = host
        app_api_server.start(port)
        api_started = True
        resp_template["server"] = "started"
        resp_template["port"] = port
        resp_template["bind"] = bind_mode
        resp_template["host"] = host
        resp_template.pop("error", None)
    Thread(target=write_resp, daemon=True).start()


def app_service_thread():
    """
    The main service thread runs forever while the app is running & executes operations.
    """
    global api_started
    global req_data
    global in_error_state
    global bind_blocked_at
    current_port = 9292
    current_bind = BIND_ALL
    last_processed_cmd = None

    write_resp()
    wake_lock = WakeLockController(android_wakelock_factory() if platform == "android" else (lambda: None))
    last_heartbeat = 0.0

    while True:
        read_req_file()
        # Heartbeat: lets the app tell a running service from a stale status file
        if time.time() - last_heartbeat >= HEARTBEAT_SECONDS:
            last_heartbeat = time.time()
            resp_template["diag"] = {      # facts only the service knows (shown on the System screen)
                "receipts": smsReceipts.receipts_available(),
                "wakelock": wake_lock.held,
                "queue": _postApi.message_svc.pending() if _postApi.message_svc else None,
            }
            write_resp()
        wake_lock.update(wakelock_wanted(api_started, req_data))
        try:
            drain_outbox(config_dir, accept_local_message)   # messages composed in the app
        except Exception as e:
            print(f"Outbox error: {e}")

        server_stat = req_data.get("server", "")
        try:
            requested_port = int(req_data.get("port", 9292))
        except (ValueError, TypeError):
            requested_port = 9292

        requested_bind = normalize_bind_mode(req_data.get("bind"))
        current_cmd = (server_stat, requested_port, requested_bind)

        # Tailscale-only mode failed because no tailnet address existed: retry every 10 s so the
        # server comes up by itself once the Tailscale app connects.
        if in_error_state and bind_blocked_at and time.time() - bind_blocked_at > 10:
            in_error_state = False
            bind_blocked_at = None
            last_processed_cmd = None

        # If in error state and command hasn't changed, do not thrash in tight retry loop
        if in_error_state and current_cmd == last_processed_cmd:
            time.sleep(0.5)
            continue

        # A changed command (e.g. a new listening mode) clears a previous error and retries
        if in_error_state and server_stat == "start" and current_cmd != last_processed_cmd:
            in_error_state = False

        # Handle port / listening-mode change while running
        if api_started and server_stat == "start" and (requested_port != current_port or requested_bind != current_bind):
            print(f"Port/bind changed to {requested_port}/{requested_bind}. Restarting server...")
            api_server_control("stop", current_port)
            time.sleep(0.5)
            current_port, current_bind = requested_port, requested_bind
            api_server_control("start", current_port, current_bind)
            last_processed_cmd = current_cmd
        elif not api_started and server_stat == "start" and not in_error_state:
            current_port, current_bind = requested_port, requested_bind
            api_server_control("start", current_port, current_bind)
            last_processed_cmd = current_cmd
        elif api_started and server_stat == "stop":
            api_server_control("stop", current_port)
            last_processed_cmd = current_cmd
        elif not api_started and server_stat == "stop" and in_error_state:
            in_error_state = False
            last_processed_cmd = current_cmd

        time.sleep(_req_watcher.next_sleep())


# run locally
if __name__ == "__main__":
    app_service_thread()

