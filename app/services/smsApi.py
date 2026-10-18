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
        from jnius import autoclass
    except ImportError:
        autoclass = None


## functions

def get_sms_manager():
    """Retrieve SmsManager instance compatible across Android versions."""
    SmsManager = autoclass('android.telephony.SmsManager')
    try:
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Context = autoclass('android.content.Context')
        activity = PythonActivity.mActivity
        # For Android 12+ (API 31+)
        sms_manager = activity.getSystemService(Context.TELEPHONY_SMS_SERVICE)
        if sms_manager is not None:
            return sms_manager
    except Exception as e:
        print("Notice: getSystemService for SmsManager failed, falling back to getDefault():", e)
    return SmsManager.getDefault()

def send_sms(phone: str, msg: str):
    stat = False
    if platform == "android":
        try:
            sms_manager = get_sms_manager()
            parts = sms_manager.divideMessage(msg)
            if parts.size() > 1:
                sms_manager.sendMultipartTextMessage(phone, None, parts, None, None)
            else:
                sms_manager.sendTextMessage(phone, None, msg, None, None)
            stat = True
        except Exception as e:
            print("SMS ❌ Failed:", e)
    else:
        # Non-android simulation
        print(f"[Simulation] SMS to {phone}: {msg}")
        stat = True
    return stat

