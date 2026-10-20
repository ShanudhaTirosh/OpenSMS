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


from os.path import join, abspath, exists, dirname
from threading import Thread

import json
import time
import sys

# local imports
from services.postApi import PosiApiServer, set_config_path, set_api_os, set_api_logger
from services.logSvc import LogService

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
    from jnius import autoclass
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
    atomic_write_json(resp_file, resp_template)

def read_req_file():
    """ Read the command file from file (Instructions from main app). """
    global req_data
    if exists(req_file):
        try:
            with open(req_file, "r", encoding="utf-8") as rf:
                req_data = json.load(rf)
        except Exception as e:
            # Ignore transient read collisions while file is being replaced
            pass

def api_server_control(api_stat: str, port: int = 9292):
    """ Turns API server on/off """
    global api_started
    global resp_template
    global in_error_state
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
        app_api_server.start(port)
        api_started = True
        resp_template["server"] = "started"
        resp_template["port"] = port
        resp_template.pop("error", None)
    Thread(target=write_resp, daemon=True).start()


def app_service_thread():
    """
    The main service thread runs forever while the app is running & executes operations.
    """
    global api_started
    global req_data
    global in_error_state
    current_port = 9292
    last_processed_cmd = None

    write_resp()

    while True:
        read_req_file()

        server_stat = req_data.get("server", "")
        try:
            requested_port = int(req_data.get("port", 9292))
        except (ValueError, TypeError):
            requested_port = 9292

        current_cmd = (server_stat, requested_port)

        # If in error state and command hasn't changed, do not thrash in tight retry loop
        if in_error_state and current_cmd == last_processed_cmd:
            time.sleep(0.5)
            continue

        # Handle port change while running
        if api_started and requested_port != current_port and server_stat == "start":
            print(f"Port changed from {current_port} to {requested_port}. Restarting server...")
            api_server_control("stop", current_port)
            time.sleep(0.5)
            current_port = requested_port
            api_server_control("start", current_port)
            last_processed_cmd = current_cmd
        elif not api_started and server_stat == "start" and not in_error_state:
            current_port = requested_port
            api_server_control("start", current_port)
            last_processed_cmd = current_cmd
        elif api_started and server_stat == "stop":
            api_server_control("stop", current_port)
            last_processed_cmd = current_cmd
        elif not api_started and server_stat == "stop" and in_error_state:
            in_error_state = False
            last_processed_cmd = current_cmd

        time.sleep(0.2)


# run locally
if __name__ == "__main__":
    app_service_thread()

