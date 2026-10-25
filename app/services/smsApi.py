try:
    from kivy.utils import platform
except ImportError:
    import sys
    if sys.platform.startswith("win"):
        platform = "win"
    elif sys.platform.startswith("linux"):
        platform = "linux"
    else:
        platform = "unknown"

## OS specific setups
# for android
if platform == "android":
    try:
        from jnius import autoclass, cast
    except ImportError:
        autoclass = None
        cast = None
else:
    autoclass = None
    cast = None

import os
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

## functions

def sanitize_phone_number(raw_phone: str) -> str:
    """
    Sanitize phone number to standard dialable format.
    Preserves leading '+' for international numbers and strips all formatting
    characters (spaces, hyphens, brackets, dots).
    Returns empty string if no digits exist.
    """
    if not raw_phone:
        return ""
    stripped = raw_phone.strip()
    is_international = stripped.startswith("+")
    digits_only = re.sub(r"[^\d]", "", stripped)
    if not digits_only:
        return ""
    return f"+{digits_only}" if is_international else digits_only

# GSM 03.38 default alphabet (without the escape code) and its extension table.
_GSM7_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = frozenset("^{}\\[~]|€\f")  # each costs 2 septets (escape + char)


def _pack_segments(costs: List[int], single_cap: int, multi_cap: int):
    """Greedy packing that never splits a multi-unit character across two segments."""
    total = sum(costs)
    if total == 0:
        return 0, single_cap
    if total <= single_cap:
        return 1, single_cap - total
    segments, used = 1, 0
    for c in costs:
        if used + c > multi_cap:
            segments += 1
            used = 0
        used += c
    return segments, multi_cap - used


def calculate_sms_segments(text: str) -> dict:
    """
    Estimate encoding and segment count (the telephony stack's divideMessage() is authoritative).
    - GSM-7: 160 septets single / 153 per part; extension characters (e.g. EUR, [, ], {, }) cost 2.
    - UCS-2: 70 UTF-16 units single / 67 per part; characters outside the BMP (emoji) cost 2.
    `length` is the number of characters, `units` the encoded size in septets / UTF-16 units.
    """
    if all(ch in _GSM7_BASIC or ch in _GSM7_EXT for ch in text):
        costs = [2 if ch in _GSM7_EXT else 1 for ch in text]
        segments, remaining = _pack_segments(costs, 160, 153)
        encoding = "GSM-7"
    else:
        costs = [2 if ord(ch) > 0xFFFF else 1 for ch in text]
        segments, remaining = _pack_segments(costs, 70, 67)
        encoding = "UCS-2 (Unicode)"
    return {
        "length": len(text),
        "units": sum(costs),
        "encoding": encoding,
        "segments": segments,
        "remaining": remaining,
    }

def get_android_context():
    """Retrieve active Android Context (Activity or Background Service)."""
    if platform != "android" or not autoclass:
        return None
    try:
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        if PythonActivity.mActivity is not None:
            return PythonActivity.mActivity
    except Exception:
        pass

    try:
        PythonService = autoclass('org.kivy.android.PythonService')
        if PythonService.mService is not None:
            return PythonService.mService
    except Exception:
        pass
    return None

def get_active_sims_with_status():
    """
    (sims, from_system). `from_system` is True only when Android answered the SubscriptionManager
    query (even with an empty list). It is False when the query failed, which on a real phone almost
    always means the Phone permission (READ_PHONE_STATE) is missing: then the returned list is only a
    placeholder and must not be used to decide anything about SIM routing.
    """
    sims = []
    from_system = False
    if platform == "android" and autoclass:
        try:
            Context = autoclass('android.content.Context')
            context = get_android_context()
            if context:
                sub_service = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE)
                if sub_service:
                    active_subs = sub_service.getActiveSubscriptionInfoList()
                    from_system = True
                    if active_subs:
                        for i in range(active_subs.size()):
                            sub = active_subs.get(i)
                            slot_idx = sub.getSimSlotIndex()
                            sub_id = sub.getSubscriptionId()
                            carrier = str(sub.getCarrierName() or f"SIM {slot_idx + 1}")
                            display_name = str(sub.getDisplayName() or carrier)
                            country = str(sub.getCountryIso() or "").upper()
                            sims.append({
                                "slot": slot_idx,
                                "sub_id": sub_id,
                                "carrier": carrier,
                                "display_name": display_name,
                                "country": country
                            })
        except Exception as e:
            print("Notice: SubscriptionManager SIM query skipped:", e)
    if not sims:
        # Fallback default SIM entry
        sims.append({
            "slot": 0,
            "sub_id": 0,
            "carrier": "Default Carrier (Primary)",
            "display_name": "SIM 1 (Default)",
            "country": "LOCAL",
            "placeholder": True
        })
    return sims, from_system


def get_active_sims() -> List[Dict[str, Any]]:
    """Enumerate active SIM cards via Android SubscriptionManager (API 22+); placeholder entries carry placeholder=True."""
    return get_active_sims_with_status()[0]

def get_sms_manager(sim_slot: int = -1):
    """
    Retrieve SmsManager instance compatible across Android versions,
    with automatic multi-SIM routing when sim_slot (0 or 1) is specified.
    """
    if platform != "android" or not autoclass:
        return None

    SmsManager = autoclass('android.telephony.SmsManager')
    context = get_android_context()

    # Multi-SIM routing (API 22+)
    if sim_slot >= 0 and context:
        try:
            Context = autoclass('android.content.Context')
            sub_service = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE)
            if sub_service:
                active_subs = sub_service.getActiveSubscriptionInfoList()
                if active_subs:
                    for i in range(active_subs.size()):
                        sub = active_subs.get(i)
                        if sub.getSimSlotIndex() == sim_slot:
                            sub_id = sub.getSubscriptionId()
                            return SmsManager.getSmsManagerForSubscriptionId(sub_id)
        except Exception as e:
            print(f"Notice: Specific SIM routing for slot {sim_slot} failed, falling back to default:", e)

    # Android 12+ (API 31+) Context service retrieval
    if context is not None:
        try:
            Context = autoclass('android.content.Context')
            raw_manager = context.getSystemService(Context.TELEPHONY_SMS_SERVICE)
            if raw_manager is not None:
                if cast is not None:
                    return cast('android.telephony.SmsManager', raw_manager)
                return raw_manager
        except Exception as e:
            print("Notice: getSystemService for SmsManager failed:", e)

    return SmsManager.getDefault()

def validate_sim_slot(sim_slot: int) -> None:
    """Raise ValueError unless sim_slot is -1 (default SIM) or an active SIM slot (audit SMS-03)."""
    if sim_slot is None or sim_slot == -1:
        return
    sims, from_system = get_active_sims_with_status()
    if platform == "android" and autoclass and not from_system:
        # Do not guess: the old behaviour silently used the default SIM when routing was impossible.
        raise ValueError(
            "SIM details are unavailable on this device (OpenSMS needs the Phone permission to route by SIM). "
            "Grant it in Android settings, or omit sim_slot to use the default SIM.")
    active = {sim["slot"] for sim in sims}
    if sim_slot not in active:
        raise ValueError(f"SIM slot {sim_slot} is not active. Active slots: {sorted(active)}")


@dataclass
class SubmitResult:
    ok: bool
    parts: int = 0
    error: Optional[str] = None
    provider: str = "android"
    # True when the provider confirms radio acceptance itself (simulation) instead of via receipts
    synthetic_sent: bool = False


class AndroidSmsProvider:
    """Hands messages to android.telephony.SmsManager; sent/delivery results arrive via receipts."""
    name = "android"

    @property
    def supports_receipts(self) -> bool:
        from services import smsReceipts
        return smsReceipts.receipts_available()

    def submit(self, msg_id: str, phone: str, text: str, sim_slot: int = -1) -> SubmitResult:
        clean_phone = sanitize_phone_number(phone)
        if not clean_phone:
            return SubmitResult(False, error="Invalid or empty phone number")
        try:
            sms_manager = get_sms_manager(sim_slot=sim_slot)
            if not sms_manager:
                return SubmitResult(False, error="SmsManager not initialised")
            parts = sms_manager.divideMessage(text)
            n = int(parts.size())
            from services import smsReceipts
            sent_pi, delivery_pi = smsReceipts.build_pending_intents(msg_id, n)
            if n > 1:
                sms_manager.sendMultipartTextMessage(clean_phone, None, parts, sent_pi, delivery_pi)
            else:
                sms_manager.sendTextMessage(
                    clean_phone, None, text,
                    sent_pi.get(0) if sent_pi is not None else None,
                    delivery_pi.get(0) if delivery_pi is not None else None)
            return SubmitResult(True, parts=n)
        except Exception as e:
            print(f"SMS failed to {clean_phone}: {e}")
            return SubmitResult(False, error=str(e) or e.__class__.__name__)


class SimulatedSmsProvider:
    """Development/CI only. Nothing is sent. Disabled unless OPENSMS_ALLOW_SIMULATION=1 (audit SMS-02)."""
    name = "simulated"
    supports_receipts = False

    def submit(self, msg_id: str, phone: str, text: str, sim_slot: int = -1) -> SubmitResult:
        if os.environ.get("OPENSMS_ALLOW_SIMULATION", "0") != "1":
            return SubmitResult(
                False, provider="simulated",
                error="Not running on Android: SMS simulation is disabled (set OPENSMS_ALLOW_SIMULATION=1 for development)")
        clean_phone = sanitize_phone_number(phone)
        if not clean_phone:
            return SubmitResult(False, provider="simulated", error="Invalid or empty phone number")
        slot_info = f" [SIM {sim_slot + 1}]" if sim_slot >= 0 else ""
        print(f"[Simulation]{slot_info} SMS to {clean_phone}: {text}")
        return SubmitResult(True, parts=max(1, calculate_sms_segments(text)["segments"]),
                            provider="simulated", synthetic_sent=True)


def get_provider():
    if platform == "android" and autoclass:
        return AndroidSmsProvider()
    return SimulatedSmsProvider()


def send_sms(phone: str, msg: str, sim_slot: int = -1, msg_id: Optional[str] = None) -> bool:
    """Backward compatible helper: True when the message was handed to the provider."""
    return get_provider().submit(msg_id or "adhoc", phone, msg, sim_slot).ok
