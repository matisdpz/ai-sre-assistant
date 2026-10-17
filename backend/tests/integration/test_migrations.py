import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.conftest import alembic_config

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {"services", "metric_snapshots", "incidents", "incident_events"}


def test_upgrade_creates_tables_and_seeds_services(migrated_engine: Engine) -> None:
    assert set(inspect(migrated_engine).get_table_names()) >= EXPECTED_TABLES
    with migrated_engine.connect() as conn:
        ids = conn.scalars(text("SELECT id FROM services ORDER BY id")).all()
    assert ids == ["api-gateway", "database-service", "payment-service"]


def test_models_match_migrations(test_database_url: str, migrated_engine: Engine) -> None:
    # Fails if a model was changed without writing a migration for it.
    command.check(alembic_config(test_database_url))


def test_downgrade_then_upgrade_round_trip(test_database_url: str, migrated_engine: Engine) -> None:
    cfg = alembic_config(test_database_url)

    command.downgrade(cfg, "base")
    assert not EXPECTED_TABLES & set(inspect(migrated_engine).get_table_names())

    command.upgrade(cfg, "head")
    assert set(inspect(migrated_engine).get_table_names()) >= EXPECTED_TABLES
