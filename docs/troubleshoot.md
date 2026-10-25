# Debug app problems

## App crash with kivymd 2.x

- Debug steps

```bash
adb logcat -c
adb logcat -b crash -v threadtime

adb shell getprop ro.build.version.release
adb shell getprop ro.product.manufacturer
adb shell getprop ro.product.model
```

---

# Troubleshooting the gateway

**Start with the System screen** (menu > *System & diagnostics*): it checks the background service, permissions, delivery tracking, SIMs, Tailscale and storage, explains each problem and can copy a report (without keys, numbers or message text) for a bug report.

| Symptom | Likely cause / what to do |
|---|---|
| `401 unauthorized` | Missing or wrong key. Keys are shown only once; create a new one in the **API** tab |
| `403 insufficient_scope` | The key lacks the scope (send = `sms:write`, history = `sms:read`) |
| `429 rate_limited` | 10 failed logins in a minute from your address: wait 60 s |
| `429 send_rate_limited` | The key exceeded 300 messages per minute: honour `Retry-After` |
| `502 delivery_failed` | The hand-off to Android failed; read `detail` (radio off, no service, invalid number) |
| `503 queue_full` | More than 1000 messages waiting; retry after `Retry-After` |
| `422 invalid_sim_slot` | That SIM slot is not active; see `GET /system/sims/` |
| Message stays `sent`, never `delivered` | Normal when the carrier does not send delivery reports |
| Message `unknown` | The app restarted or the result was lost; it may or may not have been sent. It is never re-sent automatically |
| Message stays `submitted` | Receipts are not arriving; check logcat for "SMS receipts unavailable" and the [device test plan](device-test-plan.md) |
| Server shows an error when started | Port already in use, or *Tailscale only* mode without a Tailscale address; the message says which |
| API unreachable from another device | Listening mode *This phone*; Tailscale not connected; Android battery optimisation stopped the service; wrong address |
| The gateway stops after a while with the screen off | Battery management: set OpenSMS to *Unrestricted* (Settings > Keep running in background) and allow auto-start / background activity in your manufacturer's settings |
| The gateway is offline after a reboot | It does not start by itself after a reboot; open the app once |
| "The gateway is not running" when sending from the app | In-app sending needs the service: Home > Start Server first |
| Update "Install" opens the browser | Automatic install is not available on this device; download the APK from the opened release page |
| "Checksum mismatch" on update | The download did not match the published SHA-256 and was discarded; retry, and report if it persists |
