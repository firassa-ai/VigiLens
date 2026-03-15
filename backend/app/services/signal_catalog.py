from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TRACKED_EVENTS
from app.db.models import FaersReportDrug, FaersReportReaction

SignalTermLevel = Literal["pt", "family"]
SignalConsensusTier = Literal["none", "watchlist", "public_signal", "priority_review"]
SignalLabelStatus = Literal["known_label", "label_gap", "unknown"]

TOP_TERM_LIMIT = 8
FAMILY_SUPPORT_TERM_LIMIT = 6
MIN_SUPPORTING_TERM_COUNT = 3
MIN_FAMILY_REPORT_COUNT = 5

NOISE_EXACT_TERMS = {
    "adverse drug reaction",
    "drug ineffective",
    "off label use",
    "product use issue",
    "medication error",
    "wrong technique in product usage process",
    "inappropriate schedule of product administration",
    "incorrect dose administered",
    "occupational exposure to product",
    "product storage error",
    "product quality issue",
    "expired product administered",
    "intentional product misuse",
    "device malfunction",
    "therapeutic response unexpected",
    "product preparation issue",
    "accidental exposure to product",
    "maternal exposure during pregnancy",
}

NOISE_FRAGMENTS = (
    "off label",
    "drug ineffective",
    "product use issue",
    "medication error",
    "wrong technique",
    "device malfunction",
    "occupational exposure",
    "inappropriate schedule",
    "incorrect dose",
    "accidental exposure",
    "product quality",
    "product preparation",
    "device issue",
    "expired product",
    "overdose",
)

KNOWN_LABEL_TERMS_BY_DRUG: dict[str, set[str]] = {
    "minoxidil": {
        "chest pain",
        "palpitations",
        "tachycardia",
        "dizziness",
        "syncope",
        "oedema peripheral",
        "peripheral swelling",
        "weight increased",
        "application site irritation",
        "application site inflammation",
        "application site erythema",
        "application site burning",
        "application site pruritus",
        "application site pain",
        "scalp irritation",
        "scalp redness",
        "scalp pain",
        "pruritus",
        "erythema",
        "burning sensation",
        "contact dermatitis",
        "dermatitis",
        "rash",
        "hypertrichosis",
        "facial hair growth",
        "unwanted facial hair",
        "hair texture abnormal",
    },
    "semaglutide": {
        "nausea",
        "vomiting",
        "diarrhea",
        "constipation",
        "abdominal pain",
        "abdominal distension",
        "ileus",
        "pancreatitis",
    },
    "metformin": {
        "nausea",
        "vomiting",
        "diarrhea",
        "abdominal pain",
        "lactic acidosis",
    },
}

PRIORITY_TERMS = {
    "anaphylactic reaction",
    "anaphylactic shock",
    "angioedema",
    "suicidal ideation",
    "suicide attempt",
    "ileus",
    "gastroparesis",
    "pancreatitis",
    "palpitations",
    "tachycardia",
    "syncope",
    "chest pain",
}


@dataclass(frozen=True)
class FamilyRule:
    key: str
    label: str
    patterns: tuple[str, ...]
    priority: bool = False


@dataclass(frozen=True)
class SignalCatalogEntry:
    adverse_event: str
    term_level: SignalTermLevel
    event_terms: tuple[str, ...]
    family_key: str | None
    family_label: str | None
    label_status: SignalLabelStatus
    priority_flag: bool
    supporting_terms: tuple[str, ...]


FAMILY_RULES: tuple[FamilyRule, ...] = (
    FamilyRule(
        key="application_site_irritation",
        label="Application Site Irritation / Inflammation",
        patterns=(
            "application site",
            "scalp irritation",
            "scalp pain",
            "scalp pruritus",
            "burning sensation",
            "erythema",
        ),
    ),
    FamilyRule(
        key="hypersensitivity_contact_dermatitis",
        label="Hypersensitivity / Contact Dermatitis",
        patterns=(
            "hypersensitivity",
            "contact dermatitis",
            "dermatitis",
            "urticaria",
            "angioedema",
            "allergic",
            "rash",
        ),
        priority=True,
    ),
    FamilyRule(
        key="hair_change_effects",
        label="Hair-Change Effects",
        patterns=(
            "hypertrichosis",
            "hair growth",
            "facial hair",
            "alopecia",
            "hair disorder",
        ),
    ),
    FamilyRule(
        key="systemic_cardiovascular_warning",
        label="Systemic / Cardiovascular Warning",
        patterns=(
            "palpitations",
            "tachycardia",
            "heart rate",
            "chest pain",
            "dizziness",
            "syncope",
            "faint",
            "oedema",
            "edema",
            "swelling",
            "weight increased",
            "weight gain",
            "hypotension",
        ),
        priority=True,
    ),
    FamilyRule(
        key="gi_motility_harm",
        label="GI Motility Harm",
        patterns=(
            "nausea",
            "vomiting",
            "diarrhea",
            "constipation",
            "abdominal distension",
            "abdominal pain",
            "gastroparesis",
            "ileus",
            "decreased gastrointestinal motility",
            "bloating",
        ),
        priority=True,
    ),
    FamilyRule(
        key="pancreatitis_hepatobiliary",
        label="Pancreatitis / Hepatobiliary Injury",
        patterns=(
            "pancreatitis",
            "lipase increased",
            "amylase increased",
            "hepatic",
            "liver injury",
            "cholestasis",
        ),
        priority=True,
    ),
    FamilyRule(
        key="suicidality_neuropsychiatric",
        label="Suicidality / Neuropsychiatric Risk",
        patterns=(
            "suicidal ideation",
            "suicide attempt",
            "depression",
            "anxiety",
            "self injurious",
        ),
        priority=True,
    ),
    FamilyRule(
        key="tendon_neuropathy",
        label="Tendon / Neuropathy Harm",
        patterns=(
            "tendon",
            "neuropathy",
            "paresthesia",
            "peripheral neuropathy",
            "myalgia",
        ),
        priority=True,
    ),
)


def normalize_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def is_noise_term(value: str) -> bool:
    normalized = normalize_term(value)
    if normalized in NOISE_EXACT_TERMS:
        return True
    return any(fragment in normalized for fragment in NOISE_FRAGMENTS)


def _match_family(term: str) -> FamilyRule | None:
    normalized = normalize_term(term)
    for rule in FAMILY_RULES:
        if any(pattern in normalized for pattern in rule.patterns):
            return rule
    return None


def _is_known_label_term(drug_id: str, term: str) -> bool:
    normalized = normalize_term(term)
    return normalized in KNOWN_LABEL_TERMS_BY_DRUG.get(drug_id, set())


def _label_status_for_pt(drug_id: str, term: str, family_rule: FamilyRule | None) -> SignalLabelStatus:
    if _is_known_label_term(drug_id, term):
        return "known_label"
    if family_rule and KNOWN_LABEL_TERMS_BY_DRUG.get(drug_id):
        family_known = any(
            any(pattern in known for pattern in family_rule.patterns)
            for known in KNOWN_LABEL_TERMS_BY_DRUG[drug_id]
        )
        if family_known:
            return "label_gap"
    return "unknown"


def _label_status_for_family(drug_id: str, terms: list[str], family_rule: FamilyRule) -> SignalLabelStatus:
    if not terms:
        return "unknown"
    known_count = sum(1 for term in terms if _is_known_label_term(drug_id, term))
    if known_count == len(terms):
        return "known_label"
    if known_count * 2 >= len(terms):
        return "known_label"
    if known_count > 0:
        return "label_gap"

    family_known = any(
        any(pattern in known for pattern in family_rule.patterns)
        for known in KNOWN_LABEL_TERMS_BY_DRUG.get(drug_id, set())
    )
    return "label_gap" if family_known else "unknown"


def _is_priority_term(term: str, family_rule: FamilyRule | None) -> bool:
    normalized = normalize_term(term)
    return normalized in PRIORITY_TERMS or bool(family_rule and family_rule.priority)


async def fetch_reaction_counts(
    db: AsyncSession,
    *,
    drug_id: str,
    limit: int = 200,
) -> list[tuple[str, int]]:
    rows = (
        (
            await db.execute(
                select(
                    FaersReportReaction.meddra_pt,
                    func.count(func.distinct(FaersReportReaction.safetyreportid)).label("report_count"),
                )
                .join(
                    FaersReportDrug,
                    FaersReportDrug.safetyreportid == FaersReportReaction.safetyreportid,
                )
                .where(
                    FaersReportDrug.drug_id == drug_id,
                    FaersReportDrug.role == "suspect",
                )
                .group_by(FaersReportReaction.meddra_pt)
                .order_by(func.count(func.distinct(FaersReportReaction.safetyreportid)).desc(), FaersReportReaction.meddra_pt.asc())
                .limit(limit)
            )
        )
        .all()
    )
    return [(str(row.meddra_pt), int(row.report_count or 0)) for row in rows]


async def build_signal_catalog(
    db: AsyncSession,
    *,
    drug_id: str,
) -> list[SignalCatalogEntry]:
    raw_counts = await fetch_reaction_counts(db, drug_id=drug_id)
    filtered_counts = [(term, count) for term, count in raw_counts if count > 0 and not is_noise_term(term)]
    if not filtered_counts:
        return []

    selected_terms: list[str] = []
    selected_seen: set[str] = set()
    for term, _ in filtered_counts[:TOP_TERM_LIMIT]:
        selected_terms.append(term)
        selected_seen.add(term)

    for term in TRACKED_EVENTS:
        if term in selected_seen:
            continue
        selected_terms.append(term)
        selected_seen.add(term)

    for term, count in filtered_counts:
        family_rule = _match_family(term)
        if count < MIN_SUPPORTING_TERM_COUNT:
            continue
        if normalize_term(term) not in PRIORITY_TERMS:
            continue
        if term in selected_seen:
            continue
        selected_terms.append(term)
        selected_seen.add(term)

    family_buckets: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for term, count in filtered_counts:
        family_rule = _match_family(term)
        if family_rule is None:
            continue
        family_buckets[family_rule.key].append((term, count))

    catalog: list[SignalCatalogEntry] = []
    for term in selected_terms:
        family_rule = _match_family(term)
        label_status = _label_status_for_pt(drug_id, term, family_rule)
        catalog.append(
            SignalCatalogEntry(
                adverse_event=term,
                term_level="pt",
                event_terms=(term,),
                family_key=family_rule.key if family_rule else None,
                family_label=family_rule.label if family_rule else None,
                label_status=label_status,
                priority_flag=_is_priority_term(term, family_rule),
                supporting_terms=(term,),
            )
        )

    for rule in FAMILY_RULES:
        matched = family_buckets.get(rule.key, [])
        if not matched:
            continue
        matched.sort(key=lambda item: (-item[1], item[0]))
        supporting_terms = [term for term, count in matched if count >= MIN_SUPPORTING_TERM_COUNT][:FAMILY_SUPPORT_TERM_LIMIT]
        total_count = sum(count for term, count in matched if term in supporting_terms)
        if not supporting_terms:
            continue
        if total_count < MIN_FAMILY_REPORT_COUNT and not rule.priority:
            continue
        catalog.append(
            SignalCatalogEntry(
                adverse_event=rule.label,
                term_level="family",
                event_terms=tuple(supporting_terms),
                family_key=rule.key,
                family_label=rule.label,
                label_status=_label_status_for_family(drug_id, supporting_terms, rule),
                priority_flag=rule.priority,
                supporting_terms=tuple(supporting_terms),
            )
        )

    return catalog


def consensus_tier_rank(value: SignalConsensusTier | str | None) -> int:
    if value == "public_signal":
        return 3
    if value == "priority_review":
        return 2
    if value == "watchlist":
        return 1
    return 0
