"""Plain-language texts and button states for the built-in Tailscale card (pure functions, unit tested)."""
from typing import Any, Dict

from services.tsEmbed import redact

ONLINE_DOT, OFFLINE_DOT = "\u25cf", "\u25cb"   # defined here: f-string expressions cannot contain backslashes on Python 3.11


def describe_embedded(st: Dict[str, Any], port: int = 9292) -> Dict[str, Any]:
    """Turn the service's status dict into what the card shows. `st` may be empty (service not running).
    Defence in depth: the engine already redacts keys, and every text is redacted again here."""
    out = _describe(st or {}, port)
    for k in ("title", "detail", "peers_text", "endpoint"):
        out[k] = redact(out.get(k, ""))
    return out


def _describe(st: Dict[str, Any], port: int) -> Dict[str, Any]:
    state = st.get("state") or "unknown"
    available = st.get("available", True) is not False
    out = {"state": state, "available": available, "connected": state == "connected", "peers_text": "", "endpoint": "", "ip": "",
           "can_connect": True, "can_disconnect": False, "can_forget": bool(st.get("saved_identity"))}

    if not st:
        out.update(title="Built-in Tailscale: service not running",
                   detail="Start the gateway (Home > Start Server) to use the built-in Tailscale.", can_connect=False)
        return out
    if not available or state == "unavailable":
        out.update(title="Built-in Tailscale: not in this build",
                   detail=st.get("reason") or st.get("error") or "This build does not include the built-in Tailscale engine.",
                   can_connect=False, can_forget=False)
        return out

    titles = {
        "disabled": ("Built-in Tailscale: off", "Enter an auth key or an API token to join your tailnet. "
                     "Other devices on the tailnet can then call this gateway without the Tailscale app on this phone."),
        "starting": ("Built-in Tailscale: connecting...", st.get("message") or "Joining your tailnet..."),
        "connected": ("Built-in Tailscale: connected", ""),
        "needs_auth": ("Built-in Tailscale: key needed", st.get("message") or "Enter an auth key to connect this device."),
        "needs_approval": ("Built-in Tailscale: waiting for approval", st.get("message") or
                           "An admin must approve this device in the Tailscale admin console."),
        "error": ("Built-in Tailscale: problem", st.get("error") or "Something went wrong."),
    }
    title, detail = titles.get(state, ("Built-in Tailscale", st.get("message") or ""))
    out.update(title=title, detail=detail)
    out["can_disconnect"] = state in ("starting", "connected", "needs_approval")
    out["can_connect"] = state not in ("connected", "starting")      # key fields are hidden while a node is up: Disconnect first

    if state == "connected":
        name = st.get("dns_name") or st.get("hostname") or "this device"
        ip = st.get("ip") or st.get("ip6") or "?"
        out["detail"] = f"{name}\n{ip}" + (f"  \u2022  tailnet {st['tailnet']}" if st.get("tailnet") else "")
        host = st.get("ip") or st.get("dns_name") or "<ip>"
        out["endpoint"] = f"http://{host}:{port}/sms/"
        out["ip"] = st.get("ip") or st.get("ip6") or ""
        peers = st.get("peers") or []
        if peers:
            shown = [f"{ONLINE_DOT if p.get('online') else OFFLINE_DOT} {p.get('name', '?')}  {p.get('ip', '')}" for p in peers[:8]]
            more = len(peers) - len(shown)
            out["peers_text"] = ("Other devices on your tailnet:\n" + "\n".join(shown) + (f"\n+{more} more" if more > 0 else ""))
        else:
            out["peers_text"] = "No other devices on your tailnet yet."
        fw = st.get("forwarded") or {}
        if fw.get("accepted"):
            out["detail"] += f"\n{fw['accepted']} connection(s) served"
    return out
