from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.constants import TRACKED_EVENTS
from app.core.errors import AppError
from app.db.models import (
    Belief as BeliefRow,
    Drug,
    FaersReport,
    FaersReportDrug,
    FaersReportReaction,
    FdaAction,
    IngestionState,
    Prediction as PredictionRow,
    QuarterlyStat,
)
from app.schemas.query import LLMBeliefPayload
from app.schemas.shared import (
    Belief,
    EpisodicSummary,
    FAERSReport,
    QueryResponse,
    SignalPoint,
)
from app.services.evidence_service import fetch_evidence_reports
from app.services.evermemos_client import EvermemosClient
from app.utils.quarter_extraction import extract_quarters_from_text
from app.utils.quarters import parse_quarter, quarter_minus_one, quarter_to_dates, sort_quarters

TRACKED_QUESTIONS = [
    "What is the overall safety profile of {drug_id}?",
    "Are there emerging GI motility concerns for {drug_id}?",
    "What signals warrant regulatory attention for {drug_id}?",
]

PRECURSOR_MAP: dict[str, list[str]] = {
    "Gastroparesis": [
        "Nausea",
        "Vomiting",
        "Abdominal distension",
        "Early satiety",
        "Bloating",
    ],
    "Ileus": [
        "Constipation",
        "Abdominal pain",
        "Abdominal distension",
        "Decreased gastrointestinal motility",
    ],
}

SYSTEM_PROMPT = """You are VigiLens, a pharmacovigilance signal-detection assistant.

You MUST follow these rules:
1) Do NOT claim causality. FAERS is a spontaneous reporting database.
2) Do NOT estimate incidence or risk rates. You may discuss disproportionality signals (ROR/PRR) only.
3) Always include a one-sentence FAERS limitation disclaimer at the end.
4) Only use the provided evidence and signal statistics. If data is missing, say so.
5) When citing evidence, cite by FAERS safetyreportid only (no patient-identifying info).

Return JSON only, matching the schema exactly.
"""

DISCLAIMER_SENTENCE = (
    "FAERS limitation: spontaneous reports are unverified, can include under-reporting and duplicates, "
    "and cannot establish causality or incidence."
)


@dataclass(frozen=True)
class BeliefGenerationTrace:
    episodic_ids_used: list[str]
    episodic_snippets: dict[str, str]
    foresight_ids_used: list[str]
    foresight_snippets: dict[str, str]
    reinterpretation_count: int
    reinterpretation_reason: str | None


@dataclass(frozen=True)
class BeliefGenerationResult:
    belief: Belief
    signal_summary: list[SignalPoint]
    evidence: list[FAERSReport]
    episodic_context: list[EpisodicSummary]
    trace: BeliefGenerationTrace


def normalize_question_text(question_text: str) -> str:
    normalized = re.sub(r"\s+", " ", question_text.strip().lower())
    return normalized


def compute_question_hash(question_text: str) -> str:
    normalized = normalize_question_text(question_text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def choose_gemini_model(settings: Settings, question_text: str) -> str:
    lowered = question_text.lower()
    for token in ["predict", "forecast", "regulatory"]:
        if token in lowered:
            return settings.gemini_model_reasoning
    return settings.gemini_model_default


def _ensure_disclaimer(text: str) -> str:
    if DISCLAIMER_SENTENCE.lower() in text.lower():
        return text
    return f"{text.rstrip()}\n\n{DISCLAIMER_SENTENCE}"


def _risk_from_stats(max_ci_lower: float | None, n_detected: int) -> str:
    if n_detected == 0:
        return "low"
    if max_ci_lower is None:
        return "moderate"
    if max_ci_lower >= 4:
        return "high"
    if max_ci_lower >= 2:
        return "elevated"
    return "moderate"


def compute_statistical_confidence(
    *,
    n_reports: int,
    max_ci_lower: float,
    n_detected: int,
) -> int:
    def clamp01(value: float) -> float:
        return min(1.0, max(0.0, value))

    c1 = 30 * clamp01(math.log10(n_reports + 1) / 4.0)
    c2 = 40 * clamp01((max_ci_lower - 1.0) / 3.0)
    c3 = 30 * clamp01(n_detected / 5.0)

    return int(round(c1 + c2 + c3))


def _as_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def belief_row_to_schema(row: BeliefRow) -> Belief:
    return Belief(
        id=str(row.id),
        drug_id=row.drug_id,
        question_hash=row.question_hash,
        question_text=row.question_text,
        answer_text=row.answer_text,
        confidence_score=row.confidence_score,
        evidence_report_ids=list(row.evidence_report_ids or []),
        episodic_ids_used=list(row.episodic_ids_used or []),
        created_at=_as_iso(row.created_at),
        quarter_context=row.quarter_context,
    )


async def _get_drug(db: AsyncSession, drug_id: str) -> Drug:
    row = await db.scalar(select(Drug).where(Drug.id == drug_id))
    if row is None:
        raise AppError(
            error="BadRequest",
            detail=f"drug_id '{drug_id}' not found",
            status_code=400,
        )
    return row


async def _resolve_quarter_context(db: AsyncSession, drug_id: str, quarter_context: str | None) -> str:
    state = await db.scalar(select(IngestionState).where(IngestionState.drug_id == drug_id))
    if state is None:
        raise AppError(
            error="BadRequest",
            detail=f"drug_id '{drug_id}' not found",
            status_code=400,
        )

    loaded = sort_quarters(list(state.quarters_loaded or []))
    if not loaded:
        raise AppError(
            error="BadRequest",
            detail=f"no quarters loaded for drug_id '{drug_id}'",
            status_code=400,
        )

    if quarter_context is None:
        return loaded[-1]
    if quarter_context not in loaded:
        raise AppError(
            error="BadRequest",
            detail=f"quarter_context '{quarter_context}' is not loaded for drug_id '{drug_id}'",
            status_code=400,
        )
    return quarter_context


async def _fetch_signal_summary(db: AsyncSession, drug_id: str, quarter: str) -> list[SignalPoint]:
    rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == quarter,
                )
                .order_by(QuarterlyStat.ror_ci_lower.desc().nullslast(), QuarterlyStat.report_count.desc())
            )
        )
        .scalars()
        .all()
    )

    points = [
        SignalPoint(
            quarter=row.quarter,
            adverse_event=row.adverse_event,
            report_count=row.report_count,
            cumulative_count=row.cumulative_count,
            drug_total_cumulative=row.drug_total_cumulative,
            ror=row.ror,
            ror_ci_lower=row.ror_ci_lower,
            ror_ci_upper=row.ror_ci_upper,
            prr=row.prr,
            chi_squared=row.chi_squared,
            signal_detected=bool(row.signal_detected),
            trajectory=row.trajectory,
        )
        for row in rows
    ]
    return points


async def _fetch_signal_history(
    db: AsyncSession,
    drug_id: str,
    events: list[str],
) -> dict[str, list[SignalPoint]]:
    history: dict[str, list[SignalPoint]] = {}
    for event in events:
        rows = (
            (
                await db.execute(
                    select(QuarterlyStat)
                    .where(
                        QuarterlyStat.drug_id == drug_id,
                        QuarterlyStat.adverse_event == event,
                    )
                    .order_by(QuarterlyStat.quarter.asc())
                )
            )
            .scalars()
            .all()
        )
        history[event] = [
            SignalPoint(
                quarter=row.quarter,
                adverse_event=row.adverse_event,
                report_count=row.report_count,
                cumulative_count=row.cumulative_count,
                drug_total_cumulative=row.drug_total_cumulative,
                ror=row.ror,
                ror_ci_lower=row.ror_ci_lower,
                ror_ci_upper=row.ror_ci_upper,
                prr=row.prr,
                chi_squared=row.chi_squared,
                signal_detected=bool(row.signal_detected),
                trajectory=row.trajectory,
            )
            for row in rows
        ]
    return history


async def _fetch_fda_actions(db: AsyncSession, drug_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(FdaAction)
                .where(FdaAction.drug_id == drug_id)
                .order_by(FdaAction.date.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "date": row.date.isoformat(),
            "type": row.type,
            "title": row.title,
            "description": row.description,
            "source_url": row.source_url,
        }
        for row in rows
    ]


async def _query_evidence_ids_for_event(
    db: AsyncSession,
    *,
    drug_id: str,
    event_pt: str,
    end_date: date,
    limit: int,
) -> list[str]:
    rows = (
        (
            await db.execute(
                select(FaersReport.safetyreportid)
                .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
                .join(FaersReportReaction, FaersReportReaction.safetyreportid == FaersReport.safetyreportid)
                .where(
                    FaersReportDrug.drug_id == drug_id,
                    FaersReportDrug.role == "suspect",
                    FaersReportReaction.meddra_pt == event_pt,
                    FaersReport.receivedate <= end_date,
                )
                .order_by(FaersReport.receivedate.desc(), FaersReport.safetyreportid.asc())
                .limit(limit)
            )
        )
        .all()
    )
    return [row.safetyreportid for row in rows]


async def _select_evidence_ids(
    db: AsyncSession,
    *,
    drug_id: str,
    question_text: str,
    quarter_context: str,
    signal_summary: list[SignalPoint],
) -> list[str]:
    _, quarter_end = quarter_to_dates(quarter_context)

    lowered = question_text.lower()
    matched_event = None
    for event in TRACKED_EVENTS:
        if event.lower() in lowered:
            matched_event = event
            break

    evidence_ids: list[str] = []
    if matched_event:
        evidence_ids.extend(
            await _query_evidence_ids_for_event(
                db,
                drug_id=drug_id,
                event_pt=matched_event,
                end_date=quarter_end,
                limit=5,
            )
        )
    else:
        top_events = [point.adverse_event for point in signal_summary[:2]]
        for event in top_events:
            event_ids = await _query_evidence_ids_for_event(
                db,
                drug_id=drug_id,
                event_pt=event,
                end_date=quarter_end,
                limit=8,
            )
            for report_id in event_ids:
                if report_id not in evidence_ids:
                    evidence_ids.append(report_id)
                if len(evidence_ids) >= 8:
                    break
            if len(evidence_ids) >= 8:
                break

    return evidence_ids[:8]


async def _fetch_faers_reports(db: AsyncSession, report_ids: list[str]) -> list[FAERSReport]:
    return await fetch_evidence_reports(db, report_ids)


def _fallback_assessment(
    *,
    quarter_context: str,
    signal_summary: list[SignalPoint],
    question_text: str = "",
    drug_id: str = "",
    fda_actions: list[dict[str, Any]] | None = None,
    prediction_summaries: list[str] | None = None,
    reinterpretation_note: str | None = None,
) -> tuple[str, int, str, list[str], list[str]]:
    lowered = question_text.lower()
    fda_actions = fda_actions or []
    prediction_summaries = prediction_summaries or []

    if not signal_summary:
        text = (
            f"As of {quarter_context}, there is insufficient data to provide a strong signal-level assessment."
        )
        return _ensure_disclaimer(text), 50, "low", [], ["No qualifying signal points available."]

    detected = [point for point in signal_summary if point.signal_detected]
    max_ci_lower = max([point.ror_ci_lower or 1.0 for point in detected], default=1.0)
    risk_level = _risk_from_stats(max_ci_lower=max_ci_lower, n_detected=len(detected))

    def _format_ror(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    def _format_ci(low: float | None, high: float | None) -> str:
        if low is None or high is None:
            return "CI n/a"
        return f"CI {low:.2f}\u2013{high:.2f}"

    def _trajectory_rank(trajectory: str) -> int:
        if trajectory == "stable":
            return 0
        if trajectory in {"emerging", "accelerating"}:
            return 1
        if trajectory == "declining":
            return 2
        return 3

    def _signal_line(point: SignalPoint) -> str:
        return (
            f"- {point.adverse_event}: ROR {_format_ror(point.ror)} "
            f"({_format_ci(point.ror_ci_lower, point.ror_ci_upper)}), {point.trajectory} trajectory."
        )

    if "gi motility" in lowered or "gastroparesis" in lowered or "gastrointestinal" in lowered:
        gi_events = {
            "Nausea",
            "Vomiting",
            "Constipation",
            "Abdominal distension",
            "Abdominal pain",
            "Gastroparesis",
            "Ileus",
            "Diarrhea",
        }
        gi_points = [point for point in signal_summary if point.adverse_event in gi_events and point.signal_detected]
        ordered_gi = sorted(
            gi_points,
            key=lambda point: (
                _trajectory_rank(point.trajectory),
                -(point.ror_ci_lower or -1.0),
                -point.cumulative_count,
                point.adverse_event,
            ),
        )

        if ordered_gi:
            lead = (
                f"As of {quarter_context}, GI motility monitoring for {drug_id or 'the selected drug'} "
                f"shows {len(ordered_gi)} active GI-related signals."
            )
        else:
            lead = (
                f"As of {quarter_context}, GI motility monitoring for {drug_id or 'the selected drug'} "
                "shows no currently detected GI-specific disproportionality signals."
            )
        lines = [lead]

        for point in ordered_gi:
            lines.append(_signal_line(point))

        if len(ordered_gi) > 1:
            lines.append("Multiple concurrent GI signals suggest a broader motility disruption pattern.")

        for serious_event in ("Ileus", "Gastroparesis"):
            hit = next((point for point in signal_summary if point.adverse_event == serious_event), None)
            if hit and hit.cumulative_count > 0:
                lines.append(
                    f"{serious_event} has emerged as a potential serious GI complication with "
                    f"{hit.cumulative_count} cumulative reports as of {quarter_context}."
                )

        if reinterpretation_note:
            lines.append(reinterpretation_note)

        bullets = [
            f"Detected GI signals: {', '.join(point.adverse_event for point in ordered_gi) if ordered_gi else 'none'}."
        ]
        return _ensure_disclaimer("\n".join(lines)), 56, risk_level, [], bullets

    if "regulatory" in lowered or "warrant" in lowered or "attention" in lowered:
        threshold_hits = [
            point
            for point in signal_summary
            if point.ror_ci_lower is not None
            and point.chi_squared is not None
            and point.ror_ci_lower > 1.0
            and point.chi_squared > 3.84
        ]
        ordered_threshold = sorted(
            threshold_hits,
            key=lambda point: (
                -(point.ror_ci_lower or -1.0),
                -point.cumulative_count,
                point.adverse_event,
            ),
        )

        lines = [
            (
                f"As of {quarter_context}, {len(ordered_threshold)} signals meet standard detection thresholds "
                "(ROR CI lower > 1.0, chi-squared > 3.84)."
            )
        ]
        if ordered_threshold:
            for point in ordered_threshold:
                lines.append(_signal_line(point))
        else:
            lines.append("No signals currently exceed combined regulatory attention thresholds.")

        _, quarter_end = quarter_to_dates(quarter_context)
        past_actions = [
            action
            for action in fda_actions
            if isinstance(action.get("date"), str) and action["date"] <= quarter_end.isoformat()
        ]
        if past_actions:
            action = past_actions[-1]
            title = str(action.get("title") or action.get("type") or "FDA action")
            lines.append(f"Observed FDA context through this quarter includes: {action['date']} \u2014 {title}.")

        if prediction_summaries:
            lines.append(f"Prediction summary: {'; '.join(prediction_summaries[:2])}.")

        bullets = [
            f"Threshold hits: {', '.join(point.adverse_event for point in ordered_threshold) if ordered_threshold else 'none'}."
        ]
        return _ensure_disclaimer("\n".join(lines)), 58, risk_level, [], bullets

    # Default branch: overall safety profile framing.
    ordered_detected = sorted(
        detected,
        key=lambda point: (
            _trajectory_rank(point.trajectory),
            -(point.ror_ci_lower or -1.0),
            -point.cumulative_count,
            point.adverse_event,
        ),
    )
    cumulative_reports = max([point.cumulative_count for point in signal_summary], default=0)
    lines = [
        (
            f"As of {quarter_context}, {drug_id or 'the selected drug'}'s safety profile shows "
            f"{len(ordered_detected)} active signals across {cumulative_reports} cumulative adverse event reports."
        )
    ]
    if ordered_detected:
        for point in ordered_detected:
            lines.append(_signal_line(point))
    else:
        lines.append("No signals currently meet detection thresholds in the monitored event set.")
    lines.append(f"Overall risk level is assessed as {risk_level}.")
    bullets = [
        f"Detected signals are ordered by trajectory and strength for {quarter_context}.",
    ]
    return _ensure_disclaimer("\n".join(lines)), 55, risk_level, [], bullets


def _fda_action_matches_prediction(action: dict[str, Any], prediction: PredictionRow) -> bool:
    action_type = str(action.get("type") or "")
    if action_type != prediction.predicted_action:
        return False

    hay = f"{action.get('title', '')} {action.get('description', '')}".lower()
    return prediction.adverse_event.lower() in hay


def _prediction_status_for_fallback(
    *,
    prediction: PredictionRow,
    fda_actions: list[dict[str, Any]],
) -> str:
    action = next((row for row in fda_actions if _fda_action_matches_prediction(row, prediction)), None)
    if action is None:
        return "pending"
    action_date_text = str(action.get("date") or "")
    try:
        action_date = date.fromisoformat(action_date_text)
    except ValueError:
        return "pending"
    if prediction.predicted_date_start <= action_date <= prediction.predicted_date_end:
        return "validated"
    return "pending"


async def _prediction_summaries_for_quarter(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter_context: str,
    fda_actions: list[dict[str, Any]],
) -> list[str]:
    rows = (
        (
            await db.execute(
                select(PredictionRow)
                .where(PredictionRow.drug_id == drug_id)
                .order_by(PredictionRow.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    filtered = [
        row
        for row in rows
        if row.adverse_event != "Pancreatitis"
        if parse_quarter(row.created_at_quarter) <= parse_quarter(quarter_context)
    ]
    summaries: list[str] = []
    for row in filtered:
        status = _prediction_status_for_fallback(prediction=row, fda_actions=fda_actions)
        summaries.append(
            f"{row.adverse_event} {row.predicted_action} predicted in {row.created_at_quarter} \u2014 {status}"
        )
    return summaries


def _build_llm_prompt(
    *,
    question_text: str,
    drug: Drug,
    quarter_context: str,
    quarters_loaded: list[str],
    signal_summary: list[SignalPoint],
    signal_history: dict[str, list[SignalPoint]],
    fda_actions: list[dict[str, Any]],
    evidence: list[FAERSReport],
    episodic_memory_snippets: list[str],
    foresight_memory_snippets: list[str],
) -> str:
    compact_evidence = [
        {
            "safetyreportid": item.safetyreportid,
            "receivedate": item.receivedate,
            "reactions": item.reactions,
            "serious": item.serious,
            "outcomes": item.outcomes,
        }
        for item in evidence
    ]

    episodic_block = (
        "\n\nEPISODIC MEMORY CONTEXT (EverMemOS):\n"
        + "\n".join(episodic_memory_snippets)
        if episodic_memory_snippets
        else ""
    )
    foresight_block = (
        "\n\nFORESIGHT MEMORY CONTEXT (EverMemOS):\n"
        + "\n".join(foresight_memory_snippets)
        if foresight_memory_snippets
        else ""
    )

    return f"""QUESTION:
{question_text}

DRUG:
{drug.id} ({drug.generic_name}), brand names: {', '.join(drug.brand_names)}

TIME CONTEXT:
As-of quarter: {quarter_context}
Loaded quarters: {', '.join(quarters_loaded)}

SIGNAL STATS (latest quarter points):
{json.dumps([point.model_dump() for point in signal_summary], ensure_ascii=True)}

SIGNAL HISTORY (for top 3 signals):
{json.dumps({k: [p.model_dump() for p in v] for k, v in signal_history.items()}, ensure_ascii=True)}

FDA ACTIONS (verified):
{json.dumps(fda_actions, ensure_ascii=True)}

EVIDENCE SAMPLES (max 8 reports):
{json.dumps(compact_evidence, ensure_ascii=True)}
{episodic_block}
{foresight_block}

RETROACTIVE REINTERPRETATION:
If any new signals emerged this quarter, you may flag earlier precursor-coded reports as \"reinterpreted\".
Precursor map (hardcoded):
{json.dumps(PRECURSOR_MAP, ensure_ascii=True)}

OUTPUT JSON SCHEMA (must follow):
{{
  \"assessment_text\": string,
  \"confidence_narrative\": integer 0-100,
  \"risk_level\": \"low\"|\"moderate\"|\"elevated\"|\"high\",
  \"key_evidence_ids\": string[],
  \"reasoning_bullets\": string[]
}}"""


def _parse_llm_json(raw_text: str) -> LLMBeliefPayload | None:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None

    try:
        return LLMBeliefPayload.model_validate(payload)
    except Exception:
        return None


def _call_gemini_generate(
    *,
    settings: Settings,
    model: str,
    prompt: str,
    retry_json_fix: bool,
) -> str | None:
    if not settings.gemini_api_key:
        return None

    try:
        from google import genai
        from google.genai import types
    except Exception:
        return None

    client = genai.Client(api_key=settings.gemini_api_key)
    final_prompt = prompt
    if retry_json_fix:
        final_prompt = (
            f"{prompt}\n\nYour previous output was invalid JSON. Output valid JSON only."
        )

    try:
        response = client.models.generate_content(
            model=model,
            contents=final_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception:
        return None

    return getattr(response, "text", None)


def _memory_identifier(memory: dict[str, Any]) -> str | None:
    for key in ["id", "_id", "memory_id", "message_id"]:
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _memory_search_text(memory: dict[str, Any]) -> str:
    text_parts: list[str] = []
    for key in ["title", "summary", "episode", "content", "memory", "text", "atomic_fact", "subject"]:
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value.strip())
    return "\n".join(text_parts)


def _quarter_aliases(quarter: str) -> list[str]:
    if "-Q" not in quarter:
        return [quarter]
    year, qn = quarter.split("-Q")
    q_value = qn.strip()
    year_value = year.strip()
    return [
        quarter,
        f"{year_value} Q{q_value}",
        f"Q{q_value} {year_value}",
    ]


def _memory_matches_quarter(memory: dict[str, Any], quarter_context: str) -> bool:
    text = _memory_search_text(memory)
    if not text:
        return False
    covered = extract_quarters_from_text(text)
    if quarter_context in covered:
        return True
    lower_text = text.lower()
    return any(alias.lower() in lower_text for alias in _quarter_aliases(quarter_context))


def _dedupe_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for memory in memories:
        memory_id = _memory_identifier(memory)
        if memory_id:
            key = f"id:{memory_id}"
        else:
            key = f"text:{_memory_search_text(memory)}"
        if not key.strip() or key in seen:
            continue
        seen.add(key)
        deduped.append(memory)
    return deduped


async def _retrieve_episodic_memories(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient | None,
    drug_id: str,
    question_text: str,
    quarter_context: str,
    force_query_grounding: bool,
) -> list[dict[str, Any]]:
    if evermemos_client is None:
        return []

    base_query = f"{question_text} {drug_id} safety signals {quarter_context}"
    query_variants = [base_query]
    if force_query_grounding and "-Q" in quarter_context:
        year, qn = quarter_context.split("-Q")
        query_variants.extend(
            [
                f"VigiLens Quarter Digest {quarter_context} {drug_id}",
                f"Q{qn} {year} {drug_id} safety digest",
                f"{drug_id} episodic memory {quarter_context}",
            ]
        )

    retrieve_methods = ["rrf", "keyword"] if force_query_grounding else ["rrf"]
    aggregated: list[dict[str, Any]] = []
    for retrieve_method in retrieve_methods:
        for query in query_variants:
            hits = await evermemos_client.search_memories(
                db,
                drug_id=drug_id,
                query=query,
                top_k=12 if force_query_grounding else 3,
                retrieve_method=retrieve_method,
            )
            if hits:
                aggregated.extend(hits)

    deduped = _dedupe_memories(aggregated)
    if not force_query_grounding:
        return deduped[:3]

    matching = [memory for memory in deduped if _memory_matches_quarter(memory, quarter_context)]
    if matching:
        return matching[:5]

    # Final fallback for query path: inspect bulk episodic/event memories.
    bulk_memories = await evermemos_client.fetch_episodic_memories(db, drug_id=drug_id)
    if not bulk_memories:
        return deduped[:5]
    deduped_bulk = _dedupe_memories(bulk_memories)
    bulk_matching = [memory for memory in deduped_bulk if _memory_matches_quarter(memory, quarter_context)]
    if bulk_matching:
        return bulk_matching[:5]
    return deduped[:5]


async def _retrieve_foresight_memories(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient | None,
    drug_id: str,
    question_text: str,
    quarter_context: str,
    force_query_grounding: bool,
) -> list[dict[str, Any]]:
    if evermemos_client is None:
        return []

    query_variants = [
        f"{question_text} {drug_id} foresight {quarter_context}",
        f"{drug_id} prediction {quarter_context}",
        f"{drug_id} regulatory foresight",
    ]
    retrieve_methods = ["rrf", "keyword"] if force_query_grounding else ["rrf"]

    aggregated: list[dict[str, Any]] = []
    for retrieve_method in retrieve_methods:
        for query in query_variants:
            hits = await evermemos_client.search_memories(
                db,
                drug_id=drug_id,
                query=query,
                top_k=6 if force_query_grounding else 3,
                retrieve_method=retrieve_method,
                memory_types=["foresight"],
            )
            if hits:
                aggregated.extend(hits)

    return _dedupe_memories(aggregated)[:6]


def _memory_quarter(memory: dict[str, Any], fallback_quarter: str) -> str:
    text = "\n".join(
        value
        for key in ["title", "summary", "episode", "content", "memory", "text"]
        if isinstance((value := memory.get(key)), str) and value.strip()
    )
    covered = sorted(extract_quarters_from_text(text))
    if covered:
        return covered[-1]
    return fallback_quarter


async def _count_reports_for_quarter(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter: str,
) -> int:
    start_date, end_date = quarter_to_dates(quarter)
    value = await db.scalar(
        select(func.count(func.distinct(FaersReport.safetyreportid)))
        .select_from(FaersReport)
        .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
        .where(
            FaersReportDrug.drug_id == drug_id,
            FaersReportDrug.role == "suspect",
            FaersReport.receivedate >= start_date,
            FaersReport.receivedate <= end_date,
        )
    )
    return int(value or 0)


async def _key_signals_for_quarter(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter: str,
) -> list[str]:
    rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == quarter,
                )
                .order_by(
                    QuarterlyStat.signal_detected.desc(),
                    QuarterlyStat.ror_ci_lower.desc().nullslast(),
                    QuarterlyStat.report_count.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    detected = [row.adverse_event for row in rows if row.signal_detected][:3]
    if detected:
        return detected
    return [row.adverse_event for row in rows[:3]]


async def _build_episodic_context(
    db: AsyncSession,
    *,
    drug_id: str,
    memories: list[dict[str, Any]],
    quarter_context: str,
) -> tuple[list[EpisodicSummary], list[str], list[str]]:
    contexts: list[EpisodicSummary] = []
    ids: list[str] = []
    snippets: list[str] = []
    seen_context_keys: set[str] = set()
    metrics_cache: dict[str, tuple[list[str], int]] = {}

    async def _metrics_for(quarter: str) -> tuple[list[str], int]:
        cached = metrics_cache.get(quarter)
        if cached is not None:
            return cached
        key_signals = await _key_signals_for_quarter(db, drug_id=drug_id, quarter=quarter)
        report_count = await _count_reports_for_quarter(db, drug_id=drug_id, quarter=quarter)
        metrics_cache[quarter] = (key_signals, report_count)
        return metrics_cache[quarter]

    for index, memory in enumerate(memories):
        text = ""
        for key in ["episode", "summary", "content", "memory", "text", "title"]:
            value = memory.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if not text:
            continue

        memory_id = _memory_identifier(memory)
        quarter = _memory_quarter(memory, quarter_context)
        context_key = f"quarter:{quarter}|text:{text.strip().lower()}"
        if context_key in seen_context_keys:
            continue
        seen_context_keys.add(context_key)
        if memory_id:
            ids.append(memory_id)

        key_signals, report_count = await _metrics_for(quarter)
        snippets.append(f"[memory_{index + 1}] {text}")
        contexts.append(
            EpisodicSummary(
                quarter=quarter,
                narrative=text,
                key_signals_mentioned=key_signals,
                report_count_ingested=report_count,
                created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                memory_source="evermemos",
                memory_id=memory_id,
            )
        )

    # Preserve order while removing duplicates.
    dedup_ids = list(dict.fromkeys(ids))
    return contexts, dedup_ids, snippets


def _build_episodic_snippet_map(
    episodic_context: list[EpisodicSummary],
    episodic_ids_used: list[str],
) -> dict[str, str]:
    snippet_by_id: dict[str, str] = {}
    context_by_id = {
        item.memory_id: item
        for item in episodic_context
        if isinstance(item.memory_id, str) and item.memory_id.strip()
    }
    for memory_id in episodic_ids_used:
        context = context_by_id.get(memory_id)
        if context is None or not context.narrative.strip():
            continue
        snippet_by_id[memory_id] = context.narrative.strip()
    return snippet_by_id


def _build_foresight_context(
    memories: list[dict[str, Any]],
) -> tuple[list[str], list[str], dict[str, str]]:
    ids: list[str] = []
    snippets: list[str] = []
    snippet_by_id: dict[str, str] = {}

    for index, memory in enumerate(memories):
        text = ""
        for key in ["content", "summary", "memory", "text", "title"]:
            value = memory.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if not text:
            continue
        memory_id = _memory_identifier(memory)
        if not memory_id:
            continue
        ids.append(memory_id)
        snippets.append(f"[foresight_{index + 1}] {text}")
        snippet_by_id[memory_id] = text

    return list(dict.fromkeys(ids)), snippets, snippet_by_id


def _select_top_signal_events(signal_summary: list[SignalPoint], max_events: int = 3) -> list[str]:
    return [point.adverse_event for point in signal_summary[:max_events]]


async def _detect_reinterpretations(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter_context: str,
    signal_summary: list[SignalPoint],
    all_quarters_loaded: list[str],
) -> tuple[list[str], str | None]:
    prev_quarter = quarter_minus_one(quarter_context)
    if prev_quarter not in all_quarters_loaded:
        return [], None

    prev_signals = await _fetch_signal_summary(db, drug_id, prev_quarter)
    prev_detected = {point.adverse_event for point in prev_signals if point.signal_detected}
    curr_detected = {point.adverse_event for point in signal_summary if point.signal_detected}
    newly_detected = curr_detected - prev_detected
    if not newly_detected:
        return [], None

    _, prev_quarter_end = quarter_to_dates(prev_quarter)
    reinterpreted_ids: list[str] = []

    for new_signal in sorted(newly_detected):
        precursors = PRECURSOR_MAP.get(new_signal)
        if not precursors:
            continue

        for precursor_event in precursors:
            precursor_ids = await _query_evidence_ids_for_event(
                db,
                drug_id=drug_id,
                event_pt=precursor_event,
                end_date=prev_quarter_end,
                limit=10,
            )
            for report_id in precursor_ids:
                if report_id not in reinterpreted_ids:
                    reinterpreted_ids.append(report_id)

        if not reinterpreted_ids:
            continue

        reason = (
            f"Signal '{new_signal}' newly detected in {quarter_context}. "
            f"{len(reinterpreted_ids)} earlier reports originally coded as "
            f"{', '.join(precursors[:3])} have been flagged as potential precursors."
        )
        return reinterpreted_ids[:15], reason

    return [], None


async def _build_belief_payload(
    *,
    settings: Settings,
    question_text: str,
    drug: Drug,
    quarter_context: str,
    quarters_loaded: list[str],
    signal_summary: list[SignalPoint],
    signal_history: dict[str, list[SignalPoint]],
    fda_actions: list[dict[str, Any]],
    evidence: list[FAERSReport],
    episodic_memory_snippets: list[str],
    foresight_memory_snippets: list[str],
) -> LLMBeliefPayload | None:
    prompt = _build_llm_prompt(
        question_text=question_text,
        drug=drug,
        quarter_context=quarter_context,
        quarters_loaded=quarters_loaded,
        signal_summary=signal_summary,
        signal_history=signal_history,
        fda_actions=fda_actions,
        evidence=evidence,
        episodic_memory_snippets=episodic_memory_snippets,
        foresight_memory_snippets=foresight_memory_snippets,
    )

    model = choose_gemini_model(settings, question_text)

    raw = _call_gemini_generate(
        settings=settings,
        model=model,
        prompt=prompt,
        retry_json_fix=False,
    )
    if raw:
        parsed = _parse_llm_json(raw)
        if parsed is not None:
            return parsed

    retry_raw = _call_gemini_generate(
        settings=settings,
        model=model,
        prompt=prompt,
        retry_json_fix=True,
    )
    if retry_raw:
        return _parse_llm_json(retry_raw)

    return None


async def generate_and_store_belief(
    db: AsyncSession,
    *,
    settings: Settings,
    drug_id: str,
    question_text: str,
    quarter_context: str | None,
    evermemos_client: EvermemosClient | None = None,
    force_query_grounding: bool = False,
) -> BeliefGenerationResult:
    drug = await _get_drug(db, drug_id)
    resolved_quarter = await _resolve_quarter_context(db, drug_id, quarter_context)

    if not force_query_grounding:
        question_hash = compute_question_hash(question_text)
        existing = await db.scalar(
            select(BeliefRow).where(
                BeliefRow.drug_id == drug_id,
                BeliefRow.question_hash == question_hash,
                BeliefRow.quarter_context == resolved_quarter,
            )
        )
        if existing is not None:
            return BeliefGenerationResult(
                belief=belief_row_to_schema(existing),
                signal_summary=[],
                evidence=[],
                episodic_context=[],
                trace=BeliefGenerationTrace(
                    episodic_ids_used=list(existing.episodic_ids_used or []),
                    episodic_snippets={},
                    foresight_ids_used=[],
                    foresight_snippets={},
                    reinterpretation_count=len(existing.reinterpreted_report_ids or []),
                    reinterpretation_reason=(existing.reinterpretation_reason or {}).get("reason"),
                ),
            )

    state = await db.scalar(select(IngestionState).where(IngestionState.drug_id == drug_id))
    quarters_loaded = sort_quarters(list(state.quarters_loaded or [])) if state else []

    full_signal_summary = await _fetch_signal_summary(db, drug_id, resolved_quarter)
    signal_summary = full_signal_summary[:3]
    signal_events = _select_top_signal_events(full_signal_summary)
    signal_history = await _fetch_signal_history(db, drug_id, signal_events)
    fda_actions = await _fetch_fda_actions(db, drug_id)
    prediction_summaries = await _prediction_summaries_for_quarter(
        db,
        drug_id=drug_id,
        quarter_context=resolved_quarter,
        fda_actions=fda_actions,
    )

    evidence_ids = await _select_evidence_ids(
        db,
        drug_id=drug_id,
        question_text=question_text,
        quarter_context=resolved_quarter,
        signal_summary=full_signal_summary,
    )
    evidence_reports = await _fetch_faers_reports(db, evidence_ids)

    episodic_memories = await _retrieve_episodic_memories(
        db,
        evermemos_client=evermemos_client,
        drug_id=drug_id,
        question_text=question_text,
        quarter_context=resolved_quarter,
        force_query_grounding=force_query_grounding,
    )
    episodic_context, episodic_ids_used, episodic_snippets = await _build_episodic_context(
        db,
        drug_id=drug_id,
        memories=episodic_memories,
        quarter_context=resolved_quarter,
    )
    episodic_snippet_map = _build_episodic_snippet_map(episodic_context, episodic_ids_used)
    foresight_memories = await _retrieve_foresight_memories(
        db,
        evermemos_client=evermemos_client,
        drug_id=drug_id,
        question_text=question_text,
        quarter_context=resolved_quarter,
        force_query_grounding=force_query_grounding,
    )
    foresight_ids_used, foresight_snippets, foresight_snippet_map = _build_foresight_context(
        foresight_memories
    )

    llm_payload = await _build_belief_payload(
        settings=settings,
        question_text=question_text,
        drug=drug,
        quarter_context=resolved_quarter,
        quarters_loaded=quarters_loaded,
        signal_summary=signal_summary,
        signal_history=signal_history,
        fda_actions=fda_actions,
        evidence=evidence_reports,
        episodic_memory_snippets=episodic_snippets,
        foresight_memory_snippets=foresight_snippets,
    )

    reinterpreted_report_ids, reinterpretation_reason = await _detect_reinterpretations(
        db,
        drug_id=drug_id,
        quarter_context=resolved_quarter,
        signal_summary=full_signal_summary,
        all_quarters_loaded=quarters_loaded,
    )

    if llm_payload is None:
        assessment_text, confidence_narrative, risk_level, key_evidence_ids, _ = _fallback_assessment(
            quarter_context=resolved_quarter,
            signal_summary=full_signal_summary,
            question_text=question_text,
            drug_id=drug_id,
            fda_actions=fda_actions,
            prediction_summaries=prediction_summaries,
            reinterpretation_note=reinterpretation_reason,
        )
    else:
        assessment_text = _ensure_disclaimer(llm_payload.assessment_text)
        confidence_narrative = llm_payload.confidence_narrative
        risk_level = llm_payload.risk_level
        key_evidence_ids = llm_payload.key_evidence_ids

    n_reports = await db.scalar(
        select(func.max(QuarterlyStat.drug_total_cumulative)).where(
            QuarterlyStat.drug_id == drug_id,
            QuarterlyStat.quarter == resolved_quarter,
        )
    )
    n_reports_i = int(n_reports or 0)

    detected = [point for point in full_signal_summary if point.signal_detected]
    max_ci_lower = max([point.ror_ci_lower or 1.0 for point in detected], default=1.0)
    n_detected = len(detected)

    confidence_statistical = compute_statistical_confidence(
        n_reports=n_reports_i,
        max_ci_lower=max_ci_lower,
        n_detected=n_detected,
    )
    confidence_score = int(round((confidence_statistical + confidence_narrative) / 2))

    if llm_payload is None:
        risk_level = _risk_from_stats(max_ci_lower=max_ci_lower, n_detected=n_detected)

    now = datetime.now(timezone.utc)
    question_hash = compute_question_hash(question_text)
    final_evidence_ids = key_evidence_ids if key_evidence_ids else evidence_ids
    final_reinterpretation_reason = {"reason": reinterpretation_reason} if reinterpretation_reason else {}

    result = await db.execute(
        pg_insert(BeliefRow)
        .values(
            drug_id=drug_id,
            question_hash=question_hash,
            question_text=question_text,
            answer_text=assessment_text,
            confidence_score=confidence_score,
            evidence_report_ids=final_evidence_ids,
            episodic_ids_used=episodic_ids_used,
            quarter_context=resolved_quarter,
            reinterpreted_report_ids=reinterpreted_report_ids,
            reinterpretation_reason=final_reinterpretation_reason,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=[BeliefRow.drug_id, BeliefRow.question_hash, BeliefRow.quarter_context],
            set_={
                "question_text": question_text,
                "answer_text": assessment_text,
                "confidence_score": confidence_score,
                "evidence_report_ids": final_evidence_ids,
                "episodic_ids_used": episodic_ids_used,
                "reinterpreted_report_ids": reinterpreted_report_ids,
                "reinterpretation_reason": final_reinterpretation_reason,
                "created_at": now,
            },
        )
        .returning(BeliefRow.id)
    )
    belief_id = result.scalar_one()

    belief_schema = Belief(
        id=str(belief_id),
        drug_id=drug_id,
        question_hash=question_hash,
        question_text=question_text,
        answer_text=assessment_text,
        confidence_score=confidence_score,
        evidence_report_ids=final_evidence_ids,
        episodic_ids_used=episodic_ids_used,
        created_at=_as_iso(now),
        quarter_context=resolved_quarter,
    )

    return BeliefGenerationResult(
        belief=belief_schema,
        signal_summary=signal_summary,
        evidence=evidence_reports,
        episodic_context=episodic_context,
        trace=BeliefGenerationTrace(
            episodic_ids_used=episodic_ids_used,
            episodic_snippets=episodic_snippet_map,
            foresight_ids_used=foresight_ids_used,
            foresight_snippets=foresight_snippet_map,
            reinterpretation_count=len(reinterpreted_report_ids),
            reinterpretation_reason=reinterpretation_reason,
        ),
    )


async def run_query(
    db: AsyncSession,
    *,
    settings: Settings,
    drug_id: str,
    question_text: str,
    quarter_context: str | None,
    evermemos_client: EvermemosClient | None = None,
) -> QueryResponse:
    generated = await generate_and_store_belief(
        db,
        settings=settings,
        drug_id=drug_id,
        question_text=question_text,
        quarter_context=quarter_context,
        evermemos_client=evermemos_client,
        force_query_grounding=True,
    )
    await db.commit()

    return QueryResponse(
        answer_text=generated.belief.answer_text,
        confidence=generated.belief.confidence_score,
        signal_summary=generated.signal_summary,
        evidence=generated.evidence,
        episodic_context=generated.episodic_context,
        belief_id=generated.belief.id,
        foresight_memory_ids=generated.trace.foresight_ids_used,
    )


async def list_beliefs(db: AsyncSession, drug_id: str) -> list[Belief]:
    await _get_drug(db, drug_id)

    rows = (
        (
            await db.execute(
                select(BeliefRow)
                .where(BeliefRow.drug_id == drug_id)
                .order_by(BeliefRow.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    return [belief_row_to_schema(row) for row in rows]


async def get_belief_row_or_400(db: AsyncSession, belief_id: str) -> BeliefRow:
    try:
        parsed_id = UUID(belief_id)
    except ValueError as exc:
        raise AppError(error="BadRequest", detail=f"invalid belief id '{belief_id}'", status_code=400) from exc

    row = await db.scalar(select(BeliefRow).where(BeliefRow.id == parsed_id))
    if row is None:
        raise AppError(error="BadRequest", detail=f"belief id '{belief_id}' not found", status_code=400)
    return row


async def generate_tracked_beliefs_for_quarter(
    db: AsyncSession,
    *,
    settings: Settings,
    drug_id: str,
    quarter: str,
    evermemos_client: EvermemosClient | None = None,
) -> list[BeliefGenerationResult]:
    results: list[BeliefGenerationResult] = []
    for template in TRACKED_QUESTIONS:
        try:
            generated = await generate_and_store_belief(
                db,
                settings=settings,
                drug_id=drug_id,
                question_text=template.format(drug_id=drug_id, quarter=quarter),
                quarter_context=quarter,
                evermemos_client=evermemos_client,
            )
        except Exception:
            continue
        results.append(generated)
    return results
