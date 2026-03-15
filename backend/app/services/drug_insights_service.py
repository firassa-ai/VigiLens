from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import logging
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import and_, case, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_SETTINGS, Settings
from app.core.errors import AppError
from app.db.session import get_session_factory
from app.db.models import (
    Drug,
    EvermemosRequest,
    FdaAction,
    FaersReport,
    FaersReportDrug,
    FaersReportReaction,
    IngestionState,
    Prediction as PredictionRow,
    QuarterlyStat,
    TrackingJob,
)
from app.schemas.shared import (
    DeleteDrugResponse,
    CasefileSummary,
    Drug as DrugSchema,
    DrugProfile,
    EpisodicSummary,
    FDAAction,
    ForesightMemoryStatus,
    Prediction,
    ScorecardEntry,
    SignalPoint,
    ScopeRef,
)
from app.services.evidence_service import fetch_quarter_evidence_reports
from app.services.evermemos_client import EvermemosClient
from app.services.prediction_engine import build_prediction_schema
from app.services.forecast_policy import is_strict_demo_drug
from app.services.signal_catalog import consensus_tier_rank
from app.utils.quarter_extraction import extract_quarters_from_text
from app.utils.quarters import parse_quarter, quarter_minus_one, quarter_to_dates, sort_quarters

DISCLAIMER_SENTENCE = (
    "FAERS limitation: spontaneous reports are unverified, can include under-reporting and duplicates, "
    "and cannot establish causality or incidence."
)

logger = logging.getLogger(__name__)
GROUNDING_SCORECARD_ENDPOINT = "GEMINI_GROUNDING_SCORECARD_VERIFY"
MAX_EVENT_LOG_MEMORY_WRITES_PER_QUARTER = 2
FDA_SOURCE_URL_REWRITES = {
    "https://www.fda.gov/drugs/drug-safety-and-availability/update-fdas-ongoing-evaluation-reports-suicidal-thoughts-or-actions-patients-taking":
    "https://www.fda.gov/drugs/drug-safety-and-availability/update-fdas-ongoing-evaluation-reports-suicidal-thoughts-or-actions-patients-taking-certain-type",
}


@dataclass
class GroundedAction:
    action: FDAAction
    action_date: date


async def _get_drug_and_state(db: AsyncSession, drug_id: str) -> tuple[Drug, IngestionState]:
    drug = await db.scalar(select(Drug).where(Drug.id == drug_id))
    if drug is None:
        raise AppError(error="BadRequest", detail=f"drug_id '{drug_id}' not found", status_code=400)

    state = await db.scalar(select(IngestionState).where(IngestionState.drug_id == drug_id))
    if state is None:
        raise AppError(error="BadRequest", detail=f"drug_id '{drug_id}' not found", status_code=400)

    return drug, state


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_date(value: date) -> str:
    return value.isoformat()


def _normalize_source_url(value: str) -> str:
    cleaned = value.strip()
    return FDA_SOURCE_URL_REWRITES.get(cleaned, cleaned)


def _display_label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


def _action_scope_from_fields(
    *,
    drug_id: str,
    title: str,
    description: str,
) -> ScopeRef:
    hay = f"{title} {description}".lower()
    if "class-wide" in hay or "glp-1 receptor agonists" in hay:
        return ScopeRef(
            type="class",
            key="glp1_receptor_agonists",
            label="GLP-1 receptor agonists",
        )
    return ScopeRef(
        type="drug",
        key=drug_id,
        label=_display_label(drug_id),
    )


def _signal_row_to_schema(row: QuarterlyStat) -> SignalPoint:
    return SignalPoint(
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
        bcpnn_ic=row.bcpnn_ic,
        bcpnn_ic025=row.bcpnn_ic025,
        ebgm=row.ebgm,
        eb05=row.eb05,
        signal_detected=bool(row.signal_detected),
        trajectory=row.trajectory,
        term_level=row.term_level,
        family_key=row.family_key,
        family_label=row.family_label,
        method_votes=dict(row.method_votes or {}),
        consensus_tier=row.consensus_tier,
        label_status=row.label_status,
        priority_flag=bool(row.priority_flag),
        supporting_terms=list(row.supporting_terms or []),
    )


def _fda_action_row_to_schema(row: FdaAction) -> FDAAction:
    return FDAAction(
        id=row.id,
        date=_iso_date(row.date),
        type=row.type,
        title=row.title,
        description=row.description,
        source_url=_normalize_source_url(row.source_url),
        scope=_action_scope_from_fields(
            drug_id=row.drug_id,
            title=row.title,
            description=row.description,
        ),
    )


def _signal_sort_key(row: QuarterlyStat | SignalPoint) -> tuple[int, int, int, float, int, str]:
    term_level = row.term_level if hasattr(row, "term_level") else "pt"
    consensus_tier = row.consensus_tier if hasattr(row, "consensus_tier") else "none"
    priority_flag = bool(row.priority_flag) if hasattr(row, "priority_flag") else False
    ror_ci_lower = row.ror_ci_lower if hasattr(row, "ror_ci_lower") else None
    report_count = row.report_count if hasattr(row, "report_count") else 0
    adverse_event = row.adverse_event if hasattr(row, "adverse_event") else ""
    return (
        0 if term_level == "family" else 1,
        -consensus_tier_rank(consensus_tier),
        -int(priority_flag),
        -(ror_ci_lower if ror_ci_lower is not None else -1.0),
        -report_count,
        adverse_event,
    )


def _signal_is_active(row: QuarterlyStat) -> bool:
    return (
        consensus_tier_rank(row.consensus_tier) > 0
        or bool(row.signal_detected)
        or row.trajectory in {"emerging", "accelerating"}
    )


async def _count_reports_in_quarter(db: AsyncSession, drug_id: str, quarter: str) -> int:
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


async def delete_tracked_drug(
    db: AsyncSession,
    *,
    drug_id: str,
    evermemos_client: EvermemosClient | None = None,
) -> DeleteDrugResponse:
    drug = await db.scalar(select(Drug).where(Drug.id == drug_id))
    if drug is None:
        raise AppError(error="NotFound", detail=f"drug_id '{drug_id}' not found", status_code=404)

    try:
        if evermemos_client is not None:
            await evermemos_client.delete_group_memories(db, drug_id=drug_id)
    except Exception:
        logger.warning("Failed to delete EverMemOS group memories for %s", drug_id, exc_info=True)

    await db.execute(delete(FdaAction).where(FdaAction.drug_id == drug_id))
    await db.execute(
        delete(TrackingJob).where(
            or_(
                TrackingJob.drug_id == drug_id,
                TrackingJob.resolved_generic_name == drug.generic_name,
            )
        )
    )
    await db.delete(drug)
    await db.commit()

    return DeleteDrugResponse(drug_id=drug_id, deleted=True)


async def list_drugs_with_status(db: AsyncSession) -> list[DrugSchema]:
    drugs = (
        (
            await db.execute(
                select(Drug).order_by(Drug.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not drugs:
        return []

    states = (
        (
            await db.execute(
                select(IngestionState).where(
                    IngestionState.drug_id.in_([drug.id for drug in drugs])
                )
            )
        )
        .scalars()
        .all()
    )
    state_by_drug = {row.drug_id: row for row in states}

    report_counts = (
        await db.execute(
            select(
                FaersReportDrug.drug_id,
                func.count(func.distinct(FaersReportDrug.safetyreportid)).label("cnt"),
            )
            .where(
                FaersReportDrug.role == "suspect",
                FaersReportDrug.drug_id.is_not(None),
                FaersReportDrug.drug_id.in_([drug.id for drug in drugs]),
            )
            .group_by(FaersReportDrug.drug_id)
        )
    ).all()
    total_by_drug = {row.drug_id: int(row.cnt) for row in report_counts}

    out: list[DrugSchema] = []
    for drug in drugs:
        state = state_by_drug.get(drug.id)
        quarters_loaded = sort_quarters(list(state.quarters_loaded or [])) if state is not None else []
        next_quarter = state.next_quarter if state is not None else None
        total_reports = total_by_drug.get(drug.id, 0)

        summary = drug.description
        if quarters_loaded:
            latest_quarter = quarters_loaded[-1]
            if not is_strict_demo_drug(drug.id):
                proof_prediction_rows = (
                    (
                        await db.execute(
                            select(PredictionRow)
                            .where(
                                PredictionRow.drug_id == drug.id,
                                PredictionRow.visibility == "public",
                                PredictionRow.track == "proof",
                            )
                            .order_by(PredictionRow.created_at.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
                proof_prediction_rows = [
                    row
                    for row in proof_prediction_rows
                    if parse_quarter(row.created_at_quarter) <= parse_quarter(latest_quarter)
                ]
                if proof_prediction_rows:
                    labels: list[str] = []
                    for row in proof_prediction_rows:
                        label = row.adverse_event
                        if drug.id == "minoxidil":
                            canonical = {
                                "application site irritation / inflammation": "Application Site Irritation / Inflammation",
                                "application site irritation": "Application Site Irritation / Inflammation",
                                "application site pruritus": "Application Site Irritation / Inflammation",
                                "application site pain": "Application Site Irritation / Inflammation",
                                "hair-change effects": "Hair-Change Effects",
                                "chest pain": "Systemic / Cardiovascular Warning",
                                "palpitations": "Systemic / Cardiovascular Warning",
                                "hypersensitivity / contact dermatitis": "Hypersensitivity / Contact Dermatitis",
                            }
                            label = canonical.get(label.strip().lower(), label)
                        if label not in labels:
                            labels.append(label)
                    if labels:
                        names = ", ".join(labels[:2])
                        summary = f"As of {latest_quarter}, proof-backed signals: {names}."
            latest_rows = (
                (
                    await db.execute(
                        select(QuarterlyStat)
                        .where(
                            QuarterlyStat.drug_id == drug.id,
                            QuarterlyStat.quarter == latest_quarter,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if latest_rows and summary == drug.description:
                latest_rows = sorted(latest_rows, key=_signal_sort_key)[:2]
                names = ", ".join(row.adverse_event for row in latest_rows)
                summary = f"As of {latest_quarter}, monitored signals: {names}."
        elif not summary:
            summary = "Not loaded in demo mode."

        out.append(
            DrugSchema(
                id=drug.id,
                generic_name=drug.generic_name,
                brand_names=list(drug.brand_names or []),
                total_reports=total_reports,
                quarters_loaded=quarters_loaded,
                next_quarter=next_quarter,
                current_profile_summary=summary,
            )
        )

    return out


async def get_active_signals(db: AsyncSession, drug_id: str) -> list[SignalPoint]:
    _, state = await _get_drug_and_state(db, drug_id)
    quarters = sort_quarters(list(state.quarters_loaded or []))
    if not quarters:
        return []

    latest_quarter = quarters[-1]
    rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == latest_quarter,
                )
            )
        )
        .scalars()
        .all()
    )
    active_rows = [row for row in rows if _signal_is_active(row)]
    if not active_rows:
        active_rows = sorted(rows, key=_signal_sort_key)[:6]
    else:
        active_rows = sorted(active_rows, key=_signal_sort_key)
    return [_signal_row_to_schema(row) for row in active_rows]


async def get_fda_actions(db: AsyncSession, drug_id: str) -> list[FDAAction]:
    await _get_drug_and_state(db, drug_id)
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
    return [_fda_action_row_to_schema(row) for row in rows]


def _action_matches_prediction_fields(
    *,
    action_type: str,
    title: str,
    description: str,
    prediction: PredictionRow,
) -> bool:
    if action_type != prediction.predicted_action:
        return False

    hay = f"{title} {description}".lower()
    term = prediction.adverse_event.lower()
    if term in hay:
        return True

    # Match by meaningful term overlap for multi-word events (e.g., "Suicidal ideation").
    tokens = [token for token in term.replace("-", " ").split() if len(token) >= 4]
    return any(token in hay for token in tokens)


def _action_matches_prediction(action: FdaAction, prediction: PredictionRow) -> bool:
    return _action_matches_prediction_fields(
        action_type=action.type,
        title=action.title,
        description=action.description,
        prediction=prediction,
    )


def _score_prediction(
    prediction: PredictionRow,
    action_date: date | None,
) -> str:
    if action_date is None:
        return "pending"

    if prediction.predicted_date_start <= action_date <= prediction.predicted_date_end:
        return "validated"
    if action_date > prediction.predicted_date_end and action_date <= prediction.predicted_date_end + timedelta(days=365):
        return "early"
    return "missed"


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()[:10])
    except Exception:
        return None


def _is_fda_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    return host.endswith("fda.gov")


def _extract_json_payload(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        loaded = json.loads(candidate)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        return None


def _build_grounding_prompt(prediction: PredictionRow) -> str:
    return f"""
Find an official FDA source validating this prediction.
Return JSON only with this schema:
{{
  "found_action": boolean,
  "action": {{
    "date": "YYYY-MM-DD",
    "type": "label_change|safety_communication|warning",
    "title": "string",
    "description": "string",
    "source_url": "https://www.fda.gov/..."
  }},
  "notes": "short string"
}}

Prediction:
- Drug: {prediction.drug_id}
- Event: {prediction.adverse_event}
- Predicted action: {prediction.predicted_action}
- Predicted window: {prediction.predicted_date_start.isoformat()} to {prediction.predicted_date_end.isoformat()}
- Created at quarter: {prediction.created_at_quarter}

Rules:
- Only use official FDA sources.
- If no clear FDA source exists, return found_action=false.
- Do not invent URLs.
""".strip()


def _run_grounding_lookup(
    *,
    settings: Settings,
    prediction: PredictionRow,
) -> tuple[str, dict[str, Any]]:
    if not settings.gemini_api_key:
        return "failed", {"error": "missing_gemini_api_key"}

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        return "failed", {"error": f"google_genai_import_failed: {exc.__class__.__name__}"}

    client = genai.Client(api_key=settings.gemini_api_key)
    models_to_try = [settings.gemini_model_grounding]
    if settings.gemini_model_grounding != "gemini-2.5-flash":
        models_to_try.append("gemini-2.5-flash")

    prompt = _build_grounding_prompt(prediction)
    last_error: str | None = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            payload = _extract_json_payload(getattr(response, "text", "") or "")
            if payload is None:
                return "failed", {"error": "invalid_grounding_json", "model": model_name, "raw": getattr(response, "text", "")}
            payload["model"] = model_name
            return "ok", payload
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"

    return "failed", {"error": last_error or "grounding_lookup_failed"}


def _grounded_action_from_payload(
    payload: dict[str, Any] | None,
    *,
    prediction: PredictionRow,
) -> GroundedAction | None:
    if not isinstance(payload, dict):
        return None
    if not bool(payload.get("found_action")):
        return None

    action_raw = payload.get("action")
    if not isinstance(action_raw, dict):
        return None

    source_url = _normalize_source_url(str(action_raw.get("source_url") or "").strip())
    title = str(action_raw.get("title") or "").strip()
    description = str(action_raw.get("description") or "").strip()
    action_type = str(action_raw.get("type") or "").strip()
    action_date = _parse_iso_date(str(action_raw.get("date") or ""))
    if not source_url or not _is_fda_url(source_url):
        return None
    if not title or action_date is None:
        return None
    if action_type != prediction.predicted_action:
        return None
    if not _action_matches_prediction_fields(
        action_type=action_type,
        title=title,
        description=description,
        prediction=prediction,
    ):
        return None

    return GroundedAction(
        action=FDAAction(
            id=f"grounded-{prediction.id}",
            date=action_date.isoformat(),
            type=action_type,
            title=title,
            description=description or "Validated via Gemini grounding search (FDA source).",
            source_url=source_url,
            scope=_action_scope_from_fields(
                drug_id=prediction.drug_id,
                title=title,
                description=description,
            ),
        ),
        action_date=action_date,
    )


async def _load_cached_grounding_request(
    db: AsyncSession,
    *,
    prediction: PredictionRow,
) -> EvermemosRequest | None:
    rows = (
        (
            await db.execute(
                select(EvermemosRequest)
                .where(
                    EvermemosRequest.drug_id == prediction.drug_id,
                    EvermemosRequest.endpoint == GROUNDING_SCORECARD_ENDPOINT,
                )
                .order_by(EvermemosRequest.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if isinstance(row.request_body, dict) and row.request_body.get("prediction_id") == str(prediction.id):
            return row
    return None


def _grounding_refresh_due(
    *,
    request_row: EvermemosRequest | None,
    refresh_days: int,
) -> bool:
    if request_row is None:
        return True
    if refresh_days <= 0:
        return False
    age = datetime.now(timezone.utc) - request_row.updated_at
    return age >= timedelta(days=refresh_days)


async def _upsert_grounding_cache(
    db: AsyncSession,
    *,
    prediction: PredictionRow,
    request_row: EvermemosRequest | None,
    request_body: dict[str, Any],
    response_body: dict[str, Any],
    status: str,
) -> None:
    now = datetime.now(timezone.utc)
    if request_row is None:
        db.add(
            EvermemosRequest(
                drug_id=prediction.drug_id,
                quarter=prediction.created_at_quarter,
                endpoint=GROUNDING_SCORECARD_ENDPOINT,
                request_body=request_body,
                response_body=response_body,
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        request_row.request_body = request_body
        request_row.response_body = response_body
        request_row.status = status
        request_row.updated_at = now

    try:
        await db.commit()
    except Exception:
        await db.rollback()


async def _resolve_grounded_action(
    db: AsyncSession,
    *,
    prediction: PredictionRow,
    settings: Settings,
) -> GroundedAction | None:
    if not settings.gemini_grounding_scorecard_verify or not settings.gemini_api_key:
        return None

    cached = await _load_cached_grounding_request(db, prediction=prediction)
    if cached is not None and not _grounding_refresh_due(
        request_row=cached,
        refresh_days=settings.gemini_grounding_refresh_days,
    ):
        return _grounded_action_from_payload(cached.response_body or {}, prediction=prediction)

    request_payload = {
        "prediction_id": str(prediction.id),
        "adverse_event": prediction.adverse_event,
        "predicted_action": prediction.predicted_action,
        "predicted_date_start": prediction.predicted_date_start.isoformat(),
        "predicted_date_end": prediction.predicted_date_end.isoformat(),
        "created_at_quarter": prediction.created_at_quarter,
    }
    status, response_payload = _run_grounding_lookup(settings=settings, prediction=prediction)
    await _upsert_grounding_cache(
        db,
        prediction=prediction,
        request_row=cached,
        request_body=request_payload,
        response_body=response_payload,
        status=status if status in {"ok", "failed"} else "failed",
    )
    return _grounded_action_from_payload(response_payload, prediction=prediction)


async def get_prediction_scorecard(
    db: AsyncSession,
    drug_id: str,
    *,
    settings: Settings = DEFAULT_SETTINGS,
) -> list[ScorecardEntry]:
    await _get_drug_and_state(db, drug_id)
    prediction_rows = (
        (
            await db.execute(
                select(PredictionRow)
                .where(
                    PredictionRow.drug_id == drug_id,
                    PredictionRow.adverse_event != "Pancreatitis",
                    PredictionRow.visibility == "public",
                    PredictionRow.track == "receipt",
                )
                .order_by(PredictionRow.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not prediction_rows:
        return []

    action_rows = (
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

    entries: list[ScorecardEntry] = []
    for prediction in prediction_rows:
        matching_action = next((row for row in action_rows if _action_matches_prediction(row, prediction)), None)
        grounded = None
        if matching_action is None:
            grounded = await _resolve_grounded_action(
                db,
                prediction=prediction,
                settings=settings,
            )

        action_schema = _fda_action_row_to_schema(matching_action) if matching_action else (grounded.action if grounded else None)
        action_date = matching_action.date if matching_action else (grounded.action_date if grounded else None)
        prediction_schema = await build_prediction_schema(
            db,
            prediction,
            settings=settings,
        )
        if (
            not is_strict_demo_drug(drug_id)
            and action_schema is None
            and (
                prediction_schema.verification is None
                or prediction_schema.verification.status not in {"supported", "mixed"}
            )
        ):
            continue
        entries.append(
            ScorecardEntry(
                prediction=prediction_schema,
                actual_fda_action=action_schema,
                result=_score_prediction(prediction, action_date),
            )
        )

    return entries


def _derive_casefile_stage(
    *,
    lead_signal: SignalPoint | None,
    validated_receipts: int,
    pending_receipts: int,
    watchlist_count: int,
) -> str:
    if validated_receipts > 0:
        return "receipt_validation"
    if lead_signal and lead_signal.consensus_tier == "public_signal":
        return "escalation"
    if pending_receipts > 0:
        return "escalation"
    if watchlist_count > 0 or (lead_signal and lead_signal.signal_detected):
        return "emergence"
    return "baseline"


def _receipt_summary(validated_receipts: int, pending_receipts: int) -> str:
    if validated_receipts > 0:
        return f"{validated_receipts} validated regulatory receipt{'s' if validated_receipts != 1 else ''} are already linked."
    if pending_receipts > 0:
        return f"{pending_receipts} regulatory receipt forecast{'s' if pending_receipts != 1 else ''} remain open."
    return "No regulatory receipts are linked yet."


def _casefile_copy(
    *,
    drug_label: str,
    lead_family: str | None,
    stage: str,
    watchlist_count: int,
    key_label_gaps: list[str],
    validated_receipts: int,
    pending_receipts: int,
    proof_backed_signals: int,
) -> tuple[str, str]:
    family = lead_family or "current safety monitoring"
    if stage == "receipt_validation":
        headline = f"{family} has progressed from monitoring to validated receipt."
        summary = (
            f"{drug_label} now has {validated_receipts} validated receipt{'s' if validated_receipts != 1 else ''}. "
            f"The leading family remains {family}, with {pending_receipts} additional receipt forecast"
            f"{'s' if pending_receipts != 1 else ''} and {proof_backed_signals} proof-backed public signal"
            f"{'s' if proof_backed_signals != 1 else ''} still under observation."
        )
        return headline, summary
    if stage == "escalation":
        label_gap_text = (
            f" Label gaps remain around {', '.join(key_label_gaps[:2])}."
            if key_label_gaps
            else ""
        )
        if proof_backed_signals > 0 and pending_receipts == 0:
            headline = f"Externally corroborated safety themes are building around {family}."
            summary = (
                f"{drug_label} has moved past a quiet baseline. {family} now anchors the casefile, with "
                f"{proof_backed_signals} proof-backed public signal{'s' if proof_backed_signals != 1 else ''} and "
                f"{watchlist_count} active watchlist alert{'s' if watchlist_count != 1 else ''}.{label_gap_text}"
            )
            return headline, summary
        headline = f"Consensus signal strength is building around {family}."
        summary = (
            f"{drug_label} has moved past a quiet baseline. {family} now anchors the casefile, with "
            f"{watchlist_count} active watchlist alert{'s' if watchlist_count != 1 else ''} and "
            f"{pending_receipts} regulatory receipt forecast{'s' if pending_receipts != 1 else ''}.{label_gap_text}"
        )
        return headline, summary
    if stage == "emergence":
        if proof_backed_signals > 0:
            headline = f"Externally corroborated safety themes are building around {family}."
            summary = (
                f"{drug_label} is no longer a generic placeholder casefile. The current evidence is concentrating around "
                f"{family}, with {proof_backed_signals} proof-backed public signal{'s' if proof_backed_signals != 1 else ''} "
                f"and {watchlist_count} analyst-facing watchlist alert{'s' if watchlist_count != 1 else ''} ready for deeper review."
            )
            return headline, summary
        headline = f"{family} is the main emerging watchlist family."
        summary = (
            f"{drug_label} is no longer a generic placeholder casefile. The current evidence is concentrating around "
            f"{family}, with {watchlist_count} analyst-facing watchlist alert{'s' if watchlist_count != 1 else ''} "
            f"ready for deeper review."
        )
        return headline, summary
    headline = "The casefile is at baseline, but the evidence stack is live."
    summary = (
        f"{drug_label} is using the same evidence, memory, and forecast pipeline as the demo hero drug. "
        "The current quarter does not yet meet consensus thresholds for a public or watchlist signal."
    )
    return headline, summary


async def get_casefile_summary(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter: str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> CasefileSummary:
    drug, state = await _get_drug_and_state(db, drug_id)
    quarters = sort_quarters(list(state.quarters_loaded or []))
    if not quarters:
        headline = "The casefile is ready for baseline ingestion."
        summary = (
            f"{drug.generic_name} is tracked, but no quarters are loaded yet. Start ingestion to build the signal "
            "timeline, belief state, and regulatory forecast layers."
        )
        return CasefileSummary(
            drug_id=drug_id,
            viewed_quarter=quarter or "baseline",
            stage="baseline",
            headline=headline,
            summary=summary,
            lead_signal=None,
            lead_family=None,
            key_label_gaps=[],
            watchlist_alerts=[],
            public_forecasts=[],
            validated_receipts=0,
            pending_receipts=0,
            proof_backed_signals=0,
            receipt_summary=_receipt_summary(0, 0),
        )

    from app.core.errors import AppError
    from app.utils.quarters import parse_quarter

    viewed_quarter = quarter or quarters[-1]
    if viewed_quarter not in quarters:
        raise AppError(error="BadRequest", detail=f"Quarter {viewed_quarter} is not loaded for {drug_id}", status_code=400)

    signal_rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == viewed_quarter,
                )
            )
        )
        .scalars()
        .all()
    )
    signal_rows = sorted(signal_rows, key=_signal_sort_key)
    active_rows = [row for row in signal_rows if _signal_is_active(row)]
    lead_row = active_rows[0] if active_rows else (signal_rows[0] if signal_rows else None)
    lead_signal = _signal_row_to_schema(lead_row) if lead_row is not None else None
    lead_family = lead_signal.family_label if lead_signal and lead_signal.family_label else (lead_signal.adverse_event if lead_signal else None)

    watchlist_alert_rows = [
        row
        for row in active_rows
        if row.consensus_tier in {"watchlist", "priority_review", "public_signal"}
    ][:4]
    key_label_gaps: list[str] = []
    for row in active_rows:
        if row.label_status != "label_gap":
            continue
        label = row.family_label or row.adverse_event
        if label not in key_label_gaps:
            key_label_gaps.append(label)
        if len(key_label_gaps) >= 4:
            break

    public_prediction_rows = (
        (
            await db.execute(
                select(PredictionRow)
                .where(
                    PredictionRow.drug_id == drug_id,
                    PredictionRow.adverse_event != "Pancreatitis",
                    PredictionRow.visibility == "public",
                )
                .order_by(PredictionRow.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    viewed_quarter_value = parse_quarter(viewed_quarter)
    public_prediction_rows = [
        row for row in public_prediction_rows if parse_quarter(row.created_at_quarter) <= viewed_quarter_value
    ]
    public_prediction_rows = sorted(
        public_prediction_rows,
        key=lambda row: (
            0 if lead_family and row.adverse_event == lead_family else 1,
            0 if row.track == "proof" else 1,
            0 if row.novelty_status == "known_label" else 1,
            -int(row.confidence),
            row.created_at_quarter,
            row.adverse_event,
        ),
    )
    prediction_rows = [row for row in public_prediction_rows if row.track == "receipt"]
    action_rows = (
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
    validated_receipts = 0
    pending_receipts = 0
    for prediction in prediction_rows:
        matching_action = next((row for row in action_rows if _action_matches_prediction(row, prediction)), None)
        result = _score_prediction(prediction, matching_action.date if matching_action else None)
        if result == "validated":
            validated_receipts += 1
        elif result == "pending":
            pending_receipts += 1

    public_forecasts = [
        await build_prediction_schema(
            db,
            row,
            settings=settings,
        )
        for row in public_prediction_rows
    ]

    if not is_strict_demo_drug(drug_id):
        def display_label_for_prediction(adverse_event: str) -> str | None:
            if drug_id != "minoxidil":
                return adverse_event
            canonical = {
                "application site irritation / inflammation": "Application Site Irritation / Inflammation",
                "application site irritation": "Application Site Irritation / Inflammation",
                "application site pruritus": "Application Site Irritation / Inflammation",
                "application site pain": "Application Site Irritation / Inflammation",
                "hair-change effects": "Hair-Change Effects",
                "chest pain": "Systemic / Cardiovascular Warning",
                "palpitations": "Systemic / Cardiovascular Warning",
                "hypersensitivity / contact dermatitis": "Hypersensitivity / Contact Dermatitis",
            }
            return canonical.get(adverse_event.strip().lower())

        def proof_sort_key(prediction: Prediction) -> tuple[int, int, int, tuple[int, int], str]:
            verification = prediction.verification
            status_rank = 2
            if verification and verification.status == "supported":
                status_rank = 0
            elif verification and verification.status == "mixed":
                status_rank = 1
            public_source_rank = (
                0
                if verification and any(source in {"fda", "dailymed"} for source in verification.source_types)
                else 1
            )
            return (
                status_rank,
                public_source_rank,
                -int(prediction.confidence),
                parse_quarter(prediction.created_at_quarter),
                prediction.adverse_event.lower(),
            )

        receipt_forecasts = [
            prediction
            for prediction in public_forecasts
            if prediction.track == "receipt"
            and prediction.verification is not None
            and prediction.verification.status in {"supported", "mixed"}
        ]
        grouped_proof_forecasts: dict[str, Prediction] = {}
        for prediction in public_forecasts:
            if prediction.track != "proof":
                continue
            display_label = display_label_for_prediction(prediction.adverse_event)
            if display_label is None:
                continue
            candidate = prediction.model_copy(update={"adverse_event": display_label})
            existing = grouped_proof_forecasts.get(display_label)
            if existing is None or proof_sort_key(candidate) < proof_sort_key(existing):
                grouped_proof_forecasts[display_label] = candidate

        ordered_proof_forecasts = sorted(
            grouped_proof_forecasts.values(),
            key=lambda prediction: (
                (
                    [
                        "Application Site Irritation / Inflammation",
                        "Hair-Change Effects",
                        "Systemic / Cardiovascular Warning",
                        "Hypersensitivity / Contact Dermatitis",
                    ].index(prediction.adverse_event)
                    if drug_id == "minoxidil" and prediction.adverse_event in {
                        "Application Site Irritation / Inflammation",
                        "Hair-Change Effects",
                        "Systemic / Cardiovascular Warning",
                        "Hypersensitivity / Contact Dermatitis",
                    }
                    else 99
                ),
                proof_sort_key(prediction),
            ),
        )
        if drug_id == "minoxidil":
            ordered_proof_forecasts = ordered_proof_forecasts[:4]
        public_forecasts = ordered_proof_forecasts + receipt_forecasts

    if not is_strict_demo_drug(drug_id):
        lead_public_proof = next((prediction for prediction in public_forecasts if prediction.track == "proof"), None)
        if lead_public_proof is not None:
            lead_family = lead_public_proof.adverse_event
            matching_row = next(
                (
                    row
                    for row in active_rows
                    if (row.family_label or row.adverse_event) == lead_family
                    or row.adverse_event == lead_family
                ),
                None,
            )
            if matching_row is not None:
                lead_signal = _signal_row_to_schema(matching_row)

    prediction_rows_by_id = {str(row.id): row for row in public_prediction_rows}
    validated_receipts = 0
    pending_receipts = 0
    for prediction in public_forecasts:
        if prediction.track != "receipt":
            continue
        row = prediction_rows_by_id.get(prediction.id)
        if row is None:
            continue
        matching_action = next((action for action in action_rows if _action_matches_prediction(action, row)), None)
        result = _score_prediction(row, matching_action.date if matching_action else None)
        if result == "validated":
            validated_receipts += 1
        elif result == "pending":
            pending_receipts += 1

    proof_backed_signals = sum(1 for row in public_forecasts if row.track == "proof")
    stage = _derive_casefile_stage(
        lead_signal=lead_signal,
        validated_receipts=validated_receipts,
        pending_receipts=pending_receipts,
        watchlist_count=len(watchlist_alert_rows),
    )
    headline, summary = _casefile_copy(
        drug_label=drug.generic_name,
        lead_family=lead_family,
        stage=stage,
        watchlist_count=len(watchlist_alert_rows),
        key_label_gaps=key_label_gaps,
        validated_receipts=validated_receipts,
        pending_receipts=pending_receipts,
        proof_backed_signals=proof_backed_signals,
    )

    return CasefileSummary(
        drug_id=drug_id,
        viewed_quarter=viewed_quarter,
        stage=stage,
        headline=headline,
        summary=summary,
        lead_signal=lead_signal,
        lead_family=lead_family,
        key_label_gaps=key_label_gaps,
        watchlist_alerts=[_signal_row_to_schema(row) for row in watchlist_alert_rows],
        public_forecasts=public_forecasts,
        validated_receipts=validated_receipts,
        pending_receipts=pending_receipts,
        proof_backed_signals=proof_backed_signals,
        receipt_summary=_receipt_summary(validated_receipts, pending_receipts),
    )


async def get_foresight_memory_status(
    db: AsyncSession,
    *,
    drug_id: str,
) -> ForesightMemoryStatus:
    await _get_drug_and_state(db, drug_id)

    prediction_keys = [
        f"{adverse_event} {predicted_action}"
        for adverse_event, predicted_action in (
            (
                await db.execute(
                    select(PredictionRow.adverse_event, PredictionRow.predicted_action).where(
                        PredictionRow.drug_id == drug_id,
                        PredictionRow.adverse_event != "Pancreatitis",
                        PredictionRow.visibility == "public",
                    )
                )
            ).all()
        )
    ]

    total_predictions = int(
        await db.scalar(
            select(func.count(PredictionRow.id)).where(
                PredictionRow.drug_id == drug_id,
                PredictionRow.adverse_event != "Pancreatitis",
                PredictionRow.visibility == "public",
            )
        )
        or 0
    )

    foresight_filter = and_(
        EvermemosRequest.drug_id == drug_id,
        EvermemosRequest.request_body["json"]["memory_type"].astext == "foresight",
    )

    foresight_prediction_key = func.coalesce(
        EvermemosRequest.request_body["json"]["foresight_data"]["prediction"].astext,
        EvermemosRequest.request_body["json"]["message_id"].astext,
        "",
    )
    foresight_attempt_query = (
        select(
            EvermemosRequest.status.label("status"),
            EvermemosRequest.quarter.label("quarter"),
            EvermemosRequest.created_at.label("created_at"),
            EvermemosRequest.response_body.label("response_body"),
            func.row_number()
            .over(
                partition_by=foresight_prediction_key,
                order_by=(EvermemosRequest.created_at.desc(), EvermemosRequest.id.desc()),
            )
            .label("attempt_rank"),
        )
        .where(foresight_filter)
    )
    if prediction_keys:
        foresight_attempt_query = foresight_attempt_query.where(foresight_prediction_key.in_(prediction_keys))
    latest_foresight_attempts = foresight_attempt_query.subquery()
    latest_foresight_attempts_filter = latest_foresight_attempts.c.attempt_rank == 1

    attempted_writes = int(
        await db.scalar(
            select(func.count()).select_from(latest_foresight_attempts).where(latest_foresight_attempts_filter)
        )
        or 0
    )
    successful_writes = int(
        await db.scalar(
            select(func.count()).select_from(latest_foresight_attempts).where(
                latest_foresight_attempts_filter,
                latest_foresight_attempts.c.status == "ok",
            )
        )
        or 0
    )
    failed_writes = int(
        await db.scalar(
            select(func.count()).select_from(latest_foresight_attempts).where(
                latest_foresight_attempts_filter,
                latest_foresight_attempts.c.status == "failed",
            )
        )
        or 0
    )

    last_attempted_quarter = await db.scalar(
        select(latest_foresight_attempts.c.quarter)
        .where(latest_foresight_attempts_filter)
        .order_by(latest_foresight_attempts.c.created_at.desc())
        .limit(1)
    )
    if isinstance(last_attempted_quarter, str) and not last_attempted_quarter.strip():
        last_attempted_quarter = None

    if total_predictions == 0:
        return ForesightMemoryStatus(
            status="idle",
            message="No foresight predictions generated yet.",
            total_predictions=0,
            attempted_writes=attempted_writes,
            successful_writes=successful_writes,
            failed_writes=failed_writes,
            last_attempted_quarter=last_attempted_quarter,
        )

    if attempted_writes == 0:
        return ForesightMemoryStatus(
            status="warning",
            message="Foresight write failed ⚠️ No EverMemOS foresight write attempts were logged.",
            total_predictions=total_predictions,
            attempted_writes=0,
            successful_writes=0,
            failed_writes=0,
            last_attempted_quarter=None,
        )

    if failed_writes > 0:
        schema_failures = int(
            await db.scalar(
                select(func.count()).select_from(latest_foresight_attempts).where(
                    latest_foresight_attempts_filter,
                    latest_foresight_attempts.c.status == "failed",
                    latest_foresight_attempts.c.response_body["error_type"].astext == "ForesightSchemaError",
                )
            )
            or 0
        )
        if schema_failures > 0:
            message = "Foresight write failed ⚠️ Schema validation rejected one or more payloads."
        else:
            message = "Foresight write failed ⚠️ EverMemOS write errors were detected."
        return ForesightMemoryStatus(
            status="warning",
            message=message,
            total_predictions=total_predictions,
            attempted_writes=attempted_writes,
            successful_writes=successful_writes,
            failed_writes=failed_writes,
            last_attempted_quarter=last_attempted_quarter,
        )

    return ForesightMemoryStatus(
        status="ok",
        message="Foresight stored ✅",
        total_predictions=total_predictions,
        attempted_writes=attempted_writes,
        successful_writes=successful_writes,
        failed_writes=0,
        last_attempted_quarter=last_attempted_quarter,
    )


async def _top_signal_rows(db: AsyncSession, drug_id: str, quarter: str) -> list[QuarterlyStat]:
    active_rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == quarter,
                )
                .limit(16)
            )
        )
        .scalars()
        .all()
    )
    filtered_active_rows = sorted([row for row in active_rows if _signal_is_active(row)], key=_signal_sort_key)
    if filtered_active_rows:
        return list(filtered_active_rows[:3])

    fallback_rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == quarter,
                )
                .limit(16)
            )
        )
        .scalars()
        .all()
    )
    return list(sorted(fallback_rows, key=_signal_sort_key)[:3])


async def _build_fallback_episode(db: AsyncSession, drug_id: str, quarter: str) -> EpisodicSummary:
    top_rows = await _top_signal_rows(db, drug_id, quarter)
    report_count = await _count_reports_in_quarter(db, drug_id, quarter)

    if top_rows:
        signal_names = [row.adverse_event for row in top_rows]
        signal_text = ", ".join(signal_names)
        narrative = (
            f"In {quarter}, {drug_id} reports were dominated by {signal_text}. "
            "This summary is generated from Postgres evidence because episodic memory may be unavailable."
        )
    else:
        signal_names = []
        narrative = (
            f"In {quarter}, no prominent tracked event pattern was detected from loaded reports. "
            "This summary is generated from Postgres evidence."
        )

    _, end_date = quarter_to_dates(quarter)
    created_at = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )

    return EpisodicSummary(
        quarter=quarter,
        narrative=narrative,
        key_signals_mentioned=signal_names,
        report_count_ingested=report_count,
        created_at=created_at,
        memory_source="postgres_fallback",
        memory_id=None,
    )


def _memory_identifier(memory: dict[str, Any]) -> str | None:
    for key in ["id", "_id", "memory_id", "message_id"]:
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _quarters_covered_by_memory(memory: dict[str, Any]) -> set[str]:
    text_parts: list[str] = []
    for key in ["title", "summary", "episode", "content", "memory", "text", "atomic_fact", "subject", "message_id", "id", "_id"]:
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value)
    extend = memory.get("extend")
    if isinstance(extend, dict):
        message_id = extend.get("message_id")
        if isinstance(message_id, str) and message_id.strip():
            text_parts.append(message_id)
    if not text_parts:
        return set()
    return extract_quarters_from_text("\n".join(text_parts))


def _memory_search_text(memory: dict[str, Any], *, evermemos_client: EvermemosClient) -> str:
    return evermemos_client.extract_memory_search_text(memory)


def _memory_text_len(memory: dict[str, Any], *, evermemos_client: EvermemosClient) -> int:
    text = _memory_search_text(memory, evermemos_client=evermemos_client)
    return len(text) if text else 0


def _memory_display_text(memory: dict[str, Any], *, evermemos_client: EvermemosClient) -> str:
    episode = memory.get("episode")
    if isinstance(episode, str) and episode.strip():
        return episode.strip()

    title = memory.get("title")
    summary = memory.get("summary")
    if isinstance(title, str) and title.strip() and isinstance(summary, str) and summary.strip():
        title_text = title.strip()
        summary_text = summary.strip()
        if title_text.lower() in summary_text.lower():
            return summary_text
        return f"{title_text}\n\n{summary_text}"

    return evermemos_client.extract_memory_text(memory)


def _needs_narrative_enrichment(memory: dict[str, Any], narrative: str) -> bool:
    if not narrative.strip():
        return False
    episode = memory.get("episode")
    if isinstance(episode, str) and episode.strip():
        return False
    lowered = narrative.lower()
    return "faers data limitations" in lowered or len(narrative) <= 220


def _score_memory_for_quarter(
    memory: dict[str, Any],
    *,
    quarter: str,
    evermemos_client: EvermemosClient,
) -> tuple[int, int, int, str]:
    covered = _quarters_covered_by_memory(memory)
    span = len(covered) if covered else 999
    search_text = _memory_search_text(memory, evermemos_client=evermemos_client).lower()
    has_exact = 1 if quarter.lower() in search_text else 0
    contains_quarter = 1 if quarter in covered else 0
    return (
        contains_quarter,
        has_exact,
        -span,
        _memory_identifier(memory) or "zzzz",
    )


def _select_best_memory_for_quarter(
    memories: list[dict[str, Any]],
    *,
    quarter: str,
    evermemos_client: EvermemosClient,
) -> dict[str, Any] | None:
    ranked = sorted(
        memories,
        key=lambda memory: _score_memory_for_quarter(
            memory,
            quarter=quarter,
            evermemos_client=evermemos_client,
        ),
        reverse=True,
    )
    if not ranked:
        return None
    best = ranked[0]
    if _score_memory_for_quarter(best, quarter=quarter, evermemos_client=evermemos_client)[0] == 0:
        return None
    return best


async def get_drug_episodes(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
) -> list[EpisodicSummary]:
    _, state = await _get_drug_and_state(db, drug_id)
    quarters = sort_quarters(list(state.quarters_loaded or []))
    if not quarters:
        return []

    fallback_by_quarter = {
        quarter: await _build_fallback_episode(db, drug_id, quarter)
        for quarter in quarters
    }

    memories = await evermemos_client.fetch_episodic_memories(
        db,
        drug_id=drug_id,
        target_quarters=set(quarters),
    )
    if not memories:
        memories = []

    candidates_by_quarter: dict[str, list[tuple[dict[str, Any], int]]] = {}
    for memory in memories:
        covered_quarters = _quarters_covered_by_memory(memory)
        if not covered_quarters:
            continue
        span = len(covered_quarters)
        for quarter in covered_quarters:
            if quarter not in fallback_by_quarter:
                continue
            candidates_by_quarter.setdefault(quarter, []).append((memory, span))

    chosen_memory_by_quarter: dict[str, dict[str, Any]] = {}
    for quarter, items in candidates_by_quarter.items():
        chosen_memory_by_quarter[quarter] = sorted(
            items,
            key=lambda pair: (
                pair[1],  # prefer the most specific memory span first
                -_memory_text_len(pair[0], evermemos_client=evermemos_client),
                _memory_identifier(pair[0]) or "zzzz",
            ),
        )[0][0]

    search_sequence: list[tuple[str, list[str]]] = [
        ("keyword", ["episodic_memory"]),
        ("keyword", ["event_log"]),
        ("rrf", ["episodic_memory"]),
        ("rrf", ["event_log"]),
    ]

    async def _search_memory_for_quarter(
        quarter: str,
        *,
        top_k: int,
        methods: list[tuple[str, list[str]]],
    ) -> dict[str, Any] | None:
        year, qn = quarter.split("-Q")
        query_variants = [
            f"VigiLens Quarter Digest {quarter} {drug_id}",
            f"{quarter} {drug_id} safety digest",
            f"Q{qn} {year} {drug_id} quarter digest",
        ]
        for method, memory_types in methods:
            for query in query_variants:
                search_results = await evermemos_client.search_memories(
                    db,
                    drug_id=drug_id,
                    query=query,
                    top_k=top_k,
                    retrieve_method=method,
                    memory_types=memory_types,
                )
                if not search_results:
                    continue
                selected = _select_best_memory_for_quarter(
                    search_results,
                    quarter=quarter,
                    evermemos_client=evermemos_client,
                )
                if selected is not None:
                    return selected
        return None

    # Secondary pass: for uncovered quarters, run quarter-targeted search in EverMemOS.
    missing_quarters = [quarter for quarter in quarters if quarter not in chosen_memory_by_quarter]
    if missing_quarters:
        for quarter in missing_quarters:
            selected = await _search_memory_for_quarter(quarter, top_k=60, methods=search_sequence)
            if selected is not None:
                chosen_memory_by_quarter[quarter] = selected

    episodes: list[EpisodicSummary] = []
    for quarter in quarters:
        memory = chosen_memory_by_quarter.get(quarter)
        if memory is None:
            episodes.append(fallback_by_quarter[quarter])
            continue

        text = _memory_display_text(memory, evermemos_client=evermemos_client)
        if _needs_narrative_enrichment(memory, text):
            enriched = await _search_memory_for_quarter(
                quarter,
                top_k=24,
                methods=[("keyword", ["episodic_memory"]), ("keyword", ["event_log"])],
            )
            if enriched is not None:
                enriched_text = _memory_display_text(enriched, evermemos_client=evermemos_client)
                if len(enriched_text) > len(text):
                    memory = enriched
                    text = enriched_text
        if not text:
            episodes.append(fallback_by_quarter[quarter])
            continue

        key_signals = fallback_by_quarter[quarter].key_signals_mentioned
        report_count = fallback_by_quarter[quarter].report_count_ingested
        created_at = fallback_by_quarter[quarter].created_at

        episodes.append(
            EpisodicSummary(
                quarter=quarter,
                narrative=text,
                key_signals_mentioned=key_signals,
                report_count_ingested=report_count,
                created_at=created_at,
                memory_source="evermemos",
                memory_id=_memory_identifier(memory),
            )
        )

    covered_quarters = [episode.quarter for episode in episodes if episode.memory_source == "evermemos"]
    fallback_quarters = [episode.quarter for episode in episodes if episode.memory_source == "postgres_fallback"]
    logger.info(
        "episodes coverage drug_id=%s total=%d evermemos=%d fallback=%d missing=%s",
        drug_id,
        len(episodes),
        len(covered_quarters),
        len(fallback_quarters),
        ",".join(fallback_quarters) if fallback_quarters else "-",
    )
    return episodes


def _risk_level_from_signals(max_ci_lower: float | None, n_detected: int) -> str:
    if n_detected == 0:
        return "low"
    if max_ci_lower is None:
        return "moderate"
    if max_ci_lower >= 4.0:
        return "high"
    if max_ci_lower >= 2.0:
        return "elevated"
    return "moderate"


async def _profile_snapshot_for_quarter(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter: str,
) -> dict[str, Any]:
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
    known_signals = [
        row.adverse_event
        for row in rows
        if row.signal_detected and row.ror_ci_lower is not None and row.ror_ci_lower >= 1.5
    ][:6]
    investigating_signals = [row.adverse_event for row in rows if row.adverse_event not in known_signals][:5]
    detected_lowers = [row.ror_ci_lower for row in rows if row.signal_detected and row.ror_ci_lower is not None]
    max_ci_lower = max(detected_lowers) if detected_lowers else None
    risk_level = _risk_level_from_signals(max_ci_lower=max_ci_lower, n_detected=len(known_signals))
    assessment = (
        f"As of {quarter}, known monitored signals include "
        f"{', '.join(known_signals) if known_signals else 'no high-priority detected signals'}."
    )
    return {
        "entity": drug_id,
        "risk_level": risk_level,
        "known_signals": known_signals,
        "investigating_signals": investigating_signals,
        "assessment": assessment,
        "last_updated": quarter,
    }


async def get_drug_profile(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
) -> DrugProfile:
    drug, state = await _get_drug_and_state(db, drug_id)
    quarters = sort_quarters(list(state.quarters_loaded or []))
    if not quarters:
        return DrugProfile(
            drug_id=drug_id,
            current_assessment=(
                f"No quarters are loaded yet for {drug.generic_name}. {DISCLAIMER_SENTENCE}"
            ),
            risk_level="low",
            known_signals=[],
            investigating_signals=[],
            last_updated=_now_iso(),
        )

    latest_quarter = quarters[-1]
    rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == latest_quarter,
                )
            )
        )
        .scalars()
        .all()
    )
    rows = sorted(rows, key=_signal_sort_key)

    known_signals = [
        row.adverse_event
        for row in rows
        if row.consensus_tier in {"public_signal", "priority_review"} or (row.signal_detected and row.ror_ci_lower is not None and row.ror_ci_lower >= 1.5)
    ]

    investigating_signals = [
        row.adverse_event
        for row in rows
        if row.adverse_event not in known_signals and row.consensus_tier in {"watchlist", "priority_review", "public_signal"}
    ][:5]

    detected_lowers = [row.ror_ci_lower for row in rows if row.signal_detected and row.ror_ci_lower is not None]
    max_ci_lower = max(detected_lowers) if detected_lowers else None
    risk_level = _risk_level_from_signals(max_ci_lower=max_ci_lower, n_detected=len(known_signals))

    base_assessment = (
        f"As of {latest_quarter}, known monitored signals include "
        f"{', '.join(known_signals) if known_signals else 'no high-priority detected signals'}."
    )

    profile_payload = await evermemos_client.fetch_profile(db, drug_id=drug_id)
    profile_memories = evermemos_client.extract_memories(profile_payload)
    profile_text = (
        evermemos_client.extract_memory_text(profile_memories[0])
        if profile_memories
        else ""
    )

    if profile_text:
        current_assessment = f"EverMemOS profile: {profile_text}\n\n{base_assessment} {DISCLAIMER_SENTENCE}"
    else:
        current_assessment = f"{base_assessment} {DISCLAIMER_SENTENCE}"

    return DrugProfile(
        drug_id=drug_id,
        current_assessment=current_assessment,
        risk_level=risk_level,
        known_signals=known_signals[:6],
        investigating_signals=investigating_signals,
        last_updated=_now_iso(),
    )


async def _top_reactions_for_quarter(db: AsyncSession, drug_id: str, quarter: str) -> list[tuple[str, int]]:
    start_date, end_date = quarter_to_dates(quarter)
    rows = (
        (
            await db.execute(
                select(FaersReportReaction.meddra_pt, func.count(func.distinct(FaersReportReaction.safetyreportid)).label("cnt"))
                .select_from(FaersReportReaction)
                .join(FaersReport, FaersReport.safetyreportid == FaersReportReaction.safetyreportid)
                .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
                .where(
                    FaersReportDrug.drug_id == drug_id,
                    FaersReportDrug.role == "suspect",
                    FaersReport.receivedate >= start_date,
                    FaersReport.receivedate <= end_date,
                )
                .group_by(FaersReportReaction.meddra_pt)
                .order_by(desc("cnt"), FaersReportReaction.meddra_pt.asc())
                .limit(3)
            )
        )
        .all()
    )
    return [(row.meddra_pt, int(row.cnt)) for row in rows]


async def _select_exemplar_report_ids(db: AsyncSession, drug_id: str, quarter: str) -> list[str]:
    start_date, end_date = quarter_to_dates(quarter)
    focus_rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter == quarter,
                )
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    focus_rows = sorted(focus_rows, key=_signal_sort_key)[:5]
    focus_terms: set[str] = set()
    for row in focus_rows:
        focus_terms.update(row.supporting_terms or [row.adverse_event])

    tracked_case = case((FaersReportReaction.meddra_pt.in_(list(focus_terms or {""})), 1), else_=0)
    reaction_count_subq = (
        select(
            FaersReportReaction.safetyreportid.label("rid"),
            func.count(FaersReportReaction.meddra_pt).label("reaction_count"),
            func.max(tracked_case).label("has_tracked"),
        )
        .group_by(FaersReportReaction.safetyreportid)
        .subquery()
    )

    rows = (
        (
            await db.execute(
                select(FaersReport.safetyreportid)
                .select_from(FaersReport)
                .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
                .join(reaction_count_subq, reaction_count_subq.c.rid == FaersReport.safetyreportid)
                .where(
                    FaersReportDrug.drug_id == drug_id,
                    FaersReportDrug.role == "suspect",
                    FaersReport.receivedate >= start_date,
                    FaersReport.receivedate <= end_date,
                )
                .order_by(
                    FaersReport.serious.desc(),
                    reaction_count_subq.c.has_tracked.desc(),
                    reaction_count_subq.c.reaction_count.desc(),
                    FaersReport.receivedate.desc(),
                    FaersReport.safetyreportid.asc(),
                )
                .limit(5)
            )
        )
        .all()
    )
    return [row.safetyreportid for row in rows]


def build_quarter_digest_message(
    *,
    drug_id: str,
    quarter: str,
    report_count: int,
    cumulative_count: int,
    detected_signals: list[SignalPoint],
    newly_detected: list[str],
    profile_risk_level: str,
) -> str:
    lines = [
        f"VigiLens {quarter} Surveillance Summary for {drug_id}:",
        f"{report_count} new adverse event reports processed this quarter ({cumulative_count} cumulative).",
    ]

    if detected_signals:
        top = detected_signals[0]
        if top.ror is None:
            lines.append(f"Leading signal: {top.adverse_event} ({top.trajectory} trajectory).")
        else:
            lines.append(
                f"Leading signal: {top.adverse_event} (ROR {top.ror:.2f}, {top.trajectory} trajectory)."
            )

    if newly_detected:
        lines.append(
            f"Notable: {', '.join(newly_detected)} newly crossed detection threshold this quarter."
        )

    if detected_signals:
        lines.append(
            f"Active signals: {', '.join(signal.adverse_event for signal in detected_signals)}."
        )

    lines.append(f"Overall risk assessment: {profile_risk_level}.")
    lines.append(DISCLAIMER_SENTENCE)
    return " ".join(lines)


async def build_quarter_digest_payload(db: AsyncSession, *, drug_id: str, quarter: str) -> dict[str, Any]:
    drug = await db.scalar(select(Drug).where(Drug.id == drug_id))
    if drug is None:
        raise AppError(error="BadRequest", detail=f"drug_id '{drug_id}' not found", status_code=400)

    quarter_reports = await _count_reports_in_quarter(db, drug_id, quarter)
    top_signals_all = (
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

    detected_points = [_signal_row_to_schema(row) for row in top_signals_all if row.signal_detected]
    cumulative_count = max([row.cumulative_count for row in top_signals_all], default=0)
    detected_ci_lowers = [row.ror_ci_lower for row in top_signals_all if row.signal_detected and row.ror_ci_lower is not None]
    profile_risk_level = _risk_level_from_signals(
        max(detected_ci_lowers) if detected_ci_lowers else None,
        len(detected_points),
    )

    previous_quarter = quarter_minus_one(quarter)
    previous_detected: set[str] = set()
    if previous_quarter:
        previous_rows = (
            (
                await db.execute(
                    select(QuarterlyStat.adverse_event)
                    .where(
                        QuarterlyStat.drug_id == drug_id,
                        QuarterlyStat.quarter == previous_quarter,
                        QuarterlyStat.signal_detected.is_(True),
                    )
                )
            )
            .all()
        )
        previous_detected = {row.adverse_event for row in previous_rows}
    current_detected = {point.adverse_event for point in detected_points}
    newly_detected = sorted(current_detected - previous_detected)

    exemplar_ids = await _select_exemplar_report_ids(db, drug_id, quarter)

    _, quarter_end = quarter_to_dates(quarter)
    create_time = datetime(quarter_end.year, quarter_end.month, quarter_end.day, tzinfo=timezone.utc).isoformat()
    narrative = build_quarter_digest_message(
        drug_id=drug_id,
        quarter=quarter,
        report_count=quarter_reports,
        cumulative_count=cumulative_count,
        detected_signals=detected_points[:6],
        newly_detected=newly_detected,
        profile_risk_level=profile_risk_level,
    )

    content = (
        f"{narrative}\n\n"
        f"Drug reference: {drug.generic_name} ({'/'.join(drug.brand_names)})\n"
        f"Evidence exemplars (FAERS safetyreportid): {', '.join(exemplar_ids) if exemplar_ids else 'none'}"
    )

    quarter_token = quarter.replace("-", "")
    return {
        "message_id": f"vigl_{drug_id}_{quarter_token}_digest",
        "create_time": create_time,
        "sender": f"drug:{drug_id}",
        "sender_name": drug.generic_name.capitalize(),
        "role": "user",
        "content": content,
        "group_id": f"vigl:{drug_id}",
        "group_name": f"VigiLens: {drug_id}",
        "refer_list": [],
    }


def build_conversation_meta_payload(drug_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "version": "1.0.0",
        "scene": "assistant",
        "scene_desc": {
            "description": "VigiLens pharmacovigilance demo for FAERS time-series signal detection",
            "type": "pharmacovigilance_demo",
        },
        "name": f"VigiLens: {drug_id}",
        "description": f"Quarterly digests and profile updates for {drug_id} FAERS monitoring",
        "group_id": f"vigl:{drug_id}",
        "created_at": now,
        "default_timezone": "America/Los_Angeles",
        "user_details": {
            f"drug:{drug_id}": {"full_name": drug_id.capitalize(), "role": "user", "custom_role": "drug_entity"},
            "vigl:assistant": {"full_name": "VigiLens", "role": "assistant", "custom_role": "pv_analyst_ai"},
        },
        "tags": ["pharmacovigilance", "faers", drug_id, "demo"],
    }


def _build_event_log_data(report: Any, *, quarter: str) -> dict[str, Any]:
    return {
        "report_id": report.safetyreportid,
        "quarter": quarter,
        "receivedate": report.receivedate,
        "patient_sex": report.patient_sex,
        "patient_age": report.patient_age,
        "reactions": list(report.reactions or []),
        "suspect_drugs": list(report.suspect_drugs or []),
        "concomitant_drugs": list(report.concomitant_drugs or []),
        "serious": bool(report.serious),
        "outcomes": list(report.outcomes or []),
        "evidence_api_path": report.evidence_api_path,
    }


async def _sync_quarter_event_logs(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
    quarter: str,
) -> None:
    reports = await fetch_quarter_evidence_reports(db, drug_id=drug_id, quarter=quarter)
    # Postgres remains the source of truth for the full evidence ledger. For live demo
    # responsiveness we only mirror a small representative EventLog sample into EverMemOS.
    reports = reports[:MAX_EVENT_LOG_MEMORY_WRITES_PER_QUARTER]
    for report in reports:
        ok = await evermemos_client.store_event_log_memory(
            db,
            drug_id=drug_id,
            quarter=quarter,
            event_log_data=_build_event_log_data(report, quarter=quarter),
        )
        if not ok:
            # EverMemOS is augmentation only. Stop after the first failure so an offline
            # seed/ingest run does not turn into hundreds of sequential timeout attempts.
            break


async def sync_seed_memories(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
    quarters: list[str],
    include_event_logs: bool = True,
) -> None:
    await evermemos_client.post_conversation_meta(
        db,
        drug_id=drug_id,
        body=build_conversation_meta_payload(drug_id),
    )

    for quarter in quarters:
        if include_event_logs:
            await _sync_quarter_event_logs(
                db,
                evermemos_client=evermemos_client,
                drug_id=drug_id,
                quarter=quarter,
            )
        payload = await build_quarter_digest_payload(db, drug_id=drug_id, quarter=quarter)
        await evermemos_client.post_quarter_digest(
            db,
            drug_id=drug_id,
            quarter=quarter,
            body=payload,
        )


async def sync_seed_memories_after_commit(
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
    quarters: list[str],
    include_event_logs: bool = True,
) -> None:
    session_factory = get_session_factory()
    try:
        async with session_factory() as sync_db:
            await sync_seed_memories(
                sync_db,
                evermemos_client=evermemos_client,
                drug_id=drug_id,
                quarters=quarters,
                include_event_logs=include_event_logs,
            )
            await sync_db.commit()
    except Exception:
        logger.warning("Failed to sync seed memories for %s", drug_id, exc_info=True)


async def post_ingest_digest(
    db: AsyncSession,
    *,
    evermemos_client: EvermemosClient,
    drug_id: str,
    quarter: str,
) -> bool:
    await _sync_quarter_event_logs(
        db,
        evermemos_client=evermemos_client,
        drug_id=drug_id,
        quarter=quarter,
    )
    payload = await build_quarter_digest_payload(db, drug_id=drug_id, quarter=quarter)
    posted = await evermemos_client.post_quarter_digest(
        db,
        drug_id=drug_id,
        quarter=quarter,
        body=payload,
    )
    profile_snapshot = await _profile_snapshot_for_quarter(db, drug_id=drug_id, quarter=quarter)
    await evermemos_client.store_profile_memory(
        db,
        drug_id=drug_id,
        profile_data=profile_snapshot,
    )
    return posted
