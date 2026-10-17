import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import LiveResponse, ReadyResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    """The process is running. Never checks dependencies, so a database outage
    does not make an orchestrator restart a healthy API."""
    return LiveResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
def ready(session: Annotated[Session, Depends(get_session)], response: Response) -> ReadyResponse:
    """The API can serve requests: the database answers a trivial query."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Details go to the logs only; the response does not reveal hosts or errors.
        logger.warning("readiness check failed: database unreachable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="unavailable", checks={"database": "error"})
    return ReadyResponse(status="ok", checks={"database": "ok"})
