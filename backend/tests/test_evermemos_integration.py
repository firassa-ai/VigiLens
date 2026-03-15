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
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        gemini_api_key=None,
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_profile_and_episodes_fallback_and_request_logging(
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

        profile = await client.get("/api/v1/drugs/semaglutide/profile")
        assert profile.status_code == 200
        profile_body = profile.json()
        assert profile_body["drug_id"] == "semaglutide"
        assert profile_body["risk_level"] in {"low", "moderate", "elevated", "high"}
        assert "FAERS limitation" in profile_body["current_assessment"]

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        ep = episodes.json()
        assert [item["quarter"] for item in ep] == ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"]
        assert all("generated from Postgres" in item["narrative"] for item in ep)
        assert all(item["memory_source"] == "postgres_fallback" for item in ep)
        assert all(item["memory_id"] is None for item in ep)

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM evermemos_requests;")
            total_requests = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM evermemos_requests WHERE status='failed';")
            failed_requests = cur.fetchone()[0]

    assert total_requests >= 10
    assert failed_requests == total_requests


@pytest.mark.asyncio
async def test_startup_recreates_missing_evermemos_tables(
    postgres_urls,
    reset_database,
) -> None:
    with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS evermemos_memory_cache;")
            cur.execute("DROP TABLE IF EXISTS evermemos_requests;")

    app = create_app(_build_settings(postgres_urls))

    async with app.router.lifespan_context(app):
        with psycopg.connect(postgres_urls.psycopg_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.evermemos_requests');")
                assert cur.fetchone()[0] == "evermemos_requests"
                cur.execute("SELECT to_regclass('public.evermemos_memory_cache');")
                assert cur.fetchone()[0] == "evermemos_memory_cache"


@pytest.mark.asyncio
async def test_profile_uses_evermemos_memory_when_available(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _fake_profile(*args, **kwargs):
        return {
            "result": {
                "memories": [
                    {
                        "summary": "Recent episodic consolidation suggests GI motility vigilance should be elevated.",
                        "created_at": "2026-02-21T00:00:00Z",
                    }
                ]
            }
        }

    async def _empty_episodes(*args, **kwargs):
        return []

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _fake_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _empty_episodes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        profile = await client.get("/api/v1/drugs/semaglutide/profile")
        assert profile.status_code == 200
        body = profile.json()

    assert body["current_assessment"].startswith("EverMemOS profile:")
    assert "GI motility vigilance should be elevated" in body["current_assessment"]


@pytest.mark.asyncio
async def test_seed_posts_substantive_quarter_digest_narrative(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    captured_payloads: list[dict[str, str]] = []

    async def _ok_post_meta(*args, **kwargs):
        return True

    async def _capture_digest(*args, **kwargs):
        body = kwargs.get("body", {})
        captured_payloads.append(
            {
                "quarter": kwargs.get("quarter", ""),
                "content": body.get("content", ""),
            }
        )
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _empty_episodes(*args, **kwargs):
        return []

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post_meta)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _capture_digest)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _empty_episodes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1"],
            },
        )
        assert seed.status_code == 200

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]["content"]
    assert "VigiLens 2018-Q1 Surveillance Summary for semaglutide:" in payload
    assert "new adverse event reports processed this quarter" in payload
    assert "Overall risk assessment:" in payload
    assert "FAERS limitation:" in payload


@pytest.mark.asyncio
async def test_episodes_overlay_evermemos_memories(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _episodic_memories(*args, **kwargs):
        return [
            {
                "id": "memory-q1",
                "summary": "VigiLens Quarter Digest - 2018-Q1. Nausea and Vomiting clusters dominated reports.",
            },
            {
                "id": "memory-q3",
                "summary": "VigiLens Quarter Digest - 2018-Q3. Pancreatitis concerns were reviewed.",
            },
        ]

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _episodic_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    by_quarter = {row["quarter"]: row for row in body}
    assert "2018-Q1" in by_quarter["2018-Q1"]["narrative"]
    assert "2018-Q3" in by_quarter["2018-Q3"]["narrative"]
    assert by_quarter["2018-Q1"]["memory_source"] == "evermemos"
    assert by_quarter["2018-Q3"]["memory_source"] == "evermemos"
    assert by_quarter["2018-Q1"]["memory_id"] == "memory-q1"
    assert by_quarter["2018-Q3"]["memory_id"] == "memory-q3"
    assert "generated from Postgres" in by_quarter["2018-Q2"]["narrative"]
    assert "generated from Postgres" in by_quarter["2018-Q4"]["narrative"]
    assert by_quarter["2018-Q2"]["memory_source"] == "postgres_fallback"
    assert by_quarter["2018-Q4"]["memory_source"] == "postgres_fallback"


@pytest.mark.asyncio
async def test_ingest_posts_profile_memory_as_best_effort(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    captured_profiles: list[dict[str, str]] = []

    async def _ok_post(*args, **kwargs):
        return True

    async def _store_profile(*args, **kwargs):
        profile_data = kwargs.get("profile_data", {})
        captured_profiles.append(
            {
                "risk_level": str(profile_data.get("risk_level", "")),
                "last_updated": str(profile_data.get("last_updated", "")),
            }
        )
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _empty_episodes(*args, **kwargs):
        return []

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "store_profile_memory", _store_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _empty_episodes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1"],
            },
        )
        assert seed.status_code == 200

        ingest = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
        assert ingest.status_code == 200

    assert len(captured_profiles) >= 1
    assert captured_profiles[-1]["risk_level"] in {"low", "moderate", "elevated", "high"}
    assert captured_profiles[-1]["last_updated"] == "2018-Q2"


@pytest.mark.asyncio
async def test_episodes_prefers_more_specific_quarter_memory(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _episodic_memories(*args, **kwargs):
        return [
            {
                "id": "memory-range",
                "summary": "Semaglutide review from 2018-Q1 through 2018-Q4.",
            },
            {
                "id": "memory-q2",
                "summary": "Focused quarter note for 2018-Q2 only.",
            },
        ]

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _episodic_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    by_quarter = {row["quarter"]: row for row in body}
    assert by_quarter["2018-Q1"]["memory_id"] == "memory-range"
    assert by_quarter["2018-Q2"]["memory_id"] == "memory-q2"
    assert by_quarter["2018-Q3"]["memory_id"] == "memory-range"
    assert by_quarter["2018-Q4"]["memory_id"] == "memory-range"


@pytest.mark.asyncio
async def test_episodes_supports_q_then_year_memory_format(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _episodic_memories(*args, **kwargs):
        return [
            {
                "id": "memory-q4-2022",
                "title": "VigiLens Q4 2022 Safety Report on Semaglutide",
                "summary": "Signal update for semaglutide in Q4 2022.",
            }
        ]

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _episodic_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2022-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    assert body[0]["quarter"] == "2022-Q4"
    assert body[0]["memory_source"] == "evermemos"
    assert body[0]["memory_id"] == "memory-q4-2022"


@pytest.mark.asyncio
async def test_episodes_prefers_episode_narrative_when_summary_is_truncated(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    long_episode = (
        "VigiLens Quarter Digest 2022-Q4 for semaglutide reported accelerated GI signal pressure. "
        "Constipation ROR increased to 3.95 with CI lower above 2.0, ileus remained emerging, and nausea stayed high. "
        "Monitoring recommended deeper hospitalization triage and weekly signal recalculation."
    )

    async def _episodic_memories(*args, **kwargs):
        return [
            {
                "id": "memory-q4-episode",
                "summary": "Quarter digest summary (truncated).",
                "episode": long_episode,
            }
        ]

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _episodic_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2022-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    assert body[0]["quarter"] == "2022-Q4"
    assert body[0]["memory_source"] == "evermemos"
    assert body[0]["memory_id"] == "memory-q4-episode"
    assert len(body[0]["narrative"]) > 220
    assert "Constipation ROR increased" in body[0]["narrative"]


@pytest.mark.asyncio
async def test_episodes_enriches_short_summary_with_search_results(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _bulk_memory(*args, **kwargs):
        return [
            {
                "id": "short-q4",
                "title": "VigiLens Quarter Digest 2022-Q4",
                "summary": "Short digest summary for semaglutide.",
            }
        ]

    async def _search_memories(*args, **kwargs):
        query = kwargs.get("query", "")
        if "2022-Q4" in query or "Q4 2022" in query:
            return [
                {
                    "id": "search-q4-rich",
                    "episode": (
                        "VigiLens Quarter Digest 2022-Q4 for semaglutide observed sustained constipation pressure "
                        "(ROR 3.95) with ileus trend acceleration and ongoing nausea burden. "
                        "The quarter included escalation planning for potential regulator-facing updates."
                    ),
                }
            ]
        return []

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _bulk_memory)
    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _search_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2022-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    assert body[0]["quarter"] == "2022-Q4"
    assert body[0]["memory_source"] == "evermemos"
    assert body[0]["memory_id"] == "search-q4-rich"
    assert len(body[0]["narrative"]) > 220
    assert "constipation pressure" in body[0]["narrative"].lower()


@pytest.mark.asyncio
async def test_episodes_can_use_search_when_bulk_fetch_returns_empty(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _no_bulk_memories(*args, **kwargs):
        return []

    async def _search_memories(*args, **kwargs):
        query = kwargs.get("query", "")
        if "2022-Q4" in query or "Q4 2022" in query:
            return [
                {
                    "id": "search-q4-2022",
                    "title": "Semaglutide digest for Q4 2022",
                    "summary": "Q4 2022 summary for semaglutide safety signals.",
                }
            ]
        return []

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _no_bulk_memories)
    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _search_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2022-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    assert body[0]["quarter"] == "2022-Q4"
    assert body[0]["memory_source"] == "evermemos"
    assert body[0]["memory_id"] == "search-q4-2022"


@pytest.mark.asyncio
async def test_episodes_search_sequence_can_recover_from_wrong_episodic_hits(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _no_bulk_memories(*args, **kwargs):
        return []

    async def _search_memories(*args, **kwargs):
        query = kwargs.get("query", "")
        memory_types = tuple(kwargs.get("memory_types", []))
        calls.append((query, memory_types))

        if memory_types == ("episodic_memory",):
            return [
                {
                    "id": "wrong-episodic",
                    "summary": "VigiLens Quarter Digest - 2022-Q3",
                }
            ]
        if memory_types == ("event_log",) and ("2022-Q4" in query or "Q4 2022" in query):
            return [
                {
                    "id": "right-eventlog",
                    "atomic_fact": "The report is titled 'VigiLens Quarter Digest — 2022-Q4'.",
                }
            ]
        return []

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _no_bulk_memories)
    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _search_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2022-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    assert body[0]["quarter"] == "2022-Q4"
    assert body[0]["memory_source"] == "evermemos"
    assert body[0]["memory_id"] == "right-eventlog"
    assert any(memory_types == ("episodic_memory",) for _, memory_types in calls)
    assert any(memory_types == ("event_log",) for _, memory_types in calls)


@pytest.mark.asyncio
async def test_episodes_can_map_quarter_from_message_id_pattern(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    app = create_app(_build_settings(postgres_urls))

    async def _ok_post(*args, **kwargs):
        return True

    async def _empty_profile(*args, **kwargs):
        return {"result": {"memories": []}}

    async def _episodic_memories(*args, **kwargs):
        return [
            {
                "id": "mem-msgid",
                "message_id": "vigl_semaglutide_2021Q4_digest",
                "atomic_fact": "Quarter digest synthesized for semaglutide safety monitoring.",
            }
        ]

    monkeypatch.setattr(app.state.evermemos_client, "post_conversation_meta", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "post_quarter_digest", _ok_post)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_profile", _empty_profile)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _episodic_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2021-Q4"],
            },
        )
        assert seed.status_code == 200

        episodes = await client.get("/api/v1/drugs/semaglutide/episodes")
        assert episodes.status_code == 200
        body = episodes.json()

    assert body[0]["quarter"] == "2021-Q4"
    assert body[0]["memory_source"] == "evermemos"
    assert body[0]["memory_id"] == "mem-msgid"
