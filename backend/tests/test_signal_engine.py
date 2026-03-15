from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.services.signal_engine import classify_trajectory, compute_disproportionality_metrics


def test_compute_disproportionality_metrics_expected_values() -> None:
    metrics = compute_disproportionality_metrics(a=10, b=20, c=30, d=40)

    assert metrics.ror == pytest.approx(0.6666666667, rel=1e-6)
    assert metrics.ror_ci_lower == pytest.approx(0.2725103678, rel=1e-6)
    assert metrics.ror_ci_upper == pytest.approx(1.6309267352, rel=1e-6)
    assert metrics.prr == pytest.approx(0.7777777778, rel=1e-6)
    assert metrics.chi_squared == pytest.approx(0.7936507937, rel=1e-6)
    assert metrics.signal_detected is False


def test_compute_disproportionality_metrics_zero_cell_guards() -> None:
    metrics = compute_disproportionality_metrics(a=4, b=0, c=7, d=11)

    assert metrics.ror is None
    assert metrics.ror_ci_lower is None
    assert metrics.ror_ci_upper is None
    assert metrics.signal_detected is False


def test_classify_trajectory_cases() -> None:
    assert (
        classify_trajectory([None, 1.1, 1.2], [False, False, False])
        == "insufficient_data"
    )

    assert (
        classify_trajectory([1.0, 1.2, 1.5, 1.9], [False, False, True, True])
        == "emerging"
    )

    assert (
        classify_trajectory([1.1, 1.3, 1.8, 2.6], [True, True, True, True])
        == "accelerating"
    )

    assert (
        classify_trajectory([2.8, 2.4, 2.0, 1.7], [False, False, False, False])
        == "declining"
    )


@pytest.mark.asyncio
async def test_timeline_endpoint_filters_and_returns_expected_points(
    postgres_urls,
    reset_database,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        seed_resp = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed_resp.status_code == 200

        response = await client.get(
            "/api/v1/drugs/semaglutide/timeline",
            params={"events": "Diarrhea", "quarters": "2018-Q2,2018-Q4"},
        )

    assert response.status_code == 200
    points = response.json()
    assert [point["quarter"] for point in points] == ["2018-Q2", "2018-Q4"]
    assert [point["adverse_event"] for point in points] == ["Diarrhea", "Diarrhea"]

    q2, q4 = points
    assert q2["report_count"] == 1
    assert q2["cumulative_count"] == 1
    assert q2["signal_detected"] is False

    assert q4["report_count"] == 0
    assert q4["cumulative_count"] == 1
    assert q4["ror"] is not None
    assert q4["ror"] > 0
    assert q4["signal_detected"] is False


@pytest.mark.asyncio
async def test_timeline_endpoint_rejects_unknown_drug(
    postgres_urls,
    reset_database,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/drugs/unknown/timeline")

    assert response.status_code == 400
    assert response.json() == {
        "error": "BadRequest",
        "detail": "drug_id 'unknown' not found",
        "status_code": 400,
    }


@pytest.mark.asyncio
async def test_recompute_uses_cached_openfda_background_counts(
    postgres_urls,
    reset_database,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
        openfda_live_background=False,
    )
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        seed_resp = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3"],
            },
        )
        assert seed_resp.status_code == 200

        with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO faers_background_counts
                      (quarter, adverse_event, all_total_cumulative, all_event_cumulative, source)
                    VALUES
                      ('2018-Q4', '__ALL__', 1500000, 1500000, 'test'),
                      ('2018-Q4', 'Nausea', 1500000, 50000, 'test')
                    ON CONFLICT (quarter, adverse_event) DO UPDATE
                    SET all_total_cumulative = EXCLUDED.all_total_cumulative,
                        all_event_cumulative = EXCLUDED.all_event_cumulative,
                        source = EXCLUDED.source;
                    """
                )

        ingest_resp = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
        assert ingest_resp.status_code == 200

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT all_total_cumulative, all_event_cumulative
                FROM quarterly_stats
                WHERE drug_id='semaglutide'
                  AND quarter='2018-Q4'
                  AND adverse_event='Nausea'
                """
            )
            row = cur.fetchone()

    assert row == (1500000, 50000)


@pytest.mark.asyncio
async def test_recompute_marks_metrics_insufficient_when_background_missing(
    postgres_urls,
    reset_database,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
        openfda_live_background=False,
    )
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        seed_resp = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3"],
            },
        )
        assert seed_resp.status_code == 200

        with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM faers_background_counts WHERE quarter='2018-Q4';")

        ingest_resp = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
        assert ingest_resp.status_code == 200

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ror, ror_ci_lower, ror_ci_upper, prr, chi_squared, signal_detected
                FROM quarterly_stats
                WHERE drug_id='semaglutide'
                  AND quarter='2018-Q4'
                  AND adverse_event='Nausea'
                """
            )
            row = cur.fetchone()

    assert row == (None, None, None, None, None, False)
