from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.tracking_jobs import CreateTrackingJobRequest, TrackingJobResponse
from app.services.tracking_job_service import TrackingJobRuntime, create_tracking_job, get_tracking_job

router = APIRouter()


def _get_tracking_job_runtime(request: Request) -> TrackingJobRuntime:
    return request.app.state.tracking_job_runtime


@router.post("/tracking/jobs", response_model=TrackingJobResponse)
async def create_tracking_job_endpoint(
    payload: CreateTrackingJobRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TrackingJobResponse:
    job = await create_tracking_job(
        db,
        medication_name=payload.medication_name,
        baseline_quarters=payload.baseline_quarters,
        max_reports=payload.max_reports,
        prefer_cached=payload.prefer_cached,
    )
    _get_tracking_job_runtime(request).start_job(job.id)
    return job


@router.get("/tracking/jobs/{job_id}", response_model=TrackingJobResponse)
async def get_tracking_job_endpoint(
    job_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> TrackingJobResponse:
    return await get_tracking_job(db, job_id=job_id)
