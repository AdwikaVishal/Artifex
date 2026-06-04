"""
api/websockets/workflow.py – Per-workflow streaming WebSocket endpoint.
"""
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.auth import verify_ws_token
from api.db import get_workflow_status_db, get_workflow_timeline
from api.websockets.events import (
    get_workflow_event_buffer,
    register_workflow_client,
    serialize_event,
    unregister_workflow_client,
)

logger = structlog.get_logger()
router = APIRouter()

PING_INTERVAL_S = 25
SHUTDOWN_GRACE_S = 5


@router.websocket("/workflow/{workflow_id}/stream")
async def workflow_stream(
    websocket: WebSocket,
    workflow_id: str,
    token: str = Query(default=""),
) -> None:
    """
    Stream live workflow updates for a single workflow_id.

    Requires a valid JWT via ?token=<jwt>.
    Pushes an initial snapshot, replays buffered events, then sends
    application-level pings every 25 s so the ASGI server can detect
    dropped connections even during idle periods.
    """
    user = await verify_ws_token(token, websocket)
    if user is None:
        return

    try:
        await websocket.accept()
        await register_workflow_client(workflow_id, websocket)
    except Exception:
        logger.exception("ws.workflow.accept_failed", workflow_id=workflow_id)
        return

    logger.info("ws.workflow.connected", workflow_id=workflow_id,
                client=str(websocket.client), user=user["user_id"])
    try:
        wf = await get_workflow_status_db(workflow_id)
        timeline = await get_workflow_timeline(workflow_id, limit=200)

        snapshot = serialize_event({
            "type": "workflow_snapshot",
            "workflow_id": workflow_id,
            "status": (wf.get("status") if wf else "unknown") or "unknown",
            "current_stage": (wf.get("current_stage") if wf else None) or (timeline[-1].get("stage") if timeline else None),
            "progress": wf.get("progress") if wf else 0,
            "updated_at": wf.get("updated_at") if wf else None,
            "timeline": timeline,
        })

        try:
            await websocket.send_json(snapshot)
        except Exception:
            logger.exception("ws_send_failed", workflow_id=workflow_id, stage="snapshot")
            return

        # ── Replay buffered events that were emitted before WS connected ─────
        buffered = get_workflow_event_buffer(workflow_id)
        if buffered:
            logger.info(
                "workflow_replay_buffered",
                workflow_id=workflow_id,
                count=len(buffered),
            )
            for i, ev in enumerate(buffered):
                payload = serialize_event({
                    **ev,
                    "type": "workflow_event",
                    "replayed": True,
                    "replay_index": i,
                    "replay_total": len(buffered),
                })
                try:
                    await websocket.send_json(payload)
                except Exception:
                    logger.exception(
                        "ws_send_failed",
                        workflow_id=workflow_id,
                        stage=ev.get("stage", "unknown"),
                    )
                    break
                await asyncio.sleep(0.15)

        # ── Stay alive with application-level pings ─────────────────────────
        # Live events are pushed via broadcast_workflow_event() → _workflow_clients
        # We still send periodic pings so proxy / LB / ASGI server can detect
        # dropped connections during quiet periods.
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                break

    except (WebSocketDisconnect, Exception) as exc:
        logger.info("ws.workflow.disconnected", workflow_id=workflow_id,
                    error=type(exc).__name__)
    finally:
        await unregister_workflow_client(workflow_id, websocket)
