from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.admin import SeedDemoRequest, SeedDemoResponse
from app.services.evermemos_client import EvermemosClient
from app.services.demo_seed import seed_demo_data

router = APIRouter()


@router.post("/admin/seed-demo", response_model=SeedDemoResponse)
async def seed_demo(
    payload: SeedDemoRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> SeedDemoResponse:
    settings = request.app.state.settings
    evermemos_client: EvermemosClient = request.app.state.evermemos_client
    if not settings.demo_mode:
        raise AppError(
            error="Forbidden",
            detail="/api/v1/admin/seed-demo is only available when DEMO_MODE=true",
            status_code=403,
        )

    return await seed_demo_data(
        db=db,
        drug_ids=payload.drug_ids,
        preload_quarters=payload.preload_quarters,
        data_dir=Path(payload.data_dir) if payload.data_dir else None,
        settings=settings,
        evermemos_client=evermemos_client,
    )
