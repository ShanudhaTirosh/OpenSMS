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

## functions
def atomic_write_json(file_path: str, data: dict):
    """Write data to temporary file and atomically replace to avoid corrupt reads."""
    import os
    tmp_path = file_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as tf:
            json.dump(data, tf)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, file_path)
    except Exception as e:
        print(f"Error atomic writing {file_path}: {e}")

def write_resp():
    """ Write the response json on file atomically. """
    global resp_template
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

def api_server_control(api_stat: str):
    """ Turns API server on/off """
    global api_started
    global resp_template
    global req_data
    port = req_data.get("port", 9292)
    print(f"Service control: {api_stat} on port {port}")
    if api_stat == "stop":
        app_api_server.stop()
        api_started = False
        resp_template["server"] = "stopped"
        resp_template["port"] = port
    elif api_stat == "start":
        app_api_server.start(port)
        api_started = True
        resp_template["server"] = "started"
        resp_template["port"] = port
    Thread(target=write_resp, daemon=True).start()


def app_service_thread():
    """
    The main service thready runs forever till the app is running & performs the operations.
    """
    #global vars
    global api_started

    write_resp() # blank the old file
    #api_server_control("start") # api server starts automatically

    # keep alive the service & check for requests
    while True:
        read_req_file()

        #handle api server
        server_stat = req_data.get("server", "")
        if not api_started and server_stat == "start":
            api_server_control("start")
        elif api_started and server_stat == "stop":
            api_server_control("stop")

        # put a sleep
        time.sleep(0.2)


# run locally
if __name__ == "__main__":
    app_service_thread()
