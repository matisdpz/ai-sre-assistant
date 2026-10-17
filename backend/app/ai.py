"""AI providers for optional incident diagnosis.

The rest of the backend only knows the `DiagnosisProvider` protocol. Detection never
imports this module: the application works fully without an AI provider.
"""

import json
import logging
from typing import Any, Literal, Protocol

import httpx2
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


# --- what a provider must return ------------------------------------------------------


class Hypothesis(BaseModel):
    title: str = Field(max_length=200)
    reasoning: str = Field(max_length=1500)
    confidence: Literal["low", "medium", "high"]
    supporting_facts: list[str] = Field(default_factory=list, max_length=8)


class AIDiagnosis(BaseModel):
    """Generated content only: hypotheses, never a confirmed root cause."""

    summary: str = Field(max_length=800)
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=4)
    suggested_checks: list[str] = Field(min_length=1, max_length=6)


# --- errors, each mapped to a clear HTTP response by the API ---------------------------


class AIError(Exception):
    """Base class. `message` is safe to show to users (no key, no raw provider output)."""

    status_code = 502

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AIQuotaError(AIError):
    status_code = 429


class AITimeoutError(AIError):
    status_code = 504


class AIUnavailableError(AIError):
    status_code = 502


class AIInvalidResponseError(AIError):
    status_code = 502


class DiagnosisProvider(Protocol):
    name: str
    model: str

    def diagnose(self, context: dict[str, Any]) -> AIDiagnosis: ...


# --- prompt -----------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """\
You assist a site reliability engineer investigating an incident in a SIMULATED system.
You receive JSON with the incident, facts computed from stored metrics, the detection
thresholds and the metrics of the affected service.

Rules:
- Base every statement only on the provided data. Do not invent metrics, logs or events.
- Give 1 to 4 hypotheses about possible causes, each with a confidence (low, medium, high)
  and the provided facts that support it.
- Never present a hypothesis as a confirmed root cause; the data cannot confirm one.
- Suggest 1 to 6 concrete checks an engineer could run to confirm or rule out hypotheses.
- Be concise. Answer with JSON only, matching the requested schema.
"""

# OpenAPI-style schema accepted by the Gemini API's responseSchema.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "hypotheses": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "reasoning": {"type": "STRING"},
                    "confidence": {"type": "STRING", "enum": ["low", "medium", "high"]},
                    "supporting_facts": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["title", "reasoning", "confidence", "supporting_facts"],
            },
        },
        "suggested_checks": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["summary", "hypotheses", "suggested_checks"],
}


# --- Gemini -----------------------------------------------------------------------------


class GeminiProvider:
    """Google Gemini over its REST API (generateContent), with the server-side key."""

    name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 20.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._http = httpx2.Client(
            base_url=self.BASE_URL,
            # Header, not a query parameter: keys in URLs end up in proxy and access logs.
            headers={"x-goog-api-key": api_key},
            timeout=timeout,
            transport=transport,
        )

    def diagnose(self, context: dict[str, Any]) -> AIDiagnosis:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(context)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "temperature": 0.2,
            },
        }
        try:
            response = self._http.post(f"/models/{self.model}:generateContent", json=body)
        except httpx2.TimeoutException as exc:
            raise AITimeoutError("The AI provider did not answer in time. Try again.") from exc
        except httpx2.TransportError as exc:
            raise AIUnavailableError("The AI provider is unreachable.") from exc

        if response.status_code != 200:
            raise self._error_for(response)
        return self._parse(response)

    def _error_for(self, response: httpx2.Response) -> AIError:
        status = response.status_code
        # Log the provider's message for operators; never forward it raw to users.
        logger.warning("gemini error %s: %s", status, response.text[:500])
        if status == 429:
            return AIQuotaError(
                "Gemini quota or rate limit reached (free tier limits apply). "
                "Try again later; the rest of the application keeps working."
            )
        if status in (401, 403):
            return AIUnavailableError("Gemini rejected the API key. Check GEMINI_API_KEY.")
        if status == 400:
            return AIUnavailableError(
                "Gemini rejected the request. Check GEMINI_MODEL and the server logs."
            )
        return AIUnavailableError(f"Gemini is unavailable (HTTP {status}). Try again later.")

    def _parse(self, response: httpx2.Response) -> AIDiagnosis:
        try:
            payload = response.json()
            candidate = payload["candidates"][0]
            text = candidate["content"]["parts"][0]["text"]
            return AIDiagnosis.model_validate_json(text)
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            reason = _finish_reason(response)
            logger.warning("unusable gemini response (finish reason %s)", reason, exc_info=True)
            raise AIInvalidResponseError(
                "The AI answer could not be used"
                + (f" (stopped: {reason})" if reason else "")
                + ". Try again."
            ) from exc

    def close(self) -> None:
        self._http.close()


def _finish_reason(response: httpx2.Response) -> str | None:
    try:
        payload = response.json()
        blocked = payload.get("promptFeedback", {}).get("blockReason")
        return blocked or payload["candidates"][0].get("finishReason")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


# --- fake, for tests and demos without a key ------------------------------------------


class FakeProvider:
    """Deterministic provider for tests. Never calls the network."""

    name = "fake"
    model = "fake-model"

    def __init__(self, error: AIError | None = None) -> None:
        self.error = error
        self.contexts: list[dict[str, Any]] = []

    def diagnose(self, context: dict[str, Any]) -> AIDiagnosis:
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        incident = context["incident"]
        return AIDiagnosis(
            summary=f"Fake diagnosis of {incident['type']} on {incident['service_id']}.",
            hypotheses=[
                Hypothesis(
                    title="Possible dependency degradation",
                    reasoning="Generated by the fake provider for tests.",
                    confidence="low",
                    supporting_facts=context["facts"][:1],
                )
            ],
            suggested_checks=["Compare with the dependency's metrics."],
        )
