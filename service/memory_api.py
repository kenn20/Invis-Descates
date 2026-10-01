from uuid import UUID

from flask import Response, g, jsonify, request

from service.app import MAX_EXCERPT_BYTES
from service.memory import MemoryStore
from service.model import ModelUnavailable


def register_memory(app, store):
    memory = MemoryStore(store)
    app.extensions["memory"] = memory

    def validate(payload, fields):
        if not isinstance(payload, dict) or set(payload) != fields:
            return 400
        for key in ("installationId", "vaultId", "noteId"):
            if key in fields:
                try:
                    UUID(payload[key])
                except (ValueError, TypeError, AttributeError):
                    return 400
        if not store.owns(g.identity, payload):
            return 403
        return None

    @app.put("/v1/memories")
    def upload():
        payload = request.get_json(silent=True)
        invalid = validate(payload, {"installationId", "vaultId", "noteId", "revision", "content"})
        if invalid:
            return Response(status=invalid)
        if (type(payload["revision"]) is not int or payload["revision"] < 1
                or not isinstance(payload["content"], str) or not payload["content"].strip()
                or len(payload["content"].encode()) > MAX_EXCERPT_BYTES):
            return Response(status=400)
        model = app.extensions.get("model")
        if model is None:
            return Response(status=503)
        try:
            vector = model.embed(payload["content"])
            memory.upsert(g.identity, payload["noteId"], payload["revision"], payload["content"], vector)
        except (ModelUnavailable, ValueError):
            return Response(status=503)
        return Response(status=204)

    @app.post("/v1/memories:query")
    @app.post("/v1/rag:answer")
    def query():
        payload = request.get_json(silent=True)
        invalid = validate(payload, {"installationId", "vaultId", "query", "topK"})
        if invalid:
            return Response(status=invalid)
        if (not isinstance(payload["query"], str) or not payload["query"].strip()
                or len(payload["query"].encode()) > MAX_EXCERPT_BYTES
                or type(payload["topK"]) is not int or not 1 <= payload["topK"] <= 5):
            return Response(status=400)
        model = app.extensions.get("model")
        if model is None:
            return Response(status=503)
        try:
            matches = memory.query(g.identity, model.embed(payload["query"]), payload["topK"])
            if request.path == "/v1/rag:answer":
                answer = model.answer(payload["query"], matches) if matches else "No matching memories are available."
                return jsonify(answer=answer, sources=[{"noteId": item["noteId"], "revision": item["revision"]} for item in matches])
            return jsonify(memories=matches)
        except (ModelUnavailable, ValueError):
            return Response(status=503)

    @app.delete("/v1/memories")
    def remove():
        payload = request.get_json(silent=True)
        invalid = validate(payload, {"installationId", "vaultId", "noteId"})
        if invalid:
            return Response(status=invalid)
        memory.delete(g.identity, payload["noteId"])
        return Response(status=204)
