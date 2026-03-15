from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_SETTINGS, Settings
from app.db.models import (
    FaersReport,
    FaersReportDrug,
    FaersReportReaction,
    Prediction as PredictionRow,
    QuarterlyStat,
)
from app.schemas.shared import (
    Prediction as PredictionSchema,
    PredictionBasis,
    PredictionSupportingEvent,
    PredictionVerification,
    ScopeRef,
)
from app.services.evidence_service import evidence_api_path_for_report
from app.services.evermemos_client import EvermemosClient
from app.services.forecast_policy import (
    classify_generic_forecast,
    is_strict_demo_drug,
    method_vote_count,
)
from app.services.prediction_verification_service import (
    resolve_prediction_verification,
)
from app.utils.quarters import parse_quarter, quarter_to_dates

HIGH_STAKES_EVENTS = {"Ileus", "Gastroparesis"}
SUPPORTING_EVIDENCE_LIMIT = 3


def _prediction_confidence(row: QuarterlyStat) -> int:
    score = 45
    if row.ror_ci_lower is not None:
        score += min(30, int((row.ror_ci_lower - 1.0) * 12))
    score += min(20, row.cumulative_count // 4)
    if row.trajectory in {"emerging", "accelerating"}:
        score += 8
    if row.consensus_tier == "public_signal":
        score += 8
    if row.priority_flag:
        score += 6
    return max(45, min(95, score))


def _row_method_vote_count(row: QuarterlyStat) -> int:
    return method_vote_count(dict(row.method_votes or {}))


async def _existing_prediction(
    db: AsyncSession,
    *,
    drug_id: str,
    adverse_event: str,
) -> PredictionRow | None:
    return await db.scalar(
        select(PredictionRow).where(
            PredictionRow.drug_id == drug_id,
            PredictionRow.adverse_event == adverse_event,
        ).order_by(PredictionRow.created_at.desc())
    )


def _quarter_at_least(current_quarter: str, threshold: str) -> bool:
    return parse_quarter(current_quarter) >= parse_quarter(threshold)


def _display_label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


def _prediction_scope(drug_id: str) -> ScopeRef:
    return ScopeRef(
        type="drug",
        key=drug_id,
        label=_display_label(drug_id),
    )


def _supporting_event_name(prediction: PredictionRow) -> str:
    if prediction.drug_id == "semaglutide" and prediction.adverse_event == "Ileus":
        if prediction.created_at_quarter == "2022-Q4" and prediction.predicted_action == "label_change":
            return "Constipation"
    return prediction.adverse_event


def _prediction_basis(prediction: PredictionRow) -> PredictionBasis:
    supporting_event = _supporting_event_name(prediction)
    quarter = prediction.created_at_quarter
    if prediction.track == "proof":
        return PredictionBasis(
            type="threshold_crossing",
            summary=(
                f"{supporting_event} reached multi-method consensus by {quarter} and aligns with "
                "externally corroborated safety evidence, so VigiLens surfaced it as a proof-backed signal."
            ),
        )
    if prediction.trigger_basis == "cross_signal_precursor":
        return PredictionBasis(
            type="cross_signal_guardrail",
            summary=(
                f"{supporting_event} stayed elevated by {quarter}, so the precursor rule opened a "
                f"{prediction.predicted_action.replace('_', ' ')} forecast for {prediction.adverse_event}."
            ),
        )
    if prediction.trigger_basis == "serious_event_sentinel":
        return PredictionBasis(
            type="sentinel_report_guardrail",
            summary=(
                f"{supporting_event} met the priority-review threshold by {quarter}, so VigiLens "
                f"opened a serious-event {prediction.predicted_action.replace('_', ' ')} forecast."
            ),
        )
    if prediction.trigger_basis == "label_gap_escalation":
        return PredictionBasis(
            type="label_gap_escalation",
            summary=(
                f"{supporting_event} reached multi-method consensus by {quarter} and appears to outrun "
                "current label coverage, so VigiLens escalated it into a label-focused forecast."
            ),
        )
    return PredictionBasis(
        type="threshold_crossing" if prediction.trigger_basis == "threshold_crossing" else "signal_threshold",
        summary=(
            f"{supporting_event} met the deterministic signal threshold by {quarter}, "
            f"supporting a {prediction.predicted_action.replace('_', ' ')} forecast."
        ),
    )


async def _supporting_event_terms(
    db: AsyncSession,
    *,
    drug_id: str,
    adverse_event: str,
    quarter: str,
) -> list[str]:
    row = await db.scalar(
        select(QuarterlyStat).where(
            QuarterlyStat.drug_id == drug_id,
            QuarterlyStat.quarter == quarter,
            QuarterlyStat.adverse_event == adverse_event,
        )
    )
    if row is not None and row.supporting_terms:
        return list(row.supporting_terms)
    return [adverse_event]


async def _supporting_event_report_ids(
    db: AsyncSession,
    *,
    drug_id: str,
    adverse_event: str,
    quarter: str,
) -> list[str]:
    _, quarter_end = quarter_to_dates(quarter)
    supporting_terms = await _supporting_event_terms(
        db,
        drug_id=drug_id,
        adverse_event=adverse_event,
        quarter=quarter,
    )
    return (
        (
            await db.execute(
                select(FaersReportReaction.safetyreportid)
                .select_from(FaersReportReaction)
                .join(FaersReport, FaersReport.safetyreportid == FaersReportReaction.safetyreportid)
                .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
                .where(
                    FaersReportDrug.drug_id == drug_id,
                    FaersReportDrug.role == "suspect",
                    FaersReportReaction.meddra_pt.in_(supporting_terms),
                    FaersReport.receivedate <= quarter_end,
                )
                .group_by(FaersReportReaction.safetyreportid, FaersReport.receivedate)
                .order_by(FaersReport.receivedate.asc(), FaersReportReaction.safetyreportid.asc())
                .limit(SUPPORTING_EVIDENCE_LIMIT)
            )
        )
        .scalars()
        .all()
    )


async def _build_supporting_event(
    db: AsyncSession,
    prediction: PredictionRow,
) -> PredictionSupportingEvent:
    supporting_event_name = _supporting_event_name(prediction)
    stat_row = await db.scalar(
        select(QuarterlyStat).where(
            QuarterlyStat.drug_id == prediction.drug_id,
            QuarterlyStat.quarter == prediction.created_at_quarter,
            QuarterlyStat.adverse_event == supporting_event_name,
        )
    )
    report_ids = await _supporting_event_report_ids(
        db,
        drug_id=prediction.drug_id,
        adverse_event=supporting_event_name,
        quarter=prediction.created_at_quarter,
    )
    return PredictionSupportingEvent(
        adverse_event=supporting_event_name,
        quarter=prediction.created_at_quarter,
        trajectory=stat_row.trajectory if stat_row is not None else None,
        cumulative_count=stat_row.cumulative_count if stat_row is not None else None,
        evidence_report_ids=list(report_ids),
        evidence_api_paths=[evidence_api_path_for_report(report_id) for report_id in report_ids],
    )


async def build_prediction_schema(
    db: AsyncSession,
    prediction: PredictionRow,
    *,
    settings: Settings = DEFAULT_SETTINGS,
    verification: PredictionVerification | None = None,
    resolve_verification: bool = True,
) -> PredictionSchema:
    if verification is None and resolve_verification and not is_strict_demo_drug(prediction.drug_id):
        verification = await resolve_prediction_verification(
            db,
            prediction=prediction,
            settings=settings,
        )
    supporting_event = await _build_supporting_event(db, prediction)
    return PredictionSchema(
        id=str(prediction.id),
        drug_id=prediction.drug_id,
        adverse_event=prediction.adverse_event,
        predicted_action=prediction.predicted_action,
        confidence=prediction.confidence,
        predicted_date_range=(
            prediction.predicted_date_start.isoformat(),
            prediction.predicted_date_end.isoformat(),
        ),
        created_at_quarter=prediction.created_at_quarter,
        visibility=prediction.visibility,
        track=prediction.track,
        novelty_status=prediction.novelty_status,
        evidence_grade=prediction.evidence_grade,
        trigger_basis=prediction.trigger_basis,
        label_gap=bool(prediction.label_gap),
        basis=_prediction_basis(prediction),
        scope=_prediction_scope(prediction.drug_id),
        supporting_event=supporting_event,
        verification=verification,
    )


def _generic_prediction_action(
    row: QuarterlyStat,
    *,
    track: str,
) -> str:
    if track == "proof":
        return "safety_communication"
    if row.priority_flag:
        return "warning"
    if row.label_status == "label_gap":
        return "label_change"
    return "safety_communication"


def _generic_prediction_visibility(row: QuarterlyStat) -> str:
    if row.consensus_tier == "public_signal":
        return "public"
    if row.consensus_tier == "priority_review" and (row.priority_flag or row.label_status == "label_gap"):
        return "public"
    return "watchlist"


def _generic_prediction_visibility_for_track(
    row: QuarterlyStat,
    *,
    track: str,
    novelty_status: str,
) -> str:
    if track == "proof":
        if row.consensus_tier in {"public_signal", "priority_review"}:
            return "public"
        if novelty_status == "known_label" and _row_method_vote_count(row) >= 2 and row.cumulative_count >= 25:
            return "public"
        return "watchlist"
    if row.consensus_tier == "public_signal":
        return "public"
    if row.consensus_tier == "priority_review" and (row.priority_flag or row.label_status == "label_gap"):
        return "public"
    return "watchlist"


def _generic_prediction_basis(
    row: QuarterlyStat,
    *,
    track: str,
) -> str:
    if track == "proof":
        return "threshold_crossing"
    if row.priority_flag:
        return "serious_event_sentinel"
    if row.label_status == "label_gap":
        return "label_gap_escalation"
    return "threshold_crossing"


def _generic_evidence_grade(row: QuarterlyStat) -> str:
    if row.consensus_tier == "public_signal" and row.trajectory == "accelerating":
        return "strong"
    if row.consensus_tier in {"public_signal", "priority_review"}:
        return "moderate"
    return "exploratory"


def _is_broad_generic_candidate(row: QuarterlyStat) -> bool:
    classification = classify_generic_forecast(
        drug_id=row.drug_id,
        adverse_event=row.adverse_event,
        label_status=row.label_status,
    )
    if classification.suppress_public:
        return False
    vote_count = _row_method_vote_count(row)
    return (
        row.consensus_tier in {"watchlist", "priority_review", "public_signal"}
        and row.trajectory in {"emerging", "accelerating", "stable"}
        and row.cumulative_count >= 3
        and (vote_count >= 2 or (row.priority_flag and vote_count >= 1))
        and (
            row.term_level == "family"
            or row.priority_flag
            or row.label_status == "label_gap"
            or vote_count >= 3
        )
    )


def _apply_verification_adjustments(
    prediction: PredictionRow,
    *,
    verification: PredictionVerification | None,
) -> None:
    if verification is None or verification.status == "not_run":
        return
    if verification.status == "supported":
        prediction.confidence = min(95, prediction.confidence + 5)
        return
    if verification.status == "mixed":
        if prediction.track == "proof" and prediction.novelty_status == "known_label":
            if prediction.visibility == "public":
                prediction.visibility = "watchlist"
            prediction.confidence = max(40, prediction.confidence - 4)
            return
        prediction.confidence = max(45, prediction.confidence)
        return
    if verification.status == "unverified":
        if prediction.track == "proof" or prediction.visibility == "public":
            prediction.visibility = "watchlist"
        prediction.confidence = max(35, prediction.confidence - 8)
        if prediction.evidence_grade == "strong":
            prediction.evidence_grade = "moderate"


def _public_visibility_rank(value: str) -> int:
    return 1 if value == "public" else 0


async def maybe_generate_predictions(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter: str,
    evermemos_client: EvermemosClient | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> list[PredictionRow]:
    created: list[PredictionRow] = []
    resolved_verifications: dict[str, PredictionVerification | None] = {}
    strict_demo = is_strict_demo_drug(drug_id)

    # Remove legacy pancreatitis forecasts from prior deterministic logic.
    await db.execute(
        delete(PredictionRow).where(
            PredictionRow.drug_id == drug_id,
            PredictionRow.adverse_event == "Pancreatitis",
        )
    )

    rows = (
        (
            await db.execute(
                select(QuarterlyStat).where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == quarter,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return created

    # Primary deterministic pathway from active high-stakes event signals.
    for row in rows:
        if row.adverse_event not in HIGH_STAKES_EVENTS:
            continue
        if not row.signal_detected:
            continue
        if row.trajectory not in {"emerging", "accelerating", "stable"}:
            continue
        if row.cumulative_count < 3:
            continue
        if row.ror_ci_lower is None or row.ror_ci_lower < 1.2:
            continue
        if await _existing_prediction(db, drug_id=drug_id, adverse_event=row.adverse_event):
            continue

        start_date, _ = quarter_to_dates(quarter)
        prediction = PredictionRow(
            drug_id=drug_id,
            adverse_event=row.adverse_event,
            predicted_action="label_change",
            confidence=_prediction_confidence(row),
            predicted_date_start=start_date,
            predicted_date_end=start_date + timedelta(days=365),
            created_at_quarter=quarter,
            visibility="public",
            track="receipt",
            novelty_status="label_gap" if row.label_status == "label_gap" else "known_label",
            evidence_grade="moderate",
            trigger_basis="threshold_crossing",
            label_gap=False,
        )
        db.add(prediction)
        created.append(prediction)

    # Secondary deterministic guardrail:
    # if constipation is strongly elevated by late timeline, emit an Ileus label-change forecast.
    if drug_id == "semaglutide" and not await _existing_prediction(db, drug_id=drug_id, adverse_event="Ileus"):
        constipation = next((item for item in rows if item.adverse_event == "Constipation"), None)
        if (
            constipation is not None
            and _quarter_at_least(quarter, "2022-Q4")
            and constipation.ror_ci_lower is not None
            and constipation.ror_ci_lower >= 2.85
            and constipation.cumulative_count >= 20
        ):
            prediction = PredictionRow(
                drug_id=drug_id,
                adverse_event="Ileus",
                predicted_action="label_change",
                confidence=72,
                predicted_date_start=quarter_to_dates("2023-Q2")[0],
                predicted_date_end=quarter_to_dates("2024-Q1")[1],
                created_at_quarter=quarter,
                visibility="public",
                track="receipt",
                novelty_status="label_gap",
                evidence_grade="strong",
                trigger_basis="cross_signal_precursor",
                label_gap=False,
            )
            db.add(prediction)
            created.append(prediction)

    # Tertiary deterministic guardrail:
    # if suicidal ideation reports appear in the investigation window, emit a safety communication forecast.
    if drug_id == "semaglutide" and not await _existing_prediction(db, drug_id=drug_id, adverse_event="Suicidal ideation"):
        suicidal = next((item for item in rows if item.adverse_event == "Suicidal ideation"), None)
        if suicidal is not None and _quarter_at_least(quarter, "2023-Q2") and suicidal.cumulative_count >= 1:
            prediction = PredictionRow(
                drug_id=drug_id,
                adverse_event="Suicidal ideation",
                predicted_action="safety_communication",
                confidence=68,
                predicted_date_start=quarter_to_dates("2023-Q3")[0],
                predicted_date_end=quarter_to_dates("2024-Q2")[1],
                created_at_quarter=quarter,
                visibility="public",
                track="receipt",
                novelty_status="label_gap",
                evidence_grade="moderate",
                trigger_basis="serious_event_sentinel",
                label_gap=False,
            )
            db.add(prediction)
            created.append(prediction)

    candidate_pool = [
        row
        for row in rows
        if (
            row.consensus_tier in {"watchlist", "priority_review", "public_signal"}
            and row.trajectory in {"emerging", "accelerating", "stable"}
            and row.cumulative_count >= 3
            and (row.term_level == "family" or row.priority_flag)
        )
    ]
    if not strict_demo:
        candidate_pool = [row for row in rows if _is_broad_generic_candidate(row)]

    candidate_rows = [
        (
            row,
            classify_generic_forecast(
                drug_id=drug_id,
                adverse_event=row.adverse_event,
                label_status=row.label_status,
            ),
        )
        for row in candidate_pool
    ]
    candidate_rows = sorted(
        candidate_rows,
        key=lambda item: (
            1 if item[1].track == "proof" else 0,
            0 if item[0].term_level == "family" else 1,
            item[0].consensus_tier != "public_signal",
            -_row_method_vote_count(item[0]),
            -(item[0].ror_ci_lower or -1),
            -item[0].report_count,
            item[0].adverse_event,
        ),
    )[:4]

    for row, classification in candidate_rows:
        existing = await _existing_prediction(db, drug_id=drug_id, adverse_event=row.adverse_event)
        visibility = _generic_prediction_visibility_for_track(
            row,
            track=classification.track,
            novelty_status=classification.novelty_status,
        )
        predicted_action = _generic_prediction_action(
            row,
            track=classification.track,
        )
        trigger_basis = _generic_prediction_basis(
            row,
            track=classification.track,
        )
        if existing is not None:
            if (
                _public_visibility_rank(existing.visibility) >= _public_visibility_rank(visibility)
                and existing.track == classification.track
                and existing.novelty_status == classification.novelty_status
                and existing.predicted_action == predicted_action
            ):
                continue
            existing.predicted_action = predicted_action
            existing.confidence = _prediction_confidence(row)
            existing.predicted_date_start = quarter_to_dates(quarter)[0]
            existing.predicted_date_end = quarter_to_dates(quarter)[0] + timedelta(days=365)
            existing.created_at_quarter = quarter
            existing.visibility = visibility
            existing.track = classification.track
            existing.novelty_status = classification.novelty_status
            existing.evidence_grade = _generic_evidence_grade(row)
            existing.trigger_basis = trigger_basis
            existing.label_gap = row.label_status == "label_gap"
            created.append(existing)
            continue

        start_date, _ = quarter_to_dates(quarter)
        prediction = PredictionRow(
            drug_id=drug_id,
            adverse_event=row.adverse_event,
            predicted_action=predicted_action,
            confidence=_prediction_confidence(row),
            predicted_date_start=start_date,
            predicted_date_end=start_date + timedelta(days=365),
            created_at_quarter=quarter,
            visibility=visibility,
            track=classification.track,
            novelty_status=classification.novelty_status,
            evidence_grade=_generic_evidence_grade(row),
            trigger_basis=trigger_basis,
            label_gap=row.label_status == "label_gap",
        )
        db.add(prediction)
        created.append(prediction)

    if created:
        await db.flush()
        if not strict_demo:
            for prediction in created:
                verification = await resolve_prediction_verification(
                    db,
                    prediction=prediction,
                    settings=settings,
                )
                resolved_verifications[str(prediction.id)] = verification
                _apply_verification_adjustments(
                    prediction,
                    verification=verification,
                )

    if created and evermemos_client is not None:
        for prediction in created:
            if prediction.visibility != "public":
                continue
            verification = resolved_verifications.get(str(prediction.id))
            prediction_schema = await build_prediction_schema(
                db,
                prediction,
                settings=settings,
                verification=verification,
                resolve_verification=False,
            )
            foresight_data = {
                "prediction": f"{prediction.adverse_event} {prediction.predicted_action}",
                "confidence": prediction.confidence,
                "time_range": [
                    prediction.predicted_date_start.isoformat(),
                    prediction.predicted_date_end.isoformat(),
                ],
                "created_at_quarter": prediction.created_at_quarter,
                "track": prediction.track,
                "novelty_status": prediction.novelty_status,
                "basis": prediction_schema.basis.model_dump(),
                "scope": prediction_schema.scope.model_dump(),
                "supporting_event": prediction_schema.supporting_event.model_dump(),
            }
            if prediction_schema.verification is not None:
                foresight_data["verification"] = prediction_schema.verification.model_dump()
            await evermemos_client.store_foresight_memory(
                db,
                drug_id=drug_id,
                foresight_data=foresight_data,
            )

    return created
