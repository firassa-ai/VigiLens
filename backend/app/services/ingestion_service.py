from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Belief, FaersReport, FaersReportDrug, IngestionState, Prediction
from app.schemas.ingest import AgentThought, IngestProgressMessage, IngestStatus
from app.services.belief_engine import BeliefGenerationResult, generate_tracked_beliefs_for_quarter
from app.services.drug_insights_service import post_ingest_digest
from app.services.evermemos_client import EvermemosClient
from app.services.ingest_progress_hub import IngestProgressHub
from app.services.prediction_engine import maybe_generate_predictions
from app.services.signal_engine import SignalUpdate, recompute_signals_after_ingestion
from app.utils.quarters import date_to_quarter, next_quarter, parse_quarter, quarter_to_dates, sort_quarters

MAX_MEMORY_PREVIEW_CHARS = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utcnow().isoformat().replace("+00:00", "Z")


def _truncate_preview(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= MAX_MEMORY_PREVIEW_CHARS:
        return cleaned
    if MAX_MEMORY_PREVIEW_CHARS <= 3:
        return cleaned[:MAX_MEMORY_PREVIEW_CHARS]
    return f"{cleaned[: MAX_MEMORY_PREVIEW_CHARS - 3].rstrip()}..."


def _quarter_token(quarter: str) -> str:
    return quarter.replace("-", "")


def _build_memory_preview_metadata(snippets: dict[str, str]) -> dict[str, Any] | None:
    preview_map = {
        memory_id: _truncate_preview(snippet)
        for memory_id, snippet in snippets.items()
        if isinstance(memory_id, str) and memory_id.strip() and isinstance(snippet, str) and snippet.strip()
    }
    if not preview_map:
        return None
    return {"memory_preview": preview_map}


def _build_signal_thoughts(
    *,
    quarter: str,
    total_reports: int,
    signal_updates: list[SignalUpdate],
) -> list[AgentThought]:
    thoughts: list[AgentThought] = [
        AgentThought(
            type="perceive",
            content=f"Ingesting {quarter}: {total_reports} new FAERS reports for this quarter.",
            timestamp=_now_iso(),
            metadata={"quarter": quarter, "reports_ingested": total_reports},
        ),
        AgentThought(
            type="tool",
            content=f"Running disproportionality engine (ROR/PRR) across {len(signal_updates)} tracked adverse events.",
            timestamp=_now_iso(),
            metadata={"tracked_events": len(signal_updates)},
        ),
    ]

    new_signals = [
        update for update in signal_updates if update.is_new_signal and update.signal_point.signal_detected
    ]
    if new_signals:
        for update in new_signals:
            signal = update.signal_point
            if signal.ror is None:
                detail = f"Statistical anomaly: {signal.adverse_event} crossed threshold."
            else:
                ci_lower = "-" if signal.ror_ci_lower is None else f"{signal.ror_ci_lower:.2f}"
                ci_upper = "-" if signal.ror_ci_upper is None else f"{signal.ror_ci_upper:.2f}"
                detail = (
                    f"Statistical anomaly: {signal.adverse_event} ROR {signal.ror:.2f} "
                    f"(CI {ci_lower}-{ci_upper}) - new signal detected."
                )
            thoughts.append(
                AgentThought(
                    type="perceive",
                    content=detail,
                    timestamp=_now_iso(),
                    metadata={
                        "signal": signal.adverse_event,
                        "ror": signal.ror,
                        "ror_ci_lower": signal.ror_ci_lower,
                        "ror_ci_upper": signal.ror_ci_upper,
                        "trajectory": signal.trajectory,
                        "report_count": signal.report_count,
                    },
                )
            )
    else:
        thoughts.append(
            AgentThought(
                type="perceive",
                content="No new threshold crossings this quarter; monitoring trajectory changes.",
                timestamp=_now_iso(),
            )
        )
    return thoughts


def _build_memory_write_thought(
    *,
    drug_id: str,
    quarter: str,
    posted: bool,
) -> AgentThought:
    quarter_token = _quarter_token(quarter)
    digest_id = f"vigl_{drug_id}_{quarter_token}_digest"
    profile_id = f"vigl_{drug_id}_{quarter_token}_profile"
    return AgentThought(
        type="memory_write",
        content=(
            f"Updating EverMemOS group vigl:{drug_id} for {quarter} "
            f"({'write confirmed' if posted else 'write failed'})."
        ),
        timestamp=_now_iso(),
        memory_refs=[digest_id, profile_id],
        metadata={
            "group_id": f"vigl:{drug_id}",
            "quarter": quarter,
            "posted": posted,
            "memory_preview": {
                digest_id: _truncate_preview(
                    f"Quarterly digest memory for {drug_id} {quarter} ingested evidence and signal summary."
                ),
                profile_id: _truncate_preview(
                    f"Profile memory update for {drug_id} {quarter} with refreshed risk-level and active signals."
                ),
            },
        },
    )


def _build_belief_thoughts(
    *,
    drug_id: str,
    quarter: str,
    posted: bool,
    tracked_results: list[BeliefGenerationResult],
) -> list[AgentThought]:
    thoughts: list[AgentThought] = []
    episodic_ids: list[str] = []
    snippet_map: dict[str, str] = {}
    foresight_ids: list[str] = []
    foresight_snippet_map: dict[str, str] = {}

    reinterpretation_count = 0
    reinterpretation_reason: str | None = None
    for result in tracked_results:
        for memory_id in result.trace.episodic_ids_used:
            if memory_id not in episodic_ids:
                episodic_ids.append(memory_id)
        for memory_id, snippet in result.trace.episodic_snippets.items():
            snippet_map.setdefault(memory_id, snippet)
        for memory_id in result.trace.foresight_ids_used:
            if memory_id not in foresight_ids:
                foresight_ids.append(memory_id)
        for memory_id, snippet in result.trace.foresight_snippets.items():
            foresight_snippet_map.setdefault(memory_id, snippet)
        if result.trace.reinterpretation_count > reinterpretation_count:
            reinterpretation_count = result.trace.reinterpretation_count
            reinterpretation_reason = result.trace.reinterpretation_reason

    if posted:
        thoughts.append(
            AgentThought(
                type="memory_query",
                content=(
                    "Querying EverMemOS episodic memory for tracked safety questions "
                    f"({drug_id}, {quarter})."
                ),
                timestamp=_now_iso(),
                metadata={
                    "quarter": quarter,
                    "drug_id": drug_id,
                    "query_scope": "tracked_beliefs",
                },
            )
        )
    elif not posted:
        thoughts.append(
            AgentThought(
                type="memory_query",
                content="EverMemOS unavailable - using local episodic context.",
                timestamp=_now_iso(),
                metadata={"fallback": "local_episodic_context"},
            )
        )

    if episodic_ids:
        thoughts.append(
            AgentThought(
                type="memory_recall",
                content=f"EPISODIC recall: retrieved {len(episodic_ids)} episodic memories for grounding.",
                timestamp=_now_iso(),
                memory_refs=episodic_ids,
                metadata={
                    "count": len(episodic_ids),
                    **(_build_memory_preview_metadata(snippet_map) or {}),
                },
            )
        )
    elif posted:
        thoughts.append(
            AgentThought(
                type="memory_recall",
                content="EPISODIC recall: retrieved 0 episodic memories; continuing with local context.",
                timestamp=_now_iso(),
                metadata={"count": 0},
            )
        )

    if foresight_ids:
        thoughts.append(
            AgentThought(
                type="foresight",
                content=(
                    f"FORESIGHT recall: retrieved {len(foresight_ids)} foresight memories for regulatory horizon calibration."
                ),
                timestamp=_now_iso(),
                memory_refs=foresight_ids,
                metadata={
                    "count": len(foresight_ids),
                    **(_build_memory_preview_metadata(foresight_snippet_map) or {}),
                },
            )
        )
    else:
        thoughts.append(
            AgentThought(
                type="foresight",
                content="FORESIGHT recall: no linked foresight memories for this quarter.",
                timestamp=_now_iso(),
            )
        )

    thoughts.append(
        AgentThought(
            type="reasoning",
            content="Evaluating precursor relationships and quarter-over-quarter belief shifts.",
            timestamp=_now_iso(),
            metadata={"tracked_questions": len(tracked_results)},
        )
    )

    if reinterpretation_count > 0:
        thoughts.append(
            AgentThought(
                type="reinterpretation",
                content=(
                    "Retroactive reinterpretation triggered: "
                    f"{reinterpretation_count} earlier reports reclassified as precursor-linked."
                ),
                timestamp=_now_iso(),
                metadata={
                    "reinterpreted_count": reinterpretation_count,
                    "reason": reinterpretation_reason,
                },
            )
        )
    return thoughts


def _build_done_thoughts(
    *,
    drug_id: str,
    quarter: str,
    tracked_results: list[BeliefGenerationResult],
    created_predictions: list[Prediction],
) -> list[AgentThought]:
    thoughts: list[AgentThought] = []
    if created_predictions:
        for prediction in created_predictions:
            memory_id = f"vigl_{drug_id}_{_quarter_token(prediction.created_at_quarter)}_foresight"
            predicted_action = prediction.predicted_action.replace("_", " ")
            thoughts.append(
                AgentThought(
                    type="foresight",
                    content=(
                        f"Prediction generated: {prediction.adverse_event} {predicted_action} "
                        f"(confidence: {prediction.confidence}%)."
                    ),
                    timestamp=_now_iso(),
                    memory_refs=[memory_id],
                    metadata={
                        "adverse_event": prediction.adverse_event,
                        "predicted_action": prediction.predicted_action,
                        "confidence": prediction.confidence,
                        "predicted_date_start": prediction.predicted_date_start.isoformat(),
                        "predicted_date_end": prediction.predicted_date_end.isoformat(),
                        "memory_preview": {
                            memory_id: _truncate_preview(
                                f"Foresight memory for {prediction.adverse_event} {predicted_action}; "
                                f"confidence {prediction.confidence}%."
                            )
                        },
                    },
                )
            )
    else:
        thoughts.append(
            AgentThought(
                type="foresight",
                content="No new regulatory foresight was generated this quarter.",
                timestamp=_now_iso(),
            )
        )

    thoughts.append(
        AgentThought(
            type="action",
            content=(
                f"Belief state updated for {quarter}. "
                f"{len(tracked_results)} tracked beliefs refreshed."
            ),
            timestamp=_now_iso(),
            metadata={
                "quarter": quarter,
                "tracked_beliefs": len(tracked_results),
                "new_predictions": len(created_predictions),
            },
        )
    )
    return thoughts


def _quarter_leq(left: str, right: str) -> bool:
    return parse_quarter(left) <= parse_quarter(right)


def _quarter_span_count(first_quarter: str | None, last_quarter: str | None) -> int:
    if first_quarter is None or last_quarter is None:
        return 0
    first = parse_quarter(first_quarter)
    last = parse_quarter(last_quarter)
    if last < first:
        return 0
    return (last[0] - first[0]) * 4 + (last[1] - first[1]) + 1


async def _available_quarter_bounds(db: AsyncSession, drug_id: str) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(
                func.min(FaersReport.receivedate),
                func.max(FaersReport.receivedate),
            )
            .select_from(FaersReport)
            .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
            .where(
                FaersReportDrug.drug_id == drug_id,
                FaersReportDrug.role == "suspect",
            )
        )
    ).first()

    if row is None or row[0] is None or row[1] is None:
        return None, None

    return date_to_quarter(row[0]), date_to_quarter(row[1])


def _next_quarter_capped(current_quarter: str, last_available_quarter: str | None) -> str | None:
    candidate = next_quarter(current_quarter)
    if last_available_quarter is None:
        return None
    if _quarter_leq(candidate, last_available_quarter):
        return candidate
    return None


async def _get_state(db: AsyncSession, drug_id: str, lock: bool = False) -> IngestionState:
    stmt = select(IngestionState).where(IngestionState.drug_id == drug_id)
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise AppError(
            error="BadRequest",
            detail=f"drug_id '{drug_id}' not found",
            status_code=400,
        )
    return row


async def _count_reports_for_quarter(db: AsyncSession, drug_id: str, quarter: str) -> int:
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


async def _count_total_reports_loaded(
    db: AsyncSession,
    drug_id: str,
    quarters_loaded: list[str],
) -> int:
    if not quarters_loaded:
        return 0

    ranges = [quarter_to_dates(quarter) for quarter in quarters_loaded]
    date_predicates = [
        and_(FaersReport.receivedate >= start_date, FaersReport.receivedate <= end_date)
        for start_date, end_date in ranges
    ]

    value = await db.scalar(
        select(func.count(func.distinct(FaersReport.safetyreportid)))
        .select_from(FaersReport)
        .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
        .where(
            FaersReportDrug.drug_id == drug_id,
            FaersReportDrug.role == "suspect",
            or_(*date_predicates),
        )
    )
    return int(value or 0)


async def get_ingest_status(db: AsyncSession, drug_id: str = "semaglutide") -> IngestStatus:
    state = await _get_state(db, drug_id)
    quarters_loaded = sort_quarters(list(state.quarters_loaded or []))
    total_reports_loaded = await _count_total_reports_loaded(db, drug_id, quarters_loaded)
    first_available_quarter, last_available_quarter = await _available_quarter_bounds(db, drug_id)
    total_quarters_available = _quarter_span_count(first_available_quarter, last_available_quarter)

    return IngestStatus(
        drug_id=drug_id,
        quarters_loaded=quarters_loaded,
        next_quarter=state.next_quarter,
        total_reports_loaded=total_reports_loaded,
        total_quarters_available=total_quarters_available,
        evermemos_status=state.evermemos_status,
    )


async def _update_ingestion_state(
    db: AsyncSession,
    *,
    drug_id: str,
    quarters_loaded: list[str],
    next_q: str | None,
    evermemos_status: str,
) -> None:
    await db.execute(
        update(IngestionState)
        .where(IngestionState.drug_id == drug_id)
        .values(
            quarters_loaded=quarters_loaded,
            next_quarter=next_q,
            evermemos_status=evermemos_status,
            updated_at=_utcnow(),
        )
    )


async def ingest_next_quarter(
    db: AsyncSession,
    hub: IngestProgressHub,
    settings: Settings,
    evermemos_client: EvermemosClient,
    drug_id: str,
) -> IngestStatus:
    state = await _get_state(db, drug_id, lock=True)

    if state.evermemos_status in {"ingesting", "consolidating"}:
        raise AppError(
            error="Conflict",
            detail=f"ingestion for drug_id '{drug_id}' is already in progress",
            status_code=409,
        )

    quarter = state.next_quarter
    if quarter is None:
        raise AppError(
            error="BadRequest",
            detail=f"no more quarters available for drug_id '{drug_id}'",
            status_code=400,
        )

    _, last_available_quarter = await _available_quarter_bounds(db, drug_id)

    quarters_loaded = sort_quarters([*(state.quarters_loaded or []), quarter])
    next_q = _next_quarter_capped(quarter, last_available_quarter)
    await _update_ingestion_state(
        db,
        drug_id=drug_id,
        quarters_loaded=quarters_loaded,
        next_q=next_q,
        evermemos_status="ingesting",
    )
    await db.commit()

    total_reports = await _count_reports_for_quarter(db, drug_id, quarter)

    await hub.broadcast(
        drug_id,
        IngestProgressMessage(
            phase="starting",
            quarter=quarter,
            reports_processed=0,
            total_reports=total_reports,
            signals_updated=0,
            evermemos_consolidation_status="idle",
            thoughts=[
                AgentThought(
                    type="perceive",
                    content=f"Ingesting {quarter}: preparing quarter pipeline.",
                    timestamp=_now_iso(),
                    metadata={"quarter": quarter},
                )
            ],
        ),
    )

    await hub.broadcast(
        drug_id,
        IngestProgressMessage(
            phase="loading_reports",
            quarter=quarter,
            reports_processed=total_reports,
            total_reports=total_reports,
            signals_updated=0,
            evermemos_consolidation_status="idle",
            thoughts=[
                AgentThought(
                    type="tool",
                    content=f"Loaded {total_reports} FAERS reports for {quarter}.",
                    timestamp=_now_iso(),
                    metadata={"quarter": quarter, "reports_loaded": total_reports},
                )
            ],
        ),
    )

    try:
        signal_updates = await recompute_signals_after_ingestion(
            db,
            drug_id=drug_id,
            quarter=quarter,
            settings=settings,
        )
        created_predictions = await maybe_generate_predictions(
            db,
            drug_id=drug_id,
            quarter=quarter,
            evermemos_client=evermemos_client,
            settings=settings,
        )
        await db.commit()

        await hub.broadcast(
            drug_id,
            IngestProgressMessage(
                phase="computing_signals",
                quarter=quarter,
                reports_processed=total_reports,
                total_reports=total_reports,
                signals_updated=len(signal_updates),
                evermemos_consolidation_status="idle",
                thoughts=_build_signal_thoughts(
                    quarter=quarter,
                    total_reports=total_reports,
                    signal_updates=signal_updates,
                ),
            ),
        )

        await _update_ingestion_state(
            db,
            drug_id=drug_id,
            quarters_loaded=quarters_loaded,
            next_q=next_q,
            evermemos_status="consolidating",
        )
        await db.commit()

        await hub.broadcast(
            drug_id,
            IngestProgressMessage(
                phase="posting_evermemos",
                quarter=quarter,
                reports_processed=total_reports,
                total_reports=total_reports,
                signals_updated=len(signal_updates),
                evermemos_consolidation_status="posting",
                thoughts=[
                    AgentThought(
                        type="tool",
                        content=f"Posting {quarter} digest to EverMemOS.",
                        timestamp=_now_iso(),
                        metadata={"group_id": f"vigl:{drug_id}", "quarter": quarter},
                    )
                ],
            ),
        )
        posted = await post_ingest_digest(
            db,
            evermemos_client=evermemos_client,
            drug_id=drug_id,
            quarter=quarter,
        )

        tracked_results = await generate_tracked_beliefs_for_quarter(
            db,
            settings=settings,
            drug_id=drug_id,
            quarter=quarter,
            evermemos_client=evermemos_client,
        )
        await db.commit()

        await hub.broadcast(
            drug_id,
            IngestProgressMessage(
                phase="generating_beliefs",
                quarter=quarter,
                reports_processed=total_reports,
                total_reports=total_reports,
                signals_updated=len(signal_updates),
                evermemos_consolidation_status="ready" if posted else "failed",
                thoughts=[
                    _build_memory_write_thought(
                        drug_id=drug_id,
                        quarter=quarter,
                        posted=posted,
                    ),
                    *_build_belief_thoughts(
                        drug_id=drug_id,
                        quarter=quarter,
                        posted=posted,
                        tracked_results=tracked_results,
                    ),
                ],
            ),
        )

        await _update_ingestion_state(
            db,
            drug_id=drug_id,
            quarters_loaded=quarters_loaded,
            next_q=next_q,
            evermemos_status="ready",
        )
        await db.commit()

        await hub.broadcast(
            drug_id,
            IngestProgressMessage(
                phase="done",
                quarter=quarter,
                reports_processed=total_reports,
                total_reports=total_reports,
                signals_updated=len(signal_updates),
                evermemos_consolidation_status="ready",
                thoughts=_build_done_thoughts(
                    drug_id=drug_id,
                    quarter=quarter,
                    tracked_results=tracked_results,
                    created_predictions=created_predictions,
                ),
            ),
        )
    except Exception as exc:
        await db.rollback()
        await _update_ingestion_state(
            db,
            drug_id=drug_id,
            quarters_loaded=quarters_loaded,
            next_q=quarter,
            evermemos_status="ready",
        )
        await db.commit()

        await hub.broadcast(
            drug_id,
            IngestProgressMessage(
                phase="error",
                quarter=quarter,
                reports_processed=0,
                total_reports=total_reports,
                signals_updated=0,
                evermemos_consolidation_status="failed",
                detail=str(exc),
            ),
        )
        raise

    return await get_ingest_status(db, drug_id)


async def reset_ingestion(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
    hard: bool,
) -> IngestStatus:
    await _get_state(db, drug_id)
    first_available_quarter, _ = await _available_quarter_bounds(db, drug_id)

    await db.execute(delete(Belief).where(Belief.drug_id == drug_id))
    await db.execute(delete(Prediction).where(Prediction.drug_id == drug_id))
    await _update_ingestion_state(
        db,
        drug_id=drug_id,
        quarters_loaded=[],
        next_q=first_available_quarter,
        evermemos_status="idle",
    )
    await db.commit()

    if hard:
        try:
            await evermemos_client.delete_group_memories(db, drug_id=drug_id)
        except Exception:
            # Best-effort by contract: reset must succeed even if EverMemOS is unavailable.
            pass

    return await get_ingest_status(db, drug_id)
