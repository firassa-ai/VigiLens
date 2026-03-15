from __future__ import annotations

from pathlib import Path

import psycopg
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
    )


def _quarters_2018_q1_to_2023_q4() -> list[str]:
    quarters: list[str] = []
    for year in range(2018, 2024):
        for quarter in range(1, 5):
            quarters.append(f"{year}-Q{quarter}")
    return quarters


@pytest.mark.asyncio
async def test_step83_semaglutide_baseline_guardrails(
    postgres_urls,
    reset_database,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": _quarters_2018_q1_to_2023_q4(),
            },
        )
        assert seed.status_code == 200
        seed_payload = seed.json()
        assert int(seed_payload["reports_by_drug"]["semaglutide"]) == 2237

        ingest_status = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
        assert ingest_status.status_code == 200
        status_payload = ingest_status.json()
        assert len(status_payload["quarters_loaded"]) == 24
        assert status_payload["quarters_loaded"][0] == "2018-Q1"
        assert status_payload["quarters_loaded"][-1] == "2023-Q4"
        assert int(status_payload["total_reports_loaded"]) == 2237

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        episode_items = episodes.json()
        assert len(episode_items) == 24

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        belief_items = beliefs.json()
        assert len(belief_items) in {72, 73}

        grounded = [
            row for row in belief_items if isinstance(row.get("episodic_ids_used"), list) and len(row["episodic_ids_used"]) > 0
        ]
        # In this test matrix EverMemOS is intentionally unreachable; zero grounding is
        # acceptable as long as deterministic fallback beliefs still populate.
        assert len(grounded) >= int(0.5 * len(belief_items)) or len(grounded) == 0

        gi_rows = [row for row in belief_items if "gi motility concerns" in row.get("question_text", "").lower()]
        assert len(gi_rows) >= 2
        gi_rows = sorted(gi_rows, key=lambda row: row["created_at"])
        before_id = gi_rows[0]["id"]
        after_id = gi_rows[-1]["id"]
        diff = await client.get(
            "/api/v1/beliefs/semaglutide/diff",
            params={"before_id": before_id, "after_id": after_id},
        )
        assert diff.status_code == 200
        diff_payload = diff.json()
        after_text = str(diff_payload["after"]["answer_text"]).lower()
        reinterpret_ids = diff_payload.get("reinterpreted_report_ids") or []
        assert reinterpret_ids or ("reinterpret" in after_text)

        timeline = await client.get("/api/v1/drugs/semaglutide/timeline")
        assert timeline.status_code == 200
        rows_2023_q4 = [row for row in timeline.json() if row["quarter"] == "2023-Q4"]
        constipation = next((row for row in rows_2023_q4 if row["adverse_event"] == "Constipation"), None)
        ileus = next((row for row in rows_2023_q4 if row["adverse_event"] == "Ileus"), None)
        assert constipation is not None
        assert ileus is not None
        assert constipation["trajectory"] == "accelerating"
        assert ileus["trajectory"] in {"emerging", "accelerating"}

        scorecard = await client.get("/api/v1/drugs/semaglutide/scorecard")
        assert scorecard.status_code == 200
        score_rows = scorecard.json()
        lookup = {
            (row["prediction"]["adverse_event"], row["prediction"]["predicted_action"]): row["result"]
            for row in score_rows
        }
        assert lookup.get(("Ileus", "label_change")) == "validated"
        assert lookup.get(("Suicidal ideation", "safety_communication")) == "validated"


@pytest.mark.asyncio
async def test_memory_proxy_returns_cached_payload(
    postgres_urls,
    reset_database,
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

    with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evermemos_memory_cache
                  (memory_id, drug_id, group_id, memory_type, quarter, source_endpoint, raw_payload)
                VALUES
                  (
                    'episodic:semaglutide:2018-Q4',
                    'semaglutide',
                    'vigl:semaglutide',
                    'episodic_memory',
                    '2018-Q4',
                    'GET /search',
                    '{"id":"episodic:semaglutide:2018-Q4","summary":"Quarter digest"}'::jsonb
                  )
                ON CONFLICT (memory_id) DO NOTHING
                """
            )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/memory-proxy/episodic%3Asemaglutide%3A2018-Q4",
            params={"drug_id": "semaglutide"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["memory_id"] == "episodic:semaglutide:2018-Q4"
        assert payload["drug_id"] == "semaglutide"
        assert payload["cached"] is True
        assert payload["payload"]["id"] == "episodic:semaglutide:2018-Q4"
