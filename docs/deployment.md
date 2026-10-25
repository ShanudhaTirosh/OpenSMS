# Development, deployment and rollback

## Development
```
python -m venv .venv && . .venv/bin/activate
pip install -r app/requirements-core.txt -c app/constraints.txt pytest httpx pyyaml ruff
ruff check .
python -m pytest tests -q
python tools/gen_openapi.py          # after changing endpoints: regenerates docs/openapi.json (a test fails if stale)
```
The UI needs Kivy/KivyMD (`pip install -r app/requirements.txt`); see [testing.md](testing.md) for the headless UI walkthrough.
`.env.example` lists the optional environment variables (desktop/dev only; on Android the defaults apply).

## What CI does
| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | push / PR | ruff, tests on Python 3.11 and 3.12 (pinned deps), `pip-audit` (advisory), headless UI smoke test with screenshots |
| `build-apk.yml` | push / PR / manual | tests, then a **debug** APK as a downloadable artifact (never published as a release) |
| `release.yml` | tag `vX.Y.Z` / manual | tests, **signed** release APK + `.sha256`, GitHub Release |

None of these workflows could be executed in the environment where they were written; the first run on your repository
is their real test. If the APK build fails, read the Gradle/buildozer log first: `app/java_src` (SMS receipt receiver)
and the new pins are the newest build inputs.

## Background operation (the gateway keeps running when you close the app)
- The gateway is an Android **foreground service** (`opensmssvc`, shown as a notification). It is declared **sticky** and of type
  `specialUse`, so closing the app or swiping it from recents does **not** stop it, and Android restarts it if it is killed.
- It stops only when you press **Stop Server** in the app (that also removes the notification). Reopening the app restores what you left:
  if the gateway was running it stays running and the app shows it as online.
- Why `specialUse` and not `dataSync`: on Android 15 and newer, a `dataSync` foreground service is limited to 6 hours per 24 hours and the
  app crashes if the service does not stop when the timeout fires (Android developer docs, "Foreground service timeouts").
- The CPU wake lock is held by the service while the server runs (Settings > Background WakeLock), so it survives closing the app.
- It does **not** start by itself after the phone reboots (there is no boot receiver): open the app once after a reboot.
- To keep it alive with the screen off, open **Settings > Keep running in background** and set OpenSMS to *Unrestricted / Don't optimise*.
  Some manufacturers (Xiaomi, Huawei, Samsung, OnePlus, ...) add their own "auto-start / app launch / sleeping apps" switches: allow OpenSMS there too.
- *Force stop* in Android settings kills the service and Android does not restart it until you open the app again.
- Sideloaded installs are not affected by Play's review of `specialUse`; a Play Store release would need a declared justification.

## In-app updates
The updater downloads the APK from `https://github.com/ShanudhaTirosh/OpenSMS/releases` (the `UPDATE_REPO` setting), verifies its
published SHA-256 when one exists, and installs it with Android's `PackageInstaller`: Android shows its own confirmation screen, and
the first time you must allow OpenSMS under *Install unknown apps*. The update only installs over an app signed with the **same key**.

## Testing without a release key
Debug builds are for testing only. `build-apk.yml` (Actions > Build OpenSMS APK > Run workflow, or any push) uploads a debug APK artifact.
Its debug signing key is cached between runs, so each new test build installs **over** the previous one with your data intact. If a build
ever refuses to install over an old one (for instance the cache expired after a week without builds), uninstall once and reinstall.
A debug build cannot be upgraded to a release-signed build or the other way round without uninstalling.

## Ports, permissions, services
| Item | Value |
|---|---|
| Listening port | `9292` (changeable in Settings); address depends on the listening mode |
| Permissions | `INTERNET`, `SEND_SMS`, `READ_PHONE_STATE` (list SIMs / route by SIM), `ACCESS_NETWORK_STATE` (detect the Tailscale VPN), `WAKE_LOCK`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE` (no-timeout background service), `POST_NOTIFICATIONS`, `REQUEST_INSTALL_PACKAGES` (updater) |
| Foreground service | `opensmssvc` (`app/services/appSvc.py`) runs the API |
| External services | GitHub (update check), optionally Tailscale (separate app) |

## Creating the release signing key (once)
```
keytool -genkeypair -v -keystore release.keystore -alias opensms -keyalg RSA -keysize 4096 -validity 10000
base64 -w0 release.keystore            # paste into the ANDROID_KEYSTORE_B64 secret
```
Add four repository secrets: `ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`.
Back the keystore up offline. Never commit it (`*.keystore` is git-ignored).

## Releasing
1. Update `app/app_version.py` (single source for the version) and `CHANGELOG.md`.
2. Merge to `main`, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. `release.yml` checks that the tag equals the version, runs the tests, signs, and publishes `*.apk` and `*.apk.sha256`.
4. Verify: download the APK, `sha256sum` it against the `.sha256`, and check the signer with `apksigner verify --print-certs`.
   The certificate fingerprint must be identical to the previous release. If it differs, do not announce the release.
5. Install it over the previous version on a test phone before telling anyone.

Without signing secrets the release job fails on purpose. A manual run with `allow_debug_signed` publishes a debug-signed
**pre-release** that cannot update a release-signed install.

## Database and migrations
SQLite lives in the app's private storage (`config/opensms.db`). On start the schema is upgraded in place with
`PRAGMA user_version` (currently v2; changes so far only **add** tables/columns). A database written by a newer
app version is refused instead of modified. Upgrades are forward-only.

## Rollback
Android refuses to install an APK with a lower version code over a newer one, and uninstalling deletes the data.
- **Preferred:** publish a new, higher version that contains the previous code (revert the commit, bump the version, tag).
- **Last resort:** uninstall (message history and keys are lost), then install the older APK. The older 0.4.0 app can
  open a v2 database (the changes are additive) but has none of the fixes.
- A bad update can also be stopped before users see it: delete the GitHub release; the in-app updater only offers the latest release.

## Pins
`app/requirements-core.txt` holds exact versions, `app/constraints.txt` the full tested freeze, and `app/buildozer.spec`
repeats the pins for the APK (a test fails if they disagree). KivyMD and the python-for-android fork are pinned by commit.
Update them deliberately: change the pin, run the tests, `pip-audit`, then build and test on a phone.
