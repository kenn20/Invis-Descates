import time

from sqlalchemy import select, update

from service.hosted import create_hosted_app
from service.identity import devices
from service.pairing import pairings
from service.tests.test_app import body

BASE = "https://companion.example"


def setup():
    app = create_hosted_app("sqlite://", BASE, "x" * 32,
        google_client_id="test-client", google_client_secret="test-secret")
    app.config["TESTING"] = True
    app.extensions["identity"].initialize()
    return app, app.test_client()


def start(c):
    return c.post("/auth/pairing/start", base_url=BASE, json={
        "installationId": body()["installationId"], "vaultId": body()["vaultId"], "deviceName": "Laptop"}).json


def poll(c, p):
    return c.post("/auth/pairing/poll", base_url=BASE, json={"pairingSecret": p["pairingSecret"]})


def ready(app, p):
    with app.extensions["identity"].engine.begin() as conn:
        conn.execute(update(pairings).where(pairings.c.code == p["userCode"]).values(last_poll=0))


def browser_login(app, c, p):
    with c.session_transaction(base_url=BASE) as s:
        s["pairing_code"] = p["userCode"]
    app.extensions["google"].authorize_access_token = lambda: {"id_token": "verified-by-separate-oidc-tests", "userinfo": {"iss": "https://accounts.google.com", "sub": "google-a"}}
    return c.get("/auth/google/callback", base_url=BASE)


def test_browser_approval_requires_csrf_and_poll_is_single_use():
    app, c = setup()
    p = start(c)
    assert "pairingSecret" not in p["verificationUrl"]
    assert poll(c, p).status_code == 202
    assert browser_login(app, c, p).status_code == 302
    page = c.get("/auth/approve", base_url=BASE)
    assert p["userCode"].encode() in page.data
    assert p["pairingSecret"].encode() not in page.data
    assert c.post("/auth/approve", base_url=BASE, data={"csrf": "bad"}).status_code == 403
    with c.session_transaction(base_url=BASE) as s:
        csrf = s["csrf"]
    assert c.post("/auth/approve", base_url=BASE, data={"csrf": csrf}).status_code == 200
    ready(app, p)
    response = poll(c, p)
    assert response.status_code == 200
    token = response.json["token"]
    assert app.extensions["identity"].authenticate(token) is not None
    assert poll(c, p).status_code == 410
    with app.extensions["identity"].engine.connect() as conn:
        assert len(conn.execute(select(devices)).all()) == 1
        assert p["pairingSecret"] not in str(conn.execute(select(pairings)).mappings().all())


def test_expiry_wrong_secret_nonce_state_failure_and_rate_limit():
    app, c = setup()
    p = start(c)
    assert poll(c, {"pairingSecret": "z" * 43}).status_code == 410
    app.extensions["google"].authorize_access_token = lambda: (_ for _ in ()).throw(ValueError("state or nonce mismatch"))
    assert c.get("/auth/google/callback", base_url=BASE).status_code == 401
    with app.extensions["identity"].engine.begin() as conn:
        conn.execute(update(pairings).values(expires_at=int(time.time()) - 1))
    assert poll(c, p).status_code == 410
    assert c.get("/auth/google?code=" + p["userCode"], base_url=BASE).status_code == 410
    for _ in range(9):
        assert start(c)["userCode"]
    assert c.post("/auth/pairing/start", base_url=BASE, json={
        "installationId": body()["installationId"], "vaultId": body()["vaultId"], "deviceName": "Laptop"}).status_code == 429


def test_no_approval_without_identity_and_wrong_issuer_fails():
    app, c = setup()
    p = start(c)
    with c.session_transaction(base_url=BASE) as s:
        s["pairing_code"] = p["userCode"]
    assert c.get("/auth/approve", base_url=BASE).status_code == 401
    app.extensions["google"].authorize_access_token = lambda: {"id_token": "verified-by-separate-oidc-tests", "userinfo": {"iss": "evil", "sub": "google-a"}}
    assert c.get("/auth/google/callback", base_url=BASE).status_code == 401
    assert poll(c, p).status_code == 202


def test_real_oidc_signature_audience_nonce_issuer_expiry_and_state(monkeypatch):
    """Exercise Authlib's real verification; only provider HTTP boundaries are replaced."""
    from joserfc import jwt
    from joserfc.jwk import RSAKey
    key = RSAKey.generate_key(2048, parameters={"kid": "google-test"})
    app, c = setup()
    google = app.extensions["google"]
    monkeypatch.setattr(google, "load_server_metadata", lambda: {
        "issuer": "https://accounts.google.com", "id_token_signing_alg_values_supported": ["RS256"]})
    monkeypatch.setattr(google, "fetch_jwk_set", lambda **_: {"keys": [key.as_dict(private=False)]})
    p = start(c)

    def callback(claim_changes=None, signing_key=key, saved=True):
        now = int(time.time())
        claims = {"iss": "https://accounts.google.com", "sub": "real-google-subject", "aud": "test-client",
            "iat": now, "exp": now + 300, "nonce": "saved-nonce"} | (claim_changes or {})
        encoded = jwt.encode({"alg": "RS256", "kid": "google-test"}, claims, signing_key)
        monkeypatch.setattr(google, "fetch_access_token", lambda **_: {"id_token": encoded, "access_token": "test-access"})
        with c.session_transaction(base_url=BASE) as s:
            s.clear()
            s["pairing_code"] = p["userCode"]
            if saved:
                google.framework.set_state_data(s, "saved-state", {"nonce": "saved-nonce", "redirect_uri": BASE + "/auth/google/callback"})
        return c.get("/auth/google/callback?code=authorization-code&state=saved-state", base_url=BASE)

    assert callback().status_code == 302
    for invalid in ({"aud": "other-client"}, {"nonce": "wrong"}, {"iss": "https://evil.example"}, {"exp": int(time.time()) - 600}):
        assert callback(invalid).status_code == 401
    other = RSAKey.generate_key(2048)
    assert callback(signing_key=other).status_code == 401
    assert callback(saved=False).status_code == 401
