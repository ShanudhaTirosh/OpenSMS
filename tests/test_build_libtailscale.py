import importlib.util, re, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_libtailscale", ROOT / "tools" / "build_libtailscale.py")
B = importlib.util.module_from_spec(spec); sys.modules["build_libtailscale"] = B; spec.loader.exec_module(B)


def test_android_plan_for_arm64():
    cmd, env = B.plan_android_build(Path("/ndk"), "arm64-v8a", Path("out"), {"PATH": "x"})
    assert env["GOOS"] == "android" and env["GOARCH"] == "arm64" and env["CGO_ENABLED"] == "1" and "GOARM" not in env
    assert env["CC"] == "/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang" and env["PATH"] == "x"
    assert cmd[:4] == ["go", "build", "-trimpath", "-buildmode=c-shared"] and cmd[-1] == "." and cmd[-2].endswith("arm64-v8a/libtailscale.so")
    assert "max-page-size=16384" in cmd[cmd.index("-ldflags") + 1]                       # 16 KB page-size devices

def test_android_plan_for_armv7_sets_goarm():
    cmd, env = B.plan_android_build(Path("/ndk"), "armeabi-v7a", Path("out"))
    assert env["GOARCH"] == "arm" and env["GOARM"] == "7" and env["CC"].endswith("armv7a-linux-androideabi24-clang")

def test_min_api_matches_the_build_spec():
    spec_text = (ROOT / "app" / "buildozer.spec").read_text()
    assert re.search(rf"^android\.minapi\s*=\s*{B.API_LEVEL}\s*$", spec_text, re.M)

def test_pin_is_consistent_everywhere():
    assert re.fullmatch(r"[0-9a-f]{40}", B.PINNED_COMMIT)
    assert B.PINNED_COMMIT in (ROOT / "app" / "native" / "README.md").read_text()
    for wf in ("build-apk.yml", "release.yml", "ci.yml"):
        assert B.PINNED_COMMIT in (ROOT / ".github" / "workflows" / wf).read_text(), wf

BASE = "[app]\nandroid.minapi = 24\nandroid.add_src = java_src\nandroid.allow_backup = False\n"

def test_enable_spec_adds_only_existing_abis_and_is_idempotent():
    both = B.enable_spec_text(BASE, ["arm64-v8a", "armeabi-v7a"])
    assert "android.add_libs_arm64_v8a = native/arm64-v8a/*.so" in both and "android.add_libs_armeabi_v7a = native/armeabi-v7a/*.so" in both
    assert B.enable_spec_text(both, ["arm64-v8a", "armeabi-v7a"]) == both
    only64 = B.enable_spec_text(both, ["arm64-v8a"])
    assert "armeabi_v7a" not in only64 and "arm64_v8a" in only64
    none = B.enable_spec_text(both, [])
    assert "add_libs" not in none and "Built-in Tailscale" not in none and none.count("\n\n\n") == 0
    assert "android.add_src = java_src" in none and "android.allow_backup = False" in none      # nothing else touched

def test_the_committed_spec_has_no_native_lines_so_a_plain_checkout_builds():
    assert "add_libs" not in (ROOT / "app" / "buildozer.spec").read_text().replace("#android.add_libs", "")

def test_header_check(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "tailscale.h").write_bytes(B.HEADER.read_bytes())
    B.verify_header(src)                                                                   # identical: fine
    (src / "tailscale.h").write_text(B.HEADER.read_text() + "\nextern int tailscale_new_thing(int);\n")
    with pytest.raises(SystemExit, match="differs"):
        B.verify_header(src)
    with pytest.raises(SystemExit, match="not found"):
        B.verify_header(tmp_path / "nowhere")

def test_abis_with_library(tmp_path):
    (tmp_path / "arm64-v8a").mkdir(); (tmp_path / "arm64-v8a" / "libtailscale.so").write_bytes(b"x")
    (tmp_path / "armeabi-v7a").mkdir()
    assert B.abis_with_library(tmp_path) == ["arm64-v8a"]

def test_missing_compiler_is_skipped_not_fatal(tmp_path, monkeypatch):
    src = tmp_path / "src"; src.mkdir(); (src / "tailscale.h").write_bytes(B.HEADER.read_bytes())
    assert B.build_android(src, tmp_path / "out", tmp_path / "no-ndk", ["arm64-v8a"]) == []

def test_enable_spec_command_roundtrip(tmp_path):
    spec = tmp_path / "buildozer.spec"; spec.write_text(BASE)
    native = tmp_path / "native"; (native / "arm64-v8a").mkdir(parents=True); (native / "arm64-v8a" / "libtailscale.so").write_bytes(b"x")
    assert B.main(["enable-spec", "--spec", str(spec), "--native", str(native)]) == 0
    assert "native/arm64-v8a/*.so" in spec.read_text()
