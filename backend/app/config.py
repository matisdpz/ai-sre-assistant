from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local development reads the repository-root .env file. In containers the file is
# absent and values come from real environment variables, which always take priority.
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    # SecretStr keeps the password out of repr() and accidental logs.
    database_url: SecretStr
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Shared secret the simulator sends as "Authorization: Bearer <token>".
    ingest_token: SecretStr
    # Optional AI diagnosis (Google Gemini). Without a key the feature is disabled and
    # everything else works normally.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    @field_validator("database_url")
    @classmethod
    def require_postgres_psycopg(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must start with postgresql+psycopg://")
        return value

    @field_validator("ingest_token")
    @classmethod
    def require_long_token(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 16:
            raise ValueError("INGEST_TOKEN must be at least 16 characters")
        return value

    @field_validator("gemini_api_key")
    @classmethod
    def blank_key_means_disabled(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
