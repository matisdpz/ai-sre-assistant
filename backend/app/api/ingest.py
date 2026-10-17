import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import incident_manager
from app.db import get_session
from app.schemas import IncidentDecisionOut, IngestResponse, MetricBatchIn

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


def require_ingest_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = request.app.state.settings.ingest_token.get_secret_value()
    # compare_digest takes the same time whatever the input: no timing side channel.
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing ingest token",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(
    prefix="/api/v1/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_ingest_token)],
)


@router.post("/metrics", response_model=IngestResponse)
def ingest_metrics(
    batch: MetricBatchIn, session: Annotated[Session, Depends(get_session)]
) -> IngestResponse:
    """Store a batch of simulated metric samples and run incident detection on them."""
    try:
        result = incident_manager.ingest(session, batch.samples)
    except incident_manager.UnknownServiceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    logger.info(
        "metrics ingested",
        extra={
            "stored": result.stored,
            "duplicates": result.duplicates,
            "late": result.late,
            "decisions": len(result.decisions),
        },
    )
    return IngestResponse(
        stored=result.stored,
        duplicates=result.duplicates,
        late=result.late,
        decisions=[
            IncidentDecisionOut(
                incident_id=applied.incident_id,
                service_id=applied.service_id,
                type=applied.decision.incident_type,
                kind=applied.decision.kind,
                severity=applied.decision.severity,
            )
            for applied in result.decisions
        ],
    )
