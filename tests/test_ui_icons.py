import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "offscreen")

try:
    from kivy.base import EventLoop
    if not getattr(EventLoop, "window", None):
        mock_win = MagicMock()
        mock_win.size = (800, 600)
        mock_win.width = 800
        mock_win.height = 600
        mock_win.dpi = 96
        mock_win.density = 1.0
        mock_win.children = []
        EventLoop.window = mock_win
        EventLoop.ensure_window = lambda *args, **kwargs: None
except Exception:
    pass

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
