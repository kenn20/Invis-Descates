import pytest

from service.runtime import database_url, create_from_env


def test_hosted_runtime_requires_configuration_without_exposing_values(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(ValueError, match="configuration is missing"):
        create_from_env()


@pytest.mark.parametrize("url", ["sqlite:///state.db", "postgresql://u:p@db/app", "postgresql://u:p@db/app?sslmode=disable", "postgresql://u:p@db/app?sslmode=require"])
def test_production_rejects_local_or_unverified_database(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError):
        database_url()


def test_database_alias_normalization_preserves_certificate_verification(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db/app?sslmode=verify-full")
    assert database_url() == "postgresql+psycopg://u:p@db/app?sslmode=verify-full"


def test_production_rejects_placeholder_session_secret(monkeypatch):
    for key in ("PUBLIC_ORIGIN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MODEL_ENDPOINT", "MODEL_API_KEY", "EMBEDDING_MODEL", "GENERATION_MODEL"):
        monkeypatch.setenv(key, "placeholder")
    monkeypatch.setenv("SESSION_SECRET", "REPLACE_WITH_AT_LEAST_32_RANDOM_BYTES")
    with pytest.raises(ValueError, match="random session secret"):
        create_from_env()
