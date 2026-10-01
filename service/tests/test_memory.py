from uuid import uuid4

from sqlalchemy import select

from service.memory import collections
from service.model import ModelUnavailable
from service.tests.test_app import body
from service.tests.test_identity import call, setup_app


class Model:
    def embed(self, text):
        return [1.0, 0.5]

    def answer(self, query, context):
        return " ".join(item["content"] for item in context)


def payload():
    return {key: body()[key] for key in ("installationId", "vaultId", "noteId")} | {"revision": 1, "content": "private-a-sentinel"}


def test_separate_collections_query_generation_and_delete_ownership(caplog):
    app, store, token_a = setup_app()
    app.extensions["model"] = Model()
    c = app.test_client()
    user_b = store.user_for_google("google-b")
    vault_b, install_b = str(uuid4()), str(uuid4())
    with store.engine.begin() as conn:
        token_b, _ = store.issue_device(conn, user_b, install_b, vault_b)
    a = payload()
    b = a | {"installationId": install_b, "vaultId": vault_b, "content": "private-b-sentinel"}
    assert call(c, "/v1/memories", token_a, "PUT", a).status_code == 204
    assert call(c, "/v1/memories", token_b, "PUT", b).status_code == 204
    with store.engine.connect() as conn:
        assert len(conn.execute(select(collections)).all()) == 2
    for token, p, own, other in ((token_a, a, a["content"], b["content"]), (token_b, b, b["content"], a["content"])):
        q = {key: p[key] for key in ("installationId", "vaultId")} | {"query": "anything", "topK": 5}
        response = call(c, "/v1/rag:answer", token, payload=q)
        assert response.status_code == 200
        assert own in response.json["answer"] and other not in response.json["answer"]
    assert call(c, "/v1/memories", token_b, "PUT", a).status_code == 403
    deletion = {key: a[key] for key in ("installationId", "vaultId", "noteId")}
    assert call(c, "/v1/memories", token_b, "DELETE", deletion).status_code == 403
    assert call(c, "/v1/memories", token_a, "DELETE", deletion).status_code == 204
    query_b = {"installationId": install_b, "vaultId": vault_b, "query": "anything", "topK": 5}
    assert call(c, "/v1/memories:query", token_b, payload=query_b).json["memories"][0]["content"] == b["content"]
    assert "private-a-sentinel" not in caplog.text and token_a not in caplog.text


def test_missing_provider_failure_stale_upload_and_strict_schema():
    app, store, token = setup_app()
    c, p = app.test_client(), payload()
    assert call(c, "/v1/memories", token, "PUT", p).status_code == 503
    app.extensions["model"] = Model()
    assert call(c, "/v1/memories", token, "PUT", p | {"revision": 2, "content": "new"}).status_code == 204
    assert call(c, "/v1/memories", token, "PUT", p).status_code == 204
    q = {key: p[key] for key in ("installationId", "vaultId")} | {"query": "anything", "topK": 5}
    assert call(c, "/v1/memories:query", token, payload=q).json["memories"][0]["content"] == "new"
    assert call(c, "/v1/memories:query", token, payload=q | {"userId": "other"}).status_code == 400
    assert call(c, "/v1/memories:query", token, payload=q | {"topK": True}).status_code == 400
    app.extensions["model"].embed = lambda _: (_ for _ in ()).throw(ModelUnavailable())
    assert call(c, "/v1/rag:answer", token, payload=q).status_code == 503
