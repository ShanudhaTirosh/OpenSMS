# Device test plan (Stages 4-5)

Everything below needs a real Android phone with a SIM. **None of it has been executed yet**: the receipt
plumbing (`app/java_src/*`, `app/services/smsReceipts.py`) and the Android provider were written to spec but
could not be compiled or run in the development sandbox. Use only numbers you own.

## 0. Build sanity
| # | Check | Expected |
|---|---|---|
| 0.1 | CI builds the APK with `android.add_src = java_src` | Gradle compiles `SmsResultReceiver` and `SmsResultListener` without errors |
| 0.2 | Start the gateway, then `adb logcat -s python` | No "SMS receipts unavailable" notice. If it appears, receipts are disabled and messages stay `submitted` |

## 1. Message lifecycle (own number, SIM with credit)
| # | Action | Expected |
|---|---|---|
| 1.1 | `POST /sms/` short text to your own number | Response `status: submitted`, `delivery_confirmed: false`; within seconds `GET /sms/{id}` -> `sent` |
| 1.2 | Wait up to a few minutes | `delivered` ONLY if your carrier returns delivery reports; otherwise it correctly stays `sent`. Record which one happened |
| 1.3 | 400-character text (multi-part) | `parts` shows 3 rows; `sent` only after all 3 report; `delivered` only after all 3 reports |
| 1.4 | Airplane mode on, send | `failed` with "Radio is off (airplane mode?)" (or another radio error text); no `delivered_at` |
| 1.5 | No SIM / no service | `failed` with a service error, API returns 502 `delivery_failed` |
| 1.6 | Grant the Phone permission, then `GET /system/sims/`: expect `"reliable": true` and your real carrier names. Then dual SIM: `sim_slot` 0 then 1; also an inactive slot (e.g. 5) | Message leaves via the chosen SIM; slot 5 -> 422 `invalid_sim_slot`, nothing stored |
| 1.6b | **Deny** the Phone permission, `GET /system/sims/`, then send with `sim_slot: 1` | `"reliable": false` (placeholder SIM); the send is refused with 422 `invalid_sim_slot` explaining the permission; a send without `sim_slot` still works |
| 1.7 | Force-stop the app right after a send, restart | Row is `unknown` (not `failed`) if no receipt arrived; no duplicate send |
| 1.8 | `Idempotency-Key` retry of 1.1 | Same id returned, only one SMS received |
| 1.9 | Messages tab > new-message button: send to your own number (review step, then Send; tap Send twice quickly) | One SMS arrives; the message appears in the list within ~1-2 s as Queued/Submitted, then Sent. The Home "Test SMS" behaves the same. Force-stop the app right after Send and reopen: still exactly one SMS |

## 2. Android 14+ specifics (to confirm)
| # | Check | Expected |
|---|---|---|
| 2.1 | Status report on Android 14+ with `FLAG_MUTABLE` + `setPackage` | `parts[].delivery` is populated when the carrier sends reports. If sends throw "implicit mutable PendingIntent" errors, switch to a component-targeted manifest receiver |
| 2.2 | Android 13+ `RECEIVER_NOT_EXPORTED` registration | Sent receipts still arrive |

## 3. Load / reliability
| # | Action | Expected |
|---|---|---|
| 3.1 | Batch of 20 to your own number | All `submitted` -> `sent`; API stays responsive meanwhile (`/health/`) |
| 3.2 | 24 h idle | Service alive, no growth in open file descriptors, acceptable battery use |

## 7. System screen (use this first when something does not work)
| # | Action | Expected |
|---|---|---|
| 7.1 | Menu > System & diagnostics with the gateway running | "Background service: Running", API server Online with the real address, SMS/Phone permission Granted, **Delivery tracking: Active**, SIM cards detected |
| 7.2 | Deny the SMS permission in Android settings, refresh | A warning with the fix; sending is refused |
| 7.3 | Stop the server, refresh | Service/server states change accordingly; no false alarm |
| 7.4 | Copy report, paste it somewhere | Readable text, no API keys, numbers or message text |
| 7.5 | "Clear messages older than 30 days", then "Clear all finished messages" | Counts drop; anything Queued/Submitted at that moment stays; API keys are untouched |

## 6. In-app update
| # | Action | Expected |
|---|---|---|
| 6.1 | Publish a build with a higher version (see deployment.md), open Settings/Home > Check for updates > Install | The app downloads (checksum verified if a `.sha256` exists), Android shows its install screen, the app is replaced and your data (keys, history) is still there |
| 6.2 | First time: "Install unknown apps" not yet allowed for OpenSMS | Android sends you to allow it; try again |
| 6.3 | Offer a debug-signed update to a release-signed install (or the reverse) | A clear message that the signatures conflict and the remedy (uninstall); no crash |
| 6.4 | Turn Wi-Fi off during the download | Clear error, no half-installed state, retry works |
| 6.5 | If the system installer never appears | The release page opens in the browser as the fallback; note the logcat line "PackageInstaller path failed" |

## 5. Running in the background
| # | Action | Expected |
|---|---|---|
| 5.1 | Start Server, then press Home and swipe OpenSMS out of recents | The notification stays; an API call from another device still works |
| 5.2 | Reopen the app after 5.1 | It shows **GATEWAY ONLINE** immediately (no restart; a long `curl` loop sees no gap) |
| 5.3 | Screen off for 1 hour (battery optimisation set to Unrestricted) | The API still answers; note any OEM that stops it |
| 5.4 | Same without the battery exemption | Record what happens (this shows why the setting exists) |
| 5.5 | Settings > Background WakeLock off, then on | `adb shell dumpsys power \| grep OpenSMS` shows the wake lock only while the server runs and the setting is on |
| 5.6 | Press **Stop Server** | Server stops, notification disappears, API refuses connections; reopening the app shows STANDBY (it does not restart by itself) |
| 5.7 | Start, swipe the app away, then `adb shell am kill in.daslearning.opensms` (or kill from a task manager) | Android restarts the service and the server comes back (sticky) without opening the app |
| 5.8 | Start, then Force stop in Android settings | Everything stops; Android does not restart it until you open the app |
| 5.9 | **Android 15+ phone: leave the gateway running more than 6 hours (ideally overnight, app closed)** | Still running; no crash. This is the check that `specialUse` fixed the `dataSync` timeout |
| 5.10 | Reboot the phone | Not running (expected); opening the app restores the last choice |
| 5.11 | With the gateway stopped, try Messages > new message | A toast says the gateway is not running |

## 4. Tailscale (Stage 5)
| # | Action | Expected |
|---|---|---|
| 4.1 | Tailscale app connected; open OpenSMS -> Mesh | State "connected", the same `100.x` address the Tailscale app shows, diagnostics `[OK] ... (vpn network)`. If it says "status unavailable", check logcat for "VPN network query unavailable" (permission/API) |
| 4.2 | Disconnect Tailscale | "not connected" within one Refresh; no stale address |
| 4.3 | Start another VPN instead | "Another VPN is active" |
| 4.4 | Mobile data on a carrier that uses CGNAT (`100.64/10` on `rmnet*`), Tailscale off | "not connected" (not a false positive) |
| 4.5 | Mode *Tailscale only*, Tailscale connected, start server, call it from another tailnet device | Works; the same call over Wi-Fi/LAN IP is refused |
| 4.6 | Mode *Tailscale only*, Tailscale off, start server | Error shown, nothing listening; connect Tailscale -> server starts within ~10 s |
| 4.7 | Mode *This phone* | Remote calls refused; switching back to *All networks* restores them |
| 4.8 | Tap "Tailscale app" with Tailscale installed / uninstalled | App opens / Play Store (or web) opens |
| 4.9 | Upgrade from an older build that had stored a Tailscale key | `config.json` no longer contains a `key` or `ip`; no key appears in the UI |
