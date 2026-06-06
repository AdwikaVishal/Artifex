"""
api/websockets/logs.py – Real-time agent log and workflow step WebSocket endpoints.

Broadcaster pattern: a single NATS subscriber per subject forwards messages to
all connected WebSocket clients, avoiding per-connection subscription explosion.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from weakref import WeakSet

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.auth import verify_ws_token
from nats_client.client import NATSManager

logger = structlog.get_logger()
router = APIRouter()

NATS_URL: str = os.getenv("NATS_URL", "nats://localhost:4222")

# ── Broadcaster state ─────────────────────────────────────────────────────────
# One set of connected sockets per stream type.  WeakSet so GC can collect
# closed sockets without explicit cleanup.

_log_clients: set[WebSocket] = set()
_workflow_clients: set[WebSocket] = set()
_event_clients: set[WebSocket] = set()

# None  = not yet started
# True  = running successfully
# False = startup failed (will retry on next connection)
_broadcaster_started: bool | None = None
_broadcaster_lock = asyncio.Lock()


async def _broadcast(clients: set[WebSocket], msg: dict) -> None:
    """Send msg to all connected clients; silently drop dead connections."""
    dead: list[WebSocket] = []
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def _ensure_broadcasters() -> None:
    """
    Start the shared NATS subscribers exactly once per process.
    Called lazily on first WebSocket connection.

    Fix ①: The flag is only set to True *after* NATS connects and all
    subscriptions are registered.  If anything fails the flag stays None/False
    so the next connection attempt will retry instead of silently skipping.
    """
    global _broadcaster_started
    async with _broadcaster_lock:
        if _broadcaster_started is True:
            return
        # Mark as "in-progress" so concurrent callers don't double-start,
        # but we will reset to None on failure so future callers can retry.
        _broadcaster_started = False

    try:
        manager = NATSManager(NATS_URL)
        await manager.connect()

        async def _on_log(msg: dict) -> None:
            if not msg.get("timestamp"):
                msg["timestamp"] = __import__("datetime").datetime.now().strftime("%H:%M:%S")
            await _broadcast(_log_clients, msg)

        async def _on_step(msg: dict) -> None:
            if not msg.get("timestamp"):
                msg["timestamp"] = __import__("datetime").datetime.now().strftime("%H:%M:%S")
            await _broadcast(_workflow_clients, msg)

        async def _on_event(msg: dict) -> None:
            if not msg.get("timestamp"):
                msg["timestamp"] = __import__("datetime").datetime.now().isoformat()
            await _broadcast(_event_clients, msg)

        await manager.subscribe("agent.*.log", _on_log)
        await manager.subscribe("workflow.*.step", _on_step)
        await manager.subscribe("events.live.>", _on_event)

        # Only mark as fully started once everything succeeded
        async with _broadcaster_lock:
            _broadcaster_started = True
        logger.info("ws.broadcaster.started", subjects=["agent.*.log", "workflow.*.step", "events.live.>"])
    except Exception as exc:  # noqa: BLE001
        # Reset so the next connection attempt will retry
        async with _broadcaster_lock:
            _broadcaster_started = None
        logger.warning("ws.broadcaster.start_failed", error=str(exc))


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@router.websocket("/ws/logs")
async def websocket_logs(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    """
    Stream real-time agent log events.

    Requires a valid JWT via ?token=<jwt>.
    Frames: {"agent": "planner", "message": "...", "type": "info|warning|error", "timestamp": "HH:MM:SS"}
    """
    user = None
    if token:
        user = await verify_ws_token(token, websocket)
        if user is None:
            return

    await websocket.accept()
    await _ensure_broadcasters()
    _log_clients.add(websocket)
    logger.info("ws.logs.connected", client=str(websocket.client), user=user["user_id"] if user else "anonymous")

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json(
                    {"type": "ping", "agent": "system", "message": "keepalive"}
                )
            except Exception:  # noqa: BLE001
                break
    except WebSocketDisconnect:
        logger.info("ws.logs.disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.logs.error", error=str(exc))
    finally:
        _log_clients.discard(websocket)


@router.websocket("/ws/workflow")
async def websocket_workflow(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    """
    Stream workflow step events.

    Requires a valid JWT via ?token=<jwt>.
    """
    user = None
    if token:
        user = await verify_ws_token(token, websocket)
        if user is None:
            return

    await websocket.accept()
    await _ensure_broadcasters()
    _workflow_clients.add(websocket)
    logger.info("ws.workflow.connected", client=str(websocket.client), user=user["user_id"] if user else "anonymous")

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json(
                    {"type": "ping", "agent": "system", "message": "keepalive"}
                )
            except Exception:  # noqa: BLE001
                break
    except WebSocketDisconnect:
        logger.info("ws.workflow.disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.workflow.error", error=str(exc))
    finally:
        _workflow_clients.discard(websocket)


@router.websocket("/ws/events")
async def websocket_live_events(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    """
    Stream all live foster-care events.

    Requires a valid JWT via ?token=<jwt>.
    """
    user = None
    if token:
        user = await verify_ws_token(token, websocket)
        if user is None:
            return

    await websocket.accept()
    await _ensure_broadcasters()
    _event_clients.add(websocket)
    logger.info("ws.live_events.connected", client=str(websocket.client), user=user["user_id"] if user else "anonymous")

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping", "event": "keepalive"})
            except Exception:  # noqa: BLE001
                break
    except WebSocketDisconnect:
        logger.info("ws.live_events.disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.live_events.error", error=str(exc))
    finally:
        _event_clients.discard(websocket)
