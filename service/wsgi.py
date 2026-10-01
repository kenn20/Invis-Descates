"""Portable WSGI entrypoint; use a trusted TLS proxy, not the Flask dev server."""
from service.runtime import create_from_env

app = create_from_env()
