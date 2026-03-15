from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    postgres_ok: bool
    evermemos_ok: bool
    timestamp: str
    evermemos_version: str | None = None
