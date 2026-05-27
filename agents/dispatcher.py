"""
agents/dispatcher.py – Capability-aware task dispatcher.

Listens on:  agent.executor.request
Publishes:   agent.<selected_executor>.inbox  (or agent.executor.inbox as fallback)

The dispatcher consults the AgentRegistry to find the best available executor
for each task, based on:
  1. Declared capabilities (e.g., "web_search", "http", "shell")
  2. Moving-average performance score (validators publish scores after each task)
  3. Liveness (heartbeat age < 90 s)

This decouples the planner from knowing which executor instances exist, making
the swarm truly self-organising.

Run with:
  python -m scripts.run_agent dispatcher
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from nats_client.subjects import Subjects
from tools.agent_registry import get_registry
from .base import BaseAgent

logger = structlog.get_logger()


class DispatcherAgent(BaseAgent):
    """Routes executor tasks to the best available executor instance."""

    def __init__(self) -> None:
        super().__init__(name="dispatcher", metrics_port=9098)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        # Start the registry (subscribes to agent.register, agent.performance,
        # and agent.*.heartbeat) using this agent's NATS connection.
        registry = get_registry()
        await registry.start(self._nats)

        # Listen for dispatch requests from the planner / workflow
        await self.subscribe("agent.executor.request", self._dispatch, queue="dispatcher")
        self._log.info("dispatcher.ready")

        while self._running:
            await asyncio.sleep(3600)

    # ── Handler ───────────────────────────────────────────────────────────────

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        task      = msg.get("task", {})
        task_type = task.get("type", "execute")
        tool      = task.get("tool", "")
        reply_to  = msg.get("_reply") or msg.get("reply_to")

        registry = get_registry()
        target_inbox = registry.select(task_type, tool)

        self._log.info(
            "dispatcher.routing",
            task_type=task_type,
            tool=tool,
            target=target_inbox,
        )

        if reply_to:
            # Forward with the original reply address so the executor can
            # respond directly to the Temporal activity.
            await self.publish(target_inbox, msg)
        else:
            await self.publish(target_inbox, msg)

    # ── Registry snapshot endpoint (for observability) ────────────────────────

    async def _handle_registry_query(self, msg: dict[str, Any]) -> None:
        reply_to = msg.get("_reply") or msg.get("reply_to")
        if reply_to:
            snapshot = get_registry().all_agents()
            await self.reply(reply_to, {"agents": snapshot})
