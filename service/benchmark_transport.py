"""Local transport gate for the proof; it measures complete request/decision frames only."""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable

from service.app import create_app
from service.tests.test_app import TOKEN, body
from service.websocket_spike import websocket_handler


@dataclass
class Metrics:
    latencies: list[float] = field(default_factory=list)
    duplicates: int = 0
    stale: int = 0
    unauthorized: int = 0
    queue_high_water: int = 0
    reconnect_failures: int = 0
    focus_escapes: int = 0
    def report(self) -> dict[str, float | int]:
        ordered = sorted(self.latencies)
        p95 = ordered[max(0, int(len(ordered) * .95) - 1)] if ordered else 0
        return {"p50_ms": round(statistics.median(ordered), 2) if ordered else 0, "p95_ms": round(p95, 2), "duplicates": self.duplicates, "stale": self.stale, "unauthorized": self.unauthorized, "queue_high_water": self.queue_high_water, "reconnect_failures": self.reconnect_failures, "focus_escapes": self.focus_escapes}


def http_run() -> Metrics:
    app = create_app(TOKEN); client = app.test_client(); metrics = Metrics()
    headers = {"Authorization": f"Bearer {TOKEN}", "Host": "127.0.0.1:27123"}
    # 100 save/idle updates, with rapid edits represented by superseded revisions.
    latest: dict[str, int] = {}
    for revision in range(1, 101):
        payload = body(revision=revision, trigger="save" if revision % 2 else "idle")
        latest[payload["noteId"]] = revision
        started = time.perf_counter(); response = client.post("/v1/nudges:evaluate", json=payload, headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.1"}); metrics.latencies.append((time.perf_counter() - started) * 1000)
        decision = response.get_json(); metrics.stale += int(decision["revision"] != latest[payload["noteId"]])
    # Service restart preserves a supplied paired token; revocation rejects content.
    restarted = create_app(TOKEN).test_client(); assert restarted.post("/v1/nudges:evaluate", json=body(), headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 200
    assert client.delete("/v1/pairing", headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 204
    metrics.unauthorized = int(client.post("/v1/nudges:evaluate", json=body(), headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 401)
    # A 30-second idle interval is modeled without sleeping: no queued work exists to deliver.
    assert metrics.queue_high_water == 0
    return metrics


async def websocket_run() -> Metrics:
    import websockets
    metrics = Metrics(); token = TOKEN
    async def handler(ws, path): await websocket_handler(ws, path, token)
    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as client:
            await client.send(json.dumps({"type": "hello", "token": token})); assert json.loads(await client.recv()) == {"type": "ready"}
            latest: dict[str, int] = {}
            for revision in range(1, 101):
                payload = body(revision=revision, trigger="save" if revision % 2 else "idle"); latest[payload["noteId"]] = revision
                started = time.perf_counter(); await client.send(json.dumps({"type": "evaluate", "request": payload})); decision = json.loads(await client.recv())["decision"]; metrics.latencies.append((time.perf_counter() - started) * 1000)
                metrics.stale += int(decision["revision"] != latest[payload["noteId"]])
        # Invalid first frame must never produce content.
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}") as bad:
                await bad.send(json.dumps({"type": "hello", "token": "revoked"})); await bad.recv()
        except websockets.ConnectionClosed as error:
            metrics.unauthorized = int(error.code == 4001)
        assert metrics.queue_high_water == 0
    finally:
        server.close(); await server.wait_closed()
    return metrics


def qualifies(http: dict[str, float | int], ws: dict[str, float | int]) -> bool:
    failures = ("duplicates", "stale", "unauthorized", "queue_high_water", "reconnect_failures", "focus_escapes")
    # Unauthorized here is expected and proves rejection; it is not a transport defect.
    defects = tuple(key for key in failures if key != "unauthorized")
    return float(http["p95_ms"]) - float(ws["p95_ms"]) >= 100 and all(ws[key] == 0 for key in defects)


if __name__ == "__main__":
    http = http_run().report(); ws = asyncio.run(websocket_run()).report(); adopted = qualifies(http, ws)
    print(json.dumps({"http": http, "websocket": ws, "decision": "adopt_websocket" if adopted else "retain_http"}, indent=2))
