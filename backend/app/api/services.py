from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app import repository
from app.db import get_session
from app.schemas import MetricPointOut, ServiceOut

router = APIRouter(prefix="/api/v1/services", tags=["services"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[ServiceOut])
def list_services(session: SessionDep) -> list[ServiceOut]:
    return [
        ServiceOut(
            id=service.id,
            name=service.name,
            description=service.description,
            active_incidents=active,
        )
        for service, active in repository.list_services(session)
    ]


@router.get("/{service_id}/metrics", response_model=list[MetricPointOut])
def service_metrics(
    service_id: str,
    session: SessionDep,
    since: Annotated[AwareDatetime | None, Query(description="Only samples after this")] = None,
    until: Annotated[AwareDatetime | None, Query(description="Only samples up to this")] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 360,  # 1 hour at one sample per 10 s
) -> list[MetricPointOut]:
    """Simulated metric samples of one service, oldest first (for charts)."""
    if repository.get_service(session, service_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="service not found")
    rows = repository.snapshots_since(session, service_id, since, limit, until)
    return [MetricPointOut.model_validate(row) for row in rows]
