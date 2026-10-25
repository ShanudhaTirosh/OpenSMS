# 🚀 OpenSMS Quickstart & Operator Guide

This guide walks you through setting up an Android device as a 24/7 cellular SMS Gateway, establishing cross-network connectivity, and dispatching your first API request.

---

## 📱 1. Requirements
- **Android Phone or Tablet**: Running Android 7.0 (API 24) up to Android 15+ (API 36).
- **SIM Card**: Active cellular subscription with SMS text messaging allowance.
- **Network**: Wi-Fi, Cellular Data, or VPN (Tailscale, WireGuard).
- **Optional**: Secondary SIM card for dual-carrier routing.

---

## 📥 2. Installation & Android Permissions

### Step 1: Install the APK
1. Download the latest `OpenSMS-v0.4.0.apk` from the [GitHub Releases](https://github.com/ShanudhaTirosh/OpenSMS/releases) page.
2. Open the file on your Android device and confirm installation (allow unknown sources if prompted).
3. If Google Play Protect displays a prompt, tap **More details** $\rightarrow$ **Install anyway**.

### Step 2: Grant Permissions
When you open OpenSMS for the first time, grant the requested permissions:
- **Send and view SMS messages**: Required to access native cellular modem.
- **Keep device awake (WakeLock)**: Allows the background service to process incoming HTTP requests even when the screen is locked.
- **Notifications** (Android 13+): Displays a persistent foreground service indicator.

### Step 3: Bypass "Restricted Settings" (Android 13, 14, 15+)
On newer Android versions, sideloaded applications have SMS permissions restricted by default:
1. Open phone **Settings** $\rightarrow$ **Apps** $\rightarrow$ **OpenSMS**.
2. Tap the **three dots `⋮`** in the top-right corner.
3. Tap **Allow restricted settings**.
4. Go back to **Permissions** $\rightarrow$ enable **SMS**.

### Step 4: Disable Battery Optimization
To ensure Android doesn't kill OpenSMS in the background:
1. Go to **Settings** $\rightarrow$ **Battery** $\rightarrow$ **App battery usage** $\rightarrow$ **OpenSMS**.
2. Select **Unrestricted** (or **Don't optimize**).
3. On OEM skins (MIUI, HyperOS, ColorOS, Samsung OneUI), enable **Autostart** in system settings.

---

## 🔑 3. Generating Your First API Key

1. Launch OpenSMS on your phone.
2. Tap **Start Server**.
3. If this is your first time, a dialog will appear: **"Generate API Key"**.
4. Tap **Generate**. A cryptographic key starting with `osms_...` will be created and copied to your clipboard.
5. Store this key in your `.env` or password manager. It will not be shown again in plain text!

---

## 🌐 4. Cross-Network Connectivity (Reaching Your Phone Anywhere)

When your phone is on cellular mobile data or behind home Wi-Fi (CGNAT), and your application server runs on a cloud VPS (AWS, GCP, DigitalOcean) or a developer laptop, use one of the following methods:

### Method A: Tailscale (Recommended)
1. Install **Tailscale** on your Android phone from Google Play Store or F-Droid.
2. Install **Tailscale** on your remote server or laptop.
3. Log in with the same account on both devices.
4. In OpenSMS, tap the **Mesh** tab.
5. OpenSMS reads the phone's `100.x.y.z` Tailscale address from the system and shows **Tailscale: connected**. It does not connect Tailscale for you and never asks for a Tailscale key.
6. Send API requests to `http://100.x.y.z:9292/sms/` from any device on the same tailnet. Choose *Tailscale only* under *API listening mode* to keep the API off Wi-Fi/LAN. See [tailscale.md](tailscale.md) for states and troubleshooting.

### Method B: Reverse SSH Tunnel
Run an SSH reverse tunnel from Termux on your phone to your remote VPS:
```bash
# In Termux on your phone:
ssh -N -R 9292:localhost:9292 user@your-cloud-vps.com
```
Now requests sent to `http://localhost:9292/sms/` on your VPS will route directly to your phone.

### Method C: Local Wi-Fi
If your server and phone are connected to the same local Wi-Fi router, send requests to the local IP address displayed on the OpenSMS home screen (e.g. `http://192.168.1.150:9292/sms/`).

---

## 🛠️ 5. Dispatching Your First SMS

Replace `<DEVICE_IP>` with your phone's IP address and `<YOUR_API_KEY>` with your key:

```bash
curl -i -X POST 'http://<DEVICE_IP>:9292/sms/' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer osms_your_secret_key' \
  -d '{
    "number": "+1234567890",
    "text": "Hello world from OpenSMS Gateway!"
  }'
```

Response:
```json
{
  "id": "3f2b8c1a-9d4e-4a6b-8c2d-7e1f0a5b9c42",
  "number": "+1234567890",
  "stat": true,
  "sim_slot": 0,
  "segments": 1,
  "encoding": "GSM-7"
}
```

---

## 📶 6. Dual-SIM Telephony Configuration

If your device has two SIM cards installed:
1. Open **Settings** inside OpenSMS.
2. Find the **Preferred SIM Slot** setting under **Telephony & Cellular**.
3. Tap **Auto** to cycle between:
   - **Auto**: Automatically uses your device's default cellular call/data preference.
   - **SIM 1**: Forces dispatch through Carrier Slot 1.
   - **SIM 2**: Forces dispatch through Carrier Slot 2.
4. You can also override the SIM slot on individual API calls using `"sim_slot": 0` or `"sim_slot": 1`.

---

## 🔨 7. Building the APK from Source

If you prefer building the APK yourself:

```bash
# Clone the repository
git clone https://github.com/ShanudhaTirosh/OpenSMS.git
cd OpenSMS/app

# Set up build environment on Linux / WSL2
python3 -m venv .env
source .env/bin/activate
pip install -r req_android.txt

# Run Buildozer to compile APK
buildozer android debug
```
The compiled package will be output to `app/bin/opensms-0.4.0-arm64-v8a_armeabi-v7a-debug.apk`.
