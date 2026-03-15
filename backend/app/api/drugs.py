from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import IngestionState
from app.db.session import get_db_session
from app.schemas.shared import (
    CasefileSummary,
    DeleteDrugResponse,
    Drug,
    DrugProfile,
    EpisodicSummary,
    FDAAction,
    ForesightMemoryStatus,
    ScorecardEntry,
    SignalPoint,
    SituationAnalysis,
)
from app.schemas.tracking_jobs import CreateFullHistoryRebuildJobRequest, TrackingJobResponse
from app.services.drug_insights_service import (
    delete_tracked_drug,
    get_active_signals,
    get_casefile_summary,
    get_drug_episodes,
    get_drug_profile,
    get_fda_actions,
    get_foresight_memory_status,
    get_prediction_scorecard,
    list_drugs_with_status,
)
from app.services.evermemos_client import EvermemosClient
from app.services.signal_engine import fetch_timeline_points
from app.services.situation_engine import generate_situation_analysis
from app.services.tracking_job_service import TrackingJobRuntime, create_full_history_rebuild_job
from app.services.tracking_job_service import get_active_full_history_rebuild_job

router = APIRouter()


def _parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _get_evermemos_client(request: Request) -> EvermemosClient:
    return request.app.state.evermemos_client


def _get_tracking_job_runtime(request: Request) -> TrackingJobRuntime:
    return request.app.state.tracking_job_runtime


@router.get("/drugs", response_model=list[Drug])
async def get_drugs(db: AsyncSession = Depends(get_db_session)) -> list[Drug]:
    return await list_drugs_with_status(db)


@router.delete("/drugs/{drug_id}", response_model=DeleteDrugResponse)
async def delete_drug(
    drug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DeleteDrugResponse:
    return await delete_tracked_drug(
        db,
        drug_id=drug_id,
        evermemos_client=_get_evermemos_client(request),
    )


@router.post("/drugs/{drug_id}/rebuild-full-history", response_model=TrackingJobResponse)
async def rebuild_full_history(
    drug_id: str,
    payload: CreateFullHistoryRebuildJobRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TrackingJobResponse:
    job = await create_full_history_rebuild_job(
        db,
        drug_id=drug_id,
        baseline_quarters=payload.baseline_quarters,
        prefer_cached=payload.prefer_cached,
    )
    if job.status == "queued":
        _get_tracking_job_runtime(request).start_job(job.id)
    return job


@router.get("/drugs/{drug_id}/rebuild-full-history", response_model=TrackingJobResponse)
async def get_active_rebuild_full_history(
    drug_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> TrackingJobResponse:
    return await get_active_full_history_rebuild_job(db, drug_id=drug_id)


@router.get("/drugs/{drug_id}/timeline", response_model=list[SignalPoint])
async def get_drug_timeline(
    drug_id: str,
    events: str | None = Query(default=None),
    quarters: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> list[SignalPoint]:
    try:
        return await fetch_timeline_points(
            db,
            drug_id=drug_id,
            events=_parse_csv(events),
            quarters=_parse_csv(quarters),
        )
    except ValueError as exc:
        raise AppError(error="BadRequest", detail=str(exc), status_code=400) from exc


@router.get("/drugs/{drug_id}/signals", response_model=list[SignalPoint])
async def get_signals(
    drug_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> list[SignalPoint]:
    return await get_active_signals(db, drug_id=drug_id)


@router.get("/drugs/{drug_id}/casefile-summary", response_model=CasefileSummary)
async def get_casefile_summary_route(
    drug_id: str,
    request: Request,
    quarter: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> CasefileSummary:
    return await get_casefile_summary(
        db,
        drug_id=drug_id,
        quarter=quarter,
        settings=request.app.state.settings,
    )


@router.get("/drugs/{drug_id}/profile", response_model=DrugProfile)
async def get_profile(
    drug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DrugProfile:
    return await get_drug_profile(
        db,
        evermemos_client=_get_evermemos_client(request),
        drug_id=drug_id,
    )


@router.get("/drugs/{drug_id}/episodes", response_model=list[EpisodicSummary])
async def get_episodes(
    drug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> list[EpisodicSummary]:
    return await get_drug_episodes(
        db,
        evermemos_client=_get_evermemos_client(request),
        drug_id=drug_id,
    )


@router.get("/drugs/{drug_id}/fda-actions", response_model=list[FDAAction])
async def get_actions(
    drug_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> list[FDAAction]:
    return await get_fda_actions(db, drug_id=drug_id)


@router.get("/drugs/{drug_id}/scorecard", response_model=list[ScorecardEntry])
async def get_scorecard(
    drug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> list[ScorecardEntry]:
    return await get_prediction_scorecard(
        db,
        drug_id=drug_id,
        settings=request.app.state.settings,
    )


@router.get("/drugs/{drug_id}/foresight-status", response_model=ForesightMemoryStatus)
async def get_foresight_status(
    drug_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> ForesightMemoryStatus:
    return await get_foresight_memory_status(
        db,
        drug_id=drug_id,
    )


@router.get("/drugs/{drug_id}/situation", response_model=SituationAnalysis)
async def get_situation(
    drug_id: str,
    request: Request,
    quarter: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> SituationAnalysis:
    from app.utils.quarters import sort_quarters

    if quarter is None:
        state = await db.scalar(
            sa_select(IngestionState).where(IngestionState.drug_id == drug_id)
        )
        loaded = sort_quarters(list(state.quarters_loaded or [])) if state else []
        if not loaded:
            raise AppError(error="BadRequest", detail="No quarters loaded", status_code=400)
        quarter = loaded[-1]

    return await generate_situation_analysis(
        db,
        settings=request.app.state.settings,
        drug_id=drug_id,
        quarter=quarter,
        evermemos_client=None,
    )
