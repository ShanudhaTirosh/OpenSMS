# OpenSMS — Audit & Implementation Plan

| | |
|---|---|
| **Repository audited** | `OpenSMS-main.zip` (app version `0.4.0`, ~4,900 lines of Python/KV plus CI, docs, tests) |
| **Plan status** | Stages 1–5, 7 and 8 are complete **as far as they can be without a phone, your signing key and a CI run**; Stage 6 is **partly** complete. **Nothing has been built into an APK or run on a device.** See *Resolution status*, *Stage 7–8* and *Open decisions* at the end. See *Progress log* at the end. |
| **Evidence** | `audit/verify_defects.py`, `audit/verify_defects_output.txt`, `audit/baseline_pytest.txt` |
| **Next step** | Review §H (decisions needed). Stage 2 can start as soon as you approve it. |

> **Important discovery.** Your brief allows for a web app, desktop app, or server backend. The repository is none of those. **OpenSMS is a single Android application** (Kivy + KivyMD UI) that runs an HTTP API **on the phone itself** and sends SMS through Android's `SmsManager`. There is no separate backend server, no web frontend, and no multi-user account system. The plan below is built around that reality. Three of your brief's assumptions change as a result (Tailscale architecture, "frontend redesign", "roles/permissions"); each is called out where it matters.

**What I could and could not verify in this sandbox**

| Verified here (Linux, Python 3.12) | Not verifiable here (needs a device/tailnet) |
|---|---|
| FastAPI endpoints, auth, validation, SQLite layer, rate limiter, segmentation logic, existing pytest suite | `SmsManager` calls through pyjnius, real SMS delivery, SIM routing |
| Static analysis of every Android/Kivy file | APK build (needs Android SDK/NDK; not available), Kivy UI rendering, foreground-service lifetime |
| | Tailscale connectivity, VPN interaction, in-app updater/installer |

Every issue below is labelled **Verified** (reproduced by running code), **Verified (code read)** (the code unambiguously does this, but it cannot execute here), or **Suspected** (needs a device test). Nothing marked Suspected should be treated as a confirmed defect.

---

## A. Current System Overview

### A.1 Stack

| Layer | Technology (from the source) |
|---|---|
| UI | Kivy 2.3.1 + KivyMD `master.zip` (2.0.1.dev0, **unpinned**), Material 3 |
| API | FastAPI (`>=0.110,<0.120` in `requirements.txt`, **unpinned** in `buildozer.spec`) + Uvicorn, Pydantic 2.12.3 |
| Telephony | `android.telephony.SmsManager` via PyJNIus |
| Storage | SQLite (WAL) `config/opensms.db`; JSON files `config.json`, `keys.json` (legacy), `request.json`, `resp.json`; text log `logs/api_logs.log` |
| Build | Buildozer → python-for-android fork `daslearning-org/p4a-unofficial` branch `develop` (cloned at build time), minapi 24, target 36, `armeabi-v7a` + `arm64-v8a` |
| CI | GitHub Actions: `build-apk.yml`, `release.yml` (both build a **debug** APK) |
| Tests | 29 pytest tests in `tests/test_api_and_services.py` (pure-Python paths only) |

### A.2 Architecture

```
┌─────────────── Android device ───────────────────────────────────────────┐
│  UI process (main.py, Kivy)            Foreground service process         │
│  ├ screens: SMS(home) / Mesh /         (services/appSvc.py)               │
│  │          Settings / Logs            ├ polls request.json every 0.2 s   │
│  ├ writes request.json  ───────files──►│ ├ starts/stops uvicorn thread    │
│  ├ polls resp.json every 1.5 s ◄──files┤ └ writes resp.json               │
│  └ reads SQLite for metrics            └ FastAPI app (services/postApi.py)│
│                                           ├ auth (SQLite keys + keys.json)│
│                                           ├ send_sms() → SmsManager       │
│                                           └ SQLite messages table         │
│  Tailscale: NOT embedded. TailscaleService only inspects network          │
│  interfaces for a 100.64.0.0/10 address and stores user-typed values.     │
└───────────────────────────────────────────────────────────────────────────┘
   API binds 0.0.0.0:<port> (default 9292), plain HTTP, Bearer-token auth.
```

### A.3 Feature inventory (what actually exists)

| Area | Present | Absent |
|---|---|---|
| REST API | `POST /sms/`, `POST /sms/batch/` (≤100), `GET /sms/{id}`, `GET /sms/history/`, `GET /system/stats/`, `/system/sims/`, `/system/update/`, `/health/`, `/llms.txt`, `/docs/markdown`, `POST /control/` (no-op) | Inbound SMS, delivery callbacks, webhooks (table exists, unused), key-management endpoints, idempotency, queue |
| Auth | Bearer keys (SHA-256 hashed, `osms_…`), per-IP failed-auth lockout (10/60 s) | Scope enforcement, key list/revoke UI or API, send-rate limits |
| UI screens | Home (start/stop, metrics, endpoint, update banner), Mesh (Tailscale), Settings, Logs | Message history/detail, API-key management, system/diagnostics screen |
| Tailscale | Interface detection; "in-app key" connect; client code generator | Any real tunnel, enrollment, or peer reachability (see TS-01) |
| Ops | In-app updater from GitHub Releases, log rotation (2 MB) | Release signing, health/readiness split, structured logs |

### A.4 SMS send workflow (traced end to end)

1. Client → `POST /sms/` → `verify_api_key` (`postApi.py:225-289`) → Pydantic `SmsData` validation (phone regex + 7–17 digits; **no text-length cap**).
2. Handler inserts a row with status `sending` (never `queued`), then calls **blocking** `send_sms()` inside an `async def` handler.
3. `send_sms` (`smsApi.py`) sanitises the number and calls `SmsManager.sendTextMessage / sendMultipartTextMessage(..., None, None)` — **sent and delivery PendingIntents are `None`**. Success therefore means only "the call did not throw".
4. Handler marks the row `sent`, stamps `delivered_at`, and replies `{"stat": true, "message": "SMS sent successfully…"}`.
5. Nothing ever moves a row to `delivered`, and a radio/carrier failure after hand-off is never observed.
6. On non-Android platforms `send_sms` prints a "simulation" line and returns `True`.

### A.5 Tailscale workflow (traced)

`tailscaleScr.connect_key` → `TailscaleService.connect_tailscale_key`:
- **100.x.y.z typed** → marks `connected=True` with no check at all (`tailscaleSvc.py:116-133`).
- **`tskey-auth-…`** → stores the key, no enrollment (`:212-229`).
- **API token** (also any ≥30-char string that does not start with `tskey-auth-`, `:136`) → `GET api.tailscale.com/api/v2/tailnet/-/devices`, picks one device's IP, marks `connected=True` (`:135-209`).
- All three persist the value to `config.json` in plaintext (`main.save_tailscale_config`, `:1047`).
- Real connectivity exists only if the user separately installs and runs the official Tailscale Android app; OpenSMS then sees its `100.x` interface address (`get_network_interfaces_info`). **Whether `NetworkInterface` enumeration still lists the VPN interface on Android 11+ is Suspected and needs a device test.**

---

## B. Issue Register

Severity reflects impact on a real deployment (an always-on phone that can send billable SMS and is reachable over a network).

### B.1 Security and access control

| ID | Sev | Status | Where | Root cause & evidence | Impact | Proposed fix | Regression risk |
|---|---|---|---|---|---|---|---|
| **SEC-01** | High | Verified (V3) | `postApi.py` all endpoints; `dbMgr.api_keys.scopes` | `verify_api_key` returns the key record but **no endpoint checks scopes**. A key created with only `sms:read` successfully sent an SMS. | Documented "granular scopes" are not real; a leaked read-only key can send billable SMS. | Add `require_scope()` dependency; `sms:write`→send, `sms:read`→read, `admin`→key mgmt/system. Default both scopes for existing keys (all app-generated keys already carry both). | Low for app-generated keys; keys with custom scopes (none created by the app) would be restricted. |
| **SEC-02** | High | Verified (V1, V2) | `generate_new_api_key` (`:70-97`), `get_api_keys` (`:99-109`), `verify_api_key` fallback (`:269-273`), `main.check_if_key_exists` | (a) The UI dialog says generating a key "will immediately invalidate existing keys" — false: V1 shows the old key still works. (b) Revoking in SQLite does not remove the hash from `keys.json`; the legacy fallback still accepts it (V2). (c) `check_if_key_exists` reads only `keys.json`. (d) There is no UI or API to list/revoke keys at all. | A key the owner believes is dead keeps working. | One source of truth (SQLite); one-time import of `keys.json`, then delete the file; add key list/revoke/rotate in UI and `admin`-scoped API; fix dialog text to match behaviour **(see D3)**. | Medium — touches the auth path; covered by new tests. |
| **SEC-03** | High | Verified (V7) | `verify_api_key` (`:229-232`) | Client IP is taken from `X-Forwarded-For`, which is attacker-controlled (no proxy exists). 25 bad attempts with rotating header values never hit 429; conversely 11 spoofed attempts locked out an arbitrary victim IP. | Brute-force protection is bypassable; targeted lock-out of a legitimate client. | Use `request.client.host` only; add per-key and global limiters. | Low. |
| **SEC-04** | High | Verified (code read) | `tailscaleSvc.py:184`; `tailscaleScr.py:334-337`; `main.save_tailscale_config` | Tailscale API/auth key is saved in plaintext in `config.json` and **echoed back into the visible text field** on every screen refresh. | Reusable tailnet-management credential exposed on screen, in screenshots, backups, and to anyone with file access. | Stop persisting credentials; never pre-fill; if an API credential is ever needed, hold it in memory only (or Android Keystore) with narrow scope — see §E. | Low. |
| **SEC-05** | Medium | Verified (config read) | `buildozer.spec:332` `android.allow_backup = True` | Auto-backup includes `config.json` (token above) and `opensms.db` (full SMS bodies + recipients). | Message content and secrets leave the device via cloud backup/adb backup. | `allow_backup = False` or explicit `backup_rules` excluding `config/` and `*.db`. | Low (users lose restore-on-new-phone of settings). |
| **SEC-06** | Medium | Verified (code read) | `main.create_new_api_key` (`:494-498`), `tailscaleScr.update_tailscale_info(:353)` | Key is auto-copied to the clipboard; the dialog then says it "will not be displayed again". The real key is also passed into `cached_snippets` / `snippet_code` and never cleared, contradicting the "SEC-01: wipe API key" comment at `close_key_dialog`. | Key lingers in clipboard and UI state. | Copy only on explicit tap; clear snippet cache on dismiss; snippets always use a placeholder. | Low. |
| **SEC-07** | High | Verified (code read) | `process_sms_req`, `process_batch_sms_req` | No rate limit/quota on **authenticated** sending. Only failed auth is limited. | A leaked or buggy client can send unlimited billable SMS. | Per-key sliding-window limit + daily quota, configurable; 429 with `Retry-After`. | Low–Medium (defaults must not break existing clients; set generous). |
| **SEC-08** | Medium | Verified (V8) | `postApi.py` (`/docs`, `/openapi.json`, `/llms.txt`, `/docs/markdown`) | Unauthenticated API surface disclosure. | Information leak on any reachable network. | Disable FastAPI auto docs by default; serve docs only with auth or via a setting. | Low (docs site remains on GitHub). |
| **SEC-09** | Medium | Verified (code read) | `uvicorn.Config(host="0.0.0.0")`, no TLS | Bearer token sent in clear text over Wi-Fi/LAN. Over Tailscale it is WireGuard-encrypted, but nothing lets the owner restrict the listener to the tailnet. | Token sniffing on shared networks. | Add a **bind mode** setting: `all` (current default, unchanged) / `tailscale-only` / `localhost`. Needs your approval (networking change, **D5**). | Medium — wrong mode can lock the owner out; keep `all` as default. |
| **SEC-10** | Medium | Verified (code read) | `log_activities`, `postApi` | Recipient phone numbers are written to the plain-text log; log is copyable from the UI. One thread is spawned per log line. | PII in logs; thread storm under load. | Mask numbers (`+94•••••567`), single log worker/queue. | Low. |
| **SEC-11** | Low | Verified (code read) | `release.yml` | `${{ github.event.inputs.tag_name }}` interpolated into a shell step. | Workflow injection by anyone with dispatch rights. | Pass via `env:` and validate against `^v\d+\.\d+\.\d+$`. | Low. |

### B.2 API and SMS correctness

| ID | Sev | Status | Where | Root cause & evidence | Impact | Fix | Risk |
|---|---|---|---|---|---|---|---|
| **SMS-01** | High | Verified (V5, V6) + code read | `smsApi.send_sms`; `dbMgr.update_message_status` (`:127`); `postApi` responses; `docs/api-reference.md` | No sent/delivery `PendingIntent`s. `sent` stamps `delivered_at`. Response says "SMS sent successfully". Docs advertise a "delivery lifecycle". Your brief forbids reporting delivery without authoritative confirmation. | Clients trust a delivery that was never confirmed; radio-level failures are invisible. | New status model: `accepted → submitted → sent → delivered` / `failed`. Register `PendingIntent` receivers (python-for-android `BroadcastReceiver`) in the service process for sent and delivery reports, per message part. `delivered_at` only on a real status report. Keep `stat` and `id` fields for compatibility; add `status`. **Carrier limitation:** many carriers/SIMs never return delivery reports; those messages stay `sent` and the docs must say so. Needs device testing. | Medium (API semantics, **D2**). |
| **SMS-02** | Medium | Verified (code read) | `send_sms` non-Android branch | Desktop/dev run returns `True` for every message. | Dev/CI can report success that never happened. | Return a distinct `simulated` flag/status; refuse unless `OPENSMS_ALLOW_SIMULATION=1`. | Low. |
| **SMS-03** | Medium | Verified (code read) | `smsApi.get_sms_manager` | Invalid or inactive `sim_slot` silently falls back to the default SIM. | Message leaves via the wrong SIM/carrier plan. | Validate against `get_active_sims()`; return 422 on unknown slot. | Low. |
| **SMS-04** | Low | Verified (V11) | `calculate_sms_segments` | GSM-7 extension characters (`€ [ ] { } \ ^ ~ \|`) are treated as Unicode or count as one septet; emoji counted as 1 char instead of 2 UTF-16 units; `\x1b` listed as a basic character. | Wrong segment/encoding estimates in UI and API responses. | Implement GSM-7 basic + extension tables and UTF-16 length. | Low. |
| **SMS-05** | Low | Verified (V16) | `SmsData.text` | No maximum length (200 KB accepted), no request-body cap. | Memory/DoS; guaranteed carrier failure. | Cap text (e.g. 1,600 chars ≈ 10 segments, configurable) and body size. | Low. |
| **SMS-06** | — | Capability gap | whole project | **Receiving SMS is not implemented** (no `RECEIVE_SMS`/`READ_SMS` permission, no receiver) and webhooks are an unused table. | Your brief's "receiving messages and delivery callbacks" cannot be "verified" — it does not exist. | Optional new feature; requires new permissions and has Play-policy implications **(D4)**. Delivery *callbacks to clients* would use the existing `webhooks` table. | n/a |
| **API-01** | Medium | Verified (V4) | route order `/sms/{msg_id}` vs `/sms/history/` | `GET /sms/history` (no slash) is captured by `/sms/{msg_id}` → 404 "Message ID 'history' not found". | Confusing 404 for a documented endpoint. | Declare `/sms/history` before `/sms/{msg_id}` and accept both forms. | Low. |
| **API-02** | Medium | Verified (V10) | `process_sms_req` | No idempotency: two identical POSTs created two messages. | Client retries after a timeout double-send SMS. | `Idempotency-Key` header persisted with a unique index; replay returns the original result. | Low. |
| **API-03** | Medium | Verified (code read); impact Suspected | `process_*_req` | Blocking `send_sms` + sync SQLite inside `async def` handlers; batch of 100 holds the connection ≥10 s and stalls the event loop. No queue exists (`queued` is never used; metric `queue_depth` is effectively always 0). | Slow/unresponsive API under load; client timeouts → duplicate sends (API-02). | Persistent send queue + single worker thread; `POST` returns `202` with `status=accepted` immediately; startup recovery of `sending` rows. | Medium (response timing changes; keep sync-compatible `stat`). |
| **API-04** | Low | Verified (V9) | `POST /control/` | Authenticated no-op that echoes input. | Dead/misleading endpoint. | Remove after confirming no client uses it **(D6)**. | Low |
| **API-05** | Low | Verified (V12) | `dbMgr.get_messages` | `LIKE` wildcards (`%`, `_`) in `search` are not escaped; history has no `total`; error shape differs by path (`{"total":0,…}` vs `{"count":…}`). | Surprising search results; hard to paginate. | Escape wildcards, add `total`, unify response/error envelope `{error:{code,message}}` (additive: keep `detail`). | Low. |

### B.3 Data layer

| ID | Sev | Status | Where | Root cause & evidence | Fix |
|---|---|---|---|---|---|
| **DB-01** | Medium | Verified (V13) | `dbMgr._get_connection` | `with sqlite3.connect()` commits but **does not close**. File descriptors grew by 3,971 per 2,000 calls with GC off, and 83 with GC on. Each call also re-runs three PRAGMAs. | Context manager that closes; one connection per thread (`threading.local`) or a small pool. Android FD limits make this matter under sustained load. |
| **DB-02** | Medium | Verified (V15) | `postApi.py:31-32` | Import-time side effect: `DatabaseManager.get_instance("./config")` creates `./config/opensms.db` in the **current working directory** before `set_config_path` runs. Two DB files can exist. | Lazy initialisation; no work at import. |
| **DB-03** | Low | Verified (V14) | `get_metrics` | "Today" is UTC midnight (`now - now % 86400`), not local midnight. | Compute local day start; store/return ISO-8601 with offset. |
| **DB-04** | Low | Verified (code read) | `dbMgr._init_db` | No schema version/migration mechanism; `webhooks` table unused; message bodies retained forever. | `PRAGMA user_version` migrations; retention setting (default off, explicit); drop or use `webhooks`. |

### B.4 Tailscale

| ID | Sev | Status | Where | Root cause & evidence | Fix |
|---|---|---|---|---|---|
| **TS-01** | **Critical** (for this feature) | Verified (code read) | `tailscaleSvc.connect_tailscale_key`, `tailscaleScr` copy | The "connection" is cosmetic. Typing any `100.64–127.x.y` address reports **Connected**; an auth key is stored but never used to join a tailnet; an API token only lists devices. None creates a data path. The UI then states "Worldwide cross-network SMS dispatch active via Tailscale WireGuard mesh" (`tailscaleScr.py:149`). Existing test `test_tailscale_direct_ip_connection` asserts this behaviour. This is exactly the "fake integration" your brief prohibits. | Replace with an honest design (§E). Remove fake connect modes; status derives from observed state only. |
| **TS-02** | Medium | Verified (code read) | `tailscaleSvc.py:136` | Heuristic sends any ≥30-char string not starting `tskey-auth-` to `api.tailscale.com` as a Bearer token. | Strict prefix validation; no credential entry in the default design. |
| **TS-03** | Low | Verified (code read) | `tailscaleScr.py:238-264` | Snippet generator creates PHP code but there is no PHP chip; README advertises PHP. Snippet inputs are interpolated unescaped. | Add chip; escape values. |
| **TS-04** | Medium | Suspected | `pathMgr.get_network_interfaces_info` | Android 11+ restricts some network enumeration; the VPN interface may not be listed, making status a false negative. Third-party Tailscale embeds document similar netlink restrictions. | Device test; fallback: connect-probe to the device's own `100.x` address or read `ConnectivityManager` VPN transport. |

### B.5 Updater, build, CI, dependencies

| ID | Sev | Status | Where | Root cause & evidence | Fix |
|---|---|---|---|---|---|
| **UPD-01** | High | Suspected (strong) | `updateMgr.install_apk`; `buildozer.spec` | Code asks for `<pkg>.fileprovider` but **no `FileProvider` is declared anywhere** (grep: zero matches in manifest/spec) and `androidx` dependency is not requested. The fallback `Uri.fromFile()` throws `FileUriExposedException` on API ≥ 24 (all supported devices). | Device test first; then declare provider via `android.add_resources`/manifest extras + `file_paths.xml`. |
| **UPD-02** | High | Suspected (strong, from CI config) | `release.yml` | Releases publish `buildozer android debug` APKs. CI caches `~/.buildozer` and `~/.gradle` but not `~/.android`, so the debug keystore is likely regenerated on each runner. Android refuses to update an app signed with a different key. | Compare certificates of two published releases with `apksigner verify --print-certs`. Fix: dedicated release keystore stored as a GitHub secret (needs you, **D7**) and `buildozer android release`. |
| **UPD-03** | Low | Verified (code read) | `UpdateManager.download_apk` | No checksum/host allow-list before launching the installer (Android's signature check is the backstop). | Verify SHA-256 published in the release; restrict to `github.com`/`githubusercontent.com`. |
| **BLD-01** | High | Verified | `app/requirements.txt`, `req_android.txt` | `requests` is imported by `updateMgr`/`tailscaleSvc` but listed in neither file. A clean venv fails test collection (`ModuleNotFoundError`). | Add `requests`. |
| **BLD-02** | Medium | Verified (code read) | `buildozer.spec`, `req_android.txt` | KivyMD from a moving `master.zip`; p4a fork cloned from branch `develop` at build time; `fastapi` unpinned in the spec but ranged elsewhere; `pydantic==2.12.3` coupled to a local `pydantic-core` recipe pinned 2.41.4; a stale comment mentions `fastapi==0.143.0`. `pytest.ini` uses `asyncio_default_fixture_loop_scope` without `pytest-asyncio`. | Pin commits/tags, add a lock file, align versions in one place. |

### B.6 Architecture and quality

| ID | Sev | Status | Where | Finding | Fix |
|---|---|---|---|---|---|
| **ARCH-01** | Medium | Verified (code read) | `appSvc.app_service_thread`, `main.resp_check_loop` | UI↔service IPC is two JSON files polled forever (0.2 s service side ≈ 5 file reads/s while idle) — battery and flash wear. Concurrent writers share one `.tmp` name in `pathMgr.atomic_write_json` (race when several `Thread(target=write_app_conf)` overlap). | Poll `mtime` first and back off; unique temp names + a write lock. Longer term: Android broadcast/bound service (needs device testing). |
| **ARCH-02** | Medium | Suspected | `main.OpenSmsApp.on_stop` (`:1255`) | `on_stop` calls `stop_service()`, so closing the activity may stop the "always-on" gateway, contradicting the foreground-service design. | Device test; decide intended lifetime (**D8**). |
| **ARCH-03** | Low | Verified | repo | Dead/duplicate code: `services/postFlask.py` (Flask variant, imported nowhere, `flask` not in any requirements), identical `p4a_local_recipes/pydantic-core` and `pydantic_core`, unused `webhooks` table, `/control/`. Version string hard-coded in six places (`main.py`, `postApi.py` ×4, `settings.py` KV). | Single `__version__` source; remove after your confirmation (**D6**). |
| **ARCH-04** | Low | Verified (code read) | `main.py` | 1,272-line `OpenSmsApp` mixes UI, config, service control, updater and Tailscale glue. | Extract only what the redesign touches (config store, service controller); no wholesale rewrite. |
| **TEST-01** | Medium | Verified | `tests/` | Tests cover pure-Python paths only; none for scopes/revocation/idempotency/receipts; one test enshrines TS-01; no lint, type check, or security scan in CI; nothing exercises Android code. | See §G. |
| **UX-01** | Medium | Verified (code read) | UI | No message history/detail screen (API has it), no API-key management, no diagnostics screen, test-SMS bypasses the message table. "Reset" does not reset `auto_update`/`sim_slot`. No accessibility labelling reviewed (**Suspected** gaps; KivyMD limits apply). | See §F. |

---

## C. File-by-File Change Plan

Paths are relative to the repository root. "Test" is how each change will be verified.

### C.1 Files to modify

| File | Today | Change | Depends on | Test |
|---|---|---|---|---|
| `app/requirements.txt`, `app/req_android.txt` | Missing `requests`; loose pins | Add `requests`, pin FastAPI/Uvicorn/Pydantic/Starlette, pin KivyMD to a commit | `buildozer.spec` | Clean-venv install + pytest |
| `app/buildozer.spec` | Debug-only, `allow_backup=True`, unpinned reqs, no FileProvider, p4a `develop` | Backup off/rules, aligned pins, FileProvider resources, pinned p4a ref, `release` build option | UPD-01/02 decisions | Cannot build here → CI build + device install |
| `app/services/postApi.py` | Endpoints, auth, rate limit, key helpers, server class in one file | Keep file as the FastAPI composition root; move logic out (see C.2); `require_scope`; ignore `X-Forwarded-For`; route order; idempotency; 202 flow; lazy DB init; remove import side effects; unified errors; docs gating | new services | Extended pytest suite |
| `app/services/dbMgr.py` | Per-call unclosed connections, UTC "today", no migrations | Closing connection handling, `user_version` migrations, new columns (`status`, `provider_state`, `idempotency_key`, per-part receipts), wildcard escaping, key-management methods | none | Unit + migration tests on a v0.4.0 DB copy |
| `app/services/smsApi.py` | Fire-and-forget send, approximate segment calc | `PendingIntent` sent/delivery receipts, SIM validation, accurate GSM-7/UTF-16 segmentation, simulated-send flag | `smsReceipts.py` | Unit (segments, validation); device (receipts) |
| `app/services/tailscaleSvc.py` | Fake connect modes | Becomes a read-only status provider (§E); remove credential handling and `connect_tailscale_key` | — | Unit with mocked interface lists; device |
| `app/services/pathMgr.py` | Atomic writes with shared temp name; interface scan | Unique temp files + lock; `is_tailscale_ip` also covers `fd7a:115c:a1e0::/48` | — | Unit |
| `app/services/appSvc.py` | 0.2 s file polling loop | `mtime`-gated polling with back-off | ARCH-01 | Unit + device soak |
| `app/services/logSvc.py` | Thread per entry, PII | Queue worker, number masking, redaction filter | — | Unit |
| `app/services/updateMgr.py` | No verification | Host allow-list + checksum, clearer errors | UPD decisions | Unit with mocked HTTP |
| `app/main.py` | God class, Tailscale key persistence, key dialog | Navigation shell for new screens; remove key echo/auto-clipboard; keys UI wiring; version single-source | New screens | Device UI run |
| `app/main_layout.kv` | 4 screens | New destinations (§F) | `screens/*` | Device UI run |
| `app/screens/tailscaleScr.py` | Credential form, misleading copy | Status/diagnostics/launch screen (§E) | `tailscaleSvc` | Device |
| `app/screens/settings.py`, `mainScr.py`, `logs.py` | Current UI | Re-skin into shared components; fix "Reset" gaps; bind-mode setting | components | Device |
| `.github/workflows/*.yml` | Debug releases, injection, no lint | Release signing, tag validation, `ruff`, `pytest`, `pip-audit`, cache `~/.android` | D7 | CI run |
| `tests/test_api_and_services.py` | Enshrines TS-01 | Update the Tailscale tests; split by area | — | `pytest` |
| `README.md`, `docs/*`, `llms*.txt`, `docs/openapi.json` | Claims scopes `sms:send`, "delivery lifecycle", PHP chip | Align with real behaviour; document limitations | all | Doc review |
| `CHANGELOG.md`, `pytest.ini` | — | Entries; remove unsupported option | — | `pytest` |

### C.2 New files (and why)

| File | Why |
|---|---|
| `app/services/authSvc.py` | Key lifecycle, scopes, rate limiting in one testable place; removes duplication between `postApi` and `main`. |
| `app/services/messageSvc.py` | Queue, worker thread, status state machine, idempotency; keeps handlers thin. |
| `app/services/smsReceipts.py` | Sent/delivery `BroadcastReceiver` plumbing (Android only; no-op elsewhere). |
| `app/services/settingsStore.py` | One owner for `config.json` (single writer), replaces scattered `write_app_conf` threads. |
| `app/screens/components.py` | Reusable cards, status chips, empty/skeleton/error states, confirm dialog. |
| `app/screens/messages.py`, `apiKeys.py`, `gateway.py`, `system.py` | Screens listed in §F. |
| `tests/conftest.py`, `tests/test_auth_scopes.py`, `test_message_lifecycle.py`, `test_idempotency.py`, `test_tailscale_status.py`, `test_migrations.py` | Cover every fix above. |
| `docs/tailscale.md`, `docs/security.md`, `docs/deployment.md`, `docs/testing.md`, `docs/device-test-plan.md` | Requested documentation; device test plan is what you run on hardware. |
| `.env.example` | Placeholders only. **Note:** the Android app has no environment variables today; this file would apply only to desktop/dev mode and CI (`OPENSMS_DATA_DIR`, `OPENSMS_ALLOW_SIMULATION`, …). |

### C.3 Removal candidates (nothing is deleted without your confirmation)

| File | Evidence it is unused |
|---|---|
| `app/services/postFlask.py` | `grep` finds no import; `flask` is in no requirements file |
| `app/p4a_local_recipes/pydantic_core/` | Byte-identical to `pydantic-core/` (`diff` clean); keep whichever name Buildozer resolves — needs a build to confirm which |
| `webhooks` table / `/control/` | Only referenced by their own definition |

---

## D. Implementation Roadmap

| # | Stage | Contents | Acceptance criteria | Status |
|---|---|---|---|---|
| 1 | **Audit & baseline** | Full read, defect reproduction, baseline tests | This document + `audit/` evidence; 29/29 baseline tests pass once `requests` is installed | **Complete** |
| 2 | **Critical fixes & security** | BLD-01, SEC-01/02/03/04/05/06/07/08/10, API-01, DB-01/02/03, API-05, SMS-05 | New tests prove: scope enforcement, revoked key rejected everywhere, spoofed `X-Forwarded-For` ignored, no secret persisted/echoed, no import-time files, FD count stable; existing client requests still return 200 | **Complete on the Python side (42/42 tests).** Android/UI changes in `main.py`, `tailscaleScr.py`, `buildozer.spec` compile but are **not device-tested**. Deferred: SEC-09, SEC-11 |
| 3 | **API/architecture** | unified errors, pagination totals, idempotency, schema migrations (`authSvc` extracted in Stage 2) | Migration test from a v0.4.0-schema DB; idempotent replay test; additive changes only | **Complete (60/60 tests).** `messageSvc` extraction folded into Stage 4 where the queue is built; `docs/openapi.json` not regenerated yet (it is generated from the running app, see below) |
| 4 | **SMS reliability** | Queue + worker, status model, sent/delivery receipts, SIM validation, accurate segmentation, per-key limits (Stage 2) | Mock-provider tests for every transition; **device test matrix** (own SIM, own recipient): submitted→sent→delivered/failed, airplane-mode failure, dual-SIM routing | **Python side complete (103/103 tests, mutation-checked).** Device matrix in `docs/device-test-plan.md` **not run** |
| 5 | **Tailscale** | Honest status/diagnostics, bind mode, launch/install flow, docs; spike for embedded option if approved | Status matches reality on a device in all four states; no credential persisted; setup guide verified by a fresh install | **Done except device verification** (option A; 130/130 tests, screen rendered headlessly). Embedded `tsnet` spike **not done** (needs your decision D1) |
| 6 | **UI/UX redesign** | Shell + 6 screens + components (§F) | Every control works; keyboard/back navigation; light/dark; phone + tablet screenshots; empty/error/loading states | **Mostly done**: Messages (incl. in-app send with review step), API, Mesh + shared components; Overview/Gateway/System/Settings/Logs not redesigned; no tablet layout |
| 7 | **Testing/regression** | Test suite expansion, CI lint/type/security scans | CI green; coverage report for `services/`; regression checklist run | **Done locally** (198 passed + 1 skipped, 199 with Kivy installed; ruff clean, `pip-audit` clean, mutation-checked); **CI never run**; no type checker, no coverage report |
| 8 | **Deploy/docs/final verification** | Signed release pipeline, docs, rollback notes | Release APK installs **over** the previous release (signature continuity); documented rollback | **Docs and pipeline written; not verified**: needs your keystore secrets, a CI run and an install-over-install test on a phone |

Stages 2–3 are non-UI and fully testable here. Stages 4–6 and 8 need hardware or a signing key from you.

---

## E. Tailscale Architecture Decision

**Fact that drives the design:** the application "host" is an Android phone that already runs the API. Tailscale's Android client works as the device's VPN service, and Android allows only one active VPN at a time. A Tailscale API key manages the tailnet; it does not create a tunnel.

| Option | What it means here | Verdict |
|---|---|---|
| **A. Official Tailscale app on the phone as the data path** (recommended) | User runs Tailscale normally. OpenSMS (1) detects the tailnet address honestly, (2) launches/installs the Tailscale app via the existing `com.tailscale.ipn` intent, (3) offers **bind mode "Tailscale only"** so the API is unreachable from Wi-Fi/LAN, (4) shows diagnostics and a troubleshooting list. No VPN of its own → no full-device routing or DNS change. | Reliable, supported, small, no new native code. Limitation: cannot enrol the device or toggle the tunnel itself; the user does that in the Tailscale app. |
| **B. Tailscale API from the app** | Read-only device/peer list using a credential. | Only with a short-lived, narrowly scoped credential kept in memory. Storing a reusable key on a phone is the exposure in SEC-04. Offer as an optional "peer view" after Stage 5 core, not as the connection mechanism. |
| **C. Embedded userspace Tailscale (`tsnet`/`libtailscale`)** | OpenSMS would join the tailnet itself, without the Tailscale app, and expose only its own port. | Technically possible in principle (Tailscale publishes `libtailscale`, a C library for embedding in userspace), but **not proven for this stack**: it needs a Go + NDK cross-build inside python-for-android, adds roughly 20 MB per architecture according to community wrappers, and those wrappers document Android caveats (restricted network enumeration since Android 11, tunnel support described as work in progress in one of them, another targeting only API 35+ while this app supports API 24). I could not verify upstream's Android support from here. Treat as a **time-boxed spike** only if you need "no Tailscale app on the phone". |

**Recommendation:** Stage 5 delivers **A** (+ optional **B** read-only). **C** is a separate, explicitly approved spike (**D1**). Whatever is chosen, the UI will show only controls that act (open Tailscale, copy endpoint, change bind mode, run diagnostics) and distinguish three separate facts: *local Tailscale interface present*, *OpenSMS reachable on that address (self-probe)*, and *peers online (only if option B is enabled)*. Connected / disconnected / error states derive from those observations, never from typed input.

---

## F. UI/UX Redesign Scope (adapted to a Kivy/KivyMD Android app)

Your suggested structure assumes a web dashboard and multi-user roles. The product is single-owner and mobile, so the plan adapts it:

| Destination | Contents | Notes |
|---|---|---|
| **Overview** | Gateway state, sent/failed today (local-day), queue depth, last 5 messages, Tailscale one-liner, update banner | Replaces current Home |
| **Messages** | Paginated history, search, status filter chips, detail sheet (status timeline, error, SIM, parts), send form with validation + confirm | New; uses existing `/sms/history` logic directly from the DB |
| **API** | Key list, create (shown once), revoke, rotate, scopes, last-used, per-key limits, copyable placeholder snippets | Replaces key dialog |
| **Gateway** | Port, bind mode, SIM selection, permission checklist, self-test (mock or real, clearly labelled) | Merges parts of Settings |
| **Tailscale** | §E | Replaces Mesh |
| **System** | Service state, queue, DB size, log viewer with masking, version/update | Merges Logs + About |
| **Settings** | Theme, auto-start, wake-lock, auto-update, reset | Existing items, fixed |

**Roles:** there is one local owner; the only meaningful separation is **API key scopes** (SEC-01), not UI roles. Admin-only API operations require the `admin` scope.
**Responsive:** phones plus tablet/landscape layout (KivyMD navigation rail availability to be confirmed against the pinned version). **Web dashboard:** not proposed — it would add a new network-exposed surface; see **D1/D9** if you want one for desktop use over Tailscale.
**Accessibility:** Kivy exposes limited accessibility APIs; I will ensure contrast, touch-target size, focus order and back-button behaviour, and will document what the toolkit cannot provide rather than claim compliance.

---

## G. Testing & Verification Plan

### G.1 Baseline (recorded, Stage 1)

| Test | Expected | Actual | Result |
|---|---|---|---|
| Install `app/requirements.txt` + pytest + httpx into clean venv, collect tests | Collection succeeds | `ModuleNotFoundError: requests` | **Fail** (BLD-01) |
| Same, after `pip install requests` | All tests pass | `29 passed, 2 warnings` | Pass |
| `audit/verify_defects.py` (16 probes) | Document actual behaviour | See `audit/verify_defects_output.txt` | Evidence for SEC-01/02/03, SMS-01, API-01/02, DB-01/02/03, SMS-04/05 |

Not run (impossible here): lint (none configured), type check (none configured), APK build, Kivy GUI, device tests.

### G.2 Planned per-stage tests

- **Auth:** scope matrix (read/write/admin × every endpoint); revoke/rotate; legacy-file import; XFF spoof; per-key rate limit.
- **Messages:** idempotent replay; state machine with a mock provider emitting sent/delivered/failed/timeout; crash-recovery of `sending` rows; pagination totals; wildcard search.
- **Data:** migration from a v0.4.0 DB; FD stability; local-day metrics in several time zones.
- **Tailscale:** status table-tests with mocked interface lists; no secret persisted (assert `config.json` contents); bind-mode matrix.
- **Device plan (`docs/device-test-plan.md`, you run it):** permission grant/deny, single/dual SIM, airplane mode, foreground-service lifetime after swiping the app away, Tailscale four-state check, update-over-update install, 24 h idle battery/FD soak.
- Real SMS will only be sent to numbers you own; otherwise the mock provider is used.

---

## H. Decisions Needed Before Implementation

| # | Decision | My recommendation |
|---|---|---|
| **D1** | Tailscale path: A (official app) now, B optional, C spike? | A now; B read-only later; C only if you need no-Tailscale-app. |
| **D2** | OK to extend API responses with `status` and to change the message text from "sent successfully" to accepted/submitted wording, keeping `stat`/`id`? Additive, but clients that parse the sentence would notice. | Yes. |
| **D3** | Generating a key: keep multi-key behaviour (fix the dialog text) or make "generate" revoke all previous keys as the dialog promises? | Keep multi-key, fix text, add explicit revoke/rotate. |
| **D4** | Add inbound SMS (`RECEIVE_SMS`/`READ_SMS`) and client webhooks? New permissions; Play-policy restricted. | Defer; deliver delivery-receipt tracking first. |
| **D5** | Add bind-mode setting (default stays `all`)? | Yes, default unchanged. |
| **D6** | Approve removing `postFlask.py`, `/control/`, duplicate recipe directory (after a build confirms the recipe name)? | Yes, after confirmation. |
| **D7** | Release signing: will you create a release keystore and add it as a GitHub secret? Without it, in-app updates cannot be trusted to install (UPD-02). | Required for Stage 8. |
| **D8** | Intended gateway lifetime: should closing the app stop the service (current `on_stop`) or keep it running? | Keep running until the user stops it, with a visible notification. |
| **D9** | Any wish for a desktop web dashboard served by the gateway? | No for now. |
| **D10** | Do you have an Android test device with a SIM and a tailnet for the device test plan? | Needed for Stages 4, 5, 8. |

**Ready on approval:** Stage 2 (security/critical) is self-contained, testable in this environment, and touches only non-UI services, `requirements*.txt`, `buildozer.spec`, and tests. D2/D3/D5 are the only decisions it depends on.

## Appendix — Evidence index

| ID | File | Probe |
|---|---|---|
| V1–V3 | `audit/verify_defects_output.txt` | Key invalidation, revoked-key bypass, scope enforcement |
| V4 | same | Route shadowing |
| V5–V6 | same | `delivered_at` stamping; success wording |
| V7 | same | `X-Forwarded-For` bypass and victim lock-out |
| V8–V9 | same | Unauthenticated endpoints; `/control/` |
| V10–V16 | same | Idempotency, segmentation, LIKE, FD growth, UTC day, import side effect, body size |
| Baseline | `audit/baseline_pytest.txt` | 29 passed after adding `requests`; collection error before |


---

## Progress log

### Stage 2 — done (evidence: `audit/stage2_pytest.txt`, 42 passed; baseline was 29)

| Issue | Outcome | Evidence |
|---|---|---|
| BLD-01 | `requests` added to both requirement files; `pytest.ini` cleaned | clean install collects tests |
| SEC-01 | Scopes enforced on every endpoint | `test_scopes_enforced_matrix`, `test_admin_implies_all_and_key_management` |
| SEC-02 | SQLite only; `keys.json` imported once then renamed; revoked keys stay revoked after restart; admin key endpoints added; D3 applied (multi-key kept, dialog text corrected) | `test_revoked_key_rejected…`, `test_legacy_keys_json_migrated…` |
| SEC-03 | `X-Forwarded-For` ignored | `test_rate_limiting_ignores_forwarded_for` |
| SEC-04 | Tailscale credential never stored, returned or re-displayed; old stored keys scrubbed on start | `test_tailscale_credentials_are_never_retained` (service level; UI scrub path **not device-tested**) |
| SEC-05 | `allow_backup = False` | config change only, **not build-tested** |
| SEC-06 | No auto-copy, no key in snippet cache | code change, **not device-tested** |
| SEC-07 | Per-key send limit (default 300/min, `OPENSMS_SEND_RATE_PER_MIN`) | `test_send_rate_limit_per_key` |
| SEC-08 | Docs/OpenAPI/llms endpoints need auth unless `OPENSMS_PUBLIC_DOCS=1` | `test_ai_doc_endpoints_require_auth_by_default` |
| SEC-10 | Numbers masked; single log worker | `test_phone_masking_in_logs` |
| SMS-01 (partial) | `delivered_at` only on real `delivered`; responses say `delivery_confirmed: false`. **Receipts themselves are still Stage 4** — nothing yet moves a message to `delivered` | `test_response_does_not_claim_delivery` |
| SMS-05, API-01, API-05, DB-01/02/03 | Text cap 1600; history route with/without slash; literal LIKE; connections closed; lazy init; local-day metrics | `test_text_length_cap`, `test_history_route…`, `test_search_wildcards…`, `test_db_connections_are_closed`, `test_no_files_created_at_import` |

**Not done in Stage 2:** SEC-09 bind mode (needs service/UI work), SEC-11 workflow injection (Stage 8 CI work), a UI for listing/revoking keys (Stage 6 — until then revoking needs an `admin` key via the API, and the app only generates `sms:write`+`sms:read` keys), idempotency (Stage 3), true queue and delivery receipts (Stage 4), segmentation accuracy SMS-04, Tailscale redesign TS-01 (Stage 5: the "connected" claims in the Mesh screen are **still misleading**).

**Behaviour changes to be aware of:** `/docs`, `/openapi.json`, `/llms.txt`, `/docs/markdown` now need a Bearer token; send-response text changed (fields `stat`/`id` unchanged, `status` and `delivery_confirmed` added); "sent today" now uses local midnight; clients exceeding 300 messages/min per key get `429`.


### Stage 3 — done (evidence: `audit/stage3_pytest.txt`, 60 passed)

| Issue | Outcome | Evidence |
|---|---|---|
| API-02 | `Idempotency-Key` on single and batch send; atomic claim in SQLite; replay never sends or uses quota; failed attempts release the key; stale in-progress claims (>15 min) can be taken over; 24 h retention | `test_same_idempotency_key_sends_once_and_replays`, `…batch_idempotent…`, `…failed_send_releases_key…`, `…in_progress…`, `test_concurrent_requests_with_same_key_send_once` (8 threads, repeated 5×, exactly 1 message) |
| API-05 | Unified error envelope (additive, `detail` preserved), `total`/`has_more` on history | `test_error_envelope_is_additive`, `test_history_total_and_has_more` |
| DB-04 (partial) | `PRAGMA user_version` migrations; v0.4.0 database upgraded with data intact; newer-version databases refused | `test_migration_from_v040_database_preserves_data`, `test_refuses_database_from_a_newer_version` |

**Not done / caveats:** `docs/openapi.json` and `llms*.txt` still describe the old responses (regenerating them is queued with the Stage 8 docs pass); the `webhooks` table is still unused; API-03 (blocking send inside the request handler, no queue) is intentionally left for Stage 4 because it needs the delivery-receipt design and device testing; there is no global handler for unexpected exceptions (they still return FastAPI's default 500). The migration was tested against a hand-built v0.4.0 schema, **not** against a database from a real device.


### Stage 4 — done on the Python side (evidence: `audit/stage4_pytest.txt`, 103 passed; 43 new tests)

| Issue | Outcome | Evidence |
|---|---|---|
| SMS-01 | Status model `queued→submitted→sent→delivered/failed/unknown`; per-part receipts; `delivered` only from a delivery report for every part; partial/pending/unknown reports never count | `test_resolve_status` (13 cases), `test_lifecycle…`, `test_multipart_needs_every_part`, `test_unknown_or_pending_delivery_reports_never_mark_delivered`, `test_receipt_arriving_during_submit_is_not_lost` |
| API-03 | Background worker + bounded queue (1000); event loop no longer blocked; `202` when busy; `503 queue_full`; restart recovery without double-sending | `test_event_loop_is_not_blocked_by_a_slow_send`, `test_slow_provider_gives_202…`, `test_queue_full…`, `test_restart_recovers…` |
| SMS-02 | Simulation refused unless `OPENSMS_ALLOW_SIMULATION=1`; simulated rows tagged | `test_simulation_is_refused_unless_explicitly_enabled` |
| SMS-03 | Inactive `sim_slot` -> 422, nothing stored (single and batch) | `test_invalid_sim_slot_rejected…` |
| SMS-04 | GSM-7 extension table, UTF-16 units, no split of multi-unit characters | `test_segment_estimates` (12 cases), `test_extension_char_is_not_split…` |
| (new) | Watchdog marks stuck `submitted` messages `unknown`, only with a receipt-capable provider | `test_watchdog_only_for_real_provider` |

**Test integrity check:** I deliberately broke the code in three ways (accept "unknown" reports as delivery; one sent part enough; stamp `delivered_at` on `sent`); the new tests failed each time and passed again after restoring.

**What is verified vs not.** Verified: all state-machine, queue, validation and API behaviour against a mock provider; the two Java classes compile against hand-written stubs of the Android classes and their method descriptor `(String,String,int,int,int)V` matches the Python listener. **Not verified:** that they compile against the real Android SDK; real `SmsManager` calls; that sent/delivery broadcasts actually arrive (registration with `RECEIVER_NOT_EXPORTED`, `FLAG_MUTABLE` + `setPackage` on Android 14+); the pyjnius `PythonJavaClass` bridge; carrier delivery-report behaviour; the foreground-service lifetime. If the Java classes are missing at runtime the app logs "SMS receipts unavailable" and messages remain `submitted`, never falsely `sent`/`delivered`. If receipts fail in practice on Android 14+, the documented fallback is a manifest-declared receiver.

**Limitations to know:** idempotent replays of a `202` response return `200` with the same body; a message acknowledged by the radio but whose receipt was lost to a process restart ends as `unknown` after 10 minutes (it may well have been sent); `docs/openapi.json`/`llms*.txt` still need regeneration (Stage 8).


### Stage 5 — done except device verification (evidence: `audit/stage5_pytest.txt`, 130 passed; `audit/screens/*.png`)

Decision applied: **option A** (official Tailscale app is the data path; OpenSMS observes). Option B (API peer list) and C (embedded `tsnet`) were **not** built.

| Issue | Outcome | Evidence |
|---|---|---|
| TS-01 | Fake connect removed; no key/IP entry; stored key/IP from older versions dropped at start; status only from observation; misleading "worldwide dispatch active" text gone | `test_service_keeps_no_credentials_and_has_no_connect_api`, screenshots |
| TS-02 | Heuristic that sent arbitrary strings to the Tailscale API is gone (no network code in the service) | AST import check in that test |
| TS-03 | PHP chip added; snippets contain no key; overflow fixed (wrapping grids) | screenshots, headless button-press run |
| TS-04 | Carrier CGNAT addresses no longer counted as Tailscale (interface-name rule + VPN-network rule); IPv6 range recognised; "could not read" is `unknown`, not "disconnected" | `test_carrier_cgnat_address_is_not_tailscale`, `test_interface_fallback_requires_a_tunnel_interface`, `test_unreadable_state_is_unknown…` |
| SEC-09 | Listening modes all / tailscale / localhost; **fail closed**; confirmation dialog; auto-retry every 10 s | `test_resolve_bind_host`, 4 subprocess tests that run the real service logic and check what actually listens |
| SRV-01 (new, pre-existing) | A failed bind (port in use / address unavailable) made uvicorn call `sys.exit(1)` in the server thread; it was uncaught so the UI kept showing "started". Now reported as an error | `test_service_reports_port_already_in_use`, `test_service_tailscale_mode_never_falls_back_when_bind_fails` |

**Test integrity:** three deliberate breakages (bind falling back to `0.0.0.0`; interface fallback trusting any interface name; removing the SystemExit handler) were each caught and passed again after restoring.

**Verified vs not.** Verified: decision logic, bind resolution, the service's start/stop behaviour with real sockets, KivyMD screen construction/rendering in light and dark themes, button-to-handler dispatch (Kivy 2.3.1 + KivyMD master on Linux). **Not verified on a phone:** `ConnectivityManager.getAllNetworks()/TRANSPORT_VPN` detection (may be affected by Android version/OEM, needs the new `ACCESS_NETWORK_STATE` permission), the explicit Tailscale launcher intent, behaviour while the Tailscale app and OpenSMS compete for background execution, and whether a remote device can actually reach the phone. Screenshots use injected states, not a real tunnel.

**Not shown on purpose:** a "connecting" state (no reliable signal without Tailscale's local API), and a peer list. The brief's requests for device registration/authentication, connect/disconnect controls and peer reachability were **declined** under option A because they need a credential on the phone or an embedded client; the "Open Tailscale" button is the supported path.


### Stage 6 — partly done (evidence: `audit/stage6_pytest.txt` 140 passed; `audit/screens/4…13_*.png`)

**Built**
| Area | What exists | Evidence |
|---|---|---|
| Navigation | 5-tab bottom bar SMS / Messages / API / Mesh / Settings; drawer entries; Logs reachable from the drawer | screenshots |
| Messages (UX-01) | Search (debounced), 7 status filters, pagination (25/page, "Load more", "Showing x of y"), colour-coded status chips, detail dialog with plain-language status meaning and per-part progress, skeleton loading, empty state, error state with Retry, 5 s auto-refresh with stale-response protection | `test_stage6_ui_logic.py` (9 tests on the data/formatting layer); headless walkthrough run of the real app; screenshots 4–6, 12, 13 |
| API keys (SEC-02 UI gap) | List with permissions/created/last used/state; create with Send/Read/Admin, inline name validation that keeps the dialog and typed input, double-submit guard, key shown once with explicit Copy (no auto-clipboard), revoke with confirmation | walkthrough log `inline_validation`; screenshots 7–11; `test_key_rows_and_scope_text` (no hash/secret reaches the UI model) |
| Shared components | `StatusChip`, `EmptyState`, `SkeletonRow`, Kivy-free `uiFormat.py`; every icon name validated against the bundled icon font (found and fixed one invalid name) | `test_ui_icons.py` |
| Themes | Light and dark verified on Messages, Mesh | screenshots 3, 13 |

**Not done (be aware)**
- ~~In-app sending with confirmation~~ — **done later**, see *Stage 6 completion* below.
- **Overview, Gateway, System, Settings, Logs** were not redesigned (Home/Settings/Logs are as before apart from the nav changes). No separate Gateway/System pages exist.
- **No per-key usage statistics or request log** in the API tab: the gateway does not record them, and the UI does not pretend otherwise.
- **Tablet/landscape layout, accessibility audit, keyboard navigation**: not assessed. Kivy exposes little accessibility API; only contrast was eyeballed in two themes and touch targets on the new buttons are 48 dp.
- **Light-theme screenshots of the new tabs** were taken for Messages only implicitly (screens 4–12 are light, 13 dark); the API tab has no dark capture.
- Screenshots come from a Linux software renderer at 412x860: real devices differ in density, fonts and system bars.
- Status-chip icons render slightly larger than the label text; cosmetic, not fixed.
- Behaviour on a real phone (scrolling with hundreds of rows, rotating the screen, back-button handling) is untested.


---

## Stages 7–8 — done as far as possible (evidence: `audit/stage7_8_pytest.txt`, 198 passed + 1 skipped; the skipped icon test runs in the Kivy environment, where all 199 pass)

| Item | Outcome | Evidence |
|---|---|---|
| Lint | `ruff.toml` (syntax errors + pyflakes). Fixed real findings (unused code, a duplicate import); UI-file exceptions documented (Kivy imports register widgets) | `ruff check .` clean |
| Dependency audit | `pip-audit` found 12 advisories in starlette 0.48 (several in features this app does not use, two about `request.url` built from untrusted input). Moved to fastapi 0.162.0 / starlette 1.9.0 with pydantic held at 2.12.3; audit clean; full suite passes on the exact pinned set built from scratch | `pip-audit` output, clean-venv runs |
| Pins (BLD-02) | Exact pins in `requirements-core.txt`, full freeze in `constraints.txt`, APK pins in `buildozer.spec`, KivyMD and the python-for-android fork pinned **by commit**; stale comment removed; a test keeps them in sync and checks the pydantic-core recipe | `test_ci_config.py` (4 deliberate breakages caught) |
| CI | `ci.yml` (lint, tests 3.11/3.12, audit, headless UI smoke test that exits non-zero when a screen is broken: verified by breaking one) | YAML parsed, static tests; **never executed** |
| Release (UPD-02, SEC-11) | Tag validated against the app version, signing from secrets, fails rather than publishing an update that cannot install, `.sha256` published, no untrusted input in shell | static tests; **never executed** |
| Updater (UPD-03) | Trusted-URL check, SHA-256 verification, honest "unverified" flag, browser fallback when the installer cannot open | `test_stage7_release.py` (26 tests, 2 deliberate breakages caught) |
| Single version, dead code | `app/app_version.py`; `postFlask.py` removed (no references anywhere) | `test_version_has_a_single_source`, `test_removed_dead_flask_module_is_really_unused` |
| ARCH-01 | `services/reqWatch.py`: read only on change, 1 s polling after 10 s idle; unique temp names for atomic writes | `test_stage8_ipc.py` (7 tests incl. the real service loop in a subprocess; 3 deliberate breakages caught) |
| Docs | `docs/security.md`, `docs/deployment.md`, troubleshooting table, `.env.example`, `docs/testing.md`; API reference, llms files, index and README corrected; `docs/openapi.json` generated from the app with a drift test | `test_docs_consistency.py` — it found 5 more stale claims that I fixed |
| **Regression found and fixed in my own Stage 4 work** | The app never requested `READ_PHONE_STATE`, so on a real phone the SIM list is probably always the placeholder. My `sim_slot` validation would then have rejected a valid second SIM. It now refuses to guess only when Android could not be asked, says why, and the permission is declared and requested. Dual-SIM routing very likely never worked before (it failed silently to the default SIM) | `test_sim_validation_*` (1 deliberate breakage caught); **device test 1.6/1.6b** |

## Resolution status of every issue

| Status | Issues |
|---|---|
| **Fixed and tested here** | UX-01 send form, ARCH-01 (change-detecting watcher + unique temp files; the real service loop is tested end to end, but the battery saving is **not measured** on a device), SEC-01, SEC-02, SEC-03, SEC-04, SEC-07, SEC-08, SEC-10, SMS-02, SMS-04, SMS-05, API-01, API-02, API-03, API-05, DB-01, DB-02, DB-03, TS-01, TS-02, TS-03, BLD-01, BLD-02, UPD-03, SRV-01 (new), TEST-01 (largely) |
| **Fixed in code, needs a device to confirm** | SEC-05 (needs a build), SEC-06, SEC-09 (Tailscale detection), SMS-01 (receipts), SMS-03 (SIM routing + permission), TS-04 (VPN detection) |
| **Pipeline written, needs your input and a run** | UPD-02 (needs your keystore secrets), SEC-11 |
| **Fixed in code, needs a device to confirm (added later)** | UPD-01: the installer now uses `PackageInstaller` (no `FileProvider` needed) with the old intent and the release page as fallbacks; ARCH-02: the gateway keeps running when the app is closed (sticky service, no stop on task removal, wake lock moved into the service) |
| **Partial** | DB-04 (migrations done; no retention setting, unused `webhooks` table remains), ARCH-03 (version source and dead Flask file done; duplicate `pydantic_core` recipe dir and `/control/` left), UX-01 (Messages and API done; see Stage 6) |
| **Open (not done)** | SMS-06 inbound SMS and webhooks (D4 deferred), API-04 `/control/` (kept as an admin-only no-op until you say remove it), ARCH-04 `main.py` not split |
| **Resolved** | The in-app updater trusts `ShanudhaTirosh/OpenSMS`, which you confirmed is your repository, so `UPDATE_REPO` is correct as it is |

## Files created, modified, removed (against the uploaded zip)

**Created (32):** `.env.example`, `ruff.toml`, `.github/workflows/ci.yml`, `app/app_version.py`, `app/constraints.txt`, `app/requirements-core.txt`, `app/java_src/org/opensms/gateway/{SmsResultListener,SmsResultReceiver}.java`, `app/screens/{apiKeys,components,messages}.py`, `app/services/{authSvc,messageSvc,smsReceipts,uiFormat}.py`, `docs/{deployment,device-test-plan,security,tailscale,testing}.md`, `tools/{gen_openapi,ui_walkthrough}.py`, `tests/{conftest,test_ci_config,test_docs_consistency,test_security_stage2,test_stage3_api,test_stage4_sms,test_stage5_tailscale,test_stage6_ui_logic,test_stage7_release,test_ui_icons}.py`
**Modified (29):** both other workflows, `CHANGELOG.md`, `README.md`, `llms.txt`, `pytest.ini`, `app/{buildozer.spec,main.py,main_layout.kv,req_android.txt,requirements.txt}`, `app/screens/tailscaleScr.py`, `app/services/{appSvc,dbMgr,logSvc,pathMgr,postApi,smsApi,tailscaleSvc,updateMgr}.py`, `docs/{ai-integration,api-reference,troubleshoot,quickstart}.md`, `docs/{index.html,llms-full.txt,llms.txt,openapi.json}`, `tests/test_api_and_services.py`
**Removed (1):** `app/services/postFlask.py` (unreferenced; recoverable from the patch). Nothing else was deleted. Three old tests that asserted the fake Tailscale connect behaviour were replaced.

## Open decisions (answer these and I can continue)

1. **D7 — release keystore:** create it and add the four secrets (steps in `docs/deployment.md`). Until then releases cannot be published, by design.
2. **`UPDATE_REPO`:** which repository should the in-app updater trust?
3. **D10 — device:** run `docs/device-test-plan.md` (sections 1, 4 and the SIM checks). This is the largest remaining risk.
4. **D6:** remove `/control/` and the duplicate `pydantic_core` recipe directory (needs a build to confirm which name is used)?
5. **D8:** should closing the app stop the gateway (current behaviour) or keep it running?
6. **D4 / D1 / D9:** inbound SMS + webhooks; embedded Tailscale spike; desktop web dashboard — all still deferred.
7. **Stage 6 remainder:** in-app send form, Overview/Gateway/System/Settings redesign.


## Stage 6 completion — in-app sending (evidence: `audit/stage7_8_pytest.txt`, 198 passed + 1 skipped; 199 with Kivy)

| Item | Outcome | Evidence |
|---|---|---|
| In-app send (brief §6) | Messages tab "new message": number + text, live segment count, inline validation, review/confirm step, double-tap guard; the message goes to the service through an **outbox** and so has a normal history entry, status and receipts. The Home "Test SMS" uses the same path (it used to bypass the message table and never had receipts) | `test_stage9_outbox.py` (11 tests incl. the real service loop end to end); the headless walkthrough drives compose → invalid number → review → double-tap Send and checks exactly one outbox file with the right payload; screenshots 14–16 |
| Safety | File name = message id and the service skips ids it already knows, so a crash after acceptance cannot send twice; malformed items are quarantined as `.bad`; a full queue leaves the file for a later pass; an inactive SIM becomes a visible `failed` row with the reason | 2 deliberate breakages caught (duplicate guard removed; full-queue retry removed) |

Caveats: the confirmation dialog looks slightly translucent in the software-rendered screenshot (probably the previous dialog fading out underneath; not confirmed on a device); the service picks up outbox files within about a second; compose does not offer a per-message SIM choice (it uses the SIM selected in Settings); the whole path is exercised only against the simulated provider here.


## Background operation and the updater — added after your answers (evidence: `audit/stage7_8_pytest.txt`, 234 passed + 1 skipped; 235 with Kivy)

Your decisions: the repository is `ShanudhaTirosh/OpenSMS`; there is no signing key yet (you can create one); you have a device; **the gateway must keep running when the app is closed and stop only when you stop it** (this is D8).

| Item | Outcome | Evidence |
|---|---|---|
| Keep running after the app closes (ARCH-02) | The python-for-android fork stops a non-sticky service when the app task is removed (`onTaskRemoved` in `PythonService.java`). The service is now declared `sticky` (Android restarts it if killed) and `on_stop` no longer stops it. **Stop Server** is the only thing that ends it, and then also removes the notification | `test_closing_the_app_does_not_stop_the_service`, `test_only_the_stop_button_stops_the_service`, `test_service_is_sticky_…` (4 deliberate breakages caught) |
| **Android 15+ time limit** | The old `dataSync` service type is limited to 6 hours per 24 on apps targeting API 35+ (this app targets 36); when the timeout fires the service must stop within seconds or the app crashes (Android developer documentation). Switched to `specialUse` (no timeout) with permission `FOREGROUND_SERVICE_SPECIAL_USE`. The service entry in the fork's manifest template cannot carry the optional `PROPERTY_SPECIAL_USE_FGS_SUBTYPE` element; as far as I know Android does not check it at runtime (Play review would), but **device test 5.9 (overnight run on Android 15+) is the real proof** | spec test; device plan 5.9 |
| Reopening the app no longer stops the server | Previously every launch deleted the status file and wrote a default "stop" request before the saved settings were even loaded. Now the last choice is saved and restored (`server_desired`) and a running service is left alone | `test_service_heartbeats_and_survives_the_app_reopening` runs the real service loop, rewrites the request as a reopened app would, and checks the port never drops (0 gaps) |
| Wake lock | Moved into the service so it survives closing the app; held only while the server runs and the setting is on | `test_wakelock_*` (4 tests) |
| Stale status | The service writes a heartbeat every 3 s; the app ignores a status older than 12 s, and in-app sending says so when the service is not running | `test_status_freshness`, heartbeat test |
| Battery optimisation | Settings > "Keep running in background" opens Android's battery list | device plan 5.3/5.4 |
| Updater (UPD-01) | `PackageInstaller` path added with fallbacks; Java receiver compiled against stubs and its method signatures checked against the Python side; conflict (signature) errors explained | `test_stage7_release.py` (44 tests incl. fallback order) |
| Testing without a key | `build-apk.yml` now caches the debug keystore so each test build installs **over** the previous one | `test_debug_builds_keep_a_stable_signature` |

Known limits: not restarted after a phone reboot (no boot receiver; open the app once); *Force stop* kills it until you reopen the app; manufacturer battery managers can still kill background apps (see `docs/deployment.md`); everything Android-specific above is unverified until you run `docs/device-test-plan.md` sections 1, 4, 5 and 6.

## Open decisions (updated)

1. **Signing key** (D7): not needed for testing now; needed before a public release. Steps: `docs/deployment.md`.
2. **Device test**: sections 1, 4, 5, 6 of `docs/device-test-plan.md`, especially 5.9 (overnight on Android 15+), 1.x (SMS receipts) and 6.x (updater).
3. D6: remove `/control/` and the duplicate `pydantic_core` recipe directory?
4. D4/D1/D9: inbound SMS + webhooks, embedded Tailscale, desktop dashboard: still deferred.
5. Remaining redesign: Overview, Gateway, System, Settings screens; tablet layout.


## System screen and maintenance — added last (evidence: `audit/stage7_8_pytest.txt`, `audit/screens/17_system.png`, `18_clear_confirm.png`)

Chosen because it makes the device testing you are about to do much easier: one screen says why something does not work.

| Item | Outcome | Evidence |
|---|---|---|
| System & diagnostics (brief §6 System Administration) | Service heartbeat, API server state/address, queue size, wake lock, SMS/Phone permissions, delivery tracking active?, SIM detection, Tailscale, storage, version; plain-language hints; copyable report with no keys, numbers or message text. The service publishes the facts only it knows (receipts, wake lock, queue) in its heartbeat | `test_stage11_system.py` (14 tests); real-app walkthrough checks the five sections and that the report leaks nothing |
| History maintenance (DB-04 retention, manual) | Clear finished messages older than 30 days or all; **in-flight messages and API keys are never deleted**; receipt rows are removed with their messages; confirmation dialog | 3 deliberate breakages caught; walkthrough presses Delete on the real dialog and verifies the count drops |
| Bug found and fixed | Both the app and the service registered the SMS receipt receiver, so every receipt would have been processed twice; now only the service registers it | `test_ui_process_does_not_register_the_receipt_receiver` |

Not done: automatic retention (a "keep N days" setting), Overview/Gateway/Settings redesigns, tablet layout. The System screen reports what the app can read; whether it is correct on a real phone (permissions, receipts, SIMs) is part of device test section 7.
