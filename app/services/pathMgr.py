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

def is_tailscale_ip(ip: str) -> bool:
    """Check if an IPv4 address belongs to Tailscale CGNAT range (100.64.0.0/10)."""
    try:
        parts = [int(p) for p in ip.strip().split(".")]
        if len(parts) == 4 and parts[0] == 100 and (64 <= parts[1] <= 127):
            return True
    except Exception:
        pass
    return False

def get_network_interfaces_info() -> dict:
    """
    Enumerate network interfaces and classify them (Tailscale, Wi-Fi, LAN, Cellular).
    Compatible with Android (via PyJNIus java.net.NetworkInterface), Linux, and Windows.
    """
    info = {
        "tailscale_ip": None,
        "local_ip": None,
        "cellular_ip": None,
        "all_ips": [],
        "interfaces": []
    }
    seen_ips = set()

    # 1. Android Java NetworkInterface enumeration (if on Android)
    try:
        from jnius import autoclass
        NetworkInterface = autoclass('java.net.NetworkInterface')
        interfaces = NetworkInterface.getNetworkInterfaces()
        if interfaces:
            while interfaces.hasMoreElements():
                net_if = interfaces.nextElement()
                if not net_if.isUp() or net_if.isLoopback():
                    continue
                iface_name = str(net_if.getName()).lower()
                addrs = net_if.getInetAddresses()
                while addrs.hasMoreElements():
                    addr = addrs.nextElement()
                    ip_str = str(addr.getHostAddress())
                    # Only consider IPv4
                    if ":" not in ip_str and not ip_str.startswith("127."):
                        if ip_str not in seen_ips:
                            seen_ips.add(ip_str)
                            is_ts = is_tailscale_ip(ip_str) or "tailscale" in iface_name
                            iface_type = "tailscale" if is_ts else (
                                "wifi" if any(k in iface_name for k in ["wlan", "wl", "wifi"]) else (
                                "cellular" if any(k in iface_name for k in ["rmnet", "ccmni", "pdp", "wwan"]) else (
                                "ethernet" if any(k in iface_name for k in ["eth", "en"]) else "lan"
                            )))
                            info["interfaces"].append({
                                "name": iface_name,
                                "ip": ip_str,
                                "type": iface_type,
                                "is_tailscale": is_ts
                            })
                            if is_ts and not info["tailscale_ip"]:
                                info["tailscale_ip"] = ip_str
                            elif iface_type == "cellular" and not info["cellular_ip"]:
                                info["cellular_ip"] = ip_str
                            elif not info["local_ip"]:
                                info["local_ip"] = ip_str
    except Exception:
        pass

    # 2. Outbound routing detection (Fallback or desktop)
    import socket
    for target in [('8.8.8.8', 80), ('1.1.1.1', 80)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect(target)
            primary_ip = s.getsockname()[0]
            s.close()
            if primary_ip and not primary_ip.startswith('127.') and primary_ip not in seen_ips:
                seen_ips.add(primary_ip)
                is_ts = is_tailscale_ip(primary_ip)
                if is_ts and not info["tailscale_ip"]:
                    info["tailscale_ip"] = primary_ip
                elif not info["local_ip"]:
                    info["local_ip"] = primary_ip
                info["interfaces"].append({
                    "name": "default",
                    "ip": primary_ip,
                    "type": "tailscale" if is_ts else "lan",
                    "is_tailscale": is_ts
                })
                break
        except Exception:
            pass

    # 3. Hostname resolution fallback
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip not in seen_ips and not ip.startswith('127.'):
                seen_ips.add(ip)
                is_ts = is_tailscale_ip(ip)
                if is_ts and not info["tailscale_ip"]:
                    info["tailscale_ip"] = ip
                elif not info["local_ip"]:
                    info["local_ip"] = ip
                info["interfaces"].append({
                    "name": "host",
                    "ip": ip,
                    "type": "tailscale" if is_ts else "lan",
                    "is_tailscale": is_ts
                })
    except Exception:
        pass

    # Order IPs: Tailscale first, then Local LAN, then others
    ordered_ips = []
    if info["tailscale_ip"]:
        ordered_ips.append(info["tailscale_ip"])
    if info["local_ip"] and info["local_ip"] not in ordered_ips:
        ordered_ips.append(info["local_ip"])
    for ip in seen_ips:
        if ip not in ordered_ips:
            ordered_ips.append(ip)

    if not ordered_ips:
        ordered_ips.append("127.0.0.1")

    info["all_ips"] = ordered_ips
    return info

def get_device_ip_addresses() -> list[str]:
    """Helper to discover all active IP addresses, prioritizing Tailscale and LAN."""
    net_info = get_network_interfaces_info()
    return net_info["all_ips"]


