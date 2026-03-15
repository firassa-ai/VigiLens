from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_evermemos_tables(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS evermemos_requests (
              id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
              drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
              quarter TEXT NULL,
              endpoint TEXT NOT NULL,
              request_body JSONB NOT NULL,
              response_body JSONB NULL,
              status TEXT NOT NULL CHECK (status IN ('pending','ok','failed')) DEFAULT 'pending',
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_evermemos_requests_drug
            ON evermemos_requests(drug_id, created_at)
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS evermemos_memory_cache (
              memory_id TEXT PRIMARY KEY,
              drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
              group_id TEXT NULL,
              memory_type TEXT NULL,
              quarter TEXT NULL,
              source_endpoint TEXT NULL,
              raw_payload JSONB NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_evermemos_memory_cache_drug_seen
            ON evermemos_memory_cache(drug_id, last_seen_at DESC)
            """
        )
    )
