import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.models import Base

config = context.config

# Tests call Alembic with their own logging already configured.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    # Tests pass TEST_DATABASE_URL explicitly. The migration container only gets
    # DATABASE_URL (no other secret). Locally, fall back to the application settings.
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if url:
        return url
    from app.config import get_settings

    return get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Render SQL without a database connection (alembic upgrade head --sql)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
