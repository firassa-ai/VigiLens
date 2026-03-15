from __future__ import annotations

import asyncio
from calendar import monthrange
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    Belief,
    Drug,
    EvermemosMemoryCache,
    EvermemosRequest,
    FaersReport,
    FaersReportDrug,
    IngestionState,
    Prediction,
    QuarterlyStat,
    SituationAnalysis,
)
from app.schemas.tracking import OnboardDrugResponse
from app.services.belief_engine import generate_tracked_beliefs_for_quarter
from app.services.demo_seed import SeedDrugRow, SeedReportRow, _repair_null_drug_ids_for_known_aliases, _upsert_report
from app.services.evermemos_schema import ensure_evermemos_tables
from app.services.drug_insights_service import sync_seed_memories_after_commit
from app.services.ingest_progress_hub import IngestProgressHub
from app.services.ingestion_service import ingest_next_quarter
from app.services.evermemos_client import EvermemosClient
from app.services.prediction_engine import maybe_generate_predictions
from app.services.signal_engine import recompute_signals_after_ingestion
from app.utils.quarters import sort_quarters

_START_COMPACT = "20180101"
_END_COMPACT = "20231231"
_OPENFDA_PAGE_LIMIT = 100
_OPENFDA_FULL_HISTORY_PAGE_LIMIT = 1000
_OPENFDA_SKIP_CEILING = 25_000
_FETCH_PROGRESS_MIN = 12
_FETCH_PROGRESS_MAX = 54
_ROLE_BY_CODE = {
    "1": "suspect",
    "2": "suspect",
    "3": "concomitant",
    "4": "interacting",
}
_SEX_MAP = {
    "1": "male",
    "2": "female",
    "male": "male",
    "female": "female",
}
_OUTCOME_FLAGS = {
    "seriousnessdeath": "death",
    "seriousnesshospitalization": "hospitalization",
    "seriousnesslifethreatening": "life_threatening",
    "seriousnessdisabling": "disabling",
    "seriousnesscongenitalanomali": "congenital_anomaly",
    "seriousnessother": "other_serious",
}
_SEARCH_FIELD_BY_STRATEGY = {
    "generic": "patient.drug.openfda.generic_name",
    "brand": "patient.drug.openfda.brand_name",
    "medicinalproduct": "patient.drug.medicinalproduct",
}


@dataclass(slots=True)
class ResolvedDrugIdentity:
    drug_id: str
    generic_name: str
    brand_names: list[str] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)
    existing_drug: Drug | None = None


@dataclass(slots=True)
class LiveIdentityProbeResult:
    identity: ResolvedDrugIdentity
    rows: list[tuple[SeedReportRow, dict[str, Any]]]
    strategy: str


OnboardingProgressCallback = Callable[[str, int, dict[str, Any] | None], Awaitable[None]]


async def _emit_progress(
    callback: OnboardingProgressCallback | None,
    *,
    step: str,
    progress: int,
    details: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    await callback(step, progress, details)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_drug_id(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "drug"


def _normalize_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _sorted_unique_names(values: list[str]) -> list[str]:
    deduped: dict[str, str] = {}
    for value in values:
        cleaned = _clean_name(value)
        if not cleaned:
            continue
        deduped.setdefault(cleaned.casefold(), cleaned)
    return sorted(deduped.values(), key=str.casefold)


def _merge_brand_names(
    *,
    existing: list[str],
    incoming: list[str],
    generic_name: str,
) -> list[str]:
    generic_norm = _normalize_name(generic_name)
    deduped: dict[str, str] = {}
    for value in [*existing, *incoming]:
        cleaned = _clean_name(value)
        if not cleaned:
            continue
        if _normalize_name(cleaned) == generic_norm:
            continue
        deduped.setdefault(cleaned.casefold(), cleaned)
    return sorted(deduped.values(), key=str.casefold)


def _normalize_sex(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _SEX_MAP.get(text, "unknown")


def _normalize_age(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        age = float(value)
    except Exception:
        return None
    return age if 0 <= age <= 120 else None


def _compact_to_iso(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("missing receivedate")
    if re.fullmatch(r"\d{8}", cleaned):
        return f"{cleaned[0:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned
    raise ValueError(f"invalid receivedate '{value}'")


def _openfda_names(item: dict[str, Any], key: str) -> list[str]:
    openfda = item.get("openfda")
    if not isinstance(openfda, dict):
        return []
    value = openfda.get(key)
    if not isinstance(value, list):
        return []
    return [_clean_name(entry) for entry in value if _clean_name(entry)]


def _medicinalproduct_name(item: dict[str, Any]) -> str:
    return _clean_name(item.get("medicinalproduct"))


def _drug_display_name(item: dict[str, Any]) -> str:
    medicinal = _medicinalproduct_name(item)
    if medicinal:
        return medicinal
    brand_names = _openfda_names(item, "brand_name")
    if brand_names:
        return brand_names[0]
    generic_names = _openfda_names(item, "generic_name")
    if generic_names:
        return generic_names[0]
    return "UNKNOWN"


def _matches_query_value(
    item: dict[str, Any],
    *,
    query_value: str,
    strategy: str,
) -> bool:
    normalized_query = _normalize_name(query_value)
    if not normalized_query:
        return False

    medicinal = _normalize_name(_medicinalproduct_name(item))
    generic_names = {_normalize_name(value) for value in _openfda_names(item, "generic_name")}
    brand_names = {_normalize_name(value) for value in _openfda_names(item, "brand_name")}

    if strategy == "generic":
        return normalized_query in generic_names or bool(medicinal and normalized_query in medicinal)
    if strategy == "brand":
        return normalized_query in brand_names or bool(medicinal and normalized_query in medicinal)
    return bool(medicinal) and normalized_query in medicinal


def _matches_aliases(item: dict[str, Any], aliases: set[str]) -> bool:
    normalized_aliases = {alias for alias in aliases if alias}
    if not normalized_aliases:
        return False

    medicinal = _normalize_name(_medicinalproduct_name(item))
    generic_names = {_normalize_name(value) for value in _openfda_names(item, "generic_name")}
    brand_names = {_normalize_name(value) for value in _openfda_names(item, "brand_name")}

    if generic_names & normalized_aliases:
        return True
    if brand_names & normalized_aliases:
        return True
    if medicinal and any(alias in medicinal for alias in normalized_aliases):
        return True
    return False


def _iter_month_windows(
    *,
    start_compact: str = _START_COMPACT,
    end_compact: str = _END_COMPACT,
) -> list[tuple[str, str]]:
    start = date(int(start_compact[:4]), int(start_compact[4:6]), int(start_compact[6:8]))
    end = date(int(end_compact[:4]), int(end_compact[4:6]), int(end_compact[6:8]))

    windows: list[tuple[str, str]] = []
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        month_start = date(year, month, 1)
        month_end = date(year, month, monthrange(year, month)[1])
        windows.append(
            (
                max(month_start, start).strftime("%Y%m%d"),
                min(month_end, end).strftime("%Y%m%d"),
            )
        )
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return windows


def _build_openfda_search_expr(
    *,
    strategy: str,
    search_value: str,
    window_start: str,
    window_end: str,
) -> str:
    field = _SEARCH_FIELD_BY_STRATEGY[strategy]
    escaped = search_value.strip().replace('"', '\\"')
    return f'{field}:"{escaped}" AND receivedate:[{window_start} TO {window_end}]'


def _with_openfda_api_key(url: str, api_key: str | None) -> str:
    if not api_key:
        return url

    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == "api_key" for key, _ in query_items):
        return url

    query_items.append(("api_key", api_key))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items),
            parsed.fragment,
        )
    )


def _window_label(window_start: str) -> str:
    return f"{window_start[0:4]}-{window_start[4:6]}"


def _fetch_progress_value(
    *,
    window_index: int,
    total_windows: int,
    pages_fetched: int,
    window_complete: bool,
) -> int:
    if total_windows <= 0:
        return 35

    completed_windows = max(0, window_index - 1)
    if window_complete:
        units_complete = completed_windows + 1
    else:
        page_fraction = 0.0 if pages_fetched <= 0 else pages_fetched / (pages_fetched + 1)
        units_complete = completed_windows + page_fraction

    fraction_complete = min(1.0, max(0.0, units_complete / total_windows))
    span = _FETCH_PROGRESS_MAX - _FETCH_PROGRESS_MIN
    progress = _FETCH_PROGRESS_MIN + round(span * fraction_complete)
    return max(_FETCH_PROGRESS_MIN, min(_FETCH_PROGRESS_MAX, int(progress)))


def _fetch_progress_details(
    *,
    search_strategy: str,
    search_value: str,
    window_index: int,
    total_windows: int,
    window_start: str,
    window_end: str,
    pages_fetched: int,
    provider_rows_seen: int,
    matched_reports: int,
    window_complete: bool,
) -> dict[str, Any]:
    label = _window_label(window_start)
    action = "Processed" if window_complete else "Fetching"
    page_suffix = "" if window_complete else f", page {pages_fetched}"
    status_message = (
        f"{action} month {window_index}/{total_windows} ({label}){page_suffix}; "
        f"{matched_reports} matched reports so far"
    )
    return {
        "search_strategy": search_strategy,
        "search_value": search_value,
        "window_index": window_index,
        "window_total": total_windows,
        "window_label": label,
        "window_start": window_start,
        "window_end": window_end,
        "pages_fetched": pages_fetched,
        "provider_rows_seen": provider_rows_seen,
        "matched_reports": matched_reports,
        "window_complete": window_complete,
        "status_message": status_message,
    }


def _openfda_timeout_error_message(search_value: str) -> str:
    return (
        f"openFDA timed out while fetching FAERS history for '{search_value}'. "
        "Retry the rebuild in a minute. API key recommended for large live pulls."
    )


def _should_retry_openfda_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException, httpx.NetworkError))


async def _openfda_get(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    url: str,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    max_retries = max(0, int(settings.openfda_retry_attempts))
    backoff = max(0.0, float(settings.openfda_retry_backoff_seconds))
    attempt = 0

    while True:
        try:
            response = await client.get(url, params=params)
            if response.status_code != 404:
                response.raise_for_status()
            return response
        except Exception as exc:
            if attempt < max_retries and _should_retry_openfda_error(exc):
                delay = backoff * (2**attempt)
                attempt += 1
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            raise


def _identity_from_existing_drug(existing_drug: Drug) -> ResolvedDrugIdentity:
    generic_name = _normalize_name(existing_drug.generic_name) or existing_drug.id
    brand_names = _sorted_unique_names(list(existing_drug.brand_names or []))
    aliases = {
        _normalize_name(existing_drug.id),
        _normalize_name(existing_drug.generic_name),
        *(_normalize_name(name) for name in brand_names),
    }
    return ResolvedDrugIdentity(
        drug_id=existing_drug.id,
        generic_name=generic_name,
        brand_names=brand_names,
        aliases={alias for alias in aliases if alias},
        existing_drug=existing_drug,
    )


def _provisional_identity(medication_name: str) -> ResolvedDrugIdentity:
    generic_name = _normalize_name(medication_name)
    return ResolvedDrugIdentity(
        drug_id=_normalize_drug_id(medication_name),
        generic_name=generic_name,
        brand_names=[],
        aliases={generic_name} if generic_name else set(),
        existing_drug=None,
    )


def _resolve_identity_from_live_rows(
    rows: list[tuple[SeedReportRow, dict[str, Any]]],
    *,
    query_value: str,
    strategy: str,
    existing_drug: Drug | None = None,
) -> ResolvedDrugIdentity:
    generic_counts: Counter[str] = Counter()
    found_brands: list[str] = []

    for _, raw_payload in rows:
        patient = raw_payload.get("patient")
        if not isinstance(patient, dict):
            continue
        patient_drugs = patient.get("drug")
        if not isinstance(patient_drugs, list):
            continue
        for item in patient_drugs:
            if not isinstance(item, dict):
                continue
            if not _matches_query_value(item, query_value=query_value, strategy=strategy):
                continue
            for generic_name in _openfda_names(item, "generic_name"):
                generic_counts[_normalize_name(generic_name)] += 1
            found_brands.extend(_openfda_names(item, "brand_name"))

    if existing_drug is not None:
        generic_name = _normalize_name(existing_drug.generic_name) or existing_drug.id
        drug_id = existing_drug.id
        existing_brands = list(existing_drug.brand_names or [])
    elif generic_counts:
        generic_name = sorted(
            generic_counts.items(),
            key=lambda entry: (-entry[1], entry[0]),
        )[0][0]
        drug_id = _normalize_drug_id(generic_name)
        existing_brands = []
    else:
        generic_name = _normalize_name(query_value)
        drug_id = _normalize_drug_id(generic_name)
        existing_brands = []

    brand_names = _merge_brand_names(
        existing=existing_brands,
        incoming=found_brands,
        generic_name=generic_name,
    )
    aliases = {
        _normalize_name(query_value),
        _normalize_name(generic_name),
        *(_normalize_name(name) for name in brand_names),
    }
    return ResolvedDrugIdentity(
        drug_id=drug_id,
        generic_name=generic_name,
        brand_names=brand_names,
        aliases={alias for alias in aliases if alias},
        existing_drug=existing_drug,
    )


def _merge_identity_brands(
    identity: ResolvedDrugIdentity,
    rows: list[tuple[SeedReportRow, dict[str, Any]]],
) -> ResolvedDrugIdentity:
    found_brands: list[str] = []
    for _, raw_payload in rows:
        patient = raw_payload.get("patient")
        if not isinstance(patient, dict):
            continue
        patient_drugs = patient.get("drug")
        if not isinstance(patient_drugs, list):
            continue
        for item in patient_drugs:
            if not isinstance(item, dict):
                continue
            if _matches_aliases(item, identity.aliases):
                found_brands.extend(_openfda_names(item, "brand_name"))

    brand_names = _merge_brand_names(
        existing=identity.brand_names,
        incoming=found_brands,
        generic_name=identity.generic_name,
    )
    aliases = {
        _normalize_name(identity.drug_id),
        _normalize_name(identity.generic_name),
        *(_normalize_name(name) for name in brand_names),
    }
    return ResolvedDrugIdentity(
        drug_id=identity.drug_id,
        generic_name=identity.generic_name,
        brand_names=brand_names,
        aliases={alias for alias in aliases if alias},
        existing_drug=identity.existing_drug,
    )


def _extract_drug_rows(
    patient_drugs: list[dict[str, Any]],
    *,
    target_drug_id: str,
    match_aliases: set[str],
) -> list[SeedDrugRow]:
    out: list[SeedDrugRow] = []
    for item in patient_drugs:
        if not isinstance(item, dict):
            continue
        role_code = str(item.get("drugcharacterization") or "").strip()
        role = _ROLE_BY_CODE.get(role_code, "unknown")
        out.append(
            SeedDrugRow(
                drug_id=target_drug_id
                if role == "suspect" and _matches_aliases(item, match_aliases)
                else None,
                drug_name=_drug_display_name(item),
                role=role,
            )
        )
    return out


def _extract_reactions(patient: dict[str, Any]) -> list[str]:
    reactions = patient.get("reaction")
    if not isinstance(reactions, list):
        return []
    out: list[str] = []
    for row in reactions:
        if not isinstance(row, dict):
            continue
        term = _clean_name(row.get("reactionmeddrapt"))
        if term:
            out.append(term)
    return sorted(set(out))


def _extract_outcomes(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key, label in _OUTCOME_FLAGS.items():
        if str(payload.get(key) or "").strip() == "1":
            out.append(label)
    return sorted(set(out))


def _parse_openfda_result(
    payload: dict[str, Any],
    *,
    target_drug_id: str,
    match_aliases: set[str],
) -> tuple[SeedReportRow, dict[str, Any]] | None:
    safetyreportid = str(payload.get("safetyreportid") or "").strip()
    if not safetyreportid:
        return None

    try:
        receivedate = _compact_to_iso(str(payload.get("receivedate") or ""))
    except ValueError:
        return None

    patient = payload.get("patient")
    if not isinstance(patient, dict):
        return None

    reactions = _extract_reactions(patient)
    if not reactions:
        return None

    drug_rows = _extract_drug_rows(
        patient.get("drug") if isinstance(patient.get("drug"), list) else [],
        target_drug_id=target_drug_id,
        match_aliases=match_aliases,
    )
    if not any(row.role == "suspect" and row.drug_id == target_drug_id for row in drug_rows):
        return None

    try:
        version = int(str(payload.get("safetyreportversion") or "1"))
    except ValueError:
        version = 1

    report = SeedReportRow(
        safetyreportid=safetyreportid,
        version=version,
        receivedate=receivedate,
        patient_sex=_normalize_sex(patient.get("patientsex")),
        patient_age=_normalize_age(patient.get("patientonsetage")),
        reactions=reactions,
        drugs=drug_rows,
        serious=str(payload.get("serious") or "0").strip() in {"1", "true", "True"},
        outcomes=_extract_outcomes(payload),
        is_duplicate=False,
    )
    return report, payload


async def _fetch_openfda_rows(
    *,
    settings: Settings,
    search_strategy: str,
    search_value: str,
    target_drug_id: str,
    match_aliases: set[str],
    max_reports: int | None,
    progress_callback: OnboardingProgressCallback | None = None,
) -> list[tuple[SeedReportRow, dict[str, Any]]]:
    rows: dict[str, tuple[SeedReportRow, dict[str, Any]]] = {}
    provider_rows_seen = 0

    try:
        async with httpx.AsyncClient(timeout=settings.openfda_timeout_seconds) as client:
            windows = _iter_month_windows()
            total_windows = len(windows)
            for window_index, (window_start, window_end) in enumerate(windows, start=1):
                if max_reports is not None and len(rows) >= max_reports:
                    break

                search_expr = _build_openfda_search_expr(
                    strategy=search_strategy,
                    search_value=search_value,
                    window_start=window_start,
                    window_end=window_end,
                )
                if max_reports is None:
                    params = {
                        "search": search_expr,
                        "limit": str(_OPENFDA_FULL_HISTORY_PAGE_LIMIT),
                        "sort": "receivedate:asc",
                    }
                    if settings.openfda_api_key:
                        params["api_key"] = settings.openfda_api_key

                    next_url: str | None = None
                    pages_fetched = 0
                    while True:
                        if next_url is None:
                            response = await _openfda_get(
                                client=client,
                                settings=settings,
                                url=settings.openfda_api_base_url,
                                params=params,
                            )
                        else:
                            response = await _openfda_get(
                                client=client,
                                settings=settings,
                                url=_with_openfda_api_key(next_url, settings.openfda_api_key),
                            )
                        if response.status_code == 404:
                            break
                        payload = response.json()

                        result_rows = payload.get("results")
                        if not isinstance(result_rows, list) or not result_rows:
                            break
                        pages_fetched += 1
                        provider_rows_seen += len(result_rows)

                        for item in result_rows:
                            if not isinstance(item, dict):
                                continue
                            parsed = _parse_openfda_result(
                                item,
                                target_drug_id=target_drug_id,
                                match_aliases=match_aliases,
                            )
                            if parsed is None:
                                continue
                            report, raw_payload = parsed
                            current = rows.get(report.safetyreportid)
                            if current is None or report.version >= current[0].version:
                                rows[report.safetyreportid] = (report, raw_payload)

                        await _emit_progress(
                            progress_callback,
                            step="fetching_faers",
                            progress=_fetch_progress_value(
                                window_index=window_index,
                                total_windows=total_windows,
                                pages_fetched=pages_fetched,
                                window_complete=False,
                            ),
                            details=_fetch_progress_details(
                                search_strategy=search_strategy,
                                search_value=search_value,
                                window_index=window_index,
                                total_windows=total_windows,
                                window_start=window_start,
                                window_end=window_end,
                                pages_fetched=pages_fetched,
                                provider_rows_seen=provider_rows_seen,
                                matched_reports=len(rows),
                                window_complete=False,
                            ),
                        )

                        next_link = response.links.get("next")
                        next_url = next_link.get("url") if next_link is not None else None
                        if not next_url:
                            break
                    await _emit_progress(
                        progress_callback,
                        step="fetching_faers",
                        progress=_fetch_progress_value(
                            window_index=window_index,
                            total_windows=total_windows,
                            pages_fetched=max(1, pages_fetched),
                            window_complete=True,
                        ),
                        details=_fetch_progress_details(
                            search_strategy=search_strategy,
                            search_value=search_value,
                            window_index=window_index,
                            total_windows=total_windows,
                            window_start=window_start,
                            window_end=window_end,
                            pages_fetched=pages_fetched,
                            provider_rows_seen=provider_rows_seen,
                            matched_reports=len(rows),
                            window_complete=True,
                        ),
                    )
                    continue

                skip = 0
                pages_fetched = 0
                while len(rows) < max_reports:
                    remaining = max_reports - len(rows)
                    limit = min(_OPENFDA_PAGE_LIMIT, remaining)
                    params = {
                        "search": search_expr,
                        "limit": str(limit),
                        "skip": str(skip),
                    }
                    if settings.openfda_api_key:
                        params["api_key"] = settings.openfda_api_key

                    response = await _openfda_get(
                        client=client,
                        settings=settings,
                        url=settings.openfda_api_base_url,
                        params=params,
                    )
                    if response.status_code == 404:
                        break
                    payload = response.json()

                    result_rows = payload.get("results")
                    if not isinstance(result_rows, list) or not result_rows:
                        break
                    pages_fetched += 1
                    provider_rows_seen += len(result_rows)

                    for item in result_rows:
                        if not isinstance(item, dict):
                            continue
                        parsed = _parse_openfda_result(
                            item,
                            target_drug_id=target_drug_id,
                            match_aliases=match_aliases,
                        )
                        if parsed is None:
                            continue
                        report, raw_payload = parsed
                        current = rows.get(report.safetyreportid)
                        if current is None or report.version >= current[0].version:
                            rows[report.safetyreportid] = (report, raw_payload)
                        if len(rows) >= max_reports:
                            break

                    await _emit_progress(
                        progress_callback,
                        step="fetching_faers",
                        progress=_fetch_progress_value(
                            window_index=window_index,
                            total_windows=total_windows,
                            pages_fetched=pages_fetched,
                            window_complete=False,
                        ),
                        details=_fetch_progress_details(
                            search_strategy=search_strategy,
                            search_value=search_value,
                            window_index=window_index,
                            total_windows=total_windows,
                            window_start=window_start,
                            window_end=window_end,
                            pages_fetched=pages_fetched,
                            provider_rows_seen=provider_rows_seen,
                            matched_reports=len(rows),
                            window_complete=False,
                        ),
                    )

                    if len(result_rows) < limit:
                        break
                    skip += len(result_rows)
                    if skip >= _OPENFDA_SKIP_CEILING:
                        break
                await _emit_progress(
                    progress_callback,
                    step="fetching_faers",
                    progress=_fetch_progress_value(
                        window_index=window_index,
                        total_windows=total_windows,
                        pages_fetched=max(1, pages_fetched),
                        window_complete=True,
                    ),
                    details=_fetch_progress_details(
                        search_strategy=search_strategy,
                        search_value=search_value,
                        window_index=window_index,
                        total_windows=total_windows,
                        window_start=window_start,
                        window_end=window_end,
                        pages_fetched=pages_fetched,
                        provider_rows_seen=provider_rows_seen,
                        matched_reports=len(rows),
                        window_complete=True,
                    ),
                )
    except Exception as exc:
        if max_reports is None and isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
            raise AppError(
                error="ProviderTimeout",
                detail=_openfda_timeout_error_message(search_value),
                status_code=504,
            ) from exc
        if max_reports is None:
            raise
        return list(rows.values())

    return list(rows.values())


async def _probe_live_identity(
    *,
    settings: Settings,
    medication_name: str,
    max_reports: int | None,
    progress_callback: OnboardingProgressCallback | None = None,
) -> LiveIdentityProbeResult | None:
    provisional = _provisional_identity(medication_name)
    for strategy in ("generic", "brand", "medicinalproduct"):
        rows = await _fetch_openfda_rows(
            settings=settings,
            search_strategy=strategy,
            search_value=medication_name,
            target_drug_id=provisional.drug_id,
            match_aliases=provisional.aliases,
            max_reports=max_reports,
            progress_callback=progress_callback,
        )
        if not rows:
            continue
        return LiveIdentityProbeResult(
            identity=_resolve_identity_from_live_rows(
                rows,
                query_value=medication_name,
                strategy=strategy,
            ),
            rows=rows,
            strategy=strategy,
        )
    return None


def _search_values_for_strategy(
    *,
    strategy: str,
    medication_name: str,
    identity: ResolvedDrugIdentity,
) -> list[str]:
    if strategy == "generic":
        return [identity.generic_name]
    if strategy == "brand":
        return _sorted_unique_names([*identity.brand_names, medication_name])
    return _sorted_unique_names([medication_name, identity.generic_name])


async def _fetch_live_rows_for_identity(
    *,
    settings: Settings,
    medication_name: str,
    identity: ResolvedDrugIdentity,
    max_reports: int | None,
    progress_callback: OnboardingProgressCallback | None = None,
) -> list[tuple[SeedReportRow, dict[str, Any]]]:
    for strategy in ("generic", "brand", "medicinalproduct"):
        for search_value in _search_values_for_strategy(
            strategy=strategy,
            medication_name=medication_name,
            identity=identity,
        ):
            if not _normalize_name(search_value):
                continue
            rows = await _fetch_openfda_rows(
                settings=settings,
                search_strategy=strategy,
                search_value=search_value,
                target_drug_id=identity.drug_id,
                match_aliases=identity.aliases,
                max_reports=max_reports,
                progress_callback=progress_callback,
            )
            if rows:
                return rows
    return []


def _cache_file_for_drug(drug_id: str) -> Path:
    path = _repo_root() / "data" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{drug_id}.ndjson"


def _packaged_seed_files_for_drug(drug_id: str) -> list[Path]:
    root = _repo_root()
    return [
        root / "data" / "demo" / f"{drug_id}.ndjson",
        root / "data" / "real" / f"{drug_id}.ndjson",
    ]


def _load_cached_rows(cache_path: Path) -> list[tuple[SeedReportRow, dict[str, Any]]]:
    rows: list[tuple[SeedReportRow, dict[str, Any]]] = []
    if not cache_path.exists():
        return rows
    with cache_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            row = SeedReportRow.model_validate(payload)
            rows.append((row, payload))
    return rows


def _rebind_rows_to_identity(
    rows: list[tuple[SeedReportRow, dict[str, Any]]],
    *,
    target_drug_id: str,
) -> list[tuple[SeedReportRow, dict[str, Any]]]:
    rebound: list[tuple[SeedReportRow, dict[str, Any]]] = []
    for report, raw_payload in rows:
        rebound.append(
            (
                report.model_copy(
                    update={
                        "drugs": [
                            SeedDrugRow(
                                drug_id=target_drug_id if drug.drug_id is not None else None,
                                drug_name=drug.drug_name,
                                role=drug.role,
                            )
                            for drug in report.drugs
                        ]
                    }
                ),
                raw_payload,
            )
        )
    return rebound


def _load_cached_rows_for_identity(
    cache_path: Path,
    *,
    identity: ResolvedDrugIdentity,
) -> list[tuple[SeedReportRow, dict[str, Any]]]:
    rows = _load_cached_rows(cache_path)
    if not rows:
        return rows
    return _rebind_rows_to_identity(rows, target_drug_id=identity.drug_id)


def _write_cache_rows(cache_path: Path, rows: list[tuple[SeedReportRow, dict[str, Any]]]) -> None:
    with cache_path.open("w", encoding="utf-8") as handle:
        for report, _ in rows:
            handle.write(json.dumps(report.model_dump(mode="json"), ensure_ascii=True))
            handle.write("\n")


async def _find_existing_drug(db: AsyncSession, medication_name: str, normalized_drug_id: str) -> Drug | None:
    if normalized_drug_id:
        by_id = await db.scalar(select(Drug).where(Drug.id == normalized_drug_id))
        if by_id is not None:
            return by_id

    lowered = _normalize_name(medication_name)
    rows = (await db.execute(select(Drug))).scalars().all()
    for row in rows:
        if _normalize_name(row.generic_name) == lowered:
            return row
        if any(_normalize_name(name) == lowered for name in list(row.brand_names or [])):
            return row
    return None


def _identity_uses_probe_rows(
    *,
    medication_name: str,
    identity: ResolvedDrugIdentity,
    strategy: str,
) -> bool:
    return strategy == "generic" and _normalize_name(medication_name) == _normalize_name(identity.generic_name)


async def _resolve_identity_and_rows(
    *,
    settings: Settings,
    medication_name: str,
    existing_drug: Drug | None,
    max_reports: int | None,
    prefer_cached: bool,
    allow_packaged_seed_fallback: bool = True,
    progress_callback: OnboardingProgressCallback | None = None,
) -> tuple[ResolvedDrugIdentity, list[tuple[SeedReportRow, dict[str, Any]]], str]:
    if existing_drug is not None:
        identity = _identity_from_existing_drug(existing_drug)
    else:
        provisional = _provisional_identity(medication_name)
        provisional_cache_path = _cache_file_for_drug(provisional.drug_id)
        if prefer_cached and provisional_cache_path.exists():
            return provisional, _load_cached_rows_for_identity(provisional_cache_path, identity=provisional), "cache"

        if allow_packaged_seed_fallback:
            for seed_file in _packaged_seed_files_for_drug(provisional.drug_id):
                rows = _load_cached_rows(seed_file)
                if rows:
                    return provisional, _rebind_rows_to_identity(rows, target_drug_id=provisional.drug_id), "cache"

        probe = await _probe_live_identity(
            settings=settings,
            medication_name=medication_name,
            max_reports=max_reports,
            progress_callback=progress_callback,
        )
        if probe is None:
            raise AppError(
                error="BadRequest",
                detail=f"No FAERS reports found for medication '{medication_name}'",
                status_code=400,
            )

        identity = _merge_identity_brands(
            probe.identity,
            _rebind_rows_to_identity(probe.rows, target_drug_id=probe.identity.drug_id),
        )
        canonical_cache_path = _cache_file_for_drug(identity.drug_id)
        if prefer_cached and canonical_cache_path.exists():
            return identity, _load_cached_rows_for_identity(canonical_cache_path, identity=identity), "cache"

        if allow_packaged_seed_fallback:
            for seed_file in _packaged_seed_files_for_drug(identity.drug_id):
                rows = _load_cached_rows(seed_file)
                if rows:
                    return identity, _rebind_rows_to_identity(rows, target_drug_id=identity.drug_id), "cache"

        if _identity_uses_probe_rows(
            medication_name=medication_name,
            identity=identity,
            strategy=probe.strategy,
        ):
            live_rows = _rebind_rows_to_identity(probe.rows, target_drug_id=identity.drug_id)
        else:
            live_rows = await _fetch_live_rows_for_identity(
                settings=settings,
                medication_name=medication_name,
                identity=identity,
                max_reports=max_reports,
                progress_callback=progress_callback,
            )
            if not live_rows:
                live_rows = _rebind_rows_to_identity(probe.rows, target_drug_id=identity.drug_id)

        if not live_rows:
            raise AppError(
                error="BadRequest",
                detail=f"No FAERS reports found for medication '{medication_name}'",
                status_code=400,
            )
        return _merge_identity_brands(identity, live_rows), live_rows, "openfda"

    canonical_cache_path = _cache_file_for_drug(identity.drug_id)
    if prefer_cached and canonical_cache_path.exists():
        return identity, _load_cached_rows_for_identity(canonical_cache_path, identity=identity), "cache"

    if allow_packaged_seed_fallback:
        for seed_file in _packaged_seed_files_for_drug(identity.drug_id):
            rows = _load_cached_rows(seed_file)
            if rows:
                return identity, _rebind_rows_to_identity(rows, target_drug_id=identity.drug_id), "cache"

    live_rows = await _fetch_live_rows_for_identity(
        settings=settings,
        medication_name=medication_name,
        identity=identity,
        max_reports=max_reports,
        progress_callback=progress_callback,
    )
    if not live_rows and prefer_cached and canonical_cache_path.exists():
        return identity, _load_cached_rows_for_identity(canonical_cache_path, identity=identity), "cache"
    if not live_rows:
        raise AppError(
            error="BadRequest",
            detail=f"No FAERS reports found for medication '{medication_name}'",
            status_code=400,
        )
    return _merge_identity_brands(identity, live_rows), live_rows, "openfda"


async def _count_reports_for_drug(db: AsyncSession, drug_id: str) -> int:
    value = await db.scalar(
        select(func.count(func.distinct(FaersReportDrug.safetyreportid))).where(
            FaersReportDrug.drug_id == drug_id,
            FaersReportDrug.role == "suspect",
        )
    )
    return int(value or 0)


async def _available_quarters_for_drug(db: AsyncSession, drug_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(FaersReport.receivedate)
            .select_from(FaersReport)
            .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
            .where(
                FaersReportDrug.drug_id == drug_id,
                FaersReportDrug.role == "suspect",
            )
            .order_by(FaersReport.receivedate.asc())
        )
    ).all()
    quarters = []
    for row in rows:
        month = row.receivedate.month
        quarter = f"{row.receivedate.year}-Q{((month - 1) // 3) + 1}"
        quarters.append(quarter)
    return sort_quarters(sorted(set(quarters)))


async def _clear_rebuild_state(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
) -> None:
    await ensure_evermemos_tables(db)

    try:
        await evermemos_client.delete_group_memories(db, drug_id=drug_id)
    except Exception:
        pass

    await db.execute(delete(QuarterlyStat).where(QuarterlyStat.drug_id == drug_id))
    await db.execute(delete(Belief).where(Belief.drug_id == drug_id))
    await db.execute(delete(Prediction).where(Prediction.drug_id == drug_id))
    await db.execute(delete(SituationAnalysis).where(SituationAnalysis.drug_id == drug_id))
    await db.execute(delete(EvermemosRequest).where(EvermemosRequest.drug_id == drug_id))
    await db.execute(delete(EvermemosMemoryCache).where(EvermemosMemoryCache.drug_id == drug_id))


async def onboard_drug(
    db: AsyncSession,
    *,
    settings: Settings,
    evermemos_client: EvermemosClient,
    medication_name: str,
    baseline_quarters: int,
    max_reports: int | None,
    prefer_cached: bool,
    rebuild_existing: bool = False,
    progress_callback: OnboardingProgressCallback | None = None,
) -> OnboardDrugResponse:
    if not medication_name.strip():
        raise AppError(error="BadRequest", detail="medication_name is required", status_code=400)

    await _emit_progress(progress_callback, step="resolving_identity", progress=10)

    normalized_id = _normalize_drug_id(medication_name)
    existing_drug = await _find_existing_drug(db, medication_name, normalized_id)
    if existing_drug is not None and not rebuild_existing:
        existing_state = await db.scalar(select(IngestionState).where(IngestionState.drug_id == existing_drug.id))
        if existing_state is not None and len(existing_state.quarters_loaded or []) > 0:
            reports_loaded = await _count_reports_for_drug(db, existing_drug.id)
            generic_name = _normalize_name(existing_drug.generic_name) or existing_drug.id
            await _emit_progress(
                progress_callback,
                step="ready",
                progress=100,
                details={
                    "resolved_generic_name": generic_name,
                    "drug_id": existing_drug.id,
                    "source": "existing",
                },
            )
            return OnboardDrugResponse(
                drug_id=existing_drug.id,
                generic_name=generic_name,
                source="existing",
                created=False,
                reports_loaded=reports_loaded,
                baseline_quarters_loaded=sort_quarters(list(existing_state.quarters_loaded or []))[:baseline_quarters],
                next_quarter=existing_state.next_quarter,
                message="Drug already tracked; returning existing baseline.",
            )

    await _emit_progress(
        progress_callback,
        step="fetching_faers",
        progress=_FETCH_PROGRESS_MIN,
        details={"status_message": "Starting live FAERS fetch"},
    )
    identity, rows, source = await _resolve_identity_and_rows(
        settings=settings,
        medication_name=medication_name,
        existing_drug=existing_drug,
        max_reports=max_reports,
        prefer_cached=prefer_cached,
        allow_packaged_seed_fallback=not rebuild_existing,
        progress_callback=progress_callback,
    )

    await _emit_progress(
        progress_callback,
        step="deduping_transforming",
        progress=55,
        details={
            "resolved_generic_name": identity.generic_name,
            "drug_id": identity.drug_id,
            "source": source,
        },
    )

    if source == "openfda":
        _write_cache_rows(_cache_file_for_drug(identity.drug_id), rows)

    description_text = (
        existing_drug.description
        if existing_drug is not None and existing_drug.description
        else f"Onboarded from openFDA for {medication_name.strip()}"
    )
    await _emit_progress(
        progress_callback,
        step="seeding_database",
        progress=70,
        details={
            "resolved_generic_name": identity.generic_name,
            "drug_id": identity.drug_id,
            "source": source,
        },
    )
    await db.execute(
        pg_insert(Drug)
        .values(
            id=identity.drug_id,
            generic_name=identity.generic_name,
            brand_names=identity.brand_names,
            approved_date=None,
            description=description_text,
        )
        .on_conflict_do_update(
            index_elements=[Drug.id],
            set_={
                "generic_name": identity.generic_name,
                "brand_names": identity.brand_names,
                "description": description_text,
            },
        )
    )

    if rebuild_existing:
        await db.execute(
            update(FaersReportDrug)
            .where(FaersReportDrug.drug_id == identity.drug_id)
            .values(drug_id=None)
        )

    for report, raw_payload in rows:
        await _upsert_report(db, report, raw_payload)
    await db.flush()

    if rebuild_existing:
        tracked_drug_ids = list((await db.execute(select(Drug.id))).scalars().all())
        for tracked_drug_id in tracked_drug_ids:
            await _repair_null_drug_ids_for_known_aliases(db, tracked_drug_id)
        await db.flush()

    all_quarters = await _available_quarters_for_drug(db, identity.drug_id)
    if not all_quarters:
        raise AppError(
            error="BadRequest",
            detail=f"No quarter coverage found after onboarding '{medication_name}'",
            status_code=400,
        )

    baseline = all_quarters[:baseline_quarters]
    next_quarter = all_quarters[len(baseline)] if len(all_quarters) > len(baseline) else None

    await _clear_rebuild_state(
        db,
        evermemos_client=evermemos_client,
        drug_id=identity.drug_id,
    )

    if rebuild_existing:
        first_quarter = all_quarters[0] if all_quarters else None
        await db.execute(
            pg_insert(IngestionState)
            .values(
                drug_id=identity.drug_id,
                quarters_loaded=[],
                next_quarter=first_quarter,
                evermemos_status="idle",
            )
            .on_conflict_do_update(
                index_elements=[IngestionState.drug_id],
                set_={
                    "quarters_loaded": [],
                    "next_quarter": first_quarter,
                    "evermemos_status": "idle",
                },
            )
        )
        await db.commit()

        rebuild_hub = IngestProgressHub()
        total_quarters = max(len(all_quarters), 1)
        for index in range(total_quarters):
            progress = min(94, 72 + round(((index + 1) / total_quarters) * 20))
            await _emit_progress(
                progress_callback,
                step="computing_baseline_stats",
                progress=progress,
                details={
                    "resolved_generic_name": identity.generic_name,
                    "drug_id": identity.drug_id,
                    "source": source,
                },
            )
            await ingest_next_quarter(
                db,
                hub=rebuild_hub,
                settings=settings,
                evermemos_client=evermemos_client,
                drug_id=identity.drug_id,
            )

        reports_loaded = await _count_reports_for_drug(db, identity.drug_id)
        await _emit_progress(
            progress_callback,
            step="writing_memory",
            progress=95,
            details={
                "resolved_generic_name": identity.generic_name,
                "drug_id": identity.drug_id,
                "source": source,
            },
        )
        await _emit_progress(
            progress_callback,
            step="ready",
            progress=100,
            details={
                "resolved_generic_name": identity.generic_name,
                "drug_id": identity.drug_id,
                "source": source,
            },
        )
        return OnboardDrugResponse(
            drug_id=identity.drug_id,
            generic_name=identity.generic_name,
            source=source,
            created=False,
            reports_loaded=reports_loaded,
            baseline_quarters_loaded=all_quarters,
            next_quarter=None,
            message=(
                f"Rebuilt {identity.generic_name} from full history with {reports_loaded} reports. "
                f"Analysis reran across {len(all_quarters)} quarters."
            ),
        )

    await db.execute(
        pg_insert(IngestionState)
        .values(
            drug_id=identity.drug_id,
            quarters_loaded=baseline,
            next_quarter=next_quarter,
            evermemos_status="ready" if baseline else "idle",
        )
        .on_conflict_do_update(
            index_elements=[IngestionState.drug_id],
            set_={
                "quarters_loaded": baseline,
                "next_quarter": next_quarter,
                "evermemos_status": "ready" if baseline else "idle",
            },
        )
    )

    await _emit_progress(
        progress_callback,
        step="computing_baseline_stats",
        progress=85,
        details={
            "resolved_generic_name": identity.generic_name,
            "drug_id": identity.drug_id,
            "source": source,
        },
    )
    for quarter in baseline:
        await recompute_signals_after_ingestion(
            db,
            drug_id=identity.drug_id,
            quarter=quarter,
            settings=settings,
        )
        await maybe_generate_predictions(
            db,
            drug_id=identity.drug_id,
            quarter=quarter,
            evermemos_client=evermemos_client,
            settings=settings,
        )

    for quarter in baseline:
        await generate_tracked_beliefs_for_quarter(
            db,
            settings=settings,
            drug_id=identity.drug_id,
            quarter=quarter,
            evermemos_client=evermemos_client,
        )
    await db.commit()

    await _emit_progress(
        progress_callback,
        step="writing_memory",
        progress=95,
        details={
            "resolved_generic_name": identity.generic_name,
            "drug_id": identity.drug_id,
            "source": source,
        },
    )
    await sync_seed_memories_after_commit(
        evermemos_client=evermemos_client,
        drug_id=identity.drug_id,
        quarters=baseline,
    )

    reports_loaded = await _count_reports_for_drug(db, identity.drug_id)
    await _emit_progress(
        progress_callback,
        step="ready",
        progress=100,
        details={
            "resolved_generic_name": identity.generic_name,
            "drug_id": identity.drug_id,
            "source": source,
        },
    )
    return OnboardDrugResponse(
        drug_id=identity.drug_id,
        generic_name=identity.generic_name,
        source=source,
        created=existing_drug is None,
        reports_loaded=reports_loaded,
        baseline_quarters_loaded=baseline,
        next_quarter=next_quarter,
        message=(
            f"Onboarded {medication_name.strip()} as {identity.generic_name} with {reports_loaded} reports. "
            f"Baseline initialized for {len(baseline)} quarters."
        ),
    )
