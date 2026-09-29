from __future__ import annotations

from service.app import MAX_EXCERPT_BYTES, create_app

TOKEN = "test-token"
UUIDS = {
    "requestId": "5f10bb46-ec2d-4fc5-b6cd-25eac5db1e71",
    "installationId": "e9382fe1-f383-47c6-9a32-cace44002651",
    "vaultId": "23626cd2-e72a-415d-ae8b-98c1d44bafcc",
    "noteId": "16c42420-cbc8-4b4a-a17a-457886117e49",
}


def body(**changes):
    value = {**UUIDS, "schemaVersion": 1, "revision": 1, "createdAt": "2026-09-11T19:30:00Z", "trigger": "idle", "excerpt": "A blocker", "signals": {"challengeScore": 0.9, "reflectionDepth": 0.2, "daysSinceUpdate": 2, "idleMs": 1450}}
    value.update(changes)
    return value


def client():
    app = create_app(TOKEN)
    app.config["TESTING"] = True
    return app.test_client()


def post(c, payload=None, token=TOKEN, remote="127.0.0.1", **kwargs):
    headers = {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:27123"}
    arguments = {"headers": headers, "environ_base": {"REMOTE_ADDR": remote}, **kwargs}
    if "data" not in arguments:
        arguments["json"] = body() if payload is None else payload
    return c.post("/v1/nudges:evaluate", **arguments)


def test_valid_request_returns_deterministic_show_decision():
    response = post(client())
    assert response.status_code == 200
    assert response.json["decision"] == "show"
    assert response.json["revision"] == 1


def test_missing_wrong_and_revoked_tokens_are_silent_unauthorized():
    c = client()
    assert post(c, token="wrong").status_code == 401
    assert c.delete("/v1/pairing", headers={"Authorization": f"Bearer {TOKEN}", "Host": "127.0.0.1:27123"}, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 204
    assert post(c).status_code == 401


def test_rejects_non_loopback_host_preflight_malformed_unknown_and_oversized_content():
    c = client()
    assert c.get("/healthz", headers={"Host": "evil.example"}, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 400
    assert post(c, remote="192.168.1.2").status_code == 403
    assert c.open("/v1/nudges:evaluate", method="OPTIONS", headers={"Host": "127.0.0.1:27123"}, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 403
    assert post(c, body(extra=True)).status_code == 400
    assert post(c, body(excerpt="x" * (MAX_EXCERPT_BYTES + 1))).status_code == 400
    assert post(c, data=b"{" + b"x" * 70000, content_type="application/json").status_code == 413
