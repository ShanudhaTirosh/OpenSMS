"""
Battery and power telemetry service for OpenSMS.
Queries device battery percentage, charging state, and power source safely.
Compatible with Android via PyJNIus, with safe fallback on non-Android platforms.
"""
from typing import Dict, Any

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

if platform == "android":
    try:
        from jnius import autoclass
    except ImportError:
        autoclass = None
else:
    autoclass = None


def get_battery_info() -> Dict[str, Any]:
    """
    Retrieve current battery level, percentage, charging state, and power source.
    Never raises an exception; falls back gracefully.
    """
    info: Dict[str, Any] = {
        "available": False,
        "percentage": None,
        "charging": False,
        "plugged": False,
        "power_source": "unknown",
        "status": "unknown"
    }

    if platform == "android" and autoclass:
        try:
            from services.smsApi import get_android_context
            context = get_android_context()
            if context:
                IntentFilter = autoclass('android.content.IntentFilter')
                Intent = autoclass('android.content.Intent')
                BatteryManager = autoclass('android.os.BatteryManager')

                filt = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
                status_intent = context.registerReceiver(None, filt)
                if status_intent:
                    level = status_intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
                    scale = status_intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
                    status = status_intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
                    plugged = status_intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0)

                    pct = round((level / float(scale)) * 100) if scale > 0 else (level if level >= 0 else None)
                    is_charging = status in (
                        getattr(BatteryManager, 'BATTERY_STATUS_CHARGING', 2),
                        getattr(BatteryManager, 'BATTERY_STATUS_FULL', 5)
                    )
                    is_plugged = plugged > 0

                    if plugged == 1:
                        source = "ac"
                    elif plugged == 2:
                        source = "usb"
                    elif plugged == 4:
                        source = "wireless"
                    else:
                        source = "battery"

                    info["available"] = True
                    info["percentage"] = pct
                    info["charging"] = is_charging
                    info["plugged"] = is_plugged
                    info["power_source"] = source
                    info["status"] = "charging" if is_charging else ("full" if status == 5 else "discharging")
                    return info
        except Exception as e:
            print("Notice: Android BatteryManager query skipped:", e)

    return info
