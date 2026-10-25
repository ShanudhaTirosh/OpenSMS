"""
Hand-off of messages composed in the app to the gateway service.

The service process owns the message queue and the SMS receipts, so the UI never sends by itself:
it drops a small JSON file into <config>/outbox and the service picks it up. Messages therefore get a
normal lifecycle (history, status, receipts) instead of bypassing the database.

* The file name is the message id, so a crash between "accepted" and "file removed" cannot send twice
  (the service checks whether the id already exists).
* Files are written atomically; half-written files are never picked up.
* Malformed files are renamed to *.bad and never retried; transient problems (full queue) leave the
  file for the next pass.
"""
import json
import os
import uuid
from typing import Callable, Optional, Tuple

from services.pathMgr import atomic_write_json

OUTBOX = "outbox"


class OutboxRetry(Exception):
    """Raised by a handler when the item should stay in the outbox and be retried later."""


def outbox_dir(config_dir: str) -> str:
    return os.path.join(config_dir, OUTBOX)


def validate_outgoing(number: str, text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(clean_number, clean_text, error). Uses the same rules as the HTTP API."""
    from services.postApi import SmsData
    try:
        item = SmsData(number=number, text=text)
    except ValueError as e:
        errors = getattr(e, "errors", None)
        msg = errors()[0]["msg"] if callable(errors) and errors() else str(e)
        return None, None, msg.replace("Value error, ", "")
    return item.number, item.text, None


def write_outbox(config_dir: str, number: str, text: str, sim_slot: int = -1) -> str:
    """Queue a message for the service. Returns the message id. Raises ValueError on invalid input."""
    clean_number, clean_text, error = validate_outgoing(number, text)
    if error:
        raise ValueError(error)
    msg_id = str(uuid.uuid4())
    os.makedirs(outbox_dir(config_dir), exist_ok=True)
    path = os.path.join(outbox_dir(config_dir), f"{msg_id}.json")
    atomic_write_json(path, {"id": msg_id, "number": clean_number, "text": clean_text, "sim_slot": int(sim_slot)})
    if not os.path.exists(path):
        raise OSError("Could not write the message to the outbox")
    return msg_id


def drain_outbox(config_dir: str, handler: Callable[[dict], object], max_items: int = 20) -> int:
    """Pass each queued payload to `handler`. Returns how many were consumed."""
    folder = outbox_dir(config_dir)
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return 0
    consumed = 0
    for name in names[:max_items]:
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("outbox item is not an object")
        except (OSError, ValueError):
            _quarantine(path)
            continue
        try:
            handler(payload)
        except OutboxRetry:
            break                      # keep order; try again on the next pass
        except Exception as e:         # permanent problem with this item
            print(f"Outbox item {name} rejected: {e}")
            _quarantine(path)
            continue
        try:
            os.remove(path)
        except OSError:
            pass
        consumed += 1
    return consumed


def _quarantine(path: str) -> None:
    try:
        os.replace(path, path[: -len(".json")] + ".bad")
    except OSError:
        pass
