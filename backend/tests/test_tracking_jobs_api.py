from __future__ import annotations

import asyncio
from pathlib import Path
import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import TrackingJob
from app.db.session import get_session_factory
from app.main import create_app
from app.schemas.tracking import OnboardDrugResponse
from app.services.tracking_job_service import recover_incomplete_tracking_jobs


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


async def _poll_job(client: AsyncClient, job_id: str, *, timeout_seconds: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict | None = None
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/tracking/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"ready", "failed"}:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError(f"Tracking job did not finish in time. Last payload: {last_payload}")


@pytest.mark.asyncio
async def test_tracking_job_runs_to_ready(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _fake_onboard(
        db,
        *,
        settings,
        evermemos_client,
        medication_name,
        baseline_quarters,
        max_reports,
        prefer_cached,
        rebuild_existing=False,
        progress_callback=None,
    ):
        assert medication_name == "clozapine"
        assert baseline_quarters == 4
        assert max_reports == 1500
        assert prefer_cached is True
        assert rebuild_existing is False
        if progress_callback is not None:
            await progress_callback("resolving_identity", 10, None)
            await progress_callback("fetching_faers", 35, None)
            await progress_callback(
                "deduping_transforming",
                55,
                {
                    "resolved_generic_name": "clozapine",
                    "drug_id": "clozapine",
                    "source": "openfda",
                },
            )
            await progress_callback(
                "writing_memory",
                95,
                {
                    "resolved_generic_name": "clozapine",
                    "drug_id": "clozapine",
                    "source": "openfda",
                },
            )
        return OnboardDrugResponse(
            drug_id="clozapine",
            generic_name="clozapine",
            source="openfda",
            created=True,
            reports_loaded=500,
            baseline_quarters_loaded=["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            next_quarter="2019-Q1",
            message="ready",
        )

    monkeypatch.setattr("app.services.tracking_job_service.onboard_drug", _fake_onboard)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/tracking/jobs",
            json={
                "medication_name": "clozapine",
                "baseline_quarters": 4,
                "max_reports": 1500,
                "prefer_cached": True,
            },
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["status"] == "queued"
        assert payload["step"] == "queued"
        assert payload["progress"] == 0

        job = await _poll_job(client, payload["id"])

    assert job["status"] == "ready"
    assert job["step"] == "ready"
    assert job["progress"] == 100
    assert job["resolved_generic_name"] == "clozapine"
    assert job["drug_id"] == "clozapine"
    assert job["source"] == "openfda"
    assert job["error"] is None


@pytest.mark.asyncio
async def test_tracking_job_persists_failure_reason(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _failing_onboard(*args, **kwargs):
        raise AppError(error="BadRequest", detail="No FAERS reports found for medication 'unknown-drug'", status_code=400)

    monkeypatch.setattr("app.services.tracking_job_service.onboard_drug", _failing_onboard)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/tracking/jobs",
            json={
                "medication_name": "unknown-drug",
                "baseline_quarters": 4,
                "max_reports": 500,
                "prefer_cached": False,
            },
        )
        assert created.status_code == 200
        job = await _poll_job(client, created.json()["id"])

    assert job["status"] == "failed"
    assert job["step"] == "failed"
    assert "No FAERS reports found" in job["error"]


@pytest.mark.asyncio
async def test_tracking_job_maps_timeout_to_friendly_error(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _timeout_onboard(*args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr("app.services.tracking_job_service.onboard_drug", _timeout_onboard)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/tracking/jobs",
            json={
                "medication_name": "minoxidil",
                "baseline_quarters": 4,
                "max_reports": 1500,
                "prefer_cached": False,
            },
        )
        assert created.status_code == 200
        job = await _poll_job(client, created.json()["id"])

    assert job["status"] == "failed"
    assert job["step"] == "failed"
    assert job["error"] == "openFDA timed out while fetching FAERS history. Retry the rebuild in a minute."


@pytest.mark.asyncio
async def test_full_history_rebuild_job_uses_existing_drug_and_unbounded_fetch(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _fake_onboard(
        db,
        *,
        settings,
        evermemos_client,
        medication_name,
        baseline_quarters,
        max_reports,
        prefer_cached,
        rebuild_existing=False,
        progress_callback=None,
    ):
        assert medication_name == "semaglutide"
        assert baseline_quarters == 4
        assert max_reports is None
        assert prefer_cached is False
        assert rebuild_existing is True
        if progress_callback is not None:
            await progress_callback(
                "deduping_transforming",
                55,
                {
                    "resolved_generic_name": "semaglutide",
                    "drug_id": "semaglutide",
                    "source": "openfda",
                },
            )
        return OnboardDrugResponse(
            drug_id="semaglutide",
            generic_name="semaglutide",
            source="openfda",
            created=False,
            reports_loaded=72000,
            baseline_quarters_loaded=["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            next_quarter="2019-Q1",
            message="rebuild-ready",
        )

    monkeypatch.setattr("app.services.tracking_job_service.onboard_drug", _fake_onboard)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        created = await client.post(
            "/api/v1/drugs/semaglutide/rebuild-full-history",
            json={
                "baseline_quarters": 4,
                "prefer_cached": False,
            },
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["status"] == "queued"
        assert payload["options_json"]["mode"] == "full_history_rebuild"
        assert payload["options_json"]["max_reports"] is None

        job = await _poll_job(client, payload["id"])

    assert job["status"] == "ready"
    assert job["resolved_generic_name"] == "semaglutide"
    assert job["drug_id"] == "semaglutide"


@pytest.mark.asyncio
async def test_full_history_rebuild_job_reuses_existing_active_job(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    session_factory = get_session_factory()
    existing_job_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

    async with session_factory() as db:
        db.add(
            TrackingJob(
                id=existing_job_id,
                status="running",
                step="fetching_faers",
                progress=42,
                medication_name="semaglutide",
                resolved_generic_name="semaglutide",
                drug_id="semaglutide",
                source=None,
                error=None,
                options_json={
                    "mode": "full_history_rebuild",
                    "drug_id": "semaglutide",
                    "baseline_quarters": 4,
                    "max_reports": None,
                    "prefer_cached": False,
                },
                details_json={"status_message": "Fetching month 31/72"},
            )
        )
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/drugs/semaglutide/rebuild-full-history",
            json={
                "baseline_quarters": 4,
                "prefer_cached": False,
            },
        )

    assert created.status_code == 200
    payload = created.json()
    assert payload["id"] == str(existing_job_id)
    assert payload["status"] == "running"
    assert payload["progress"] == 42

    async with session_factory() as db:
        jobs = (
            await db.execute(
                select(TrackingJob).where(
                    TrackingJob.drug_id == "semaglutide",
                    TrackingJob.options_json["mode"].astext == "full_history_rebuild",
                )
            )
        ).scalars().all()

    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_get_active_full_history_rebuild_job_for_drug(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    session_factory = get_session_factory()
    active_job_id = uuid4()
    older_failed_job_id = uuid4()

    async with session_factory() as db:
        db.add(
            TrackingJob(
                id=older_failed_job_id,
                status="failed",
                step="failed",
                progress=12,
                medication_name="minoxidil",
                resolved_generic_name="minoxidil",
                drug_id="minoxidil",
                source=None,
                error="Tracking job failed.",
                options_json={
                    "mode": "full_history_rebuild",
                    "drug_id": "minoxidil",
                    "baseline_quarters": 4,
                    "max_reports": None,
                    "prefer_cached": False,
                },
                details_json={},
            )
        )
        db.add(
            TrackingJob(
                id=active_job_id,
                status="running",
                step="fetching_faers",
                progress=44,
                medication_name="minoxidil",
                resolved_generic_name="minoxidil",
                drug_id="minoxidil",
                source=None,
                error=None,
                options_json={
                    "mode": "full_history_rebuild",
                    "drug_id": "minoxidil",
                    "baseline_quarters": 4,
                    "max_reports": None,
                    "prefer_cached": False,
                },
                details_json={"status_message": "Fetching month 32/72"},
            )
        )
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/drugs/minoxidil/rebuild-full-history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(active_job_id)
    assert payload["status"] == "running"
    assert payload["step"] == "fetching_faers"
    assert payload["details_json"]["status_message"] == "Fetching month 32/72"


@pytest.mark.asyncio
async def test_get_tracking_job_exposes_live_fetch_details(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    session_factory = get_session_factory()
    job_id = uuid4()

    async with session_factory() as db:
        db.add(
            TrackingJob(
                id=job_id,
                status="running",
                step="fetching_faers",
                progress=41,
                medication_name="semaglutide",
                resolved_generic_name="semaglutide",
                drug_id="semaglutide",
                source=None,
                error=None,
                options_json={
                    "mode": "full_history_rebuild",
                    "drug_id": "semaglutide",
                    "baseline_quarters": 4,
                    "max_reports": None,
                    "prefer_cached": False,
                },
                details_json={
                    "window_index": 31,
                    "window_total": 72,
                    "window_label": "2020-07",
                    "pages_fetched": 2,
                    "matched_reports": 1740,
                    "provider_rows_seen": 2000,
                    "status_message": "Fetching month 31/72 (2020-07), page 2; 1740 matched reports so far",
                },
            )
        )
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        inflight = await client.get(f"/api/v1/tracking/jobs/{job_id}")
        assert inflight.status_code == 200
        inflight_payload = inflight.json()
        assert inflight_payload["step"] == "fetching_faers"
        assert inflight_payload["progress"] == 41
        assert inflight_payload["details_json"]["window_index"] == 31
        assert inflight_payload["details_json"]["window_total"] == 72
        assert inflight_payload["details_json"]["pages_fetched"] == 2
        assert inflight_payload["details_json"]["matched_reports"] == 1740


@pytest.mark.asyncio
async def test_recover_incomplete_tracking_jobs_marks_stale_rows_failed(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    session_factory = get_session_factory()

    async with session_factory() as db:
        db.add(
            TrackingJob(
                id=uuid4(),
                status="running",
                step="fetching_faers",
                progress=35,
                medication_name="clozapine",
                options_json={"baseline_quarters": 4, "max_reports": 500, "prefer_cached": True},
            )
        )
        await db.commit()

    async with session_factory() as db:
        updated = await recover_incomplete_tracking_jobs(db)
        await db.commit()
        job = await db.scalar(
            select(TrackingJob).where(TrackingJob.medication_name == "clozapine")
        )

    assert updated == 1
    assert job is not None
    assert job.status == "failed"
    assert job.step == "failed"
    assert job.error == "Server restarted during tracking job. Start monitoring again."


@pytest.mark.asyncio
async def test_get_tracking_job_returns_404_for_unknown_job(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/tracking/jobs/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Tracking job was not found."
