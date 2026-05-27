"""
FosterMonitorAgent – bridges NATS events to Temporal workflow signals.

Listens on:
  events.check_in      – weekly foster-parent check-in → signals FosterPlacementWorkflow
  events.close_placement – placement ended → signals workflow to close

The agent reuses BaseAgent for NATS connection, heartbeat, and metrics.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from temporalio.client import Client

from .base import BaseAgent

logger = structlog.get_logger()


class FosterMonitorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="foster_monitor", metrics_port=9097)
        self._temporal_host = os.getenv("TEMPORAL_HOST", "temporal:7233")
        self._temporal_namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
        self._temporal_client: Client | None = None

    # ── Temporal client (lazy, with retry) ───────────────────────────────────

    async def _get_temporal(self) -> Client:
        if self._temporal_client is None:
            for attempt in range(1, 6):
                try:
                    self._temporal_client = await Client.connect(
                        self._temporal_host,
                        namespace=self._temporal_namespace,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    wait = attempt * 3
                    self._log.warning(
                        "foster_monitor.temporal_retry",
                        attempt=attempt,
                        wait=wait,
                        error=str(exc),
                    )
                    await asyncio.sleep(wait)
        return self._temporal_client  # type: ignore[return-value]

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.subscribe("events.check_in",       self.handle_check_in,       queue="foster_monitor")
        await self.subscribe("events.close_placement", self.handle_close_placement, queue="foster_monitor")
        self._log.info("foster_monitor.ready")
        while self._running:
            await asyncio.sleep(3600)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def handle_check_in(self, msg: dict[str, Any]) -> None:
        """
        Expected msg shape:
          {"workflow_id": "foster-<child_id>", "score": 1-5, "notes": "..."}
        """
        workflow_id: str | None = msg.get("workflow_id")
        score: int              = int(msg.get("score", 3))
        notes: str              = msg.get("notes", "")

        if not workflow_id:
            self._log.error("foster_monitor.missing_workflow_id", msg=msg)
            return

        self._log.info(
            "foster_monitor.check_in",
            workflow_id=workflow_id,
            score=score,
        )

        try:
            client = await self._get_temporal()
            handle = client.get_workflow_handle(workflow_id)
            await handle.signal("weekly_check_in", args=[score, notes])
            self._log.info("foster_monitor.signal_sent", workflow_id=workflow_id)
        except Exception as exc:  # noqa: BLE001
            self._log.exception(
                "foster_monitor.signal_error",
                workflow_id=workflow_id,
                error=str(exc),
            )

    async def handle_close_placement(self, msg: dict[str, Any]) -> None:
        """
        Expected msg shape:
          {"workflow_id": "foster-<child_id>"}
        """
        workflow_id: str | None = msg.get("workflow_id")
        if not workflow_id:
            self._log.error("foster_monitor.missing_workflow_id_close", msg=msg)
            return

        self._log.info("foster_monitor.close_placement", workflow_id=workflow_id)

        try:
            client = await self._get_temporal()
            handle = client.get_workflow_handle(workflow_id)
            await handle.signal("close_placement")
        except Exception as exc:  # noqa: BLE001
            self._log.exception(
                "foster_monitor.close_error",
                workflow_id=workflow_id,
                error=str(exc),
            )
