from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestNextQuarterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str


class IngestResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str
    hard: bool = False


class IngestStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str
    quarters_loaded: list[str]
    next_quarter: str | None
    total_reports_loaded: int
    total_quarters_available: int
    evermemos_status: Literal["idle", "ingesting", "consolidating", "ready"]


class AgentThought(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "perceive",
        "tool",
        "memory_query",
        "memory_recall",
        "reasoning",
        "reinterpretation",
        "memory_write",
        "foresight",
        "action",
    ]
    content: str
    timestamp: str
    memory_refs: list[str] | None = None
    metadata: dict[str, Any] | None = None


class IngestProgressMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal[
        "starting",
        "loading_reports",
        "computing_signals",
        "posting_evermemos",
        "generating_beliefs",
        "done",
        "error",
    ]
    quarter: str
    reports_processed: int
    total_reports: int
    signals_updated: int
    evermemos_consolidation_status: Literal["idle", "posting", "ready", "failed"]
    detail: str | None = Field(default=None)
    thoughts: list[AgentThought] | None = None


class IngestProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: IngestProgressMessage
