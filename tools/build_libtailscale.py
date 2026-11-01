#!/usr/bin/env python3
"""
Build libtailscale (https://github.com/tailscale/libtailscale) for the built-in Tailscale engine.

    build_libtailscale.py android --src <checkout> --out app/native --ndk $ANDROID_NDK_LATEST_HOME
    build_libtailscale.py host    --src <checkout> --out native-host [--with-testcontrol]
    build_libtailscale.py enable-spec --spec app/buildozer.spec --native app/native

* `android` builds arm64-v8a and armeabi-v7a with Go + the NDK's clang (cgo, c-shared). A failing ABI is reported
  and skipped; the exit status is non-zero only if NOTHING was built.
* `enable-spec` adds `android.add_libs_<abi>` lines to buildozer.spec for the ABIs whose library exists, so a plain
  checkout (without the libraries) still builds an APK without the engine.
* The header of the checkout must equal app/native/tailscale.h: the Python binding is written against it.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

PINNED_COMMIT = "d1dc45d039edb7759ecbee6ba2aea0c4bca884b8"
ROOT = Path(__file__).resolve().parent.parent
HEADER = ROOT / "app" / "native" / "tailscale.h"
API_LEVEL = 24                         # = android.minapi in buildozer.spec
# Android 15+ devices may use 16 KB pages: shared objects must be aligned for that (NDK < r28 defaults to 4 KB)
LDFLAGS = "-s -w -extldflags=-Wl,-z,max-page-size=16384"

ABIS = {
    "arm64-v8a": {"goarch": "arm64", "clang": "aarch64-linux-android{api}-clang", "extra_env": {}},
    "armeabi-v7a": {"goarch": "arm", "clang": "armv7a-linux-androideabi{api}-clang", "extra_env": {"GOARM": "7"}},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_header(src: Path) -> None:
    theirs = src / "tailscale.h"
    if not theirs.exists():
        raise SystemExit(f"{theirs} not found: is --src a libtailscale checkout?")
    if sha256(theirs) != sha256(HEADER):
        raise SystemExit("tailscale.h in the checkout differs from app/native/tailscale.h. The Python binding "
                         "(app/services/tsNative.py) was written against the pinned header: review the change, update "
                         "SIGNATURES and the header copy, then re-run.")


def ndk_clang(ndk: Path, abi: str, api: int = API_LEVEL) -> Path:
    name = ABIS[abi]["clang"].format(api=api)
    return ndk / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin" / name


def plan_android_build(ndk: Path, abi: str, out_dir: Path, base_env: Optional[Dict[str, str]] = None, api: int = API_LEVEL):
    """(command, env) for one ABI. Pure: nothing is executed."""
    spec = ABIS[abi]
    env = dict(base_env or {})
    env.update({"CGO_ENABLED": "1", "GOOS": "android", "GOARCH": spec["goarch"], "CC": ndk_clang(ndk, abi, api).as_posix()})
    env.update(spec["extra_env"])
    cmd = ["go", "build", "-trimpath", "-buildmode=c-shared", "-ldflags", LDFLAGS,
           "-o", (out_dir / abi / "libtailscale.so").as_posix(), "."]
    return cmd, env


def run(cmd: List[str], env: Dict[str, str], cwd: Path) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, env=env).returncode


def build_android(src: Path, out: Path, ndk: Path, abis: List[str]) -> List[str]:
    verify_header(src)
    built = []
    for abi in abis:
        clang = ndk_clang(ndk, abi)
        if not clang.exists():
            print(f"[{abi}] skipped: compiler not found at {clang}", file=sys.stderr)
            continue
        (out / abi).mkdir(parents=True, exist_ok=True)
        cmd, env = plan_android_build(ndk, abi, out, dict(os.environ))
        if run(cmd, env, src) == 0 and (out / abi / "libtailscale.so").exists():
            size = (out / abi / "libtailscale.so").stat().st_size
            print(f"[{abi}] built libtailscale.so ({size / 1048576:.1f} MB)")
            built.append(abi)
        else:
            print(f"[{abi}] FAILED to build", file=sys.stderr)
    return built


def build_host(src: Path, out: Path, with_testcontrol: bool) -> int:
    verify_header(src)
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CGO_ENABLED="1")
    rc = run(["go", "build", "-buildmode=c-shared", "-o", str(out / "libtailscale.so"), "."], env, src)
    if rc == 0 and with_testcontrol:
        rc = run(["go", "build", "-buildmode=c-shared", "-o", str(out / "libtstestcontrol.so"), "./tstestcontrol"], env, src)
    return rc


_BLOCK_RE = re.compile(r"\n*# Built-in Tailscale engine \(added by tools/build_libtailscale\.py[^\n]*\n(?:android\.add_libs_\w+\s*=[^\n]*\n?)*")
_ADD_RE = re.compile(r"^(#\s*)?android\.add_libs_(arm64_v8a|armeabi_v7a)\s*=.*\n?", re.M)


def enable_spec_text(spec_text: str, abis_present: List[str]) -> str:
    """Return the spec with android.add_libs_<abi> lines for exactly the given ABIs (idempotent)."""
    spec_text = _BLOCK_RE.sub("\n", spec_text)          # our earlier block, comment included
    spec_text = _ADD_RE.sub("", spec_text)              # any hand-written line
    spec_text = re.sub(r"\n{3,}", "\n\n", spec_text).rstrip("\n") + "\n"
    if not abis_present:
        return spec_text
    lines = ["", "# Built-in Tailscale engine (added by tools/build_libtailscale.py; absent in a plain checkout)"]
    for abi in abis_present:
        lines.append(f"android.add_libs_{abi.replace('-', '_')} = native/{abi}/*.so")
    block = "\n".join(lines) + "\n"
    marker = re.search(r"^android\.add_src\s*=.*$", spec_text, re.M)
    if marker:                                           # keep it next to the other android.* native settings
        end = marker.end()
        return spec_text[:end] + "\n" + block.rstrip("\n") + spec_text[end:]
    return spec_text + block


def abis_with_library(native: Path) -> List[str]:
    return [abi for abi in ABIS if (native / abi / "libtailscale.so").exists()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("android"); a.add_argument("--src", required=True); a.add_argument("--out", required=True)
    a.add_argument("--ndk", required=True); a.add_argument("--abis", nargs="*", default=list(ABIS))
    h = sub.add_parser("host"); h.add_argument("--src", required=True); h.add_argument("--out", required=True)
    h.add_argument("--with-testcontrol", action="store_true")
    e = sub.add_parser("enable-spec"); e.add_argument("--spec", required=True); e.add_argument("--native", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "android":
        built = build_android(Path(args.src), Path(args.out), Path(args.ndk), args.abis)
        print("BUILT_ABIS=" + ",".join(built))
        return 0 if built else 1
    if args.cmd == "host":
        return build_host(Path(args.src), Path(args.out), args.with_testcontrol)
    spec = Path(args.spec)
    present = abis_with_library(Path(args.native))
    spec.write_text(enable_spec_text(spec.read_text(), present))
    print("ENABLED_ABIS=" + ",".join(present))
    return 0


if __name__ == "__main__":
    sys.exit(main())
