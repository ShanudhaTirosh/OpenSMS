"""
Presentation helpers for the Messages and API screens. No Kivy imports: everything here is unit tested.
"""
import datetime
from typing import Any, Dict, List, Optional

# status -> (label, icon, rgba colour, plain-language explanation)
STATUS_STYLE = {
    "queued":    ("Queued",    "clock-outline",         (0.55, 0.55, 0.60, 1), "Accepted and waiting to be handed to the phone's SMS service."),
    "submitted": ("Submitted", "send-clock-outline",    (0.20, 0.45, 0.85, 1), "Handed to Android. The radio result is not known yet."),
    "sent":      ("Sent",      "check",                 (0.10, 0.60, 0.60, 1), "The network accepted every part. Delivery is only confirmed if your carrier returns a delivery report."),
    "delivered": ("Delivered", "check-all",             (0.15, 0.65, 0.30, 1), "A delivery report confirmed every part reached the recipient's handset."),
    "failed":    ("Failed",    "alert-circle-outline",  (0.80, 0.25, 0.25, 1), "The message was rejected or could not be sent."),
    "unknown":   ("Unknown",   "help-circle-outline",   (0.85, 0.60, 0.10, 1), "No result was received (for example the app restarted). It may or may not have been sent."),
}
FILTERS = ["all", "queued", "submitted", "sent", "delivered", "failed", "unknown"]
PAGE_SIZE = 25


def status_info(status: Optional[str]) -> Dict[str, Any]:
    key = (status or "").lower()
    label, icon, color, help_text = STATUS_STYLE.get(
        key, ((status or "?").title(), "help-circle-outline", (0.5, 0.5, 0.5, 1), "Unrecognised status."))
    return {"key": key, "label": label, "icon": icon, "color": color, "help": help_text}


def format_time(ts: Optional[float], now: Optional[datetime.datetime] = None) -> str:
    """Local time: 'Today 14:05', 'Yesterday 09:12', '12 Oct 14:05' or '12 Oct 2025'. '-' when missing."""
    if not ts:
        return "-"
    now = now or datetime.datetime.now().astimezone()
    dt = datetime.datetime.fromtimestamp(ts).astimezone()
    days = (now.date() - dt.date()).days
    clock = dt.strftime("%H:%M")
    if days == 0:
        return f"Today {clock}"
    if days == 1:
        return f"Yesterday {clock}"
    if dt.year == now.year:
        return f"{dt.day} {dt.strftime('%b')} {clock}"
    return f"{dt.day} {dt.strftime('%b %Y')}"


def shorten(text: str, limit: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def parts_summary(msg: Dict[str, Any], parts: List[Dict[str, Any]]) -> str:
    expected = msg.get("parts_expected") or len(parts) or 0
    if not expected:
        return "-"
    sent = sum(1 for p in parts if p.get("sent_ok") == 1 or p.get("delivery") == "delivered")
    delivered = sum(1 for p in parts if p.get("delivery") == "delivered")
    failed = sum(1 for p in parts if p.get("sent_ok") == 0 or p.get("delivery") == "failed")
    bits = [f"{sent}/{expected} sent", f"{delivered}/{expected} delivered"]
    if failed:
        bits.append(f"{failed} failed")
    return f"{expected} part{'s' if expected != 1 else ''}: " + ", ".join(bits)


def describe_message(msg: Dict[str, Any], parts: List[Dict[str, Any]], now=None) -> List[tuple]:
    """Ordered (label, value) rows for the detail dialog."""
    info = status_info(msg.get("status"))
    rows = [
        ("Status", info["label"]),
        ("Meaning", info["help"]),
    ]
    if msg.get("carrier_error"):
        rows.append(("Reason", msg["carrier_error"]))
    rows += [
        ("To", msg.get("recipient", "-")),
        ("Created", format_time(msg.get("created_at"), now)),
        ("Last update", format_time(msg.get("updated_at"), now)),
        ("Delivered at", format_time(msg.get("delivered_at"), now) if msg.get("delivered_at") else "Not confirmed"),
        ("Parts", parts_summary(msg, parts)),
        ("Encoding", f"{msg.get('encoding') or '-'} (~{msg.get('segments') or 0} segment(s))"),
        ("SIM", "Default" if (msg.get("sim_slot") in (None, -1)) else f"Slot {msg['sim_slot'] + 1}"),
        ("Provider", "Simulated (nothing was sent)" if msg.get("provider") == "simulated" else (msg.get("provider") or "-")),
        ("Message ID", msg.get("id", "-")),
        ("Text", shorten(msg.get("text", ""), 500)),
    ]
    return rows


def fetch_messages(db, status: str = "all", search: str = "", offset: int = 0, limit: int = PAGE_SIZE) -> Dict[str, Any]:
    status = status if status in FILTERS else "all"
    search = (search or "").strip()[:100] or None
    rows = db.get_messages(limit=limit, offset=max(0, offset), status=status, search=search)
    total = db.count_messages(status=status, search=search)
    return {
        "rows": rows, "total": total, "offset": offset,
        "has_more": offset + len(rows) < total,
        "range_text": ("No messages" if total == 0 else f"Showing {min(offset + len(rows), total)} of {total}"),
    }


SCOPE_LABELS = {"sms:write": "Send", "sms:read": "Read", "admin": "Admin"}


def scopes_text(scopes: List[str]) -> str:
    return ", ".join(SCOPE_LABELS.get(s, s) for s in (scopes or [])) or "No scopes"


def key_row(key: Dict[str, Any], now=None) -> Dict[str, Any]:
    active = bool(key.get("is_active"))
    return {
        "id": key["id"],
        "title": key.get("name") or "Unnamed key",
        "prefix": f"{key.get('prefix') or 'osms_'}",
        "active": active,
        "scopes": scopes_text(key.get("scopes", [])),
        "created": format_time(key.get("created_at"), now),
        "last_used": format_time(key.get("last_used_at"), now) if key.get("last_used_at") else "Never used",
        "state": "Active" if active else "Revoked",
    }


def valid_key_name(name: str) -> Optional[str]:
    """Return an error message, or None when the name is acceptable."""
    name = (name or "").strip()
    if not name:
        return "Enter a name so you can recognise this key later."
    if len(name) > 64:
        return "Use at most 64 characters."
    return None
