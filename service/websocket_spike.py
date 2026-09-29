"""Test-only WebSocket protocol spike. It is never imported by app.py."""
from __future__ import annotations

import json
from typing import Any

from service.app import _decision, _valid_request


async def websocket_handler(websocket: Any, path: str, token: str) -> None:
    """Require hello authentication before accepting any complete evaluation frame."""
    try:
        hello = json.loads(await websocket.recv())
        if hello != {"type": "hello", "token": token}:
            await websocket.close(code=4001)
            return
        await websocket.send(json.dumps({"type": "ready"}))
        async for raw in websocket:
            frame = json.loads(raw)
            if set(frame) != {"type", "request"} or frame["type"] != "evaluate" or not _valid_request(frame["request"]):
                await websocket.close(code=4002)
                return
            await websocket.send(json.dumps({"type": "decision", "decision": _decision(frame["request"])}))
    except (json.JSONDecodeError, TypeError):
        await websocket.close(code=4002)
