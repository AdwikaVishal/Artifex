"""
tools/agent_registry.py – Live agent registry with capability tracking and
performance-based routing.

Agents self-register on startup by publishing to agent.register.
The registry subscribes to:
  agent.register      – agent announces its name, capabilities, and inbox subject
  agent.performance   – validator publishes success/failure scores after each task
  agent.*.heartbeat   – liveness tracking (reuses existing heartbeat infrastructure)

The dispatcher queries the registry to select the best available agent for a
given task type and tool, preferring agents with higher moving-average scores.

Design notes
────────────
• Pure in-process state – no external DB required.
• Thread-safe via asyncio (single-threaded event loop).
• Falls back to the default subject if no specialised agent is registered.
• Moving average window = 20 samples (configurable via REGISTRY_WINDOW env var).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from typing import Any

import structlog

logger = structlog.get_logger()

_WINDOW = int(os.getenv("REGISTRY_WINDOW", "20"))


class AgentInfo:
    """Metadata for one registered agent instance."""

    def __init__(self, name: str, capabilities: list[str], inbox: str) -> None:
        self.name         = name
        self.capabilities = set(capabilities)
        self.inbox        = inbox
        self.last_seen    = time.time()
        self._scores: deque[float] = deque(maxlen=_WINDOW)

    @property
    def avg_score(self) -> float:
        return sum(self._scores) / len(self._scores) if self._scores else 0.5

    def record_score(self, score: float) -> None:
        self._scores.append(score)

    def is_alive(self, stale_after: float = 90.0) -> bool:
        return (time.time() - self.last_seen) < stale_after


class AgentRegistry:
    """
    Central registry of all live agent instances.

    Usage (inside an async context):
        registry = AgentRegistry()
        await registry.start(nats_manager)   # subscribe to registration events
        inbox = registry.select("execute", tool="web_search")
    """

    def __init__(self) -> None:
        # agent_name → AgentInfo
        self._agents: dict[str, AgentInfo] = {}
        # capability → list[agent_name]  (for fast lookup)
        self._by_capability: dict[str, list[str]] = defaultdict(list)
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, nats_manager: Any) -> None:
        """Subscribe to registration and performance subjects."""
        from nats_client.subjects import Subjects  # noqa: PLC0415

        await nats_manager.subscribe(Subjects.AGENT_REGISTER,    self._on_register)
        await nats_manager.subscribe(Subjects.AGENT_PERFORMANCE,  self._on_performance)
        await nats_manager.subscribe(Subjects.HEARTBEAT_WILDCARD, self._on_heartbeat)
        logger.info("agent_registry.started")

    # ── Selection ─────────────────────────────────────────────────────────────

    def select(self, task_type: str, tool: str = "") -> str:
        """
        Return the NATS inbox subject of the best available agent for this task.

        Selection priority:
          1. Alive agents that list the exact tool in their capabilities
          2. Alive agents that list the task_type in their capabilities
          3. Default subject for the task_type (fallback)
        """
        from nats_client.subjects import Subjects  # noqa: PLC0415

        candidates = self._candidates_for(tool or task_type)
        if not candidates:
            candidates = self._candidates_for(task_type)

        if candidates:
            # Pick the agent with the highest moving-average score
            best = max(candidates, key=lambda a: a.avg_score)
            logger.debug("agent_registry.selected",
                         agent=best.name, score=best.avg_score,
                         task_type=task_type, tool=tool)
            return best.inbox

        # Fallback to default subjects
        _defaults = {
            "search":        Subjects.EXECUTOR_INBOX,
            "direct_answer": Subjects.EXECUTOR_INBOX,
            "execute":       Subjects.EXECUTOR_INBOX,
            "retrieve":      Subjects.RETRIEVER_INBOX,
            "validate":      Subjects.VALIDATOR_INBOX,
        }
        return _defaults.get(task_type, Subjects.EXECUTOR_INBOX)

    def all_agents(self) -> list[dict[str, Any]]:
        """Return a snapshot of all registered agents (for observability)."""
        return [
            {
                "name":         a.name,
                "capabilities": sorted(a.capabilities),
                "inbox":        a.inbox,
                "avg_score":    round(a.avg_score, 3),
                "alive":        a.is_alive(),
                "last_seen_s":  round(time.time() - a.last_seen, 1),
            }
            for a in self._agents.values()
        ]

    # ── NATS handlers ─────────────────────────────────────────────────────────

    async def _on_register(self, msg: dict[str, Any]) -> None:
        name         = msg.get("agent", "")
        capabilities = msg.get("capabilities", [])
        inbox        = msg.get("inbox", "")
        if not name or not inbox:
            return

        async with self._lock:
            if name in self._agents:
                # Update existing entry
                self._agents[name].capabilities = set(capabilities)
                self._agents[name].inbox        = inbox
                self._agents[name].last_seen    = time.time()
            else:
                info = AgentInfo(name, capabilities, inbox)
                self._agents[name] = info
                for cap in capabilities:
                    if name not in self._by_capability[cap]:
                        self._by_capability[cap].append(name)

        logger.info("agent_registry.registered",
                    agent=name, capabilities=capabilities, inbox=inbox)

    async def _on_performance(self, msg: dict[str, Any]) -> None:
        agent = msg.get("agent", "")
        score = float(msg.get("score", 0.5))
        if agent in self._agents:
            self._agents[agent].record_score(score)
            logger.debug("agent_registry.score_updated",
                         agent=agent, score=score,
                         avg=round(self._agents[agent].avg_score, 3))

    async def _on_heartbeat(self, msg: dict[str, Any]) -> None:
        agent = msg.get("agent", "")
        if agent in self._agents:
            self._agents[agent].last_seen = time.time()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _candidates_for(self, capability: str) -> list[AgentInfo]:
        names = self._by_capability.get(capability, [])
        return [self._agents[n] for n in names
                if n in self._agents and self._agents[n].is_alive()]


# ── Module-level singleton (shared across the process) ────────────────────────
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
