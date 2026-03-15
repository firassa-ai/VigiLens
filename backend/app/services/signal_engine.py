from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_SETTINGS, Settings
from app.db.models import (
    Drug,
    FaersReport,
    FaersReportDrug,
    FaersReportReaction,
    IngestionState,
    QuarterlyStat,
)
from app.schemas.shared import SignalPoint, SignalTrajectory
from app.services.forecast_policy import is_strict_demo_drug, method_vote_count
from app.services.openfda_background_service import get_background_counts
from app.services.signal_catalog import (
    SignalCatalogEntry,
    SignalConsensusTier,
    build_signal_catalog,
    consensus_tier_rank,
)
from app.utils.quarters import quarter_minus_one, quarter_to_dates, sort_quarters


@dataclass(frozen=True)
class SignalUpdate:
    adverse_event: str
    quarter: str
    signal_point: SignalPoint
    is_new_signal: bool


@dataclass(frozen=True)
class DisproportionalityMetrics:
    ror: float | None
    ror_ci_lower: float | None
    ror_ci_upper: float | None
    prr: float | None
    chi_squared: float | None
    bcpnn_ic: float | None
    bcpnn_ic025: float | None
    ebgm: float | None
    eb05: float | None
    method_votes: dict[str, bool]
    signal_detected: bool


INSUFFICIENT_METRICS = DisproportionalityMetrics(
    ror=None,
    ror_ci_lower=None,
    ror_ci_upper=None,
    prr=None,
    chi_squared=None,
    bcpnn_ic=None,
    bcpnn_ic025=None,
    ebgm=None,
    eb05=None,
    method_votes={"ror": False, "prr": False, "bcpnn": False, "mgps": False},
    signal_detected=False,
)


def _clamp_positive(value: int) -> int:
    return value if value > 0 else 0


def compute_disproportionality_metrics(a: int, b: int, c: int, d: int) -> DisproportionalityMetrics:
    a = _clamp_positive(a)
    b = _clamp_positive(b)
    c = _clamp_positive(c)
    d = _clamp_positive(d)

    ror: float | None = None
    ror_ci_lower: float | None = None
    ror_ci_upper: float | None = None

    if a > 0 and b > 0 and c > 0 and d > 0:
        ror = (a * d) / (b * c)
        ln_ror = math.log(a) + math.log(d) - math.log(b) - math.log(c)
        se = math.sqrt((1 / a) + (1 / b) + (1 / c) + (1 / d))
        ror_ci_lower = math.exp(ln_ror - 1.96 * se)
        ror_ci_upper = math.exp(ln_ror + 1.96 * se)

    prr: float | None = None
    if (a + b) > 0 and (c + d) > 0 and c > 0:
        prr = (a / (a + b)) / (c / (c + d))

    chi_squared: float | None = None
    n = a + b + c + d
    expected: float | None = None
    if n > 0:
        r1 = a + b
        r2 = c + d
        c1 = a + c
        c2 = b + d
        expected = (r1 * c1) / n if n else None

        e11 = (r1 * c1) / n
        e12 = (r1 * c2) / n
        e21 = (r2 * c1) / n
        e22 = (r2 * c2) / n

        expected_values = [e11, e12, e21, e22]
        if all(v > 0 for v in expected_values):
            chi_squared = (
                ((a - e11) ** 2) / e11
                + ((b - e12) ** 2) / e12
                + ((c - e21) ** 2) / e21
                + ((d - e22) ** 2) / e22
            )

    bcpnn_ic: float | None = None
    bcpnn_ic025: float | None = None
    if n > 0:
        p_xy = (a + 0.5) / (n + 1)
        p_x = (a + b + 0.5) / (n + 1)
        p_y = (a + c + 0.5) / (n + 1)
        denom = p_x * p_y
        if denom > 0 and p_xy > 0:
            bcpnn_ic = math.log2(p_xy / denom)
            ic_se = math.sqrt(
                (1 / (a + 0.5))
                + (1 / (a + b + 0.5))
                + (1 / (a + c + 0.5))
                + (1 / (n + 1))
            ) / math.log(2)
            bcpnn_ic025 = bcpnn_ic - 1.96 * ic_se

    ebgm: float | None = None
    eb05: float | None = None
    if expected is not None and expected >= 0:
        ebgm = (a + 0.5) / (expected + 0.5)
        ebgm_se = math.sqrt((1 / (a + 0.5)) + (1 / (expected + 0.5)))
        eb05 = math.exp(math.log(ebgm) - 1.645 * ebgm_se)

    method_votes = {
        "ror": bool(a >= 3 and ror_ci_lower is not None and ror_ci_lower > 1),
        "prr": bool(a >= 3 and prr is not None and prr >= 2 and chi_squared is not None and chi_squared >= 4),
        "bcpnn": bool(bcpnn_ic025 is not None and bcpnn_ic025 > 0),
        "mgps": bool(eb05 is not None and eb05 >= 2),
    }
    signal_detected = method_votes["ror"]

    return DisproportionalityMetrics(
        ror=ror,
        ror_ci_lower=ror_ci_lower,
        ror_ci_upper=ror_ci_upper,
        prr=prr,
        chi_squared=chi_squared,
        bcpnn_ic=bcpnn_ic,
        bcpnn_ic025=bcpnn_ic025,
        ebgm=ebgm,
        eb05=eb05,
        method_votes=method_votes,
        signal_detected=signal_detected,
    )


def _signal_detected_for_drug(
    *,
    drug_id: str,
    cumulative_count: int,
    method_votes: dict[str, bool],
    priority_flag: bool,
) -> bool:
    if is_strict_demo_drug(drug_id):
        return bool(method_votes.get("ror"))
    vote_count = method_vote_count(method_votes)
    return cumulative_count >= 3 and (vote_count >= 2 or (priority_flag and vote_count >= 1))


def classify_trajectory(
    quarterly_rors: list[float | None],
    signal_detected_flags: list[bool],
) -> SignalTrajectory:
    x = [ror for ror in quarterly_rors if ror is not None]
    k = len(x)
    if k < 4:
        return "insufficient_data"

    v1 = x[-1] - x[-2]
    v2 = x[-2] - x[-3]
    v3 = x[-3] - x[-4]

    v_recent = (v1 + v2 + v3) / 3
    a1 = v1 - v2
    a2 = v2 - v3
    a_recent = (a1 + a2) / 2

    vel_eps = 0.10
    acc_eps = 0.05
    emerge_n = 2

    if not signal_detected_flags[-1]:
        if v1 < 0 and v2 < 0 and v3 < 0:
            return "declining"
        return "stable"

    first_true_idx = max(
        i
        for i in range(len(signal_detected_flags))
        if signal_detected_flags[i] and (i == 0 or not signal_detected_flags[i - 1])
    )
    if len(signal_detected_flags) - 1 - first_true_idx <= emerge_n:
        return "emerging"
    if v_recent > vel_eps and a_recent > acc_eps:
        return "accelerating"
    if abs(v_recent) <= vel_eps:
        return "stable"
    if v_recent < -vel_eps:
        return "declining"
    return "stable"


async def _count_distinct_reports(
    db: AsyncSession,
    *,
    drug_id: str | None = None,
    role: str | None = None,
    event_terms: tuple[str, ...] | None = None,
    start_date: date | None = None,
    end_date: date,
) -> int:
    stmt = select(func.count(func.distinct(FaersReport.safetyreportid))).select_from(FaersReport)

    if drug_id is not None or role is not None:
        stmt = stmt.join(
            FaersReportDrug,
            FaersReportDrug.safetyreportid == FaersReport.safetyreportid,
        )

    if event_terms is not None:
        stmt = stmt.join(
            FaersReportReaction,
            FaersReportReaction.safetyreportid == FaersReport.safetyreportid,
        )

    conditions = [FaersReport.receivedate <= end_date]
    if start_date is not None:
        conditions.append(FaersReport.receivedate >= start_date)
    if drug_id is not None:
        conditions.append(FaersReportDrug.drug_id == drug_id)
    if role is not None:
        conditions.append(FaersReportDrug.role == role)
    if event_terms is not None:
        conditions.append(FaersReportReaction.meddra_pt.in_(event_terms))

    stmt = stmt.where(and_(*conditions))
    value = await db.scalar(stmt)
    return int(value or 0)


async def _fetch_quarters_loaded(db: AsyncSession, drug_id: str) -> list[str]:
    quarters = await db.scalar(
        select(IngestionState.quarters_loaded).where(IngestionState.drug_id == drug_id)
    )
    if not quarters:
        return []
    return sort_quarters(list(quarters))


async def _resolve_background_counts(
    db: AsyncSession,
    *,
    drug_id: str,
    settings: Settings,
    quarter: str,
    entry: SignalCatalogEntry,
    cumulative_start_date: date,
    quarter_end_date: date,
    local_total_cumulative: int,
) -> tuple[int, int] | None:
    if entry.term_level == "pt" and len(entry.event_terms) == 1:
        background_counts = await get_background_counts(
            db,
            settings=settings,
            quarter=quarter,
            adverse_event=entry.event_terms[0],
        )
        if background_counts is not None or is_strict_demo_drug(drug_id):
            return background_counts

    local_event_cumulative = await _count_distinct_reports(
        db,
        event_terms=entry.event_terms,
        start_date=cumulative_start_date,
        end_date=quarter_end_date,
    )
    return local_total_cumulative, local_event_cumulative


def _consensus_tier_for_row(
    *,
    cumulative_count: int,
    trajectory: SignalTrajectory,
    method_votes: dict[str, bool],
    label_status: str,
    priority_flag: bool,
    prior_positive_count: int,
    strict_demo: bool,
) -> SignalConsensusTier:
    vote_count = method_vote_count(method_votes)
    if strict_demo:
        watchlist = (
            cumulative_count >= 3
            and vote_count >= 2
            and (method_votes.get("ror") or method_votes.get("bcpnn"))
        )
        public_signal = (
            watchlist
            and vote_count >= 3
            and cumulative_count >= 5
            and (trajectory == "accelerating" or prior_positive_count >= 1)
            and (label_status == "label_gap" or priority_flag)
        )
    else:
        watchlist = cumulative_count >= 3 and (vote_count >= 2 or (priority_flag and vote_count >= 1))
        public_signal = (
            watchlist
            and vote_count >= 3
            and cumulative_count >= 5
            and (trajectory == "accelerating" or prior_positive_count >= 1)
            and (label_status == "label_gap" or priority_flag)
        )
    if public_signal:
        return "public_signal"
    if priority_flag and vote_count >= 1 and cumulative_count >= 3:
        return "priority_review"
    if watchlist:
        return "watchlist"
    return "none"


def _row_to_signal_point(row: QuarterlyStat) -> SignalPoint:
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


async def recompute_signals_after_ingestion(
    db: AsyncSession,
    drug_id: str,
    quarter: str,
    settings: Settings | None = None,
) -> list[SignalUpdate]:
    active_settings = settings or DEFAULT_SETTINGS
    strict_demo = is_strict_demo_drug(drug_id)
    quarter_start_date, quarter_end_date = quarter_to_dates(quarter)
    cumulative_start_date = date(2018, 1, 1)

    catalog = await build_signal_catalog(db, drug_id=drug_id)
    if not catalog:
        return []

    drug_total_cumulative = await _count_distinct_reports(
        db,
        drug_id=drug_id,
        role="suspect",
        start_date=cumulative_start_date,
        end_date=quarter_end_date,
    )
    local_total_cumulative = await _count_distinct_reports(
        db,
        start_date=cumulative_start_date,
        end_date=quarter_end_date,
    )

    current_points_by_event: dict[str, SignalPoint] = {}

    for entry in catalog:
        report_count = await _count_distinct_reports(
            db,
            drug_id=drug_id,
            role="suspect",
            event_terms=entry.event_terms,
            start_date=quarter_start_date,
            end_date=quarter_end_date,
        )
        cumulative_count = await _count_distinct_reports(
            db,
            drug_id=drug_id,
            role="suspect",
            event_terms=entry.event_terms,
            start_date=cumulative_start_date,
            end_date=quarter_end_date,
        )

        background_counts = await _resolve_background_counts(
            db,
            drug_id=drug_id,
            settings=active_settings,
            quarter=quarter,
            entry=entry,
            cumulative_start_date=cumulative_start_date,
            quarter_end_date=quarter_end_date,
            local_total_cumulative=local_total_cumulative,
        )
        if background_counts is None:
            all_total_cumulative = 0
            all_event_cumulative = 0
            metrics = INSUFFICIENT_METRICS
        else:
            all_total_cumulative, all_event_cumulative = background_counts
            b = max(0, drug_total_cumulative - cumulative_count)
            c = max(0, all_event_cumulative - cumulative_count)
            d = max(0, all_total_cumulative - (cumulative_count + b + c))
            metrics = compute_disproportionality_metrics(
                a=cumulative_count,
                b=b,
                c=c,
                d=d,
            )
        signal_detected = _signal_detected_for_drug(
            drug_id=drug_id,
            cumulative_count=cumulative_count,
            method_votes=metrics.method_votes,
            priority_flag=entry.priority_flag,
        )

        row_payload = {
            "drug_id": drug_id,
            "quarter": quarter,
            "adverse_event": entry.adverse_event,
            "report_count": report_count,
            "cumulative_count": cumulative_count,
            "drug_total_cumulative": drug_total_cumulative,
            "all_total_cumulative": all_total_cumulative,
            "all_event_cumulative": all_event_cumulative,
            "ror": metrics.ror,
            "ror_ci_lower": metrics.ror_ci_lower,
            "ror_ci_upper": metrics.ror_ci_upper,
            "prr": metrics.prr,
            "chi_squared": metrics.chi_squared,
            "bcpnn_ic": metrics.bcpnn_ic,
            "bcpnn_ic025": metrics.bcpnn_ic025,
            "ebgm": metrics.ebgm,
            "eb05": metrics.eb05,
            "signal_detected": signal_detected,
            "term_level": entry.term_level,
            "family_key": entry.family_key,
            "family_label": entry.family_label,
            "method_votes": metrics.method_votes,
            "consensus_tier": "none",
            "label_status": entry.label_status,
            "priority_flag": entry.priority_flag,
            "supporting_terms": list(entry.supporting_terms),
            "trajectory": "insufficient_data",
        }

        await db.execute(
            pg_insert(QuarterlyStat)
            .values(**row_payload)
            .on_conflict_do_update(
                index_elements=[QuarterlyStat.drug_id, QuarterlyStat.quarter, QuarterlyStat.adverse_event],
                set_=row_payload,
            )
        )

    quarters_loaded = await _fetch_quarters_loaded(db, drug_id)
    selected_quarters = quarters_loaded or [quarter]

    for entry in catalog:
        rows = (
            (
                await db.execute(
                    select(QuarterlyStat)
                    .where(
                        QuarterlyStat.drug_id == drug_id,
                        QuarterlyStat.adverse_event == entry.adverse_event,
                        QuarterlyStat.quarter.in_(selected_quarters),
                    )
                    .order_by(QuarterlyStat.quarter.asc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            continue

        quarterly_rors = [row.ror for row in rows]
        signal_flags = [bool(row.signal_detected) for row in rows]
        trajectory = classify_trajectory(quarterly_rors, signal_flags)

        for index, row in enumerate(rows):
            prior_positive_count = sum(
                1
                for previous in rows[:index]
                if sum(1 for vote in (previous.method_votes or {}).values() if vote) >= 2
            )
            row_trajectory = trajectory if row.quarter == quarter else row.trajectory
            consensus_tier = _consensus_tier_for_row(
                cumulative_count=row.cumulative_count,
                trajectory=row_trajectory,
                method_votes=dict(row.method_votes or {}),
                label_status=row.label_status,
                priority_flag=bool(row.priority_flag),
                prior_positive_count=prior_positive_count,
                strict_demo=strict_demo,
            )
            values = {"consensus_tier": consensus_tier}
            if row.quarter == quarter:
                values["trajectory"] = trajectory
            await db.execute(
                update(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.adverse_event == entry.adverse_event,
                    QuarterlyStat.quarter == row.quarter,
                )
                .values(**values)
            )
            if row.quarter == quarter:
                current_points_by_event[entry.adverse_event] = _row_to_signal_point(
                    row
                ).model_copy(update={"trajectory": trajectory, "consensus_tier": consensus_tier})

    prev_quarter = quarter_minus_one(quarter)
    updates: list[SignalUpdate] = []

    prev_rows: dict[str, QuarterlyStat] = {}
    if prev_quarter in selected_quarters:
        previous = (
            (
                await db.execute(
                    select(QuarterlyStat).where(
                        QuarterlyStat.drug_id == drug_id,
                        QuarterlyStat.quarter == prev_quarter,
                        QuarterlyStat.adverse_event.in_(list(current_points_by_event.keys())),
                    )
                )
            )
            .scalars()
            .all()
        )
        prev_rows = {row.adverse_event: row for row in previous}

    for adverse_event, point in current_points_by_event.items():
        previous_rank = consensus_tier_rank(prev_rows.get(adverse_event).consensus_tier if adverse_event in prev_rows else None)
        current_rank = consensus_tier_rank(point.consensus_tier)
        updates.append(
            SignalUpdate(
                adverse_event=adverse_event,
                quarter=quarter,
                signal_point=point,
                is_new_signal=(previous_rank == 0 and current_rank > 0),
            )
        )

    return updates


async def _default_timeline_events(db: AsyncSession, *, drug_id: str, latest_quarter: str) -> list[str]:
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
    rows.sort(
        key=lambda row: (
            0 if row.term_level == "family" else 1,
            -consensus_tier_rank(row.consensus_tier),
            -int(bool(row.priority_flag)),
            -(row.ror_ci_lower or -1),
            -row.report_count,
            row.adverse_event,
        )
    )
    return [row.adverse_event for row in rows[:8]]


async def fetch_timeline_points(
    db: AsyncSession,
    *,
    drug_id: str,
    events: list[str] | None,
    quarters: list[str] | None,
) -> list[SignalPoint]:
    drug_exists = await db.scalar(select(func.count()).select_from(Drug).where(Drug.id == drug_id))
    if not drug_exists:
        raise ValueError(f"drug_id '{drug_id}' not found")

    quarters_loaded = await _fetch_quarters_loaded(db, drug_id)
    if not quarters_loaded:
        return []

    selected_events = events if events else await _default_timeline_events(db, drug_id=drug_id, latest_quarter=quarters_loaded[-1])
    selected_quarters = quarters if quarters else quarters_loaded
    loaded_set = set(quarters_loaded)
    selected_quarters = [q for q in selected_quarters if q in loaded_set]
    selected_quarters = sort_quarters(selected_quarters)

    if not selected_quarters or not selected_events:
        return []

    rows = (
        (
            await db.execute(
                select(QuarterlyStat)
                .where(
                    QuarterlyStat.drug_id == drug_id,
                    QuarterlyStat.quarter.in_(selected_quarters),
                    QuarterlyStat.adverse_event.in_(selected_events),
                )
                .order_by(QuarterlyStat.quarter.asc(), QuarterlyStat.adverse_event.asc())
            )
        )
        .scalars()
        .all()
    )

    return [_row_to_signal_point(row) for row in rows]
