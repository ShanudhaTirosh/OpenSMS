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

import re
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

def calculate_sms_segments(text: str) -> dict:
    """
    Calculate SMS length, encoding type (GSM-7 vs UCS-2), and segment count.
    - GSM-7: 160 chars single, 153 chars/segment for multipart.
    - UCS-2: 70 chars single, 67 chars/segment for multipart.
    """
    # GSM 03.38 basic character set check
    gsm7_basic = set(
        "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
        "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ`abcdefghijklmnopqrstuvwxyzäöñüà"
    )
    is_unicode = any(char not in gsm7_basic for char in text)
    length = len(text)

    if not is_unicode:
        encoding = "GSM-7"
        if length <= 160:
            segments = 1 if length > 0 else 0
            remaining = 160 - length
        else:
            segments = (length + 152) // 153
            remaining = (segments * 153) - length
    else:
        encoding = "UCS-2 (Unicode)"
        if length <= 70:
            segments = 1 if length > 0 else 0
            remaining = 70 - length
        else:
            segments = (length + 66) // 67
            remaining = (segments * 67) - length

    return {
        "length": length,
        "encoding": encoding,
        "segments": segments,
        "remaining": remaining
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

def get_active_sims() -> List[Dict[str, Any]]:
    """Enumerate active SIM cards via Android SubscriptionManager (API 22+)."""
    sims = []
    if platform == "android" and autoclass:
        try:
            Context = autoclass('android.content.Context')
            context = get_android_context()
            if context:
                sub_service = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE)
                if sub_service:
                    active_subs = sub_service.getActiveSubscriptionInfoList()
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
            "country": "LOCAL"
        })
    return sims

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

def send_sms(phone: str, msg: str, sim_slot: int = -1, msg_id: Optional[str] = None) -> bool:
    """
    Send an SMS message via Android SmsManager or desktop simulation.
    Handles phone sanitization, multi-part segmentation, and SIM slot routing.
    """
    clean_phone = sanitize_phone_number(phone)
    if not clean_phone:
        print(f"SMS ❌ Failed: invalid or empty phone number '{phone}'")
        return False

    if platform == "android" and autoclass:
        try:
            sms_manager = get_sms_manager(sim_slot=sim_slot)
            if not sms_manager:
                print("SMS ❌ Failed: SmsManager not initialized")
                return False

            parts = sms_manager.divideMessage(msg)
            if parts.size() > 1:
                sms_manager.sendMultipartTextMessage(clean_phone, None, parts, None, None)
            else:
                sms_manager.sendTextMessage(clean_phone, None, msg, None, None)
            return True
        except Exception as e:
            print(f"SMS ❌ Failed to {clean_phone}: {e}")
            return False
    else:
        # Non-android desktop simulation
        slot_info = f" [SIM {sim_slot + 1}]" if sim_slot >= 0 else ""
        print(f"[Simulation]{slot_info} SMS to {clean_phone}: {msg}")
        return True
