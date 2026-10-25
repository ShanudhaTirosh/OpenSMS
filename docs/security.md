# Security

OpenSMS turns a phone into an HTTP API that can send billable SMS. This page says what is protected, how, and
what is **not**.

## What is stored where (on the phone)
| Data | Location | Protection |
|---|---|---|
| API keys | SQLite `config/opensms.db`, table `api_keys` | Only a SHA-256 hash is stored; the secret is shown once at creation |
| Message text and recipients | same database, `messages` | **Not encrypted**, kept until you clear app data (no retention setting yet) |
| Settings | `config/config.json` | No secrets. Tailscale credentials are never stored |
| Logs | `logs/api_logs.log` | Phone numbers are masked (`+94******567`); no keys or message text |
| Android backup | disabled (`allowBackup=false`) | Database and settings are not copied to cloud/adb backups |

## API keys
- Scopes are enforced on every endpoint: `sms:write` (send), `sms:read` (history, stats), `admin` (key management, `/control/`).
  Give each client the minimum it needs.
- Create and revoke keys in the app (**API** tab) or with an `admin` key (`POST /keys/`, `DELETE /keys/{id}`). Revocation is immediate.
- **Rotation:** create a new key, switch the client to it, confirm it works, then revoke the old one.
- **Suspected leak:** revoke the key first, then check **Messages** for unexpected sends. A leaked key can send at
  most 300 messages per minute (per-key limit) until revoked.
- Failed logins are limited to 10 per minute per client address (socket address; `X-Forwarded-For` is ignored).

## Network exposure
- The default listening mode is **all networks** over **plain HTTP**. On Wi-Fi/LAN the API key travels unencrypted.
- Prefer **Tailscale only** (WireGuard-encrypted, reachable only from your tailnet; fails closed if Tailscale is off)
  and restrict the port with Tailscale ACLs. Use **This phone** to disable remote access entirely. See [tailscale.md](tailscale.md).
- OpenSMS does not terminate TLS. If you need HTTPS, put a tunnel/reverse proxy you control in front of it.
- Interactive docs and the AI discovery files require an API key unless `OPENSMS_PUBLIC_DOCS=1`.

## Tailscale credentials
OpenSMS never asks for, stores or transmits a Tailscale auth key or API key. Versions before this audit stored one in
plain text; it is deleted on first start of the new version. **If you ever entered a Tailscale key in an old version,
revoke it in the Tailscale admin console.**

## Background service
The gateway runs as a sticky foreground service so it survives closing the app; a persistent notification shows it is active and **Stop Server**
ends it. Anyone who can unlock the phone can stop it. Because it keeps listening while the app is closed, use a strong API key per client,
the **Tailscale only** listening mode where possible, and revoke keys you no longer use.

## Updates and release signing
- The in-app updater only accepts `https://github.com/<configured repo>/releases/download/...` URLs
  (`UPDATE_REPO` in `app/app_version.py`; it defaults to the upstream project, **change it if you publish from your own fork**),
  verifies the published SHA-256 when one exists, and Android additionally checks that the APK is signed with the same key as the installed app.
- Releases must be signed with one stable release key (see [deployment.md](deployment.md)). Keep the keystore and its
  passwords in a password manager and an offline backup. **Losing or replacing the key breaks in-app updates:** users
  would have to uninstall (losing local data) and reinstall.
- Rotating the GitHub signing secrets without changing the keystore is safe; changing the keystore is not.

## Known limitations
- No TLS, no encryption of the message database, no data-retention/purge setting.
- SMS delivery confirmation depends on the carrier returning delivery reports.
- The Android-specific code (SMS receipts, VPN detection, installer) has not been verified on hardware yet: see [device-test-plan.md](device-test-plan.md).
- `POST /control/` is a reserved no-op (admin only).
- The pinned dependency set is clean in `pip-audit` today; re-run it (CI does) when updating pins.

## Reporting a vulnerability
Open a private security advisory on the repository (GitHub: Security > Report a vulnerability) rather than a public issue.
