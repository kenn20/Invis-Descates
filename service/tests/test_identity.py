import time
from uuid import uuid4

from sqlalchemy import select, update

from service.hosted import create_hosted_app
from service.identity import devices
from service.tests.test_app import body


def setup_app(database_url="sqlite://"):
    app = create_hosted_app(database_url, "https://companion.example", "x" * 32)
    app.config["TESTING"] = True
    store = app.extensions["identity"]
    store.initialize()
    user = store.user_for_google("google-a")
    with store.engine.begin() as conn:
        token, _ = store.issue_device(conn, user, body()["installationId"], body()["vaultId"])
    return app, store, token


def call(client, path, token, method="POST", payload=None):
    return client.open(path, method=method, base_url="https://companion.example",
        headers={"Authorization": f"Bearer {token}"}, json=payload)


def test_identity_persists_only_hash_and_survives_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'identity.db'}"
    app, store, token = setup_app(url)
    with store.engine.connect() as conn:
        row = conn.execute(select(devices)).mappings().one()
        assert token not in str(row)
    restarted = create_hosted_app(url, "https://companion.example", "x" * 32)
    assert call(restarted.test_client(), "/v1/nudges:evaluate", token, payload=body()).status_code == 200
    assert store.user_for_google("google-a") == store.authenticate(token).user_id


def test_wrong_expired_revoked_tokens_and_device_ownership():
    app, store, token = setup_app()
    c = app.test_client()
    assert call(c, "/v1/nudges:evaluate", "wrong", payload=body()).status_code == 401
    for field in ("vaultId", "installationId"):
        assert call(c, "/v1/nudges:evaluate", token, payload=body(**{field: str(uuid4())})).status_code == 403
    user_b = store.user_for_google("google-b")
    with store.engine.begin() as conn:
        try:
            store.issue_device(conn, user_b, str(uuid4()), body()["vaultId"])
            assert False, "Another user claimed a vault"
        except PermissionError:
            pass
    assert call(c, "/v1/pairing", token, method="DELETE").status_code == 204
    assert call(c, "/v1/nudges:evaluate", token, payload=body()).status_code == 401
    with store.engine.begin() as conn:
        conn.execute(update(devices).values(revoked=False, expires_at=int(time.time()) - 1))
    assert call(c, "/v1/nudges:evaluate", token, payload=body()).status_code == 401


def test_hosted_transport_and_malformed_payload_fail_closed():
    app, _, token = setup_app()
    c = app.test_client()
    assert c.get("/healthz", base_url="http://companion.example").status_code == 400
    assert c.get("/healthz", base_url="https://evil.example").status_code == 400
    assert c.options("/v1/nudges:evaluate", base_url="https://companion.example").status_code == 403
    for change in ({"signals": None}, {"trigger": []}, {"createdAt": 42}):
        assert call(c, "/v1/nudges:evaluate", token, payload=body(**change)).status_code == 400
    response = c.get("/healthz", base_url="https://companion.example")
    assert response.headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in response.headers


def test_unexpected_failure_never_logs_content_or_credentials(caplog, monkeypatch):
    app, store, token = setup_app()
    monkeypatch.setattr(store, "authenticate", lambda _: (_ for _ in ()).throw(RuntimeError("private-note-sentinel " + token)))
    response = call(app.test_client(), "/v1/nudges:evaluate", token, payload=body())
    assert response.status_code == 500
    assert "private-note-sentinel" not in caplog.text and token not in caplog.text
    assert not response.data


def test_repairing_rotates_token_without_changing_account_or_vault():
    app, store, old = setup_app()
    identity = store.authenticate(old)
    with store.engine.begin() as conn:
        new, _ = store.issue_device(conn, identity.user_id, identity.installation_id, identity.vault_id)
    assert store.authenticate(old) is None
    assert store.authenticate(new).user_id == identity.user_id
    assert store.authenticate(new).vault_id == identity.vault_id
