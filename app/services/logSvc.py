from datetime import datetime
import os

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

