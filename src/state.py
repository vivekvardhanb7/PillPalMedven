from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FactStatus(str, Enum):
    NOT_ASKED = "not_asked"
    UNKNOWN = "unknown"
    REPORTED = "reported"
    DENIED = "denied"
    NOT_APPLICABLE = "not_applicable"
    CONFLICTING = "conflicting"


class SubjectState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship: str | None = None
    age: int | None = Field(default=None, ge=0, le=130)


class ClinicalFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | int | float | bool | None = None
    status: FactStatus = FactStatus.NOT_ASKED
    subject_id: str | None = None
    supporting_text: str | None = None
    message_id: UUID | None = None
    recorded_at: datetime | None = None


class AssessmentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    revision: int = Field(default=0, ge=0)
    response_id: UUID | None = None
    language: Literal["de", "en", "unknown"] = "unknown"
    subject: SubjectState = Field(default_factory=SubjectState)
    complaints: list[ClinicalFact] = Field(default_factory=list)
    facts: dict[str, ClinicalFact] = Field(default_factory=dict)
    active_protocol_ids: list[str] = Field(default_factory=list)
    pending_question_ids: list[str] = Field(default_factory=list)
    pending_question_fact_ids: dict[str, str] = Field(default_factory=dict)
    ai_processing_consent: bool = False
    pending_ai_consent_message: str | None = None
    recommendation_requested: bool = False
    disposition: Literal[
        "assessment_incomplete",
        "unsupported",
        "self_care",
        "medicine_option",
        "pharmacist_referral",
        "medical_referral",
        "emergency",
    ] = "unsupported"
    candidate_product_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    protocol_versions: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime
