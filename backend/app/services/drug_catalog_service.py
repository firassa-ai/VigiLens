from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Drug, FaersReportDrug
from app.schemas.catalog import CatalogPreviewResponse, CatalogSearchResult
from app.services.onboarding_service import (
    ResolvedDrugIdentity,
    _build_openfda_search_expr,
    _END_COMPACT,
    _find_existing_drug,
    _identity_from_existing_drug,
    _normalize_drug_id,
    _normalize_name,
    _probe_live_identity,
    _search_values_for_strategy,
    _START_COMPACT,
    _sorted_unique_names,
)

_DOSAGE_TOKEN_RE = re.compile(
    r"\b(?:TABLET|TABLETS|CAPSULE|CAPSULES|INJECTION|INJECTIONS|SOLUTION|SOLUTIONS|SUSPENSION|SUSPENSIONS|CREAM|PATCH|PATCHES|GEL|SPRAY|AEROSOL|SYRUP|LOTION|POWDER|KIT|SOAP|FILM|PEN|AUTO-INJECTOR|AUTOINJECTOR|INHALATION|OINTMENT|EMULSION)\b"
)
_FORMULATION_PREFIX_RE = re.compile(
    r"^(?:ORAL|TOPICAL|INJECTABLE|INTRAVENOUS|OPHTHALMIC|OTIC|NASAL|SUBLINGUAL|TRANSDERMAL|INHALATION)\s+",
)


@dataclass(slots=True)
class DailyMedLabel:
    generic_name: str
    brand_names: list[str]
    setid: str
    title: str
    published_date: str | None


def _display_name(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    if not cleaned:
        return ""
    return cleaned.title()


def _canonical_generic_name(value: str) -> str:
    lowered = _normalize_name(value)
    lowered = _FORMULATION_PREFIX_RE.sub("", lowered)
    return lowered.strip()


def _published_sort_key(value: str | None) -> tuple[int, int, int]:
    if not value:
        return (0, 0, 0)
    try:
        parsed = datetime.strptime(value, "%b %d, %Y")
    except ValueError:
        return (0, 0, 0)
    return (parsed.year, parsed.month, parsed.day)


def _parse_dailymed_title(title: str) -> tuple[str, list[str]]:
    prefix = title.split("[", 1)[0].strip().upper()
    brand_names: list[str] = []
    generic_candidates: list[str] = []

    for match in re.finditer(r"([A-Z0-9][A-Z0-9 /-]{0,80}?)\s*\(([^)]+)\)", prefix):
        raw_brand = match.group(1).strip(" ,;/")
        brand = re.split(_DOSAGE_TOKEN_RE, raw_brand)[-1].strip(" ,;/")
        generic = _canonical_generic_name(match.group(2))
        if generic:
            generic_candidates.append(generic)
        if brand:
            display_brand = _display_name(brand)
            if display_brand:
                brand_names.append(display_brand)

    generic_name = ""
    if generic_candidates:
        counts: dict[str, int] = {}
        for candidate in generic_candidates:
            counts[candidate] = counts.get(candidate, 0) + 1
        generic_name = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    else:
        generic_name = _canonical_generic_name(re.split(_DOSAGE_TOKEN_RE, prefix, maxsplit=1)[0].strip(" ,;/"))

    deduped_brands = [
        brand
        for brand in _sorted_unique_names(brand_names)
        if _normalize_name(brand) != generic_name
    ]
    return generic_name, deduped_brands


async def _search_dailymed_labels(
    *,
    settings: Settings,
    query: str,
) -> list[DailyMedLabel]:
    params = {
        "drug_name": query,
        "name_type": "both",
        "page": "1",
        "page_size": "12",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.dailymed_timeout_seconds) as client:
            response = await client.get(settings.dailymed_api_base_url, params=params)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    labels: dict[str, DailyMedLabel] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        setid = str(row.get("setid") or "").strip()
        if not title or not setid:
            continue
        generic_name, brand_names = _parse_dailymed_title(title)
        if not generic_name:
            generic_name = _canonical_generic_name(query)
        label = DailyMedLabel(
            generic_name=generic_name,
            brand_names=brand_names,
            setid=setid,
            title=title,
            published_date=str(row.get("published_date") or "").strip() or None,
        )
        current = labels.get(label.generic_name)
        if current is None or _published_sort_key(label.published_date) > _published_sort_key(current.published_date):
            labels[label.generic_name] = label
        else:
            labels[label.generic_name] = DailyMedLabel(
                generic_name=current.generic_name,
                brand_names=_sorted_unique_names([*current.brand_names, *label.brand_names]),
                setid=current.setid,
                title=current.title,
                published_date=current.published_date,
            )
    return list(labels.values())


def _merge_brand_names(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        merged.extend(group)
    return _sorted_unique_names(merged)


def _drug_matches_query(drug: Drug, query: str) -> bool:
    normalized = _normalize_name(query)
    if not normalized:
        return False
    if normalized in _normalize_name(drug.id):
        return True
    if normalized in _normalize_name(drug.generic_name):
        return True
    return any(normalized in _normalize_name(name) for name in list(drug.brand_names or []))


def _candidate_matches_query(
    *,
    query: str,
    generic_name: str,
    brand_names: list[str],
) -> tuple[bool, bool]:
    normalized = _normalize_name(query)
    names = [_normalize_name(generic_name), *(_normalize_name(name) for name in brand_names)]
    exact = any(name == normalized for name in names)
    prefix = any(name.startswith(normalized) for name in names)
    return exact, prefix


async def _load_tracked_drugs(db: AsyncSession) -> list[Drug]:
    return (
        (
            await db.execute(
                select(Drug).order_by(Drug.generic_name.asc())
            )
        )
        .scalars()
        .all()
    )


def _match_tracked_drug(
    drugs: list[Drug],
    *,
    generic_name: str,
    brand_names: list[str],
) -> Drug | None:
    aliases = {_normalize_name(generic_name), *(_normalize_name(name) for name in brand_names)}
    for drug in drugs:
        if _normalize_name(drug.id) in aliases or _normalize_name(drug.generic_name) in aliases:
            return drug
        if any(_normalize_name(name) in aliases for name in list(drug.brand_names or [])):
            return drug
    return None


def _build_search_result(
    *,
    generic_name: str,
    brand_names: list[str],
    tracked_drug: Drug | None,
    label_available: bool,
    sources: set[str],
) -> CatalogSearchResult:
    tracked = tracked_drug is not None
    resolved_generic = tracked_drug.generic_name if tracked_drug is not None else generic_name
    merged_brands = _merge_brand_names(
        list(tracked_drug.brand_names or []) if tracked_drug is not None else [],
        brand_names,
    )
    normalized_sources = sorted(
        {source for source in sources if source in {"tracked", "dailymed", "faers"}},
        key=lambda value: ("tracked", "faers", "dailymed").index(value),
    )
    return CatalogSearchResult(
        generic_name=resolved_generic,
        brand_names=merged_brands,
        tracked=tracked,
        tracked_drug_id=tracked_drug.id if tracked_drug is not None else None,
        label_available=label_available,
        sources=normalized_sources or (["tracked", "faers"] if tracked else []),
    )


async def search_catalog(
    db: AsyncSession,
    *,
    settings: Settings,
    query: str,
) -> list[CatalogSearchResult]:
    normalized_query = _normalize_name(query)
    if len(normalized_query) < 2:
        return []

    tracked_drugs = await _load_tracked_drugs(db)
    merged: dict[str, CatalogSearchResult] = {}

    local_hits = [drug for drug in tracked_drugs if _drug_matches_query(drug, normalized_query)]
    for drug in local_hits:
        merged[drug.id] = _build_search_result(
            generic_name=drug.generic_name,
            brand_names=list(drug.brand_names or []),
            tracked_drug=drug,
            label_available=False,
            sources={"tracked", "faers"},
        )

    try:
        dailymed_labels = await _search_dailymed_labels(settings=settings, query=query)
    except Exception:
        dailymed_labels = []

    for label in dailymed_labels:
        tracked_match = _match_tracked_drug(
            tracked_drugs,
            generic_name=label.generic_name,
            brand_names=label.brand_names,
        )
        key = tracked_match.id if tracked_match is not None else label.generic_name or _normalize_drug_id(query)
        existing = merged.get(key)
        sources = set(existing.sources if existing is not None else [])
        sources.add("dailymed")
        if tracked_match is not None:
            sources.update({"tracked", "faers"})
        merged[key] = _build_search_result(
            generic_name=label.generic_name,
            brand_names=_merge_brand_names(
                existing.brand_names if existing is not None else [],
                label.brand_names,
            ),
            tracked_drug=tracked_match,
            label_available=True,
            sources=sources,
        )

    ranked = list(merged.values())
    ranked.sort(
        key=lambda item: (
            0 if item.tracked else 1,
            0 if _candidate_matches_query(query=query, generic_name=item.generic_name, brand_names=item.brand_names)[0] else 1,
            0 if _candidate_matches_query(query=query, generic_name=item.generic_name, brand_names=item.brand_names)[1] else 1,
            item.generic_name,
        )
    )
    return ranked[:10]


async def _preview_faers_identity(
    *,
    settings: Settings,
    name: str,
) -> ResolvedDrugIdentity | None:
    probe = await _probe_live_identity(
        settings=settings,
        medication_name=name,
        max_reports=25,
    )
    if probe is None:
        return None
    return probe.identity


def _extract_total(payload: dict) -> int | None:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    results = meta.get("results")
    if not isinstance(results, dict):
        return None
    total = results.get("total")
    if isinstance(total, int):
        return total
    return None


async def _count_tracked_reports(
    db: AsyncSession,
    *,
    drug_id: str,
) -> int:
    value = await db.scalar(
        select(func.count(func.distinct(FaersReportDrug.safetyreportid))).where(
            FaersReportDrug.drug_id == drug_id,
            FaersReportDrug.role == "suspect",
        )
    )
    return int(value or 0)


async def _fetch_openfda_total(
    *,
    settings: Settings,
    strategy: str,
    search_value: str,
) -> int | None:
    params = {
        "search": _build_openfda_search_expr(
            strategy=strategy,
            search_value=search_value,
            window_start=_START_COMPACT,
            window_end=_END_COMPACT,
        ),
        "limit": "1",
    }
    if settings.openfda_api_key:
        params["api_key"] = settings.openfda_api_key

    try:
        async with httpx.AsyncClient(timeout=settings.openfda_timeout_seconds) as client:
            response = await client.get(settings.openfda_api_base_url, params=params)
        if response.status_code == 404:
            return 0
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    return _extract_total(payload)


async def _estimate_faers_report_count(
    *,
    settings: Settings,
    name: str,
    identity: ResolvedDrugIdentity,
) -> int | None:
    saw_success = False
    for strategy in ("generic", "brand", "medicinalproduct"):
        for search_value in _search_values_for_strategy(
            strategy=strategy,
            medication_name=name,
            identity=identity,
        ):
            if not _normalize_name(search_value):
                continue
            total = await _fetch_openfda_total(
                settings=settings,
                strategy=strategy,
                search_value=search_value,
            )
            if total is None:
                continue
            saw_success = True
            if total > 0:
                return total
    return 0 if saw_success else None


async def preview_catalog_candidate(
    db: AsyncSession,
    *,
    settings: Settings,
    name: str,
) -> CatalogPreviewResponse:
    existing_drug = await _find_existing_drug(db, name, _normalize_drug_id(name))
    tracked = existing_drug is not None

    identity: ResolvedDrugIdentity | None = None
    faers_available = tracked
    faers_report_count: int | None = None
    faers_report_count_is_estimate = False
    if existing_drug is not None:
        identity = _identity_from_existing_drug(existing_drug)
        faers_report_count = await _count_tracked_reports(db, drug_id=existing_drug.id)
    else:
        try:
            identity = await _preview_faers_identity(settings=settings, name=name)
        except Exception:
            identity = None
        faers_available = identity is not None
        if identity is not None:
            faers_report_count = await _estimate_faers_report_count(
                settings=settings,
                name=name,
                identity=identity,
            )
            faers_report_count_is_estimate = faers_report_count is not None

    try:
        dailymed_labels = await _search_dailymed_labels(settings=settings, query=name)
    except Exception:
        dailymed_labels = []
    if not dailymed_labels and identity is not None and _normalize_name(identity.generic_name) != _normalize_name(name):
        try:
            dailymed_labels = await _search_dailymed_labels(settings=settings, query=identity.generic_name)
        except Exception:
            dailymed_labels = []

    label = dailymed_labels[0] if dailymed_labels else None

    generic_name = (
        identity.generic_name
        if identity is not None and identity.generic_name
        else label.generic_name
        if label is not None
        else _normalize_name(name)
    )
    brand_names = _merge_brand_names(
        list(existing_drug.brand_names or []) if existing_drug is not None else [],
        identity.brand_names if identity is not None else [],
        label.brand_names if label is not None else [],
    )

    return CatalogPreviewResponse(
        generic_name=generic_name,
        brand_names=brand_names,
        tracked=tracked,
        tracked_drug_id=existing_drug.id if existing_drug is not None else None,
        dailymed_setid=label.setid if label is not None else None,
        dailymed_title=label.title if label is not None else None,
        dailymed_published_date=label.published_date if label is not None else None,
        faers_available=faers_available,
        faers_report_count=faers_report_count,
        faers_report_count_is_estimate=faers_report_count_is_estimate,
    )
