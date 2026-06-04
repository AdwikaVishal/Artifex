"""
api/websockets/dashboard.py – Live dashboard WebSocket endpoint.

Broadcaster pattern: a single NATS subscriber pushes placement updates to all
connected clients instead of each connection creating its own subscription.
Falls back to polling PostgreSQL every 2 s if NATS is unavailable.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.auth import verify_ws_token
from api.db import get_all_placements
from api.websockets.events import serialize_event

logger = structlog.get_logger()
router = APIRouter()

NATS_URL: str = os.getenv("NATS_URL", "nats://localhost:4222")

# ── Broadcaster state ─────────────────────────────────────────────────────────
_dashboard_clients: set[WebSocket] = set()

# None  = not yet attempted
# True  = running successfully
# False = startup in-progress or failed (will retry on next connection)
_broadcaster_started: bool | None = None
_broadcaster_lock = asyncio.Lock()


async def _broadcast(msg: dict) -> None:
    """Send msg to all connected dashboard clients; drop dead connections."""
    dead: list[WebSocket] = []
    payload = serialize_event(msg)
    for ws in list(_dashboard_clients):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
            logger.warning("ws.dashboard.broadcast_failed")
    for ws in dead:
        _dashboard_clients.discard(ws)


async def _ensure_broadcaster() -> None:
    """
    Start the shared NATS subscriber exactly once per process.
    On new placements, push the full updated list to all connected clients.

    Fix ②: The flag is only set to True *after* NATS connects and the
    subscription is registered.  On failure the flag resets to None so the
    next connection attempt will retry instead of silently skipping.
    Clients always have the 2-second DB polling fallback while NATS is down.
    """
    global _broadcaster_started
    async with _broadcaster_lock:
        if _broadcaster_started is True:
            return
        _broadcaster_started = False  # mark in-progress; reset to None on failure

    try:
        from nats_client.client import NATSManager  # noqa: PLC0415
        manager = NATSManager(NATS_URL)
        await manager.connect()

        async def _on_placement(msg: dict) -> None:
            """Fetch fresh list from DB and broadcast to all clients."""
            try:
                placements = await get_all_placements()
            except Exception:  # noqa: BLE001
                return
            await _broadcast({"placements": placements, "count": len(placements)})

        await manager.subscribe("foster.placements", _on_placement)

        # Only mark as fully started once everything succeeded
        async with _broadcaster_lock:
            _broadcaster_started = True
        logger.info("ws.dashboard.broadcaster.started", subject="foster.placements")
    except Exception as exc:  # noqa: BLE001
        async with _broadcaster_lock:
            _broadcaster_started = None  # allow retry on next connection
        logger.warning("ws.dashboard.broadcaster.nats_unavailable", error=str(exc))
        # NATS unavailable – clients will rely on the polling fallback loop below


async def _poll_loop(websocket: WebSocket) -> None:
    """
    Fallback: push DB snapshot every 2 s when NATS broadcaster is not delivering.
    Runs concurrently with the keepalive loop; exits when the socket closes.
    """
    while True:
        try:
            placements = await get_all_placements()
            payload = serialize_event({"placements": placements, "count": len(placements)})
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001
            break
        await asyncio.sleep(2)


@router.websocket("/ws/dashboard")
async def websocket_dashboard(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    """
    WebSocket endpoint for the live foster care dashboard.

    Requires a valid JWT via ?token=<jwt> query parameter.
    Receives placement updates pushed by the NATS broadcaster.
    Falls back to 2-second DB polling if NATS is unavailable.
    """
    user = await verify_ws_token(token, websocket)
    if user is None:
        return  # already closed with 1008

    try:
        await websocket.accept()
    except Exception:
        return

    await _ensure_broadcaster()
    _dashboard_clients.add(websocket)
    logger.info("ws.dashboard.connected", client=str(websocket.client), user=user["user_id"])

    # Send an immediate snapshot so the client doesn't wait for the next NATS event
    try:
        placements = await get_all_placements()
        payload = serialize_event({"placements": placements, "count": len(placements)})
        await websocket.send_json(payload)
    except Exception:  # noqa: BLE001
        logger.warning("ws.dashboard.snapshot_failed")

    try:
        # Keepalive loop – NATS broadcaster handles actual data pushes.
        # Also runs a 2-second poll as a fallback in case NATS is quiet.
        poll_task = asyncio.create_task(_poll_loop(websocket))
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:  # noqa: BLE001
                    logger.warning("ws.dashboard.ping_failed")
                    break
        finally:
            poll_task.cancel()
    except WebSocketDisconnect:
        logger.info("ws.dashboard.disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.dashboard.error", error=str(exc))
    finally:
        _dashboard_clients.discard(websocket)
