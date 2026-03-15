from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Belief as BeliefRow
from app.db.models import Drug, EvermemosMemoryCache
from app.db.session import get_db_session
from app.schemas.query import QueryRequest
from app.schemas.shared import Belief, BeliefDiff, FAERSReport, MemoryProxyResponse, QueryResponse
from app.services.evermemos_client import EvermemosClient
from app.services.belief_engine import (
    belief_row_to_schema,
    get_belief_row_or_400,
    list_beliefs,
    run_query,
)
from app.services.evidence_service import get_evidence_report
from app.utils.diff import compute_belief_diff
from app.utils.quarters import parse_quarter

router = APIRouter()


def _get_evermemos_client(request: Request) -> EvermemosClient:
    return request.app.state.evermemos_client


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> QueryResponse:
    settings = request.app.state.settings
    return await run_query(
        db,
        settings=settings,
        drug_id=payload.drug_id,
        question_text=payload.question_text,
        quarter_context=payload.quarter_context,
        evermemos_client=_get_evermemos_client(request),
    )


@router.get("/beliefs/{drug_id}", response_model=list[Belief])
async def get_beliefs(
    drug_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> list[Belief]:
    return await list_beliefs(db, drug_id)


@router.get("/beliefs/{drug_id}/diff", response_model=BeliefDiff)
async def get_belief_diff(
    drug_id: str,
    before_id: str = Query(...),
    after_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> BeliefDiff:
    before_row = await get_belief_row_or_400(db, before_id)
    after_row = await get_belief_row_or_400(db, after_id)

    if before_row.drug_id != drug_id or after_row.drug_id != drug_id:
        raise AppError(
            error="BadRequest",
            detail="belief ids do not belong to requested drug_id",
            status_code=400,
        )

    if before_row.question_hash != after_row.question_hash:
        raise AppError(
            error="BadRequest",
            detail="before_id and after_id must share the same question_hash",
            status_code=400,
        )

    before_quarter = parse_quarter(before_row.quarter_context)
    after_quarter = parse_quarter(after_row.quarter_context)
    lower_quarter, upper_quarter = sorted((before_quarter, after_quarter))
    rows = (
        (
            await db.execute(
                select(BeliefRow)
                .where(
                    BeliefRow.drug_id == drug_id,
                    BeliefRow.question_hash == before_row.question_hash,
                )
                .order_by(BeliefRow.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    reinterpreted_ids: list[str] = []
    seen_ids: set[str] = set()
    for row in rows:
        quarter_value = parse_quarter(row.quarter_context)
        if quarter_value < lower_quarter or quarter_value > upper_quarter:
            continue
        for report_id in row.reinterpreted_report_ids or []:
            if report_id in seen_ids:
                continue
            seen_ids.add(report_id)
            reinterpreted_ids.append(report_id)

    return compute_belief_diff(
        before=belief_row_to_schema(before_row),
        after=belief_row_to_schema(after_row),
        reinterpreted_ids=reinterpreted_ids,
    )


@router.get("/evidence/{report_id}", response_model=FAERSReport)
async def get_evidence(
    report_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> FAERSReport:
    return await get_evidence_report(db, report_id)


@router.get("/memory-proxy/{memory_id}", response_model=MemoryProxyResponse)
async def get_memory_proxy(
    memory_id: str,
    request: Request,
    drug_id: str = Query(...),
    refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryProxyResponse:
    if not memory_id.strip():
        raise AppError(error="BadRequest", detail="memory_id is required", status_code=400)

    exists = await db.scalar(select(Drug.id).where(Drug.id == drug_id))
    if not exists:
        raise AppError(error="BadRequest", detail=f"drug_id '{drug_id}' not found", status_code=400)

    cache_row = await db.scalar(
        select(EvermemosMemoryCache).where(
            EvermemosMemoryCache.drug_id == drug_id,
            EvermemosMemoryCache.memory_id == memory_id,
        )
    )
    cached = cache_row is not None
    refreshed = False

    if refresh:
        refreshed_row, refresh_hit = await _get_evermemos_client(request).refresh_memory_by_id(
            db,
            drug_id=drug_id,
            memory_id=memory_id,
        )
        if refreshed_row is not None:
            cache_row = refreshed_row
            cached = True
        refreshed = refresh_hit

    if cache_row is None:
        raise AppError(
            error="NotFound",
            detail=f"memory_id '{memory_id}' is not cached for drug_id '{drug_id}'",
            status_code=404,
        )

    return MemoryProxyResponse(
        memory_id=cache_row.memory_id,
        drug_id=cache_row.drug_id,
        cached=cached,
        refreshed=refreshed,
        memory_type=cache_row.memory_type,
        group_id=cache_row.group_id,
        quarter=cache_row.quarter,
        source_endpoint=cache_row.source_endpoint,
        payload=cache_row.raw_payload,
    )
