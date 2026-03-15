from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.catalog import CatalogPreviewResponse, CatalogSearchResult
from app.services.drug_catalog_service import preview_catalog_candidate, search_catalog

router = APIRouter()


@router.get("/catalog/search", response_model=list[CatalogSearchResult])
async def catalog_search(
    request: Request,
    q: str = Query(min_length=2),
    db: AsyncSession = Depends(get_db_session),
) -> list[CatalogSearchResult]:
    settings = request.app.state.settings
    return await search_catalog(db, settings=settings, query=q)


@router.get("/catalog/preview", response_model=CatalogPreviewResponse)
async def catalog_preview(
    request: Request,
    name: str = Query(min_length=2),
    db: AsyncSession = Depends(get_db_session),
) -> CatalogPreviewResponse:
    settings = request.app.state.settings
    return await preview_catalog_candidate(db, settings=settings, name=name)
