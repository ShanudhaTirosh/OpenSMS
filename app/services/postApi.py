import hashlib
import secrets
import asyncio
import re
import time
from threading import Thread
import sys
from os.path import dirname, abspath, join, exists
import json


from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
import uvicorn

# local imports
from services.smsApi import send_sms
from services.pathMgr import get_user_data_dir
from services.logSvc import LogService

## global vars / obj
app_name = "opensms"
api_os_flavor = "linux"
logger = None

# Set the path
config_dir = "./config"

# Rate limiting / brute-force protection
FAILED_AUTH_ATTEMPTS: dict[str, list[float]] = {}
MAX_FAILED_ATTEMPTS = 10
AUTH_LOCKOUT_WINDOW_SECONDS = 60.0

## Functions

def set_config_path(config_path: str):
    global config_dir
    config_dir = config_path

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

def generate_new_api_key() -> str:
    # Generate a high-entropy secret token
    new_raw_key = secrets.token_urlsafe(32)
    new_raw_key = f"osms_{new_raw_key}"
    # Hash and store in your DB
    new_hashed_key = hash_api_key(new_raw_key)
    app_api_keys = {
        new_hashed_key: {
            "name": "opensms",
            "scopes": ["sms:write"],
            "created_at": time.time()
        }
    }
    keys_path = join(config_dir, "keys.json")
    with open(keys_path, "w") as kf:
        json.dump(app_api_keys, kf, indent=2)
    print("Created/updated the API key")
    log_activities("Created/updated the API key")
    return new_raw_key

def get_api_keys() -> dict:
    keys_path = join(config_dir, "keys.json")
    api_keys = {}
    if exists(keys_path):
        try:
            with open(keys_path, "r") as kf:
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
app = FastAPI(title="OpenSMS API", version="0.3.0")
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

    # Periodic cleanup of stale rate-limit entries to prevent memory leak
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
        "version": "0.3.0",
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
    print(f"Authenticated request from: {client_ip}")
    log_activities(f"Authenticated request from: {client_ip} to send SMS to {item.number}")

    stat = send_sms(item.number, item.text)
    if stat:
        print(f"SMS successfully sent to: {item.number}")
        log_activities(f"SMS successfully sent to: {item.number}")
    else:
        print(f"SMS failed to: {item.number}")
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

    if server and server.kivyCallback:
        Thread(
            target=server.kivyCallback,
            kwargs={"stat": True, "count": 1},
            daemon=True
        ).start()

    return {
        "stat": True,
        "message": f"SMS sent successfully to {item.number}",
        "recipient": item.number
    }

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

    for idx, item in enumerate(batch.messages):
        stat = send_sms(item.number, item.text)
        results.append({
            "number": item.number,
            "stat": stat
        })
        if not stat:
            failed_count += 1
        # Rate-pacing delay (100ms) to prevent baseband buffer saturation
        if idx < total - 1:
            await asyncio.sleep(0.1)

    successful_count = total - failed_count
    log_activities(f"Batch SMS processed: {successful_count}/{total} succeeded")

    if server and server.kivyCallback:
        Thread(
            target=server.kivyCallback,
            kwargs={"stat": (failed_count == 0), "count": successful_count},
            daemon=True
        ).start()

    return {
        "total": total,
        "successful": successful_count,
        "failed": failed_count,
        "results": results
    }

@app.post("/control/")
async def internal_control(
    item: ControlData,
    request: Request,
    client: dict = Depends(verify_api_key)
):
    server = getattr(request.app.state, "server", None)
    return {"status": "ok", "action": item.api}

# test locally
if __name__ == "__main__":
    apiServ = PosiApiServer()
    apiServ.start()

