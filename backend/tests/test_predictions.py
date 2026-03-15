from __future__ import annotations

import json
from pathlib import Path

import pytest
import psycopg
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


def _quarters_2018_q1_to_2023_q4() -> list[str]:
    quarters: list[str] = []
    for year in range(2018, 2024):
        for quarter in range(1, 5):
            quarters.append(f"{year}-Q{quarter}")
    return quarters


@pytest.mark.asyncio
async def test_scorecard_contains_validated_prediction_after_late_timeline_seed(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": _quarters_2018_q1_to_2023_q4(),
            },
        )
        assert seed.status_code == 200

        scorecard = await client.get("/api/v1/drugs/semaglutide/scorecard")
        assert scorecard.status_code == 200
        rows = scorecard.json()

    assert len(rows) >= 1
    by_event = {
        (row["prediction"]["adverse_event"], row["prediction"]["predicted_action"]): row["result"]
        for row in rows
    }
    suicidal_row = next(
        (
            row
            for row in rows
            if row["prediction"]["adverse_event"] == "Suicidal ideation"
            and row["prediction"]["predicted_action"] == "safety_communication"
        ),
        None,
    )
    assert by_event.get(("Ileus", "label_change")) == "validated"
    assert by_event.get(("Suicidal ideation", "safety_communication")) == "validated"
    assert ("Pancreatitis", "label_change") not in by_event
    assert suicidal_row is not None
    ileus_row = next(
        (
            row
            for row in rows
            if row["prediction"]["adverse_event"] == "Ileus"
            and row["prediction"]["predicted_action"] == "label_change"
        ),
        None,
    )
    assert ileus_row is not None
    assert ileus_row["prediction"]["basis"]["type"] == "cross_signal_guardrail"
    assert "2022-Q4" in ileus_row["prediction"]["basis"]["summary"]
    assert ileus_row["prediction"]["scope"] == {
        "type": "drug",
        "key": "semaglutide",
        "label": "Semaglutide",
    }
    assert ileus_row["prediction"]["supporting_event"]["adverse_event"] == "Constipation"
    assert ileus_row["prediction"]["supporting_event"]["quarter"] == "2022-Q4"
    assert ileus_row["prediction"]["supporting_event"]["evidence_report_ids"]
    assert all(
        path.startswith("/api/v1/evidence/")
        for path in ileus_row["prediction"]["supporting_event"]["evidence_api_paths"]
    )
    assert ileus_row["actual_fda_action"]["scope"] == {
        "type": "drug",
        "key": "semaglutide",
        "label": "Semaglutide",
    }
    assert suicidal_row["prediction"]["basis"]["type"] == "sentinel_report_guardrail"
    assert suicidal_row["prediction"]["supporting_event"]["adverse_event"] == "Suicidal ideation"
    assert suicidal_row["actual_fda_action"]["scope"] == {
        "type": "class",
        "key": "glp1_receptor_agonists",
        "label": "GLP-1 receptor agonists",
    }
    assert suicidal_row["actual_fda_action"]["source_url"].endswith(
        "update-fdas-ongoing-evaluation-reports-suicidal-thoughts-or-actions-patients-taking-certain-type"
    )


@pytest.mark.asyncio
async def test_seed_writes_foresight_memories_for_predictions(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    captured: list[dict[str, object]] = []

    async def _ok_post(*args, **kwargs):
        return True

    async def _store_foresight(*args, **kwargs):
        captured.append(kwargs.get("foresight_data", {}))
        return True

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "store_foresight_memory", _store_foresight)
    monkeypatch.setattr(app.state.evermemos_client, "store_event_log_memory", _ok_post)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": _quarters_2018_q1_to_2023_q4(),
            },
        )
        assert seed.status_code == 200

    assert len(captured) >= 2
    predictions = {str(item.get("prediction", "")) for item in captured}
    assert "Ileus label_change" in predictions
    assert "Suicidal ideation safety_communication" in predictions


@pytest.mark.asyncio
async def test_foresight_status_uses_latest_attempt_per_prediction(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _store_foresight(*args, **kwargs):
        return True

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "store_foresight_memory", _store_foresight)
    monkeypatch.setattr(app.state.evermemos_client, "store_event_log_memory", _ok_post)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": _quarters_2018_q1_to_2023_q4(),
            },
        )
        assert seed.status_code == 200

    rows = [
        ("2023-Q2", "Ileus label_change", "failed", "ReadTimeout", "2026-01-01T00:00:00+00:00"),
        ("2023-Q2", "Ileus label_change", "ok", None, "2026-01-01T00:01:00+00:00"),
        (
            "2023-Q3",
            "Suicidal ideation safety_communication",
            "failed",
            "ReadTimeout",
            "2026-01-01T00:02:00+00:00",
        ),
        (
            "2023-Q3",
            "Suicidal ideation safety_communication",
            "failed",
            "ReadError",
            "2026-01-01T00:03:00+00:00",
        ),
    ]

    with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for quarter, prediction, status, error_type, created_at in rows:
                request_body = {
                    "params": {},
                    "json": {
                        "memory_type": "foresight",
                        "message_id": f"vigl_semaglutide_{quarter}_foresight",
                        "foresight_data": {
                            "prediction": prediction,
                            "created_at_quarter": quarter,
                        },
                    },
                }
                response_body = (
                    {"ok": True}
                    if status == "ok"
                    else {"error": "transport failure", "error_type": error_type}
                )
                cur.execute(
                    """
                    insert into evermemos_requests (
                        drug_id,
                        quarter,
                        endpoint,
                        request_body,
                        response_body,
                        status,
                        created_at,
                        updated_at
                    ) values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                    """,
                    (
                        "semaglutide",
                        quarter,
                        "POST /",
                        json.dumps(request_body),
                        json.dumps(response_body),
                        status,
                        created_at,
                        created_at,
                    ),
                )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/drugs/semaglutide/foresight-status")
        assert response.status_code == 200

    status = response.json()
    assert status["total_predictions"] >= 2
    assert status["attempted_writes"] == 2
    assert status["successful_writes"] == 1
    assert status["failed_writes"] == 1
    assert status["last_attempted_quarter"] == "2023-Q3"
    assert status["message"] == "Foresight write failed ⚠️ EverMemOS write errors were detected."
