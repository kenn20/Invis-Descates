import asyncio
import json

import pytest
import websockets

from service.tests.test_app import body
from service.websocket_spike import websocket_handler


async def exercise_first_frame_authentication_and_ready_before_content():
    token = "test-token"
    async def handler(ws, path):
        await websocket_handler(ws, path, token)
    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as client:
            await client.send(json.dumps({"type": "hello", "token": token}))
            assert json.loads(await client.recv()) == {"type": "ready"}
            await client.send(json.dumps({"type": "evaluate", "request": body()}))
            assert json.loads(await client.recv())["type"] == "decision"
        async with websockets.connect(f"ws://127.0.0.1:{port}") as attacker:
            await attacker.send(json.dumps({"type": "evaluate", "request": body()}))
            with pytest.raises(websockets.ConnectionClosed) as closed:
                await attacker.recv()
            assert closed.value.code == 4001
    finally:
        server.close(); await server.wait_closed()


def test_first_frame_authentication_and_ready_before_content():
    asyncio.run(exercise_first_frame_authentication_and_ready_before_content())
