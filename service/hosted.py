"""Central API boundary. The local proof remains available through service.app."""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, request

from service.app import MAX_BODY_BYTES, _bearer, _decision, _valid_request
from service.identity import IdentityStore
from service.memory_api import register_memory


def create_hosted_app(database_url: str, public_origin: str, session_secret: str, *, google_client_id: str | None = None,
                      google_client_secret: str | None = None) -> Flask:
    origin = urlsplit(public_origin)
    if (origin.scheme != "https" or not origin.hostname or origin.path not in ("", "/")
            or origin.query or origin.fragment or origin.username or origin.password):
        raise ValueError("A public HTTPS origin is required")
    if len(session_secret) < 32:
        raise ValueError("A strong session secret is required")
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=MAX_BODY_BYTES, SECRET_KEY=session_secret,
        SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax", TRUSTED_HOSTS=[origin.hostname])
    store = IdentityStore(database_url)
    app.extensions["identity"] = store
    app.config["PUBLIC_ORIGIN"] = public_origin.rstrip("/")

    @app.before_request
    def boundary():
        if not request.is_secure:
            return Response(status=400)
        if request.method == "OPTIONS":
            return Response(status=403)
        if request.path.startswith("/v1/"):
            g.identity = store.authenticate(_bearer())
            if g.identity is None:
                return Response(status=401)
        return None

    @app.after_request
    def secure_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(413)
    def oversized(_):
        return Response(status=413)

    @app.get("/healthz")
    def health():
        return Response(status=204)

    @app.post("/v1/nudges:evaluate")
    def evaluate():
        payload = request.get_json(silent=True)
        if not _valid_request(payload):
            return Response(status=400)
        if not store.owns(g.identity, payload):
            return Response(status=403)
        # Preserve deterministic proof; real generation has a separate release gate.
        return jsonify(_decision(payload))

    @app.delete("/v1/pairing")
    def revoke():
        store.revoke(g.identity)
        return Response(status=204)

    if google_client_id is not None or google_client_secret is not None:
        from service.pairing import register_google_pairing
        register_google_pairing(app, store, google_client_id, google_client_secret)
    register_memory(app, store)
    return app
