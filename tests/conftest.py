import os
# Tests run on Linux: allow the (otherwise disabled) simulated SMS provider. Nothing is ever sent.
os.environ.setdefault("OPENSMS_ALLOW_SIMULATION", "1")
