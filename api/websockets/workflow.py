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


@router.websocket("/workflow/{workflow_id}/stream")
async def workflow_stream(
    websocket: WebSocket,
    workflow_id: str,
    token: str = Query(default=""),
) -> None:
    """
    Stream live workflow updates for a single workflow_id.

    Requires a valid JWT via ?token=<jwt>.
    Pushes an initial snapshot and then streams real-time workflow events.
    """
    user = await verify_ws_token(token, websocket)
    if user is None:
        return

    await websocket.accept()
    await register_workflow_client(workflow_id, websocket)
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
            logger.info(
                "workflow_event_sent",
                workflow_id=workflow_id,
                stage="snapshot",
            )
        except Exception:  # noqa: BLE001
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
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "ws_send_failed",
                        workflow_id=workflow_id,
                        stage=ev.get("stage", "unknown"),
                    )
                    break
                await asyncio.sleep(0.15)  # small gap so UI can animate each item

        # ── Stay alive and forward live broadcasts ───────────────────────────
        # Live events are pushed via broadcast_workflow_event() → _workflow_clients
        # We only need to keep the connection open.
        while True:
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        logger.info("ws.workflow.disconnected", workflow_id=workflow_id)
    finally:
        await unregister_workflow_client(workflow_id, websocket)
