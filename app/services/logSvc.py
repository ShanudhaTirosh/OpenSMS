from datetime import datetime
import os
import re
import queue
import threading


def mask_phone(number: str) -> str:
    """Mask a phone number for logs: keep the first 3 and last 3 characters (audit issue SEC-10)."""
    n = re.sub(r"[^\d+]", "", str(number or ""))
    if len(n) <= 6:
        return "***"
    return n[:3] + "*" * (len(n) - 6) + n[-3:]


class AsyncLogWriter:
    """Single background worker so request handlers never spawn a thread per log line."""

    def __init__(self, maxsize: int = 1000):
        self._q: "queue.Queue[tuple]" = queue.Queue(maxsize=maxsize)
        self._thread = None
        self._lock = threading.Lock()

    def submit(self, log_service, message: str) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        try:
            self._q.put_nowait((log_service, message))
        except queue.Full:
            pass  # drop rather than block the request or grow without bound

    def _run(self):
        while True:
            svc, msg = self._q.get()
            try:
                svc.write_log(msg)
            except Exception as e:
                print(f"Error writing log: {e}")

class LogService:

    def __init__(self, app_name:str, platform:str = "none"):
        if platform == "android":
            from android.storage import app_storage_path
            self.base_path = app_storage_path()
        else:
            from services.pathMgr import get_user_data_dir
            self.base_path = str(get_user_data_dir(app_name))


        self.config_dir = os.path.join(self.base_path, "config")
        log_dir = os.path.join(self.base_path, "logs")
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "api_logs.log")
        # Migrate legacy .json log file if present
        legacy_log_path = os.path.join(log_dir, "api_logs.json")
        if os.path.exists(legacy_log_path) and not os.path.exists(self.log_path):
            try:
                os.replace(legacy_log_path, self.log_path)
            except Exception:
                pass

    def write_log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}\n"
        try:
            # Rotate log if it exceeds 2MB
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 2 * 1024 * 1024:
                backup = self.log_path + ".old"
                if os.path.exists(backup):
                    os.remove(backup)
                os.replace(self.log_path, backup)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"Error writing log: {e}")

    def get_api_logs(self) -> list[str]:
        logs = []
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    logs = f.readlines()
            except Exception as e:
                print(f"Error reading logs: {e}")
        return logs

    def clear_logs(self):
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("")
            backup = self.log_path + ".old"
            if os.path.exists(backup):
                os.remove(backup)
        except Exception as e:
            print(f"Error clearing logs: {e}")

