"""
SMS sent / delivery receipt plumbing.

Pure helpers (describe_sent_result, classify_tp_status) are platform independent and unit tested.
The Android parts (register_receiver, build_pending_intents) need the Java classes in
app/java_src (declared via `android.add_src` in buildozer.spec) and have NOT been verified on a
device yet; every entry point degrades to "receipts unavailable" instead of raising.
"""
from typing import Callable, Optional, Tuple

try:
    from kivy.utils import platform
except ImportError:  # desktop / tests without Kivy
    import sys
    platform = "android" if hasattr(sys, "getandroidapilevel") else "linux"

ACTION_SENT = "org.opensms.gateway.SMS_SENT"
ACTION_DELIVERED = "org.opensms.gateway.SMS_DELIVERED"

RESULT_OK = -1  # android.app.Activity.RESULT_OK

# SmsManager.RESULT_ERROR_* / RESULT_* codes (android.telephony.SmsManager constants)
_SENT_ERRORS = {
    1: "Generic failure",
    2: "Radio is off (airplane mode?)",
    3: "Null PDU",
    4: "No cellular service",
    5: "Sending limit exceeded",
    6: "Fixed dialing numbers (FDN) check failed",
    7: "Short code not allowed",
    8: "Short code never allowed",
    9: "Radio not available",
    10: "Network rejected the message",
    11: "Invalid arguments",
    12: "Invalid state",
    13: "No memory",
    14: "Network congestion / unavailable",
    15: "Invalid SMSC address",
    16: "Modem error",
    17: "Network error",
}


def describe_sent_result(result_code: int) -> Tuple[bool, Optional[str]]:
    """(ok, error_text). RESULT_OK means the radio accepted this part for transmission."""
    if result_code == RESULT_OK:
        return True, None
    return False, _SENT_ERRORS.get(result_code, f"Send failed (code {result_code})")


def classify_tp_status(tp_status: int) -> str:
    """
    Interpret the TP-Status octet of an SMS-STATUS-REPORT (3GPP TS 23.040 section 9.2.3.15):
      0x00-0x1F  delivered / completed
      0x20-0x3F  temporary error, SC still trying   -> 'pending'
      0x40-0x7F  permanent / gave up                -> 'failed'
    Returns 'unknown' when no PDU status was available, so nothing is ever reported as delivered
    without an authoritative status report.
    """
    if tp_status is None or tp_status < 0:
        return "unknown"
    if tp_status < 0x20:
        return "delivered"
    if tp_status < 0x40:
        return "pending"
    return "failed"


# --------------------------- Android only (device-untested) ---------------------------
_state = {"registered": False, "listener": None, "receiver": None}


def receipts_available() -> bool:
    return platform == "android" and _state["registered"]


def register_receiver(callback: Callable[[str, str, int, Optional[bool], Optional[str], Optional[str]], None]) -> bool:
    """
    Register the dynamic receiver. `callback(kind, msg_id, part, sent_ok, sent_error, delivery)` is
    invoked on the Android main thread, so it must only enqueue work. Returns False if anything
    needed is missing (e.g. the Java classes were not compiled into the APK).
    """
    if platform != "android":
        return False
    if _state["registered"]:
        return True
    try:
        from jnius import autoclass, PythonJavaClass, java_method

        class _Listener(PythonJavaClass):
            __javainterfaces__ = ["org/opensms/gateway/SmsResultListener"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/String;Ljava/lang/String;III)V")
            def onResult(self, action, msg_id, part, result_code, tp_status):
                try:
                    if str(action) == ACTION_SENT:
                        ok, err = describe_sent_result(int(result_code))
                        callback("sent", str(msg_id), int(part), ok, err, None)
                    elif str(action) == ACTION_DELIVERED:
                        callback("delivered", str(msg_id), int(part), None, None,
                                 classify_tp_status(int(tp_status)))
                except Exception as e:  # never let an exception cross into Java
                    print(f"Receipt callback error: {e}")

        SmsResultReceiver = autoclass("org.opensms.gateway.SmsResultReceiver")
        IntentFilter = autoclass("android.content.IntentFilter")
        Context = autoclass("android.content.Context")
        Build = autoclass("android.os.Build$VERSION")
        from services.smsApi import get_android_context
        context = get_android_context()
        if context is None:
            return False

        listener = _Listener()
        SmsResultReceiver.setListener(listener)
        receiver = SmsResultReceiver()
        flt = IntentFilter()
        flt.addAction(ACTION_SENT)
        flt.addAction(ACTION_DELIVERED)
        if Build.SDK_INT >= 33:
            context.registerReceiver(receiver, flt, Context.RECEIVER_NOT_EXPORTED)
        else:
            context.registerReceiver(receiver, flt)
        _state.update(registered=True, listener=listener, receiver=receiver)
        return True
    except Exception as e:
        print(f"Notice: SMS receipts unavailable: {e}")
        return False


def build_pending_intents(msg_id: str, n_parts: int):
    """
    Returns (sent_intents, delivery_intents) as java.util.ArrayLists of PendingIntent, one per part,
    or (None, None) when receipts are unavailable. Each PendingIntent is unique per
    (message, part, kind) through its data URI.
    """
    if not receipts_available():
        return None, None
    from jnius import autoclass
    from services.smsApi import get_android_context
    Intent = autoclass("android.content.Intent")
    Uri = autoclass("android.net.Uri")
    PendingIntent = autoclass("android.app.PendingIntent")
    ArrayList = autoclass("java.util.ArrayList")
    context = get_android_context()
    # FLAG_MUTABLE is required so the telephony framework can attach the status-report PDU.
    # The intent is made explicit with setPackage (mutable + fully implicit intents are rejected
    # on Android 14+). Behaviour on Android 14+ must be confirmed on a device.
    flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE
    sent_list, delivery_list = ArrayList(), ArrayList()
    for part in range(n_parts):
        for action, kind, target in ((ACTION_SENT, "sent", sent_list), (ACTION_DELIVERED, "delivered", delivery_list)):
            intent = Intent(action)
            intent.setPackage(context.getPackageName())
            intent.setData(Uri.parse(f"opensms://receipt/{msg_id}/{part}/{kind}"))
            intent.putExtra("msg_id", msg_id)
            intent.putExtra("part", part)
            target.add(PendingIntent.getBroadcast(context, 0, intent, flags))
    return sent_list, delivery_list
