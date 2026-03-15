from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.services.drug_catalog_service import DailyMedLabel
from app.services.onboarding_service import ResolvedDrugIdentity


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_catalog_search_merges_local_hits_with_dailymed(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _fake_dailymed(*, settings, query):
        assert query == "wegovy"
        return [
            DailyMedLabel(
                generic_name="semaglutide",
                brand_names=["Wegovy"],
                setid="wegovy-label",
                title="WEGOVY (SEMAGLUTIDE) INJECTION, SOLUTION [NOVO NORDISK]",
                published_date="Mar 05, 2026",
            )
        ]

    monkeypatch.setattr("app.services.drug_catalog_service._search_dailymed_labels", _fake_dailymed)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        response = await client.get("/api/v1/catalog/search", params={"q": "wegovy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["generic_name"] == "semaglutide"
    assert payload[0]["tracked"] is True
    assert payload[0]["tracked_drug_id"] == "semaglutide"
    assert payload[0]["label_available"] is True
    assert payload[0]["sources"] == ["tracked", "faers", "dailymed"]


@pytest.mark.asyncio
async def test_catalog_preview_returns_label_metadata_and_faers_status(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _fake_dailymed(*, settings, query):
        assert query == "clozapine"
        return [
            DailyMedLabel(
                generic_name="clozapine",
                brand_names=["Clozaril"],
                setid="clozapine-label",
                title="CLOZARIL (CLOZAPINE) TABLET [HLS THERAPEUTICS]",
                published_date="Jun 30, 2025",
            )
        ]

    async def _fake_preview_identity(*, settings, name):
        assert name == "clozapine"
        return ResolvedDrugIdentity(
            drug_id="clozapine",
            generic_name="clozapine",
            brand_names=["Clozaril"],
            aliases={"clozapine", "clozaril"},
            existing_drug=None,
        )

    async def _fake_estimate_count(*, settings, name, identity):
        assert name == "clozapine"
        assert identity.generic_name == "clozapine"
        return 1842

    monkeypatch.setattr("app.services.drug_catalog_service._search_dailymed_labels", _fake_dailymed)
    monkeypatch.setattr("app.services.drug_catalog_service._preview_faers_identity", _fake_preview_identity)
    monkeypatch.setattr("app.services.drug_catalog_service._estimate_faers_report_count", _fake_estimate_count)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalog/preview", params={"name": "clozapine"})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "generic_name": "clozapine",
        "brand_names": ["Clozaril"],
        "tracked": False,
        "tracked_drug_id": None,
        "dailymed_setid": "clozapine-label",
        "dailymed_title": "CLOZARIL (CLOZAPINE) TABLET [HLS THERAPEUTICS]",
        "dailymed_published_date": "Jun 30, 2025",
        "faers_available": True,
        "faers_report_count": 1842,
        "faers_report_count_is_estimate": True,
    }


@pytest.mark.asyncio
async def test_catalog_search_degrades_to_local_hits_when_dailymed_unavailable(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _failing_dailymed(*, settings, query):
        raise RuntimeError("DailyMed unavailable")

    monkeypatch.setattr("app.services.drug_catalog_service._search_dailymed_labels", _failing_dailymed)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        response = await client.get("/api/v1/catalog/search", params={"q": "semag"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["generic_name"] == "semaglutide"
    assert payload[0]["tracked"] is True
    assert payload[0]["label_available"] is False
    assert payload[0]["sources"] == ["tracked", "faers"]


@pytest.mark.asyncio
async def test_catalog_preview_degrades_when_faers_probe_fails(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _fake_dailymed(*, settings, query):
        assert query == "clozapine"
        return [
            DailyMedLabel(
                generic_name="clozapine",
                brand_names=["Clozaril"],
                setid="clozapine-label",
                title="CLOZARIL (CLOZAPINE) TABLET [HLS THERAPEUTICS]",
                published_date="Jun 30, 2025",
            )
        ]

    async def _failing_preview_identity(*, settings, name):
        assert name == "clozapine"
        raise RuntimeError("FAERS unavailable")

    monkeypatch.setattr("app.services.drug_catalog_service._search_dailymed_labels", _fake_dailymed)
    monkeypatch.setattr("app.services.drug_catalog_service._preview_faers_identity", _failing_preview_identity)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/catalog/preview", params={"name": "clozapine"})

    assert response.status_code == 200
    assert response.json() == {
        "generic_name": "clozapine",
        "brand_names": ["Clozaril"],
        "tracked": False,
        "tracked_drug_id": None,
        "dailymed_setid": "clozapine-label",
        "dailymed_title": "CLOZARIL (CLOZAPINE) TABLET [HLS THERAPEUTICS]",
        "dailymed_published_date": "Jun 30, 2025",
        "faers_available": False,
        "faers_report_count": None,
        "faers_report_count_is_estimate": False,
    }


@pytest.mark.asyncio
async def test_catalog_preview_returns_exact_local_count_for_tracked_drug(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _fake_dailymed(*, settings, query):
        assert query == "semaglutide"
        return []

    monkeypatch.setattr("app.services.drug_catalog_service._search_dailymed_labels", _fake_dailymed)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        response = await client.get("/api/v1/catalog/preview", params={"name": "semaglutide"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["tracked"] is True
    assert payload["tracked_drug_id"] == "semaglutide"
    assert payload["faers_available"] is True
    assert payload["faers_report_count"] > 0
    assert payload["faers_report_count_is_estimate"] is False
