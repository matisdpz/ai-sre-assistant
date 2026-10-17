import pytest
from pydantic import ValidationError

from app.config import Settings

VALID_URL = "postgresql+psycopg://user:s3cret@localhost:5432/db"
VALID_TOKEN = "ingest-token-0123456789"


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("INGEST_TOKEN", VALID_TOKEN)

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == VALID_URL
    assert settings.log_level == "DEBUG"
    assert settings.app_env == "development"


def test_missing_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pw@localhost/db",  # missing the psycopg driver
        "sqlite:///local.db",
        "not a url",
    ],
)
def test_non_postgres_psycopg_url_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        Settings(_env_file=None, database_url=url, ingest_token=VALID_TOKEN)


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError, match="log_level"):
        Settings(
            _env_file=None, database_url=VALID_URL, ingest_token=VALID_TOKEN, log_level="VERBOSE"
        )


def test_password_is_not_shown_in_repr_or_str() -> None:
    settings = Settings(_env_file=None, database_url=VALID_URL, ingest_token=VALID_TOKEN)
    for secret in ("s3cret", VALID_TOKEN):
        assert secret not in repr(settings)
        assert secret not in str(settings)


def test_missing_ingest_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INGEST_TOKEN", raising=False)
    with pytest.raises(ValidationError, match="ingest_token"):
        Settings(_env_file=None, database_url=VALID_URL)


def test_short_ingest_token_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 16 characters"):
        Settings(_env_file=None, database_url=VALID_URL, ingest_token="change-me")
