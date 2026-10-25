import os

# Tests run on Linux: allow the (otherwise disabled) simulated SMS provider. Nothing is ever sent.
os.environ.setdefault("OPENSMS_ALLOW_SIMULATION", "1")
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "offscreen")

try:
    from unittest.mock import MagicMock
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
