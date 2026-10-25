"""
Tailscale awareness for OpenSMS (read-only).

Design (audit TS-01, see IMPLEMENTATION_PLAN.md section E, option A):
  The data path is the official Tailscale Android app, which owns the device's VPN. OpenSMS does NOT
  join a tailnet itself and does not store, accept or send any Tailscale credential. It only
  *observes* the device and reports what it actually sees:

    connected     a VPN network on this device carries a tailnet address (100.64.0.0/10 or fd7a:115c:a1e0::/48)
    other_vpn     a VPN is active but has no tailnet address
    disconnected  no tailnet address found
    unknown       the network state could not be read

  100.64.0.0/10 is shared with carrier-grade NAT, so an address in that range on a cellular/Wi-Fi
  interface is NOT treated as Tailscale.

  OpenSMS can also restrict which network the API listens on (bind modes), which is what makes the
  "tailnet only" setup enforceable.
"""

import ipaddress
import socket
from services.pathMgr import get_network_interfaces_info, get_vpn_networks

BIND_ALL = "all"
BIND_TAILSCALE = "tailscale"
BIND_LOCALHOST = "localhost"
BIND_MODES = (BIND_ALL, BIND_TAILSCALE, BIND_LOCALHOST)

_TS_V4 = ipaddress.ip_network("100.64.0.0/10")
_TS_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
# Interface-name hints used ONLY when the OS cannot tell us which networks are VPNs.
_TUNNEL_PREFIXES = ("tailscale", "tun", "utun", "wg")
_NON_TUNNEL_HINTS = ("rmnet", "ccmni", "pdp", "wwan", "wlan", "wifi", "eth", "en", "lo")


def is_tailnet_address(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(str(ip).split("%")[0].strip())
    except ValueError:
        return False
    return addr in (_TS_V4 if addr.version == 4 else _TS_V6)


def normalize_bind_mode(mode) -> str:
    return mode if mode in BIND_MODES else BIND_ALL


def resolve_bind_host(mode: str, tailnet_ip):
    """
    Returns (host, error). Fails CLOSED: in tailscale mode without a tailnet address the server must
    not start (and must never silently fall back to listening on all interfaces).
    """
    mode = normalize_bind_mode(mode)
    if mode == BIND_ALL:
        return "0.0.0.0", None
    if mode == BIND_LOCALHOST:
        return "127.0.0.1", None
    if tailnet_ip and ":" not in tailnet_ip and is_tailnet_address(tailnet_ip):
        return tailnet_ip, None
    return None, ("Tailscale-only mode is on but no Tailscale IPv4 address was found. "
                  "Start the Tailscale app and connect, or choose another listening mode.")


def classify(net_info: dict, vpn_networks, port=None, bind_mode: str = BIND_ALL, listening=None) -> dict:
    """
    Pure decision function (unit tested). `vpn_networks` is a list of
    {"interface": str, "addresses": [str]} for networks the OS marks as VPN, or None when the OS
    could not be asked (non-Android, missing permission, API failure).
    """
    bind_mode = normalize_bind_mode(bind_mode)
    ts_ip = ts_ip6 = iface = evidence = None
    diagnostics = []
    state = "disconnected"

    if vpn_networks is not None:
        for net in vpn_networks:
            for a in net.get("addresses", []):
                if is_tailnet_address(a):
                    if ":" in a:
                        ts_ip6 = ts_ip6 or a.split("%")[0]
                    else:
                        ts_ip = ts_ip or a
                    iface = iface or net.get("interface")
                    evidence = "vpn_network"
        if ts_ip or ts_ip6:
            state = "connected"
        elif vpn_networks:
            state = "other_vpn"
    else:
        # Fallback: interface names. Only tunnel-looking interfaces count.
        for entry in net_info.get("interfaces", []):
            name = str(entry.get("name", "")).lower()
            ip = entry.get("ip", "")
            if not is_tailnet_address(ip):
                continue
            if name.startswith(_TUNNEL_PREFIXES) and not name.startswith(_NON_TUNNEL_HINTS):
                if ":" in ip:
                    ts_ip6 = ts_ip6 or ip
                else:
                    ts_ip = ts_ip or ip
                iface, evidence, state = name, "interface", "connected"
        if state != "connected":
            state = "unknown" if vpn_networks is None and not net_info.get("interfaces") else "disconnected"

    # carrier-grade NAT look-alikes
    cgnat = [e for e in net_info.get("interfaces", [])
             if is_tailnet_address(e.get("ip", "")) and e.get("ip") not in (ts_ip, ts_ip6)]
    if cgnat:
        diagnostics.append({"level": "info", "id": "cgnat_ignored",
                            "text": "Address %s on '%s' is in the Tailscale range but not on a VPN interface "
                                    "(usually carrier-grade NAT); it was ignored." % (cgnat[0]["ip"], cgnat[0].get("name"))})

    if state == "connected":
        diagnostics.append({"level": "ok", "id": "tailnet_address", "text": "Tailscale address %s (%s)." % (ts_ip or ts_ip6, evidence.replace("_", " "))})
    elif state == "other_vpn":
        diagnostics.append({"level": "warn", "id": "other_vpn", "text": "A VPN is active but has no Tailscale address. Open the Tailscale app and connect (Android allows one VPN at a time)."})
    elif state == "unknown":
        diagnostics.append({"level": "warn", "id": "unknown", "text": "Network state could not be read on this device."})
    else:
        diagnostics.append({"level": "warn", "id": "disconnected", "text": "No Tailscale address found. Open the Tailscale app, sign in and connect."})

    if bind_mode == BIND_TAILSCALE and not ts_ip:
        diagnostics.append({"level": "error", "id": "bind_blocked", "text": "Listening mode is 'Tailscale only' but there is no Tailscale IPv4 address, so the API server will not start."})
    if bind_mode == BIND_ALL and state == "connected":
        diagnostics.append({"level": "info", "id": "bind_all", "text": "The API also listens on Wi-Fi/LAN. Choose 'Tailscale only' to restrict it to your tailnet."})
    if bind_mode == BIND_LOCALHOST:
        diagnostics.append({"level": "info", "id": "bind_localhost", "text": "The API listens on this device only; no other device can reach it."})
    if listening is True and ts_ip:
        diagnostics.append({"level": "ok", "id": "listening", "text": "The gateway answers on %s:%s." % (ts_ip, port)})
    elif listening is False and ts_ip:
        diagnostics.append({"level": "warn", "id": "not_listening", "text": "Nothing answers on %s:%s. Is the server started and the listening mode compatible?" % (ts_ip, port)})

    return {
        "state": state,
        "connected": state == "connected",
        "ip": ts_ip,
        "ipv6": ts_ip6,
        "interface": iface,
        "evidence": evidence,
        "bind_mode": bind_mode,
        "listening": listening,
        "diagnostics": diagnostics,
        "all_ips": net_info.get("all_ips", ["127.0.0.1"]),
        "local_ip": net_info.get("local_ip"),
        "interfaces": [e for e in net_info.get("interfaces", []) if e.get("ip") in (ts_ip, ts_ip6)],
        "node_name": None,
        "mode": evidence,
        "devices": [],
        "configured_key": "",
    }


def probe_listener(ip: str, port: int, timeout: float = 1.0) -> bool:
    """True if something accepts TCP connections on ip:port (a reachability hint, not an auth check)."""
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class TailscaleService:
    """Thin facade kept for the UI. Holds NO credentials and NO connection state."""

    @classmethod
    def init_config(cls, saved_config: dict):
        return None  # nothing is persisted any more

    @classmethod
    def get_config_dict(cls) -> dict:
        return {}

    @classmethod
    def disconnect_key(cls) -> dict:
        return {"success": True, "message": "Nothing to disconnect: OpenSMS keeps no Tailscale credential."}

    @classmethod
    def get_status(cls, port=None, bind_mode: str = BIND_ALL, probe: bool = False) -> dict:
        net_info = get_network_interfaces_info()
        try:
            vpn = get_vpn_networks()
        except Exception:
            vpn = None
        status = classify(net_info, vpn, port=port, bind_mode=bind_mode)
        if probe and port and status["ip"]:
            return classify(net_info, vpn, port=port, bind_mode=bind_mode,
                            listening=probe_listener(status["ip"], port))
        return status

    @classmethod
    def get_preferred_endpoint(cls, port: int = 9292, bind_mode: str = BIND_ALL) -> tuple[str, str]:
        """(endpoint_url, network_type) that a remote client can actually use under `bind_mode`."""
        status = cls.get_status(bind_mode=bind_mode)
        mode = normalize_bind_mode(bind_mode)
        if mode == BIND_LOCALHOST:
            return f"http://127.0.0.1:{port}/sms/", "This device only"
        if status["connected"] and status["ip"]:
            return f"http://{status['ip']}:{port}/sms/", "Tailscale"
        if mode == BIND_TAILSCALE:
            return f"http://<tailscale-ip>:{port}/sms/", "Tailscale (not connected)"
        if status["local_ip"]:
            return f"http://{status['local_ip']}:{port}/sms/", "Local Wi-Fi / LAN"
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
