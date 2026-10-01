"""Vercel Python entrypoint. HTTPS proxy behavior must pass the staging gate."""
from service.runtime import create_from_env

app = create_from_env(trusted_platform_proxy=True)
