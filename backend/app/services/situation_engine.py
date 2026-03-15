from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    Belief as BeliefRow,
    Drug,
    FdaAction,
    IngestionState,
    Prediction as PredictionRow,
    QuarterlyStat,
    SituationAnalysis as SituationAnalysisRow,
)
from app.schemas.shared import SituationAnalysis
from app.services.evermemos_client import EvermemosClient
from app.utils.quarters import parse_quarter, sort_quarters

logger = logging.getLogger(__name__)

SITUATION_SYSTEM_PROMPT = (
    "You are a senior pharmacovigilance analyst writing an internal safety brief. "
    "Your audience is an expert safety committee. Be precise, decisive, and quantitative. "
    "Every claim must cite a specific number — ROR value, confidence percentage, or report count. "
    "Format the narrative using markdown: **bold** for drug names, adverse event names, and key numbers; "
    "bullet lists (- item) for signal summaries when listing 3+ items; ### headings for distinct sections."
)

FALLBACK_NARRATIVE = (
    "AI situation analysis is unavailable. Review the signal statistics, beliefs, "
    "and prediction scorecard above for a manual assessment of the current safety posture."
)
SITUATION_GEMINI_TIMEOUT_SECONDS = 30.0


def _compute_belief_hash(beliefs: list[BeliefRow]) -> str:
    parts = sorted(f"{b.question_hash}:{b.confidence_score}:{b.answer_text[:80]}" for b in beliefs)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _as_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_report_evidence_question(question_text: str) -> bool:
    return "report-level evidence supports" in question_text.lower()


async def _gather_context(
    db: AsyncSession,
    drug_id: str,
    quarter: str,
    evermemos_client: EvermemosClient | None,
) -> dict[str, Any]:
    drug = await db.scalar(select(Drug).where(Drug.id == drug_id))
    drug_name = drug.generic_name if drug else drug_id

    signals = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(QuarterlyStat.drug_id == drug_id, QuarterlyStat.quarter == quarter)
                .order_by(QuarterlyStat.ror_ci_lower.desc().nullslast())
            )
        )
        .scalars()
        .all()
    )

    signal_lines: list[str] = []
    detected_events: list[str] = []
    for s in signals[:8]:
        flag = "DETECTED" if s.signal_detected else "sub-threshold"
        ror_str = f"ROR {s.ror:.2f} [{s.ror_ci_lower:.2f}-{s.ror_ci_upper:.2f}]" if s.ror else "N/A"
        signal_lines.append(
            f"  - {s.adverse_event}: {s.cumulative_count} cumul. reports, {ror_str}, "
            f"trajectory={s.trajectory}, {flag}"
        )
        if s.signal_detected:
            detected_events.append(s.adverse_event)

    n_reports = await db.scalar(
        select(func.max(QuarterlyStat.drug_total_cumulative)).where(
            QuarterlyStat.drug_id == drug_id,
            QuarterlyStat.quarter == quarter,
        )
    )

    beliefs = (
        (
            await db.execute(
                select(BeliefRow)
                .where(BeliefRow.drug_id == drug_id, BeliefRow.quarter_context == quarter)
                .order_by(BeliefRow.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    prompt_beliefs = [b for b in beliefs if not _is_report_evidence_question(b.question_text)] or beliefs
    belief_lines: list[str] = []
    for b in prompt_beliefs[:4]:
        snippet = b.answer_text[:200].replace("\n", " ")
        belief_lines.append(f"  - [{b.confidence_score}%] {b.question_text}\n    → {snippet}")

    fda_rows = (
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
    fda_lines = [f"  - {r.date.isoformat()}: [{r.type}] {r.title}" for r in fda_rows]

    state = await db.scalar(select(IngestionState).where(IngestionState.drug_id == drug_id))
    loaded = sort_quarters(list(state.quarters_loaded or [])) if state else []
    q_idx = loaded.index(quarter) if quarter in loaded else -1

    prev_quarter = loaded[q_idx - 1] if q_idx > 0 else None
    delta_lines: list[str] = []
    if prev_quarter:
        prev_beliefs = (
            (
                await db.execute(
                    select(BeliefRow)
                    .where(BeliefRow.drug_id == drug_id, BeliefRow.quarter_context == prev_quarter)
                    .order_by(BeliefRow.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        prev_map = {b.question_hash: b.confidence_score for b in prev_beliefs}
        for b in beliefs:
            prev_conf = prev_map.get(b.question_hash)
            if prev_conf is not None and prev_conf != b.confidence_score:
                delta_lines.append(
                    f"  - Confidence on \"{b.question_text[:60]}\" shifted from {prev_conf}% → {b.confidence_score}%"
                )

        prev_detected = set()
        prev_signals = (
            (
                await db.execute(
                    select(QuarterlyStat)
                    .where(
                        QuarterlyStat.drug_id == drug_id,
                        QuarterlyStat.quarter == prev_quarter,
                        QuarterlyStat.signal_detected.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        prev_detected = {s.adverse_event for s in prev_signals}
        new_signals = [e for e in detected_events if e not in prev_detected]
        if new_signals:
            delta_lines.append(f"  - Newly detected signals: {', '.join(new_signals)}")

    predictions = (
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
    pred_lines = []
    visible_predictions = [
        p for p in predictions if parse_quarter(p.created_at_quarter) <= parse_quarter(quarter)
    ]
    visible_predictions.sort(key=lambda prediction: (-int(prediction.confidence), prediction.created_at_quarter))
    for p in visible_predictions[:6]:
        pred_lines.append(
            f"  - {p.adverse_event} → {p.predicted_action} (conf {p.confidence}%, "
            f"window {p.predicted_date_start.isoformat()}–{p.predicted_date_end.isoformat()})"
        )

    memory_sources: list[str] = ["EventLog", "Profile"]
    if beliefs:
        memory_sources.append("Episodic")
    if predictions:
        memory_sources.append("Foresight")

    episodic_text = ""
    if evermemos_client:
        try:
            memories = await evermemos_client.search_memories(
                db, drug_id=drug_id, query=f"safety summary {quarter}", top_k=3
            )
            if memories:
                memory_sources.append("EverMemOS")
                snippets = [m.get("summary", m.get("content", ""))[:150] for m in memories[:3]]
                episodic_text = "\n".join(f"  - {s}" for s in snippets if s)
        except Exception:
            pass

    return {
        "drug_name": drug_name,
        "quarter": quarter,
        "n_reports": int(n_reports or 0),
        "n_detected": len(detected_events),
        "signal_data": "\n".join(signal_lines) or "  (no signal data)",
        "belief_summaries": "\n".join(belief_lines) or "  (no beliefs generated)",
        "fda_actions": "\n".join(fda_lines) or "  (none)",
        "delta_summary": "\n".join(delta_lines) or "  (first quarter — no prior data)",
        "foresight_data": "\n".join(pred_lines) or "  (no predictions yet)",
        "episodic_narratives": episodic_text or "  (not available)",
        "memory_sources": memory_sources,
        "beliefs": beliefs,
    }


def _build_prompt(ctx: dict[str, Any]) -> str:
    return f"""Drug: {ctx['drug_name']} | Quarter: {ctx['quarter']} | Reports: {ctx['n_reports']} | Detected signals: {ctx['n_detected']}

SIGNAL STATISTICS:
{ctx['signal_data']}

BELIEF ENGINE ASSESSMENTS:
{ctx['belief_summaries']}

EPISODIC MEMORY CONTEXT:
{ctx['episodic_narratives']}

FORESIGHT PREDICTIONS:
{ctx['foresight_data']}

FDA ACTIONS:
{ctx['fda_actions']}

QUARTER-OVER-QUARTER CHANGES:
{ctx['delta_summary']}

Write a concise safety brief (~150 words). Use markdown formatting.

Structure:
### Risk Posture
One paragraph: decisive risk assessment opening sentence, cite specific **ROR values**, **CI bounds**, **confidence percentages**, and **report counts** in bold. Explain how episodic memory or foresight predictions changed the interpretation beyond raw disproportionality math.

### Forward Look
One paragraph: name the single most important development this quarter, then close with a forward-looking sentence grounded in the foresight data.

Formatting rules:
- Use **bold** for drug names, adverse event names, and key statistics.
- Use bullet lists (- item) only if listing 3+ discrete signals or changes.
- No preamble, no hedging, no filler.

Return JSON only:
- "narrative": the markdown-formatted brief text (use \\n\\n between sections)
- "risk_level": one of "low", "moderate", "elevated", "high"
- "key_changes": exactly 3 strings, each under 15 words"""


def _call_gemini(settings: Settings, prompt: str) -> dict[str, Any] | None:
    if not settings.gemini_api_key:
        return None

    try:
        from google import genai
        from google.genai import types
    except Exception:
        return None

    client = genai.Client(api_key=settings.gemini_api_key)

    try:
        response = client.models.generate_content(
            model=settings.gemini_model_default,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SITUATION_SYSTEM_PROMPT,
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
    except Exception:
        logger.exception("Gemini call failed for situation analysis")
        return None

    raw = getattr(response, "text", None)
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def _call_gemini_with_timeout(
    settings: Settings,
    prompt: str,
) -> dict[str, Any] | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call_gemini, settings, prompt),
            timeout=SITUATION_GEMINI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Situation analysis Gemini call timed out after %.1fs",
            SITUATION_GEMINI_TIMEOUT_SECONDS,
        )
        return None
    except Exception:
        logger.exception("Situation analysis Gemini dispatch failed")
        return None


async def generate_situation_analysis(
    db: AsyncSession,
    *,
    settings: Settings,
    drug_id: str,
    quarter: str,
    evermemos_client: EvermemosClient | None = None,
) -> SituationAnalysis:
    ctx = await _gather_context(db, drug_id, quarter, evermemos_client)
    beliefs: list[BeliefRow] = ctx.pop("beliefs")
    current_hash = _compute_belief_hash(beliefs)

    existing = await db.scalar(
        select(SituationAnalysisRow).where(
            SituationAnalysisRow.drug_id == drug_id,
            SituationAnalysisRow.quarter == quarter,
        )
    )
    if (
        existing is not None
        and existing.belief_hash == current_hash
        and existing.narrative != FALLBACK_NARRATIVE
    ):
        return SituationAnalysis(
            id=str(existing.id),
            drug_id=existing.drug_id,
            quarter=existing.quarter,
            narrative=existing.narrative,
            risk_level=existing.risk_level,
            key_changes=list(existing.key_changes or []),
            memory_sources=list(existing.memory_sources or []),
            created_at=_as_iso(existing.created_at),
        )

    # Release the pooled database connection before the Gemini wait. Without this,
    # repeated brief generations can starve the async pool and stall unrelated routes.
    await db.rollback()

    prompt = _build_prompt(ctx)
    parsed = await _call_gemini_with_timeout(settings, prompt)

    if parsed and isinstance(parsed.get("narrative"), str):
        narrative = parsed["narrative"]
        risk_level = parsed.get("risk_level", "moderate")
        if risk_level not in ("low", "moderate", "elevated", "high"):
            risk_level = "moderate"
        key_changes = parsed.get("key_changes", [])
        if not isinstance(key_changes, list):
            key_changes = []
        key_changes = [str(c) for c in key_changes[:6]]
    else:
        narrative = FALLBACK_NARRATIVE
        n_detected = ctx["n_detected"]
        risk_level = "low" if n_detected == 0 else "moderate" if n_detected <= 2 else "elevated"
        key_changes = [f"{ctx['n_detected']} signals detected", f"{ctx['n_reports']} reports analyzed"]

    memory_sources = ctx["memory_sources"]
    now = datetime.now(timezone.utc)

    result = await db.execute(
        pg_insert(SituationAnalysisRow)
        .values(
            drug_id=drug_id,
            quarter=quarter,
            narrative=narrative,
            risk_level=risk_level,
            key_changes=key_changes,
            memory_sources=memory_sources,
            belief_hash=current_hash,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=[SituationAnalysisRow.drug_id, SituationAnalysisRow.quarter],
            set_={
                "narrative": narrative,
                "risk_level": risk_level,
                "key_changes": key_changes,
                "memory_sources": memory_sources,
                "belief_hash": current_hash,
                "created_at": now,
            },
        )
        .returning(SituationAnalysisRow.id)
    )
    row_id = result.scalar_one()
    await db.commit()

    return SituationAnalysis(
        id=str(row_id),
        drug_id=drug_id,
        quarter=quarter,
        narrative=narrative,
        risk_level=risk_level,
        key_changes=key_changes,
        memory_sources=memory_sources,
        created_at=_as_iso(now),
    )
