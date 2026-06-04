"""In-memory WebSocket event broadcasting for workflow and child event streams."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

logger = structlog.get_logger()

_workflow_clients: dict[str, set[WebSocket]] = defaultdict(set)
_child_event_clients: dict[str, set[WebSocket]] = defaultdict(set)

# ── Per-workflow event buffer ──────────────────────────────────────────────
# Stores the last N events per workflow so newly connected WebSocket clients
# can replay "missed" events instead of only seeing the DB snapshot.
_WORKFLOW_EVENT_BUFFER_SIZE = 100
_workflow_event_buffer: dict[str, list[dict[str, Any]]] = defaultdict(list)


def serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Convert all non-serializable values (datetime, Decimal, UUID, etc.)
    to JSON-compatible types using FastAPI's jsonable_encoder."""
    return jsonable_encoder(event)


def get_workflow_event_buffer(workflow_id: str) -> list[dict[str, Any]]:
    """Return all buffered events for *workflow_id* (copy so caller can mutate freely)."""
    return list(_workflow_event_buffer.get(workflow_id, []))


def clear_workflow_event_buffer(workflow_id: str) -> None:
    """Drop the in-memory event buffer for *workflow_id*."""
    _workflow_event_buffer.pop(workflow_id, None)


async def register_workflow_client(workflow_id: str, websocket: WebSocket) -> None:
    _workflow_clients[workflow_id].add(websocket)


async def unregister_workflow_client(workflow_id: str, websocket: WebSocket) -> None:
    clients = _workflow_clients.get(workflow_id, set())
    clients.discard(websocket)
    if not clients:
        _workflow_clients.pop(workflow_id, None)


# ── Child event broadcasting ────────────────────────────────────────────

_CHILD_EVENT_BUFFER_SIZE = 200
_child_event_buffer: dict[str, list[dict[str, Any]]] = defaultdict(list)


def get_child_event_buffer(child_id: str) -> list[dict[str, Any]]:
    return list(_child_event_buffer.get(child_id, []))


async def register_child_client(child_id: str, websocket: WebSocket) -> None:
    _child_event_clients[child_id].add(websocket)


async def unregister_child_client(child_id: str, websocket: WebSocket) -> None:
    clients = _child_event_clients.get(child_id, set())
    clients.discard(websocket)
    if not clients:
        _child_event_clients.pop(child_id, None)


async def broadcast_child_event(child_id: str, event: dict[str, Any]) -> None:
    """Persist event to the per-child buffer and fan-out to connected clients."""
    buf = _child_event_buffer[child_id]
    buf.append(event)
    if len(buf) > _CHILD_EVENT_BUFFER_SIZE:
        buf.pop(0)

    clients = list(_child_event_clients.get(child_id, set()))
    if not clients:
        logger.info("child_event_buffered", child_id=child_id, buffer_size=len(buf))
        return

    payload = serialize_event(event)
    for websocket in clients:
        try:
            await websocket.send_json(payload)
        except Exception:
            logger.exception("child_ws_send_failed", child_id=child_id)
            await unregister_child_client(child_id, websocket)


async def broadcast_workflow_event(workflow_id: str, event: dict[str, Any]) -> None:
    """Persist event to the per-workflow buffer and fan-out to connected clients."""
    stage = event.get("stage", "unknown")
    status = event.get("status", "unknown")

    # Always buffer, even when no clients are connected, so newly connecting
    # clients can replay missed events.
    buf = _workflow_event_buffer[workflow_id]
    buf.append(event)
    if len(buf) > _WORKFLOW_EVENT_BUFFER_SIZE:
        buf.pop(0)

    clients = list(_workflow_clients.get(workflow_id, set()))
    if not clients:
        logger.info(
            "workflow_event_buffered",
            workflow_id=workflow_id,
            stage=stage,
            status=status,
            buffer_size=len(buf),
        )
        return

    payload = serialize_event(event)

    logger.info(
        "workflow_event_sent",
        workflow_id=workflow_id,
        stage=stage,
        status=status,
        client_count=len(clients),
    )

    for websocket in clients:
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ws_send_failed",
                workflow_id=workflow_id,
                stage=stage,
            )
            await unregister_workflow_client(workflow_id, websocket)
