import os
# Tests run on Linux: allow the (otherwise disabled) simulated SMS provider. Nothing is ever sent.
os.environ.setdefault("OPENSMS_ALLOW_SIMULATION", "1")
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("KIVY_WINDOW", "mock")
