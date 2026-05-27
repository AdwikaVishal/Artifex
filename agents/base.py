"""
BaseAgent – shared foundation for every Artifex agent.

Responsibilities:
  • Connect to NATS (with reconnect).
  • Provide publish / subscribe / request-reply helpers.
  • Emit a heartbeat every 30 s so the Supervisor can detect failures.
  • Expose a Prometheus metrics endpoint on /metrics.
  • Emit structured JSON logs via structlog.
"""

from __future__ import annotations

import asyncio
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

import structlog
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from nats_client.client import NATSManager
from nats_client.subjects import Subjects

logger = structlog.get_logger()

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]

# ── Prometheus metrics (shared labels) ───────────────────────────────────────
MESSAGES_PROCESSED = Counter(
    "artifex_messages_processed_total",
    "Total messages processed by this agent",
    ["agent", "subject"],
)
MESSAGES_FAILED = Counter(
    "artifex_messages_failed_total",
    "Total messages that raised an exception",
    ["agent", "subject"],
)
PROCESSING_LATENCY = Histogram(
    "artifex_processing_seconds",
    "Message processing latency in seconds",
    ["agent", "subject"],
)
HEARTBEAT_GAUGE = Gauge(
    "artifex_last_heartbeat_timestamp",
    "Unix timestamp of the last heartbeat emitted",
    ["agent"],
)

# ── Search / answer task counters (used by executor + validator) ──────────────
# Defined here so they are registered once regardless of import order.
TASK_TYPE_COUNTER = Counter(
    "artifex_task_type_total",
    "Tasks dispatched by type (search, direct_answer, execute, retrieve)",
    ["agent", "task_type"],
)


class BaseAgent(ABC):
    """Abstract base class for all Artifex agents."""

    def __init__(
        self,
        name: str,
        nats_url: str | None = None,
        metrics_port: int = 9090,
    ) -> None:
        self.name = name
        self.nats_url = nats_url or os.getenv("NATS_URL", "nats://localhost:4222")
        self.metrics_port = metrics_port
        self._nats: NATSManager = NATSManager(self.nats_url)
        self._log = logger.bind(agent=name)
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to NATS, start metrics server, then run the agent loop."""
        self._log.info("agent.starting")
        await self._nats.connect()
        self._running = True

        # Start Prometheus metrics HTTP server in background
        try:
            start_http_server(self.metrics_port)
            self._log.info("metrics.server.started", port=self.metrics_port)
        except OSError:
            self._log.warning("metrics.server.port_in_use", port=self.metrics_port)

        # Heartbeat loop
        asyncio.create_task(self._heartbeat_loop(), name=f"{self.name}-heartbeat")

        # Self-register with the AgentRegistry so the dispatcher can discover
        # this agent's capabilities and inbox subject.
        asyncio.create_task(self._register(), name=f"{self.name}-register")

        await self.run()

    async def stop(self) -> None:
        self._running = False
        await self._nats.close()
        self._log.info("agent.stopped")

    # ── NATS helpers ──────────────────────────────────────────────────────────

    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        await self._nats.publish(subject, data)
        self._log.debug("nats.publish", subject=subject)

    async def log_event(
        self,
        message: str,
        log_type: str = "info",
    ) -> None:
        """
        Publish a structured log event to agent.<name>.log so the dashboard
        WebSocket can stream it in real time.
        """
        import datetime as _dt  # noqa: PLC0415
        try:
            await self._nats.publish(
                f"agent.{self.name}.log",
                {
                    "agent":     self.name,
                    "message":   message,
                    "type":      log_type,
                    "timestamp": _dt.datetime.now().strftime("%H:%M:%S"),
                },
            )
        except Exception:  # noqa: BLE001
            pass  # never let logging break the agent

    async def subscribe(
        self,
        subject: str,
        handler: MessageHandler,
        queue: str = "",
    ) -> None:
        """Subscribe with automatic metrics instrumentation."""

        async def _instrumented(msg: dict[str, Any]) -> None:
            start = time.perf_counter()
            try:
                await handler(msg)
                MESSAGES_PROCESSED.labels(agent=self.name, subject=subject).inc()
            except Exception as exc:  # noqa: BLE001
                MESSAGES_FAILED.labels(agent=self.name, subject=subject).inc()
                self._log.exception("handler.error", subject=subject, error=str(exc))
            finally:
                elapsed = time.perf_counter() - start
                PROCESSING_LATENCY.labels(agent=self.name, subject=subject).observe(elapsed)

        await self._nats.subscribe(subject, _instrumented, queue=queue)

    async def request(
        self, subject: str, data: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        return await self._nats.request(subject, data, timeout=timeout)

    async def reply(self, reply_subject: str, data: dict[str, Any]) -> None:
        await self._nats.reply(reply_subject, data)

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            ts = time.time()
            await self.publish(
                Subjects.heartbeat(self.name),
                {"agent": self.name, "timestamp": ts, "status": "alive"},
            )
            HEARTBEAT_GAUGE.labels(agent=self.name).set(ts)
            self._log.debug("heartbeat.sent", timestamp=ts)

    async def _register(self) -> None:
        """
        Publish a registration message to agent.register so the AgentRegistry
        (running inside the DispatcherAgent) can discover this agent.

        Subclasses can override `capabilities` to advertise specific tools.
        """
        await asyncio.sleep(1)   # brief delay so subscriptions are ready first
        try:
            await self.publish(Subjects.AGENT_REGISTER, {
                "agent":        self.name,
                "capabilities": self.capabilities,
                "inbox":        Subjects.inbox(self.name),
            })
            self._log.info("agent.registered", capabilities=self.capabilities)
        except Exception as exc:  # noqa: BLE001
            self._log.warning("agent.register_error", error=str(exc))

    @property
    def capabilities(self) -> list[str]:
        """
        Override in subclasses to declare supported task types / tools.
        Default: the agent's own name (e.g. "planner", "retriever").
        """
        return [self.name]

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def run(self) -> None:
        """Subscribe to relevant subjects and process messages indefinitely."""
