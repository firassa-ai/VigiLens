from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

CatalogSource = Literal["tracked", "dailymed", "faers"]


class CatalogSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generic_name: str
    brand_names: list[str]
    tracked: bool
    tracked_drug_id: str | None
    label_available: bool
    sources: list[CatalogSource]


class CatalogPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generic_name: str
    brand_names: list[str]
    tracked: bool
    tracked_drug_id: str | None
    dailymed_setid: str | None
    dailymed_title: str | None
    dailymed_published_date: str | None
    faers_available: bool
    faers_report_count: int | None
    faers_report_count_is_estimate: bool
