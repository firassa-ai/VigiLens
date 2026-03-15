from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SeedDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_ids: list[str] = Field(min_length=1)
    preload_quarters: list[str] = Field(default_factory=list)
    data_dir: str | None = None


class SeedDemoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seeded_drugs: list[str]
    preload_quarters: list[str]
    reports_loaded: int
    reports_by_drug: dict[str, int]
