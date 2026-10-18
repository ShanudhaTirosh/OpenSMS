import os
import sys
from pathlib import Path

def get_user_data_dir(app_name: str) -> Path:
    """
    Returns a safe, user-specific data directory for Linux and Windows.
    Creates the directory if it does not already exist.
    """
    home = Path.home()

    if sys.platform.startswith("win"):
        # Windows standard: %LOCALAPPDATA% (or fallback to ~/AppData/Local)
        base_dir = os.environ.get("LOCALAPPDATA")
        if base_dir:
            data_dir = Path(base_dir) / app_name
        else:
            data_dir = home / "AppData" / "Local" / app_name

    else:
        # Linux / Unix standard: XDG_DATA_HOME (or fallback to ~/.local/share)
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            data_dir = Path(xdg_data) / app_name
        else:
            data_dir = home / ".local" / "share" / app_name

    # Safely create the folder with parents
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error while creating app dir: {e}")

    return data_dir

def atomic_write_json(file_path: str, data: dict):
    """Write data to temporary file and atomically replace to avoid corrupt reads."""
    import json
    tmp_path = str(file_path) + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as tf:
            json.dump(data, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, str(file_path))
    except Exception as e:
        print(f"Error atomic writing {file_path}: {e}")

def get_device_ip_addresses() -> list[str]:
    """Helper to discover local Wi-Fi, Ethernet, and VPN IP addresses."""
    import socket
    ip_list = []
    # 1. Outbound routing detection
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(('8.8.8.8', 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith('127.'):
            ip_list.append(primary_ip)
    except Exception:
        pass

    # 2. Hostname resolution
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip not in ip_list and not ip.startswith('127.'):
                ip_list.append(ip)
    except Exception:
        pass

    if not ip_list:
        ip_list.append("127.0.0.1")
    return ip_list

