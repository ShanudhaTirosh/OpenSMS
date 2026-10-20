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
- **Limit**: Maximum 5 failed authorization attempts per IP within a 60-second sliding window.
- **Response**: HTTP `429 Too Many Requests` with `{"detail": "Rate limit exceeded. Try again in 60s."}`.

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
  "id": "msg_9f3b81ca7d2e4018",
  "number": "+1234567890",
  "stat": true,
  "sim_slot": 0,
  "segments": 1,
  "encoding": "GSM-7"
}
```

#### Error Responses
- `400 Bad Request`: `{"detail": "Invalid phone number format. Must contain 7 to 15 digits."}`
- `401 Unauthorized`: `{"detail": "Invalid or missing Bearer API key"}`
- `500 Internal Server Error`: `{"detail": "Carrier error: cellular modem failed to transmit message"}`

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
| `id` | string | **Yes** | The message ID returned by `POST /sms/` (e.g. `msg_9f3b81ca7d2e4018`). |

#### Response (`200 OK`)
```json
{
  "id": "msg_9f3b81ca7d2e4018",
  "recipient": "+1234567890",
  "text": "Your verification code is 849201.",
  "encoding": "GSM-7",
  "segments": 1,
  "sim_slot": 0,
  "status": "sent",
  "batch_id": null,
  "created_at": 1729432800.12,
  "delivered_at": 1729432801.45,
  "carrier_error": null
}
```

#### Message Status Values
- `queued`: Message stored in database, awaiting baseband pickup.
- `sending`: Handed over to Android native `SmsManager`.
- `sent`: Successfully acknowledged by carrier cellular tower.
- `failed`: Baseband error (e.g. no signal, SIM disabled, carrier rejected).

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
      "id": "msg_9f3b81ca7d2e4018",
      "recipient": "+1234567890",
      "text": "Alert: Sensor threshold exceeded",
      "status": "sent",
      "encoding": "GSM-7",
      "segments": 1,
      "sim_slot": 0,
      "created_at": 1729432800.12,
      "delivered_at": 1729432801.45
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
