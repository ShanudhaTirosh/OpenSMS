import hashlib
import os
import re
import sys
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Callable
import requests

try:
    from kivy.utils import platform
except ImportError:
    if sys.platform.startswith("win"):
        platform = "win"
    elif sys.platform.startswith("linux"):
        platform = "linux"
    else:
        platform = "unknown"

try:
    from app_version import UPDATE_REPO as GITHUB_REPO
except ImportError:  # pragma: no cover
    GITHUB_REPO = "ShanudhaTirosh/OpenSMS"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def parse_semver(ver_str: str) -> tuple:
    """Extract (major, minor, patch) integers from a version string like 'v0.3.0' or '0.4.1-beta'."""
    clean = ver_str.strip().lstrip("vV")
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", clean)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3) or 0)
        return (major, minor, patch)
    return (0, 0, 0)

def is_newer_version(current_ver: str, remote_ver: str) -> bool:
    """Returns True if remote_ver is strictly greater than current_ver."""
    return parse_semver(remote_ver) > parse_semver(current_ver)

TRUSTED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")


def is_trusted_download_url(url: str, repo: str = None) -> bool:
    """
    Only https downloads of release assets of the configured repository are accepted. GitHub redirects
    the asset to its CDN, so the CDN hosts are allowed for the redirect target but the URL we are GIVEN
    must be a github.com release-download URL of `repo`.
    """
    repo = repo or GITHUB_REPO
    try:
        u = urlparse(url or "")
    except ValueError:
        return False
    if u.scheme != "https" or (u.hostname or "") != "github.com":
        return False
    try:
        if u.username or u.password or (u.port not in (None, 443)):
            return False   # no embedded credentials, no unusual ports
    except ValueError:
        return False
    return u.path.lower().startswith(f"/{repo.lower()}/releases/download/")


def _clean_sha256(value) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip().lower()
    if value.startswith("sha256:"):
        value = value[7:]
    value = value.split()[0] if value.split() else ""
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else None


# android.content.pm.PackageInstaller.STATUS_* -> (kind, user-facing explanation)
_INSTALL_STATUS = {
    0: ("success", "Update installed."),
    -1: ("pending", "Waiting for your confirmation in the Android install screen."),
    1: ("error", "Android could not install the update."),
    2: ("error", "Android blocked the installation. Allow OpenSMS to install apps in Settings, then try again."),
    3: ("error", "The installation was cancelled."),
    4: ("error", "Android rejected the APK as invalid or corrupt."),
    5: ("error", "The update conflicts with the installed app, usually because it was signed with a different key "
                 "(for example a debug build over a release build). Uninstall OpenSMS and install the new APK; "
                 "local data is lost."),
    6: ("error", "Not enough storage to install the update."),
    7: ("error", "The update is not compatible with this device."),
    8: ("error", "The installation timed out."),
}


def describe_install_status(status: int, message: Optional[str] = None):
    """(kind, text) for a PackageInstaller status code; `kind` is success / pending / error."""
    kind, text = _INSTALL_STATUS.get(int(status), ("error", f"Installation failed (status {status})."))
    if message and kind == "error" and str(message).strip():
        text = f"{text} ({str(message).strip()})"
    return kind, text


def copy_file_to_stream(path: str, stream, chunk_size: int = 65536) -> int:
    """Copy a file into a Java OutputStream-like object (`write(bytes, offset, length)`). Returns bytes written."""
    total = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            stream.write(chunk, 0, len(chunk))
            total += len(chunk)
    return total


_installer = {"listener": None, "receiver": None, "registered": False, "on_status": None}


def _install_via_package_installer(apk_path: str, on_status) -> None:
    """
    Install through android.content.pm.PackageInstaller. Unlike an ACTION_VIEW intent this needs no
    FileProvider (the app reads the file and streams it to the system), so it works with the current manifest.
    The result arrives through org.opensms.gateway.InstallResultReceiver (app/java_src). Device-untested.
    Raises on any setup problem so the caller can fall back.
    """
    from jnius import autoclass, PythonJavaClass, java_method
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Intent = autoclass('android.content.Intent')
    IntentFilter = autoclass('android.content.IntentFilter')
    Context = autoclass('android.content.Context')
    PendingIntent = autoclass('android.app.PendingIntent')
    SessionParams = autoclass('android.content.pm.PackageInstaller$SessionParams')
    Build = autoclass('android.os.Build$VERSION')
    Receiver = autoclass('org.opensms.gateway.InstallResultReceiver')

    activity = PythonActivity.mActivity
    package = activity.getPackageName()
    action = f"{package}.INSTALL_RESULT"
    _installer["on_status"] = on_status

    if not _installer["registered"]:
        class _Listener(PythonJavaClass):
            __javainterfaces__ = ["org/opensms/gateway/InstallResultListener"]
            __javacontext__ = "app"

            @java_method("(ILjava/lang/String;Landroid/content/Intent;)V")
            def onResult(self, status, message, confirm_intent):
                try:
                    kind, text = describe_install_status(int(status), str(message) if message else None)
                    if kind == "pending" and confirm_intent is not None:
                        confirm_intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        PythonActivity.mActivity.startActivity(confirm_intent)
                    cb = _installer["on_status"]
                    if cb:
                        cb(kind, text)
                except Exception as e:      # never let an exception cross into Java
                    print(f"Install result error: {e}")

        listener = _Listener()
        Receiver.setListener(listener)
        receiver = Receiver()
        flt = IntentFilter()
        flt.addAction(action)
        if Build.SDK_INT >= 33:
            activity.registerReceiver(receiver, flt, Context.RECEIVER_NOT_EXPORTED)
        else:
            activity.registerReceiver(receiver, flt)
        _installer.update(listener=listener, receiver=receiver, registered=True)

    installer = activity.getPackageManager().getPackageInstaller()
    session_id = installer.createSession(SessionParams(SessionParams.MODE_FULL_INSTALL))
    session = installer.openSession(session_id)
    try:
        out = session.openWrite("opensms-update.apk", 0, os.path.getsize(apk_path))
        copy_file_to_stream(apk_path, out)
        session.fsync(out)
        out.close()
        intent = Intent(action)
        intent.setPackage(package)
        # FLAG_MUTABLE: the system adds the status extras to this intent
        pending = PendingIntent.getBroadcast(activity, session_id, intent,
                                             PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE)
        session.commit(pending.getIntentSender())
    except Exception:
        session.abandon()
        raise
    finally:
        session.close()


class UpdateManager:
    @staticmethod
    def check_for_updates(current_version: str, timeout: int = 10) -> Dict[str, Any]:
        """
        Query GitHub Releases API and determine if a newer version is available.
        Returns release metadata and APK download URL if found.
        """
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"OpenSMS-App/{current_version}"
        }
        try:
            resp = requests.get(LATEST_RELEASE_API, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                tag_name = data.get("tag_name", "").strip()
                remote_version = tag_name.lstrip("vV")
                has_update = is_newer_version(current_version, remote_version)

                # Search for APK asset
                apk_asset = None
                assets = data.get("assets", [])
                for asset in assets:
                    name = asset.get("name", "").lower()
                    if name.endswith(".apk"):
                        apk_asset = asset
                        # Prefer arm64 or release apk if multiple
                        if "arm64" in name or "release" in name:
                            break

                apk_url = apk_asset.get("browser_download_url") if apk_asset else None
                apk_size = apk_asset.get("size", 0) if apk_asset else 0
                if apk_url and not is_trusted_download_url(apk_url):
                    apk_url = None   # never offer a download outside the configured repository's releases

                # SHA-256: GitHub's asset "digest" field, else a "<apk name>.sha256" sidecar asset
                apk_sha256 = _clean_sha256(apk_asset.get("digest")) if apk_asset else None
                if apk_asset and not apk_sha256:
                    side = next((a for a in assets if a.get("name", "").lower() == apk_asset.get("name", "").lower() + ".sha256"), None)
                    side_url = side.get("browser_download_url") if side else None
                    if side_url and is_trusted_download_url(side_url):
                        try:
                            sr = requests.get(side_url, headers=headers, timeout=timeout)
                            if sr.status_code == 200:
                                apk_sha256 = _clean_sha256(sr.text)
                        except requests.exceptions.RequestException:
                            pass

                return {
                    "success": True,
                    "has_update": has_update,
                    "current_version": current_version,
                    "latest_version": remote_version,
                    "tag_name": tag_name,
                    "release_name": data.get("name") or f"OpenSMS {tag_name}",
                    "release_notes": data.get("body") or "No changelog provided.",
                    "html_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
                    "apk_url": apk_url,
                    "apk_size": apk_size,
                    "apk_sha256": apk_sha256,
                    "published_at": data.get("published_at")
                }
            elif resp.status_code == 404:
                return {"success": False, "error": "No releases found on GitHub."}
            else:
                return {"success": False, "error": f"GitHub API returned HTTP {resp.status_code}."}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Network error checking for updates: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Update check error: {str(e)}"}

    @staticmethod
    def download_apk(
        apk_url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[float, int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        expected_sha256: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Download the APK in chunks with progress reporting.
        progress_callback(percent: float, downloaded_bytes: int, total_bytes: int)
        """
        if not apk_url:
            return {"success": False, "error": "No APK download URL provided."}
        if not is_trusted_download_url(apk_url):
            return {"success": False, "error": "Refusing to download: the URL is not a release asset of the configured repository."}
        expected = _clean_sha256(expected_sha256)
        digest = hashlib.sha256()

        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        tmp_path = dest_path + ".tmp"

        headers = {"User-Agent": "OpenSMS-Downloader"}
        try:
            with requests.get(apk_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_size = int(r.headers.get("content-length", 0))
                downloaded = 0

                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if cancel_check and cancel_check():
                            f.close()
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                            return {"success": False, "error": "Download cancelled by user."}

                        if chunk:
                            f.write(chunk)
                            digest.update(chunk)
                            downloaded += len(chunk)
                            if total_size > 0 and progress_callback:
                                percent = (downloaded / total_size) * 100.0
                                progress_callback(percent, downloaded, total_size)

                actual = digest.hexdigest()
                if expected and actual != expected:
                    f.close()
                    os.remove(tmp_path)
                    return {"success": False, "error": "Checksum mismatch: the downloaded file does not match the published SHA-256, so it was discarded."}

                # Atomically replace completed download
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.replace(tmp_path, dest_path)

            return {
                "success": True,
                "file_path": dest_path,
                "size": downloaded,
                "sha256": actual,
                "verified": bool(expected)   # False = no published checksum was available to compare against
            }
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return {"success": False, "error": f"Download failed: {str(e)}"}

    @staticmethod
    def install_apk(apk_path: str, on_status=None) -> Dict[str, Any]:
        """
        Install the downloaded APK on Android. First choice: PackageInstaller (no FileProvider needed);
        then an ACTION_VIEW intent; finally the release page in the browser. `on_status(kind, text)` is
        called later with the system's result (success / pending / error).
        Desktop: opens the release page.
        """
        if not os.path.exists(apk_path):
            return {"success": False, "error": f"File not found: {apk_path}"}

        if platform == "android":
            try:
                _install_via_package_installer(apk_path, on_status)
                return {"success": True, "message": "Waiting for Android's install confirmation..."}
            except Exception as e:
                print(f"PackageInstaller path failed, trying the install intent: {e}")
            try:
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Intent = autoclass('android.content.Intent')
                Uri = autoclass('android.net.Uri')
                File = autoclass('java.io.File')
                activity = PythonActivity.mActivity
                apk_file = File(apk_path)

                intent = Intent(Intent.ACTION_VIEW)
                # Android 7.0+ (API 24+) requires FileProvider
                VERSION = autoclass('android.os.Build$VERSION')
                if VERSION.SDK_INT >= 24:
                    try:
                        FileProvider = autoclass('androidx.core.content.FileProvider')
                        pkg = activity.getPackageName()
                        content_uri = FileProvider.getUriForFile(
                            activity,
                            f"{pkg}.fileprovider",
                            apk_file
                        )
                    except Exception:
                        content_uri = Uri.fromFile(apk_file)
                else:
                    content_uri = Uri.fromFile(apk_file)

                intent.setDataAndType(content_uri, "application/vnd.android.package-archive")
                intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION)
                activity.startActivity(intent)
                return {"success": True, "message": "Opening package installer..."}
            except Exception as e:
                print(f"Android install intent failed: {e}")
                # Fallback to browser
                import webbrowser
                webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases")
                return {"success": False, "error": (
                    "Could not open the installer automatically, so the release page was opened in your browser. "
                    f"Download and install the APK from there. ({e})")}
        else:
            import webbrowser
            webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases")
            return {
                "success": True,
                "message": f"Desktop simulation: update package saved at {apk_path}"
            }
