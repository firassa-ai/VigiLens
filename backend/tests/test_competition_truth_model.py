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
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "real",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
        gemini_grounding_scorecard_verify=False,
        gemini_prediction_proof_verify=False,
        openfda_live_background=False,
    )


def _quarters_2018_q1_to_2023_q4() -> list[str]:
    quarters: list[str] = []
    for year in range(2018, 2024):
        for quarter in range(1, 5):
            quarters.append(f"{year}-Q{quarter}")
    return quarters


@pytest.mark.asyncio
async def test_minoxidil_routes_public_forecasts_to_proof_track_and_keeps_scorecard_receipt_only(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed_semaglutide = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
                "data_dir": str(Path(__file__).resolve().parents[2] / "data" / "real"),
            },
        )
        assert seed_semaglutide.status_code == 200

        seed_minoxidil = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["minoxidil"],
                "preload_quarters": _quarters_2018_q1_to_2023_q4(),
                "data_dir": str(Path(__file__).resolve().parents[2] / "data" / "real"),
            },
        )
        assert seed_minoxidil.status_code == 200

        casefile = await client.get("/api/v1/drugs/minoxidil/casefile-summary")
        assert casefile.status_code == 200
        casefile_payload = casefile.json()

        scorecard = await client.get("/api/v1/drugs/minoxidil/scorecard")
        assert scorecard.status_code == 200
        scorecard_payload = scorecard.json()

    public_forecasts = casefile_payload["public_forecasts"]
    assert public_forecasts
    assert casefile_payload["validated_receipts"] == 0
    assert casefile_payload["pending_receipts"] == 0
    assert casefile_payload["proof_backed_signals"] == len(public_forecasts)
    assert all(row["track"] == "proof" for row in public_forecasts)
    adverse_events = {row["adverse_event"] for row in public_forecasts}
    assert "Alopecia" not in adverse_events
    assert "Adverse drug reaction" not in adverse_events
    assert scorecard_payload == []
