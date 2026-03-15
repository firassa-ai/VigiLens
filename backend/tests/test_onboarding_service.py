from __future__ import annotations

from pathlib import Path

import httpx
import psycopg
import pytest

from app.core.config import Settings
from app.db.session import get_session_factory
from app.main import create_app
from app.services.demo_seed import SeedDrugRow, SeedReportRow
from app.services.onboarding_service import (
    LiveIdentityProbeResult,
    ResolvedDrugIdentity,
    _clear_rebuild_state,
    _extract_drug_rows,
    _fetch_openfda_rows,
    _load_cached_rows_for_identity,
    _parse_openfda_result,
    _resolve_identity_from_live_rows,
    _write_cache_rows,
)


def _build_settings(postgres_urls) -> Settings:
    return Settings(
        database_url=postgres_urls.sqlalchemy_url,
        demo_mode=True,
        demo_data_dir=Path(__file__).resolve().parents[2] / "data" / "demo",
        evermemos_url="http://127.0.0.1:9",
        evermemos_timeout_seconds=0.01,
    )


def _payload(
    *,
    safetyreportid: str = "1001",
    version: str = "1",
    drugs: list[dict],
    reactions: list[str] | None = None,
    receivedate: str = "20240115",
) -> dict:
    reaction_rows = [{"reactionmeddrapt": value} for value in (reactions or ["Nausea"])]
    return {
        "safetyreportid": safetyreportid,
        "safetyreportversion": version,
        "receivedate": receivedate,
        "serious": "1",
        "seriousnesshospitalization": "1",
        "patient": {
            "patientsex": "2",
            "patientonsetage": "61",
            "reaction": reaction_rows,
            "drug": drugs,
        },
    }


def _drug_row(
    *,
    medicinalproduct: str,
    drugcharacterization: str,
    generic_names: list[str] | None = None,
    brand_names: list[str] | None = None,
) -> dict:
    row: dict[str, object] = {
        "medicinalproduct": medicinalproduct,
        "drugcharacterization": drugcharacterization,
    }
    openfda: dict[str, list[str]] = {}
    if generic_names:
        openfda["generic_name"] = generic_names
    if brand_names:
        openfda["brand_name"] = brand_names
    if openfda:
        row["openfda"] = openfda
    return row


def test_parse_openfda_result_only_marks_matching_suspect_drug() -> None:
    parsed = _parse_openfda_result(
        _payload(
            drugs=[
                _drug_row(
                    medicinalproduct="Ozempic",
                    drugcharacterization="1",
                    generic_names=["semaglutide"],
                    brand_names=["Ozempic"],
                ),
                _drug_row(
                    medicinalproduct="Zoloft",
                    drugcharacterization="1",
                    generic_names=["sertraline"],
                    brand_names=["Zoloft"],
                ),
            ]
        ),
        target_drug_id="semaglutide",
        match_aliases={"semaglutide", "ozempic"},
    )

    assert parsed is not None
    report, _ = parsed
    assert [drug.role for drug in report.drugs] == ["suspect", "suspect"]
    assert [drug.drug_id for drug in report.drugs] == ["semaglutide", None]
    assert report.outcomes == ["hospitalization"]


def test_extract_drug_rows_matches_bulk_script_role_mapping() -> None:
    rows = _extract_drug_rows(
        [
            _drug_row(
                medicinalproduct="Wegovy",
                drugcharacterization="2",
                generic_names=["semaglutide"],
                brand_names=["Wegovy"],
            ),
            _drug_row(
                medicinalproduct="Metformin",
                drugcharacterization="3",
                generic_names=["metformin"],
                brand_names=["Glucophage"],
            ),
            _drug_row(
                medicinalproduct="Ibuprofen",
                drugcharacterization="4",
                generic_names=["ibuprofen"],
                brand_names=["Advil"],
            ),
        ],
        target_drug_id="semaglutide",
        match_aliases={"semaglutide", "wegovy"},
    )

    assert [(row.drug_name, row.role, row.drug_id) for row in rows] == [
        ("Wegovy", "suspect", "semaglutide"),
        ("Metformin", "concomitant", None),
        ("Ibuprofen", "interacting", None),
    ]


def test_resolve_identity_from_live_rows_collects_generic_and_brand_names() -> None:
    live_rows = [
        (
            SeedReportRow(
                safetyreportid="S-1",
                version=1,
                receivedate="2024-01-15",
                patient_sex="female",
                patient_age=61,
                reactions=["Nausea"],
                drugs=[SeedDrugRow(drug_id="ozempic", drug_name="Ozempic", role="suspect")],
                serious=True,
                outcomes=["hospitalization"],
                is_duplicate=False,
            ),
            _payload(
                drugs=[
                    _drug_row(
                        medicinalproduct="Ozempic",
                        drugcharacterization="1",
                        generic_names=["semaglutide"],
                        brand_names=["Ozempic", "Wegovy"],
                    )
                ]
            ),
        )
    ]

    identity = _resolve_identity_from_live_rows(
        live_rows,
        query_value="Ozempic",
        strategy="brand",
    )

    assert identity.drug_id == "semaglutide"
    assert identity.generic_name == "semaglutide"
    assert identity.brand_names == ["Ozempic", "Wegovy"]
    assert {"semaglutide", "ozempic", "wegovy"} <= identity.aliases


@pytest.mark.asyncio
async def test_fetch_openfda_rows_keeps_highest_version(monkeypatch) -> None:
    payload_v1 = _payload(
        safetyreportid="DUP-1",
        version="1",
        drugs=[
            _drug_row(
                medicinalproduct="Ozempic",
                drugcharacterization="1",
                generic_names=["semaglutide"],
                brand_names=["Ozempic"],
            )
        ],
    )
    payload_v2 = _payload(
        safetyreportid="DUP-1",
        version="2",
        drugs=[
            _drug_row(
                medicinalproduct="Ozempic",
                drugcharacterization="1",
                generic_names=["semaglutide"],
                brand_names=["Ozempic"],
            )
        ],
    )

    class _FakeResponse:
        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, _url: str, params: dict[str, str]) -> _FakeResponse:
            assert params["search"].startswith('patient.drug.openfda.generic_name:"semaglutide"')
            return _FakeResponse({"results": [payload_v1, payload_v2]})

    monkeypatch.setattr("app.services.onboarding_service.httpx.AsyncClient", lambda timeout: _FakeClient())
    monkeypatch.setattr("app.services.onboarding_service._iter_month_windows", lambda: [("20240101", "20240131")])

    rows = await _fetch_openfda_rows(
        settings=Settings(openfda_api_base_url="https://example.com"),
        search_strategy="generic",
        search_value="semaglutide",
        target_drug_id="semaglutide",
        match_aliases={"semaglutide", "ozempic"},
        max_reports=10,
    )

    assert len(rows) == 1
    assert rows[0][0].version == 2


@pytest.mark.asyncio
async def test_fetch_openfda_rows_preserves_api_key_on_search_after_pages(monkeypatch) -> None:
    payload_page_1 = _payload(
        safetyreportid="PAGE-1",
        version="1",
        drugs=[
            _drug_row(
                medicinalproduct="Minoxidil",
                drugcharacterization="1",
                generic_names=["minoxidil"],
                brand_names=["Rogaine"],
            )
        ],
        receivedate="20200701",
    )
    payload_page_2 = _payload(
        safetyreportid="PAGE-2",
        version="1",
        drugs=[
            _drug_row(
                medicinalproduct="Minoxidil",
                drugcharacterization="1",
                generic_names=["minoxidil"],
                brand_names=["Rogaine"],
            )
        ],
        receivedate="20200715",
    )

    class _FakeResponse:
        def __init__(self, payload: dict, next_url: str | None = None) -> None:
            self._payload = payload
            self.status_code = 200
            self.links = {"next": {"url": next_url}} if next_url else {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str] | None]] = []

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params: dict[str, str] | None = None) -> _FakeResponse:
            self.calls.append((url, params))
            if params is not None:
                return _FakeResponse(
                    {"results": [payload_page_1]},
                    next_url="https://api.fda.gov/drug/event.json?search=patient.drug.openfda.generic_name%3A%22minoxidil%22&limit=1000&sort=receivedate%3Aasc&skip=0&search_after=0%3D1593561600000%3B1%3D12345",
                )
            return _FakeResponse({"results": [payload_page_2]})

    fake_client = _FakeClient()

    monkeypatch.setattr("app.services.onboarding_service.httpx.AsyncClient", lambda timeout: fake_client)
    monkeypatch.setattr("app.services.onboarding_service._iter_month_windows", lambda: [("20200701", "20200731")])

    rows = await _fetch_openfda_rows(
        settings=Settings(openfda_api_base_url="https://example.com", openfda_api_key="test-key"),
        search_strategy="generic",
        search_value="minoxidil",
        target_drug_id="minoxidil",
        match_aliases={"minoxidil", "rogaine"},
        max_reports=None,
    )

    assert len(rows) == 2
    assert fake_client.calls[0][1] is not None
    assert fake_client.calls[0][1]["api_key"] == "test-key"
    assert "api_key=test-key" in fake_client.calls[1][0]


@pytest.mark.asyncio
async def test_fetch_openfda_rows_emits_granular_fetch_progress(monkeypatch) -> None:
    payload_page_1 = _payload(
        safetyreportid="PAGE-1",
        version="1",
        drugs=[
            _drug_row(
                medicinalproduct="Minoxidil",
                drugcharacterization="1",
                generic_names=["minoxidil"],
                brand_names=["Rogaine"],
            )
        ],
        receivedate="20200701",
    )
    payload_page_2 = _payload(
        safetyreportid="PAGE-2",
        version="1",
        drugs=[
            _drug_row(
                medicinalproduct="Minoxidil",
                drugcharacterization="1",
                generic_names=["minoxidil"],
                brand_names=["Rogaine"],
            )
        ],
        receivedate="20200715",
    )

    class _FakeResponse:
        def __init__(self, payload: dict, next_url: str | None = None) -> None:
            self._payload = payload
            self.status_code = 200
            self.links = {"next": {"url": next_url}} if next_url else {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params: dict[str, str] | None = None) -> _FakeResponse:
            self.calls += 1
            if params is not None:
                return _FakeResponse(
                    {"results": [payload_page_1]},
                    next_url="https://api.fda.gov/drug/event.json?search=patient.drug.openfda.generic_name%3A%22minoxidil%22&limit=1000&sort=receivedate%3Aasc&skip=0&search_after=0%3D1593561600000%3B1%3D12345",
                )
            return _FakeResponse({"results": [payload_page_2]})

    progress_events: list[tuple[int, dict[str, object]]] = []

    async def _capture_progress(step: str, progress: int, details: dict | None) -> None:
        if step != "fetching_faers":
            return
        progress_events.append((progress, dict(details or {})))

    monkeypatch.setattr("app.services.onboarding_service.httpx.AsyncClient", lambda timeout: _FakeClient())
    monkeypatch.setattr("app.services.onboarding_service._iter_month_windows", lambda: [("20200701", "20200731")])

    rows = await _fetch_openfda_rows(
        settings=Settings(openfda_api_base_url="https://example.com", openfda_api_key="test-key"),
        search_strategy="generic",
        search_value="minoxidil",
        target_drug_id="minoxidil",
        match_aliases={"minoxidil", "rogaine"},
        max_reports=None,
        progress_callback=_capture_progress,
    )

    assert len(rows) == 2
    assert [event[0] for event in progress_events] == [33, 40, 54]
    assert progress_events[0][1]["window_index"] == 1
    assert progress_events[1][1]["pages_fetched"] == 2
    assert progress_events[1][1]["matched_reports"] == 2
    assert progress_events[-1][1]["window_complete"] is True


@pytest.mark.asyncio
async def test_fetch_openfda_rows_retries_timeout_then_succeeds(monkeypatch) -> None:
    payload_page_1 = _payload(
        safetyreportid="PAGE-1",
        version="1",
        drugs=[
            _drug_row(
                medicinalproduct="Minoxidil",
                drugcharacterization="1",
                generic_names=["minoxidil"],
                brand_names=["Rogaine"],
            )
        ],
        receivedate="20200701",
    )

    class _FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload
            self.status_code = 200
            self.links = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params: dict[str, str] | None = None) -> _FakeResponse:
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("")
            return _FakeResponse({"results": [payload_page_1]})

    fake_client = _FakeClient()
    monkeypatch.setattr("app.services.onboarding_service.httpx.AsyncClient", lambda timeout: fake_client)
    monkeypatch.setattr("app.services.onboarding_service._iter_month_windows", lambda: [("20200701", "20200731")])
    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("app.services.onboarding_service.asyncio.sleep", _fake_sleep)

    rows = await _fetch_openfda_rows(
        settings=Settings(
            openfda_api_base_url="https://example.com",
            openfda_api_key="test-key",
            openfda_retry_attempts=2,
            openfda_retry_backoff_seconds=0.5,
        ),
        search_strategy="generic",
        search_value="minoxidil",
        target_drug_id="minoxidil",
        match_aliases={"minoxidil", "rogaine"},
        max_reports=None,
    )

    assert len(rows) == 1
    assert fake_client.calls == 2
    assert sleep_calls == [0.5]


def test_cache_rows_round_trip_with_canonical_identity(tmp_path: Path) -> None:
    cache_path = tmp_path / "semaglutide.ndjson"
    rows = [
        (
            SeedReportRow(
                safetyreportid="CACHE-1",
                version=1,
                receivedate="2024-01-15",
                patient_sex="female",
                patient_age=61,
                reactions=["Nausea"],
                drugs=[SeedDrugRow(drug_id="ozempic", drug_name="Ozempic", role="suspect")],
                serious=True,
                outcomes=["hospitalization"],
                is_duplicate=False,
            ),
            {"cached": True},
        )
    ]
    _write_cache_rows(cache_path, rows)

    identity = ResolvedDrugIdentity(
        drug_id="semaglutide",
        generic_name="semaglutide",
        brand_names=["Ozempic"],
        aliases={"semaglutide", "ozempic"},
    )
    loaded = _load_cached_rows_for_identity(cache_path, identity=identity)

    assert len(loaded) == 1
    assert loaded[0][0].drugs[0].drug_id == "semaglutide"


@pytest.mark.asyncio
async def test_clear_rebuild_state_recreates_missing_evermemos_tables(
    postgres_urls,
    reset_database,
) -> None:
    create_app(_build_settings(postgres_urls))

    with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS evermemos_memory_cache;")
            cur.execute("DROP TABLE IF EXISTS evermemos_requests;")

    class _FakeEvermemosClient:
        async def delete_group_memories(self, db, *, drug_id: str) -> bool:
            assert drug_id == "semaglutide"
            return True

    session_factory = get_session_factory()
    async with session_factory() as db:
        await _clear_rebuild_state(
            db,
            evermemos_client=_FakeEvermemosClient(),
            drug_id="semaglutide",
        )
        await db.commit()

    with psycopg.connect(postgres_urls.psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.evermemos_requests');")
            assert cur.fetchone()[0] == "evermemos_requests"
            cur.execute("SELECT to_regclass('public.evermemos_memory_cache');")
            assert cur.fetchone()[0] == "evermemos_memory_cache"
