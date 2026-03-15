from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock

from app.core.config import Settings
import app.services.evermemos_client as evermemos_client_module
from app.services.evermemos_client import EvermemosClient


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://vigilens:vigilens@localhost:5432/vigilens",
        evermemos_url="http://127.0.0.1:1995",
        evermemos_timeout_seconds=0.2,
    )


def test_flatten_grouped_memories_group_filtering() -> None:
    payload = {
        "result": {
            "memories": [
                {
                    "vigl:semaglutide": [
                        {"id": "m1", "group_id": "vigl:semaglutide", "summary": "Digest 2018-Q1"},
                        {"id": "m2", "group_id": "vigl:semaglutide", "atomic_fact": "Quarter Digest 2018-Q2"},
                    ]
                },
                {
                    "vigl:other": [
                        {"id": "m3", "group_id": "vigl:other", "summary": "Other group"}
                    ]
                },
            ]
        }
    }
    flattened = EvermemosClient.flatten_grouped_memories(payload, group_id="vigl:semaglutide")
    assert {item["id"] for item in flattened} == {"m1", "m2"}


def test_extract_memory_text_prefers_episode_over_summary() -> None:
    text = EvermemosClient.extract_memory_text(
        {
            "summary": "Truncated summary text",
            "episode": "Full episode narrative with richer details.",
        }
    )
    assert text == "Full episode narrative with richer details."


@pytest.mark.asyncio
async def test_fetch_episodic_memories_merges_episodic_and_event_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EvermemosClient(_settings())

    async def _fake_request(*args, **kwargs):
        params = kwargs.get("params", {})
        memory_type = params.get("memory_type")
        if memory_type == "episodic_memory":
            return {
                "result": {
                    "memories": [
                        {"id": "ep-1", "group_id": "vigl:semaglutide", "summary": "Digest for 2018-Q1"}
                    ]
                }
            }
        if memory_type == "event_log":
            return {
                "result": {
                    "memories": [
                        {
                            "id": "log-1",
                            "group_id": "vigl:semaglutide",
                            "atomic_fact": "The report titled 'VigiLens Quarter Digest — 2018-Q2' concerns semaglutide.",
                        },
                        {
                            "id": "ep-1",
                            "group_id": "vigl:semaglutide",
                            "atomic_fact": "duplicate id should dedupe",
                        },
                    ]
                }
            }
        return None

    monkeypatch.setattr(client, "_request", _fake_request)
    memories = await client.fetch_episodic_memories(None, drug_id="semaglutide")
    assert {item["id"] for item in memories} == {"ep-1", "log-1"}


@pytest.mark.asyncio
async def test_best_effort_writes_use_auxiliary_session_factory_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed_statements: list[object] = []

    class _UnexpectedNestedTransaction:
        async def __aenter__(self):
            raise AssertionError("request-scoped nested transaction should not be used")

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            del exc_type, exc, tb
            return False

    class _RequestSession:
        def begin_nested(self) -> _UnexpectedNestedTransaction:
            return _UnexpectedNestedTransaction()

    class _WriterSession:
        def begin(self):
            class _BeginContext:
                async def __aenter__(self_inner):
                    return None

                async def __aexit__(self_inner, exc_type, exc, tb) -> bool:
                    del exc_type, exc, tb
                    return False

            return _BeginContext()

        async def execute(self, statement) -> None:
            executed_statements.append(statement)

    class _SessionContext:
        async def __aenter__(self) -> _WriterSession:
            return _WriterSession()

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        evermemos_client_module,
        "get_session_factory",
        lambda: (lambda: _SessionContext()),
    )

    await evermemos_client_module._run_best_effort_write(
        _RequestSession(),
        lambda write_db: write_db.execute("insert into evermemos_memory_cache"),
    )

    assert executed_statements == ["insert into evermemos_memory_cache"]


@pytest.mark.asyncio
async def test_fetch_episodic_memories_pages_event_logs_sequentially_with_inaccurate_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = EvermemosClient(_settings())
    seen_offsets: list[int] = []

    async def _fake_request(*args, **kwargs):
        params = kwargs.get("params", {})
        memory_type = params.get("memory_type")
        offset = int(params.get("offset", 0))
        seen_offsets.append(offset)

        if memory_type == "episodic_memory":
            return {"result": {"memories": [], "has_more": False, "total_count": 1}}

        if memory_type == "event_log":
            if offset == 0:
                return {
                    "result": {
                        "memories": [
                            {
                                "id": "log-q1",
                                "group_id": "vigl:semaglutide",
                                "atomic_fact": "VigiLens Quarter Digest — 2021-Q1",
                            }
                        ],
                        "has_more": True,
                        "total_count": 1,  # intentionally inaccurate
                    }
                }
            if offset == 200:
                return {
                    "result": {
                        "memories": [
                            {
                                "id": "log-q2",
                                "group_id": "vigl:semaglutide",
                                "atomic_fact": "VigiLens Quarter Digest — 2021-Q2",
                            }
                        ],
                        "has_more": False,
                        "total_count": 1,
                    }
                }
            return {"result": {"memories": [], "has_more": False, "total_count": 1}}

        return None

    monkeypatch.setattr(client, "_request", _fake_request)
    memories = await client.fetch_episodic_memories(
        None,
        drug_id="semaglutide",
        target_quarters={"2021-Q1", "2021-Q2"},
    )
    assert {item["id"] for item in memories} == {"log-q1", "log-q2"}
    assert 0 in seen_offsets and 200 in seen_offsets


@pytest.mark.asyncio
async def test_search_memories_uses_event_log_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EvermemosClient(_settings())
    calls: list[str] = []

    async def _fake_request(*args, **kwargs):
        memory_types = (kwargs.get("params") or {}).get("memory_types", "")
        calls.append(memory_types)
        if memory_types == "episodic_memory":
            return {"result": {"memories": []}}
        if memory_types == "event_log":
            return {
                "result": {
                    "memories": [
                        {
                            "vigl:semaglutide": [
                                {
                                    "id": "log-hit-1",
                                    "group_id": "vigl:semaglutide",
                                    "atomic_fact": "VigiLens Quarter Digest — 2023-Q3",
                                }
                            ]
                        }
                    ]
                }
            }
        return None

    monkeypatch.setattr(client, "_request", _fake_request)
    memories = await client.search_memories(None, drug_id="semaglutide", query="2023-Q3 digest", top_k=3)
    assert calls == ["episodic_memory", "event_log"]
    assert [item["id"] for item in memories] == ["log-hit-1"]


@pytest.mark.asyncio
async def test_search_memories_respects_explicit_memory_types(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EvermemosClient(_settings())
    calls: list[str] = []

    async def _fake_request(*args, **kwargs):
        memory_types = (kwargs.get("params") or {}).get("memory_types", "")
        calls.append(memory_types)
        return {
            "result": {
                "memories": [
                    {
                        "vigl:semaglutide": [
                            {
                                "id": "explicit-log",
                                "group_id": "vigl:semaglutide",
                                "atomic_fact": "VigiLens Quarter Digest — 2022-Q4",
                            }
                        ]
                    }
                ]
            }
        }

    monkeypatch.setattr(client, "_request", _fake_request)
    memories = await client.search_memories(
        None,
        drug_id="semaglutide",
        query="2022-Q4 digest",
        top_k=3,
        retrieve_method="keyword",
        memory_types=["event_log"],
    )
    assert calls == ["event_log"]
    assert [item["id"] for item in memories] == ["explicit-log"]


@pytest.mark.asyncio
async def test_store_foresight_memory_rejects_invalid_payload_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = EvermemosClient(_settings())
    request_calls = 0
    log_calls: list[dict[str, object]] = []

    async def _fake_request(*args, **kwargs):
        nonlocal request_calls
        request_calls += 1
        return {"ok": True}

    async def _fake_log_request(*args, **kwargs):
        log_calls.append(kwargs)

    monkeypatch.setattr(client, "_request", _fake_request)
    monkeypatch.setattr(client, "_log_request", _fake_log_request)

    ok = await client.store_foresight_memory(
        None,
        drug_id="semaglutide",
        foresight_data={
            "prediction": "Ileus label_change",
            "confidence": 72,
            "time_range": ["2023-04-01", "2024-04-01"],
            "created_at_quarter": "2023-03",  # invalid quarter token
        },
    )

    assert ok is False
    assert request_calls == 0
    assert log_calls
    assert log_calls[0]["status"] == "failed"
    assert log_calls[0]["response_body"]["error_type"] == "ForesightSchemaError"


@pytest.mark.asyncio
async def test_store_foresight_memory_writes_valid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EvermemosClient(_settings())
    seen_payloads: list[dict[str, object]] = []

    async def _fake_request(*args, **kwargs):
        seen_payloads.append(kwargs.get("json_body", {}))
        return {"ok": True}

    monkeypatch.setattr(client, "_request", _fake_request)

    ok = await client.store_foresight_memory(
        None,
        drug_id="semaglutide",
        foresight_data={
            "prediction": "Ileus label_change",
            "confidence": 72,
            "time_range": ["2023-04-01", "2024-04-01"],
            "created_at_quarter": "2023-Q2",
        },
    )

    assert ok is True
    assert len(seen_payloads) == 1
    body = seen_payloads[0]
    assert body["memory_type"] == "foresight"
    assert body["message_id"] == "vigl_semaglutide_2023Q2_ileus_label_change_foresight"
    assert str(body["message_id"]).endswith("_foresight")


@pytest.mark.asyncio
async def test_request_retries_timeout_before_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EvermemosClient(_settings())
    log_calls: list[dict[str, object]] = []
    sleep_delays: list[float] = []
    attempts = 0

    class _FakeResponse:
        content = b'{"ok": true}'
        text = '{"ok": true}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            del exc_type, exc, tb
            return False

        async def request(self, *args, **kwargs):
            nonlocal attempts
            del args, kwargs
            attempts += 1
            if attempts < 3:
                raise httpx.ReadTimeout("slow write")
            return _FakeResponse()

    async def _fake_log_request(*args, **kwargs):
        del args
        log_calls.append(kwargs)

    async def _fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr(evermemos_client_module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(client, "_cache_memory_objects", AsyncMock())
    monkeypatch.setattr(client, "_log_request", _fake_log_request)
    monkeypatch.setattr(evermemos_client_module.asyncio, "sleep", _fake_sleep)

    payload = await client._request(  # noqa: SLF001 - direct unit test of retry behavior
        None,
        method="POST",
        endpoint="",
        drug_id="semaglutide",
        quarter="2023-Q2",
        json_body={"memory_type": "foresight"},
        timeout_seconds=0.01,
        retry_attempts=2,
        retry_backoff_seconds=0.5,
    )

    assert payload == {"ok": True}
    assert attempts == 3
    assert sleep_delays == [0.5, 1.0]
    assert len(log_calls) == 1
    assert log_calls[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_store_foresight_memory_uses_extended_timeout_and_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = EvermemosClient(
        Settings(
            database_url="postgresql+psycopg://vigilens:vigilens@localhost:5432/vigilens",
            evermemos_url="http://127.0.0.1:1995",
            evermemos_timeout_seconds=0.2,
            evermemos_foresight_timeout_seconds=1.5,
            evermemos_write_retry_attempts=3,
        )
    )
    request_kwargs: list[dict[str, object]] = []

    async def _fake_request(*args, **kwargs):
        del args
        request_kwargs.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(client, "_request", _fake_request)

    ok = await client.store_foresight_memory(
        None,
        drug_id="semaglutide",
        foresight_data={
            "prediction": "Ileus label_change",
            "confidence": 72,
            "time_range": ["2023-04-01", "2024-04-01"],
            "created_at_quarter": "2023-Q2",
        },
    )

    assert ok is True
    assert len(request_kwargs) == 1
    assert request_kwargs[0]["timeout_seconds"] == 1.5
    assert request_kwargs[0]["retry_attempts"] == 3


@pytest.mark.asyncio
async def test_store_event_log_memory_rejects_invalid_payload_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = EvermemosClient(_settings())
    request_calls = 0
    log_calls: list[dict[str, object]] = []

    async def _fake_request(*args, **kwargs):
        nonlocal request_calls
        request_calls += 1
        return {"ok": True}

    async def _fake_log_request(*args, **kwargs):
        log_calls.append(kwargs)

    monkeypatch.setattr(client, "_request", _fake_request)
    monkeypatch.setattr(client, "_log_request", _fake_log_request)

    ok = await client.store_event_log_memory(
        None,
        drug_id="semaglutide",
        quarter="2023-Q2",
        event_log_data={
            "report_id": "S-1001",
            "quarter": "2023-Q2",
            "receivedate": "2023-04-12",
            "reactions": ["Ileus"],
            "suspect_drugs": ["Semaglutide"],
            "serious": True,
            "outcomes": ["hospitalization"],
            "evidence_api_path": "evidence/S-1001",
        },
    )

    assert ok is False
    assert request_calls == 0
    assert log_calls
    assert log_calls[0]["status"] == "failed"
    assert log_calls[0]["response_body"]["error_type"] == "EventLogSchemaError"


@pytest.mark.asyncio
async def test_store_event_log_memory_writes_valid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EvermemosClient(_settings())
    seen_payloads: list[dict[str, object]] = []

    async def _fake_request(*args, **kwargs):
        seen_payloads.append(kwargs.get("json_body", {}))
        return {"ok": True}

    monkeypatch.setattr(client, "_request", _fake_request)

    ok = await client.store_event_log_memory(
        None,
        drug_id="semaglutide",
        quarter="2023-Q2",
        event_log_data={
            "report_id": "S-1001",
            "quarter": "2023-Q2",
            "receivedate": "2023-04-12",
            "reactions": ["Ileus"],
            "suspect_drugs": ["Semaglutide"],
            "concomitant_drugs": ["Metformin"],
            "serious": True,
            "outcomes": ["hospitalization"],
            "evidence_api_path": "/api/v1/evidence/S-1001",
        },
    )

    assert ok is True
    assert len(seen_payloads) == 1
    body = seen_payloads[0]
    assert body["memory_type"] == "event_log"
    assert str(body["message_id"]).endswith("_eventlog")
    assert body["event_log_data"]["evidence_api_path"] == "/api/v1/evidence/S-1001"
    assert "/api/v1/evidence/S-1001" in str(body["atomic_fact"])
