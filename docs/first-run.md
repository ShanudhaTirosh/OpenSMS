# First run: from this change set to a tested APK on your phone

Everything below the "Prepare" step is what has **never been executed** yet. Take it one step at a time and stop at the first surprise.

## 1. Prepare the repository (`ShanudhaTirosh/OpenSMS`)
1. Create a branch: `git checkout -b audit-fixes`.
2. Copy the contents of the delivered `OpenSMS-final.zip` (folder `OpenSMS-main`) over your working copy. Delete `app/services/postFlask.py` if it is still there.
3. `git add -A && git commit -m "Audit fixes: security, SMS lifecycle, Tailscale, UI, CI"` and `git push -u origin audit-fixes`.
4. Open a pull request. The **CI** workflow (lint, tests on Python 3.11/3.12, dependency audit, headless UI test, buildozer spec check) should go green. If a job fails, open its log first: the tests passed in the environment where they were written, so a failure is most likely an environment difference.

## 2. Build a test APK (no signing key needed)
1. Actions > **Build OpenSMS APK** > Run workflow on the branch (or just push). The first build takes a long time (it downloads the Android SDK/NDK).
2. If it fails, the first suspects are `app/java_src/*.java` (SMS receipt and installer receivers), the new pinned requirements, and the python-for-android commit. Copy the failing step's log.
3. Download the APK artifact. Debug builds share one cached signing key, so later test builds install over each other. The artifact is a **debug** build: never publish it as a release.

## 3. Install and set up on the phone
1. Install the APK (allow "Install unknown apps" for your browser/file manager).
2. Open OpenSMS and allow **SMS**, **Phone** and **Notifications** when asked.
3. Settings > **Keep running in background**: set OpenSMS to *Unrestricted / Don't optimise*. Allow auto-start/background activity if your phone maker has a separate switch.
4. API tab > **New key** (Send + Read). Copy it when it is shown: it is never shown again.
5. Home > **Start Server**. Use the System screen (menu) to confirm everything is green.

## 4. First smoke test (5 minutes, uses your own number)
1. From another device on the same Wi-Fi: `curl -X POST http://<phone-ip>:9292/sms/ -H "Authorization: Bearer <key>" -H "Content-Type: application/json" -d '{"number":"+<your number>","text":"hello"}'`. Expect `200`, `status: submitted`, and an SMS arriving on your number.
2. Messages tab: the message goes Submitted > Sent (and Delivered only if your carrier sends delivery reports).
3. Close the app and swipe it away: the notification stays and the same `curl` still works.
4. Messages tab > new-message button: send one from the app.

## 5. Then work through `device-test-plan.md`
Sections 1 (SMS), 7 (System), 5 (background, including an overnight run on Android 15+), 4 (Tailscale), 6 (updater). Note each result; send me anything that fails, with the System screen's **Copy report** text and, for crashes, `adb logcat -b crash`.

## 6. When you want a real release
Create the signing key and the four repository secrets (see `deployment.md`), bump `app/app_version.py`, tag `vX.Y.Z`. Do not release before sections 1, 5 and 6 pass on your phone.
