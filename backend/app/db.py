from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_db_engine(url: str) -> Engine:
    # create_engine does not connect yet: the API can start while the database is down,
    # and /health/ready reports it.
    return create_engine(
        url,
        pool_pre_ping=True,  # drop dead pooled connections instead of failing a request
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 5},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    with request.app.state.session_factory() as session:
        yield session
