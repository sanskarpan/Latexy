"""Forward Dodo's official outbound sandbox relay to the local signed webhook.

Uses the official CLI protocol. Run from any directory with the backend's
Python dependencies installed. This helper never stores or logs event bodies.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = "http://127.0.0.1:8030/billing/webhook"


def test_key() -> str:
    config = {
        **dotenv_values(ROOT / ".env"),
        **dotenv_values(ROOT / "backend/.env"),
    }
    mode = os.environ.get("DODO_MODE", config.get("DODO_MODE", "test"))
    if mode != "test":
        raise SystemExit("This local relay requires DODO_MODE=test.")
    key = os.environ.get("DODO_TEST_API_KEY") or config.get("DODO_TEST_API_KEY")
    if not key:
        raise SystemExit("Set DODO_TEST_API_KEY in the ignored backend/.env.")
    return str(key)


async def forward(client: httpx.AsyncClient, ws, message: dict) -> None:
    request_id = message.get("requestId")
    if not request_id:
        return
    # Same compact JSON representation as the official CLI. Standard Webhooks
    # signature verification remains exclusively in the receiving backend.
    payload = json.dumps(message["payload"], separators=(",", ":"), ensure_ascii=False).encode()
    headers = {
        name.lower(): str(value)
        for name, value in message.get("headers", {}).items()
        if name.lower() in {"webhook-id", "webhook-timestamp", "webhook-signature"}
    }
    headers["content-type"] = "application/json"
    try:
        response = await client.post(DESTINATION, content=payload, headers=headers)
        status = response.status_code
    except httpx.RequestError:
        status = 503
    # Only log the result; a payload can contain private customer information.
    print(f"Local webhook HTTP {status}", flush=True)
    await ws.send(json.dumps({
        "type": "webhook_response", "requestId": request_id,
        "status": status, "body": {"forwarded": status < 400},
        "headers": {"content-type": "application/json"},
    }))


async def main() -> None:
    key = test_key()
    async with httpx.AsyncClient(timeout=25) as client:
        while True:
            try:
                async with connect(
                    "wss://wsserver.dodopayments.tech/connect",
                    additional_headers={"api-key": key}, open_timeout=25,
                ) as ws:
                    print("Connected to Dodo sandbox relay; forwarding to localhost:8030.", flush=True)
                    async for raw in ws:
                        try:
                            message = json.loads(raw)
                            if isinstance(message, dict):
                                await forward(client, ws, message)
                        except (KeyError, TypeError, ValueError):
                            print("Ignored malformed relay message.", flush=True)
            except (WebSocketException, OSError, TimeoutError) as error:
                print(f"Relay disconnected ({type(error).__name__}); reconnecting in 10 seconds.", flush=True)
                await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Relay stopped.")
