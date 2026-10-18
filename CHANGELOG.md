# App Details

## Changes

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
