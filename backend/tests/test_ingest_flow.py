from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.services import ingestion_service


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_ingest_status_and_reset(
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

        status_response = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["drug_id"] == "semaglutide"
        assert status_payload["quarters_loaded"] == ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"]
        assert status_payload["next_quarter"] == "2019-Q1"
        assert status_payload["evermemos_status"] == "ready"
        # Step 22 expanded the curated semaglutide baseline to reduce ROR inflation artifacts.
        assert status_payload["total_reports_loaded"] >= 30

        reset_response = await client.post(
            "/api/v1/ingest/reset",
            json={"drug_id": "semaglutide", "hard": False},
        )
        assert reset_response.status_code == 200
        payload = reset_response.json()
        assert payload["drug_id"] == "semaglutide"
        assert payload["quarters_loaded"] == []
        assert payload["next_quarter"] == "2018-Q1"
        assert payload["total_reports_loaded"] == 0
        assert payload["evermemos_status"] == "idle"
        assert payload["total_quarters_available"] >= 1


@pytest.mark.asyncio
async def test_hard_reset_invokes_evermemos_delete(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    called: list[str] = []

    async def _fake_delete(*_args, **kwargs) -> bool:
        called.append(kwargs["drug_id"])
        return True

    monkeypatch.setattr(app.state.evermemos_client, "delete_group_memories", _fake_delete)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        reset_response = await client.post(
            "/api/v1/ingest/reset",
            json={"drug_id": "semaglutide", "hard": True},
        )
        assert reset_response.status_code == 200

    assert called == ["semaglutide"]


@pytest.mark.asyncio
async def test_hard_reset_succeeds_when_evermemos_delete_raises(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _failing_delete(*_args, **_kwargs) -> bool:
        raise RuntimeError("evermemos unavailable")

    monkeypatch.setattr(app.state.evermemos_client, "delete_group_memories", _failing_delete)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        reset_response = await client.post(
            "/api/v1/ingest/reset",
            json={"drug_id": "semaglutide", "hard": True},
        )
        assert reset_response.status_code == 200
        payload = reset_response.json()
        assert payload["drug_id"] == "semaglutide"
        assert payload["quarters_loaded"] == []
        assert payload["next_quarter"] == "2018-Q1"
        assert payload["total_reports_loaded"] == 0
        assert payload["evermemos_status"] == "idle"
        assert payload["total_quarters_available"] >= 1


@pytest.mark.asyncio
async def test_ingest_next_quarter_writes_report_level_event_logs(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    captured: list[dict[str, object]] = []

    async def _ok(*args, **kwargs):
        return True

    async def _capture_event_log(*args, **kwargs):
        captured.append(kwargs.get("event_log_data", {}))
        return True

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok)
    monkeypatch.setattr(app.state.evermemos_client, "store_profile_memory", _ok)
    monkeypatch.setattr(app.state.evermemos_client, "store_foresight_memory", _ok)
    monkeypatch.setattr(app.state.evermemos_client, "store_event_log_memory", _capture_event_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        captured.clear()

        ingest_response = await client.post(
            "/api/v1/ingest/next-quarter",
            json={"drug_id": "semaglutide"},
        )

    assert ingest_response.status_code == 200
    assert captured
    assert all(item["quarter"] == "2019-Q1" for item in captured)
    assert all(
        str(item["evidence_api_path"]).startswith("/api/v1/evidence/")
        for item in captured
    )


@pytest.mark.asyncio
async def test_concurrent_ingest_same_drug_conflicts(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    real_recompute = ingestion_service.recompute_signals_after_ingestion

    async def slow_recompute(*args, **kwargs):
        await asyncio.sleep(0.2)
        return await real_recompute(*args, **kwargs)

    monkeypatch.setattr(ingestion_service, "recompute_signals_after_ingestion", slow_recompute)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        async def _ingest_once():
            return await client.post(
                "/api/v1/ingest/next-quarter",
                json={"drug_id": "semaglutide"},
            )

        responses = await asyncio.gather(_ingest_once(), _ingest_once())

    status_codes = sorted(response.status_code for response in responses)
    assert status_codes == [200, 409]

    conflict = [response for response in responses if response.status_code == 409][0]
    assert conflict.json() == {
        "error": "Conflict",
        "detail": "ingestion for drug_id 'semaglutide' is already in progress",
        "status_code": 409,
    }


def test_websocket_receives_ingest_progress_sequence(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    with TestClient(app) as client:
        seed = client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        with client.websocket_connect("/ws/ingest-progress?drug_id=semaglutide") as ws:
            ingest_response = client.post(
                "/api/v1/ingest/next-quarter",
                json={"drug_id": "semaglutide"},
            )
            assert ingest_response.status_code == 200
            assert ingest_response.json()["next_quarter"] == "2019-Q2"

            messages = [ws.receive_json() for _ in range(6)]

    phases = [message["message"]["phase"] for message in messages]
    assert phases == [
        "starting",
        "loading_reports",
        "computing_signals",
        "posting_evermemos",
        "generating_beliefs",
        "done",
    ]

    for message in messages:
        assert message["message"]["quarter"] == "2019-Q1"
        thoughts = message["message"].get("thoughts") or []
        for thought in thoughts:
            metadata = thought.get("metadata") or {}
            previews = metadata.get("memory_preview") if isinstance(metadata, dict) else None
            if isinstance(previews, dict):
                for preview in previews.values():
                    if isinstance(preview, str):
                        assert len(preview) <= 200


@pytest.mark.asyncio
async def test_ingest_returns_no_more_quarters_after_dataset_end(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    preload = [f"{year}-Q{quarter}" for year in range(2018, 2026) for quarter in range(1, 5)]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": preload,
            },
        )
        assert seed.status_code == 200

        status_response = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
        assert status_response.status_code == 200
        assert status_response.json()["next_quarter"] is None

        ingest_response = await client.post(
            "/api/v1/ingest/next-quarter",
            json={"drug_id": "semaglutide"},
        )
        assert ingest_response.status_code == 400
        assert ingest_response.json() == {
            "error": "BadRequest",
            "detail": "no more quarters available for drug_id 'semaglutide'",
            "status_code": 400,
        }
