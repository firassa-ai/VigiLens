from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import FaersBackgroundCount
from app.utils.quarters import quarter_to_dates

_DEMO_START_COMPACT = "20180101"
_TABLE_READY = False
_FAILED_FETCH_KEYS: set[tuple[str, str]] = set()


async def _ensure_background_table(db: AsyncSession) -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return

    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS faers_background_counts (
              quarter TEXT NOT NULL,
              adverse_event TEXT NOT NULL,
              all_total_cumulative INTEGER NOT NULL,
              all_event_cumulative INTEGER NOT NULL,
              source TEXT NOT NULL DEFAULT 'openfda',
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              PRIMARY KEY (quarter, adverse_event)
            )
            """
        )
    )
    await db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_faers_background_quarter ON faers_background_counts(quarter)"
        )
    )
    _TABLE_READY = True


def _quarter_end_compact(quarter: str) -> str:
    _, quarter_end = quarter_to_dates(quarter)
    return quarter_end.strftime("%Y%m%d")


def _total_search_expr(quarter: str) -> str:
    return f"receivedate:[{_DEMO_START_COMPACT} TO {_quarter_end_compact(quarter)}]"


def _event_search_expr(quarter: str, adverse_event: str) -> str:
    escaped = adverse_event.replace('"', r'\"')
    return (
        f"receivedate:[{_DEMO_START_COMPACT} TO {_quarter_end_compact(quarter)}] "
        f"AND patient.reaction.reactionmeddrapt.exact:\"{escaped}\""
    )


def _extract_total(payload: dict) -> int | None:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    results = meta.get("results")
    if not isinstance(results, dict):
        return None
    total = results.get("total")
    if isinstance(total, int):
        return total
    return None


async def _fetch_total(settings: Settings, search_expr: str) -> int | None:
    params = {
        "search": search_expr,
        "limit": "1",
    }
    if settings.openfda_api_key:
        params["api_key"] = settings.openfda_api_key

    try:
        async with httpx.AsyncClient(timeout=settings.openfda_timeout_seconds) as client:
            response = await client.get(settings.openfda_api_base_url, params=params)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    return _extract_total(payload)


async def _upsert_background_count(
    db: AsyncSession,
    *,
    quarter: str,
    adverse_event: str,
    all_total_cumulative: int,
    all_event_cumulative: int,
    source: str,
) -> None:
    now = datetime.now(timezone.utc)
    row = {
        "quarter": quarter,
        "adverse_event": adverse_event,
        "all_total_cumulative": all_total_cumulative,
        "all_event_cumulative": all_event_cumulative,
        "source": source,
        "updated_at": now,
    }
    await db.execute(
        pg_insert(FaersBackgroundCount)
        .values(**row)
        .on_conflict_do_update(
            index_elements=[FaersBackgroundCount.quarter, FaersBackgroundCount.adverse_event],
            set_=row,
        )
    )


async def get_background_counts(
    db: AsyncSession,
    *,
    settings: Settings,
    quarter: str,
    adverse_event: str,
) -> tuple[int, int] | None:
    await _ensure_background_table(db)

    total_row = await db.scalar(
        select(FaersBackgroundCount).where(
            FaersBackgroundCount.quarter == quarter,
            FaersBackgroundCount.adverse_event == "__ALL__",
        )
    )
    event_row = await db.scalar(
        select(FaersBackgroundCount).where(
            FaersBackgroundCount.quarter == quarter,
            FaersBackgroundCount.adverse_event == adverse_event,
        )
    )

    total_count = int(total_row.all_total_cumulative) if total_row is not None else None
    event_count = int(event_row.all_event_cumulative) if event_row is not None else None

    if total_count is not None and event_count is not None:
        return total_count, event_count

    if not settings.openfda_live_background:
        return None

    total_key = (quarter, "__ALL__")
    event_key = (quarter, adverse_event)
    if total_count is None and total_key in _FAILED_FETCH_KEYS:
        return None
    if event_count is None and event_key in _FAILED_FETCH_KEYS:
        return None

    if total_count is None:
        total_count = await _fetch_total(settings, _total_search_expr(quarter))
        if total_count is not None:
            _FAILED_FETCH_KEYS.discard(total_key)
            await _upsert_background_count(
                db,
                quarter=quarter,
                adverse_event="__ALL__",
                all_total_cumulative=total_count,
                all_event_cumulative=total_count,
                source="openfda_live",
            )
            await db.flush()
        else:
            _FAILED_FETCH_KEYS.add(total_key)
            return None

    if event_count is None:
        event_count = await _fetch_total(settings, _event_search_expr(quarter, adverse_event))
        if event_count is not None and total_count is not None:
            _FAILED_FETCH_KEYS.discard(event_key)
            await _upsert_background_count(
                db,
                quarter=quarter,
                adverse_event=adverse_event,
                all_total_cumulative=total_count,
                all_event_cumulative=event_count,
                source="openfda_live",
            )
            await db.flush()
        else:
            _FAILED_FETCH_KEYS.add(event_key)

    if total_count is None or event_count is None:
        return None

    return total_count, event_count
