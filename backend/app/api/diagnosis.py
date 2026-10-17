import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import diagnosis, repository
from app.ai import AIError, DiagnosisProvider
from app.db import get_session
from app.incident_manager import IncidentNotFoundError
from app.models import IncidentDiagnosis
from app.schemas import AIStatusOut, DiagnosisOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["ai diagnosis"])
SessionDep = Annotated[Session, Depends(get_session)]


def get_provider(request: Request) -> DiagnosisProvider | None:
    return request.app.state.diagnosis_provider


ProviderDep = Annotated[DiagnosisProvider | None, Depends(get_provider)]


def _out(row: IncidentDiagnosis) -> DiagnosisOut:
    return DiagnosisOut(
        id=row.id,
        incident_id=row.incident_id,
        provider=row.provider,
        model=row.model,
        created_at=row.created_at,
        facts=row.facts,
        **row.result,
    )


@router.get("/ai/status", response_model=AIStatusOut)
def ai_status(provider: ProviderDep) -> AIStatusOut:
    """Whether AI diagnosis is configured. The dashboard hides or explains the button."""
    if provider is None:
        return AIStatusOut(enabled=False, provider=None, model=None)
    return AIStatusOut(enabled=True, provider=provider.name, model=provider.model)


@router.get(
    "/incidents/{incident_id}/diagnosis",
    response_model=DiagnosisOut,
    responses={404: {"description": "No diagnosis requested yet"}},
)
def latest_diagnosis(incident_id: uuid.UUID, session: SessionDep) -> DiagnosisOut:
    """The latest stored diagnosis. Reading it never calls the AI provider."""
    row = repository.latest_diagnosis(session, incident_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no diagnosis yet")
    return _out(row)


@router.post(
    "/incidents/{incident_id}/diagnosis",
    response_model=DiagnosisOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Incident not found"},
        429: {"description": "AI provider quota or rate limit reached"},
        502: {"description": "AI provider error or unusable answer"},
        503: {"description": "AI diagnosis is not configured"},
        504: {"description": "AI provider timeout"},
    },
)
def request_diagnosis(
    incident_id: uuid.UUID, session: SessionDep, provider: ProviderDep
) -> DiagnosisOut:
    """Ask the AI provider for hypotheses. Only on explicit user request; may use quota."""
    if provider is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI diagnosis is disabled: no GEMINI_API_KEY is configured on the server.",
        )
    try:
        row = diagnosis.request_diagnosis(session, incident_id, provider)
    except IncidentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="incident not found") from exc
    except AIError as exc:
        logger.warning(
            "ai diagnosis failed",
            extra={"incident_id": str(incident_id), "error": type(exc).__name__},
        )
        raise HTTPException(exc.status_code, detail=exc.message) from exc

    logger.info(
        "ai diagnosis created",
        extra={"incident_id": str(incident_id), "provider": row.provider, "model": row.model},
    )
    return _out(row)
