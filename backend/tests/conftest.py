from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import Session

from app.config import ROOT_ENV_FILE, Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


class _TestEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")
    test_database_url: str | None = None


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    # configparser treats % as interpolation; escape it in case the password contains one.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = _TestEnv().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    # These tests drop the whole schema: refuse anything that is not a test database.
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("refusing to run: database in TEST_DATABASE_URL must end with '_test'")
    return url


@pytest.fixture(scope="session")
def migrated_engine(test_database_url: str) -> Iterator[Engine]:
    cfg = alembic_config(test_database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session whose changes are rolled back after each test, even if it commits."""
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def db_client(test_database_url: str, migrated_engine: Engine) -> Iterator[TestClient]:
    app = create_app(Settings(database_url=test_database_url, app_env="test"))
    with TestClient(app) as client:
        yield client
