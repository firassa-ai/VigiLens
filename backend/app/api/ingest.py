from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.ingest import IngestNextQuarterRequest, IngestResetRequest, IngestStatus
from app.services.evermemos_client import EvermemosClient
from app.services.ingest_progress_hub import IngestProgressHub
from app.services.ingestion_service import get_ingest_status, ingest_next_quarter, reset_ingestion

router = APIRouter()


def _get_hub(request: Request) -> IngestProgressHub:
    return request.app.state.ingest_progress_hub


def _get_evermemos_client(request: Request) -> EvermemosClient:
    return request.app.state.evermemos_client


@router.get("/ingest/status", response_model=IngestStatus)
async def ingest_status(
    drug_id: str = Query(default="semaglutide"),
    db: AsyncSession = Depends(get_db_session),
) -> IngestStatus:
    return await get_ingest_status(db, drug_id=drug_id)


@router.post("/ingest/next-quarter", response_model=IngestStatus)
async def ingest_next(
    payload: IngestNextQuarterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> IngestStatus:
    hub = _get_hub(request)
    evermemos_client = _get_evermemos_client(request)
    settings = request.app.state.settings
    return await ingest_next_quarter(
        db,
        hub=hub,
        settings=settings,
        evermemos_client=evermemos_client,
        drug_id=payload.drug_id,
    )


@router.post("/ingest/reset", response_model=IngestStatus)
async def ingest_reset(
    payload: IngestResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> IngestStatus:
    evermemos_client = _get_evermemos_client(request)
    return await reset_ingestion(
        db,
        evermemos_client=evermemos_client,
        drug_id=payload.drug_id,
        hard=payload.hard,
    )
