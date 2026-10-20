"""
Tailscale & Cross-Network Integration Service for OpenSMS.
Handles Tailscale detection, MagicDNS formatting, multi-language code snippets,
in-app Tailscale Key connection, and cross-network routing diagnostics.
"""

import re
import socket
import requests
from services.pathMgr import is_tailscale_ip, get_network_interfaces_info

class TailscaleService:
    _config = {
        "key": "",
        "ip": None,
        "node_name": None,
        "mode": None,  # "api_token", "direct_ip", "auth_key"
        "connected": False,
        "last_sync": None,
        "devices": []
    }

    @classmethod
    def init_config(cls, saved_config: dict):
        """Load in-app Tailscale settings from app config dictionary."""
        if not isinstance(saved_config, dict):
            return
        ts_data = saved_config.get("tailscale", {})
        if isinstance(ts_data, dict):
            cls._config["key"] = ts_data.get("key", "")
            cls._config["ip"] = ts_data.get("ip")
            cls._config["node_name"] = ts_data.get("node_name")
            cls._config["mode"] = ts_data.get("mode")
            cls._config["connected"] = bool(ts_data.get("connected") and ts_data.get("ip"))
            cls._config["last_sync"] = ts_data.get("last_sync")
            cls._config["devices"] = ts_data.get("devices", [])

    @classmethod
    def get_config_dict(cls) -> dict:
        """Return Tailscale configuration dictionary for persistence in config.json."""
        return {
            "key": cls._config.get("key", ""),
            "ip": cls._config.get("ip"),
            "node_name": cls._config.get("node_name"),
            "mode": cls._config.get("mode"),
            "connected": bool(cls._config.get("connected") and cls._config.get("ip")),
            "last_sync": cls._config.get("last_sync"),
            "devices": cls._config.get("devices", [])
        }

    @classmethod
    def get_status(cls) -> dict:
        """
        Check if Tailscale is active on the device (either via physical device interface
        or configured via in-app Tailscale key/IP) and retrieve its configuration.
        """
        net_info = get_network_interfaces_info()
        live_ts_ip = net_info.get("tailscale_ip")

        # 1. Physical / OS device interface takes highest precedence
        if live_ts_ip:
            return {
                "connected": True,
                "ip": live_ts_ip,
                "interfaces": [iface for iface in net_info.get("interfaces", []) if iface.get("is_tailscale")],
                "node_name": cls._config.get("node_name") or "opensms-gateway",
                "mode": "device_interface",
                "all_ips": net_info.get("all_ips", ["127.0.0.1"]),
                "local_ip": net_info.get("local_ip"),
                "configured_key": cls._config.get("key", ""),
                "devices": cls._config.get("devices", [])
            }

        # 2. In-app configured key / direct IP
        if cls._config.get("connected") and cls._config.get("ip"):
            ts_ip = cls._config["ip"]
            all_ips = [ts_ip] + [ip for ip in net_info.get("all_ips", []) if ip != ts_ip]
            return {
                "connected": True,
                "ip": ts_ip,
                "interfaces": [{"name": "in-app-tailscale", "ip": ts_ip, "type": "tailscale", "is_tailscale": True}],
                "node_name": cls._config.get("node_name") or f"opensms-{ts_ip.replace('.', '-')}",
                "mode": cls._config.get("mode") or "in_app_key",
                "all_ips": all_ips,
                "local_ip": net_info.get("local_ip"),
                "configured_key": cls._config.get("key", ""),
                "devices": cls._config.get("devices", [])
            }

        # 3. Not connected
        return {
            "connected": False,
            "ip": None,
            "interfaces": [],
            "node_name": None,
            "mode": None,
            "all_ips": net_info.get("all_ips", ["127.0.0.1"]),
            "local_ip": net_info.get("local_ip"),
            "configured_key": cls._config.get("key", ""),
            "devices": []
        }

    @classmethod
    def connect_tailscale_key(cls, raw_input: str, device_filter: str = None) -> dict:
        """
        Connect to Tailscale using an Auth Key, API Token, or Direct 100.x.y.z IP.
        - API Token (tskey-api-...): Queries Tailscale REST API to fetch nodes and auto-select device IP.
        - Direct IP (100.64.0.0/10): Directly sets the Tailscale Mesh IPv4 address.
        - Auth Key (tskey-auth-...): Validates key format and pairs with the local node.
        """
        import datetime
        raw_input = (raw_input or "").strip()
        if not raw_input:
            return {"success": False, "error": "Please enter a Tailscale Key, API Token, or Tailscale IP."}

        # Case 1: Direct Tailscale IP (e.g. "100.85.12.34" or "100.85.12.34:9292")
        ip_candidate = raw_input.split(":")[0].strip()
        if is_tailscale_ip(ip_candidate):
            node_name = f"node-{ip_candidate.replace('.', '-')}"
            cls._config["key"] = ip_candidate
            cls._config["ip"] = ip_candidate
            cls._config["node_name"] = node_name
            cls._config["mode"] = "direct_ip"
            cls._config["connected"] = True
            cls._config["last_sync"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cls._config["devices"] = [{"name": node_name, "ip": ip_candidate, "os": "android"}]
            return {
                "success": True,
                "ip": ip_candidate,
                "node_name": node_name,
                "mode": "direct_ip",
                "message": f"Tailscale IP {ip_candidate} connected successfully!"
            }

        # Case 2: Tailscale API Token (tskey-api-...) or long token
        if raw_input.startswith("tskey-api-") or (len(raw_input) >= 30 and ("api" in raw_input.lower() or not raw_input.startswith("tskey-auth-"))):
            try:
                headers = {"Authorization": f"Bearer {raw_input}"}
                url = "https://api.tailscale.com/api/v2/tailnet/-/devices"
                resp = requests.get(url, headers=headers, timeout=12)

                if resp.status_code == 200:
                    data = resp.json()
                    raw_devices = data.get("devices", [])
                    if not raw_devices:
                        return {"success": False, "error": "API Key is valid, but no devices were found in your Tailnet."}

                    devices_summary = []
                    candidate_device = None

                    for dev in raw_devices:
                        dev_name = dev.get("name", "").split(".")[0] or dev.get("hostname", "unknown")
                        dev_os = str(dev.get("os", "")).lower()
                        addresses = dev.get("addresses", [])
                        ipv4_ts = next((addr for addr in addresses if is_tailscale_ip(addr)), None)
                        if ipv4_ts:
                            dev_info = {
                                "id": dev.get("id"),
                                "name": dev_name,
                                "hostname": dev.get("hostname"),
                                "ip": ipv4_ts,
                                "os": dev_os,
                                "online": dev.get("online", False),
                                "last_seen": dev.get("lastSeen")
                            }
                            devices_summary.append(dev_info)

                            # Filter matching or prioritize android / online
                            if not candidate_device:
                                candidate_device = dev_info
                            elif device_filter and (device_filter.lower() in dev_name.lower() or device_filter.lower() in dev_os):
                                candidate_device = dev_info
                            elif dev_os == "android" and candidate_device.get("os") != "android":
                                candidate_device = dev_info
                            elif dev_info.get("online") and not candidate_device.get("online"):
                                candidate_device = dev_info

                    if not candidate_device:
                        return {"success": False, "error": "No devices with 100.x.y.z IPv4 addresses found in this Tailnet."}

                    chosen_ip = candidate_device["ip"]
                    chosen_name = candidate_device["name"]

                    cls._config["key"] = raw_input
                    cls._config["ip"] = chosen_ip
                    cls._config["node_name"] = chosen_name
                    cls._config["mode"] = "api_token"
                    cls._config["connected"] = True
                    cls._config["last_sync"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cls._config["devices"] = devices_summary

                    return {
                        "success": True,
                        "ip": chosen_ip,
                        "node_name": chosen_name,
                        "mode": "api_token",
                        "devices": devices_summary,
                        "message": f"Connected to Tailnet! Synced device '{chosen_name}' ({chosen_ip})."
                    }

                elif resp.status_code in (401, 403):
                    return {"success": False, "error": "Invalid Tailscale API token or permission denied."}
                else:
                    return {"success": False, "error": f"Tailscale API error HTTP {resp.status_code}."}

            except requests.exceptions.RequestException as re_err:
                return {"success": False, "error": f"Could not reach Tailscale API: {str(re_err)}"}
            except Exception as e:
                return {"success": False, "error": f"Connection error: {str(e)}"}

        # Case 3: Tailscale Auth Key (tskey-auth-...)
        if raw_input.startswith("tskey-auth-"):
            net_info = get_network_interfaces_info()
            live_ip = net_info.get("tailscale_ip")
            cls._config["key"] = raw_input
            cls._config["ip"] = live_ip or cls._config.get("ip")
            cls._config["node_name"] = "opensms-node"
            cls._config["mode"] = "auth_key"
            cls._config["connected"] = bool(cls._config["ip"])
            cls._config["last_sync"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {
                "success": True,
                "ip": cls._config["ip"],
                "node_name": "opensms-node",
                "mode": "auth_key",
                "message": "Tailscale Auth Key registered. " + (
                    f"Connected on IP {cls._config['ip']}." if cls._config["ip"] else "Key saved. Launch Tailscale on device to activate interface."
                )
            }

        return {
            "success": False,
            "error": "Unrecognized key format. Please enter an API token (tskey-api-...), Auth Key (tskey-auth-...), or Tailscale IP (100.x.y.z)."
        }

    @classmethod
    def disconnect_key(cls) -> dict:
        """Disconnect and clear configured Tailscale key and virtual IP."""
        cls._config = {
            "key": "",
            "ip": None,
            "node_name": None,
            "mode": None,
            "connected": False,
            "last_sync": None,
            "devices": []
        }
        return {"success": True, "message": "Tailscale in-app key disconnected."}

    @classmethod
    def get_preferred_endpoint(cls, port: int = 9292) -> tuple[str, str]:
        """
        Returns (endpoint_url, network_type).
        Prioritizes Tailscale Mesh IP (for worldwide cross-network access),
        then local Wi-Fi/LAN IP, then 127.0.0.1.
        """
        status = cls.get_status()
        if status["connected"] and status["ip"]:
            return f"http://{status['ip']}:{port}/sms/", "Tailscale Mesh"
        elif status["local_ip"]:
            return f"http://{status['local_ip']}:{port}/sms/", "Local Wi-Fi / LAN"
        else:
            return f"http://127.0.0.1:{port}/sms/", "Localhost"

    @staticmethod
    def generate_code_snippets(endpoint: str, api_key: str = "YOUR_API_KEY", phone: str = "+1234567890", text: str = "Hello from OpenSMS!") -> dict[str, str]:
        """
        Generate ready-to-copy code snippets for connecting from any remote program.
        """
        clean_key = api_key if api_key else "YOUR_API_KEY"

        # cURL
        curl_snippet = (
            f"curl -i -X POST '{endpoint}' \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -H 'Authorization: Bearer {clean_key}' \\\n"
            f"  -d '{{\"number\": \"{phone}\", \"text\": \"{text}\"}}'"
        )

        # Python (requests)
        python_snippet = (
            f"import requests\n\n"
            f"url = \"{endpoint}\"\n"
            f"headers = {{\n"
            f"    \"Authorization\": \"Bearer {clean_key}\",\n"
            f"    \"Content-Type\": \"application/json\"\n"
            f"}}\n"
            f"payload = {{\n"
            f"    \"number\": \"{phone}\",\n"
            f"    \"text\": \"{text}\"\n"
            f"}}\n\n"
            f"resp = requests.post(url, json=payload, headers=headers, timeout=10)\n"
            f"print(resp.json())\n"
        )

        # Node.js (fetch)
        nodejs_snippet = (
            f"const resp = await fetch('{endpoint}', {{\n"
            f"  method: 'POST',\n"
            f"  headers: {{\n"
            f"    'Content-Type': 'application/json',\n"
            f"    'Authorization': 'Bearer {clean_key}'\n"
            f"  }},\n"
            f"  body: JSON.stringify({{\n"
            f"    number: '{phone}',\n"
            f"    text: '{text}'\n"
            f"  }})\n"
            f"}});\n"
            f"const data = await resp.json();\n"
            f"console.log(data);\n"
        )

        # PHP
        php_snippet = (
            f"<?php\n"
            f"$ch = curl_init('{endpoint}');\n"
            f"$payload = json_encode([\n"
            f"    'number' => '{phone}',\n"
            f"    'text' => '{text}'\n"
            f"]);\n"
            f"curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);\n"
            f"curl_setopt($ch, CURLOPT_HTTPHEADER, [\n"
            f"    'Content-Type: application/json',\n"
            f"    'Authorization: Bearer {clean_key}'\n"
            f"]);\n"
            f"curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);\n"
            f"$result = curl_exec($ch);\n"
            f"curl_close($ch);\n"
            f"echo $result;\n"
        )

        # Go
        go_snippet = (
            f"package main\n\n"
            f"import (\n"
            f"    \"bytes\"\n"
            f"    \"encoding/json\"\n"
            f"    \"fmt\"\n"
            f"    \"net/http\"\n"
            f")\n\n"
            f"func main() {{\n"
            f"    body, _ := json.Marshal(map[string]string{{\n"
            f"        \"number\": \"{phone}\",\n"
            f"        \"text\": \"{text}\",\n"
            f"    }})\n"
            f"    req, _ := http.NewRequest(\"POST\", \"{endpoint}\", bytes.NewBuffer(body))\n"
            f"    req.Header.Set(\"Authorization\", \"Bearer {clean_key}\")\n"
            f"    req.Header.Set(\"Content-Type\", \"application/json\")\n"
            f"    resp, err := http.DefaultClient.Do(req)\n"
            f"    if err != nil {{ panic(err) }}\n"
            f"    defer resp.Body.Close()\n"
            f"    fmt.Println(\"Status:\", resp.Status)\n"
            f"}}\n"
        )

        return {
            "curl": curl_snippet,
            "python": python_snippet,
            "nodejs": nodejs_snippet,
            "php": php_snippet,
            "go": go_snippet
        }
