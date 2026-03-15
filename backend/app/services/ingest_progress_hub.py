from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket

from app.schemas.ingest import IngestProgress, IngestProgressMessage


class IngestProgressHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, drug_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[drug_id].add(websocket)

    async def disconnect(self, websocket: WebSocket, drug_id: str) -> None:
        async with self._lock:
            if drug_id in self._connections:
                self._connections[drug_id].discard(websocket)
                if not self._connections[drug_id]:
                    self._connections.pop(drug_id, None)

    async def broadcast(self, drug_id: str, message: IngestProgressMessage) -> None:
        payload = IngestProgress(message=message).model_dump()

        async with self._lock:
            targets = list(self._connections.get(drug_id, set()))

        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)

        if stale:
            async with self._lock:
                for websocket in stale:
                    self._connections.get(drug_id, set()).discard(websocket)
