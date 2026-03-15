from __future__ import annotations

from pathlib import Path
import re

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.schemas.shared import Belief
from app.services.belief_engine import compute_question_hash, compute_statistical_confidence, normalize_question_text
from app.utils.diff import compute_belief_diff


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        gemini_api_key=None,
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


def test_question_hash_normalization() -> None:
    q1 = "  Are there emerging GI motility concerns for semaglutide?  "
    q2 = "are   there emerging GI motility concerns for semaglutide?"

    assert normalize_question_text(q1) == normalize_question_text(q2)
    assert compute_question_hash(q1) == compute_question_hash(q2)


def test_compute_statistical_confidence() -> None:
    score = compute_statistical_confidence(n_reports=1000, max_ci_lower=2.5, n_detected=2)
    assert 0 <= score <= 100
    assert score == 55


def test_compute_belief_diff() -> None:
    before = Belief(
        id="b1",
        drug_id="semaglutide",
        question_hash="sha256:x",
        question_text="q",
        answer_text="line a\nline b",
        confidence_score=40,
        evidence_report_ids=["S-1001"],
        episodic_ids_used=[],
        created_at="2026-01-01T00:00:00Z",
        quarter_context="2018-Q4",
    )
    after = Belief(
        id="b2",
        drug_id="semaglutide",
        question_hash="sha256:x",
        question_text="q",
        answer_text="line a\nline c",
        confidence_score=55,
        evidence_report_ids=["S-1001", "S-1002"],
        episodic_ids_used=[],
        created_at="2026-01-02T00:00:00Z",
        quarter_context="2019-Q1",
    )

    diff = compute_belief_diff(before, after, ["S-1002"])
    assert diff.confidence_delta == 15
    assert diff.new_evidence_ids == ["S-1002"]
    assert diff.reinterpreted_report_ids == ["S-1002"]
    assert [line.type for line in diff.text_diff] == ["unchanged", "removed", "added"]


@pytest.mark.asyncio
async def test_query_beliefs_and_diff_endpoints(
    postgres_urls,
    reset_database,
) -> None:
    from app.main import create_app

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

        q = "Are there emerging GI motility concerns for semaglutide?"
        r1 = await client.post(
            "/api/v1/query",
            json={"drug_id": "semaglutide", "question_text": q, "quarter_context": "2018-Q2"},
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert "FAERS limitation" in body1["answer_text"]
        assert 0 <= body1["confidence"] <= 100
        assert len(body1["signal_summary"]) <= 3

        r2 = await client.post(
            "/api/v1/query",
            json={"drug_id": "semaglutide", "question_text": q, "quarter_context": "2018-Q4"},
        )
        assert r2.status_code == 200
        body2 = r2.json()

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        belief_items = beliefs.json()
        assert len(belief_items) >= 2

        before_id = body1["belief_id"]
        after_id = body2["belief_id"]

        diff = await client.get(
            "/api/v1/beliefs/semaglutide/diff",
            params={"before_id": before_id, "after_id": after_id},
        )
        assert diff.status_code == 200
        diff_body = diff.json()
        assert diff_body["before"]["id"] == before_id
        assert diff_body["after"]["id"] == after_id
        assert isinstance(diff_body["confidence_delta"], int)

        other = await client.post(
            "/api/v1/query",
            json={
                "drug_id": "semaglutide",
                "question_text": "What is the overall safety profile of semaglutide?",
                "quarter_context": "2018-Q4",
            },
        )
        assert other.status_code == 200

        mismatch = await client.get(
            "/api/v1/beliefs/semaglutide/diff",
            params={"before_id": before_id, "after_id": other.json()["belief_id"]},
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["error"] == "BadRequest"


@pytest.mark.asyncio
async def test_query_upserts_existing_belief_instead_of_creating_duplicate(
    postgres_urls,
    reset_database,
) -> None:
    from app.main import create_app

    app = create_app(_build_settings(postgres_urls))
    question = "What report-level evidence supports the Vomiting safety signal for semaglutide? Prioritize serious and hospitalization cases."
    quarter = "2019-Q1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4", "2019-Q1"],
            },
        )
        assert seed.status_code == 200

        first = await client.post(
            "/api/v1/query",
            json={"drug_id": "semaglutide", "question_text": question, "quarter_context": quarter},
        )
        assert first.status_code == 200

        second = await client.post(
            "/api/v1/query",
            json={"drug_id": "semaglutide", "question_text": question, "quarter_context": quarter},
        )
        assert second.status_code == 200
        assert first.json()["belief_id"] == second.json()["belief_id"]

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        rows = beliefs.json()

    question_hash = compute_question_hash(question)
    matching = [
        row
        for row in rows
        if row["quarter_context"] == quarter and row["question_hash"] == question_hash
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_ingest_generates_tracked_beliefs(
    postgres_urls,
    reset_database,
) -> None:
    from app.main import create_app

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

        ingest = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
        assert ingest.status_code == 200
        assert ingest.json()["next_quarter"] == "2019-Q2"

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        rows = beliefs.json()

    q2019 = [row for row in rows if row["quarter_context"] == "2019-Q1"]
    assert len(q2019) >= 3
    texts = [row["question_text"] for row in q2019]
    assert any("overall safety profile" in text.lower() for text in texts)
    assert any("gi motility" in text.lower() for text in texts)
    assert any("regulatory attention" in text.lower() for text in texts)
    assert all("as of" not in text.lower() for text in texts)

    q2018 = [row for row in rows if row["quarter_context"] == "2018-Q4"]
    assert len(q2018) >= 3

    hashes_2018 = {row["question_hash"] for row in q2018}
    hashes_2019 = {row["question_hash"] for row in q2019}
    assert hashes_2018 == hashes_2019


@pytest.mark.asyncio
async def test_query_persists_episodic_ids_when_memory_search_returns_hits(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    from app.main import create_app

    app = create_app(_build_settings(postgres_urls))

    async def _search_memories(*args, **kwargs):
        return [
            {
                "id": "mem-abc-1",
                "summary": "VigiLens episodic memory for 2018-Q4 and GI monitoring.",
            },
            {
                "id": "mem-abc-2",
                "summary": "Additional memory context from 2018-Q3 through 2018-Q4.",
            },
        ]

    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _search_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        query = await client.post(
            "/api/v1/query",
            json={
                "drug_id": "semaglutide",
                "question_text": "Are there emerging GI motility concerns for semaglutide?",
                "quarter_context": "2018-Q4",
            },
        )
        assert query.status_code == 200
        query_body = query.json()
        assert len(query_body["episodic_context"]) >= 1
        assert query_body["episodic_context"][0]["memory_source"] == "evermemos"

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        rows = beliefs.json()
        target = next((row for row in rows if row["id"] == query_body["belief_id"]), None)

    assert target is not None
    assert set(target["episodic_ids_used"]) == {"mem-abc-1", "mem-abc-2"}


@pytest.mark.asyncio
async def test_query_memory_grounding_falls_back_to_bulk_episodic_memories(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    from app.main import create_app

    app = create_app(_build_settings(postgres_urls))

    async def _search_empty(*args, **kwargs):
        return []

    async def _bulk_memories(*args, **kwargs):
        return [
            {
                "id": "bulk-2023-q3",
                "title": "Semaglutide safety digest for Q3 2023",
                "summary": "VigiLens digest for Q3 2023 shows emerging ileus and gastroparesis patterns.",
            },
            {
                "id": "bulk-2023-q3-duplicate",
                "title": "Semaglutide safety digest for Q3 2023",
                "summary": "VigiLens digest for Q3 2023 shows emerging ileus and gastroparesis patterns.",
            },
            {
                "id": "bulk-2022-q4",
                "title": "Semaglutide safety digest for Q4 2022",
                "summary": "Signals were monitored before later escalations.",
            },
        ]

    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _search_empty)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _bulk_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        # Advance to late quarter so query context mirrors demo path.
        while True:
            status = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
            assert status.status_code == 200
            next_quarter = status.json()["next_quarter"]
            if next_quarter in {None, "2023-Q4"}:
                break
            ingest = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
            assert ingest.status_code == 200

        query = await client.post(
            "/api/v1/query",
            json={
                "drug_id": "semaglutide",
                "question_text": "Are there emerging GI motility concerns for semaglutide?",
                "quarter_context": "2023-Q3",
            },
        )
        assert query.status_code == 200
        query_body = query.json()
        assert len(query_body["episodic_context"]) >= 1
        assert query_body["episodic_context"][0]["memory_source"] == "evermemos"
        assert any(item["quarter"] == "2023-Q3" for item in query_body["episodic_context"])
        assert [item["quarter"] for item in query_body["episodic_context"]].count("2023-Q3") == 1
        q3_item = next(item for item in query_body["episodic_context"] if item["quarter"] == "2023-Q3")
        assert q3_item["report_count_ingested"] > 0
        assert len(q3_item["key_signals_mentioned"]) > 0

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        rows = beliefs.json()
        target = next((row for row in rows if row["id"] == query_body["belief_id"]), None)

    assert target is not None
    assert "bulk-2023-q3" in target["episodic_ids_used"]


@pytest.mark.asyncio
async def test_fallback_assessments_are_question_aware_and_rounded(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    from app.main import create_app

    app = create_app(_build_settings(postgres_urls))
    async def _empty_memories(*args, **kwargs):
        return []
    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _empty_memories)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _empty_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        # Advance to 2023-Q3 for richer fallback content.
        while True:
            status = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
            assert status.status_code == 200
            next_quarter = status.json()["next_quarter"]
            if next_quarter in {None, "2023-Q4"}:
                break
            ingest = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
            assert ingest.status_code == 200

        questions = [
            "What is the overall safety profile of semaglutide?",
            "Are there emerging GI motility concerns for semaglutide?",
            "What signals warrant regulatory attention for semaglutide?",
        ]
        answers: list[str] = []
        for question in questions:
            query = await client.post(
                "/api/v1/query",
                json={
                    "drug_id": "semaglutide",
                    "question_text": question,
                    "quarter_context": "2023-Q3",
                },
            )
            assert query.status_code == 200
            answers.append(query.json()["answer_text"])

    assert len(set(answers)) == 3
    assert all("FAERS limitation" in answer for answer in answers)
    assert all("CI " in answer for answer in answers)
    assert all("\u2013" in answer for answer in answers)
    assert all(re.search(r"\d+\.\d{3,}", answer) is None for answer in answers)


@pytest.mark.asyncio
async def test_reinterpretation_ids_and_reason_are_persisted_and_exposed_in_diff(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    from app.main import create_app

    app = create_app(_build_settings(postgres_urls))
    async def _empty_memories(*args, **kwargs):
        return []
    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _empty_memories)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _empty_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        while True:
            status = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
            assert status.status_code == 200
            next_quarter = status.json()["next_quarter"]
            if next_quarter in {None, "2022-Q3"}:
                break
            ingest = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
            assert ingest.status_code == 200

        with psycopg.connect(postgres_urls.psycopg_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id::text, question_hash, created_at
                    FROM beliefs
                    WHERE drug_id='semaglutide'
                      AND cardinality(reinterpreted_report_ids) > 0
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                target = cur.fetchone()

        assert target is not None
        target_id, target_hash, target_created_at = target

        beliefs = await client.get("/api/v1/beliefs/semaglutide")
        assert beliefs.status_code == 200
        belief_rows = beliefs.json()
        lineage_rows = [
            row
            for row in belief_rows
            if row["question_hash"] == target_hash and row["created_at"] < target_created_at.isoformat().replace("+00:00", "Z")
        ]
        lineage_rows = sorted(lineage_rows, key=lambda row: row["created_at"])
        assert lineage_rows

        diff = await client.get(
            "/api/v1/beliefs/semaglutide/diff",
            params={"before_id": lineage_rows[-1]["id"], "after_id": target_id},
        )
        assert diff.status_code == 200
        diff_body = diff.json()
        assert len(diff_body["reinterpreted_report_ids"]) > 0

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT reinterpretation_reason
                FROM beliefs
                WHERE drug_id='semaglutide'
                  AND cardinality(reinterpreted_report_ids) > 0
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()

    assert row is not None
    reason_payload = row[0]
    assert isinstance(reason_payload, dict)
    assert isinstance(reason_payload.get("reason"), str)
    assert "newly detected" in reason_payload.get("reason", "").lower()


@pytest.mark.asyncio
async def test_diff_unions_reinterpretation_ids_across_comparison_window(
    postgres_urls,
    reset_database,
    monkeypatch,
) -> None:
    from app.main import create_app

    app = create_app(_build_settings(postgres_urls))

    async def _empty_memories(*args, **kwargs):
        return []

    monkeypatch.setattr(app.state.evermemos_client, "search_memories", _empty_memories)
    monkeypatch.setattr(app.state.evermemos_client, "fetch_episodic_memories", _empty_memories)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed = await client.post(
            "/api/v1/admin/seed-demo",
            json={
                "drug_ids": ["semaglutide", "metformin"],
                "preload_quarters": ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"],
            },
        )
        assert seed.status_code == 200

        while True:
            status = await client.get("/api/v1/ingest/status", params={"drug_id": "semaglutide"})
            assert status.status_code == 200
            next_quarter = status.json()["next_quarter"]
            if next_quarter is None:
                break
            ingest = await client.post("/api/v1/ingest/next-quarter", json={"drug_id": "semaglutide"})
            assert ingest.status_code == 200

        with psycopg.connect(postgres_urls.psycopg_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      id::text,
                      question_hash,
                      quarter_context,
                      cardinality(reinterpreted_report_ids) AS reinterpret_count,
                      reinterpreted_report_ids
                    FROM beliefs
                    WHERE drug_id='semaglutide'
                    ORDER BY question_hash, created_at
                    """
                )
                rows = cur.fetchall()

        grouped: dict[str, list[tuple[str, str, int, list[str]]]] = {}
        for belief_id, question_hash, quarter_context, reinterpret_count, reinterpret_ids in rows:
            grouped.setdefault(question_hash, []).append(
                (belief_id, quarter_context, int(reinterpret_count or 0), list(reinterpret_ids or [])),
            )

        candidate: tuple[str, str, list[str], int] | None = None
        for lineage in grouped.values():
            if len(lineage) < 2:
                continue
            latest = lineage[-1]
            if latest[2] != 0:
                continue

            union_ids: list[str] = []
            for _, _, _, ids in lineage:
                for report_id in ids:
                    if report_id not in union_ids:
                        union_ids.append(report_id)
            if not union_ids:
                continue

            candidate = (lineage[0][0], latest[0], union_ids, latest[2])
            break

        assert candidate is not None
        before_id, after_id, expected_union_ids, latest_count = candidate
        assert latest_count == 0

        diff = await client.get(
            "/api/v1/beliefs/semaglutide/diff",
            params={"before_id": before_id, "after_id": after_id},
        )
        assert diff.status_code == 200
        diff_body = diff.json()
        assert diff_body["after"]["id"] == after_id
        assert len(diff_body["reinterpreted_report_ids"]) > 0
        assert diff_body["reinterpreted_report_ids"] == expected_union_ids
