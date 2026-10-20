import hashlib
import secrets
import asyncio
import re
import time
from threading import Thread
import sys
from os.path import dirname, abspath, join, exists
import json
import uuid

from fastapi import FastAPI, Request, HTTPException, Depends, status, Query
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
import uvicorn

# local imports
from services.smsApi import send_sms, calculate_sms_segments, get_active_sims
from services.pathMgr import get_user_data_dir
from services.logSvc import LogService
from services.dbMgr import DatabaseManager
from services.updateMgr import UpdateManager

## global vars / obj
app_name = "opensms"
api_os_flavor = "linux"
logger = None

# Set the path
config_dir = "./config"
db_mgr: DatabaseManager = DatabaseManager.get_instance(config_dir)

# Rate limiting / brute-force protection
FAILED_AUTH_ATTEMPTS: dict[str, list[float]] = {}
MAX_FAILED_ATTEMPTS = 10
AUTH_LOCKOUT_WINDOW_SECONDS = 60.0

## Functions

def set_config_path(config_path: str):
    global config_dir
    global db_mgr
    config_dir = config_path
    db_path = join(config_dir, "opensms.db")
    db_mgr = DatabaseManager.set_db_path(db_path)
    # Migrate any legacy keys from keys.json into SQLite
    db_mgr.migrate_legacy_keys_json(join(config_dir, "keys.json"))

def set_api_os(os_flavour: str):
    global api_os_flavor
    api_os_flavor = os_flavour

def set_api_logger(log_obj: LogService):
    global logger
    logger = log_obj

def log_activities(message: str):
    if logger:
        Thread(
            target=logger.write_log,
            kwargs={"message": message},
            daemon=True
        ).start()

def hash_api_key(raw_key: str) -> str:
    """Hash the raw key using SHA-256."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

def generate_new_api_key(name: str = "Default Key") -> str:
    global db_mgr
    # Generate high-entropy secret token
    new_raw_key = f"osms_{secrets.token_urlsafe(32)}"
    new_hashed_key = hash_api_key(new_raw_key)

    # Store in SQLite
    if db_mgr:
        db_mgr.add_api_key(new_raw_key, name=name, scopes=["sms:write", "sms:read"])

    # Synchronize with legacy keys.json for backwards compatibility
    app_api_keys = {
        new_hashed_key: {
            "name": name,
            "scopes": ["sms:write", "sms:read"],
            "created_at": time.time()
        }
    }
    keys_path = join(config_dir, "keys.json")
    try:
        with open(keys_path, "w", encoding="utf-8") as kf:
            json.dump(app_api_keys, kf, indent=2)
    except Exception as e:
        print(f"Notice: legacy keys.json write error: {e}")

    print(f"Created API key: {name}")
    log_activities(f"Created/updated API key: {name}")
    return new_raw_key

def get_api_keys() -> dict:
    """Read API keys from legacy keys.json and SQLite."""
    keys_path = join(config_dir, "keys.json")
    api_keys = {}
    if exists(keys_path):
        try:
            with open(keys_path, "r", encoding="utf-8") as kf:
                api_keys = json.load(kf)
        except Exception as e:
            print(f"Error loading API keys: {e}")
    return api_keys

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

# FastAPI app
app = FastAPI(title="OpenSMS Gateway API", version="0.4.0", description="Privacy-first Android SMS Gateway REST API")
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

# Auth verification with rate-limiting & timing-safe check
async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> dict:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Periodic cleanup of stale rate-limit entries
    if len(FAILED_AUTH_ATTEMPTS) > 200:
        cutoff = now - AUTH_LOCKOUT_WINDOW_SECONDS
        stale = [ip for ip, timestamps in list(FAILED_AUTH_ATTEMPTS.items()) if not timestamps or timestamps[-1] < cutoff]
        for ip in stale:
            FAILED_AUTH_ATTEMPTS.pop(ip, None)

    # Rate limiting on failed auth attempts
    attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(client_ip, []) if now - t < AUTH_LOCKOUT_WINDOW_SECONDS]
    FAILED_AUTH_ATTEMPTS[client_ip] = attempts

    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        log_activities(f"Rate limit exceeded (too many failed auth) for IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Please try again later."
        )

    if not credentials or not credentials.credentials:
        attempts.append(now)
        FAILED_AUTH_ATTEMPTS[client_ip] = attempts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token header"
        )

    raw_token = credentials.credentials

    # 1. Check SQLite database first
    client_info = None
    if db_mgr:
        client_info = db_mgr.verify_api_key(raw_token)

    # 2. Check legacy keys.json fallback
    if not client_info:
        hashed_token = hash_api_key(raw_token)
        app_api_keys = get_api_keys()
        client_info = app_api_keys.get(hashed_token)

    if not client_info:
        attempts.append(now)
        FAILED_AUTH_ATTEMPTS[client_ip] = attempts
        print(f"Authentication failed from IP: {client_ip}")
        log_activities(f"Authentication failed from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    # Reset failed attempts upon successful login
    if client_ip in FAILED_AUTH_ATTEMPTS:
        FAILED_AUTH_ATTEMPTS.pop(client_ip, None)

    return client_info

@app.get("/")
@app.get("/health/")
async def health_check():
    return {
        "status": "online",
        "app": "OpenSMS",
        "version": "0.4.0",
        "service": "SMS Gateway"
    }

@app.post("/sms/")
async def process_sms_req(
    item: SmsData,
    request: Request,
    client: dict = Depends(verify_api_key)
):
    server = getattr(request.app.state, "server", None)
    client_ip = request.client.host if request.client else "unknown"
    log_activities(f"Authenticated request from: {client_ip} to send SMS to {item.number}")

    # Calculate segmentation metrics
    seg_info = calculate_sms_segments(item.text)
    sim_slot = item.sim_slot if item.sim_slot is not None else -1

    # Record message in SQLite database
    msg_id = str(uuid.uuid4())
    if db_mgr:
        db_mgr.create_message(
            recipient=item.number,
            text=item.text,
            encoding=seg_info["encoding"],
            segments=seg_info["segments"],
            sim_slot=sim_slot,
            status="sending",
            msg_id=msg_id
        )

    stat = send_sms(item.number, item.text, sim_slot=sim_slot, msg_id=msg_id)

    if stat:
        if db_mgr:
            db_mgr.update_message_status(msg_id, "sent")
        log_activities(f"SMS successfully dispatched to: {item.number} (id: {msg_id})")
        if server and server.kivyCallback:
            Thread(
                target=server.kivyCallback,
                kwargs={"stat": True, "count": 1},
                daemon=True
            ).start()
        return {
            "stat": True,
            "id": msg_id,
            "message": f"SMS sent successfully to {item.number}",
            "recipient": item.number,
            "segments": seg_info["segments"],
            "encoding": seg_info["encoding"]
        }
    else:
        if db_mgr:
            db_mgr.update_message_status(msg_id, "failed", carrier_error="Telephony dispatch failed")
        log_activities(f"SMS failed to: {item.number}")
        if server and server.kivyCallback:
            Thread(
                target=server.kivyCallback,
                kwargs={"stat": False, "count": 1},
                daemon=True
            ).start()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SMS delivery to {item.number} failed on telephony service."
        )

@app.post("/sms/batch/")
async def process_batch_sms_req(
    batch: BatchSmsData,
    request: Request,
    client: dict = Depends(verify_api_key)
):
    server = getattr(request.app.state, "server", None)
    results = []
    failed_count = 0
    total = len(batch.messages)
    batch_id = str(uuid.uuid4())

    for idx, item in enumerate(batch.messages):
        msg_id = str(uuid.uuid4())
        seg_info = calculate_sms_segments(item.text)
        sim_slot = item.sim_slot if item.sim_slot is not None else -1

        if db_mgr:
            db_mgr.create_message(
                recipient=item.number,
                text=item.text,
                encoding=seg_info["encoding"],
                segments=seg_info["segments"],
                sim_slot=sim_slot,
                status="sending",
                batch_id=batch_id,
                msg_id=msg_id
            )

        stat = send_sms(item.number, item.text, sim_slot=sim_slot, msg_id=msg_id)
        if stat:
            if db_mgr:
                db_mgr.update_message_status(msg_id, "sent")
            results.append({"id": msg_id, "number": item.number, "stat": True})
        else:
            if db_mgr:
                db_mgr.update_message_status(msg_id, "failed", carrier_error="Carrier dispatch failed")
            results.append({"id": msg_id, "number": item.number, "stat": False})
            failed_count += 1

        # Rate-pacing delay (100ms) to prevent baseband radio saturation
        if idx < total - 1:
            await asyncio.sleep(0.1)

    successful_count = total - failed_count
    log_activities(f"Batch SMS processed ({batch_id}): {successful_count}/{total} succeeded")

    if server and server.kivyCallback:
        Thread(
            target=server.kivyCallback,
            kwargs={"stat": (failed_count == 0), "count": successful_count},
            daemon=True
        ).start()

    return {
        "batch_id": batch_id,
        "total": total,
        "successful": successful_count,
        "failed": failed_count,
        "results": results
    }

@app.get("/sms/{msg_id}")
async def get_message_status(
    msg_id: str,
    client: dict = Depends(verify_api_key)
):
    if not db_mgr:
        raise HTTPException(status_code=500, detail="Database uninitialized")
    msg = db_mgr.get_message(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail=f"Message ID '{msg_id}' not found")
    return msg

@app.get("/sms/history/")
async def list_message_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str = Query("all"),
    search: str | None = None,
    client: dict = Depends(verify_api_key)
):
    if not db_mgr:
        return {"total": 0, "messages": []}
    messages = db_mgr.get_messages(limit=limit, offset=offset, status=status, search=search)
    return {"count": len(messages), "offset": offset, "limit": limit, "messages": messages}

@app.get("/system/stats/")
async def get_system_stats(client: dict = Depends(verify_api_key)):
    metrics = db_mgr.get_metrics() if db_mgr else {}
    return {
        "app": "OpenSMS",
        "version": "0.4.0",
        "metrics": metrics
    }

@app.get("/system/sims/")
async def get_system_sims(client: dict = Depends(verify_api_key)):
    sims = get_active_sims()
    return {"count": len(sims), "sims": sims}

@app.get("/system/update/")
async def check_app_update(client: dict = Depends(verify_api_key)):
    return UpdateManager.check_for_updates("0.4.0")

@app.get("/llms.txt", response_class=PlainTextResponse)
async def get_llms_txt():
    """Serve standard llms.txt directly to AI agents / LLMs."""
    possible_paths = [
        join(dirname(dirname(dirname(abspath(__file__)))), "llms.txt"),
        join(dirname(dirname(dirname(abspath(__file__)))), "docs", "llms.txt"),
        join(config_dir, "llms.txt")
    ]
    for p in possible_paths:
        if exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return "# OpenSMS API for LLMs & AI Agents\n\nBase URL: http://<DEVICE_IP>:9292\nAuth: Bearer <API_KEY>\nEndpoints: POST /sms/, POST /sms/batch/, GET /sms/{id}, GET /system/stats/"

@app.get("/docs/markdown", response_class=PlainTextResponse)
@app.get("/docs/ai", response_class=PlainTextResponse)
async def get_markdown_docs():
    """Serve full Markdown API docs directly over HTTP for LLMs and developers."""
    possible_paths = [
        join(dirname(dirname(dirname(abspath(__file__)))), "docs", "api-reference.md"),
        join(config_dir, "api-reference.md")
    ]
    for p in possible_paths:
        if exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return "# OpenSMS API Reference\n\nEndpoints:\n- POST /sms/\n- POST /sms/batch/\n- GET /sms/{id}\n- GET /system/stats/"

@app.post("/control/")
async def internal_control(
    item: ControlData,
    request: Request,
    client: dict = Depends(verify_api_key)
):
    return {"status": "ok", "action": item.api}

# test locally
if __name__ == "__main__":
    apiServ = PosiApiServer()
    apiServ.start()
