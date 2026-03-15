from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_get_evidence_returns_expected_shape(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        response = await client.get("/api/v1/evidence/S-1001")
        assert response.status_code == 200

        payload = response.json()
        assert payload["safetyreportid"] == "S-1001"
        assert payload["version"] == 1
        assert payload["patient_sex"] == "female"
        assert payload["serious"] is False
        assert "Semaglutide" in payload["suspect_drugs"]
        assert "Metformin" in payload["concomitant_drugs"]
        assert "Nausea" in payload["reactions"]
        assert payload["evidence_api_path"] == "/api/v1/evidence/S-1001"
        assert payload["eventlog_memory_id"] == "vigl_semaglutide_S-1001_eventlog"


@pytest.mark.asyncio
async def test_get_evidence_not_found_returns_error(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evidence/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": "NotFound",
        "detail": "report_id 'does-not-exist' not found",
        "status_code": 404,
    }
