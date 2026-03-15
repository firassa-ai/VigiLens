from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import router as admin_router
from app.api.catalog import router as catalog_router
from app.api.drugs import router as drugs_router
from app.api.ingest import router as ingest_router
from app.api.query import router as query_router
from app.api.tracking import router as tracking_router
from app.api.tracking_jobs import router as tracking_jobs_router
from app.core.config import DEFAULT_SETTINGS, Settings
from app.core.errors import AppError
from app.db.session import configure_database, dispose_database, get_db_session, get_session_factory
from app.schemas.common import ErrorResponse
from app.schemas.health import HealthResponse
from app.services.evermemos_client import EvermemosClient
from app.services.casefile_schema import ensure_casefile_schema
from app.services.evermemos_schema import ensure_evermemos_tables
from app.services.ingest_progress_hub import IngestProgressHub
from app.services.tracking_job_service import TrackingJobRuntime


def _error_response(error: str, detail: str, status_code: int) -> JSONResponse:
    payload = ErrorResponse(error=error, detail=detail, status_code=status_code)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or DEFAULT_SETTINGS
    configure_database(active_settings.database_url)
    evermemos_client = EvermemosClient(active_settings)
    tracking_job_runtime = TrackingJobRuntime(
        session_factory=get_session_factory(),
        settings=active_settings,
        evermemos_client=evermemos_client,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with get_session_factory()() as db:
            await ensure_casefile_schema(db)
            await ensure_evermemos_tables(db)
            await db.commit()
        await tracking_job_runtime.startup()
        yield
        await tracking_job_runtime.shutdown()
        await dispose_database()

    app = FastAPI(title=active_settings.app_name, lifespan=lifespan)
    origins = [
        origin.strip()
        for origin in active_settings.cors_allow_origins.split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = active_settings
    app.state.ingest_progress_hub = IngestProgressHub()
    app.state.evermemos_client = evermemos_client
    app.state.tracking_job_runtime = tracking_job_runtime

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.error, exc.detail, exc.status_code)

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return _error_response("HTTPException", detail, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response("ValidationError", str(exc), 422)

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health(db: AsyncSession = Depends(get_db_session)) -> HealthResponse:
        await db.execute(text("SELECT 1"))

        evermemos_ok = False
        evermemos_version: str | None = None
        base = active_settings.evermemos_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=active_settings.evermemos_timeout_seconds) as client:
                health_resp = await client.get(f"{base}/health")
            if health_resp.status_code == 200:
                evermemos_ok = True
                try:
                    payload = health_resp.json()
                    if isinstance(payload, dict):
                        evermemos_version = str(payload.get("version") or payload.get("app_version") or "unknown")
                except Exception:
                    evermemos_version = "unknown"
            else:
                async with httpx.AsyncClient(timeout=active_settings.evermemos_timeout_seconds) as client:
                    probe_resp = await client.get(f"{base}/api/v1/memories/conversation-meta")
                if probe_resp.status_code == 200:
                    evermemos_ok = True
                    evermemos_version = "unknown"
        except Exception:
            evermemos_ok = False
            evermemos_version = None

        return HealthResponse(
            ok=True,
            postgres_ok=True,
            evermemos_ok=evermemos_ok,
            evermemos_version=evermemos_version,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(catalog_router, prefix="/api/v1")
    app.include_router(drugs_router, prefix="/api/v1")
    app.include_router(ingest_router, prefix="/api/v1")
    app.include_router(query_router, prefix="/api/v1")
    app.include_router(tracking_router, prefix="/api/v1")
    app.include_router(tracking_jobs_router, prefix="/api/v1")

    @app.websocket("/ws/ingest-progress")
    async def ws_ingest_progress(websocket: WebSocket) -> None:
        drug_id = websocket.query_params.get("drug_id", "semaglutide")
        hub: IngestProgressHub = app.state.ingest_progress_hub
        await hub.connect(websocket, drug_id)
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await hub.disconnect(websocket, drug_id)
    return app


app = create_app()
