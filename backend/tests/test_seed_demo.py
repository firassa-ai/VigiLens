from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_seed_demo_requires_demo_mode(
    postgres_urls,
    reset_database,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=False,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": "Forbidden",
        "detail": "/api/v1/admin/seed-demo is only available when DEMO_MODE=true",
        "status_code": 403,
    }


@pytest.mark.asyncio
async def test_seed_demo_loads_data_and_is_idempotent(
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

    payload = {
        "drug_ids": ["semaglutide", "metformin"],
        "preload_quarters": ["2018-Q4", "2018-Q2", "2018-Q1", "2018-Q3", "2018-Q3"],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.post("/api/v1/admin/seed-demo", json=payload)
        second = await client.post("/api/v1/admin/seed-demo", json=payload)

    assert first.status_code == 200
    first_body = first.json()
    assert first_body["seeded_drugs"] == ["semaglutide", "metformin"]
    assert first_body["preload_quarters"] == ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"]
    assert first_body["reports_by_drug"]["metformin"] == 23
    assert first_body["reports_by_drug"]["semaglutide"] >= 200
    assert first_body["reports_loaded"] == (
        first_body["reports_by_drug"]["semaglutide"] + first_body["reports_by_drug"]["metformin"]
    )

    assert second.status_code == 200
    assert second.json()["reports_loaded"] == first_body["reports_loaded"]

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM faers_reports;")
            assert cur.fetchone()[0] == first_body["reports_loaded"]

            cur.execute("SELECT COUNT(*) FROM quarterly_stats;")
            assert cur.fetchone()[0] == 120

            cur.execute("SELECT COUNT(*) FROM faers_background_counts;")
            assert cur.fetchone()[0] >= 264

            cur.execute(
                "SELECT version, receivedate::text FROM faers_reports WHERE safetyreportid = 'S-1002';"
            )
            version, receivedate = cur.fetchone()
            assert version == 2
            assert receivedate == "2018-03-05"

            cur.execute(
                "SELECT quarters_loaded, next_quarter, evermemos_status FROM ingestion_state WHERE drug_id = 'semaglutide';"
            )
            quarters_loaded, next_quarter, evermemos_status = cur.fetchone()
            assert quarters_loaded == ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"]
            assert next_quarter == "2019-Q1"
            assert evermemos_status == "ready"


@pytest.mark.asyncio
async def test_seed_demo_writes_report_level_event_logs(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )
    app = create_app(settings)
    captured: list[dict[str, object]] = []

    async def _ok(*args, **kwargs):
        return True

    async def _capture_event_log(*args, **kwargs):
        captured.append(kwargs.get("event_log_data", {}))
        return True

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok)
    monkeypatch.setattr(app.state.evermemos_client, "store_foresight_memory", _ok)
    monkeypatch.setattr(app.state.evermemos_client, "store_event_log_memory", _capture_event_log)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1"],
            },
        )

    assert response.status_code == 200
    assert captured
    semaglutide_q1 = next(
        (item for item in captured if item.get("report_id") == "S-1001"),
        None,
    )
    assert semaglutide_q1 is not None
    assert semaglutide_q1["quarter"] == "2018-Q1"
    assert semaglutide_q1["evidence_api_path"] == "/api/v1/evidence/S-1001"
    assert semaglutide_q1["report_id"] == "S-1001"


@pytest.mark.asyncio
async def test_seed_demo_repairs_null_drug_id_mappings_on_reseed(
    postgres_urls,
    reset_database,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "real",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )
    app = create_app(settings)

    payload = {
        "drug_ids": ["semaglutide", "metformin"],
        "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.post("/api/v1/admin/seed-demo", json=payload)
        assert first.status_code == 200

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE faers_report_drugs
                SET drug_id = NULL
                WHERE safetyreportid = '14367880' AND drug_name = 'SEMAGLUTIDE' AND role = 'suspect';
                """
            )
            conn.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        second = await client.post("/api/v1/admin/seed-demo", json=payload)
        assert second.status_code == 200
        status = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
        assert status.status_code == 200

    assert status.json()["quarters_loaded"] == payload["preload_quarters"]

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT drug_id
                FROM faers_report_drugs
                WHERE safetyreportid = '14367880' AND drug_name = 'SEMAGLUTIDE' AND role = 'suspect';
                """
            )
            repaired = {row[0] for row in cur.fetchall()}
            assert repaired == {"semaglutide"}


@pytest.mark.asyncio
async def test_seed_demo_recreates_missing_belief_unique_index(
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

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS uq_beliefs_drug_question_quarter;")
            conn.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )

    assert response.status_code == 200

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'beliefs' AND indexname = 'uq_beliefs_drug_question_quarter';
                """
            )
            assert cur.fetchone() == ("uq_beliefs_drug_question_quarter",)


@pytest.mark.asyncio
async def test_seed_demo_rejects_unknown_drug(
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
        response = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["unknown-drug"],
                "preload_quarters": ["2018-Q1"],
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "BadRequest"
    assert "unknown-drug" in response.json()["detail"]


@pytest.mark.asyncio
async def test_seed_demo_accepts_custom_data_dir(
    postgres_urls,
    reset_database,
    tmp_path,
) -> None:
    data_dir = tmp_path / "real_sample"
    data_dir.mkdir(parents=True, exist_ok=True)

    (data_dir / "semaglutide.ndjson").write_text(
        (
            '{"safetyreportid":"RS-1","version":1,"receivedate":"2018-01-10",'
            '"patient_sex":"female","patient_age":45,"serious":false,"outcomes":[],'
            '"reactions":["Nausea"],"drugs":[{"drug_id":"semaglutide","drug_name":"Semaglutide","role":"suspect"}]}\n'
        ),
        encoding="utf-8",
    )
    (data_dir / "metformin.ndjson").write_text(
        (
            '{"safetyreportid":"RM-1","version":1,"receivedate":"2018-01-12",'
            '"patient_sex":"male","patient_age":54,"serious":false,"outcomes":[],'
            '"reactions":["Diarrhea"],"drugs":[{"drug_id":"metformin","drug_name":"Metformin","role":"suspect"}]}\n'
        ),
        encoding="utf-8",
    )

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
        response = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1"],
                "data_dir": str(data_dir),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["reports_loaded"] == 2
    assert body["reports_by_drug"] == {"semaglutide": 1, "metformin": 1}


@pytest.mark.asyncio
async def test_seed_demo_disables_live_openfda_background_fetch(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    settings = Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "real",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
        openfda_live_background=True,
    )
    app = create_app(settings)

    async def _fail_fetch(*args, **kwargs):
        raise AssertionError("seed-demo should not call live openFDA background fetches")

    monkeypatch.setattr(
        "app.services.openfda_background_service._fetch_total",
        _fail_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["minoxidil"],
                "preload_quarters": ["2018-Q1"],
            },
        )

    assert response.status_code == 200
    assert response.json()["seeded_drugs"] == ["minoxidil"]

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM faers_background_counts WHERE source = 'openfda_live';")
            assert cur.fetchone()[0] == 0
