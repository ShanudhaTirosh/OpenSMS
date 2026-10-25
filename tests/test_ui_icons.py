"""Every icon name used by the UI must exist in the bundled KivyMD icon font (a missing one renders blank)."""
import re, sys
from pathlib import Path
import pytest

md = pytest.importorskip("kivymd.icon_definitions")
APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))


def used_icons():
    names = set()
    files = list(APP.glob("screens/*.py")) + [APP / "services" / "uiFormat.py", APP / "main_layout.kv", APP / "main.py"]
    for f in files:
        t = f.read_text(encoding="utf-8")
        names |= set(re.findall(r'\bicon(?:_color)?\s*[:=]\s*["\']([a-z0-9-]+)["\']', t)) - {"green", "red", "blue", "white"}
        names |= set(re.findall(r'icon="([a-z0-9-]+)"', t))
    from services.uiFormat import STATUS_STYLE
    names |= {v[1] for v in STATUS_STYLE.values()}
    return names


def test_all_icons_exist():
    missing = sorted(n for n in used_icons() if n not in md.md_icons)
    assert not missing, f"unknown icon names: {missing}"
