"""
Unit tests for app/patch_p4a.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from patch_p4a import patch_p4a, FILE_PROVIDER_XML


def test_patch_p4a_manifest_injection(tmp_path):
    p4a_dir = tmp_path / "python-for-android"
    tmpl_dir = p4a_dir / "pythonforandroid" / "bootstraps" / "_sdl_common" / "build" / "templates"
    tmpl_dir.mkdir(parents=True)
    tmpl_file = tmpl_dir / "AndroidManifest.tmpl.xml"

    dummy_content = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:label="test">
        <activity android:name="MainActivity" />
    </application>
</manifest>
"""
    tmpl_file.write_text(dummy_content, encoding="utf-8")

    patch_p4a(str(p4a_dir))

    result = tmpl_file.read_text(encoding="utf-8")
    assert "androidx.core.content.FileProvider" in result
    assert "{{ args.package }}.fileprovider" in result
    assert "@xml/file_paths" in result
    assert "</application>" in result

    # Running a second time should be idempotent
    patch_p4a(str(p4a_dir))
    assert result.count("androidx.core.content.FileProvider") == 1
