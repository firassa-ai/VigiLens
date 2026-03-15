from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter

from app.core.config import Settings
from app.main import create_app
from app.schemas.health import HealthResponse
from app.schemas.ingest import IngestStatus
from app.schemas.shared import (
    Belief,
    BeliefDiff,
    Drug,
    DrugProfile,
    EpisodicSummary,
    FAERSReport,
    FDAAction,
    ForesightMemoryStatus,
    QueryResponse,
    ScorecardEntry,
    SignalPoint,
)


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_http_api_contract_matrix(
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

        health = await client.get("/api/v1/health")
        assert health.status_code == 200
        HealthResponse.model_validate(health.json())

        drugs = await client.get("/api/v1/drugs")
        assert drugs.status_code == 200
        drug_items = TypeAdapter(list[Drug]).validate_python(drugs.json())
        assert any(item.id == "semaglutide" for item in drug_items)

        status = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
        assert status.status_code == 200
        IngestStatus.model_validate(status.json())

        profile = await client.get("/api/v1/drugs/semaglutide/profile")
        assert profile.status_code == 200
        DrugProfile.model_validate(profile.json())

        timeline = await client.get("/api/v1/drugs/semaglutide/timeline")
        assert timeline.status_code == 200
        TypeAdapter(list[SignalPoint]).validate_python(timeline.json())

        signals = await client.get("/api/v1/drugs/semaglutide/signals")
        assert signals.status_code == 200
        TypeAdapter(list[SignalPoint]).validate_python(signals.json())

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        TypeAdapter(list[EpisodicSummary]).validate_python(episodes.json())

        actions = await client.get("/api/v1/drugs/semaglutide/fda-actions")
        assert actions.status_code == 200
        TypeAdapter(list[FDAAction]).validate_python(actions.json())

        query_first = await client.post(
            "/api/v1/query",
            json={
                "drug_id": "semaglutide",
                "question_text": "Are there emerging GI motility concerns for semaglutide?",
                "quarter_context": "2018-Q3",
            },
        )
        assert query_first.status_code == 200
        query_first_payload = QueryResponse.model_validate(query_first.json())
        assert query_first_payload.evidence

        query_second = await client.post(
            "/api/v1/query",
            json={
                "drug_id": "semaglutide",
                "question_text": "Are there emerging GI motility concerns for semaglutide?",
                "quarter_context": "2018-Q4",
            },
        )
        assert query_second.status_code == 200
        QueryResponse.model_validate(query_second.json())

        report_id = query_first_payload.evidence[0].safetyreportid
        evidence = await client.get(f"/api/v1/evidence/{report_id}")
        assert evidence.status_code == 200
        FAERSReport.model_validate(evidence.json())

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        belief_items = TypeAdapter(list[Belief]).validate_python(beliefs.json())
        assert belief_items

        grouped: dict[str, list[Belief]] = {}
        for belief in belief_items:
            grouped.setdefault(belief.question_hash, []).append(belief)

        pair = next((items for items in grouped.values() if len(items) >= 2), None)
        assert pair is not None
        before = sorted(pair, key=lambda item: item.created_at)[0]
        after = sorted(pair, key=lambda item: item.created_at)[-1]

        belief_diff = await client.get(
            "/api/v1/beliefs/semaglutide/diff",
            params={"before_id": before.id, "after_id": after.id},
        )
        assert belief_diff.status_code == 200
        BeliefDiff.model_validate(belief_diff.json())

        scorecard = await client.get("/api/v1/drugs/semaglutide/scorecard")
        assert scorecard.status_code == 200
        TypeAdapter(list[ScorecardEntry]).validate_python(scorecard.json())

        foresight_status = await client.get("/api/v1/drugs/semaglutide/foresight-status")
        assert foresight_status.status_code == 200
        ForesightMemoryStatus.model_validate(foresight_status.json())

        ingest_next = await client.post(
            "/api/v1/ingest/next-quarter",
            json={"drug_id": "semaglutide"},
        )
        assert ingest_next.status_code == 200
        IngestStatus.model_validate(ingest_next.json())

        reset = await client.post(
            "/api/v1/ingest/reset",
            json={"drug_id": "semaglutide", "hard": False},
        )
        assert reset.status_code == 200
        IngestStatus.model_validate(reset.json())
