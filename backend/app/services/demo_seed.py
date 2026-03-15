from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    Belief,
    Drug,
    FdaAction,
    FaersReport,
    FaersReportDrug,
    FaersReportReaction,
    IngestionState,
    Prediction,
    QuarterlyStat,
)
from app.schemas.admin import SeedDemoResponse
from app.services.belief_engine import generate_tracked_beliefs_for_quarter
from app.services.drug_insights_service import sync_seed_memories_after_commit
from app.services.evermemos_client import EvermemosClient
from app.services.prediction_engine import maybe_generate_predictions
from app.services.signal_engine import recompute_signals_after_ingestion
from app.utils.quarters import date_to_quarter, next_quarter, parse_quarter, sort_quarters

VALID_PATIENT_SEX = {"male", "female", "unknown"}
VALID_DRUG_ROLE = {"suspect", "concomitant", "interacting", "unknown"}
SEED_EVENT_LOG_SYNC_REPORT_LIMIT = 5000
RUNTIME_SCHEMA_FIXES = (
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_beliefs_drug_question_quarter "
        "ON beliefs(drug_id, question_hash, quarter_context)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_beliefs_drug_created ON beliefs(drug_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_beliefs_hash ON beliefs(drug_id, question_hash)",
)

CURATED_FDA_ACTIONS: list[dict[str, str]] = [
    {
        "id": "ozempic_label_2023_09_ileus",
        "drug_id": "semaglutide",
        "date": "2023-09-01",
        "type": "label_change",
        "title": "Ozempic label revised (Sep 2023): Ileus added to postmarketing GI disorders",
        "description": "Postmarketing Experience includes: Gastrointestinal Disorders: Ileus.",
        "source_url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?audience=consumer&setid=adec4fd2-6858-4c99-91d4-531f5f2a2d79",
    },
    {
        "id": "fda_glp1_suicidal_update_2024_01_11",
        "drug_id": "semaglutide",
        "date": "2024-01-11",
        "type": "safety_communication",
        "title": "FDA update on ongoing evaluation of reports of suicidal thoughts/actions with GLP-1 receptor agonists",
        "description": "Class-wide FDA update including semaglutide products.",
        "source_url": "https://www.fda.gov/drugs/drug-safety-and-availability/update-fdas-ongoing-evaluation-reports-suicidal-thoughts-or-actions-patients-taking-certain-type",
    },
    {
        "id": "fda_glp1_suicidal_update_2026_01_13",
        "drug_id": "semaglutide",
        "date": "2026-01-13",
        "type": "warning",
        "title": "FDA requests removal of suicidal behavior warning from GLP-1 receptor agonists",
        "description": "FDA update and removal request page.",
        "source_url": "https://www.fda.gov/drugs/drug-safety-and-availability/fda-requests-removal-suicidal-behavior-warning-glp-1-receptor-agonists",
    },
]

# The docker seed container and demo smoke can both hit /admin/seed-demo during startup.
# Serializing the seed flow avoids Postgres deadlocks while the deterministic fixture is reset.
SEED_DEMO_LOCK = asyncio.Lock()


class SeedDrugRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str | None = None
    drug_name: str
    role: str = "unknown"


class SeedReportRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    safetyreportid: str
    version: int = 1
    receivedate: str
    patient_sex: str = "unknown"
    patient_age: float | None = None
    reactions: list[str] = Field(default_factory=list)
    drugs: list[SeedDrugRow] = Field(default_factory=list)
    serious: bool = False
    outcomes: list[str] = Field(default_factory=list)
    is_duplicate: bool = False


def _resolve_data_file(
    override_data_dir: Path | None,
    default_data_dir: Path | None,
    drug_id: str,
) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    file_name = f"{drug_id}.ndjson"
    candidates: list[Path] = []
    if override_data_dir is not None:
        candidates.append(Path(override_data_dir) / file_name)
    if override_data_dir is None and drug_id == "minoxidil":
        candidates.append(repo_root / "data" / "demo" / file_name)
    if default_data_dir is not None:
        candidates.append(Path(default_data_dir) / file_name)
    candidates.extend(
        [
            repo_root / "data" / "real" / file_name,
            repo_root / "data" / "demo" / file_name,
        ]
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    if override_data_dir is not None:
        return Path(override_data_dir) / file_name
    if default_data_dir is not None:
        return Path(default_data_dir) / file_name
    return repo_root / "data" / "real" / file_name


def _resolve_background_seed_sql() -> Path:
    return Path(__file__).resolve().parents[2] / "sql" / "seed_background_counts.sql"


def _normalize_patient_sex(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in VALID_PATIENT_SEX else "unknown"


def _normalize_role(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in VALID_DRUG_ROLE else "unknown"


async def _validate_drug_exists(db: AsyncSession, drug_id: str) -> None:
    exists = await db.scalar(select(func.count()).select_from(Drug).where(Drug.id == drug_id))
    if not exists:
        raise AppError(
            error="BadRequest",
            detail=f"drug_id '{drug_id}' not found",
            status_code=400,
        )


async def _ensure_runtime_seed_schema(db: AsyncSession) -> None:
    # Reused local Postgres volumes may predate newer deterministic seed indexes.
    for ddl in RUNTIME_SCHEMA_FIXES:
        await db.execute(text(ddl))


async def _upsert_curated_fda_actions(db: AsyncSession) -> None:
    for row in CURATED_FDA_ACTIONS:
        await db.execute(
            pg_insert(FdaAction)
            .values(**row)
            .on_conflict_do_update(
                index_elements=[FdaAction.id],
                set_={
                    "drug_id": row["drug_id"],
                    "date": row["date"],
                    "type": row["type"],
                    "title": row["title"],
                    "description": row["description"],
                    "source_url": row["source_url"],
                },
            )
        )


async def _upsert_report(db: AsyncSession, report: SeedReportRow, raw_payload: dict) -> None:
    upsert_stmt = (
        pg_insert(FaersReport)
        .values(
            safetyreportid=report.safetyreportid,
            version=report.version,
            receivedate=report.receivedate,
            patient_sex=_normalize_patient_sex(report.patient_sex),
            patient_age=report.patient_age,
            serious=report.serious,
            outcomes=report.outcomes,
            raw_json=raw_payload,
            is_duplicate=report.is_duplicate,
        )
        .on_conflict_do_update(
            index_elements=[FaersReport.safetyreportid],
            set_={
                "version": report.version,
                "receivedate": report.receivedate,
                "patient_sex": _normalize_patient_sex(report.patient_sex),
                "patient_age": report.patient_age,
                "serious": report.serious,
                "outcomes": report.outcomes,
                "raw_json": raw_payload,
                "is_duplicate": report.is_duplicate,
            },
        )
    )
    await db.execute(upsert_stmt)

    await db.execute(
        delete(FaersReportReaction).where(
            FaersReportReaction.safetyreportid == report.safetyreportid
        )
    )
    if report.reactions:
        reaction_rows = [
            {"safetyreportid": report.safetyreportid, "meddra_pt": reaction}
            for reaction in sorted(set(report.reactions))
        ]
        await db.execute(insert(FaersReportReaction), reaction_rows)

    await db.execute(
        delete(FaersReportDrug).where(FaersReportDrug.safetyreportid == report.safetyreportid)
    )
    if report.drugs:
        drug_rows = []
        for drug in report.drugs:
            drug_rows.append(
                {
                    "safetyreportid": report.safetyreportid,
                    "drug_id": drug.drug_id,
                    "drug_name": drug.drug_name,
                    "role": _normalize_role(drug.role),
                }
            )
        if drug_rows:
            await db.execute(
                pg_insert(FaersReportDrug)
                .values(drug_rows)
                .on_conflict_do_nothing(index_elements=["safetyreportid", "drug_name", "role"])
            )


async def _repair_null_drug_ids_for_known_aliases(db: AsyncSession, drug_id: str) -> None:
    drug = await db.scalar(select(Drug).where(Drug.id == drug_id))
    if drug is None:
        return

    aliases = {
        value.strip().lower()
        for value in [drug.id, drug.generic_name, *(drug.brand_names or [])]
        if isinstance(value, str) and value.strip()
    }
    if not aliases:
        return

    await db.execute(
        update(FaersReportDrug)
        .where(
            FaersReportDrug.role == "suspect",
            FaersReportDrug.drug_id.is_(None),
            func.lower(FaersReportDrug.drug_name).in_(aliases),
        )
        .values(drug_id=drug_id)
    )


async def _count_suspect_reports_for_drug(db: AsyncSession, drug_id: str) -> int:
    value = await db.scalar(
        select(func.count(func.distinct(FaersReportDrug.safetyreportid))).where(
            FaersReportDrug.drug_id == drug_id,
            FaersReportDrug.role == "suspect",
        )
    )
    return int(value or 0)


async def _upsert_ingestion_state(
    db: AsyncSession,
    drug_id: str,
    preload_quarters: list[str],
    first_available_quarter: str | None,
    last_available_quarter: str | None,
) -> None:
    sorted_quarters = sort_quarters(preload_quarters)
    if sorted_quarters:
        if last_available_quarter is None:
            next_q = None
        else:
            candidate = next_quarter(sorted_quarters[-1])
            next_q = candidate if parse_quarter(candidate) <= parse_quarter(last_available_quarter) else None
        evermemos_status = "ready"
    else:
        next_q = first_available_quarter
        evermemos_status = "idle"

    upsert_stmt = (
        pg_insert(IngestionState)
        .values(
            drug_id=drug_id,
            quarters_loaded=sorted_quarters,
            next_quarter=next_q,
            evermemos_status=evermemos_status,
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            index_elements=[IngestionState.drug_id],
            set_={
                "quarters_loaded": sorted_quarters,
                "next_quarter": next_q,
                "evermemos_status": evermemos_status,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )
    await db.execute(upsert_stmt)


async def _available_quarter_bounds(db: AsyncSession, drug_id: str) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(func.min(FaersReport.receivedate), func.max(FaersReport.receivedate))
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


def _load_report_rows(file_path: Path) -> list[tuple[SeedReportRow, dict]]:
    if not file_path.exists():
        raise AppError(
            error="BadRequest",
            detail=f"Demo data file not found: {file_path}",
            status_code=400,
        )

    rows: list[tuple[SeedReportRow, dict]] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            row = SeedReportRow.model_validate(payload)
            rows.append((row, payload))
    return rows


async def seed_demo_data(
    db: AsyncSession,
    drug_ids: list[str],
    preload_quarters: list[str],
    data_dir: Path | None,
    settings: Settings,
    evermemos_client: EvermemosClient,
) -> SeedDemoResponse:
    async with SEED_DEMO_LOCK:
        background_seed_sql = _resolve_background_seed_sql()
        normalized_preload = sort_quarters(preload_quarters)
        deterministic_seed_settings = settings.model_copy(
            update={
                "gemini_api_key": None,
                "gemini_grounding_scorecard_verify": False,
                "openfda_live_background": False,
            }
        )
        await _ensure_runtime_seed_schema(db)
        await _upsert_curated_fda_actions(db)

        validated_drug_ids: list[str] = []
        pending_seed_memory_syncs: list[tuple[str, list[str], bool]] = []

        # Pass 1: validate and load all demo evidence first.
        for drug_id in drug_ids:
            await _validate_drug_exists(db, drug_id)
            validated_drug_ids.append(drug_id)

            file_path = _resolve_data_file(data_dir, settings.demo_data_dir, drug_id)
            rows = _load_report_rows(file_path)
            # Deterministic pass: later lines with higher version overwrite earlier rows for same report.
            for report, raw_payload in rows:
                await _upsert_report(db, report, raw_payload)

        if background_seed_sql.exists():
            seed_sql = background_seed_sql.read_text(encoding="utf-8").strip()
            if seed_sql:
                await db.execute(text(seed_sql))
                await db.flush()

        for drug_id in validated_drug_ids:
            await _repair_null_drug_ids_for_known_aliases(db, drug_id)
        await db.flush()

        # Pass 2: reset state + recompute stats once all comparator evidence is present.
        for drug_id in validated_drug_ids:
            first_available_quarter, last_available_quarter = await _available_quarter_bounds(db, drug_id)
            reports_loaded_for_drug = await _count_suspect_reports_for_drug(db, drug_id)

            bounded_preload = normalized_preload
            if last_available_quarter is not None:
                bounded_preload = [
                    quarter
                    for quarter in normalized_preload
                    if parse_quarter(quarter) <= parse_quarter(last_available_quarter)
                ]

            await _upsert_ingestion_state(
                db,
                drug_id,
                bounded_preload,
                first_available_quarter,
                last_available_quarter,
            )
            await db.execute(delete(QuarterlyStat).where(QuarterlyStat.drug_id == drug_id))
            await db.execute(delete(Belief).where(Belief.drug_id == drug_id))
            await db.execute(delete(Prediction).where(Prediction.drug_id == drug_id))

            for quarter in bounded_preload:
                await recompute_signals_after_ingestion(
                    db,
                    drug_id=drug_id,
                    quarter=quarter,
                    settings=deterministic_seed_settings,
                )
                await maybe_generate_predictions(
                    db,
                    drug_id=drug_id,
                    quarter=quarter,
                    evermemos_client=None,
                    settings=deterministic_seed_settings,
                )

            for quarter in bounded_preload:
                await generate_tracked_beliefs_for_quarter(
                    db,
                    settings=deterministic_seed_settings,
                    drug_id=drug_id,
                    quarter=quarter,
                    evermemos_client=None,
                )
            await db.commit()
            pending_seed_memory_syncs.append(
                (
                    drug_id,
                    bounded_preload,
                    reports_loaded_for_drug <= SEED_EVENT_LOG_SYNC_REPORT_LIMIT,
                )
            )

        for drug_id, quarters, include_event_logs in pending_seed_memory_syncs:
            asyncio.create_task(
                sync_seed_memories_after_commit(
                    evermemos_client=evermemos_client,
                    drug_id=drug_id,
                    quarters=quarters,
                    include_event_logs=include_event_logs,
                )
            )

        reports_by_drug: dict[str, int] = {}
        for drug_id in validated_drug_ids:
            reports_by_drug[drug_id] = await _count_suspect_reports_for_drug(db, drug_id)

        reports_loaded = sum(reports_by_drug.values())
        return SeedDemoResponse(
            seeded_drugs=validated_drug_ids,
            preload_quarters=normalized_preload,
            reports_loaded=reports_loaded,
            reports_by_drug=reports_by_drug,
        )
