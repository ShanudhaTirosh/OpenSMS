import os
import re
import sys
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
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        Download the APK in chunks with progress reporting.
        progress_callback(percent: float, downloaded_bytes: int, total_bytes: int)
        """
        if not apk_url:
            return {"success": False, "error": "No APK download URL provided."}

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
                            downloaded += len(chunk)
                            if total_size > 0 and progress_callback:
                                percent = (downloaded / total_size) * 100.0
                                progress_callback(percent, downloaded, total_size)

                # Atomically replace completed download
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.replace(tmp_path, dest_path)

            return {
                "success": True,
                "file_path": dest_path,
                "size": downloaded
            }
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return {"success": False, "error": f"Download failed: {str(e)}"}

    @staticmethod
    def install_apk(apk_path: str) -> Dict[str, Any]:
        """
        Trigger native Android Package Installer for the downloaded APK.
        Falls back to opening GitHub release page or file location on desktop.
        """
        if not os.path.exists(apk_path):
            return {"success": False, "error": f"File not found: {apk_path}"}

        if platform == "android":
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
                return {"success": False, "error": f"Could not launch installer: {e}"}
        else:
            import webbrowser
            webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases")
            return {
                "success": True,
                "message": f"Desktop simulation: update package saved at {apk_path}"
            }
