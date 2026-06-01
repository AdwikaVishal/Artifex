"""
api/websockets/workflow.py – Per-workflow streaming WebSocket endpoint.
"""
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.auth import verify_ws_token
from api.db import get_workflow_status_db, get_workflow_timeline

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
    Pushes status + timeline every second.
    """
    user = await verify_ws_token(token, websocket)
    if user is None:
        return

    await websocket.accept()
    logger.info("ws.workflow.connected", workflow_id=workflow_id,
                client=str(websocket.client), user=user["user_id"])
    try:
        while True:
            wf = await get_workflow_status_db(workflow_id)
            timeline = await get_workflow_timeline(workflow_id, limit=200)
            payload = {
                "workflow_id":    workflow_id,
                "status":         wf.get("status") if wf else "unknown",
                "current_stage":  wf.get("current_stage") if wf else None,
                "progress":       wf.get("progress") if wf else 0,
                "updated_at":     wf.get("updated_at") if wf else None,
                "timeline":       timeline,
            }
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info("ws.workflow.disconnected", workflow_id=workflow_id)
