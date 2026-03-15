from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Select, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Drug, TrackingJob
from app.schemas.tracking_jobs import TrackingJobResponse
from app.services.evermemos_client import EvermemosClient
from app.services.onboarding_service import onboard_drug

_TRACKING_JOBS_TABLE_READY = False
_NON_TERMINAL_STATUSES = {"queued", "running"}
_RESTART_FAILURE_MESSAGE = "Server restarted during tracking job. Start monitoring again."
_MISSING_JOB_MESSAGE = "Tracking job was not found."
_UPDATE_SENTINEL = object()


def _job_error_message(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.detail
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "openFDA timed out while fetching FAERS history. Retry the rebuild in a minute."
    message = str(exc).strip()
    return message or "Tracking job failed."


async def _ensure_tracking_jobs_table(db: AsyncSession) -> None:
    global _TRACKING_JOBS_TABLE_READY
    if _TRACKING_JOBS_TABLE_READY:
        return

    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS tracking_jobs (
              id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
              status TEXT NOT NULL CHECK (status IN ('queued','running','ready','failed')) DEFAULT 'queued',
              step TEXT NOT NULL CHECK (
                step IN (
                  'queued',
                  'resolving_identity',
                  'fetching_faers',
                  'deduping_transforming',
                  'seeding_database',
                  'computing_baseline_stats',
                  'writing_memory',
                  'ready',
                  'failed'
                )
              ) DEFAULT 'queued',
              progress INTEGER NOT NULL CHECK (progress >= 0 AND progress <= 100) DEFAULT 0,
              medication_name TEXT NOT NULL,
              resolved_generic_name TEXT NULL,
              drug_id TEXT NULL,
              source TEXT NULL,
              error TEXT NULL,
              options_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await db.execute(
        text(
            """
            ALTER TABLE tracking_jobs
            ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{}'::jsonb
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_tracking_jobs_status_updated
            ON tracking_jobs(status, updated_at DESC)
            """
        )
    )
    _TRACKING_JOBS_TABLE_READY = True


def _status_for_step(step: str) -> str:
    if step in {"queued", "ready", "failed"}:
        return step
    return "running"


def _tracking_job_query(job_id: UUID) -> Select[tuple[TrackingJob]]:
    return select(TrackingJob).where(TrackingJob.id == job_id)


def _full_history_rebuild_job_query(*, drug_id: str) -> Select[tuple[TrackingJob]]:
    return (
        select(TrackingJob)
        .where(TrackingJob.drug_id == drug_id)
        .where(TrackingJob.options_json["mode"].astext == "full_history_rebuild")
        .order_by(TrackingJob.created_at.desc())
    )


async def _get_tracking_job_or_raise(db: AsyncSession, job_id: UUID) -> TrackingJob:
    await _ensure_tracking_jobs_table(db)
    job = await db.scalar(_tracking_job_query(job_id))
    if job is None:
        raise AppError(error="NotFound", detail=_MISSING_JOB_MESSAGE, status_code=404)
    return job


async def _update_tracking_job(
    db: AsyncSession,
    *,
    job_id: UUID,
    status: str | object = _UPDATE_SENTINEL,
    step: str | object = _UPDATE_SENTINEL,
    progress: int | object = _UPDATE_SENTINEL,
    resolved_generic_name: str | None | object = _UPDATE_SENTINEL,
    drug_id: str | None | object = _UPDATE_SENTINEL,
    source: str | None | object = _UPDATE_SENTINEL,
    error: str | None | object = _UPDATE_SENTINEL,
    details_json: dict[str, Any] | object = _UPDATE_SENTINEL,
) -> TrackingJob:
    await _ensure_tracking_jobs_table(db)

    values: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if status is not _UPDATE_SENTINEL:
        values["status"] = status
    if step is not _UPDATE_SENTINEL:
        values["step"] = step
    if progress is not _UPDATE_SENTINEL:
        values["progress"] = progress
    if resolved_generic_name is not _UPDATE_SENTINEL:
        values["resolved_generic_name"] = resolved_generic_name
    if drug_id is not _UPDATE_SENTINEL:
        values["drug_id"] = drug_id
    if source is not _UPDATE_SENTINEL:
        values["source"] = source
    if error is not _UPDATE_SENTINEL:
        values["error"] = error
    if details_json is not _UPDATE_SENTINEL:
        values["details_json"] = details_json

    await db.execute(
        update(TrackingJob)
        .where(TrackingJob.id == job_id)
        .values(**values)
    )
    return await _get_tracking_job_or_raise(db, job_id)


def _to_response(job: TrackingJob) -> TrackingJobResponse:
    return TrackingJobResponse(
        id=job.id,
        status=job.status,
        step=job.step,
        progress=int(job.progress),
        medication_name=job.medication_name,
        resolved_generic_name=job.resolved_generic_name,
        drug_id=job.drug_id,
        source=job.source,
        error=job.error,
        options_json=dict(job.options_json or {}),
        details_json=dict(job.details_json or {}),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def create_tracking_job(
    db: AsyncSession,
    *,
    medication_name: str,
    baseline_quarters: int,
    max_reports: int | None,
    prefer_cached: bool,
) -> TrackingJobResponse:
    await _ensure_tracking_jobs_table(db)
    job = TrackingJob(
        medication_name=medication_name.strip(),
        status="queued",
        step="queued",
        progress=0,
        resolved_generic_name=None,
        drug_id=None,
        source=None,
        error=None,
        options_json={
            "mode": "onboard",
            "baseline_quarters": baseline_quarters,
            "max_reports": max_reports,
            "prefer_cached": prefer_cached,
        },
        details_json={},
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    await db.commit()
    return _to_response(job)


async def create_full_history_rebuild_job(
    db: AsyncSession,
    *,
    drug_id: str,
    baseline_quarters: int,
    prefer_cached: bool,
) -> TrackingJobResponse:
    await _ensure_tracking_jobs_table(db)
    drug = await db.scalar(select(Drug).where(Drug.id == drug_id))
    if drug is None:
        raise AppError(error="NotFound", detail=f"drug_id '{drug_id}' not found", status_code=404)

    active_job = await db.scalar(
        _full_history_rebuild_job_query(drug_id=drug_id).where(TrackingJob.status.in_(_NON_TERMINAL_STATUSES))
    )
    if active_job is not None:
        return _to_response(active_job)

    job = TrackingJob(
        medication_name=drug.generic_name.strip(),
        status="queued",
        step="queued",
        progress=0,
        resolved_generic_name=drug.generic_name.strip(),
        drug_id=drug.id,
        source=None,
        error=None,
        options_json={
            "mode": "full_history_rebuild",
            "drug_id": drug.id,
            "baseline_quarters": baseline_quarters,
            "max_reports": None,
            "prefer_cached": prefer_cached,
        },
        details_json={},
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    await db.commit()
    return _to_response(job)


async def get_active_full_history_rebuild_job(
    db: AsyncSession,
    *,
    drug_id: str,
) -> TrackingJobResponse:
    await _ensure_tracking_jobs_table(db)
    job = await db.scalar(
        _full_history_rebuild_job_query(drug_id=drug_id).where(TrackingJob.status.in_(_NON_TERMINAL_STATUSES))
    )
    if job is None:
        raise AppError(error="NotFound", detail="No active full-history rebuild job for this drug.", status_code=404)
    return _to_response(job)


async def get_tracking_job(db: AsyncSession, *, job_id: UUID) -> TrackingJobResponse:
    job = await _get_tracking_job_or_raise(db, job_id)
    return _to_response(job)


async def recover_incomplete_tracking_jobs(db: AsyncSession) -> int:
    await _ensure_tracking_jobs_table(db)
    result = await db.execute(
        update(TrackingJob)
        .where(TrackingJob.status.in_(_NON_TERMINAL_STATUSES))
        .values(
            status="failed",
            step="failed",
            error=_RESTART_FAILURE_MESSAGE,
            updated_at=datetime.now(timezone.utc),
        )
        .returning(TrackingJob.id)
    )
    job_ids = result.scalars().all()
    return len(job_ids)


class TrackingJobRuntime:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        evermemos_client: EvermemosClient,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._evermemos_client = evermemos_client
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    async def startup(self) -> None:
        async with self._session_factory() as db:
            await recover_incomplete_tracking_jobs(db)
            await db.commit()

    async def shutdown(self) -> None:
        active_tasks = [task for task in self._tasks.values() if not task.done()]
        if not active_tasks:
            return
        for task in active_tasks:
            task.cancel()
        await asyncio.gather(*active_tasks, return_exceptions=True)

    def start_job(self, job_id: UUID) -> None:
        current = self._tasks.get(job_id)
        if current is not None and not current.done():
            return

        task = asyncio.create_task(self._run_job(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    async def _run_job(self, job_id: UUID) -> None:
        async def report_progress(
            step: str,
            progress: int,
            details: dict[str, Any] | None = None,
        ) -> None:
            async with self._session_factory() as progress_db:
                await _update_tracking_job(
                    progress_db,
                    job_id=job_id,
                    status=_status_for_step(step),
                    step=step,
                    progress=progress,
                    resolved_generic_name=(details or {}).get("resolved_generic_name", _UPDATE_SENTINEL),
                    drug_id=(details or {}).get("drug_id", _UPDATE_SENTINEL),
                    source=(details or {}).get("source", _UPDATE_SENTINEL),
                    error=(details or {}).get("error", _UPDATE_SENTINEL),
                    details_json=dict(details or {}),
                )
                await progress_db.commit()

        try:
            async with self._session_factory() as db:
                job = await _get_tracking_job_or_raise(db, job_id)
                options = dict(job.options_json or {})
                medication_name = job.medication_name
                mode = str(options.get("mode") or "onboard")
                await db.commit()

            await report_progress("queued", 0)

            async with self._session_factory() as db:
                response = await onboard_drug(
                    db,
                    settings=self._settings,
                    evermemos_client=self._evermemos_client,
                    medication_name=medication_name,
                    baseline_quarters=int(options.get("baseline_quarters", 4)),
                    max_reports=(
                        int(options["max_reports"])
                        if options.get("max_reports") is not None
                        else None
                    ),
                    prefer_cached=bool(options.get("prefer_cached", True)),
                    rebuild_existing=mode == "full_history_rebuild",
                    progress_callback=report_progress,
                )

            async with self._session_factory() as db:
                await _update_tracking_job(
                    db,
                    job_id=job_id,
                    status="ready",
                    step="ready",
                    progress=100,
                    resolved_generic_name=response.generic_name,
                    drug_id=response.drug_id,
                    source=response.source,
                    error=None,
                    details_json={
                        "reports_loaded": response.reports_loaded,
                        "baseline_quarters_loaded": list(response.baseline_quarters_loaded),
                        "next_quarter": response.next_quarter,
                        "message": response.message,
                    },
                )
                await db.commit()
        except asyncio.CancelledError:
            raise
        except AppError as exc:
            await self._fail_job(job_id, _job_error_message(exc))
        except Exception as exc:
            await self._fail_job(job_id, _job_error_message(exc))

    async def _fail_job(self, job_id: UUID, message: str) -> None:
        async with self._session_factory() as db:
            await _update_tracking_job(
                db,
                job_id=job_id,
                status="failed",
                step="failed",
                error=message,
            )
            await db.commit()
