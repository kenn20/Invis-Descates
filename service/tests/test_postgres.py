"""Real PostgreSQL gate; CI always supplies an isolated database, never production."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.schema import CreateSchema, DropSchema

from service.hosted import create_hosted_app
from service.identity import IdentityStore
from service.memory import MemoryStore, collections
from service.pairing import PairingStore
from service.tests.test_app import body
from service.tests.test_identity import call
from service.tests.test_memory import Model


@pytest.fixture
def postgres_app():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL gate requires TEST_DATABASE_URL; CI must run it")
    schema = "gate_" + uuid4().hex
    app = create_hosted_app(url, "https://companion.example", "x" * 32,
        google_client_id="test-client", google_client_secret="test-secret")
    store = app.extensions["identity"]
    with store.engine.begin() as conn:
        conn.execute(CreateSchema(schema))
    store.engine = store.engine.execution_options(schema_translate_map={None: schema})
    app.extensions["memory"] = MemoryStore(store)
    app.extensions["pairing"].engine = store.engine
    store.initialize()
    app.config["TESTING"] = True
    try:
        yield app, store, schema
    finally:
        with store.engine.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        store.engine.dispose()


def test_postgres_persistence_ownership_and_vector_collection_isolation(postgres_app):
    app, store, schema = postgres_app
    memory = MemoryStore(store)
    app.extensions["model"] = Model()
    user_a, user_b = store.user_for_google("google-a"), store.user_for_google("google-b")
    with store.engine.begin() as conn:
        token_a, _ = store.issue_device(conn, user_a, body()["installationId"], body()["vaultId"])
        token_b, _ = store.issue_device(conn, user_b, str(uuid4()), str(uuid4()))
    a, b = store.authenticate(token_a), store.authenticate(token_b)
    note = body()["noteId"]
    memory.upsert(a, note, 1770000000000, "private-a", [1.0, 0.0])
    memory.upsert(b, note, 1770000000000, "private-b", [1.0, 0.0])
    assert memory.query(a, [1.0, 0.0], 5)[0]["content"] == "private-a"
    assert memory.query(b, [1.0, 0.0], 5)[0]["content"] == "private-b"
    c = app.test_client()
    query = {"installationId": a.installation_id, "vaultId": a.vault_id, "query": "anything", "topK": 5}
    assert call(c, "/v1/rag:answer", token_a, payload=query).json["answer"] == "private-a"
    assert call(c, "/v1/rag:answer", token_b, payload=query).status_code == 403
    assert call(c, "/v1/nudges:evaluate", token_b, payload=body()).status_code == 403
    memory.delete(b, note)
    assert memory.query(a, [1.0, 0.0], 5)[0]["content"] == "private-a"
    with store.engine.connect() as conn:
        assert len(conn.execute(select(collections)).all()) == 2
    restarted = IdentityStore(os.environ["TEST_DATABASE_URL"])
    restarted.engine = restarted.engine.execution_options(schema_translate_map={None: schema})
    try:
        assert restarted.authenticate(token_a) == a
        restarted.revoke(a)
        assert store.authenticate(token_a) is None
    finally:
        restarted.engine.dispose()


def test_postgres_simultaneous_pairing_polls_issue_only_one_token(postgres_app):
    _, store, _ = postgres_app
    pairing = PairingStore(store)
    secret, code = pairing.start(str(uuid4()), str(uuid4()), "Concurrent device")
    user = store.user_for_google("google-concurrent")
    assert pairing.approve(code, user)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: pairing.poll(secret), range(2)))
    assert sorted(status for _, status in results) == [200, 410]
    result = next(result for result, status in results if status == 200)
    assert store.authenticate(result["token"]).user_id == user
