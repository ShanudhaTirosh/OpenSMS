# Testing

## Automated (no phone needed)
```
python -m venv .venv && . .venv/bin/activate
pip install -r app/requirements.txt pytest httpx
python -m pytest tests -q
```
`tests/conftest.py` enables the simulated SMS provider; nothing is ever sent. Tests are grouped by audit stage
(`test_security_stage2.py`, `test_stage3_api.py`, `test_stage4_sms.py`, `test_stage5_tailscale.py`,
`test_stage6_ui_logic.py`, `test_stage8_ipc.py`, `test_stage9_outbox.py`). `test_ui_icons.py` runs only when KivyMD is installed.

## Headless UI walkthrough (screenshots)
`tools/ui_walkthrough.py` launches the real app under a virtual display, seeds sample data and drives the Messages
and API screens. See the file header for setup. It proves the screens build, render in light/dark themes and that
their handlers work; it is not a substitute for testing on a phone.

## On a device
`docs/device-test-plan.md` lists the checks that only a real phone/SIM/tailnet can answer (SMS receipts, Android 14
behaviour, VPN detection, Tailscale-only listening, updater).
