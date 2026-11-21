"""
Asynchronous webhook dispatcher for OpenSMS.

Dispatches event notifications (e.g. sms.submitted, sms.sent, sms.delivered, sms.failed)
to registered HTTP/HTTPS webhook endpoints with HMAC-SHA256 signature verification.
Runs in a separate thread pool so it never blocks the SMS worker or telephony operations.
"""
import hmac
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
import requests

from app_version import __version__

_webhook_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opensms-webhooks")


def build_signature(payload_bytes: bytes, secret: str) -> str:
    """Generate HMAC-SHA256 signature hex digest."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def send_webhook_request(
    url: str,
    payload: Dict[str, Any],
    secret: Optional[str] = None,
    timeout: float = 5.0
) -> tuple[bool, Optional[int], Optional[str]]:
    """
    Synchronous HTTP POST to a single webhook endpoint.
    Returns (success, status_code, error_message).
    """
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"OpenSMS-Gateway/{__version__}",
        "X-OpenSMS-Event": payload.get("event", "unknown"),
        "X-OpenSMS-Delivery-Timestamp": str(payload.get("timestamp", time.time()))
    }
    if secret:
        sig = build_signature(payload_bytes, secret)
        headers["X-OpenSMS-Signature"] = f"sha256={sig}"

    try:
        resp = requests.post(url, data=payload_bytes, headers=headers, timeout=timeout)
        success = 200 <= resp.status_code < 300
        return success, resp.status_code, None if success else f"HTTP {resp.status_code}"
    except Exception as e:
        return False, None, str(e)


def dispatch_event(db, event: str, data: Dict[str, Any]):
    """
    Look up all active webhooks subscribed to `event` and dispatch asynchronously.
    Safe against exceptions; never raises.
    """
    if db is None:
        return

    try:
        hooks = db.get_active_webhooks_for_event(event)
    except Exception as e:
        print(f"Notice: Failed to query active webhooks for {event}: {e}")
        return

    if not hooks:
        return

    now = time.time()
    payload = {
        "event": event,
        "timestamp": now,
        "data": data
    }

    for hook in hooks:
        url = hook.get("url")
        secret = hook.get("secret")
        if url:
            _webhook_pool.submit(_safe_dispatch, url, payload, secret)


def _safe_dispatch(url: str, payload: Dict[str, Any], secret: Optional[str]):
    try:
        ok, code, err = send_webhook_request(url, payload, secret=secret)
        if not ok:
            print(f"Webhook delivery failed for {url} ({payload.get('event')}): {err}")
    except Exception as e:
        print(f"Webhook dispatch exception for {url}: {e}")
