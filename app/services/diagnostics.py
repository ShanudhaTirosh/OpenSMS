"""
System diagnostics: turns raw facts about the app, the background service and the phone into sections of
plain-language rows with a level (ok / info / warn / error) and a hint on how to fix problems.
Pure functions (unit tested); the screen gathers the facts. Nothing here ever includes API keys, message text
or phone numbers, so the copied report is safe to paste into a bug report.
"""
from typing import Any, Dict, List, Optional

OK, INFO, WARN, ERROR = "ok", "info", "warn", "error"


def _row(label: str, value: str, level: str = INFO, hint: Optional[str] = None) -> Dict[str, Any]:
    return {"label": label, "value": value, "level": level, "hint": hint}


def _size(n: Optional[int]) -> str:
    if n is None:
        return "unknown"
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / (1024 * 1024):.1f} MB"


def _perm(label: str, granted: Optional[bool], why: str, fix: str) -> Dict[str, Any]:
    if granted is None:
        return _row(label, "Not applicable on this platform", INFO)
    return _row(label, "Granted" if granted else "Not granted", OK if granted else WARN, None if granted else f"{why} {fix}")


def build_sections(f: Dict[str, Any]) -> List[Dict[str, Any]]:
    android = bool(f.get("android"))
    diag = f.get("diag") or {}
    sections: List[Dict[str, Any]] = []

    # ---------------- gateway ----------------
    alive = bool(f.get("service_alive"))
    age = f.get("heartbeat_age")
    gw = []
    if alive:
        gw.append(_row("Background service", f"Running (last signal {age:.0f} s ago)" if age is not None else "Running", OK))
    else:
        gw.append(_row("Background service", "Not running", ERROR if f.get("server_desired") == "start" else WARN,
                       "Open Home and tap Start Server. If it stops by itself, see 'Keep running in background' in Settings."))
    server = f.get("server")
    if not alive:
        gw.append(_row("API server", "Unknown (service not running)", INFO))
    elif server == "started":
        gw.append(_row("API server", f"Online on {f.get('host') or '?'}:{f.get('port') or '?'}", OK))
    elif server == "error":
        gw.append(_row("API server", f"Error: {f.get('error') or 'unknown'}", ERROR,
                       "Change the port in Settings, or connect Tailscale if the mode is 'Tailscale only'."))
    else:
        gw.append(_row("API server", "Stopped", INFO))
    gw.append(_row("Listening mode", {"all": "All networks", "tailscale": "Tailscale only", "localhost": "This phone only"}
                   .get(f.get("bind"), str(f.get("bind") or "All networks")), INFO))
    if alive and server == "started":
        want_lock = bool(f.get("wakelock_setting", True))
        held = diag.get("wakelock")
        if not want_lock:
            gw.append(_row("CPU wake lock", "Off (setting)", WARN, "With the screen off the phone may sleep and stop answering requests."))
        elif android and held is False:
            gw.append(_row("CPU wake lock", "Not held", WARN, "Unexpected: the setting is on. Check logcat for 'Wake lock acquire error'."))
        elif held:
            gw.append(_row("CPU wake lock", "Held", OK))
    pending = diag.get("queue")
    if alive and pending is not None:
        gw.append(_row("Send queue", f"{pending} waiting", INFO if pending < 50 else WARN))
    sections.append({"title": "Gateway", "rows": gw})

    # ---------------- SMS ----------------
    sms = [
        _perm("SMS permission", f.get("perm_sms"), "Messages cannot be sent.", "Allow SMS for OpenSMS in Android settings."),
        _perm("Phone permission", f.get("perm_phone"), "SIM selection (sim_slot) is refused.", "Allow Phone for OpenSMS in Android settings."),
    ]
    if android:
        rec = diag.get("receipts")
        if not alive:
            sms.append(_row("Delivery tracking", "Unknown (service not running)", INFO))
        elif rec:
            sms.append(_row("Delivery tracking", "Active (sent and delivery reports are received)", OK))
        else:
            sms.append(_row("Delivery tracking", "Unavailable", WARN,
                            "Messages will stay 'Submitted'. The receipt receiver could not be registered; see logcat for 'SMS receipts unavailable'."))
        sims = f.get("sims") or {}
        if sims.get("reliable"):
            sms.append(_row("SIM cards", f"{sims.get('count', 0)} detected", OK))
        else:
            sms.append(_row("SIM cards", "Could not be read", WARN, "Grant the Phone permission; until then only the default SIM can be used."))
    else:
        sms.append(_row("SMS provider", "Simulation (not Android): nothing is sent", INFO))
    sections.append({"title": "SMS", "rows": sms})

    # ---------------- network ----------------
    ts = f.get("tailscale") or {}
    state = ts.get("state")
    net = []
    if state == "connected":
        net.append(_row("Tailscale", f"Connected ({ts.get('ip') or 'IPv6 only'})", OK))
    elif state == "other_vpn":
        net.append(_row("Tailscale", "Another VPN is active", WARN, "Android allows one VPN at a time; connect Tailscale."))
    elif state == "unknown":
        net.append(_row("Tailscale", "Status unavailable", WARN, "The network state could not be read on this device."))
    else:
        net.append(_row("Tailscale", "Not connected", INFO))
    net.append(_row("Local address", str(f.get("local_ip") or "unknown"), INFO))
    if f.get("bind") == "tailscale" and state != "connected":
        net.append(_row("Mode check", "'Tailscale only' needs Tailscale to be connected", ERROR, "Connect Tailscale or change the listening mode."))
    sections.append({"title": "Network", "rows": net})

    # ---------------- storage ----------------
    db = f.get("db") or {}
    sections.append({"title": "Storage", "rows": [
        _row("Messages stored", str(db.get("messages", "?")), INFO),
        _row("Active API keys", str(db.get("active_keys", "?")), OK if db.get("active_keys") else WARN,
             None if db.get("active_keys") else "No active key: every API request will be refused. Create one in the API tab."),
        _row("Database", f"{_size(db.get('size_bytes'))}, schema v{db.get('schema', '?')}", INFO),
    ]})

    # ---------------- app ----------------
    sections.append({"title": "App", "rows": [
        _row("Version", str(f.get("version", "?")), INFO),
        _row("Update source", str(f.get("repo", "?")), INFO),
        _row("Platform", str(f.get("platform_text", "?")), INFO),
    ]})
    return sections


def overall_level(sections: List[Dict[str, Any]]) -> str:
    levels = {r["level"] for s in sections for r in s["rows"]}
    return ERROR if ERROR in levels else WARN if WARN in levels else OK


def to_text(sections: List[Dict[str, Any]], header: str = "OpenSMS diagnostics") -> str:
    mark = {OK: "[OK]", INFO: "[i] ", WARN: "[!] ", ERROR: "[X] "}
    lines = [header]
    for s in sections:
        lines.append("")
        lines.append(s["title"].upper())
        for r in s["rows"]:
            lines.append(f"{mark[r['level']]} {r['label']}: {r['value']}")
            if r.get("hint"):
                lines.append(f"      -> {r['hint']}")
    return "\n".join(lines)
