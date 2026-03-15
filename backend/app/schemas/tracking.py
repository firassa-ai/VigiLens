from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OnboardDrugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_name: str = Field(min_length=2, max_length=120)
    baseline_quarters: int = Field(default=4, ge=1, le=8)
    max_reports: int = Field(default=1500, ge=200, le=5000)
    prefer_cached: bool = True


class OnboardDrugResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str
    generic_name: str
    source: Literal["existing", "cache", "openfda"]
    created: bool
    reports_loaded: int
    baseline_quarters_loaded: list[str]
    next_quarter: str | None
    message: str
