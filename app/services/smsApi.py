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


import re

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

def get_sms_manager():
    """Retrieve SmsManager instance compatible across Android versions."""
    SmsManager = autoclass('android.telephony.SmsManager')
    try:
        Context = autoclass('android.content.Context')
        context = None
        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            context = PythonActivity.mActivity
        except Exception:
            pass

        if not context:
            try:
                PythonService = autoclass('org.kivy.android.PythonService')
                context = PythonService.mService
            except Exception:
                pass

        # For Android 12+ (API 31+)
        if context is not None:
            raw_manager = context.getSystemService(Context.TELEPHONY_SMS_SERVICE)
            if raw_manager is not None:
                if cast is not None:
                    return cast('android.telephony.SmsManager', raw_manager)
                return raw_manager
    except Exception as e:
        print("Notice: getSystemService for SmsManager failed, falling back to getDefault():", e)
    return SmsManager.getDefault()

def send_sms(phone: str, msg: str):
    stat = False
    clean_phone = sanitize_phone_number(phone)
    if not clean_phone:
        print(f"SMS ❌ Failed: invalid or empty phone number '{phone}'")
        return False

    if platform == "android":
        try:
            sms_manager = get_sms_manager()
            parts = sms_manager.divideMessage(msg)
            if parts.size() > 1:
                sms_manager.sendMultipartTextMessage(clean_phone, None, parts, None, None)
            else:
                sms_manager.sendTextMessage(clean_phone, None, msg, None, None)
            stat = True
        except Exception as e:
            print("SMS ❌ Failed:", e)
    else:
        # Non-android simulation
        print(f"[Simulation] SMS to {clean_phone}: {msg}")
        stat = True
    return stat

