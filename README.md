<p align="center"><img width="20%" src="app/data/images/favicont512.png" /></p>

# 📨 OpenSMS

An open-source, privacy-first Android application that turns your Android phone into a high-performance **SMS Gateway & REST API server**.

Developed & maintained by **[Shanudha Tirosh](https://info.shanutechx.com)**.

---

### ✨ Key Features

- 📱 **Turns your Android device into an SMS REST API gateway**.
- 🌐 **Cross-Network & VPN Ready**: Works across different networks and worldwide via **Tailscale**, **WireGuard**, **Cloudflare Tunnel**, or **Reverse SSH Tunnels**.
- 🔒 **Privacy Focused & Secure**: No third-party data tracking, no ads. Built-in SHA-256 API token authentication and brute-force rate-limiting.
- 📦 **Batch SMS Support**: Send multiple SMS messages in a single API call via `/sms/batch/`.
- 💬 **Long / Multipart SMS Support**: Automatic message splitting with `divideMessage` and `sendMultipartTextMessage` (messages >160 characters won't be truncated).
- 📱 **Wide Device Compatibility**: Supports Android 7.0 (API 24) up to Android 15+ (API 36), with both 64-bit (`arm64-v8a`) and 32-bit (`armeabi-v7a`) ARM architectures.
- 🧪 **Built-In In-App Test SMS**: Test phone carrier signal and permissions directly from the app UI without terminal commands.
- 🌙 **Modern Material 3 UI**: Includes Dark Theme, active IP addresses display, quick-copy API endpoints, and real-time logs.

---

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

#### Health Check
```bash
curl http://<DEVICE_IP>:9292/health/
```

---

## 🌐 Connecting Across Different Networks (VPN & Remote Access)

If your client (e.g. server, cloud VPS, laptop) is on a **different network** than your phone:

### Option 1: Tailscale (Recommended & Zero-Config)
1. Install [Tailscale](https://tailscale.com) on your Android phone and on your remote machine/server.
2. Log into the same account on both devices.
3. OpenSMS will display your phone's private Tailscale IP (e.g., `100.85.x.x`).
4. You can now send SMS from anywhere in the world:
   ```bash
   curl -X POST 'http://100.85.x.x:9292/sms/' ...
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
