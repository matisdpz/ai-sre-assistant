from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
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

    @field_validator("database_url")
    @classmethod
    def require_postgres_psycopg(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must start with postgresql+psycopg://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
