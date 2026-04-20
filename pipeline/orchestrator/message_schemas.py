"""v7.6 — Pydantic v2 message-boundary validation for KAIROS dispatcher.

Each subject has its own body schema. parse_message() validates body BEFORE dispatching
to handlers; on violation, the message is quarantined to /var/lib/karios/agent-msg/schema-violations/
and a [SCHEMA-VIOLATION] reply is sent to the originating agent.

Usage:
    from message_schemas import validate_body, SchemaViolation

    try:
        validate_body(subject, body)
    except SchemaViolation as e:
        # log, quarantine, reply
        ...
"""
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, ValidationError, field_validator
import json
import re


class SchemaViolation(Exception):
    """Raised when a message body fails Pydantic validation."""
    def __init__(self, subject: str, errors: list, body_preview: str = ""):
        self.subject = subject
        self.errors = errors
        self.body_preview = body_preview
        super().__init__(f"Schema violation on '{subject}': {errors}")


# ── Body models ────────────────────────────────────────────────────────────────

class ArchCompleteBody(BaseModel):
    """Architect → Orchestrator: Phase 2 architecture done."""
    gap_id: Optional[str] = None
    iteration: int = Field(default=1, ge=1, le=20)
    docs_written: Optional[List[str]] = None
    summary: Optional[str] = None


class ArchReviewedBody(BaseModel):
    """Architect-blind-tester → Orchestrator: review verdict."""
    gap_id: Optional[str] = None
    iteration: int = Field(default=1, ge=1, le=20)
    rating: int = Field(ge=0, le=10)
    recommendation: Literal["APPROVE", "REQUEST_CHANGES", "REJECT"] = "REQUEST_CHANGES"
    summary: str = ""
    critical_issues: List[Any] = Field(default_factory=list)
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    adversarial_test_cases: Dict[str, Any] = Field(default_factory=dict)


class CodingCompleteBody(BaseModel):
    """Backend/Frontend → Orchestrator: Phase 3 coding done."""
    gap_id: Optional[str] = None
    iteration: int = Field(default=1, ge=1, le=20)
    files_changed: Optional[List[str]] = None
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    summary: Optional[str] = None


class E2EResultsBody(BaseModel):
    """Code-blind-tester → Orchestrator: Phase 4 E2E results."""
    gap_id: Optional[str] = None
    iteration: int = Field(default=1, ge=1, le=20)
    rating: int = Field(ge=0, le=10)
    recommendation: Literal["APPROVE", "REQUEST_CHANGES", "REJECT"] = "REQUEST_CHANGES"
    summary: str = ""
    critical_issues: List[Any] = Field(default_factory=list)
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    adversarial_test_cases: Dict[str, Any] = Field(default_factory=dict)


class StagingDeployedBody(BaseModel):
    gap_id: Optional[str] = None
    iteration: int = Field(default=1, ge=1, le=20)
    md5sums: Dict[str, str] = Field(default_factory=dict)
    nodes: List[str] = Field(default_factory=list)


class ProdDeployedBody(BaseModel):
    gap_id: Optional[str] = None
    iteration: int = Field(default=1, ge=1, le=20)
    md5sums: Dict[str, str] = Field(default_factory=dict)
    gitea_pushed: Optional[bool] = None  # v7.6: gate evidence


class MonitoringCompleteBody(BaseModel):
    gap_id: Optional[str] = None
    incidents: int = Field(default=0, ge=0)
    summary: str = ""


# ── Subject → Schema mapping ───────────────────────────────────────────────────

_SUBJECT_TO_MODEL = {
    "[ARCH-COMPLETE]": ArchCompleteBody,
    "[ARCHITECTURE-COMPLETE]": ArchCompleteBody,
    "[ARCH-REVIEWED]": ArchReviewedBody,
    "[BLIND-REVIEWED]": ArchReviewedBody,
    "[CODING-COMPLETE]": CodingCompleteBody,
    "[FAN-IN]": CodingCompleteBody,
    "[E2E-RESULTS]": E2EResultsBody,
    "[BLIND-E2E-RESULTS]": E2EResultsBody,
    "[E2E-COMPLETE]": E2EResultsBody,
    "[TEST-RESULTS]": E2EResultsBody,
    "[STAGING-DEPLOYED]": StagingDeployedBody,
    "[DEPLOYED-STAGING]": StagingDeployedBody,
    "[STAGING-COMPLETE]": StagingDeployedBody,
    "[PROD-DEPLOYED]": ProdDeployedBody,
    "[DEPLOYED-PROD]": ProdDeployedBody,
    "[DEPLOY-DONE]": ProdDeployedBody,
    "[PRODUCTION-COMPLETE]": ProdDeployedBody,
    "[MONITORING-COMPLETE]": MonitoringCompleteBody,
}


def _model_for_subject(subject: str):
    for prefix, model in _SUBJECT_TO_MODEL.items():
        if subject.startswith(prefix):
            return model
    return None


def _extract_json_body(subject: str, body: str) -> Optional[dict]:
    """Best-effort JSON extraction matching v7.5 dispatcher behavior."""
    if not body:
        return None
    b = body.strip()
    # strip leading subject prefix line
    for prefix in _SUBJECT_TO_MODEL.keys():
        if b.startswith(prefix):
            b = b.split("\n", 1)[1] if "\n" in b else b
            break
    # extract fenced ```json block
    m = re.search(r"```(?:json)?\s*\n(.+?)\n```", b, re.DOTALL)
    if m:
        b = m.group(1)
    # fall back to first {…}
    if not b.strip().startswith("{"):
        m2 = re.search(r"\{.*\}", b, re.DOTALL)
        if m2:
            b = m2.group(0)
    try:
        return json.loads(b)
    except (json.JSONDecodeError, ValueError):
        return None


def validate_body(subject: str, body: str, log_only: bool = False) -> Optional[BaseModel]:
    """Validate body against the schema for subject. Returns model instance on success.

    If log_only=True, validation failures only log and return None (soft enforcement
    for the first iteration so we observe what blows up before refusing messages).

    Raises SchemaViolation when log_only=False and body is invalid.
    """
    model = _model_for_subject(subject)
    if model is None:
        return None  # Unknown subject; let dispatcher's existing handler decide
    extracted = _extract_json_body(subject, body)
    if extracted is None:
        if log_only:
            return None
        raise SchemaViolation(subject, ["could not extract JSON body"], body[:120])
    try:
        return model.model_validate(extracted)
    except ValidationError as e:
        if log_only:
            return None
        raise SchemaViolation(subject, [str(err) for err in e.errors()], body[:120])
