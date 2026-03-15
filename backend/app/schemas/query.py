from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str
    question_text: str = Field(min_length=1)
    quarter_context: str | None = None


class LLMBeliefPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_text: str
    confidence_narrative: int = Field(ge=0, le=100)
    risk_level: Literal["low", "moderate", "elevated", "high"]
    key_evidence_ids: list[str]
    reasoning_bullets: list[str]
