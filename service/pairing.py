"""Application-owned device pairing layered on Google's web OIDC flow."""
from __future__ import annotations

import secrets
import time
from uuid import UUID

from authlib.integrations.flask_client import OAuth
from flask import Response, jsonify, redirect, render_template_string, request, session
from sqlalchemy import Column, ForeignKey, Integer, String, Table, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from service.identity import digest, metadata

pairings = Table("pairings", metadata,
    Column("secret_hash", String(64), primary_key=True),
    Column("code", String(16), unique=True, nullable=False),
    Column("installation_id", String(36), nullable=False),
    Column("vault_id", String(36), nullable=False),
    Column("name", String(80), nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("last_poll", Integer, nullable=False, default=0),
    Column("user_id", ForeignKey("users.id")),
    Column("status", String(16), nullable=False, default="pending"))
buckets = Table("pairing_rate", metadata,
    Column("key", String(64), primary_key=True),
    Column("window", Integer, primary_key=True),
    Column("count", Integer, nullable=False))


class PairingStore:
    def __init__(self, identity):
        self.identity = identity
        self.engine = identity.engine

    def allow_start(self, remote):
        key, window = digest(remote or "unknown"), int(time.time()) // 60
        # Unique insert handles first-request races; conditional increment enforces a shared limit.
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(buckets).values(key=key, window=window, count=0))
        except IntegrityError:
            pass
        with self.engine.begin() as conn:
            conn.execute(delete(buckets).where(buckets.c.window < window - 10))
            return conn.execute(update(buckets).where(buckets.c.key == key, buckets.c.window == window,
                buckets.c.count < 10).values(count=buckets.c.count + 1)).rowcount == 1

    def start(self, installation, vault, name):
        secret, code = secrets.token_urlsafe(32), secrets.token_hex(5).upper()
        with self.engine.begin() as conn:
            conn.execute(delete(pairings).where(pairings.c.expires_at < int(time.time())))
            conn.execute(insert(pairings).values(secret_hash=digest(secret), code=code,
                installation_id=installation, vault_id=vault, name=name,
                expires_at=int(time.time()) + 300, last_poll=0, status="pending"))
        return secret, code

    def pending(self, code):
        with self.engine.connect() as conn:
            return conn.execute(select(pairings).where(pairings.c.code == code,
                pairings.c.expires_at > int(time.time()), pairings.c.status == "pending")).mappings().first()

    def approve(self, code, user_id):
        with self.engine.begin() as conn:
            return conn.execute(update(pairings).where(pairings.c.code == code,
                pairings.c.expires_at > int(time.time()), pairings.c.status == "pending")
                .values(status="approved", user_id=user_id)).rowcount == 1

    def poll(self, secret):
        now = int(time.time())
        with self.engine.begin() as conn:
            claimed = conn.execute(update(pairings).where(pairings.c.secret_hash == digest(secret),
                pairings.c.expires_at > now, pairings.c.status.in_(["pending", "approved"]),
                pairings.c.last_poll <= now - 3).values(last_poll=now)).rowcount
            if claimed != 1:
                active = conn.execute(select(pairings.c.status).where(pairings.c.secret_hash == digest(secret),
                    pairings.c.expires_at > now, pairings.c.status.in_(["pending", "approved"]))).first()
                return None, 429 if active else 410
            row = conn.execute(select(pairings).where(pairings.c.secret_hash == digest(secret))).mappings().one()
            if row["status"] == "pending":
                return None, 202
            token, device_id = self.identity.issue_device(conn, row["user_id"], row["installation_id"], row["vault_id"], row["name"])
            conn.execute(update(pairings).where(pairings.c.secret_hash == digest(secret)).values(status="consumed"))
            return {"token": token, "deviceId": device_id}, 200


def register_google_pairing(app, store, client_id, client_secret):
    if not client_id or not client_secret:
        raise ValueError("Google OAuth credentials are required")
    oauth = OAuth(app)
    google = oauth.register(name="google", client_id=client_id, client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"})
    pairing = PairingStore(store)
    app.extensions["pairing"] = pairing
    app.extensions["google"] = google
    origin = app.config["PUBLIC_ORIGIN"]

    @app.post("/auth/pairing/start")
    def start():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"installationId", "vaultId", "deviceName"}:
            return Response(status=400)
        try:
            UUID(payload["installationId"])
            UUID(payload["vaultId"])
        except (TypeError, ValueError, AttributeError):
            return Response(status=400)
        name = payload["deviceName"]
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            return Response(status=400)
        if not pairing.allow_start(request.remote_addr):
            return Response(status=429)
        secret, code = pairing.start(payload["installationId"], payload["vaultId"], name)
        return jsonify(pairingSecret=secret, userCode=code, expiresIn=300, interval=3,
            verificationUrl=origin + "/auth/google?code=" + code)

    @app.post("/auth/pairing/poll")
    def poll():
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or set(payload) != {"pairingSecret"}
                or not isinstance(payload["pairingSecret"], str) or not 32 <= len(payload["pairingSecret"]) <= 128):
            return Response(status=400)
        try:
            result, status = pairing.poll(payload["pairingSecret"])
        except (PermissionError, IntegrityError):
            return Response(status=403)
        return (jsonify(result), status) if result else Response(status=status)

    @app.get("/auth/google")
    def login():
        code = request.args.get("code", "")
        if not pairing.pending(code):
            return Response(status=410)
        session.clear()
        session["pairing_code"] = code
        try:
            return google.authorize_redirect(origin + "/auth/google/callback", nonce=secrets.token_urlsafe(32))
        except Exception:
            # OAuth/provider errors must not expose credentials or redirect arbitrary URLs.
            session.clear()
            return Response(status=503)

    @app.get("/auth/google/callback")
    def callback():
        try:
            # Authlib checks state and verifies the ID token's signature, issuer, audience,
            # expiry and saved nonce before returning userinfo.
            token = google.authorize_access_token()
            info = token.get("userinfo")
            if (not token.get("id_token") or not info or info.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}
                    or not pairing.pending(session.get("pairing_code", ""))):
                raise ValueError()
            session["user_id"] = store.user_for_google(info["sub"])
            session["csrf"] = secrets.token_urlsafe(32)
        except Exception:
            session.clear()
            return Response(status=401)
        return redirect(origin + "/auth/approve")

    @app.get("/auth/approve")
    def approval():
        row = pairing.pending(session.get("pairing_code", ""))
        if not session.get("user_id") or row is None:
            return Response(status=401)
        return render_template_string('''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Connect Obsidian</title><h1>Connect {{ name }}</h1>
<p>Confirm that Obsidian displays this code: <strong>{{ code }}</strong>.</p>
<p>Approve only a connection you started. The plugin will receive access to your memories.</p>
<form method="post" action="/auth/approve"><input type="hidden" name="csrf" value="{{ csrf }}">
<button type="submit">Approve connection</button></form></html>''',
            name=row["name"], code=row["code"], csrf=session["csrf"])

    @app.post("/auth/approve")
    def approve():
        csrf = request.form.get("csrf", "")
        expected = session.get("csrf", "")
        if not expected or not secrets.compare_digest(csrf, expected) or not session.get("user_id"):
            return Response(status=403)
        if not pairing.approve(session.get("pairing_code", ""), session["user_id"]):
            return Response(status=410)
        session.clear()
        return Response("Connection approved. Return to Obsidian.", mimetype="text/plain")
