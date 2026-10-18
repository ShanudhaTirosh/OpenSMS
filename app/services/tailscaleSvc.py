"""
Tailscale & Cross-Network Integration Service for OpenSMS.
Handles Tailscale detection, MagicDNS formatting, multi-language code snippets,
and cross-network routing diagnostics.
"""

from services.pathMgr import is_tailscale_ip, get_network_interfaces_info

class TailscaleService:

    @staticmethod
    def get_status() -> dict:
        """
        Check if Tailscale is active on the device and retrieve its configuration.
        """
        net_info = get_network_interfaces_info()
        ts_ip = net_info.get("tailscale_ip")
        is_connected = ts_ip is not None

        return {
            "connected": is_connected,
            "ip": ts_ip,
            "interfaces": [iface for iface in net_info.get("interfaces", []) if iface.get("is_tailscale")],
            "node_name": f"opensms-gateway" if is_connected else None,
            "all_ips": net_info.get("all_ips", ["127.0.0.1"]),
            "local_ip": net_info.get("local_ip")
        }

    @staticmethod
    def get_preferred_endpoint(port: int = 9292) -> tuple[str, str]:
        """
        Returns (endpoint_url, network_type).
        Prioritizes Tailscale Mesh IP (for worldwide cross-network access),
        then local Wi-Fi/LAN IP, then 127.0.0.1.
        """
        status = TailscaleService.get_status()
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
