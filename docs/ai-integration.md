# 🤖 AI Agent & LLM Integration Guide

This guide describes how to give **Large Language Models (LLMs)**, **AI Agents**, and **Autonomous Workflows** the ability to send cellular SMS messages, verify 2FA codes, check delivery receipts, and query telephony status through OpenSMS.

---

## 📑 Direct Markdown & AI View URLs

AI agents such as **ChatGPT**, **Claude**, **Cursor**, **Windsurf**, **Gemini**, and **Copilot** can ingest OpenSMS documentation directly:

| Format | URL / File Path | Purpose |
|---|---|---|
| **LLMs Index** | [`/llms.txt`](llms.txt) | Lightweight index of all documentation following the llmstxt.org standard |
| **Full LLM Bundle** | [`/llms-full.txt`](llms-full.txt) | Consolidated single-file prompt context for full context window loading |
| **API Reference (MD)**| [`/docs/api-reference.md`](api-reference.md) | Machine-readable Markdown API specification |
| **OpenAPI Spec (JSON)**| [`/docs/openapi.json`](openapi.json) | OpenAPI 3.1.0 schema for automated tool generator pipelines |

When OpenSMS is running on your phone, you can also fetch live documentation directly over HTTP:
```bash
curl http://<DEVICE_IP>:9292/llms.txt
curl http://<DEVICE_IP>:9292/docs/markdown
```

---

## 🛠️ 1. OpenAI Function Calling (Tool Definition)

Pass this tool definition directly to OpenAI's Chat Completions API (`gpt-4o`, `gpt-4o-mini`, `o1`):

```python
import json
import requests
from openai import OpenAI

client = OpenAI()

OPENSMS_BASE_URL = "http://100.85.x.x:9292"  # Or local Wi-Fi IP
OPENSMS_API_KEY = "osms_your_secret_key"

tools = [
    {
        "type": "function",
        "function": {
            "name": "send_cellular_sms",
            "description": "Sends a real SMS text message to a recipient phone number via the OpenSMS cellular gateway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "number": {
                        "type": "string",
                        "description": "Destination phone number with country code in E.164 format (e.g., '+1234567890')."
                    },
                    "text": {
                        "type": "string",
                        "description": "The message body to transmit to the recipient."
                    },
                    "sim_slot": {
                        "type": "integer",
                        "description": "Optional carrier slot (0 for SIM 1, 1 for SIM 2). Omit for system default."
                    }
                },
                "required": ["number", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sms_delivery_status",
            "description": "Checks the delivery status of a previously dispatched SMS message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The unique message ID returned by send_cellular_sms (e.g. '3f2b8c1a-9d4e-4a6b-8c2d-7e1f0a5b9c42')."
                    }
                },
                "required": ["message_id"]
            }
        }
    }
]

def execute_sms_tool(tool_call):
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    headers = {
        "Authorization": f"Bearer {OPENSMS_API_KEY}",
        "Content-Type": "application/json"
    }

    if name == "send_cellular_sms":
        resp = requests.post(f"{OPENSMS_BASE_URL}/sms/", json=args, headers=headers)
        return resp.text

    elif name == "get_sms_delivery_status":
        resp = requests.get(f"{OPENSMS_BASE_URL}/sms/{args['message_id']}", headers=headers)
        return resp.text

    return json.dumps({"error": f"Unknown tool: {name}"})
```

---

## 🧠 2. Anthropic Claude Tool Definition

Pass this tool specification to Anthropic's Messages API:

```python
import anthropic

claude = anthropic.Anthropic()

claude_tools = [
    {
        "name": "send_sms",
        "description": "Dispatches a real cellular text message to a user or client phone number using an Android OpenSMS gateway.",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "Destination phone number in international E.164 format (e.g. +1234567890)."
                },
                "text": {
                    "type": "string",
                    "description": "The SMS text content to send."
                },
                "sim_slot": {
                    "type": "integer",
                    "description": "Optional: 0 for SIM 1, 1 for SIM 2."
                }
            },
            "required": ["number", "text"]
        }
    }
]
```

---

## 🦜 3. LangChain Custom Tool

Integrate OpenSMS into your LangChain or LangGraph agent:

```python
import os
import requests
from langchain.tools import tool

OPENSMS_URL = os.getenv("OPENSMS_URL", "http://100.85.x.x:9292")
OPENSMS_KEY = os.getenv("OPENSMS_KEY", "osms_your_secret_key")

@tool
def send_sms(number: str, message: str, sim_slot: int = None) -> dict:
    """Send an SMS to a phone number using the OpenSMS Android gateway.
    
    Args:
        number: The destination phone number in E.164 format (+1234567890).
        message: The text content of the message.
        sim_slot: Optional SIM slot index (0 for SIM 1, 1 for SIM 2).
    """
    headers = {
        "Authorization": f"Bearer {OPENSMS_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"number": number, "text": message}
    if sim_slot is not None:
        payload["sim_slot"] = sim_slot

    try:
        resp = requests.post(f"{OPENSMS_URL}/sms/", json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool
def get_sms_status(message_id: str) -> dict:
    """Retrieve the delivery status of an SMS message by ID.
    
    Args:
        message_id: The ID returned from send_sms (e.g. 3f2b8c1a-9d4e-4a6b-8c2d-7e1f0a5b9c42).
    """
    headers = {"Authorization": f"Bearer {OPENSMS_KEY}"}
    try:
        resp = requests.get(f"{OPENSMS_URL}/sms/{message_id}", headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}
```

---

## 🔌 4. Model Context Protocol (MCP) Server

OpenSMS can be integrated into any MCP-compatible environment (Claude Desktop, Antigravity IDE, Cursor) as an MCP server tool:

### MCP Tool Schema (`send_sms`)
```json
{
  "name": "send_sms",
  "description": "Send a real cellular SMS text message via your OpenSMS Android phone gateway.",
  "parameters": {
    "type": "object",
    "properties": {
      "number": {
        "type": "string",
        "description": "Recipient phone number with country code (e.g., +1234567890)"
      },
      "text": {
        "type": "string",
        "description": "Message body"
      },
      "sim_slot": {
        "type": "integer",
        "description": "Optional: 0 for SIM 1, 1 for SIM 2"
      }
    },
    "required": ["number", "text"]
  }
}
```

### Python FastMCP Server Implementation
```python
# opensms_mcp.py
import os
import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("OpenSMS Gateway")
GATEWAY_URL = os.getenv("OPENSMS_URL", "http://127.0.0.1:9292")
API_KEY = os.getenv("OPENSMS_KEY", "")

@mcp.tool()
def send_sms(number: str, text: str, sim_slot: int = 0) -> str:
    """Send an SMS to a phone number via cellular gateway."""
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"number": number, "text": text, "sim_slot": sim_slot}
    r = requests.post(f"{GATEWAY_URL}/sms/", json=payload, headers=headers)
    return r.text

@mcp.tool()
def check_status(message_id: str) -> str:
    """Check SMS delivery status from SQLite store."""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    r = requests.get(f"{GATEWAY_URL}/sms/{message_id}", headers=headers)
    return r.text

if __name__ == "__main__":
    mcp.run()
```

---

## 🎯 AI System Prompt Recommendations

When giving an agent access to OpenSMS, append these instructions to your agent's system prompt:

```text
You have access to a real cellular SMS gateway via the OpenSMS tool.
- Always verify the recipient's phone number includes their country code before calling the tool.
- Inform the user that real cellular SMS will be dispatched over carrier networks.
- For emergency, two-factor authentication, or verification codes, keep messages concise (<160 characters) to ensure single-segment GSM-7 delivery.
- If you receive a rate limit error (HTTP 429), pause operations for 60 seconds.
- You can query `get_sms_status` to verify whether the carrier modem confirmed transmission.
```
