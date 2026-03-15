from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.tracking import OnboardDrugRequest, OnboardDrugResponse
from app.services.evermemos_client import EvermemosClient
from app.services.onboarding_service import onboard_drug

router = APIRouter()


def _get_evermemos_client(request: Request) -> EvermemosClient:
    return request.app.state.evermemos_client


@router.post("/tracking/onboard", response_model=OnboardDrugResponse)
async def onboard_tracking_drug(
    payload: OnboardDrugRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OnboardDrugResponse:
    settings = request.app.state.settings
    return await onboard_drug(
        db,
        settings=settings,
        evermemos_client=_get_evermemos_client(request),
        medication_name=payload.medication_name,
        baseline_quarters=payload.baseline_quarters,
        max_reports=payload.max_reports,
        prefer_cached=payload.prefer_cached,
    )
