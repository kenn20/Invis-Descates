"""Explicit schema bootstrap for a new beta database (not a schema upgrade tool)."""
from service.identity import IdentityStore
# Import all tables before bootstrap.
from service import memory, pairing  # noqa: F401
from service.runtime import database_url

if __name__ == "__main__":
    store = IdentityStore(database_url())
    store.initialize()
    print("Beta database schema initialized.")
