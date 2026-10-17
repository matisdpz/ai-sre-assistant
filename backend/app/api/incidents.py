import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import incident_manager, repository
from app.db import get_session
from app.models import IncidentStatus
from app.schemas import IncidentDetailOut, IncidentOut, IncidentSummaryOut, StatusChangeIn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    session: SessionDep,
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    service_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[IncidentOut]:
    """Incidents, newest first."""
    incidents = repository.list_incidents(
        session, status=status_filter, service_id=service_id, limit=limit, offset=offset
    )
    return [IncidentOut.model_validate(incident) for incident in incidents]


# Declared before /{incident_id}, which would otherwise try to parse "summary" as a UUID.
@router.get("/summary", response_model=IncidentSummaryOut)
def incident_summary(session: SessionDep) -> IncidentSummaryOut:
    """Counts by status and the classic SRE response times (MTTA, MTTR)."""
    return IncidentSummaryOut(**repository.incident_summary(session))


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def get_incident(incident_id: uuid.UUID, session: SessionDep) -> IncidentDetailOut:
    """One incident with its evidence and timeline."""
    incident = repository.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incident not found")
    return IncidentDetailOut.model_validate(incident)


def _change_status(
    session: Session,
    incident_id: uuid.UUID,
    to_status: IncidentStatus,
    body: StatusChangeIn | None,
) -> IncidentDetailOut:
    try:
        incident_manager.change_status(
            session, incident_id, to_status, body.note if body else None, now=datetime.now(UTC)
        )
    except incident_manager.IncidentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incident not found") from exc
    except incident_manager.InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    logger.info("incident status changed", extra={"incident_id": str(incident_id), "to": to_status})
    session.expire_all()  # re-read the committed state, timeline included
    return get_incident(incident_id, session)


@router.post(
    "/{incident_id}/acknowledge",
    response_model=IncidentDetailOut,
    responses={404: {}, 409: {"description": "Not open"}},
)
def acknowledge(
    incident_id: uuid.UUID,
    session: SessionDep,
    body: Annotated[StatusChangeIn | None, Body()] = None,
) -> IncidentDetailOut:
    """Someone is looking at it. Only an open incident can be acknowledged."""
    return _change_status(session, incident_id, IncidentStatus.ACKNOWLEDGED, body)


@router.post(
    "/{incident_id}/resolve",
    response_model=IncidentDetailOut,
    responses={404: {}, 409: {"description": "Already resolved"}},
)
def resolve(
    incident_id: uuid.UUID,
    session: SessionDep,
    body: Annotated[StatusChangeIn | None, Body()] = None,
) -> IncidentDetailOut:
    """Close the incident (final). A recurrence opens a new incident."""
    return _change_status(session, incident_id, IncidentStatus.RESOLVED, body)
