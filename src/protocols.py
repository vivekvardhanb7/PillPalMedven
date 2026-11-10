import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ProtocolQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    fact_id: str
    prompt_en: str
    prompt_de: str
    required: bool = True


class ReviewedProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_id: str
    version: str
    status: Literal["draft", "active", "withdrawn"]
    approved: bool
    approved_by: str | None = None
    jurisdiction: Literal["DE"]
    symptom_terms: list[str] = Field(min_length=1)
    questions: list[ProtocolQuestion] = Field(min_length=1)
    assessment_guidance_en: str | None = None
    assessment_guidance_de: str | None = None
    permitted_product_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(min_length=1)
    source_versions: dict[str, str] = Field(min_length=1)


def load_reviewed_protocols(path: str | Path) -> list[ReviewedProtocol]:
    protocol_path = Path(path)
    if not protocol_path.exists():
        return []
    try:
        raw_protocols = json.loads(protocol_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to load reviewed protocols from {protocol_path}.") from error
    if not isinstance(raw_protocols, list):
        raise ValueError("The protocol catalog must contain a JSON array.")

    protocols: list[ReviewedProtocol] = []
    for raw_protocol in raw_protocols:
        try:
            protocol = ReviewedProtocol.model_validate(raw_protocol)
        except ValidationError as error:
            raise ValueError("The protocol catalog contains an invalid protocol record.") from error
        if (
            protocol.approved
            and protocol.status == "active"
            and protocol.approved_by
            and all(
                source_id in protocol.source_versions
                for source_id in protocol.source_ids
            )
        ):
            protocols.append(protocol)
    return protocols
