from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import FaersReport, FaersReportDrug, FaersReportReaction
from app.schemas.shared import FAERSReport
from app.utils.quarters import quarter_to_dates


def evidence_api_path_for_report(report_id: str) -> str:
    return f"/api/v1/evidence/{report_id}"


def eventlog_memory_id_for_report(drug_id: str, report_id: str) -> str:
    return f"vigl_{drug_id}_{report_id}_eventlog"


def _build_faers_report(
    *,
    report_row: FaersReport,
    reactions: list[str],
    suspect_drugs: list[str],
    concomitant_drugs: list[str],
    eventlog_memory_id: str | None,
) -> FAERSReport:
    return FAERSReport(
        safetyreportid=report_row.safetyreportid,
        version=report_row.version,
        receivedate=report_row.receivedate.isoformat(),
        patient_sex=report_row.patient_sex,
        patient_age=float(report_row.patient_age) if report_row.patient_age is not None else None,
        reactions=reactions,
        suspect_drugs=suspect_drugs,
        concomitant_drugs=concomitant_drugs,
        serious=bool(report_row.serious),
        outcomes=list(report_row.outcomes or []),
        evidence_api_path=evidence_api_path_for_report(report_row.safetyreportid),
        eventlog_memory_id=eventlog_memory_id,
    )


async def fetch_evidence_reports(db: AsyncSession, report_ids: list[str]) -> list[FAERSReport]:
    if not report_ids:
        return []

    report_rows = (
        (
            await db.execute(
                select(FaersReport).where(FaersReport.safetyreportid.in_(report_ids))
            )
        )
        .scalars()
        .all()
    )
    report_map = {row.safetyreportid: row for row in report_rows}

    reaction_rows = (
        (
            await db.execute(
                select(FaersReportReaction.safetyreportid, FaersReportReaction.meddra_pt).where(
                    FaersReportReaction.safetyreportid.in_(report_ids)
                )
            )
        )
        .all()
    )
    reactions_by_report: dict[str, list[str]] = {}
    for row in reaction_rows:
        reactions_by_report.setdefault(row.safetyreportid, []).append(row.meddra_pt)

    drug_rows = (
        (
            await db.execute(
                select(
                    FaersReportDrug.safetyreportid,
                    FaersReportDrug.drug_id,
                    FaersReportDrug.drug_name,
                    FaersReportDrug.role,
                ).where(
                    FaersReportDrug.safetyreportid.in_(report_ids)
                )
            )
        )
        .all()
    )
    suspect_by_report: dict[str, list[str]] = {}
    suspect_ids_by_report: dict[str, set[str]] = {}
    concomitant_by_report: dict[str, list[str]] = {}
    for row in drug_rows:
        if row.role == "suspect":
            suspect_by_report.setdefault(row.safetyreportid, []).append(row.drug_name)
            if row.drug_id:
                suspect_ids_by_report.setdefault(row.safetyreportid, set()).add(row.drug_id)
        else:
            concomitant_by_report.setdefault(row.safetyreportid, []).append(row.drug_name)

    ordered: list[FAERSReport] = []
    for report_id in report_ids:
        row = report_map.get(report_id)
        if row is None:
            continue
        suspect_ids = sorted(suspect_ids_by_report.get(row.safetyreportid, set()))
        eventlog_memory_id = (
            eventlog_memory_id_for_report(suspect_ids[0], row.safetyreportid)
            if len(suspect_ids) == 1
            else None
        )
        ordered.append(
            _build_faers_report(
                report_row=row,
                reactions=sorted(reactions_by_report.get(row.safetyreportid, [])),
                suspect_drugs=sorted(suspect_by_report.get(row.safetyreportid, [])),
                concomitant_drugs=sorted(concomitant_by_report.get(row.safetyreportid, [])),
                eventlog_memory_id=eventlog_memory_id,
            )
        )

    return ordered


async def fetch_quarter_evidence_reports(
    db: AsyncSession,
    *,
    drug_id: str,
    quarter: str,
) -> list[FAERSReport]:
    start_date, end_date = quarter_to_dates(quarter)
    report_ids = (
        (
            await db.execute(
                select(FaersReport.safetyreportid)
                .select_from(FaersReport)
                .join(FaersReportDrug, FaersReportDrug.safetyreportid == FaersReport.safetyreportid)
                .where(
                    FaersReportDrug.drug_id == drug_id,
                    FaersReportDrug.role == "suspect",
                    FaersReport.receivedate >= start_date,
                    FaersReport.receivedate <= end_date,
                )
                .group_by(FaersReport.safetyreportid, FaersReport.receivedate)
                .order_by(FaersReport.receivedate.asc(), FaersReport.safetyreportid.asc())
            )
        )
        .scalars()
        .all()
    )
    return await fetch_evidence_reports(db, list(report_ids))


async def get_evidence_report(db: AsyncSession, report_id: str) -> FAERSReport:
    reports = await fetch_evidence_reports(db, [report_id])
    if not reports:
        raise AppError(
            error="NotFound",
            detail=f"report_id '{report_id}' not found",
            status_code=404,
        )
    return reports[0]
