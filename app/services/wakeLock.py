"""
CPU wake lock held by the SERVICE process while the gateway runs.

It used to be held by the UI process, so it vanished as soon as the app was closed or swiped away and the
phone could go to sleep with the gateway "running". The service process outlives the UI, so the lock lives here.
"""
from typing import Callable, Optional


class WakeLockController:
    """Acquires/releases a lock so that it is held exactly while `desired` is True."""

    def __init__(self, factory: Callable[[], Optional[object]]):
        self._factory = factory
        self._lock = None

    @property
    def held(self) -> bool:
        return self._lock is not None

    def update(self, desired: bool) -> None:
        if desired and self._lock is None:
            try:
                lock = self._factory()
                if lock is not None:
                    lock.acquire()
                    self._lock = lock
            except Exception as e:                 # never let a wake-lock problem take the gateway down
                print(f"Wake lock acquire error: {e}")
        elif not desired and self._lock is not None:
            lock, self._lock = self._lock, None
            try:
                if lock.isHeld():
                    lock.release()
            except Exception as e:
                print(f"Wake lock release error: {e}")


def android_wakelock_factory():
    """Returns a factory creating a PARTIAL_WAKE_LOCK from the service context (device-untested)."""
    def make():
        from jnius import autoclass
        from services.smsApi import get_android_context
        context = get_android_context()
        if context is None:
            return None
        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        pm = context.getSystemService(Context.POWER_SERVICE)
        return pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "OpenSMS::GatewayService")
    return make
