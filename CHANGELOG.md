# App Details

## Changes

### 0.5.5 (2026-11-21)

#### UI/UX & Visual Ergonomics
- **Hero Card Above-the-Fold Placement**: Repositioned the primary Server toggle button ("Start Server" / "Stop Server") inside the Gateway Hero Status Card, eliminating scrolling past network addresses and metrics on compact mobile screens.
- **WCAG AA Dynamic Color Contrast**: Upgraded `STATUS_STYLE` color tuples to darker, high-contrast values achieving $\ge 4.5:1$ contrast against light card backgrounds.
- **M3 Streamlined Compose Flow**: Consolidated the previous two-step confirmation dialog into a unified single dialog featuring real-time segment and character metrics, SIM slot indicator, and direct Send submission.
- **Touch Target & Accessibility Upgrades**: Standardized all icon buttons, filter chips, and interactive cards to adhere to the Material 3 48dp minimum touch target standard.
- **Navigation State Synchronization**: Synchronized bottom navigation bar active states when navigating to secondary screens (`System`, `Logs`) to highlight the parent Settings tab.

#### Feature Expansions
- **In-App Webhooks Management UI**: Added a full in-app Webhooks management dialog enabling users to list active webhook destinations, add new endpoints with HMAC secrets, test delivery pings, and delete active webhooks directly on device.
- **Client Pairing & Quick Connect**: Added a "Connect" action dialog providing base Gateway URLs, Bearer authentication syntax, and one-tap copyable cURL commands for instant client integration.
- **Per-SIM Quota & Usage Analytics**: Added per-SIM message traffic breakdown in `get_metrics()`, surfacing daily volume per SIM slot in the diagnostics report.
- **Message History CSV Export**: Implemented CSV export pipeline that writes `opensms_export.csv` to app storage and copies data to the clipboard from both Messages and System screens.

#### Performance & Perceived Loading
- **In-Place Message List Diffing**: Refactored `MessagesBox._apply()` to perform non-destructive in-place diffing on quiet background auto-refreshes, preserving user scroll positions and eliminating list rebuild flicker.
- **Reverse Byte-Seeking Log Viewer**: Optimized `LogService.get_recent_logs()` using reverse byte-seeking from the end of the file (reading only trailing ~64KB), eliminating reading entire multi-megabyte log files into memory.
- **Lifecycle-Bound Polling**: Bound background Tailscale status polling strictly to screen entry (`on_enter`) and exit (`on_leave`), stopping unnecessary background wakeups when viewing other screens.
- **Network Discovery Throttle**: Relaxed periodic network interface discovery polling interval from 5.0s to 10.0s to conserve battery life.

#### Stability, Architecture & Android 15
- **Atomic Batch SQLite Ingestion**: Implemented `DatabaseManager.create_messages_batch()` using atomic `executemany` in a single transaction, preventing SQLite database lock contention during concurrent batch dispatches.
- **Thread-Safe UI Marshaling**: Safely marshaled all dialog, toast, and snackbar invocations through `Clock.schedule_once` when invoked from background worker threads, eliminating GLES/SDL rendering crashes.
- **Auto-Update Storage Sanitation**: Added automatic cleanup of stale `.apk` and `.tmp` files in the download directory before downloading new updates.
- **Target SDK 35 (Android 15)**: Aligned target Android API to production-standard API 35 with `#0F172A` presplash styling in `buildozer.spec`.
- **Monotonic Version Code (505)**: Incremented `android.numeric_version` to `505` in `app/buildozer.spec`.

#### Event Webhooks & Delivery Callbacks
- **Asynchronous Webhook Subsystem (`webhookSvc`)**: Real-time non-blocking HTTP POST delivery callbacks (`sms.submitted`, `sms.sent`, `sms.delivered`, `sms.failed`) with 5s timeout and thread-pool execution.
- **HMAC-SHA256 Cryptographic Signatures**: Computes `X-OpenSMS-Signature` header over raw JSON payload using the configured webhook secret for tampering prevention.
- **REST Endpoints**: Added `GET /webhooks/`, `POST /webhooks/`, `DELETE /webhooks/{webhook_id}`, and `POST /webhooks/test/{webhook_id}` requiring `admin` scope.

#### Telemetry & Device Battery State
- **Battery Telemetry (`batterySvc`)**: Cross-platform Android battery monitoring (`ACTION_BATTERY_CHANGED`) reporting level percentage, charging state (`is_charging`), and power source (`ac`, `usb`, `wireless`, `unplugged`) in `GET /system/stats/`.

### 0.5.4 (2026-11-05)

#### Package Installation & In-App Updater
- **Monotonic Version Code Increment (504)**: Incremented `android.numeric_version` to `504` to resolve Android's `INSTALL_FAILED_VERSION_DOWNGRADE` (`STATUS_FAILURE_INVALID`), which causes the system dialog "App not installed as package appears to be invalid" when attempting to install an APK with the same or lower version code over an existing installation.
- **Enhanced `PackageInstaller.SessionParams`**: Configured `params.setAppPackageName(package)` and `params.setSize(size)` during in-app update streaming sessions so Android's package manager pre-allocates resources and targets updates accurately.
- **Improved Failure Guidance**: Added clearer messaging for `STATUS_FAILURE_INVALID` advising that updates require a higher version code than the installed build.

#### UI/UX Refinements
- **Remote Mesh Input Fields**: Updated `emb_key`, `emb_host`, and `emb_ctrl` text fields on the Remote Mesh screen to `mode: "filled"` to prevent floating label overlap and border clipping artifacts on colored surface cards.
- **Settings Server Port Input**: Updated `port_no_inp` styling with fixed width and centered text alignment (`halign: "center"`) preventing 4-digit port numbers (e.g. `9292`) from being squeezed or clipped against list item edges.

### 0.5.3 (2026-11-05)

#### SMS Delivery Tracking & Status Pipeline
- **Fixed SMS Sent & Delivery Receipt Broadcasts**: Resolved Android Intent matching issue where PendingIntents carrying `opensms://...` data URIs were dropped by dynamic `IntentFilters` lacking `<data>` scheme registration. Configured `addDataScheme("opensms")`, fallback action filters, and distinct PendingIntent request codes per part/kind. Messages now accurately transition through `queued` $\to$ `submitted` $\to$ `sent` $\to$ `delivered`.
- **API Response Clarity**: Updated `/sms/` endpoints to return distinct, accurate messages for `submitted`, `sent`, and `delivered` states.

#### Live Home Screen Tailscale State
- **Added `on_resume` Lifecycle Refresh**: Implemented `on_resume()` in `MDApp` and scheduled a live 5-second periodic refresh so connection status and network IP addresses automatically refresh when switching back from the Tailscale app or other applications.
- **Embedded & Mesh Detection**: Integrated built-in Tailscale (`ts_embedded`) engine state with system VPN detection so the home screen status chip, icon, and endpoint labels display live connectivity across all operating modes.

#### UI/UX Polish & Responsive Layout
- **Fixed Clipped Buttons on Remote Mesh Screen**: Replaced rigid 3-column layout in API listening mode with a clean, responsive multi-row layout so "This phone only (Localhost)" and surrounding controls never overflow or get clipped on narrow screens.
- **Flexible Quick Operations & Button Feedback**: Streamlined Quick Operations buttons on Home screen to fit mobile screens cleanly. Upgraded `ButtonControl` with proper RGBA Material colors and feedback for start, stop, error, and loading states.

#### Input Field Configuration
- **Specialized Keyboards & IME Configuration**: Set `input_type="tel"` on phone inputs (Test SMS dialog and Compose screen), `input_type="number"` on server port inputs, and `input_type="text"` / `input_type="url"` on Tailscale and search fields.

#### In-App Updater & Persistent Signing Keystore
- **Fixed Install-Over-Existing Bug**: Configured GitHub Actions release pipeline to cache and persist the fallback signing keystore with a 10,000-day certificate, eliminating signature mismatches between versions.
- **FileProvider Configuration**: Declared `androidx.core.content.FileProvider` in `app/buildozer.spec` and `app/extra_manifest_application_arguments.xml` with `file_paths.xml` resource mapping.
- **Install Permission Guard**: Added `canRequestPackageInstalls()` check directing the user to Android Settings (`ACTION_MANAGE_UNKNOWN_APP_SOURCES`) when required.
- **Monotonic Version Code**: Set `android.numeric_version = 503` ensuring strictly increasing version codes.

### 0.5.2 (2026-11-05)

#### Built-in Tailscale Engine (Android 11+ Sandbox Compatibility)
- **Fixed `route ip+net: netlinkrib: permission denied`**: Starting with Android 11 (API 30+), untrusted applications in the Android sandbox are denied direct access to `NETLINK_ROUTE` sockets. Added `app/native/android_netmon.go` providing a custom interface fallback using UDP routing queries and enabling `androiddns` so `tsnet` starts up seamlessly without crashing on netlink permission restrictions.

### 0.5.1 (2026-11-01)

#### Built-in Tailscale Engine & Lifecycle (Experimental)
- **Built-in Tailscale**: the app can join your tailnet **itself** (no Tailscale app, no VPN permission) using an **auth key** or an **API access token** (used once to mint a single-use key, never stored), and forwards tailnet connections to the local API, so any device on your tailnet can use it. Shows the other devices on the tailnet. The node's identity is kept, so restarts and reboots need no key; **Forget** removes it.
- **Lifecycle & Deadlock Resolution**: Fixed Tailscale deadlock when running in "Tailscale only" mode where service wasn't started; `ts_embedded_connect` now automatically starts the background service and safely handles secret provisioning.
- **Cross-Platform C Foreign Function Interface**: Added Windows C-runtime memory management and socket detachment in `tsNative` and test mock suites.
- Runs in the background service (survives closing the app); state changes appear in the app immediately. A **crash guard** switches the engine off after repeated unexpected service deaths until you press Connect.
- Built from Tailscale's `libtailscale` by CI (`tools/build_libtailscale.py`; best effort: without it the APK still builds and the card says "not in this build"). New `native-tailscale` CI job runs an integration test against the real library on Linux.
- Python binding checked against the real `tailscale.h`; the relay handles large simultaneous transfers (found and fixed a deadlock in my first single-threaded relay); keys are redacted everywhere including the engine log, which the diagnostics report includes.
- **Not verified on a phone.** See `docs/tailscale.md` ("Why it is experimental") and `docs/device-test-plan.md` section 8.

#### In-App Auto-Updater & Package Installer
- **In-app update install now uses Android's `PackageInstaller`** (the app streams the APK to the system, no `FileProvider` needed), with the previous install intent and the release page as fallbacks. A conflict (typically a differently signed APK) is explained with its remedy. New Java classes in `app/java_src` (`InstallResultReceiver`, `InstallResultListener`). Device-untested.
- **Install Permission Settings (Unknown Sources)**: Added Android Unknown Sources (`MANAGE_UNKNOWN_APP_SOURCES`) direct settings navigation (`can_install_packages()` and `open_install_permission_settings()`), background download throttling, and concurrent download guards.
- **Verified Downloads**: Only accepts release-asset URLs of the configured repository (`UPDATE_REPO` in `app/app_version.py`), verifies the published SHA-256, and tells you when no checksum was available. If the installer cannot be opened it opens the release page.

#### System & Diagnostics
- **System & diagnostics screen** (menu drawer): shows whether the background service is alive (with a heartbeat age), the API server state and listening address, queue size, wake lock, SMS and Phone permissions, whether delivery tracking is active, SIM detection, Tailscale state, storage and app facts, each with a plain-language hint when something is wrong. **Copy report** copies a text report that never contains keys, phone numbers or message text.
- **Maintenance**: clear finished messages older than 30 days, or all finished messages (with confirmation). Messages that are still being sent and API keys are never touched.
- **Fix**: SMS receipts are now registered only in the service process (the app and the service both registered the receiver, so every receipt would have been processed twice).

#### Background Operation & Battery
- **The gateway keeps running when you close the app** and stops only when you press Stop Server. The service is now sticky (restarted by Android if killed) and no longer stops when the app task is removed.
- **Service type changed from `dataSync` to `specialUse`**: on Android 15+ a `dataSync` service is limited to 6 hours per 24 h and the app crashes when the timeout fires. New permission `FOREGROUND_SERVICE_SPECIAL_USE` replaces `FOREGROUND_SERVICE_DATA_SYNC`.
- **Reopening the app no longer stops the server**: the last choice (running / stopped) is restored, and a running service's status is kept (it used to be deleted and a "stop" request written at every launch).
- The CPU wake lock is now held by the service (it used to die with the app). New **Keep running in background** shortcut in Settings opens Android's battery settings.
- The service writes a heartbeat so the app can tell a live service from a stale status file. In-app sending says so when the service is not running.
- **Battery / IPC**: the service no longer parses `request.json` five times a second. It reads the file only when it changed and polls once a second after 10 s without commands (a command after a long idle is picked up within about a second). Atomic file writes use a unique temp name per thread, so concurrent writers can no longer collide. Added write lock mutex and retry backoff around atomic JSON state file replacement on Windows NTFS.
- CI: the debug signing key is cached so test builds install over each other.

#### In-App Sending & Outbox IPC
- **New message** (Messages tab, top-right button): write a number and text with a live segment counter, inline validation, a review/confirm step and a double-tap guard. The message is handed to the gateway service through an outbox, so it appears in the history with its real status and receipts. The Home "Test SMS" dialog now uses the same path (it used to bypass the message table).
- Crash-safe: the file name is the message id and the service ignores ids it already knows, so a crash can never send a message twice; malformed items are set aside as `*.bad`; a full queue just delays the message.

#### UI & Presentation Layer
- **Messages tab** (new): searchable, filterable (queued / submitted / sent / delivered / failed / unknown), paginated history with colour-coded status chips, a detail dialog (what the status means, failure reason, per-part progress, SIM, provider, id), loading skeletons, empty and error states, and auto-refresh every 5 s while open.
- **API tab** (new): list keys (name, prefix, permissions, created, last used, active/revoked), create a key with Send/Read/Admin permissions (inline validation, double-submit guard, key shown once with an explicit Copy button) and revoke with confirmation. This is the in-app way to revoke keys.
- Bottom navigation is now SMS / Messages / API / Mesh / Settings (Logs stays in the menu drawer).
- Shared components (`StatusChip`, `EmptyState`, `SkeletonRow`) and a Kivy-free presentation layer (`services/uiFormat.py`) with unit tests.

#### Tailscale Network Integration
- **Removed the fake in-app "connect"**: typing a `100.x` address or pasting a key used to show "Connected" with no tunnel. OpenSMS now only *observes* the Tailscale app (see `docs/tailscale.md`) and never stores or asks for a Tailscale key; keys/IPs stored by older versions are deleted on first start.
- **Honest status** (connected / other VPN / not connected / unavailable) from the OS's VPN networks, with diagnostics. Carrier-grade-NAT addresses in `100.64.0.0/10` on cellular/Wi-Fi interfaces are no longer mistaken for Tailscale. IPv6 tailnet addresses recognised.
- **API listening mode** (Mesh screen): *All networks* (default, unchanged), *Tailscale only* (fails closed, never falls back), *This phone*. The server retries a blocked Tailscale-only start every 10 s.
- **Fix**: a failed server bind (port in use, address unavailable) was silent and the UI kept showing "started"; it now reports the error.
- Mesh screen: explicit "Tailscale app" launcher intent, PHP snippet chip, buttons/chips wrap on narrow phones, snippets no longer contain any API key.
- New permission `ACCESS_NETWORK_STATE` (normal, no prompt). Device testing required: `docs/device-test-plan.md` section 4.

#### SMS Reliability & Telephony
- **Honest message lifecycle**: `queued` -> `submitted` (handed to Android) -> `sent` (radio accepted every part) -> `delivered` (status report confirmed every part) / `failed` / `unknown` (no result ever arrived). `delivered` is only ever set from a real delivery report; many carriers never send one, in which case the message correctly stays `sent`. Android sent/delivery results are captured per message part (new `parts` array on `GET /sms/{id}`).
- **Send queue**: sends run on a background worker (bounded queue of 1000, 100 ms pacing) instead of blocking the API event loop. `POST /sms/` still waits for the hand-off and answers as before; if the worker is busy for more than `OPENSMS_SUBMIT_WAIT_SECONDS` (default 15) it returns `202` with `status: queued`. A full queue returns `503 queue_full` (+`Retry-After`). Queued messages are re-queued after a restart; messages whose outcome is ambiguous are marked `unknown` and never re-sent.
- **SIM validation & routing**: the app now requests `READ_PHONE_STATE`; `GET /system/sims/` reports `reliable`; an inactive `sim_slot` now returns `422 invalid_sim_slot` instead of silently using the default SIM.
- **Accurate segment estimates**: GSM-7 extension characters (EUR, `[`, `]`, `{`, `}`, `\\`, `^`, `~`, `|`) cost 2 septets, emoji cost 2 UTF-16 units, characters are never split across segments; the backtick is correctly treated as non-GSM.
- **Simulation is opt-in**: outside Android nothing is "sent" unless `OPENSMS_ALLOW_SIMULATION=1`, and such messages carry `provider: simulated`.
- Database schema v2 (additive): `message_parts` table, `messages.provider`, `messages.parts_expected`.
- **Device testing required**: the Android receipt code (`app/java_src`, `smsReceipts.py`) is built via `android.add_src` and is verified only by unit tests against a mock provider and a stub compile. See `docs/device-test-plan.md`.

#### API Architecture & Security
- **Idempotency**: send `Idempotency-Key: <1-128 chars>` on `POST /sms/` and `POST /sms/batch/`. A retry with the same key returns the original response (header `Idempotent-Replay: true`) and never sends another SMS or uses rate-limit quota. Same key + different body -> `422 idempotency_key_reuse`; still running -> `409 request_in_progress`; a failed send releases the key so it can be retried. Keys are per API key and kept 24 h. Requests without the header behave exactly as before.
- **Unified error envelope** (additive): every error keeps the legacy `detail` field and adds `error: {code, message}` (e.g. `unauthorized`, `insufficient_scope`, `validation_error`, `send_rate_limited`, `not_found`).
- **Pagination**: `GET /sms/history` now returns `total` and `has_more` (and a stable sort order).
- **Schema migrations**: database versioned with `PRAGMA user_version` (now v1, adds the `idempotency` table; existing tables/rows untouched). A database written by a newer app version is refused rather than modified.
- **Scopes are now enforced** (`sms:write` send, `sms:read` history/stats/update, `admin` keys/control). Keys created by the app carry `sms:write`+`sms:read`, so existing clients are unaffected.
- **Key lifecycle**: SQLite is the single source of truth. Legacy `keys.json` is imported once and renamed to `keys.json.migrated` (previously a revoked key kept working through it). New admin-only endpoints: `GET/POST /keys/`, `DELETE /keys/{id}`. Generating a key does **not** revoke others; the dialog text now says so.
- **Rate limiting**: failed-auth lockout uses the socket address only (`X-Forwarded-For` is ignored); new per-key send limit (`OPENSMS_SEND_RATE_PER_MIN`, default 300, `0` disables) returning `429` + `Retry-After`.
- **Honest delivery reporting**: `sent` means handed to Android's telephony layer; `delivered_at` is only set for a real `delivered` status. Send responses add `delivery_confirmed: false`; the message text no longer says "sent successfully".
- `/docs`, `/openapi.json`, `/llms.txt`, `/docs/markdown` require auth unless `OPENSMS_PUBLIC_DOCS=1`.
- `GET /sms/history` works with or without trailing slash; SMS text limited to 1600 chars; search treats `%`/`_` literally; "sent today" uses local midnight.
- SQLite connections are always closed; nothing is created at import time; phone numbers are masked in logs; one log-writer thread.
- Tailscale credentials are no longer stored or shown (older stored keys are scrubbed on start); API keys are no longer auto-copied to the clipboard; Android auto-backup disabled; `requests` added to requirements.

#### CI, Build & Release Pipelines
- CI lints the workflows with actionlint + shellcheck; fixed two glob-quoting issues in the build/release scripts.
- **Release pipeline**: new `ci.yml` (ruff, tests on Python 3.11/3.12 with pinned deps, `pip-audit`, headless UI smoke test). `release.yml` now requires a validated `vX.Y.Z` tag equal to `app/app_version.py`, **signs** the APK from repository secrets (fails instead of publishing a debug-signed release; a manual opt-in publishes a debug-signed *pre*-release), publishes `.sha256` files, and no longer interpolates workflow inputs into shell. python-for-android and KivyMD are pinned by commit.
- **Pinned, audited dependencies**: `fastapi 0.162.0`, `starlette 1.9.0` (fixes known advisories in the previous `0.48`), `uvicorn 0.34.3`, `pydantic 2.12.3` (matches the local pydantic-core recipe), etc. in `requirements-core.txt`, `constraints.txt` and `buildozer.spec` (a test keeps them in sync). `requests` is now declared.
- Single version source `app/app_version.py`; removed the unused `services/postFlask.py`; `docs/openapi.json` is generated from the app (`tools/gen_openapi.py`) and a test fails if it is stale; corrected stale documentation claims; added `docs/security.md`, `docs/deployment.md`, troubleshooting table and `.env.example`.



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
