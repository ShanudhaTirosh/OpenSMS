"""
Message lifecycle service.

Status model (each step is only reached on evidence):

    queued     accepted by the API, waiting for the send worker
    submitted  handed to the telephony layer (SmsManager); radio result not known yet
    sent       the radio/network accepted EVERY part (sent receipt)
    delivered  a delivery status report confirmed EVERY part   <- only authoritative delivery signal
    failed     rejected at submit, by the radio, or by a failed delivery report
    unknown    submitted but no result ever arrived (e.g. process restarted) - may or may not have been sent

Carriers/SIMs frequently never return delivery reports; such messages correctly stay at `sent`.
"""
import queue
import threading
import time
import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

QUEUE_MAX = 1000
PACING_SECONDS = 0.1                 # gap between hand-offs so the baseband is not saturated
SENT_RECEIPT_TIMEOUT = 10 * 60       # 'submitted' without a sent receipt after this -> 'unknown'
WATCHDOG_INTERVAL = 30

_RANK = {"queued": 0, "submitted": 1, "sent": 2, "delivered": 3}
TERMINAL = {"failed", "delivered", "unknown"}


class QueueFull(Exception):
    pass


def resolve_status(current: str, expected: Optional[int], parts: List[Dict[str, Any]]):
    """
    Pure state machine. Returns (new_status, error_or_None).
    `parts` rows: {"part", "sent_ok" (None/0/1), "sent_error", "delivery" (None/delivered/pending/failed)}.
    Never moves a message backwards and never reports `delivered` without an explicit delivered report
    for every expected part.
    """
    if current == "failed":
        return current, None
    for p in parts:
        if p.get("sent_ok") == 0:
            return "failed", p.get("sent_error") or "Radio rejected the message"
    for p in parts:
        if p.get("delivery") == "failed":
            return "failed", "Delivery failed (status report)"
    if not expected or len(parts) < expected:
        return current, None  # part count not known yet: keep what we have

    by_part = {p["part"]: p for p in parts}
    if len(by_part) < expected:
        return current, None
    all_delivered = all(by_part[i].get("delivery") == "delivered" for i in range(expected) if i in by_part) \
        and all(i in by_part for i in range(expected))
    all_sent = all(i in by_part and (by_part[i].get("sent_ok") == 1 or by_part[i].get("delivery") == "delivered")
                   for i in range(expected))
    target = "delivered" if all_delivered else "sent" if all_sent else current
    if _RANK.get(target, -1) > _RANK.get(current, -1):
        return target, None
    return current, None


@dataclass
class _Item:
    msg_id: str
    number: str
    text: str
    sim_slot: int
    future: "concurrent.futures.Future" = field(default_factory=concurrent.futures.Future)


class MessageService:
    def __init__(self, db, provider, notify: Optional[Callable[[str, str], None]] = None,
                 pacing: float = PACING_SECONDS, sent_timeout: float = SENT_RECEIPT_TIMEOUT):
        self.db = db
        self.provider = provider
        self.notify = notify            # notify(msg_id, new_status), optional UI hook
        self.pacing = pacing
        self.sent_timeout = sent_timeout
        self._q: "queue.Queue[Optional[_Item]]" = queue.Queue(maxsize=QUEUE_MAX)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_watchdog = 0.0

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._recover()
            self._thread = threading.Thread(target=self._run, name="opensms-sender", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0):
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        t = self._thread
        if t and t.is_alive():
            t.join(timeout)

    def _recover(self):
        """After a restart: re-queue messages that never reached the radio; flag ambiguous ones."""
        for row in self.db.list_by_status(["queued"]):
            item = _Item(row["id"], row["recipient"], row["text"], row.get("sim_slot", -1))
            try:
                self._q.put_nowait(item)
            except queue.Full:
                break
        for row in self.db.list_by_status(["sending"]):  # legacy 0.4.0 state: outcome unknown
            self.db.update_message_status(
                row["id"], "unknown",
                carrier_error="Gateway restarted while sending; the message may or may not have been sent")

    # ------------------------------------------------------------------ producer side
    def pending(self) -> int:
        """Messages waiting for the worker."""
        return self._q.qsize()

    def free_slots(self) -> int:
        return QUEUE_MAX - self._q.qsize()

    def enqueue(self, msg_id: str, number: str, text: str, sim_slot: int = -1) -> "concurrent.futures.Future":
        """The message row must already exist with status 'queued'."""
        item = _Item(msg_id, number, text, sim_slot)
        try:
            self._q.put_nowait(item)
        except queue.Full:
            raise QueueFull()
        return item.future

    # ------------------------------------------------------------------ worker
    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                self._maybe_watchdog()
                continue
            if item is None:
                break
            try:
                self._process(item)
            except Exception as e:  # keep the worker alive no matter what
                print(f"Send worker error for {item.msg_id}: {e}")
                self._finish(item, "failed", f"Internal error: {e}")
            self._maybe_watchdog()
            if self.pacing and not self._stop.is_set():
                time.sleep(self.pacing)

    def _finish(self, item: _Item, status: str, error: Optional[str] = None):
        try:
            if status == "failed":
                self.db.update_message_status(item.msg_id, "failed", carrier_error=error)
        finally:
            try:
                item.future.set_result({"status": status, "error": error})
            except concurrent.futures.InvalidStateError:
                pass
            self._notify(item.msg_id, status)

    def _process(self, item: _Item):
        res = self.provider.submit(item.msg_id, item.number, item.text, item.sim_slot)
        if not res.ok:
            self._finish(item, "failed", res.error or "Telephony dispatch failed")
            return
        self.db.record_parts(item.msg_id, max(1, res.parts))
        self.db.update_message_status(item.msg_id, "submitted")
        if res.synthetic_sent:
            for i in range(max(1, res.parts)):
                self.db.update_part(item.msg_id, i, sent_ok=True)
        status = self._recompute(item.msg_id)
        self._finish(item, status)

    # ------------------------------------------------------------------ receipts
    def on_receipt(self, kind: str, msg_id: str, part: int,
                   sent_ok: Optional[bool] = None, sent_error: Optional[str] = None,
                   delivery: Optional[str] = None):
        """Called (from any thread) when a sent/delivery receipt arrives."""
        if kind == "sent":
            self.db.update_part(msg_id, part, sent_ok=bool(sent_ok), sent_error=sent_error)
        elif kind == "delivered":
            if delivery in ("delivered", "failed", "pending"):   # 'unknown' (no PDU) is ignored on purpose
                self.db.update_part(msg_id, part, delivery=delivery)
            else:
                return
        else:
            return
        status = self._recompute(msg_id)
        self._notify(msg_id, status)

    def _recompute(self, msg_id: str) -> str:
        row = self.db.get_status_row(msg_id)
        if not row:
            return "unknown"
        status = row["status"]
        if status in ("queued",):   # receipts before submit bookkeeping finished are applied later
            return status
        new_status, error = resolve_status(status, row.get("parts_expected"), self.db.get_parts(msg_id))
        if new_status != status:
            self.db.update_message_status(msg_id, new_status, carrier_error=error)
        return new_status

    # ------------------------------------------------------------------ watchdog
    def _maybe_watchdog(self):
        now = time.time()
        if now - self._last_watchdog < WATCHDOG_INTERVAL:
            return
        self._last_watchdog = now
        self.run_watchdog(now)

    def run_watchdog(self, now: Optional[float] = None) -> int:
        """Mark messages stuck in 'submitted' (real provider only) as 'unknown'."""
        if not getattr(self.provider, "supports_receipts", False):
            return 0   # without receipts 'submitted' is the best truth we have; do not guess
        now = now or time.time()
        return self.db.expire_submitted(
            now - self.sent_timeout,
            "No radio result received; the message may or may not have been sent")

    def _notify(self, msg_id: str, status: str):
        if self.notify:
            try:
                self.notify(msg_id, status)
            except Exception:
                pass
