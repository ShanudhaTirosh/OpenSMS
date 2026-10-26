# App Details

## Changes

### 0.5.0 (2026-10-26)

#### System & diagnostics
- **System & diagnostics screen** (menu drawer): shows whether the background service is alive (with a heartbeat age), the API server state and listening address, queue size, wake lock, SMS and Phone permissions, whether delivery tracking is active, SIM detection, Tailscale state, storage and app facts, each with a plain-language hint when something is wrong. **Copy report** copies a text report that never contains keys, phone numbers or message text.
- **Maintenance**: clear finished messages older than 30 days, or all finished messages (with confirmation). Messages that are still being sent and API keys are never touched.
- **Fix**: SMS receipts are now registered only in the service process (the app and the service both registered the receiver, so every receipt would have been processed twice).

#### Updater & installer
- **In-app update install now uses Android's `PackageInstaller`** (the app streams the APK to the system, no `FileProvider` needed), with the previous install intent and the release page as fallbacks. A conflict (typically a differently signed APK) is explained with its remedy. New Java classes in `app/java_src` (`InstallResultReceiver`, `InstallResultListener`).

#### Background operation
- **The gateway keeps running when you close the app** and stops only when you press Stop Server. The service is now sticky (restarted by Android if killed) and no longer stops when the app task is removed.
- **Service type changed from `dataSync` to `specialUse`**: on Android 15+ a `dataSync` service is limited to 6 hours per 24 h and the app crashes when the timeout fires. New permission `FOREGROUND_SERVICE_SPECIAL_USE` replaces `FOREGROUND_SERVICE_DATA_SYNC`.
- **Reopening the app no longer stops the server**: the last choice (running / stopped) is restored, and a running service's status is kept (it used to be deleted and a "stop" request written at every launch).
- The CPU wake lock is now held by the service (it used to die with the app). New **Keep running in background** shortcut in Settings opens Android's battery settings.
- The service writes a heartbeat so the app can tell a live service from a stale status file. In-app sending says so when the service is not running.
- CI: the debug signing key is cached so test builds install over each other.

#### In-app sending & outbox IPC
- **New message** (Messages tab, top-right button): write a number and text with a live segment counter, inline validation, a review/confirm step and a double-tap guard. The message is handed to the gateway service through an outbox, so it appears in the history with its real status and receipts. The Home "Test SMS" dialog now uses the same path (it used to bypass the message table).
- Crash-safe: the file name is the message id and the service ignores ids it already knows, so a crash can never send a message twice; malformed items are set aside as `*.bad`; a full queue just delays the message.

#### Build, release & documentation
- **Battery / IPC**: the service no longer parses `request.json` five times a second. It reads the file only when it changed and polls once a second after 10 s without commands (a command after a long idle is picked up within about a second). Atomic file writes use a unique temp name per thread, so concurrent writers can no longer collide.
- **Release pipeline**: new `ci.yml` (ruff, tests on Python 3.11/3.12 with pinned deps, `pip-audit`, headless UI smoke test). `release.yml` now requires a validated `vX.Y.Z` tag equal to `app/app_version.py`, **signs** the APK from repository secrets (fails instead of publishing a debug-signed release; a manual opt-in publishes a debug-signed *pre*-release), publishes `.sha256` files, and no longer interpolates workflow inputs into shell. python-for-android and KivyMD are pinned by commit.
- **Pinned, audited dependencies**: `fastapi 0.162.0`, `starlette 1.9.0` (fixes known advisories in the previous `0.48`), `uvicorn 0.34.3`, `pydantic 2.12.3` (matches the local pydantic-core recipe), etc. in `requirements-core.txt`, `constraints.txt` and `buildozer.spec` (a test keeps them in sync). `requests` is now declared.
- **Updater**: only accepts release-asset URLs of the configured repository (`UPDATE_REPO` in `app/app_version.py`), verifies the published SHA-256, and tells you when no checksum was available. If the installer cannot be opened it opens the release page.
- **SIM routing**: the app now requests `READ_PHONE_STATE`; `GET /system/sims/` reports `reliable`; `sim_slot` requests are refused with an explanation when Android cannot be asked instead of silently using the default SIM.
- Single version source `app/app_version.py`; removed the unused `services/postFlask.py`; `docs/openapi.json` is generated from the app (`tools/gen_openapi.py`) and a test fails if it is stale; corrected stale documentation claims; added `docs/security.md`, `docs/deployment.md`, troubleshooting table and `.env.example`.

#### UI / UX
- **Messages tab** (new): searchable, filterable (queued / submitted / sent / delivered / failed / unknown), paginated history with colour-coded status chips, a detail dialog (what the status means, failure reason, per-part progress, SIM, provider, id), loading skeletons, empty and error states, and auto-refresh every 5 s while open.
- **API tab** (new): list keys (name, prefix, permissions, created, last used, active/revoked), create a key with Send/Read/Admin permissions (inline validation, double-submit guard, key shown once with an explicit Copy button) and revoke with confirmation. This is the in-app way to revoke keys.
- Bottom navigation is now SMS / Messages / API / Mesh / Settings (Logs stays in the menu drawer).
- Shared components (`StatusChip`, `EmptyState`, `SkeletonRow`) and a Kivy-free presentation layer (`services/uiFormat.py`) with unit tests.

#### Tailscale mesh networking
- **Removed the fake in-app "connect"**: typing a `100.x` address or pasting a key used to show "Connected" with no tunnel. OpenSMS now only *observes* the Tailscale app (see `docs/tailscale.md`) and never stores or asks for a Tailscale key; keys/IPs stored by older versions are deleted on first start.
- **Honest status** (connected / other VPN / not connected / unavailable) from the OS's VPN networks, with diagnostics. Carrier-grade-NAT addresses in `100.64.0.0/10` on cellular/Wi-Fi interfaces are no longer mistaken for Tailscale. IPv6 tailnet addresses recognised.
- **API listening mode** (Mesh screen): *All networks* (default, unchanged), *Tailscale only* (fails closed, never falls back), *This phone*. The server retries a blocked Tailscale-only start every 10 s.
- **Fix**: a failed server bind (port in use, address unavailable) was silent and the UI kept showing "started"; it now reports the error.
- Mesh screen: explicit "Tailscale app" launcher intent, PHP snippet chip, buttons/chips wrap on narrow phones, snippets no longer contain any API key.
- New permission `ACCESS_NETWORK_STATE` (normal, no prompt).

#### SMS reliability & lifecycle
- **Honest message lifecycle**: `queued` -> `submitted` (handed to Android) -> `sent` (radio accepted every part) -> `delivered` (status report confirmed every part) / `failed` / `unknown` (no result ever arrived). `delivered` is only ever set from a real delivery report; many carriers never send one, in which case the message correctly stays `sent`. Android sent/delivery results are captured per message part (new `parts` array on `GET /sms/{id}`).
- **Send queue**: sends run on a background worker (bounded queue of 1000, 100 ms pacing) instead of blocking the API event loop. `POST /sms/` still waits for the hand-off and answers as before; if the worker is busy for more than `OPENSMS_SUBMIT_WAIT_SECONDS` (default 15) it returns `202` with `status: queued`. A full queue returns `503 queue_full` (+`Retry-After`). Queued messages are re-queued after a restart; messages whose outcome is ambiguous are marked `unknown` and never re-sent.
- **SIM validation**: an inactive `sim_slot` now returns `422 invalid_sim_slot` instead of silently using the default SIM.
- **Accurate segment estimates**: GSM-7 extension characters (EUR, `[`, `]`, `{`, `}`, `\\`, `^`, `~`, `|`) cost 2 septets, emoji cost 2 UTF-16 units, characters are never split across segments; the backtick is correctly treated as non-GSM.
- **Simulation is opt-in**: outside Android nothing is "sent" unless `OPENSMS_ALLOW_SIMULATION=1`, and such messages carry `provider: simulated`.
- Database schema v2 (additive): `message_parts` table, `messages.provider`, `messages.parts_expected`.

#### API architecture & idempotency
- **Idempotency**: send `Idempotency-Key: <1-128 chars>` on `POST /sms/` and `POST /sms/batch/`. A retry with the same key returns the original response (header `Idempotent-Replay: true`) and never sends another SMS or uses rate-limit quota. Same key + different body -> `422 idempotency_key_reuse`; still running -> `409 request_in_progress`; a failed send releases the key so it can be retried. Keys are per API key and kept 24 h. Requests without the header behave exactly as before.
- **Unified error envelope** (additive): every error keeps the legacy `detail` field and adds `error: {code, message}` (e.g. `unauthorized`, `insufficient_scope`, `validation_error`, `send_rate_limited`, `not_found`).
- **Pagination**: `GET /sms/history` now returns `total` and `has_more` (and a stable sort order).
- **Schema migrations**: database versioned with `PRAGMA user_version` (now v1, adds the `idempotency` table; existing tables/rows untouched). A database written by a newer app version is refused rather than modified.

#### Security & scopes
- **Scopes are now enforced** (`sms:write` send, `sms:read` history/stats/update, `admin` keys/control). Keys created by the app carry `sms:write`+`sms:read`, so existing clients are unaffected.
- **Key lifecycle**: SQLite is the single source of truth. Legacy `keys.json` is imported once and renamed to `keys.json.migrated` (previously a revoked key kept working through it). New admin-only endpoints: `GET/POST /keys/`, `DELETE /keys/{id}`. Generating a key does **not** revoke others; the dialog text now says so.
- **Rate limiting**: failed-auth lockout uses the socket address only (`X-Forwarded-For` is ignored); new per-key send limit (`OPENSMS_SEND_RATE_PER_MIN`, default 300, `0` disables) returning `429` + `Retry-After`.
- **Honest delivery reporting**: `sent` means handed to Android's telephony layer; `delivered_at` is only set for a real `delivered` status. Send responses add `delivery_confirmed: false`; the message text no longer says "sent successfully".
- `/docs`, `/openapi.json`, `/llms.txt`, `/docs/markdown` require auth unless `OPENSMS_PUBLIC_DOCS=1`.
- `GET /sms/history` works with or without trailing slash; SMS text limited to 1600 chars; search treats `%`/`_` literally; "sent today" uses local midnight.
- SQLite connections are always closed; nothing is created at import time; phone numbers are masked in logs; one log-writer thread.
- Tailscale credentials are no longer stored or shown (older stored keys are scrubbed on start); API keys are no longer auto-copied to the clipboard; Android auto-backup disabled; `requests` added to requirements.


### 0.4.0
- **In-App GitHub Releases Auto-Updater**: Automatic background update detection against GitHub Releases API with notification banner, manual check option in Settings and Navigation Drawer, chunked APK downloader with progress reporting, and 1-tap Android package installation via native `Intent(ACTION_VIEW)`.
- **SQLite WAL Message Persistence**: Added robust SQLite database layer operating in Write-Ahead Logging (`WAL`) mode with automatic indexing, message status tracking (`queued`, `sent`, `failed`), retry counters, and concurrent thread safety.
- **Live Home Metrics Dashboard**: Real-time stats dashlet displaying Sent Today counter, Success Rate percentage, and Queue Depth with immediate UI synchronization.
- **Telephony & Multi-SIM Engine**: Added multi-SIM detection and routing using Android `SubscriptionManager`, allowing selection between Auto, SIM 1, and SIM 2 via in-app UI and the REST API.
- **Expanded REST API**:
  - `GET /sms/{id}`: Query real-time message status, delivery timestamp, and error details.
  - `GET /sms/history/`: Paginated SMS history with limit, offset, and status filtering.
  - `GET /system/stats/`: Real-time gateway telemetry, throughput metrics, and uptime.
  - `GET /system/sims/`: Active cellular subscriptions and carrier identifiers.
  - `GET /system/update/`: Check for newer OpenSMS GitHub releases via API.
- **Multi-Token API Security**: Added support for multiple named API keys with granular permission scopes (`sms:send`, `sms:read`, `admin`) and individual revocation while maintaining full backwards compatibility with legacy `keys.json`.
- **Programmatic Switch Event Guard (BUG-03 Fix)**: Resolved recurring event loops in KivyMD 2.x `MDSwitch` by implementing a reentrant refresh guard across Settings.
- **Activity Heartbeat Synchronization**: Bidirectional IPC activity timestamps keep the UI gateway hero card responsive to background cellular and API events.

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
