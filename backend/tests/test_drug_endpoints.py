from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.services import situation_engine


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_drug_listing_and_related_endpoints(
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

        drugs = await client.get("/api/v1/drugs")
        assert drugs.status_code == 200
        items = drugs.json()
        by_id = {item["id"]: item for item in items}
        assert "semaglutide" in by_id
        assert by_id["semaglutide"]["next_quarter"] == "2019-Q1"
        assert by_id["semaglutide"]["total_reports"] > 0

        signals = await client.get("/api/v1/drugs/semaglutide/signals")
        assert signals.status_code == 200
        assert isinstance(signals.json(), list)

        casefile_summary = await client.get("/api/v1/drugs/semaglutide/casefile-summary")
        assert casefile_summary.status_code == 200
        summary_payload = casefile_summary.json()
        assert summary_payload["drug_id"] == "semaglutide"
        assert summary_payload["stage"] in {"baseline", "emergence", "escalation", "receipt_validation"}
        assert "headline" in summary_payload
        assert "watchlist_alerts" in summary_payload
        assert "public_forecasts" in summary_payload

        actions = await client.get("/api/v1/drugs/semaglutide/fda-actions")
        assert actions.status_code == 200
        action_items = actions.json()
        assert len(action_items) >= 1
        assert all("source_url" in item for item in action_items)

        scorecard = await client.get("/api/v1/drugs/semaglutide/scorecard")
        assert scorecard.status_code == 200
        assert isinstance(scorecard.json(), list)


@pytest.mark.asyncio
async def test_signals_endpoint_rejects_unknown_drug(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/drugs/unknown/signals")

    assert response.status_code == 400
    assert response.json() == {
        "error": "BadRequest",
        "detail": "drug_id 'unknown' not found",
        "status_code": 400,
    }


@pytest.mark.asyncio
async def test_delete_drug_removes_tracked_casefile_and_keeps_other_drugs(
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

        delete_response = await client.delete("/api/v1/drugs/metformin")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"drug_id": "metformin", "deleted": True}

        drugs = await client.get("/api/v1/drugs")
        assert drugs.status_code == 200
        remaining_ids = {item["id"] for item in drugs.json()}
        assert "metformin" not in remaining_ids
        assert "semaglutide" in remaining_ids

        deleted_signals = await client.get("/api/v1/drugs/metformin/signals")
        assert deleted_signals.status_code == 400
        assert deleted_signals.json() == {
            "error": "BadRequest",
            "detail": "drug_id 'metformin' not found",
            "status_code": 400,
        }


@pytest.mark.asyncio
async def test_delete_drug_returns_not_found_for_unknown_id(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/v1/drugs/unknown")

    assert response.status_code == 404
    assert response.json() == {
        "error": "NotFound",
        "detail": "drug_id 'unknown' not found",
        "status_code": 404,
    }


@pytest.mark.asyncio
async def test_situation_analysis_times_out_to_fallback_without_blocking_route(
    postgres_urls,
    reset_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    def slow_gemini(*_args, **_kwargs):
        time.sleep(0.05)
        return {
            "narrative": "should not be returned",
            "risk_level": "high",
            "key_changes": ["x", "y", "z"],
        }

    monkeypatch.setattr(situation_engine, "_call_gemini", slow_gemini)
    monkeypatch.setattr(situation_engine, "SITUATION_GEMINI_TIMEOUT_SECONDS", 0.01)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        started = time.perf_counter()
        response = await client.get("/api/v1/drugs/semaglutide/situation?quarter=2018-Q4")
        elapsed = time.perf_counter() - started

    assert response.status_code == 200
    payload = response.json()
    assert payload["drug_id"] == "semaglutide"
    assert payload["quarter"] == "2018-Q4"
    assert payload["narrative"] == situation_engine.FALLBACK_NARRATIVE
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_situation_analysis_route_does_not_depend_on_evermemos_search(
    postgres_urls,
    reset_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def fake_gemini(*_args, **_kwargs):
        return {
            "narrative": "### Risk Posture\nGenerated brief.\n\n### Forward Look\nGenerated outlook.",
            "risk_level": "moderate",
            "key_changes": ["one", "two", "three"],
        }

    async def fail_search(*_args, **_kwargs):
        raise AssertionError("search_memories should not be called for situation analysis")

    monkeypatch.setattr(situation_engine, "_call_gemini_with_timeout", fake_gemini)
    app.state.evermemos_client.search_memories = fail_search

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        response = await client.get("/api/v1/drugs/semaglutide/situation?quarter=2018-Q4")

    assert response.status_code == 200
    payload = response.json()
    assert payload["drug_id"] == "semaglutide"
    assert payload["quarter"] == "2018-Q4"
    assert payload["narrative"].startswith("### Risk Posture")


@pytest.mark.asyncio
async def test_situation_analysis_regenerates_after_cached_fallback(
    postgres_urls,
    reset_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        async def fallback_gemini(*_args, **_kwargs):
            return None

        monkeypatch.setattr(situation_engine, "_call_gemini_with_timeout", fallback_gemini)

        first = await client.get("/api/v1/drugs/semaglutide/situation?quarter=2018-Q4")
        assert first.status_code == 200
        assert first.json()["narrative"] == situation_engine.FALLBACK_NARRATIVE

        async def generated_gemini(*_args, **_kwargs):
            return {
                "narrative": "### Risk Posture\nRecovered brief.\n\n### Forward Look\nRecovered outlook.",
                "risk_level": "moderate",
                "key_changes": ["one", "two", "three"],
            }

        monkeypatch.setattr(situation_engine, "_call_gemini_with_timeout", generated_gemini)

        second = await client.get("/api/v1/drugs/semaglutide/situation?quarter=2018-Q4")

    assert second.status_code == 200
    assert second.json()["narrative"].startswith("### Risk Posture")


@pytest.mark.asyncio
async def test_situation_analysis_releases_db_session_before_waiting_on_gemini(
    postgres_urls,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = SimpleNamespace(
        rollback_calls=0,
        commit_calls=0,
    )

    async def fake_scalar(*_args, **_kwargs):
        return None

    async def fake_rollback():
        fake_db.rollback_calls += 1

    class _ExecuteResult:
        def scalar_one(self) -> str:
            return "generated-row"

    async def fake_execute(*_args, **_kwargs):
        return _ExecuteResult()

    async def fake_commit():
        fake_db.commit_calls += 1

    fake_db.scalar = fake_scalar
    fake_db.rollback = fake_rollback
    fake_db.execute = fake_execute
    fake_db.commit = fake_commit

    async def fake_gather_context(*_args, **_kwargs):
        return {
            "drug_name": "semaglutide",
            "quarter": "2018-Q4",
            "n_reports": 12,
            "n_detected": 1,
            "signal_data": "  - GI Motility Harm: 12 cumul. reports",
            "belief_summaries": "  - [76%] Are there emerging GI motility concerns for semaglutide?",
            "fda_actions": "  (none)",
            "delta_summary": "  (first quarter — no prior data)",
            "foresight_data": "  (no predictions yet)",
            "episodic_narratives": "  (not available)",
            "memory_sources": ["EventLog", "Profile", "Episodic"],
            "beliefs": [
                SimpleNamespace(
                    question_hash="sha256:gi",
                    confidence_score=76,
                    answer_text="GI answer",
                )
            ],
        }

    async def fake_gemini(_settings, _prompt):
        assert fake_db.rollback_calls == 1
        return {
            "narrative": "### Risk Posture\nGenerated brief.\n\n### Forward Look\nGenerated outlook.",
            "risk_level": "moderate",
            "key_changes": ["one", "two", "three"],
        }

    monkeypatch.setattr(situation_engine, "_gather_context", fake_gather_context)
    monkeypatch.setattr(situation_engine, "_call_gemini_with_timeout", fake_gemini)

    settings = _build_settings(postgres_urls)
    result = await situation_engine.generate_situation_analysis(
        fake_db,
        settings=settings,
        drug_id="semaglutide",
        quarter="2018-Q4",
        evermemos_client=None,
    )

    assert fake_db.rollback_calls == 1
    assert fake_db.commit_calls == 1
    assert result.narrative.startswith("### Risk Posture")
