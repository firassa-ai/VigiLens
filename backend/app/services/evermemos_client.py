from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import re
from typing import Any

import httpx
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import EvermemosMemoryCache, EvermemosRequest
from app.db.session import get_session_factory
from app.utils.quarter_extraction import extract_quarters_from_text

FORESIGHT_QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")


async def _run_best_effort_write(
    db: AsyncSession | None,
    writer: Callable[[AsyncSession], Awaitable[None]],
) -> None:
    try:
        try:
            session_factory = get_session_factory()
        except RuntimeError:
            session_factory = None

        if session_factory is not None:
            async with session_factory() as write_db:
                async with write_db.begin():
                    await writer(write_db)
            return

        if db is None:
            return

        async with db.begin_nested():
            await writer(db)
    except Exception:
        return


class EvermemosClient:
    """EverMemOS client adapter.

    `group_id` is a per-drug memory namespace boundary (for isolation/scoping).
    EverMemOS generates MemCells/MemScenes internally from posted message content.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def _base_url(self) -> str:
        base = self._settings.evermemos_url.rstrip("/")
        if base.endswith("/api/v1/memories"):
            return base
        return f"{base}/api/v1/memories"

    @staticmethod
    def _should_retry_request_error(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 429 or exc.response.status_code >= 500
        return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))

    @staticmethod
    def _message_token(value: str, *, fallback: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        return cleaned or fallback

    @staticmethod
    def _memory_identifier(memory: dict[str, Any]) -> str | None:
        for key in ["id", "_id", "memory_id", "message_id"]:
            value = memory.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _memory_quarters(cls, memory: dict[str, Any]) -> list[str]:
        search_text = cls.extract_memory_search_text(memory)
        if not search_text:
            return []
        return sorted(extract_quarters_from_text(search_text))

    @classmethod
    async def _cache_memory_objects(
        cls,
        db: AsyncSession,
        *,
        drug_id: str,
        quarter: str | None,
        source_endpoint: str,
        payload: dict[str, Any] | None,
    ) -> None:
        if not isinstance(payload, dict):
            return
        group_id = f"vigl:{drug_id}"
        memories = cls.flatten_grouped_memories(payload, group_id=group_id)
        if not memories:
            return

        now = datetime.now(timezone.utc)

        async def writer(write_db: AsyncSession) -> None:
            for memory in memories:
                memory_id = cls._memory_identifier(memory)
                if not memory_id:
                    continue
                memory_group = memory.get("group_id") if isinstance(memory.get("group_id"), str) else group_id
                memory_type = memory.get("memory_type") if isinstance(memory.get("memory_type"), str) else None
                inferred_quarters = cls._memory_quarters(memory)
                memory_quarter = quarter or (inferred_quarters[-1] if inferred_quarters else None)

                row = {
                    "memory_id": memory_id,
                    "drug_id": drug_id,
                    "group_id": memory_group,
                    "memory_type": memory_type,
                    "quarter": memory_quarter,
                    "source_endpoint": source_endpoint,
                    "raw_payload": memory,
                    "created_at": now,
                    "last_seen_at": now,
                }
                await write_db.execute(
                    pg_insert(EvermemosMemoryCache)
                    .values(**row)
                    .on_conflict_do_update(
                        index_elements=[EvermemosMemoryCache.memory_id],
                        set_={
                            "drug_id": row["drug_id"],
                            "group_id": row["group_id"],
                            "memory_type": row["memory_type"],
                            "quarter": row["quarter"],
                            "source_endpoint": row["source_endpoint"],
                            "raw_payload": row["raw_payload"],
                            "last_seen_at": row["last_seen_at"],
                        },
                    )
                )

        await _run_best_effort_write(db, writer)

    async def _log_request(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        quarter: str | None,
        endpoint: str,
        request_body: dict[str, Any],
        response_body: dict[str, Any] | None,
        status: str,
        ) -> None:
        if db is None:
            return
        now = datetime.now(timezone.utc)

        async def writer(write_db: AsyncSession) -> None:
            await write_db.execute(
                insert(EvermemosRequest).values(
                    drug_id=drug_id,
                    quarter=quarter,
                    endpoint=endpoint,
                    request_body=request_body,
                    response_body=response_body,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
            )

        await _run_best_effort_write(db, writer)

    async def _request(
        self,
        db: AsyncSession,
        *,
        method: str,
        endpoint: str,
        drug_id: str,
        quarter: str | None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        retry_attempts: int | None = None,
        retry_backoff_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        url = f"{self._base_url}{endpoint}"
        req_body = json_body or {}
        timeout = timeout_seconds if timeout_seconds is not None else self._settings.evermemos_timeout_seconds
        max_retries = max(0, int(retry_attempts or 0))
        backoff = max(
            0.0,
            float(
                retry_backoff_seconds
                if retry_backoff_seconds is not None
                else self._settings.evermemos_retry_backoff_seconds
            ),
        )
        attempt = 0

        while True:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(method, url, params=params, json=json_body)
                response.raise_for_status()
                if response.content:
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = {"raw_text": response.text}
                else:
                    payload = {}
                await self._cache_memory_objects(
                    db,
                    drug_id=drug_id,
                    quarter=quarter,
                    source_endpoint=f"{method.upper()} {endpoint or '/'}",
                    payload=payload if isinstance(payload, dict) else None,
                )
                await self._log_request(
                    db,
                    drug_id=drug_id,
                    quarter=quarter,
                    endpoint=f"{method.upper()} {endpoint or '/'}",
                    request_body={"params": params or {}, "json": req_body},
                    response_body=payload if isinstance(payload, dict) else {"raw": payload},
                    status="ok",
                )
                return payload if isinstance(payload, dict) else {"raw": payload}
            except Exception as exc:
                if attempt < max_retries and self._should_retry_request_error(exc):
                    delay = backoff * (2**attempt)
                    attempt += 1
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue

                await self._log_request(
                    db,
                    drug_id=drug_id,
                    quarter=quarter,
                    endpoint=f"{method.upper()} {endpoint or '/'}",
                    request_body={"params": params or {}, "json": req_body},
                    response_body={"error": str(exc), "error_type": exc.__class__.__name__},
                    status="failed",
                )
                return None

    @staticmethod
    def extract_memories(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not payload:
            return []

        candidates = [
            payload.get("result", {}).get("memories") if isinstance(payload.get("result"), dict) else None,
            payload.get("memories"),
            payload.get("data", {}).get("memories") if isinstance(payload.get("data"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return []

    @staticmethod
    def extract_has_more(payload: dict[str, Any] | None) -> bool:
        if not payload:
            return False
        result = payload.get("result")
        if isinstance(result, dict):
            return bool(result.get("has_more"))
        data = payload.get("data")
        if isinstance(data, dict):
            return bool(data.get("has_more"))
        return False

    @staticmethod
    def extract_total_count(payload: dict[str, Any] | None) -> int:
        if not payload:
            return 0
        result = payload.get("result")
        if isinstance(result, dict):
            try:
                return int(result.get("total_count") or 0)
            except (TypeError, ValueError):
                return 0
        data = payload.get("data")
        if isinstance(data, dict):
            try:
                return int(data.get("total_count") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    @staticmethod
    def extract_memory_text(memory: dict[str, Any]) -> str:
        for key in ["episode", "summary", "content", "memory", "text", "atomic_fact", "subject", "title"]:
            value = memory.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def extract_memory_search_text(memory: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ["title", "summary", "episode", "content", "memory", "text", "atomic_fact", "subject", "message_id", "id", "_id"]:
            value = memory.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        extend = memory.get("extend")
        if isinstance(extend, dict):
            message_id = extend.get("message_id")
            if isinstance(message_id, str) and message_id.strip():
                parts.append(message_id.strip())
        return "\n".join(parts)

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.endswith("Z"):
            cleaned = f"{cleaned[:-1]}+00:00"
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None

    @classmethod
    def _validate_foresight_data(cls, foresight_data: dict[str, Any]) -> str | None:
        prediction = foresight_data.get("prediction")
        if not isinstance(prediction, str) or not prediction.strip():
            return "foresight_data.prediction must be a non-empty string"

        confidence = foresight_data.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return "foresight_data.confidence must be a number between 0 and 100"
        if confidence < 0 or confidence > 100:
            return "foresight_data.confidence must be between 0 and 100"

        created_at_quarter = foresight_data.get("created_at_quarter")
        if not isinstance(created_at_quarter, str) or not FORESIGHT_QUARTER_RE.match(created_at_quarter.strip()):
            return "foresight_data.created_at_quarter must match YYYY-Q#"

        time_range = foresight_data.get("time_range")
        if not isinstance(time_range, (list, tuple)) or len(time_range) != 2:
            return "foresight_data.time_range must be a 2-item array of ISO datetimes"
        start_raw, end_raw = time_range
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            return "foresight_data.time_range values must be strings"
        start_dt = cls._parse_iso_datetime(start_raw)
        end_dt = cls._parse_iso_datetime(end_raw)
        if start_dt is None or end_dt is None:
            return "foresight_data.time_range values must be valid ISO datetimes"
        if end_dt < start_dt:
            return "foresight_data.time_range end must be on/after start"

        return None

    @classmethod
    def _validate_event_log_data(cls, event_log_data: dict[str, Any]) -> str | None:
        report_id = event_log_data.get("report_id")
        if not isinstance(report_id, str) or not report_id.strip():
            return "event_log_data.report_id must be a non-empty string"

        receivedate = event_log_data.get("receivedate")
        if not isinstance(receivedate, str) or cls._parse_iso_datetime(f"{receivedate.strip()}T00:00:00Z") is None:
            return "event_log_data.receivedate must be a valid ISO date"

        evidence_api_path = event_log_data.get("evidence_api_path")
        if not isinstance(evidence_api_path, str) or not evidence_api_path.startswith("/api/v1/evidence/"):
            return "event_log_data.evidence_api_path must point to /api/v1/evidence/{report_id}"

        quarter = event_log_data.get("quarter")
        if not isinstance(quarter, str) or not FORESIGHT_QUARTER_RE.match(quarter.strip()):
            return "event_log_data.quarter must match YYYY-Q#"

        return None

    @classmethod
    def flatten_grouped_memories(
        cls,
        payload: dict[str, Any] | None,
        *,
        group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        grouped = cls.extract_memories(payload)
        if not grouped:
            return []

        flattened: list[dict[str, Any]] = []

        def visit(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if not isinstance(node, dict):
                return

            has_memory_shape = any(
                key in node
                for key in ["id", "_id", "memory_type", "timestamp", "group_id", "summary", "episode", "atomic_fact"]
            )
            if has_memory_shape:
                if group_id and node.get("group_id") not in {None, group_id}:
                    return
                flattened.append(node)
                return

            for value in node.values():
                visit(value)

        visit(grouped)

        dedup: list[dict[str, Any]] = []
        seen: set[str] = set()
        for memory in flattened:
            identifier = memory.get("id") or memory.get("_id") or cls.extract_memory_text(memory)
            if not isinstance(identifier, str):
                continue
            key = identifier.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            dedup.append(memory)

        return dedup

    async def get_cached_memory(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        memory_id: str,
    ) -> EvermemosMemoryCache | None:
        return await db.scalar(
            select(EvermemosMemoryCache).where(
                EvermemosMemoryCache.drug_id == drug_id,
                EvermemosMemoryCache.memory_id == memory_id,
            )
        )

    async def post_conversation_meta(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        body: dict[str, Any],
    ) -> bool:
        payload = await self._request(
            db,
            method="POST",
            endpoint="/conversation-meta",
            drug_id=drug_id,
            quarter=None,
            json_body=body,
            retry_attempts=self._settings.evermemos_write_retry_attempts,
        )
        return payload is not None

    async def post_quarter_digest(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        quarter: str,
        body: dict[str, Any],
    ) -> bool:
        """Post a quarter digest message into one drug-isolated EverMemOS memory space.

        EverMemOS encodes MemCells from this message content and consolidates them into
        higher-order MemScenes over time. `group_id` keeps each drug namespace isolated.
        """
        payload = await self._request(
            db,
            method="POST",
            endpoint="",
            drug_id=drug_id,
            quarter=quarter,
            json_body=body,
            retry_attempts=self._settings.evermemos_write_retry_attempts,
        )
        return payload is not None

    async def fetch_profile(self, db: AsyncSession, *, drug_id: str) -> dict[str, Any] | None:
        return await self._request(
            db,
            method="GET",
            endpoint="",
            drug_id=drug_id,
            quarter=None,
            params={"user_id": f"drug:{drug_id}", "memory_type": "profile", "limit": 1},
        )

    async def store_profile_memory(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        profile_data: dict[str, Any],
    ) -> bool:
        """Store profile update message for one drug namespace in EverMemOS.

        The message is written into the drug `group_id` scope. EverMemOS builds/stitches
        MemCells and MemScenes internally from this content to evolve profile memory.
        """
        quarter_token = str(profile_data.get("last_updated") or "latest").replace("-", "")
        payload = await self._request(
            db,
            method="POST",
            endpoint="",
            drug_id=drug_id,
            quarter=str(profile_data.get("last_updated") or ""),
            json_body={
                "message_id": f"vigl_{drug_id}_{quarter_token}_profile",
                "create_time": datetime.now(timezone.utc).isoformat(),
                "sender": f"drug:{drug_id}",
                "sender_name": drug_id.capitalize(),
                "role": "user",
                "group_id": f"vigl:{drug_id}",
                "group_name": f"VigiLens: {drug_id}",
                "memory_type": "profile",
                "content": (
                    f"Profile update for {drug_id}: risk={profile_data.get('risk_level')}; "
                    f"known={', '.join(profile_data.get('known_signals', [])) or 'none'}; "
                    f"investigating={', '.join(profile_data.get('investigating_signals', [])) or 'none'}; "
                    f"assessment={profile_data.get('assessment', '')}; "
                    f"last_updated={profile_data.get('last_updated', '')}"
                ),
                "profile_data": profile_data,
                "refer_list": [],
            },
            retry_attempts=self._settings.evermemos_write_retry_attempts,
        )
        return payload is not None

    async def store_foresight_memory(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        foresight_data: dict[str, Any],
    ) -> bool:
        """Store a foresight message in EverMemOS within the drug memory namespace."""
        created_at_quarter = str(foresight_data.get("created_at_quarter") or "").strip()
        validation_error = self._validate_foresight_data(foresight_data)
        if validation_error:
            await self._log_request(
                db,
                drug_id=drug_id,
                quarter=created_at_quarter or None,
                endpoint="POST / (foresight-schema-validation)",
                request_body={
                    "params": {},
                    "json": {
                        "memory_type": "foresight",
                        "foresight_data": foresight_data,
                    },
                },
                response_body={
                    "error": validation_error,
                    "error_type": "ForesightSchemaError",
                },
                status="failed",
            )
            return False

        quarter_token = created_at_quarter.replace("-", "") or "latest"
        prediction_token = self._message_token(
            str(foresight_data.get("prediction") or ""),
            fallback="prediction",
        )
        payload = await self._request(
            db,
            method="POST",
            endpoint="",
            drug_id=drug_id,
            quarter=created_at_quarter,
            json_body={
                "message_id": f"vigl_{drug_id}_{quarter_token}_{prediction_token}_foresight",
                "create_time": datetime.now(timezone.utc).isoformat(),
                "sender": "vigl:assistant",
                "sender_name": "VigiLens",
                "role": "assistant",
                "group_id": f"vigl:{drug_id}",
                "group_name": f"VigiLens: {drug_id}",
                "memory_type": "foresight",
                "content": (
                    f"Prediction for {drug_id}: {foresight_data.get('prediction')}; "
                    f"confidence={foresight_data.get('confidence')}; "
                    f"time_range={foresight_data.get('time_range')}; "
                    f"created_at_quarter={foresight_data.get('created_at_quarter')}"
                ),
                "foresight_data": foresight_data,
                "refer_list": [],
            },
            timeout_seconds=max(
                float(self._settings.evermemos_timeout_seconds),
                float(self._settings.evermemos_foresight_timeout_seconds),
            ),
            retry_attempts=self._settings.evermemos_write_retry_attempts,
        )
        return payload is not None

    async def store_event_log_memory(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        quarter: str,
        event_log_data: dict[str, Any],
    ) -> bool:
        """Store a report-level EventLog memory within the drug namespace."""
        validation_error = self._validate_event_log_data(event_log_data)
        if validation_error:
            await self._log_request(
                db,
                drug_id=drug_id,
                quarter=quarter,
                endpoint="POST / (event-log-schema-validation)",
                request_body={
                    "params": {},
                    "json": {
                        "memory_type": "event_log",
                        "event_log_data": event_log_data,
                    },
                },
                response_body={
                    "error": validation_error,
                    "error_type": "EventLogSchemaError",
                },
                status="failed",
            )
            return False

        report_id = str(event_log_data.get("report_id")).strip()
        receivedate = str(event_log_data.get("receivedate")).strip()
        reactions = ", ".join(event_log_data.get("reactions") or []) or "none"
        suspect_drugs = ", ".join(event_log_data.get("suspect_drugs") or []) or "none"
        outcomes = ", ".join(event_log_data.get("outcomes") or []) or "none"
        summary = (
            f"FAERS report {report_id} for {drug_id} on {receivedate}: "
            f"reactions={reactions}; suspect_drugs={suspect_drugs}; "
            f"serious={bool(event_log_data.get('serious'))}; outcomes={outcomes}; "
            f"evidence_api_path={event_log_data.get('evidence_api_path')}"
        )

        payload = await self._request(
            db,
            method="POST",
            endpoint="",
            drug_id=drug_id,
            quarter=quarter,
            json_body={
                "message_id": f"vigl_{drug_id}_{report_id}_eventlog",
                "create_time": f"{receivedate}T00:00:00+00:00",
                "sender": f"drug:{drug_id}",
                "sender_name": drug_id.capitalize(),
                "role": "user",
                "group_id": f"vigl:{drug_id}",
                "group_name": f"VigiLens: {drug_id}",
                "memory_type": "event_log",
                "content": summary,
                "atomic_fact": summary,
                "event_log_data": event_log_data,
                "refer_list": [],
            },
            retry_attempts=self._settings.evermemos_write_retry_attempts,
        )
        return payload is not None

    async def fetch_episodic_memories(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        target_quarters: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        group_id = f"vigl:{drug_id}"
        timeout = max(0.05, float(self._settings.evermemos_timeout_seconds))
        page_limit = max(25, int(self._settings.evermemos_event_log_page_limit))
        max_pages = max(3, int(self._settings.evermemos_event_log_max_pages))

        async def fetch_pages(memory_type: str) -> list[dict[str, Any]]:
            combined: list[dict[str, Any]] = []
            offset = 0
            page_count = 0
            empty_page_streak = 0
            discovered_quarters: set[str] = set()

            while page_count < max_pages:
                page_count += 1
                payload = await self._request(
                    db,
                    method="GET",
                    endpoint="",
                    drug_id=drug_id,
                    quarter=None,
                    params={
                        "group_id": group_id,
                        "memory_type": memory_type,
                        "limit": page_limit,
                        "offset": offset,
                    },
                    timeout_seconds=timeout,
                )
                if not payload:
                    break
                page_memories = self.flatten_grouped_memories(payload, group_id=group_id)
                if not page_memories:
                    empty_page_streak += 1
                else:
                    empty_page_streak = 0
                combined.extend(page_memories)

                if memory_type == "event_log" and target_quarters:
                    for memory in page_memories:
                        searchable = self.extract_memory_search_text(memory)
                        if searchable:
                            discovered_quarters.update(extract_quarters_from_text(searchable))
                    if target_quarters.issubset(discovered_quarters):
                        break

                if empty_page_streak >= 2:
                    break
                if not self.extract_has_more(payload):
                    break

                offset += page_limit
            return combined

        episodic = await fetch_pages("episodic_memory")
        event_logs = []
        for memory in await fetch_pages("event_log"):
            searchable = self.extract_memory_search_text(memory)
            if not searchable:
                continue
            if "quarter digest" in searchable.lower() or re.search(r"(\d{4}\s*[-/]?\s*Q[1-4]|Q[1-4]\s*\d{4})", searchable, re.IGNORECASE):
                event_logs.append(memory)

        merged: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for memory in [*episodic, *event_logs]:
            identifier = memory.get("id") or memory.get("_id")
            if isinstance(identifier, str) and identifier in seen_ids:
                continue
            if isinstance(identifier, str):
                seen_ids.add(identifier)
            merged.append(memory)
        return merged

    async def search_memories(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        query: str,
        top_k: int = 5,
        retrieve_method: str = "rrf",
        memory_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        group_id = f"vigl:{drug_id}"
        timeout = max(0.05, float(self._settings.evermemos_timeout_seconds))
        if memory_types is None:
            search_types = [["episodic_memory"], ["event_log"]]
        else:
            if not memory_types:
                return []
            search_types = [memory_types]

        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for type_group in search_types:
            payload = await self._request(
                db,
                method="GET",
                endpoint="/search",
                drug_id=drug_id,
                quarter=None,
                params={
                    "query": query,
                    "group_id": group_id,
                    "memory_types": ",".join(type_group),
                    "retrieve_method": retrieve_method,
                    "top_k": top_k,
                },
                timeout_seconds=timeout,
            )
            hits = self.flatten_grouped_memories(payload, group_id=group_id)
            for memory in hits:
                identifier = memory.get("id") or memory.get("_id") or self.extract_memory_text(memory)
                if not isinstance(identifier, str):
                    continue
                key = identifier.strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(memory)
            if merged and memory_types is None:
                break

        return merged

    async def refresh_memory_by_id(
        self,
        db: AsyncSession,
        *,
        drug_id: str,
        memory_id: str,
    ) -> tuple[EvermemosMemoryCache | None, bool]:
        """Best-effort refresh for a specific memory id.

        Uses search retrieval because EverMemOS public API is group/type/search-oriented.
        """
        target = memory_id.strip()
        if not target:
            return None, False

        query_variants = [target, target.replace("_", " "), target.replace(":", " ")]
        memory_types = ["episodic_memory", "event_log", "profile", "foresight"]
        for query in query_variants:
            hits = await self.search_memories(
                db,
                drug_id=drug_id,
                query=query,
                top_k=20,
                retrieve_method="keyword",
                memory_types=memory_types,
            )
            if not hits:
                continue
            for memory in hits:
                identifier = self._memory_identifier(memory)
                if identifier != target:
                    continue
                await self._cache_memory_objects(
                    db,
                    drug_id=drug_id,
                    quarter=None,
                    source_endpoint="GET /search (memory_id_refresh)",
                    payload={"result": {"memories": [memory]}},
                )
                return await self.get_cached_memory(db, drug_id=drug_id, memory_id=target), True

        return await self.get_cached_memory(db, drug_id=drug_id, memory_id=target), False

    async def delete_group_memories(self, db: AsyncSession, *, drug_id: str) -> bool:
        payload = await self._request(
            db,
            method="DELETE",
            endpoint="",
            drug_id=drug_id,
            quarter=None,
            json_body={"group_id": f"vigl:{drug_id}"},
        )
        return payload is not None
