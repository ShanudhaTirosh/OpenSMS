import hashlib
import secrets
import asyncio
import re
import os
from threading import Thread
from os.path import dirname, abspath, join, exists
import json
import uuid

from fastapi import FastAPI, Request, HTTPException, Depends, status, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
import uvicorn

# local imports
from services.smsApi import send_sms, calculate_sms_segments, get_active_sims_with_status, validate_sim_slot, get_provider
from services.messageSvc import MessageService, QueueFull
from services import smsReceipts
from concurrent.futures import ThreadPoolExecutor
from services.logSvc import LogService, AsyncLogWriter, mask_phone
from services import authSvc
from app_version import __version__
from services.authSvc import (
    FAILED_AUTH_ATTEMPTS,  # noqa: F401  (re-exported: tests and the UI inspect postApi.FAILED_AUTH_ATTEMPTS)
    SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN, DEFAULT_SCOPES, ALL_SCOPES,
)
from services.dbMgr import DatabaseManager
from services.updateMgr import UpdateManager

## global vars / obj
app_name = "opensms"
api_os_flavor = "linux"
logger = None

# Data directory and database are initialised lazily by set_config_path()/_db().
# Nothing is created at import time (audit issue DB-02).
config_dir: str | None = None
db_mgr: DatabaseManager | None = None
message_svc: MessageService | None = None
_receipt_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="opensms-receipts")
SUBMIT_WAIT_SECONDS = float(os.environ.get("OPENSMS_SUBMIT_WAIT_SECONDS", "15"))

MAX_SMS_TEXT_CHARS = 1600          # ~10 concatenated segments; longer messages cannot be delivered reliably
PUBLIC_DOCS = os.environ.get("OPENSMS_PUBLIC_DOCS", "0") == "1"
_log_writer = AsyncLogWriter()

## Functions

def set_config_path(config_path: str, register_receipts: bool = True):
    """register_receipts=False for the UI process: only the service owns the queue and processes SMS receipts."""
    global config_dir
    global db_mgr
    config_dir = config_path
    db_path = join(config_dir, "opensms.db")
    db_mgr = DatabaseManager.set_db_path(db_path)
    # One-time import of legacy keys.json into SQLite (file is renamed afterwards)
    db_mgr.migrate_legacy_keys_json(join(config_dir, "keys.json"))
    _reset_message_service(register_receipts=register_receipts)

def _reset_message_service(provider=None, register_receipts: bool = True):
    """(Re)create the message service for the current database. The worker starts lazily."""
    global message_svc
    if message_svc is not None:
        message_svc.stop()
    message_svc = MessageService(db_mgr, provider or get_provider())
    # Receipts (Android only; no-op elsewhere). The callback only hands work to a single thread.
    if register_receipts:
        smsReceipts.register_receiver(
            lambda kind, msg_id, part, ok, err, delivery: _receipt_pool.submit(
                lambda: message_svc and message_svc.on_receipt(kind, msg_id, part, ok, err, delivery)))

def _svc() -> MessageService:
    if message_svc is None:
        raise HTTPException(status_code=503, detail="Gateway storage is not initialised")
    message_svc.start()   # idempotent
    return message_svc

def _db() -> DatabaseManager:
    """Return the database, or fail with 503 if the gateway has not been configured yet."""
    if db_mgr is None:
        raise HTTPException(status_code=503, detail="Gateway storage is not initialised")
    return db_mgr

def set_api_os(os_flavour: str):
    global api_os_flavor
    api_os_flavor = os_flavour

def set_api_logger(log_obj: LogService):
    global logger
    logger = log_obj

def log_activities(message: str):
    if logger:
        _log_writer.submit(logger, message)

def hash_api_key(raw_key: str) -> str:
    """Hash the raw key using SHA-256."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

def generate_new_api_key(name: str = "Default Key", scopes: list[str] | None = None) -> str:
    """
    Create a new API key and return the raw secret (shown once, only the hash is stored).
    Existing keys are NOT invalidated; revoke them explicitly (see DELETE /keys/{id}).
    """
    scopes = [sc for sc in (scopes or DEFAULT_SCOPES) if sc in ALL_SCOPES] or list(DEFAULT_SCOPES)
    new_raw_key = f"osms_{secrets.token_urlsafe(32)}"
    _db().add_api_key(new_raw_key, name=name, scopes=scopes)
    log_activities(f"Created API key: {name} scopes={','.join(scopes)}")
    return new_raw_key

def get_api_keys() -> dict:
    """Active API keys as {key_id: metadata}. SQLite is the single source of truth."""
    if db_mgr is None:
        return {}
    return {k["id"]: k for k in db_mgr.list_api_keys() if k.get("is_active")}

# data formatting for request
PHONE_REGEX = re.compile(r'^\+?[0-9\s\-()]{7,25}$')

class SmsData(BaseModel):
    number: str
    text: str
    sub_text: str | None = None
    sim_slot: int | None = None

    @field_validator('number')
    @classmethod
    def validate_phone_number(cls, v: str) -> str:
        clean = v.strip()
        digits = re.sub(r'\D', '', clean)
        if not PHONE_REGEX.match(clean) or not (7 <= len(digits) <= 17):
            raise ValueError("Invalid phone number format. Must contain 7 to 17 digits.")
        return clean

    @field_validator('text')
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("SMS text cannot be empty.")
        if len(v) > MAX_SMS_TEXT_CHARS:
            raise ValueError(f"SMS text exceeds the maximum of {MAX_SMS_TEXT_CHARS} characters.")
        return v

class BatchSmsData(BaseModel):
    messages: list[SmsData]

    @field_validator('messages')
    @classmethod
    def validate_batch_size(cls, v: list[SmsData]) -> list[SmsData]:
        if not v:
            raise ValueError("Batch cannot be empty.")
        if len(v) > 100:
            raise ValueError("Batch size exceeds maximum limit of 100 messages per request.")
        return v

class ControlData(BaseModel):
    api: str

class NewKeyData(BaseModel):
    name: str = "API Key"
    scopes: list[str] = list(DEFAULT_SCOPES)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v or len(v) > 64:
            raise ValueError("Key name must be 1-64 characters.")
        return v

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in ALL_SCOPES]
        if bad or not v:
            raise ValueError(f"Scopes must be a non-empty subset of {sorted(ALL_SCOPES)}.")
        return v

# FastAPI app
# Interactive docs / OpenAPI are disabled unless OPENSMS_PUBLIC_DOCS=1 (audit issue SEC-08).
app = FastAPI(
    title="OpenSMS Gateway API", version=__version__,
    description="Privacy-first Android SMS Gateway REST API",
    docs_url="/docs" if PUBLIC_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if PUBLIC_DOCS else None,
)
# ---- Unified error envelope (additive: the legacy "detail" field is preserved) ----
_ERROR_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 422: "validation_error",
    429: "rate_limited", 502: "upstream_failure", 503: "service_unavailable",
}

class ApiError(HTTPException):
    """HTTPException with a machine-readable code."""
    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code

def _error_body(status_code: int, detail, code: str | None = None, message: str | None = None) -> dict:
    if message is None:
        message = detail if isinstance(detail, str) else "Request failed"
    return {"detail": detail, "error": {"code": code or _ERROR_CODES.get(status_code, "error"), "message": message}}

@app.exception_handler(StarletteHTTPException)
async def _http_error_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.status_code, exc.detail, getattr(exc, "code", None)),
        headers=getattr(exc, "headers", None),
    )

@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    message = f"{loc}: {first.get('msg', 'invalid request')}" if loc else first.get("msg", "invalid request")
    return JSONResponse(
        status_code=422,
        content=_error_body(422, jsonable_encoder(errors), "validation_error", message),
    )

security = HTTPBearer(auto_error=False)

# api server class with callback function
class PosiApiServer:

    def __init__(self, host="0.0.0.0", port=9292):
        self.host = host
        self.port = port
        self.kivyCallback = None
        self.controlCallback = None
        self.server: uvicorn.Server | None = None
        self.thread: Thread | None = None
        self.last_error: str | None = None

    def set_control_caller(self, callback=None):
        self.controlCallback = callback

    def set_kivy_caller(self, callback=None):
        self.kivyCallback = callback

    def _run(self, port=None):
        actual_port = port if port else self.port
        self.last_error = None
        try:
            config = uvicorn.Config(
                app,
                host=self.host,
                port=actual_port,
                log_level="info",
                loop="asyncio"
            )
            self.server = uvicorn.Server(config)
            app.state.server = self
            asyncio.run(self.server.serve())
        except SystemExit as e:
            # uvicorn reports a failed bind (port in use, address not available) with sys.exit(1)
            # inside this thread; without this handler the failure was silent and the UI showed "started".
            if e.code not in (0, None):
                self.last_error = f"Could not bind {self.host}:{actual_port} (address or port unavailable)"
                print(self.last_error)
                log_activities(f"SERVER ERROR: {self.last_error}")
                if self.controlCallback:
                    self.controlCallback("bind_error", self.last_error)
        except OSError as e:
            self.last_error = f"Port bind conflict on {actual_port}: {e}"
            print(f"Error binding to port {actual_port}: {e}")
            log_activities(f"SERVER ERROR: {self.last_error}")
            if self.controlCallback:
                self.controlCallback("bind_error", str(e))
        except Exception as e:
            self.last_error = f"Server runtime error: {e}"
            print(f"Server exception: {e}")
            log_activities(f"SERVER ERROR: {self.last_error}")
            if self.controlCallback:
                self.controlCallback("error", str(e))
        finally:
            self.server = None

    def start(self, port=None):
        if self.thread and self.thread.is_alive():
            print("Server already running")
            return
        self.thread = Thread(
            target=self._run,
            kwargs={"port": port},
            daemon=True
        )
        self.thread.start()
        print("FastAPI started")

    def stop(self):
        if self.server:
            print("Stopping FastAPI...")
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.server = None
        self.thread = None
        print("FastAPI stopped")

# Auth verification with rate-limiting & scope enforcement
async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> dict:
    ip = authSvc.client_ip(request)

    if authSvc.check_lockout(ip):
        log_activities(f"Rate limit exceeded (too many failed auth) for IP: {ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Please try again later.",
            headers={"Retry-After": str(int(authSvc.AUTH_LOCKOUT_WINDOW_SECONDS))},
        )

    if not credentials or not credentials.credentials:
        authSvc.record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token header"
        )

    client_info = _db().verify_api_key(credentials.credentials)
    if not client_info:
        authSvc.record_failure(ip)
        log_activities(f"Authentication failed from IP: {ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    authSvc.clear_failures(ip)
    return client_info

def require_scope(scope: str):
    """Dependency factory: authenticate, then require `scope` (admin implies all)."""
    async def _dep(client: dict = Depends(verify_api_key)) -> dict:
        if not authSvc.has_scope(client, scope):
            raise ApiError(403, "insufficient_scope", f"API key lacks the required scope '{scope}'")
        return client
    return _dep

def _enforce_send_quota(client: dict, count: int):
    wait = authSvc.consume_send_quota(client["id"], count)
    if wait > 0:
        raise ApiError(429, "send_rate_limited",
                       "Send rate limit exceeded for this API key. Please slow down.",
                       headers={"Retry-After": str(int(wait) + 1)})

@app.get("/")
@app.get("/health/")
async def health_check():
    return {
        "status": "online",
        "app": "OpenSMS",
        "version": __version__,
        "service": "SMS Gateway"
    }

_IDEM_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.:]{1,128}$")

async def _idempotent(request: Request, client: dict, scope: str, body: dict, run):
    """
    Run `run()` at most once per (API key, Idempotency-Key). Without the header the request
    is executed normally. Replays return the original response and never send another SMS.
    """
    idem = request.headers.get("Idempotency-Key")
    if idem is None:
        return await run()
    if not _IDEM_KEY_RE.match(idem):
        raise ApiError(400, "invalid_idempotency_key",
                       "Idempotency-Key must be 1-128 characters of A-Z a-z 0-9 _ - . :")
    db = _db()
    req_hash = hashlib.sha256(json.dumps([scope, body], sort_keys=True, default=str).encode()).hexdigest()
    state, stored = db.idem_begin(client["id"], idem, req_hash)
    if state == "replay":
        return _respond(stored, replay=True)
    if state == "conflict":
        raise ApiError(422, "idempotency_key_reuse",
                       "This Idempotency-Key was already used with a different request body.")
    if state == "in_progress":
        raise ApiError(409, "request_in_progress",
                       "A request with this Idempotency-Key is still being processed.",
                       headers={"Retry-After": "2"})
    try:
        result = await run()
    except BaseException:
        db.idem_release(client["id"], idem)   # failed attempts may be retried with the same key
        raise
    db.idem_complete(client["id"], idem, result)
    return result

def _notify_ui(request: Request, stat: bool, count: int):
    server = getattr(request.app.state, "server", None)
    if server and server.kivyCallback:
        Thread(target=server.kivyCallback, kwargs={"stat": stat, "count": count}, daemon=True).start()

def _dispatch_one(db: DatabaseManager, item: SmsData, batch_id: str | None = None) -> tuple[str, dict, bool]:
    """Record + send one message. Returns (msg_id, segment_info, handed_to_telephony)."""
    seg_info = calculate_sms_segments(item.text)
    sim_slot = item.sim_slot if item.sim_slot is not None else -1
    msg_id = str(uuid.uuid4())
    db.create_message(
        recipient=item.number, text=item.text, encoding=seg_info["encoding"],
        segments=seg_info["segments"], sim_slot=sim_slot, status="sending",
        batch_id=batch_id, msg_id=msg_id,
    )
    ok = send_sms(item.number, item.text, sim_slot=sim_slot, msg_id=msg_id)
    if ok:
        # NOTE: "sent" means the message was handed to Android's SmsManager. It is NOT a delivery
        # confirmation, so delivered_at stays empty (audit issue SMS-01; receipts arrive in Stage 4).
        db.update_message_status(msg_id, "sent")
    else:
        db.update_message_status(msg_id, "failed", carrier_error="Telephony dispatch failed")
    return msg_id, seg_info, ok

def _respond(payload: dict, replay: bool = False):
    """Turn a stored/returned payload into an HTTP response (honours the internal _http_status)."""
    payload = dict(payload)
    code = payload.pop("_http_status", 200)
    headers = {"Idempotent-Replay": "true"} if replay else None
    return JSONResponse(status_code=code, content=payload, headers=headers)

def _prepare(db: DatabaseManager, item: SmsData, batch_id: str | None = None, msg_id: str | None = None) -> str:
    """Validate the SIM, then persist the message as 'queued'. Returns the message id."""
    sim_slot = item.sim_slot if item.sim_slot is not None else -1
    try:
        validate_sim_slot(sim_slot)
    except ValueError as e:
        raise ApiError(422, "invalid_sim_slot", str(e))
    seg_info = calculate_sms_segments(item.text)
    msg_id = msg_id or str(uuid.uuid4())
    db.create_message(
        recipient=item.number, text=item.text, encoding=seg_info["encoding"],
        segments=seg_info["segments"], sim_slot=sim_slot, status="queued",
        batch_id=batch_id, msg_id=msg_id, provider=_svc().provider.name,
    )
    return msg_id

def accept_local_message(payload: dict) -> str:
    """
    Take a message composed in the app (see services/outbox.py) into the normal pipeline.
    Idempotent on the message id, so a crash after acceptance can never send twice.
    """
    from services.outbox import OutboxRetry
    db = _db()
    svc = _svc()
    try:
        msg_id = str(uuid.UUID(str(payload["id"])))
    except (KeyError, ValueError):
        msg_id = str(uuid.uuid4())
    if db.get_message(msg_id):
        return msg_id                                   # already accepted earlier
    item = SmsData(number=payload["number"], text=payload["text"], sim_slot=payload.get("sim_slot", -1))
    if svc.free_slots() < 1:
        raise OutboxRetry()
    try:
        _prepare(db, item, msg_id=msg_id)
    except ApiError as e:                               # e.g. inactive SIM: show it in history as failed, with the reason
        seg = calculate_sms_segments(item.text)
        db.create_message(recipient=item.number, text=item.text, encoding=seg["encoding"], segments=seg["segments"],
                          sim_slot=item.sim_slot if item.sim_slot is not None else -1, status="failed",
                          msg_id=msg_id, provider=svc.provider.name)
        db.update_message_status(msg_id, "failed", carrier_error=str(e.detail))
        return msg_id
    try:
        svc.enqueue(msg_id, item.number, item.text, item.sim_slot if item.sim_slot is not None else -1)
    except QueueFull:
        db.update_message_status(msg_id, "failed", carrier_error="Send queue full")
        raise OutboxRetry()
    log_activities(f"Message queued from the app for: {mask_phone(item.number)} (id: {msg_id})")
    return msg_id

def _queue_full():
    return ApiError(503, "queue_full", "The send queue is full. Please retry shortly.",
                    headers={"Retry-After": "5"})

@app.post("/sms/")
async def process_sms_req(
    item: SmsData,
    request: Request,
    client: dict = Depends(require_scope(SCOPE_WRITE))
):
    res = await _idempotent(request, client, "sms", item.model_dump(),
                            lambda: _send_single(item, request, client))
    return _respond(res) if isinstance(res, dict) else res

async def _send_single(item: SmsData, request: Request, client: dict):
    db = _db()
    svc = _svc()
    if svc.free_slots() < 1:
        raise _queue_full()
    _enforce_send_quota(client, 1)
    log_activities(f"Authenticated request from: {authSvc.client_ip(request)} to send SMS to {mask_phone(item.number)}")

    msg_id = _prepare(db, item)
    seg_info = calculate_sms_segments(item.text)
    try:
        fut = svc.enqueue(msg_id, item.number, item.text, item.sim_slot if item.sim_slot is not None else -1)
    except QueueFull:
        db.update_message_status(msg_id, "failed", carrier_error="Send queue full")
        raise _queue_full()

    try:
        outcome = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(fut)), timeout=SUBMIT_WAIT_SECONDS)
    except asyncio.TimeoutError:
        outcome = None

    if outcome is None:  # accepted, still waiting for the worker
        log_activities(f"SMS queued for: {mask_phone(item.number)} (id: {msg_id})")
        return {
            "_http_status": 202, "stat": True, "id": msg_id, "status": "queued",
            "delivery_confirmed": False,
            "message": f"SMS accepted and queued for {item.number} (not yet handed to the telephony service)",
            "recipient": item.number, "segments": seg_info["segments"], "encoding": seg_info["encoding"],
        }

    if outcome["status"] == "failed":
        log_activities(f"SMS failed to: {mask_phone(item.number)}")
        _notify_ui(request, False, 1)
        raise ApiError(502, "delivery_failed",
                       f"SMS to {item.number} failed on telephony service: {outcome.get('error') or 'unknown error'}")

    log_activities(f"SMS handed to telephony for: {mask_phone(item.number)} (id: {msg_id})")
    _notify_ui(request, True, 1)
    return {
        "stat": True, "id": msg_id, "status": outcome["status"],
        "delivery_confirmed": outcome["status"] == "delivered",
        "message": f"SMS submitted to the telephony service for {item.number} (delivery not confirmed)",
        "recipient": item.number, "segments": seg_info["segments"], "encoding": seg_info["encoding"],
    }

@app.post("/sms/batch/")
async def process_batch_sms_req(
    batch: BatchSmsData,
    request: Request,
    client: dict = Depends(require_scope(SCOPE_WRITE))
):
    res = await _idempotent(request, client, "batch", batch.model_dump(),
                            lambda: _send_batch(batch, request, client))
    return _respond(res) if isinstance(res, dict) else res

async def _send_batch(batch: BatchSmsData, request: Request, client: dict):
    db = _db()
    svc = _svc()
    total = len(batch.messages)
    if svc.free_slots() < total:
        raise _queue_full()
    # validate every SIM slot BEFORE anything is stored or sent
    for item in batch.messages:
        try:
            validate_sim_slot(item.sim_slot if item.sim_slot is not None else -1)
        except ValueError as e:
            raise ApiError(422, "invalid_sim_slot", str(e))
    _enforce_send_quota(client, total)
    batch_id = str(uuid.uuid4())

    entries = []
    for item in batch.messages:
        msg_id = _prepare(db, item, batch_id=batch_id)
        entries.append((item, msg_id, svc.enqueue(msg_id, item.number, item.text,
                                                  item.sim_slot if item.sim_slot is not None else -1)))

    wait = max(SUBMIT_WAIT_SECONDS, 0.25 * total + 5)
    async def _outcome(fut):
        try:
            return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(fut)), timeout=wait)
        except asyncio.TimeoutError:
            return None
    outcomes = await asyncio.gather(*[_outcome(f) for _, _, f in entries])

    results, failed_count, pending = [], 0, 0
    for (item, msg_id, _), out in zip(entries, outcomes):
        if out is None:
            pending += 1
            results.append({"id": msg_id, "number": item.number, "stat": True, "status": "queued"})
        elif out["status"] == "failed":
            failed_count += 1
            results.append({"id": msg_id, "number": item.number, "stat": False, "status": "failed",
                            "error": out.get("error")})
        else:
            results.append({"id": msg_id, "number": item.number, "stat": True, "status": out["status"]})

    successful_count = total - failed_count
    log_activities(f"Batch SMS processed ({batch_id}): {successful_count}/{total} accepted, {pending} still queued")
    _notify_ui(request, failed_count == 0, successful_count)
    return {
        "batch_id": batch_id, "total": total, "successful": successful_count,
        "failed": failed_count, "pending": pending, "delivery_confirmed": False, "results": results,
    }

# NOTE: /sms/history MUST be declared before /sms/{msg_id}, otherwise the path parameter
# captures the word "history" (audit issue API-01).
@app.get("/sms/history")
@app.get("/sms/history/")
async def list_message_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str = Query("all"),
    search: str | None = Query(None, max_length=100),
    client: dict = Depends(require_scope(SCOPE_READ))
):
    db = _db()
    messages = db.get_messages(limit=limit, offset=offset, status=status, search=search)
    total = db.count_messages(status=status, search=search)
    return {
        "count": len(messages), "total": total, "offset": offset, "limit": limit,
        "has_more": offset + len(messages) < total, "messages": messages,
    }

@app.get("/sms/{msg_id}")
async def get_message_status(
    msg_id: str,
    client: dict = Depends(require_scope(SCOPE_READ))
):
    db = _db()
    msg = db.get_message(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail=f"Message ID '{msg_id}' not found")
    msg["parts"] = db.get_parts(msg_id)
    msg["delivery_confirmed"] = msg.get("status") == "delivered"
    return msg

@app.get("/system/stats/")
async def get_system_stats(client: dict = Depends(require_scope(SCOPE_READ))):
    return {
        "app": "OpenSMS",
        "version": __version__,
        "metrics": _db().get_metrics()
    }

@app.get("/system/sims/")
async def get_system_sims(client: dict = Depends(require_scope(SCOPE_READ))):
    sims, reliable = get_active_sims_with_status()
    # reliable=false: Android could not be asked (usually the Phone permission is missing); `sims` is a placeholder
    return {"count": len(sims), "reliable": reliable, "sims": sims}

@app.get("/system/update/")
async def check_app_update(client: dict = Depends(require_scope(SCOPE_READ))):
    return UpdateManager.check_for_updates(__version__)

# ---- API key management (admin scope) ------------------------------------
@app.get("/keys/")
async def list_keys(client: dict = Depends(require_scope(SCOPE_ADMIN))):
    keys = _db().list_api_keys()
    return {"count": len(keys), "keys": keys}

@app.post("/keys/", status_code=201)
async def create_key(body: NewKeyData, client: dict = Depends(require_scope(SCOPE_ADMIN))):
    raw = generate_new_api_key(body.name, body.scopes)
    # The secret is returned exactly once and never stored in plain text.
    return {"key": raw, "name": body.name, "scopes": body.scopes}

@app.delete("/keys/{key_id}")
async def revoke_key(key_id: str, client: dict = Depends(require_scope(SCOPE_ADMIN))):
    db = _db()
    if key_id == client.get("id"):
        raise HTTPException(status_code=409, detail="A key cannot revoke itself.")
    if not db.get_api_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    db.revoke_api_key(key_id)
    log_activities(f"Revoked API key: {key_id}")
    return {"revoked": True, "id": key_id}

# ---- machine-readable docs (authenticated unless OPENSMS_PUBLIC_DOCS=1) ----
async def _docs_access(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if PUBLIC_DOCS:
        return None
    client = await verify_api_key(request, credentials)
    if not authSvc.has_scope(client, SCOPE_READ):
        raise HTTPException(status_code=403, detail="API key lacks the required scope 'sms:read'")
    return client

def _repo_root() -> str:
    return dirname(dirname(dirname(abspath(__file__))))

def _read_first(paths: list[str], fallback: str) -> str:
    for p in paths:
        if exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return fallback

@app.get("/llms.txt", response_class=PlainTextResponse)
async def get_llms_txt(_: object = Depends(_docs_access)):
    """Serve llms.txt to AI agents / LLMs."""
    return _read_first(
        [join(_repo_root(), "llms.txt"), join(_repo_root(), "docs", "llms.txt")]
        + ([join(config_dir, "llms.txt")] if config_dir else []),
        "# OpenSMS API for LLMs & AI Agents\n\nBase URL: http://<DEVICE_IP>:9292\nAuth: Bearer <API_KEY>\n"
        "Endpoints: POST /sms/, POST /sms/batch/, GET /sms/{id}, GET /system/stats/",
    )

@app.get("/docs/markdown", response_class=PlainTextResponse)
@app.get("/docs/ai", response_class=PlainTextResponse)
async def get_markdown_docs(_: object = Depends(_docs_access)):
    """Serve the Markdown API reference."""
    return _read_first(
        [join(_repo_root(), "docs", "api-reference.md")] + ([join(config_dir, "api-reference.md")] if config_dir else []),
        "# OpenSMS API Reference\n\nEndpoints:\n- POST /sms/\n- POST /sms/batch/\n- GET /sms/{id}\n- GET /system/stats/",
    )

@app.post("/control/")
async def internal_control(
    item: ControlData,
    request: Request,
    client: dict = Depends(require_scope(SCOPE_ADMIN))
):
    # Reserved no-op (see audit issue API-04); now admin-only. Candidate for removal.
    return {"status": "ok", "action": item.api}

# test locally
if __name__ == "__main__":
    apiServ = PosiApiServer()
    apiServ.start()
