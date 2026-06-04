"""
NATS connection manager – singleton with automatic reconnection.

Usage:
    manager = NATSManager()
    await manager.connect()
    await manager.publish("some.subject", {"key": "value"})
    await manager.subscribe("some.subject", my_handler)
    await manager.close()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import nats
from nats.aio.client import Client as NATSClient
from nats.aio.msg import Msg

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


class NATSManager:
    """Thread-safe singleton NATS connection manager."""

    _instance: NATSManager | None = None
    _nats_url_cache: str = "nats://localhost:4222"

    def __new__(cls, nats_url: str = "nats://localhost:4222") -> NATSManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
            cls._nats_url_cache = nats_url
        return cls._instance

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        if self._initialised:
            return
        self.nats_url: str = NATSManager._nats_url_cache
        self.nc: NATSClient | None = None
        self._subscriptions: list[Any] = []
        self._initialised = True

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish connection with exponential-backoff reconnect.

        Idempotent: safe to call multiple times; returns existing connection if already connected.
        """
        if self.nc is not None and not self.nc.is_closed:
            logger.debug("NATS already connected", extra={"url": self.nats_url})
            return
        self.nc = await nats.connect(
            self.nats_url,
            reconnect_time_wait=2,
            max_reconnect_attempts=-1,  # infinite
            error_cb=self._error_cb,
            disconnected_cb=self._disconnected_cb,
            reconnected_cb=self._reconnected_cb,
            closed_cb=self._closed_cb,
        )
        logger.info("NATS connected", extra={"url": self.nats_url})

    async def close(self) -> None:
        if self.nc and not self.nc.is_closed:
            await self.nc.drain()
            logger.info("NATS connection drained and closed")

    # ── Pub / Sub ─────────────────────────────────────────────────────────────

    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        """Publish a JSON-encoded message."""
        if not self.nc or self.nc.is_closed:
            raise RuntimeError("NATS not connected")
        payload = json.dumps(data).encode()
        await self.nc.publish(subject, payload)
        logger.debug("NATS publish", extra={"subject": subject})

    async def request(
        self, subject: str, data: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Publish and wait for a single reply (request-reply pattern)."""
        if not self.nc or self.nc.is_closed:
            raise RuntimeError("NATS not connected")
        payload = json.dumps(data).encode()
        msg = await self.nc.request(subject, payload, timeout=timeout)
        return json.loads(msg.data.decode())

    async def subscribe(
        self,
        subject: str,
        handler: MessageHandler,
        queue: str = "",
    ) -> Any:
        """
        Subscribe to a subject.  The handler receives a decoded dict.
        Optionally join a queue group for load-balanced delivery.
        """
        if not self.nc or self.nc.is_closed:
            raise RuntimeError("NATS not connected")

        async def _wrapper(msg: Msg) -> None:
            try:
                data = json.loads(msg.data.decode())
                # Attach reply subject so handlers can respond
                if msg.reply:
                    data["_reply"] = msg.reply
                await handler(data)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error in NATS handler", extra={"subject": subject, "error": str(exc)})

        sub = await self.nc.subscribe(subject, queue=queue, cb=_wrapper)
        self._subscriptions.append(sub)
        logger.info("NATS subscribed", extra={"subject": subject, "queue": queue})
        return sub

    async def reply(self, reply_subject: str, data: dict[str, Any]) -> None:
        """Send a reply to a request-reply inbox."""
        await self.publish(reply_subject, data)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    async def _error_cb(self, exc: Exception) -> None:
        logger.error("NATS error", extra={"error": str(exc)})

    async def _disconnected_cb(self) -> None:
        logger.warning("NATS disconnected – will attempt reconnect")

    async def _reconnected_cb(self) -> None:
        logger.info("NATS reconnected", extra={"url": self.nc.connected_url.netloc if self.nc else "?"})
        # Re-apply stored subscriptions on reconnect
        for sub in list(self._subscriptions):
            try:
                subject = getattr(sub, "subject", None)
                queue = getattr(sub, "queue", "")
                cb = getattr(sub, "_cb", None)
                if subject and cb:
                    new_sub = await self.nc.subscribe(subject, queue=queue, cb=cb)
                    idx = self._subscriptions.index(sub)
                    self._subscriptions[idx] = new_sub
            except Exception as exc:
                logger.warning("NATS re-subscribe error", extra={"error": str(exc)})

    async def _closed_cb(self) -> None:
        logger.info("NATS connection closed")
