"""Fail-closed production configuration, independent of the hosting provider."""
import os
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from service.identity import metadata
from werkzeug.middleware.proxy_fix import ProxyFix

from service.hosted import create_hosted_app
from service.model import ModelClient


def database_url():
    value = os.environ.get("DATABASE_URL", "")
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql+psycopg" or not parsed.hostname:
        raise ValueError("Production requires PostgreSQL")
    if parse_qs(parsed.query).get("sslmode") != ["verify-full"]:
        raise ValueError("Production database TLS must verify the server certificate")
    return value


def create_from_env(*, trusted_platform_proxy=False):
    required = ("PUBLIC_ORIGIN", "SESSION_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                "MODEL_ENDPOINT", "MODEL_API_KEY", "EMBEDDING_MODEL", "GENERATION_MODEL")
    if any(not os.environ.get(key) for key in required):
        raise ValueError("Required hosted configuration is missing")
    secret = os.environ["SESSION_SECRET"]
    if secret.startswith("REPLACE_") or len(set(secret)) < 12:
        raise ValueError("Generate a random session secret before deployment")
    app = create_hosted_app(database_url(), os.environ["PUBLIC_ORIGIN"], os.environ["SESSION_SECRET"],
        google_client_id=os.environ["GOOGLE_CLIENT_ID"], google_client_secret=os.environ["GOOGLE_CLIENT_SECRET"])
    app.extensions["model"] = ModelClient(os.environ["MODEL_ENDPOINT"], os.environ["MODEL_API_KEY"],
        os.environ["EMBEDDING_MODEL"], os.environ["GENERATION_MODEL"])
    if trusted_platform_proxy:
        # Only on a platform where clients cannot bypass the sanitizing reverse proxy.
        # Do not trust forwarded Host or arbitrary client IP headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=0, x_for=0)

    @app.get("/readyz")
    def ready():
        from flask import Response
        try:
            with app.extensions["identity"].engine.connect() as conn:
                for table in metadata.sorted_tables:
                    conn.execute(select(table).limit(0))
        except Exception:
            return Response(status=503)
        return Response(status=204)

    return app
