import pytest
import requests

from service.model import ModelClient, ModelUnavailable


def client():
    return ModelClient("https://model.example/v1", "server-key-sentinel", "embedding-model", "generation-model")


def test_provider_credentials_stay_in_headers_and_redirects_are_disabled(monkeypatch):
    seen = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": [{"embedding": [1.0, 0.5]}]}
    def post(url, **kwargs):
        seen.append((url, kwargs))
        return Response()
    monkeypatch.setattr(requests, "post", post)
    assert client().embed("memory") == [1.0, 0.5]
    url, options = seen[0]
    assert options["headers"]["Authorization"] == "Bearer server-key-sentinel"
    assert "server-key-sentinel" not in url and "server-key-sentinel" not in str(options["json"])
    assert options["allow_redirects"] is False
    assert options["timeout"] == (3, 10)


def test_provider_errors_and_invalid_embeddings_fail_closed(monkeypatch):
    model = client()
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("server-key-sentinel")))
    with pytest.raises(ModelUnavailable) as caught:
        model.embed("memory")
    assert "server-key-sentinel" not in str(caught.value)
    for vector in ([], [0, 0], [True], [float("nan")], [float("inf")]):
        monkeypatch.setattr(model, "_post", lambda *args, v=vector: {"data": [{"embedding": v}]})
        with pytest.raises(ModelUnavailable):
            model.embed("memory")
    with pytest.raises(ValueError):
        ModelClient("http://model.example/v1", "key", "embed", "generate")
