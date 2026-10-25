"""Stage 7/8: updater trust + checksum, single version source."""
import hashlib, re, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from services import updateMgr as um
from services.updateMgr import UpdateManager, is_trusted_download_url

REPO = um.GITHUB_REPO
GOOD = f"https://github.com/{REPO}/releases/download/v9.9.9/OpenSMS-arm64.apk"


@pytest.mark.parametrize("url,ok", [
    (GOOD, True),
    (GOOD.upper().replace("HTTPS", "https"), True),             # host and owner/repo are case-insensitive
    (f"http://github.com/{REPO}/releases/download/v1/a.apk", False),                 # not https
    (f"https://github.com.evil.example/{REPO}/releases/download/v1/a.apk", False),    # look-alike host
    (f"https://evil.example/{REPO}/releases/download/v1/a.apk", False),
    ("https://github.com/someone-else/OpenSMS/releases/download/v1/a.apk", False),   # another repository
    (f"https://github.com/{REPO}/archive/main.zip", False),                           # not a release asset
    (f"https://user:pw@github.com/{REPO}/releases/download/v1/a.apk", False),         # embedded credentials
    (f"https://github.com:8443/{REPO}/releases/download/v1/a.apk", False),            # unusual port
    (f"https://github.com:443/{REPO}/releases/download/v1/a.apk", True),
    ("", False), (None, False), ("not a url", False), ("file:///sdcard/a.apk", False),
])
def test_trusted_download_url(url, ok):
    assert is_trusted_download_url(url) is ok


class FakeResp:
    def __init__(self, status=200, payload=None, chunks=(), text=""):
        self.status_code, self._payload, self._chunks, self.text = status, payload, chunks, text
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}
    def json(self): return self._payload
    def raise_for_status(self): pass
    def iter_content(self, chunk_size=0): return iter(self._chunks)
    def __enter__(self): return self
    def __exit__(self, *a): return False


def release(assets):
    return {"tag_name": "v9.9.9", "name": "x", "body": "notes", "html_url": "u", "published_at": "t", "assets": assets}


def asset(name, url=None, digest=None, size=10):
    a = {"name": name, "browser_download_url": url or f"https://github.com/{REPO}/releases/download/v9.9.9/{name}", "size": size}
    if digest: a["digest"] = digest
    return a


SHA = "ab" * 32


def test_update_check_uses_github_digest(monkeypatch):
    monkeypatch.setattr(um.requests, "get", lambda *a, **k: FakeResp(payload=release([asset("OpenSMS.apk", digest="sha256:" + SHA)])))
    r = UpdateManager.check_for_updates("0.4.0")
    assert r["has_update"] and r["apk_url"].endswith("OpenSMS.apk") and r["apk_sha256"] == SHA

def test_update_check_falls_back_to_sidecar(monkeypatch):
    payload = release([asset("OpenSMS.apk"), asset("OpenSMS.apk.sha256")])
    def fake_get(url, **k):
        return FakeResp(text=f"{SHA}  OpenSMS.apk\n") if url.endswith(".sha256") else FakeResp(payload=payload)
    monkeypatch.setattr(um.requests, "get", fake_get)
    assert UpdateManager.check_for_updates("0.4.0")["apk_sha256"] == SHA

def test_update_check_without_checksum_reports_none(monkeypatch):
    monkeypatch.setattr(um.requests, "get", lambda *a, **k: FakeResp(payload=release([asset("OpenSMS.apk")])))
    assert UpdateManager.check_for_updates("0.4.0")["apk_sha256"] is None

def test_update_check_drops_untrusted_asset_url(monkeypatch):
    bad = asset("OpenSMS.apk", url="https://evil.example/OpenSMS.apk", digest="sha256:" + SHA)
    monkeypatch.setattr(um.requests, "get", lambda *a, **k: FakeResp(payload=release([bad])))
    r = UpdateManager.check_for_updates("0.4.0")
    assert r["success"] and r["apk_url"] is None

def test_malformed_digest_is_ignored(monkeypatch):
    monkeypatch.setattr(um.requests, "get", lambda *a, **k: FakeResp(payload=release([asset("OpenSMS.apk", digest="sha256:nothex")])))
    assert UpdateManager.check_for_updates("0.4.0")["apk_sha256"] is None


def test_download_verifies_checksum(monkeypatch, tmp_path):
    data = [b"abc" * 1000, b"def" * 500]
    good = hashlib.sha256(b"".join(data)).hexdigest()
    monkeypatch.setattr(um.requests, "get", lambda *a, **k: FakeResp(chunks=data))
    dest = tmp_path / "u.apk"
    r = UpdateManager.download_apk(GOOD, str(dest), expected_sha256="sha256:" + good)
    assert r["success"] and r["verified"] is True and r["sha256"] == good and dest.exists()

def test_download_rejects_wrong_checksum_and_leaves_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(um.requests, "get", lambda *a, **k: FakeResp(chunks=[b"tampered"]))
    dest = tmp_path / "u.apk"
    r = UpdateManager.download_apk(GOOD, str(dest), expected_sha256=SHA)
    assert not r["success"] and "Checksum mismatch" in r["error"]
    assert not dest.exists() and not Path(str(dest) + ".tmp").exists()

def test_download_without_checksum_is_flagged_unverified(monkeypatch, tmp_path):
    monkeypatch.setattr(um.requests, "get", lambda *a, **k: FakeResp(chunks=[b"data"]))
    r = UpdateManager.download_apk(GOOD, str(tmp_path / "u.apk"))
    assert r["success"] and r["verified"] is False

def test_download_refuses_untrusted_url_without_touching_network(monkeypatch, tmp_path):
    def boom(*a, **k): raise AssertionError("network must not be used")
    monkeypatch.setattr(um.requests, "get", boom)
    r = UpdateManager.download_apk("https://evil.example/a.apk", str(tmp_path / "u.apk"))
    assert not r["success"] and "Refusing" in r["error"]


# ---------------- single version source ----------------
def test_version_has_a_single_source():
    from app_version import __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    spec = (APP / "buildozer.spec").read_text()
    assert "version.filename = %(source.dir)s/app_version.py" in spec
    literal = re.compile(r"""['"]%s['"]""" % re.escape(__version__))
    offenders = [str(p.relative_to(ROOT)) for p in list(APP.glob("*.py")) + list(APP.glob("services/*.py")) + list(APP.glob("screens/*.py"))
                 if p.name != "app_version.py" and literal.search(p.read_text())]
    assert offenders == [], f"version literal duplicated in {offenders}"

def test_api_reports_the_single_version(tmp_path):
    import services.postApi as P
    from app_version import __version__
    from fastapi.testclient import TestClient
    assert TestClient(P.app).get("/health/").json()["version"] == __version__
    assert P.app.version == __version__

def test_removed_dead_flask_module_is_really_unused():
    assert not (APP / "services" / "postFlask.py").exists()
    for p in APP.rglob("*.py"):
        assert "postFlask" not in p.read_text(), p


# ---------------- PackageInstaller path (pure parts + fallback order) ----------------
import pytest as _pytest


@_pytest.mark.parametrize("status,kind", [(0, "success"), (-1, "pending"), (1, "error"), (2, "error"), (3, "error"),
                                          (4, "error"), (5, "error"), (6, "error"), (7, "error"), (8, "error"), (99, "error")])
def test_install_status_kinds(status, kind):
    k, text = um.describe_install_status(status)
    assert k == kind and text

def test_install_conflict_explains_the_signature_problem_and_data_loss():
    _, text = um.describe_install_status(5)
    assert "signed" in text and "Uninstall" in text and "data is lost" in text
    _, blocked = um.describe_install_status(2)
    assert "Settings" in blocked

def test_install_status_message_is_appended_only_for_errors():
    assert "disk quota" in um.describe_install_status(6, " disk quota ")[1]
    assert um.describe_install_status(0, "ignored")[1] == "Update installed."
    assert um.describe_install_status(-1, "ignored")[0] == "pending"

def test_copy_file_to_stream_chunks_and_counts(tmp_path):
    data = bytes(range(256)) * 1000                                    # 256000 bytes
    f = tmp_path / "a.apk"; f.write_bytes(data)
    class Stream:
        def __init__(self): self.calls = []; self.buf = b""
        def write(self, chunk, offset, length):
            assert offset == 0 and length == len(chunk); self.calls.append(length); self.buf += chunk
    s = Stream()
    assert um.copy_file_to_stream(str(f), s, chunk_size=65536) == len(data)
    assert s.buf == data and len(s.calls) == 4 and max(s.calls) <= 65536
    e = tmp_path / "empty.apk"; e.write_bytes(b"")
    s2 = Stream(); assert um.copy_file_to_stream(str(e), s2) == 0 and s2.calls == []

def test_install_apk_falls_back_when_package_installer_fails(monkeypatch, tmp_path):
    f = tmp_path / "a.apk"; f.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(um, "platform", "android")
    def broken(path, cb): calls.append("package_installer"); raise RuntimeError("no jnius here")
    monkeypatch.setattr(um, "_install_via_package_installer", broken)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: calls.append(("browser", url)) or True)
    r = UpdateManager.install_apk(str(f))
    # package installer tried first; the ACTION_VIEW intent path cannot work off-device, so the browser fallback is reached
    assert calls[0] == "package_installer" and calls[-1][0] == "browser"
    assert r["success"] is False and "release page" in r["error"]

def test_install_apk_reports_waiting_when_package_installer_starts(monkeypatch, tmp_path):
    f = tmp_path / "a.apk"; f.write_bytes(b"x")
    seen = []
    monkeypatch.setattr(um, "platform", "android")
    monkeypatch.setattr(um, "_install_via_package_installer", lambda path, cb: seen.append((path, cb)))
    cb = lambda kind, text: None
    r = UpdateManager.install_apk(str(f), on_status=cb)
    assert r["success"] is True and seen == [(str(f), cb)]

def test_install_apk_missing_file(tmp_path):
    assert UpdateManager.install_apk(str(tmp_path / "nope.apk"))["success"] is False


# ---------------- the new Java classes compile (against hand-written Android stubs) ----------------
import shutil, subprocess, tempfile

@_pytest.mark.skipif(shutil.which("javac") is None, reason="no JDK installed")
def test_java_sources_compile_against_android_stubs():
    stubs = {
        "android/content/Context.java": "package android.content; public class Context {}",
        "android/content/Intent.java": """package android.content; public class Intent {
            public static final String EXTRA_INTENT = "android.intent.extra.INTENT";
            public String getAction(){return null;} public String getStringExtra(String n){return null;}
            public int getIntExtra(String n,int d){return d;} public byte[] getByteArrayExtra(String n){return null;}
            public <T> T getParcelableExtra(String n, Class<T> c){return null;} public Object getParcelableExtra(String n){return null;} }""",
        "android/content/BroadcastReceiver.java": "package android.content; public abstract class BroadcastReceiver { public abstract void onReceive(Context c, Intent i); public final int getResultCode(){return 0;} }",
        "android/content/pm/PackageInstaller.java": """package android.content.pm; public class PackageInstaller {
            public static final String EXTRA_STATUS="a"; public static final String EXTRA_STATUS_MESSAGE="b";
            public static final int STATUS_FAILURE=1; public static final int STATUS_PENDING_USER_ACTION=-1; }""",
        "android/os/Build.java": "package android.os; public class Build { public static class VERSION { public static int SDK_INT = 34; } }",
        "android/telephony/SmsMessage.java": "package android.telephony; public class SmsMessage { public static SmsMessage createFromPdu(byte[] p, String f){return null;} public int getStatus(){return 0;} }",
    }
    with tempfile.TemporaryDirectory() as d:
        for rel, src in stubs.items():
            p = Path(d, "stubs", rel); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(src)
        out = Path(d, "out"); out.mkdir()
        sources = [str(p) for p in (APP / "java_src").rglob("*.java")]
        r = subprocess.run(["javac", "-d", str(out), "-sourcepath", str(Path(d, "stubs")), *sources], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        desc = subprocess.run(["javap", "-cp", str(out), "-s", "org.opensms.gateway.InstallResultListener"], capture_output=True, text=True).stdout
        assert "(ILjava/lang/String;Landroid/content/Intent;)V" in desc               # matches @java_method in updateMgr
        desc2 = subprocess.run(["javap", "-cp", str(out), "-s", "org.opensms.gateway.SmsResultListener"], capture_output=True, text=True).stdout
        assert "(Ljava/lang/String;Ljava/lang/String;III)V" in desc2                  # matches @java_method in smsReceipts
