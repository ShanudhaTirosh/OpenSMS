# App Details

## Changes

### 0.3.0
- **Tailscale Mesh Hub & Cross-Network Integration**: Added dedicated Remote Mesh hub with live Tailscale status detection, Tailscale CGNAT (`100.64.0.0/10`) interface recognition, and remote endpoint discovery.
- **Multi-Language Client Code Generator**: Built-in 1-tap code generator producing pre-configured connection code for cURL, Python (`requests`), Node.js (`fetch`), PHP (`curl`), and Go (`net/http`).
- **Comprehensive Network Interface Discovery**: Native `NetworkInterface` enumeration on Android and multi-target routing detection classifying Wi-Fi, Ethernet, Cellular, and Tailscale interfaces.
- **Dynamic Port Synchronization & Error Recovery**: Port changes in Settings now trigger immediate service restarts; added `OSError` port-bind exception handling to prevent silent background server crashes.
- **Enhanced Telephony & Dialable Phone Sanitization**: Dialable phone numbers with dashes, spaces, and brackets are automatically sanitized to standard E.164 digits, eliminating carrier rejection on OEM modems.
- **Live SMS Segmentation Calculator**: In-app Test SMS modal displays real-time character count, segment count, and encoding indicators (GSM-7 160 vs UCS-2 70 Unicode).
- **Batch SMS Enhancements**: Added 100-message payload limits, 100ms rate-pacing delay to prevent cellular baseband saturation, and UI event callbacks.
- **Bounded Log Viewer & Filtering**: Prevented Android GPU texture overflow crashes on Qualcomm Adreno devices by bounding log rendering; added instant filters for All, Errors, and SMS.
- **Rate-Limiter Memory Leak Fix**: Periodic eviction of expired IP entries prevents memory leaks during long-running gateway operations.
- **Modern Material 3 UI Overhaul**: Redesigned gateway dashboard with live status pills (Online/Standby), network cards, and elevated theme-aware color styling.

### 0.2.0
- Added multi-network and VPN discovery (displays Wi-Fi, Ethernet, and Tailscale/WireGuard mesh IPs)
- Added built-in VPN & Cross-Network Guide (step-by-step for Tailscale, WireGuard, SSH reverse tunnel)
- Added in-app Test SMS sender to verify cellular connectivity without curl
- Added Batch SMS endpoint (/sms/batch/) for multiple message dispatches
- Added Health check endpoint (/health/ and /)
- Added IP rate-limiting & brute-force protection on API authentication
- Added strict phone number format validation
- Added support for older Android devices: lowered minapi to 24 (Android 7.0+) and added armeabi-v7a (32-bit ARM)
- Guarded POST_NOTIFICATIONS runtime permissions for older Android versions (SDK < 33)
- Fixed SMS truncation for messages >160 characters using divideMessage & sendMultipartTextMessage
- Fixed thread-safety violations by routing UI property updates through Kivy Clock
- Fixed Python < 3.12 syntax errors caused by nested f-string quotes
- Fixed race condition in IPC file exchange using atomic file writes
- Fixed thread target function execution bug in clear_logs
- Fixed missing "app" key in reset_settings and added reset confirmation dialog
- Fixed port range validation (1025-65535) and input bounds
- Added Dark / Light theme toggle in Settings
- Replaced deprecated FULL_WAKE_LOCK with battery-efficient PARTIAL_WAKE_LOCK
- Added log rotation (2MB limit) to protect storage on long-running Android devices

### 0.1.1

- Fixing app crash on some mobile GPU with kivymd 2.x . Thanks to [DorDeorz](https://github.com/DorDeorz) for the fix in [UniversalDownlaoder](https://github.com/DorDeorz/UniversalDownloader).

### 0.1.0
- App will check if required permissions are granted
- Adding logging for API requests
- Fixing the android bottom padding
- Adding a back button

### 0.0.1
- Initial version
