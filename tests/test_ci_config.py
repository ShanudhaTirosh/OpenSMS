"""Static checks of the CI/release configuration (cannot run the workflows here, so guard what can be checked)."""
import re
from pathlib import Path
import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parent.parent
WF = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
APP = ROOT / "app"


def load(p):
    return yaml.safe_load(p.read_text())


def run_scripts(doc):
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            if "run" in step:
                yield step["run"]


def test_workflows_parse_and_have_explicit_permissions():
    assert {p.name for p in WF} >= {"ci.yml", "build-apk.yml", "release.yml"}
    for p in WF:
        doc = load(p)
        assert "permissions" in doc, f"{p.name}: set explicit permissions"
        assert doc["jobs"], p.name


def test_no_untrusted_expression_interpolated_into_shell():
    bad = re.compile(r"\$\{\{\s*(github\.event\.|github\.head_ref|github\.ref_name|inputs\.)")
    for p in WF:
        for script in run_scripts(load(p)):
            assert not bad.search(script), f"{p.name}: pass untrusted values through env:, not into run:\n{script[:200]}"


def test_release_requires_signing_and_validates_tag():
    text = (ROOT / ".github/workflows/release.yml").read_text()
    doc = load(ROOT / ".github/workflows/release.yml")
    steps = [s.get("name", "") for s in doc["jobs"]["release"]["steps"]]
    assert "Check signing configuration" in steps and "Determine and validate tag" in steps
    assert "exit 1" in text and "ANDROID_KEYSTORE_B64" in text
    assert "buildozer android release" in text
    assert "^v[0-9]+\\.[0-9]+\\.[0-9]+$" in text                      # tag format
    assert "app/app_version.py" in text                                # tag must equal the app version
    assert ".sha256" in text                                           # checksum published for the updater
    # the only debug build is the explicitly allowed pre-release path
    debug_steps = [s for s in doc["jobs"]["release"]["steps"] if "buildozer android debug" in s.get("run", "")]
    assert len(debug_steps) == 1 and "!= 'true'" in debug_steps[0]["if"]
    assert doc["jobs"]["release"]["steps"][-1]["with"]["prerelease"].startswith("${{ steps.signing.outputs.signed != 'true'")


def test_p4a_fork_is_pinned_to_a_commit_everywhere():
    for name in ("build-apk.yml", "release.yml"):
        text = (ROOT / ".github/workflows" / name).read_text()
        assert re.search(r"P4A_FORK_REF:\s*[0-9a-f]{40}\b", text), name
        assert "-b develop" not in text, name


def test_release_artifact_is_apk_and_backup_is_off():
    spec = (APP / "buildozer.spec").read_text()
    assert re.search(r"^android\.release_artifact\s*=\s*apk\s*$", spec, re.M)
    assert re.search(r"^android\.allow_backup\s*=\s*False\s*$", spec, re.M)
    assert re.search(r"^android\.add_src\s*=\s*java_src\s*$", spec, re.M)


def parse_pins(text):
    pins = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([0-9][^\s,;#]*)", line.strip())
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_pins_agree_between_requirements_constraints_and_buildozer():
    core = parse_pins((APP / "requirements-core.txt").read_text())
    cons = parse_pins((APP / "constraints.txt").read_text())
    spec = parse_pins((APP / "buildozer.spec").read_text())
    assert core["pydantic"] == "2.12.3" and core["pydantic-core"] == "2.41.4"
    for name, ver in core.items():
        assert cons.get(name) == ver, f"constraints.txt disagrees on {name}"
    for name in ("fastapi", "starlette", "uvicorn", "pydantic", "annotated-doc", "opentelemetry-api"):
        assert spec.get(name) == core[name], f"buildozer.spec disagrees on {name}: {spec.get(name)} vs {core[name]}"
    # the local pydantic-core recipe must declare exactly the pinned version
    recipe = (APP / "p4a_local_recipes/pydantic-core/__init__.py").read_text()
    m = re.search(r"version\s*=\s*['\"]([0-9.]+)['\"]", recipe)
    assert m and m.group(1) == core["pydantic-core"], f"recipe declares {m and m.group(1)}"


def test_kivymd_is_pinned_by_commit():
    for f in ("requirements.txt", "buildozer.spec"):
        text = (APP / f).read_text()
        assert "KivyMD/archive/master.zip" not in text, f
        assert re.search(r"KivyMD/archive/[0-9a-f]{40}\.zip", text), f


def test_debug_builds_keep_a_stable_signature():
    text = (ROOT / ".github/workflows/build-apk.yml").read_text()
    assert "~/.android" in text and "debug-keystore" in text      # otherwise test builds cannot update each other
