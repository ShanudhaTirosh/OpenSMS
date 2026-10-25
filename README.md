<p align="center"><img width="20%" src="app/data/images/favicont512.png" /></p>

# 📨 OpenSMS

An open-source, privacy-first Android application that turns your Android phone into a high-performance **SMS Gateway & REST API server**.

Developed & maintained by **[Shanudha Tirosh](https://info.shanutechx.com)**.

---

### ✨ Key Features

- 📱 **Turns your Android device into an SMS REST API gateway**.
- 🚀 **1-Tap In-App Auto-Updater**: Automatic update checks directly against GitHub Releases, animated banner alerts, download progress reporting, and native Android APK package installation (`REQUEST_INSTALL_PACKAGES`).
- 📊 **Live Metrics & SQLite Message Persistence**: High-performance SQLite engine operating in Write-Ahead Logging (`WAL`) mode. Tracks queued, sent, and failed messages with live home dashlet metrics (Sent Today, Success Rate %, and Queue Depth).
- 📶 **Dual-SIM & Multi-SIM Telephony Orchestration**: Auto-detects dual SIM configurations via Android `SubscriptionManager`. Choose preferred carrier slot in Settings or dynamically route per API request using `sim_slot`.
- 🌐 **Tailscale-aware**: With the official Tailscale app connected on the phone, other devices on your tailnet reach the gateway at the phone's `100.x.y.z` address without port forwarding. OpenSMS shows the observed status and can restrict the API to the tailnet (see [docs/tailscale.md](docs/tailscale.md)).
- ⚡ **Built-In Client Code Generator**: Generate copy-paste client code snippets in **cURL**, **Python (requests)**, **Node.js (fetch)**, **PHP (cURL)**, and **Go** directly from the in-app Remote Mesh tab.
- 🔒 **Multi-Token Security & Granular Scopes**: Manage multiple named API tokens with permission scopes (`sms:write` to send, `sms:read` for history/stats, `admin` for key management) enforced on every endpoint, individual revocation via `DELETE /keys/{id}`, SHA-256 key hashing, brute-force lockout and a per-key send rate limit.
- 📦 **Batch SMS & Tracking**: Send up to 100 SMS messages in a single API call via `/sms/batch/` with automated rate pacing (100ms) to prevent carrier throttling, plus individual status inspection via `/sms/{id}` and `/sms/history/`.
- 💬 **Smart Telephony & Segmentation**: Automatic phone number sanitization (stripping spaces, brackets, hyphens) and real-time GSM-7 (160 chars) vs UCS-2 (70 chars) multipart SMS segment calculation.
- 📱 **Wide Device Compatibility**: Supports Android 7.0 (API 24) up to Android 15+ (API 36), with both 64-bit (`arm64-v8a`) and 32-bit (`armeabi-v7a`) ARM architectures.
- 🧪 **Built-In Test SMS & Live Metrics**: Test carrier signal, permissions, and inspect SMS character encoding and segment metrics in-app.
- 🌙 **Modern Material 3 UI**: Live Gateway Hero card with active status pills, dynamic port change auto-restart, and a high-performance log viewer protected against Android OpenGL texture crashes with category filters (All, Errors, SMS).

---

### 📖 Documentation & AI Integration

OpenSMS provides full interactive web documentation as well as dedicated machine-readable endpoints for AI agents and LLMs:

| Resource | Description | Format |
|---|---|---|
| **[Interactive Docs Site](docs/)** | Hosted documentation portal with live cURL generator, SDK examples, and architecture guide. | Web / HTML |
| **[`llms.txt`](llms.txt)** | Standard discovery index for AI coding assistants (Cursor, Windsurf, Claude, ChatGPT). | Plaintext Markdown |
| **[`llms-full.txt`](llms-full.txt)** | Full consolidated API reference and prompt context bundle for LLM context windows. | Plaintext Markdown |
| **[API Reference](docs/api-reference.md)** | Direct machine-readable Markdown specification of all REST endpoints and error codes. | Markdown |
| **[AI Agent Guide](docs/ai-integration.md)** | Tool schemas for OpenAI Function Calling, Anthropic Claude Tools, LangChain, and FastMCP. | Markdown |
| **[OpenAPI 3.1](docs/openapi.json)** | Machine-readable API specification for automated tool generators and Swagger/Postman. | JSON |

---

> **Testing a new build?** Follow [docs/first-run.md](docs/first-run.md) (push, build, install, smoke test).

## 🧑‍💻 Quickstart Guide

### 1. Download & Install
1. Download the latest APK from the [Releases](https://github.com/ShanudhaTirosh/OpenSMS/releases) page.
2. Install the APK on your Android device (temporarily allow installation from unknown sources or Play Protect prompt).
3. Open **OpenSMS** and grant SMS, WakeLock, and Notification permissions.
4. Android may restrict background SMS permissions on newer Android versions:
   - Go to `Settings` > `Apps` > `OpenSMS` > Tap top-right three dots `⋮` > **Allow restricted settings**.
   - Ensure **SMS** permission is allowed.

### 2. Start the Server & Generate API Key
1. Tap **Start Server**.
2. If this is your first time, you will be prompted to **Generate an API Key**.
3. Tap **Generate** and then **Copy Key** to store it securely.

### 3. Send SMS via API
Your device's active network IP addresses (Wi-Fi, VPN, or cellular) are displayed on the home screen.

#### Single SMS
```bash
curl -i -X POST 'http://<DEVICE_IP>:9292/sms/' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer your-secret-api-key' \
  -d '{"number": "+1234567890", "text": "Hello from OpenSMS API!"}'
```

#### Batch SMS (Multiple Recipients)
```bash
curl -i -X POST 'http://<DEVICE_IP>:9292/sms/batch/' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer your-secret-api-key' \
  -d '{
    "messages": [
      {"number": "+1234567890", "text": "Alert 1"},
      {"number": "+0987654321", "text": "Alert 2"}
    ]
  }'
```

#### Health & Telemetry Check
```bash
curl http://<DEVICE_IP>:9292/health/
curl -H 'Authorization: Bearer your-secret-api-key' http://<DEVICE_IP>:9292/system/stats/
```

#### Query Message Delivery Status
```bash
curl -H 'Authorization: Bearer your-secret-api-key' http://<DEVICE_IP>:9292/sms/<MESSAGE_ID>
```

#### Dual-SIM Routing (Optional `sim_slot`)
```bash
curl -i -X POST 'http://<DEVICE_IP>:9292/sms/' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer your-secret-api-key' \
  -d '{"number": "+1234567890", "text": "Dispatching via SIM 2", "sim_slot": 1}'
```


---

## 🌐 Connecting Across Different Networks (Mesh & Remote Access)

When your phone is on cellular data (CGNAT) or home Wi-Fi and your program/backend runs on a remote server, cloud VPS, or laptop on a **completely different network**, you have several easy options:

### Option 1: Tailscale (Recommended)
1. Install [Tailscale](https://tailscale.com) on your Android phone and on your remote server/laptop.
2. Log into the same Tailscale tailnet on both devices.
3. Open **OpenSMS** and navigate to the **Mesh** tab at the bottom navigation bar.
4. OpenSMS reads the phone's `100.x.y.z` Tailscale address from the system and shows **Tailscale: connected**. It never asks for a Tailscale key and does not connect Tailscale for you; if it shows anything else, follow the diagnostics on that screen.
5. Optional: choose **Tailscale only** under *API listening mode* so the API is unreachable from Wi-Fi/LAN.
6. In the **Mesh** screen, select your language (**cURL**, **Python**, **Node.js**, **PHP**, or **Go**) to instantly generate ready-to-use code targeting your remote endpoint!

```python
# Example: Sending SMS from a remote server anywhere in the world to your phone
import requests

url = "http://100.85.x.x:9292/sms/"
headers = {
    "Authorization": "Bearer your-secret-api-key",
    "Content-Type": "application/json"
}
payload = {
    "number": "+1234567890",
    "text": "Alert from Cloud Server dispatched via OpenSMS!"
}
response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

### Option 2: Reverse SSH Tunnel
Run a reverse tunnel from Termux on your phone to your VPS:
```bash
ssh -R 9292:localhost:9292 user@your-vps.com
```
Now requests sent to `http://localhost:9292/sms/` on your VPS will route directly to your phone.

### Option 3: Cloudflare Tunnel / Bore / Ngrok
Expose port 9292 via your preferred tunneling tool to get a public HTTPS endpoint.

---

## 📚 Tech Stack

- **API Layer**: [FastAPI](https://github.com/fastapi/fastapi) & [Uvicorn](https://github.com/encode/uvicorn)
- **UI Framework**: [Kivy](https://github.com/kivy/kivy) & [KivyMD](https://github.com/kivymd/kivymd) (Material 3)
- **Telephony**: Android Native `SmsManager` via PyJNIus with multi-part SMS support

---

## 🧩 Building the APK from Source

### Prerequisites
A Linux environment or WSL2 on Windows with Java 17 and Python 3.10/3.11.

```bash
# Clone the repository
git clone https://github.com/ShanudhaTirosh/OpenSMS.git
cd OpenSMS/app

# Set up virtual environment
python3 -m venv .env
source .env/bin/activate
pip install -r req_android.txt

# Build Android APK using Buildozer
buildozer android debug
```
The compiled APK will be generated inside the `bin/` directory.

---

## 👤 Author & Support

- **Author**: Shanudha Tirosh
- **Website**: [info.shanutechx.com](https://info.shanutechx.com)
- **Email**: [info@shanutechx.com](mailto:info@shanutechx.com)
- **GitHub**: [@ShanudhaTirosh](https://github.com/ShanudhaTirosh)

---

## 📄 License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
