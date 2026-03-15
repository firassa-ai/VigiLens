from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_casefile_schema(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS term_level TEXT NOT NULL DEFAULT 'pt'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS family_key TEXT NULL
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS family_label TEXT NULL
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS bcpnn_ic DOUBLE PRECISION NULL
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS bcpnn_ic025 DOUBLE PRECISION NULL
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS ebgm DOUBLE PRECISION NULL
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS eb05 DOUBLE PRECISION NULL
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS method_votes JSONB NOT NULL DEFAULT '{}'::jsonb
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS consensus_tier TEXT NOT NULL DEFAULT 'none'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS label_status TEXT NOT NULL DEFAULT 'unknown'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS priority_flag BOOLEAN NOT NULL DEFAULT FALSE
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE quarterly_stats
            ADD COLUMN IF NOT EXISTS supporting_terms TEXT[] NOT NULL DEFAULT '{}'::text[]
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'public'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS track TEXT NOT NULL DEFAULT 'receipt'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS novelty_status TEXT NOT NULL DEFAULT 'label_gap'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS evidence_grade TEXT NOT NULL DEFAULT 'moderate'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS trigger_basis TEXT NOT NULL DEFAULT 'signal_threshold'
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS label_gap BOOLEAN NOT NULL DEFAULT FALSE
            """
        )
    )
