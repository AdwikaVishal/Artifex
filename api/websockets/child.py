"""WebSocket endpoint for real-time child event streaming."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from api.auth import verify_ws_token
from api.websockets.events import (
    register_child_client,
    unregister_child_client,
    get_child_event_buffer,
    broadcast_child_event,
)

logger = structlog.get_logger()
router = APIRouter(tags=["ws_child"])


@router.websocket("/ws/child/{child_id}")
async def child_event_ws(
    websocket: WebSocket,
    child_id: str,
    token: str = Query(default=""),
):
    """WebSocket endpoint for real-time child events."""
    if not verify_ws_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    await register_child_client(child_id, websocket)

    # Replay buffered events so the new client doesn't miss anything
    for event in get_child_event_buffer(child_id):
        try:
            await websocket.send_json(event)
        except Exception:  # noqa: BLE001
            break

    logger.info("child_ws.connected", child_id=child_id)

    try:
        while True:
            # Keep connection alive — client may send pings
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("child_ws.disconnected", child_id=child_id)
    except Exception:  # noqa: BLE001
        logger.exception("child_ws.error", child_id=child_id)
    finally:
        await unregister_child_client(child_id, websocket)
