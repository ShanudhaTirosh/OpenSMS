"""Load buildozer.spec with the real buildozer library (runs only where buildozer is installed, e.g. the build workflow)."""
import shutil, sys
from pathlib import Path
import pytest

buildozer = pytest.importorskip("buildozer")
APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))


@pytest.fixture()
def bz(tmp_path):
    # buildozer creates .buildozer/ and bin/ next to the spec, so work on a copy
    shutil.copy(APP / "buildozer.spec", tmp_path / "buildozer.spec")
    shutil.copy(APP / "app_version.py", tmp_path / "app_version.py")
    import os
    old = os.getcwd(); os.chdir(tmp_path)
    try:
        b = buildozer.Buildozer(str(tmp_path / "buildozer.spec"), "android")
        yield b
    finally:
        os.chdir(old)


def test_spec_is_valid_and_version_is_read_from_app_version(bz):
    from app_version import __version__
    bz.check_configuration_tokens()
    assert bz.get_version() == __version__


def test_service_and_permissions_as_intended(bz):
    cfg = bz.config
    opts = cfg.get("app", "services").split(":")
    assert opts[0] == "opensmssvc" and "sticky" in opts and "foregroundServiceType=specialUse" in opts
    perms = {p.strip().split(".")[-1] for p in cfg.get("app", "android.permissions").split(",")}
    assert {"SEND_SMS", "READ_PHONE_STATE", "ACCESS_NETWORK_STATE", "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_SPECIAL_USE",
            "INTERNET", "WAKE_LOCK"} <= perms
    assert "FOREGROUND_SERVICE_DATA_SYNC" not in perms


def test_requirements_are_pinned_and_consistent(bz):
    reqs = [r.strip() for r in bz.config.get("app", "requirements").replace("\n", "").split(",") if r.strip()]
    pins = {r.split("==")[0].lower(): r.split("==")[1] for r in reqs if "==" in r}
    assert pins["fastapi"] == "0.162.0" and pins["starlette"] == "1.9.0" and pins["pydantic"] == "2.12.3"
    assert any("KivyMD/archive/" in r and r.endswith(".zip") and "master" not in r for r in reqs)
    assert "kivy" in {r.lower() for r in reqs} or any(r.lower().startswith("kivy") for r in reqs)
