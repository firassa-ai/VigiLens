from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.services.demo_seed import SeedDrugRow, SeedReportRow
from app.services.onboarding_service import LiveIdentityProbeResult, ResolvedDrugIdentity


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


def _fake_openfda_rows(drug_id: str) -> list[tuple[SeedReportRow, dict]]:
    rows: list[tuple[SeedReportRow, dict]] = []
    quarter_months = ["01", "04", "07", "10", "11"]
    for index, month in enumerate(quarter_months, start=1):
        report = SeedReportRow(
            safetyreportid=f"C-{index:04d}",
            version=1,
            receivedate=f"2018-{month}-15",
            patient_sex="unknown",
            patient_age=55 + index,
            reactions=["Constipation", "Nausea"] if index % 2 else ["Vomiting"],
            drugs=[SeedDrugRow(drug_id=drug_id, drug_name=drug_id, role="suspect")],
            serious=index % 2 == 0,
            outcomes=[],
            is_duplicate=False,
        )
        rows.append((report, report.model_dump(mode="json")))
    return rows


def _reset_db(postgres_urls) -> None:
    init_sql_path = Path(__file__).resolve().parents[1] / "sql" / "init.sql"
    init_sql = init_sql_path.read_text(encoding="utf-8")
    with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER;")
            cur.execute(init_sql)


def _fake_probe_result(
    *,
    drug_id: str,
    generic_name: str | None = None,
    strategy: str = "generic",
) -> LiveIdentityProbeResult:
    resolved_generic = generic_name or drug_id
    return LiveIdentityProbeResult(
        identity=ResolvedDrugIdentity(
            drug_id=drug_id,
            generic_name=resolved_generic,
            brand_names=[],
            aliases={resolved_generic},
        ),
        rows=_fake_openfda_rows(drug_id),
        strategy=strategy,
    )


def _stub_downstream_pipeline(monkeypatch) -> None:
    async def _noop(*args, **kwargs):
        return []

    async def _noop_none(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.onboarding_service.recompute_signals_after_ingestion",
        _noop,
    )
    monkeypatch.setattr(
        "app.services.onboarding_service.maybe_generate_predictions",
        _noop_none,
    )
    monkeypatch.setattr(
        "app.services.onboarding_service.generate_tracked_beliefs_for_quarter",
        _noop_none,
    )
    monkeypatch.setattr(
        "app.services.onboarding_service.sync_seed_memories",
        _noop_none,
    )


@pytest.mark.asyncio
async def test_tracking_onboard_creates_new_drug_and_baseline(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    _stub_downstream_pipeline(monkeypatch)

    async def _fake_probe_live_identity(*, settings, medication_name, max_reports):
        assert medication_name == "clozapine"
        return _fake_probe_result(drug_id="clozapine")

    monkeypatch.setattr(
        "app.services.onboarding_service._probe_live_identity",
        _fake_probe_live_identity,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/tracking/onboard",
            json={
                "medication_name": "clozapine",
                "baseline_quarters": 4,
                "max_reports": 500,
                "prefer_cached": False,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["drug_id"] == "clozapine"
        assert payload["generic_name"] == "clozapine"
        assert payload["reports_loaded"] >= 4
        assert len(payload["baseline_quarters_loaded"]) == 4

        drugs = await client.get("/api/v1/drugs")
        assert drugs.status_code == 200
        ids = {item["id"] for item in drugs.json()}
        assert "clozapine" in ids

        status = await client.get("/api/v1/ingest/status", params={"drug_id": "clozapine"})
        assert status.status_code == 200
        status_payload = status.json()
        assert len(status_payload["quarters_loaded"]) == 4


@pytest.mark.asyncio
async def test_tracking_onboard_brand_alias_ozempic_resolves_to_semaglutide(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    _stub_downstream_pipeline(monkeypatch)

    async def _fail_live_fetch(*args, **kwargs):
        raise AssertionError("packaged semaglutide replay should avoid live fetch")

    monkeypatch.setattr(
        "app.services.onboarding_service._fetch_live_rows_for_identity",
        _fail_live_fetch,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/tracking/onboard",
            json={
                "medication_name": "Ozempic",
                "baseline_quarters": 4,
                "max_reports": 500,
                "prefer_cached": False,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["drug_id"] == "semaglutide"
    assert payload["generic_name"] == "semaglutide"


@pytest.mark.asyncio
async def test_tracking_onboard_brand_alias_wegovy_resolves_to_semaglutide(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    _stub_downstream_pipeline(monkeypatch)

    async def _fail_live_fetch(*args, **kwargs):
        raise AssertionError("packaged semaglutide replay should avoid live fetch")

    monkeypatch.setattr(
        "app.services.onboarding_service._fetch_live_rows_for_identity",
        _fail_live_fetch,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/tracking/onboard",
            json={
                "medication_name": "Wegovy",
                "baseline_quarters": 4,
                "max_reports": 500,
                "prefer_cached": False,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["drug_id"] == "semaglutide"
    assert payload["generic_name"] == "semaglutide"


@pytest.mark.asyncio
async def test_tracking_onboard_cache_replay_preserves_canonical_identity(
    postgres_urls,
    reset_database,
    monkeypatch,
    tmp_path,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def _temp_cache_file(drug_id: str) -> Path:
        return cache_dir / f"{drug_id}.ndjson"

    def _no_packaged_seed_files(_drug_id: str) -> list[Path]:
        return []

    async def _fake_probe_live_identity(*, settings, medication_name, max_reports):
        assert medication_name == "clozapine"
        return _fake_probe_result(drug_id="clozapine")

    monkeypatch.setattr(
        "app.services.onboarding_service._cache_file_for_drug",
        _temp_cache_file,
    )
    monkeypatch.setattr(
        "app.services.onboarding_service._packaged_seed_files_for_drug",
        _no_packaged_seed_files,
    )

    first_app = create_app(_build_settings(postgres_urls))
    _stub_downstream_pipeline(monkeypatch)
    monkeypatch.setattr(
        "app.services.onboarding_service._probe_live_identity",
        _fake_probe_live_identity,
    )

    async with AsyncClient(transport=ASGITransport(app=first_app), base_url="http://test") as client:
        first_response = await client.post(
            "/api/v1/tracking/onboard",
            json={
                "medication_name": "clozapine",
                "baseline_quarters": 4,
                "max_reports": 500,
                "prefer_cached": False,
            },
        )

    assert first_response.status_code == 200
    assert _temp_cache_file("clozapine").exists()

    _reset_db(postgres_urls)

    second_app = create_app(_build_settings(postgres_urls))

    async def _should_not_probe(*args, **kwargs):
        raise AssertionError("cache replay should not call the live probe")

    monkeypatch.setattr(
        "app.services.onboarding_service._probe_live_identity",
        _should_not_probe,
    )

    async with AsyncClient(transport=ASGITransport(app=second_app), base_url="http://test") as client:
        second_response = await client.post(
            "/api/v1/tracking/onboard",
            json={
                "medication_name": "clozapine",
                "baseline_quarters": 4,
                "max_reports": 500,
                "prefer_cached": True,
            },
        )

    assert second_response.status_code == 200
    payload = second_response.json()
    assert payload["source"] == "cache"
    assert payload["drug_id"] == "clozapine"
    assert payload["generic_name"] == "clozapine"
