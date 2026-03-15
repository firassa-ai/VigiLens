from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TrackingJobStatus = Literal["queued", "running", "ready", "failed"]
TrackingJobMode = Literal["onboard", "full_history_rebuild"]
TrackingJobStep = Literal[
    "queued",
    "resolving_identity",
    "fetching_faers",
    "deduping_transforming",
    "seeding_database",
    "computing_baseline_stats",
    "writing_memory",
    "ready",
    "failed",
]


class CreateTrackingJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_name: str = Field(min_length=2, max_length=120)
    baseline_quarters: int = Field(default=4, ge=1, le=8)
    max_reports: int | None = Field(default=1500, ge=200, le=5000)
    prefer_cached: bool = True


class CreateFullHistoryRebuildJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_quarters: int = Field(default=4, ge=1, le=8)
    prefer_cached: bool = False


class TrackingJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: TrackingJobStatus
    step: TrackingJobStep
    progress: int
    medication_name: str
    resolved_generic_name: str | None
    drug_id: str | None
    source: str | None
    error: str | None
    options_json: dict[str, Any]
    details_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
