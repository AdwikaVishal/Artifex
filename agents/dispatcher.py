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


# ── Capability aliases ────────────────────────────────────────────────────────
# Maps canonical tool names to all accepted variants so that tasks using
# "web_search" can match executors that advertise "search", and vice-versa.

CAPABILITY_ALIASES: dict[str, list[str]] = {
    "web_search":    ["search", "web_search", "web-search"],
    "search":        ["search", "web_search", "web-search"],
    "direct_answer": ["direct_answer", "llm_answer", "direct"],
    "http":          ["http", "http_request", "api"],
    "shell":         ["shell", "bash", "exec"],
    "file":          ["file", "file_io", "fs"],
    "execute":       ["execute", "exec", "shell", "bash"],
}


def _resolve_aliases(tool: str) -> list[str]:
    """Return all known aliases for a tool name (including itself)."""
    return CAPABILITY_ALIASES.get(tool, [tool])


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

        # Try the exact tool first, then fall back through aliases
        target_inbox = registry.select(task_type, tool)
        if target_inbox == Subjects.EXECUTOR_INBOX and tool:
            # Fallback: try each alias until we find a better match
            for alias in _resolve_aliases(tool):
                if alias == tool:
                    continue
                candidate = registry.select(task_type, alias)
                if candidate != Subjects.EXECUTOR_INBOX:
                    target_inbox = candidate
                    self._log.info(
                        "dispatcher.alias_resolved",
                        original_tool=tool,
                        alias=alias,
                        target=target_inbox,
                    )
                    break

        self._log.info(
            "dispatcher.routing",
            task_type=task_type,
            tool=tool,
            target=target_inbox,
        )

        await self.publish(target_inbox, msg)

    # ── Registry snapshot endpoint (for observability) ────────────────────────

    async def _handle_registry_query(self, msg: dict[str, Any]) -> None:
        reply_to = msg.get("_reply") or msg.get("reply_to")
        if reply_to:
            snapshot = get_registry().all_agents()
            await self.reply(reply_to, {"agents": snapshot})
