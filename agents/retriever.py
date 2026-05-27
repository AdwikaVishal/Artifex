"""
RetrieverAgent – embeds a query and fetches top-k documents from Qdrant.

Listens on:  agent.retriever.inbox
Publishes:   agent.validator.inbox  (with retrieved context)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from sentence_transformers import SentenceTransformer

from nats_client.subjects import Subjects
from tools.vector_tool import VectorTool
from .base import BaseAgent

logger = structlog.get_logger()


class RetrieverAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="retriever", metrics_port=9092)
        # Groq has no embeddings API – use a local sentence-transformers model instead.
        # all-MiniLM-L6-v2 produces 384-dim vectors; fast and runs on CPU.
        self._encoder = SentenceTransformer("all-MiniLM-L6-v2")
        self._vector = VectorTool(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            collection=os.getenv("QDRANT_COLLECTION", "artifex"),
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.subscribe(Subjects.RETRIEVER_INBOX, self.handle_retrieve, queue="retriever")
        # Emergent swarm: bid on announced tasks
        await self.subscribe(Subjects.TASK_ANNOUNCEMENT, self._handle_task_announcement)
        # Emergent swarm: respond to proposal requests from TeamCoordinator
        await self.subscribe(f"agent.{self.name}.propose", self._handle_propose)
        self._log.info("retriever.ready")
        while self._running:
            await asyncio.sleep(3600)

    # ── Emergent swarm: bidding ───────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current agent status for bid scoring."""
        return {
            "capabilities": self.capabilities,
            "current_tasks": 0,
            "success_rate":  0.8,
        }

    async def _handle_task_announcement(self, msg: dict) -> None:
        """Evaluate the announced task and submit a bid if capable."""
        from tools.negotiation_protocol import compute_agent_score, Bid  # noqa: PLC0415
        task_id  = msg.get("task_id", "")
        task_req = msg.get("requirements", {})
        score    = compute_agent_score(self.get_status(), task_req)
        bid      = Bid(
            agent_id=self.name,
            task_id=task_id,
            score=score,
            proposed_team=[self.name],
            capabilities=self.capabilities,
        )
        await self.publish(Subjects.TASK_BID, bid.to_dict())
        self._log.debug("retriever.bid_submitted", task_id=task_id, score=score)

    async def _handle_propose(self, msg: dict) -> None:
        """
        TeamCoordinator asks this agent to propose a solution.
        We run a retrieval and return the result with a confidence score.
        """
        task     = msg.get("task", {})
        reply_to = msg.get("_reply") or msg.get("reply_to")
        query    = task.get("requirements", {}).get("goal", task.get("goal", ""))
        inner_task = {
            "type":   "retrieve",
            "params": {"query": query, "top_k": 5},
            "id":     task.get("task_id", ""),
        }
        try:
            await self.handle_retrieve({
                "task": inner_task,
                "remaining_tasks": [],
                "workflow_id": task.get("task_id", "emergent"),
                "_reply": reply_to,
            })
        except Exception as exc:  # noqa: BLE001
            if reply_to:
                await self.reply(reply_to, {"confidence": 0.0, "result": None, "error": str(exc)})

    # ── Handler ───────────────────────────────────────────────────────────────

    async def handle_retrieve(self, msg: dict[str, Any]) -> None:
        task: dict = msg.get("task", {})
        remaining: list = msg.get("remaining_tasks", [])
        workflow_id: str = msg.get("workflow_id", "unknown")
        reply_to: str | None = msg.get("_reply") or msg.get("reply_to")

        query: str = task.get("params", {}).get("query", "")
        top_k: int = task.get("params", {}).get("top_k", 5)

        self._log.info("retriever.handle", query=query, workflow_id=workflow_id)

        try:
            embedding = await self._embed(query)
            documents = await self._vector.search(embedding, top_k=top_k)
            result = {
                "status": "ok",
                "documents": documents,
                "query": query,
                "task_id": task.get("id"),
            }
        except Exception as exc:  # noqa: BLE001
            self._log.exception("retriever.error", error=str(exc))
            result = {"status": "error", "error": str(exc), "task_id": task.get("id")}

        payload = {
            "task": task,
            "result": result,
            "remaining_tasks": remaining,
            "workflow_id": workflow_id,
        }

        if reply_to:
            await self.reply(reply_to, payload)
        else:
            await self.publish(Subjects.VALIDATOR_INBOX, payload)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float]:
        """Embed text using a local sentence-transformers model (CPU-friendly)."""
        import asyncio
        loop = asyncio.get_event_loop()
        # encode() is synchronous – run in executor to avoid blocking the event loop
        embedding = await loop.run_in_executor(None, self._encoder.encode, text)
        return embedding.tolist()
