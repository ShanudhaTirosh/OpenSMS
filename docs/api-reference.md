# OpenSMS REST API Reference

The OpenSMS REST API allows applications, backends, scripts, and AI agents to dispatch SMS messages, track delivery lifecycle, and monitor cellular status directly through an Android device.

- **Base URL**: `http://<DEVICE_IP>:9292` (Port default: `9292`, configurable in Settings)
- **Content-Type**: `application/json`
- **Current App Version**: `0.4.0`

---

## 🔐 Authentication

All API endpoints (except `/health/` and `/llms.txt`) require Bearer token authentication:

```http
Authorization: Bearer <YOUR_API_KEY>
```

API tokens are cryptographically generated (prefix `osms_...`) and hashed with SHA-256 before persistence in SQLite. You can generate and view your API key on the OpenSMS Android app interface under **Start Server** or **Settings**.

### Rate Limiting & Protection
- To protect against brute-force attacks on cellular hardware, the gateway enforces IP rate-limiting on failed authentication attempts.
- **Limit**: 10 failed authorization attempts per client address within a 60-second sliding window. The address is the socket peer; `X-Forwarded-For` is ignored.
- **Response**: HTTP `429 Too Many Requests` with `Retry-After: 60`.
- **Send limit**: separately, each API key may send at most 300 messages per minute (`429` `send_rate_limited` with `Retry-After`).

---

## 📡 Endpoints

### 1. Send Single SMS
Dispatches an SMS to a single recipient.

- **Method**: `POST`
- **Path**: `/sms/`
- **Scopes**: `sms:write`

#### Request Headers
```http
Content-Type: application/json
Authorization: Bearer osms_your_secret_key
```

#### Request Body
| Field | Type | Required | Description |
|---|---|---|---|
| `number` | string | **Yes** | Destination phone number (e.g. `+1234567890`). Spaces, hyphens, and brackets are automatically stripped. |
| `text` | string | **Yes** | Message text body. Can be plain text or Unicode/emojis. |
| `sim_slot` | integer | No | Carrier SIM slot index (`0` for SIM 1, `1` for SIM 2). Defaults to device preferred SIM slot. |

```json
{
  "number": "+1234567890",
  "text": "Your verification code is 849201. Do not share this code.",
  "sim_slot": 0
}
```

#### Response (`200 OK`)
```json
{
  "stat": true,
  "id": "3f2b8c1a-9d4e-4a6b-8c2d-7e1f0a5b9c42",
  "status": "submitted",
  "delivery_confirmed": false,
  "message": "SMS submitted to the telephony service for +1234567890 (delivery not confirmed)",
  "recipient": "+1234567890",
  "segments": 1,
  "encoding": "GSM-7"
}
```
`stat: true` means the message was accepted and handed to Android. It never means delivered. If the send worker is busy for more than 15 seconds the response is `202 Accepted` with `"status": "queued"`; poll `GET /sms/{id}`. Send an `Idempotency-Key` header to make retries safe (see below).

#### Error Responses
Every error has the legacy `detail` field plus `error: {code, message}`.
- `401 Unauthorized` (`unauthorized`): missing or invalid API key.
- `403 Forbidden` (`insufficient_scope`): the key lacks `sms:write`.
- `422 Unprocessable Entity` (`validation_error` / `invalid_sim_slot` / `idempotency_key_reuse`): invalid number, text over 1600 characters, inactive SIM slot, reused idempotency key with a different body.
- `429 Too Many Requests` (`rate_limited` / `send_rate_limited`): too many failed authentications, or the per-key send limit; see `Retry-After`.
- `502 Bad Gateway` (`delivery_failed`): the hand-off to the telephony layer failed; the reason is in `detail`.
- `503 Service Unavailable` (`queue_full`): the send queue is full; retry after `Retry-After`.

---

### 2. Send Batch SMS
Dispatches multiple SMS messages sequentially with built-in hardware pacing (100ms) to prevent cellular carrier throttling and baseband saturation.

- **Method**: `POST`
- **Path**: `/sms/batch/`
- **Scopes**: `sms:write`

#### Request Body
| Field | Type | Required | Description |
|---|---|---|---|
| `messages` | array of objects | **Yes** | Array of message objects (maximum 100 items per request). |
| `sim_slot` | integer | No | Global fallback SIM slot for items that do not specify their own. |

```json
{
  "sim_slot": 0,
  "messages": [
    {
      "number": "+1234567890",
      "text": "System maintenance scheduled tonight at 02:00 UTC."
    },
    {
      "number": "+1987654321",
      "text": "System maintenance scheduled tonight at 02:00 UTC."
    }
  ]
}
```

#### Response (`200 OK`)
```json
{
  "batch_id": "batch_3d810a9f24",
  "total": 2,
  "successful": 2,
  "failed": 0,
  "results": [
    {
      "id": "msg_01a8f92e4",
      "number": "+1234567890",
      "stat": true
    },
    {
      "id": "msg_02b9f93c5",
      "number": "+1987654321",
      "stat": true
    }
  ]
}
```

---

### 3. Get SMS Status by ID
Retrieves the persistent delivery status and lifecycle metadata for a previously dispatched message.

- **Method**: `GET`
- **Path**: `/sms/{id}`
- **Scopes**: `sms:read`

#### Path Parameters
| Parameter | Type | Required | Description |
|---|---|---|---|
| `id` | string | **Yes** | The message ID returned by `POST /sms/` (a UUID). |

#### Response (`200 OK`)
```json
{
  "id": "3f2b8c1a-9d4e-4a6b-8c2d-7e1f0a5b9c42",
  "recipient": "+1234567890",
  "text": "Your verification code is 849201.",
  "encoding": "GSM-7",
  "segments": 1,
  "sim_slot": 0,
  "status": "sent",
  "batch_id": null,
  "created_at": 1729432800.12,
  "updated_at": 1729432801.45,
  "delivered_at": null,
  "carrier_error": null,
  "provider": "android",
  "parts_expected": 1,
  "parts": [{"part": 0, "sent_ok": 1, "sent_error": null, "delivery": null, "updated_at": 1729432801.45}],
  "delivery_confirmed": false
}
```

#### Message Status Values
See **Message lifecycle** at the end of this document: `queued`, `submitted`, `sent`, `delivered`, `failed`, `unknown`. Only `delivered` (with `delivered_at` set) is a delivery confirmation.

---

### 4. List SMS History
Retrieves paginated historical SMS messages with status filtering and text search.

- **Method**: `GET`
- **Path**: `/sms/history/`
- **Scopes**: `sms:read`

#### Query Parameters
| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | integer | `50` | Maximum records to return (1 to 200). |
| `offset` | integer | `0` | Number of records to skip for pagination. |
| `status` | string | `all` | Filter by status: `all`, `sent`, `failed`, or `queued`. |
| `search` | string | none | Keyword matching recipient phone number or message body snippet. |

#### Response (`200 OK`)
```json
{
  "count": 2,
  "offset": 0,
  "limit": 50,
  "messages": [
    {
      "id": "3f2b8c1a-9d4e-4a6b-8c2d-7e1f0a5b9c42",
      "recipient": "+1234567890",
      "text": "Alert: Sensor threshold exceeded",
      "status": "sent",
      "encoding": "GSM-7",
      "segments": 1,
      "sim_slot": 0,
      "created_at": 1729432800.12,
      "delivered_at": null
    }
  ]
}
```

---

### 5. Get System Telemetry & Metrics
Returns live gateway operational metrics, Sent Today counters, success rate percentages, and active queue depth.

- **Method**: `GET`
- **Path**: `/system/stats/`
- **Scopes**: `sms:read`

#### Response (`200 OK`)
```json
{
  "app": "OpenSMS",
  "version": "0.4.0",
  "metrics": {
    "sent_today": 142,
    "failed_today": 1,
    "success_rate": 99.3,
    "queue_depth": 0
  }
}
```

---

### 6. List Active Cellular SIM Slots
Inspects active cellular SIM cards and network operators on the device.

- **Method**: `GET`
- **Path**: `/system/sims/`
- **Scopes**: `sms:read`

#### Response (`200 OK`)
```json
{
  "count": 2,
  "sims": [
    {
      "slot": 0,
      "carrier": "T-Mobile",
      "country": "us",
      "active": true
    },
    {
      "slot": 1,
      "carrier": "AT&T",
      "country": "us",
      "active": true
    }
  ]
}
```

---

### 7. Check for GitHub Updates
Queries GitHub Releases to check if a newer OpenSMS APK is available.

- **Method**: `GET`
- **Path**: `/system/update/`
- **Scopes**: `sms:read`

#### Response (`200 OK`)
```json
{
  "success": true,
  "has_update": false,
  "current_version": "0.4.0",
  "latest_version": "0.4.0",
  "tag_name": "v0.4.0",
  "release_name": "OpenSMS v0.4.0",
  "release_notes": "Added SQLite WAL persistence, Dual-SIM routing, and auto-updater.",
  "html_url": "https://github.com/ShanudhaTirosh/OpenSMS/releases/tag/v0.4.0",
  "apk_url": "https://github.com/ShanudhaTirosh/OpenSMS/releases/download/v0.4.0/OpenSMS.apk",
  "apk_size": 18452100
}
```

---

### 8. Liveness Health Check
Unauthenticated ping endpoint used by load balancers, container orchestrators, and uptime monitors.

- **Method**: `GET`
- **Path**: `/health/`
- **Authentication**: None

#### Response (`200 OK`)
```json
{
  "status": "ok",
  "service": "OpenSMS",
  "version": "0.4.0"
}
```

---

## 📏 SMS Segmentation Rules

OpenSMS automatically detects character encoding and divides long messages using native Android multipart SMS (`SmsManager.divideMessage` and `sendMultipartTextMessage`):

| Encoding | Single SMS Limit | Multipart Segment Size | Trigger Condition |
|---|---|---|---|
| **GSM 7-bit** | 160 characters | 153 characters / segment | Standard ASCII characters, numbers, and basic punctuation. |
| **UCS-2 (Unicode)** | 70 characters | 67 characters / segment | Triggered when text contains emojis, non-Latin alphabets (Arabic, Cyrillic, Chinese, Sinhala, etc.), or special Unicode symbols. |


---

## Authentication scopes, key management and delivery semantics (audit update)

| Scope | Allows |
|---|---|
| `sms:write` | `POST /sms/`, `POST /sms/batch/` |
| `sms:read` | `GET /sms/{id}`, `GET /sms/history`, `GET /system/*`, docs endpoints |
| `admin` | everything above plus `GET/POST /keys/`, `DELETE /keys/{id}`, `POST /control/` |

A key lacking the scope receives `403`. Send requests over the per-key rate limit receive `429` with `Retry-After`.

**Delivery status.** `status: "sent"` means the message was handed to Android's telephony service. It is **not** a delivery confirmation: `delivery_confirmed` is `false` and `delivered_at` is `null`. Carrier delivery reports are not yet tracked.

`/docs`, `/openapi.json`, `/llms.txt` and `/docs/markdown` require a Bearer token unless the gateway is started with `OPENSMS_PUBLIC_DOCS=1`.


## Idempotency, errors and pagination (audit Stage 3)

**Idempotency.** Add `Idempotency-Key: <unique string>` (1-128 chars of `A-Z a-z 0-9 _ - . :`) to `POST /sms/` or `POST /sms/batch/`. Retrying after a timeout with the same key and body returns the original response with `Idempotent-Replay: true` and does not send again.

| Situation | Result |
|---|---|
| Same key, same body, finished | original response, `Idempotent-Replay: true` |
| Same key, same body, still running | `409` `request_in_progress` (`Retry-After: 2`) |
| Same key, different body | `422` `idempotency_key_reuse` |
| Previous attempt failed (e.g. `502`) | key is released; retry runs normally |
| Malformed key | `400` `invalid_idempotency_key` |

Keys are scoped to the API key and expire after 24 hours.

**Errors.** Every error body is `{"detail": ..., "error": {"code": "...", "message": "..."}}`. `detail` is unchanged from earlier versions.

**Pagination.** `GET /sms/history` returns `count` (rows in this page), `total` (rows matching the filters), `offset`, `limit` and `has_more`. `limit` is 1-200.


## Message lifecycle (audit Stage 4)

| `status` | Meaning | Evidence |
|---|---|---|
| `queued` | Accepted by the API, waiting for the send worker | - |
| `submitted` | Handed to Android's telephony layer; radio result not known yet | `SmsManager` call returned |
| `sent` | The radio/network accepted **every** part | sent receipts |
| `delivered` | The handset/recipient reported delivery for **every** part | delivery status reports |
| `failed` | Rejected at submit, by the radio, or a failed delivery report; see `carrier_error` | - |
| `unknown` | Submitted but no result ever arrived (e.g. the gateway restarted). It may or may not have been sent and is never re-sent automatically | - |

`delivered_at` and `delivery_confirmed: true` appear only with a real delivery report. Carrier support for delivery reports varies; without one a message stays at `sent`.

`POST /sms/` returns `200` after the hand-off (`status: submitted` or `sent`), `202` (`status: queued`) if the worker is still busy after `OPENSMS_SUBMIT_WAIT_SECONDS` (default 15), `502 delivery_failed` if the hand-off failed (the reason is in `detail`), `503 queue_full` if the queue is full and `422 invalid_sim_slot` for an inactive SIM. `POST /sms/batch/` returns per-message `status` and a `pending` count. `GET /system/sims/` returns `reliable` (false when Android could not be asked, usually because the Phone permission is missing; the single entry is then a placeholder and `sim_slot` routing is refused with `422 invalid_sim_slot`). `GET /sms/{id}` adds `parts` (per-part `sent_ok`, `sent_error`, `delivery`), `provider` (`android` or `simulated`) and `delivery_confirmed`.
