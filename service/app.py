"""The deliberately small, local-only HTTP companion proof."""
from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from flask import Flask, Response, jsonify, request

MAX_BODY_BYTES = 64 * 1024
MAX_EXCERPT_BYTES = 8 * 1024
ALLOWED_HOSTS = {"127.0.0.1:27123", "localhost:27123"}
TRIGGERS = {"idle", "save", "manual"}


@dataclass
class TokenStore:
    """In-memory test pairing store. Production pairing persistence is deferred."""

    token: str
    revoked: bool = False

    def valid(self, presented: str | None) -> bool:
        return bool(presented) and not self.revoked and hmac.compare_digest(self.token, presented)


def _error(status: int) -> Response:
    # Do not reflect malformed content, tokens, paths, or upstream errors.
    return Response(status=status)


def _is_loopback(remote: str | None) -> bool:
    try:
        return ipaddress.ip_address(remote or "").is_loopback
    except ValueError:
        return False


def _bearer() -> str | None:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        return None
    token = value[7:]
    return token if token and len(token) <= 512 else None


def _valid_request(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    expected = {"schemaVersion", "requestId", "installationId", "vaultId", "noteId", "revision", "createdAt", "trigger", "excerpt", "signals"}
    if set(payload) != expected or payload["schemaVersion"] != 1:
        return False
    for key in ("requestId", "installationId", "vaultId", "noteId"):
        try:
            UUID(payload[key])
        except (ValueError, TypeError, AttributeError):
            return False
    if not isinstance(payload["revision"], int) or isinstance(payload["revision"], bool) or payload["revision"] < 1:
        return False
    if not isinstance(payload["trigger"], str) or payload["trigger"] not in TRIGGERS or not isinstance(payload["excerpt"], str):
        return False
    if len(payload["excerpt"].encode("utf-8")) > MAX_EXCERPT_BYTES:
        return False
    try:
        datetime.fromisoformat(payload["createdAt"].replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return False
    signals = payload["signals"]
    if not isinstance(signals, dict) or set(signals) != {"challengeScore", "reflectionDepth", "daysSinceUpdate", "idleMs"}:
        return False
    return (
        all(isinstance(signals[k], (int, float)) and not isinstance(signals[k], bool) and 0 <= signals[k] <= 1 for k in ("challengeScore", "reflectionDepth"))
        and all(isinstance(signals[k], int) and not isinstance(signals[k], bool) and signals[k] >= 0 for k in ("daysSinceUpdate", "idleMs"))
    )


def _decision(payload: dict[str, Any]) -> dict[str, Any]:
    base = {key: payload[key] for key in ("schemaVersion", "requestId", "noteId", "revision")}
    # Deterministic fake logic: no remote model, no persistence, no content logging.
    if payload["signals"]["challengeScore"] >= 0.75 and payload["signals"]["reflectionDepth"] < 0.5:
        return {
            **base,
            "decision": "show",
            "mode": "reflection",
            "displayMode": "inline",
            "hint": "Which assumption failed, and what will you test next?",
            "range": {"from": 0, "to": min(len(payload["excerpt"]), 120)},
            "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        }
    return {**base, "decision": "silent", "reason": "no_value"}


def create_app(token: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    app.config["TOKEN_STORE"] = TokenStore(token or os.environ.get("COMPANION_TOKEN", secrets.token_urlsafe(32)))

    @app.before_request
    def loopback_only() -> Response | None:
        if request.method == "OPTIONS" or not _is_loopback(request.remote_addr):
            return _error(403)
        if request.host not in ALLOWED_HOSTS:
            return _error(400)
        return None

    @app.errorhandler(413)
    def oversized(_: Exception) -> Response:
        return _error(413)

    @app.get("/healthz")
    def healthz() -> Response:
        return Response(status=204)

    @app.post("/v1/nudges:evaluate")
    def evaluate() -> Response:
        store: TokenStore = app.config["TOKEN_STORE"]
        if not store.valid(_bearer()):
            return _error(401)
        if not request.is_json:
            return _error(400)
        payload = request.get_json(silent=True)
        if not _valid_request(payload):
            return _error(400)
        return jsonify(_decision(payload))

    @app.delete("/v1/pairing")
    def revoke() -> Response:
        store: TokenStore = app.config["TOKEN_STORE"]
        if not store.valid(_bearer()):
            return _error(401)
        store.revoked = True
        return Response(status=204)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=27123, debug=False)
