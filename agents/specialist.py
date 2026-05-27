"""
agents/specialist.py – On-demand domain specialist agent.

A SpecialistAgent is a lightweight, ephemeral agent that is created at
runtime by spawn_specialist_activity when the planner detects a task
requiring domain-specific expertise (finance, medicine, legal, etc.).

It subscribes to a unique NATS subject, answers one query, then shuts
down cleanly. This avoids the overhead of maintaining permanent specialist
containers while still giving the swarm deep domain knowledge on demand.

Lifecycle:
  1. spawn_specialist_activity creates a SpecialistAgent with a domain prompt.
  2. The agent subscribes to agent.<agent_id>.inbox.
  3. spawn_specialist_activity sends the query via NATS request-reply.
  4. The agent answers and publishes the result back.
  5. spawn_specialist_activity sends a shutdown signal; the agent stops.

Domain prompts are defined in SPECIALIST_PROMPTS below. Add new domains
by extending that dict – no code changes required elsewhere.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from langchain_groq import ChatGroq
from langchain.schema import HumanMessage, SystemMessage

from .base import BaseAgent

logger = structlog.get_logger()

# ── Domain system prompts ─────────────────────────────────────────────────────
SPECIALIST_PROMPTS: dict[str, str] = {
    "finance": (
        "You are a senior financial analyst with expertise in equity markets, "
        "macroeconomics, and corporate finance. Provide concise, data-driven "
        "answers. Always note when real-time data is needed."
    ),
    "medicine": (
        "You are a medical information specialist. Provide accurate, evidence-based "
        "health information. Always recommend consulting a licensed physician for "
        "personal medical decisions. Never diagnose."
    ),
    "legal": (
        "You are a legal research assistant. Summarise relevant laws and precedents "
        "clearly. Always note that this is not legal advice and recommend consulting "
        "a qualified attorney for specific situations."
    ),
    "foster_care": (
        "You are a licensed social work specialist with expertise in foster care "
        "regulations, child welfare best practices, and placement stability research. "
        "Provide evidence-based guidance grounded in AFCARS data and CWLA standards."
    ),
    "data_analysis": (
        "You are a data scientist specialising in statistical analysis and "
        "machine learning. Explain findings clearly for non-technical audiences "
        "while maintaining analytical rigour."
    ),
}

_DEFAULT_PROMPT = "You are a helpful expert assistant. Answer concisely and accurately."


class SpecialistAgent(BaseAgent):
    """
    Ephemeral domain-specialist agent.

    Args:
        agent_id:      unique identifier (used as NATS subject prefix)
        domain:        key into SPECIALIST_PROMPTS (or a raw system prompt string)
        model_name:    Groq model to use (default: llama-3.1-8b-instant)
    """

    def __init__(
        self,
        agent_id: str,
        domain: str,
        model_name: str | None = None,
    ) -> None:
        super().__init__(name=agent_id, metrics_port=0)   # port=0 → skip metrics server
        self._inbox   = f"agent.{agent_id}.inbox"
        self._shutdown_subject = f"agent.{agent_id}.shutdown"
        self._system_prompt = (
            SPECIALIST_PROMPTS.get(domain, domain)   # allow raw prompt as fallback
            or _DEFAULT_PROMPT
        )
        self._llm = ChatGroq(
            model=model_name or os.getenv("SPECIALIST_MODEL", "llama-3.1-8b-instant"),
            temperature=0.1,
        )
        self._answered = asyncio.Event()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Override: skip Prometheus server (ephemeral agent doesn't need metrics)."""
        self._log.info("specialist.starting", inbox=self._inbox)
        await self._nats.connect()
        self._running = True
        await self.run()

    async def run(self) -> None:
        await self.subscribe(self._inbox, self._handle_query)
        await self.subscribe(self._shutdown_subject, self._handle_shutdown)
        self._log.info("specialist.ready", inbox=self._inbox)
        # Wait until the query is answered or a shutdown signal arrives
        await self._answered.wait()
        await self._nats.close()
        self._log.info("specialist.stopped")

    # ── Handlers ─────────────────────────────────────────────────────────────

    async def _handle_query(self, msg: dict[str, Any]) -> None:
        query    = msg.get("query", "")
        reply_to = msg.get("_reply") or msg.get("reply_to")

        self._log.info("specialist.query", query=query[:80])

        try:
            messages = [
                SystemMessage(content=self._system_prompt),
                HumanMessage(content=query),
            ]
            response = await self._llm.ainvoke(messages)
            answer = response.content.strip()
        except Exception as exc:  # noqa: BLE001
            self._log.exception("specialist.llm_error", error=str(exc))
            answer = f"Specialist error: {exc}"

        result = {
            "status": "ok",
            "result": {"answer": answer, "domain": self.name},
        }

        if reply_to:
            await self.reply(reply_to, result)
        else:
            await self.publish("api.result", result)

        self._answered.set()   # signal run() to exit

    async def _handle_shutdown(self, _msg: dict[str, Any]) -> None:
        self._log.info("specialist.shutdown_received")
        self._answered.set()
