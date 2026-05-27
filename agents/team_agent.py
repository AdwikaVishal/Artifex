"""
agents/team_agent.py – TeamCoordinator

A temporary agent that coordinates a self-organised team of agents using
consensus voting.  Spawned by SwarmManager after a winning bid is selected;
disbanded automatically after the task completes.

Protocol
────────
1. Ask each member to propose a solution via agent.<member>.propose.
2. Each member votes for the proposal with the highest confidence score
   (excluding its own).
3. The most-voted proposal becomes the final answer.
4. Result is published to swarm.task.complete.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.base import BaseAgent
from nats_client.subjects import Subjects


class TeamCoordinator(BaseAgent):
    """
    Manages a temporary team: collects proposals, runs consensus voting,
    and publishes the final result.
    """

    def __init__(
        self,
        team_id: str,
        member_ids: list[str],
        task: dict[str, Any],
        nats_url: str | None = None,
    ) -> None:
        # Use a unique metrics port offset to avoid clashes with other agents.
        # In production, disable per-coordinator metrics or use a shared registry.
        super().__init__(
            name=f"team_coordinator_{team_id}",
            nats_url=nats_url,
            metrics_port=0,   # 0 = skip Prometheus server for ephemeral agents
        )
        self.team_id   = team_id
        self.members   = member_ids
        self.task      = task

    # ── Override start() to skip Prometheus for ephemeral agents ─────────────

    async def start(self) -> None:
        self._log.info("team_coordinator.starting", team_id=self.team_id)
        await self._nats.connect()
        self._running = True
        asyncio.create_task(self._heartbeat_loop(), name=f"{self.name}-heartbeat")
        await self.run()

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        task_id = self.task.get("task_id", self.team_id)
        self._log.info("team_coordinator.run",
                       team_id=self.team_id, members=self.members, task_id=task_id)
        await self.log_event(
            f"TeamCoordinator {self.team_id} started with members: {', '.join(self.members)}",
            "info",
        )

        # ── Step 1: collect proposals from each member ────────────────────────
        proposals: dict[str, dict[str, Any]] = {}
        for member in self.members:
            try:
                resp = await self.request(
                    f"agent.{member}.propose",
                    {"task": self.task, "team_id": self.team_id},
                    timeout=10.0,
                )
                proposals[member] = resp
                self._log.debug("team_coordinator.proposal_received",
                                member=member, confidence=resp.get("confidence", 0))
            except Exception as exc:  # noqa: BLE001
                self._log.warning("team_coordinator.proposal_timeout",
                                  member=member, error=str(exc))
                proposals[member] = {"confidence": 0.0, "result": None, "error": str(exc)}

        if not proposals:
            await self._publish_failure(task_id, "no proposals received")
            return

        # ── Step 2: consensus voting ──────────────────────────────────────────
        # Each member votes for the proposal with the highest confidence
        # (excluding its own to avoid self-bias).
        vote_counts: dict[str, int] = {m: 0 for m in proposals}

        for voter in proposals:
            others = {m: p for m, p in proposals.items() if m != voter}
            if not others:
                # Only one member – it wins by default
                vote_counts[voter] += 1
                continue
            best_member = max(
                others,
                key=lambda m: float(others[m].get("confidence", 0)),
            )
            vote_counts[best_member] += 1
            self._log.debug("team_coordinator.vote",
                            voter=voter, voted_for=best_member)

        winner = max(vote_counts, key=lambda m: vote_counts[m])
        final_proposal = proposals[winner]

        self._log.info("team_coordinator.consensus",
                       winner=winner, votes=vote_counts, task_id=task_id)
        await self.log_event(
            f"Consensus reached: winner={winner} votes={vote_counts}", "info"
        )

        # ── Step 3: publish result ────────────────────────────────────────────
        await self.publish(
            Subjects.TASK_COMPLETION,
            {
                "task_id":  task_id,
                "team_id":  self.team_id,
                "result":   final_proposal.get("result"),
                "winner":   winner,
                "votes":    vote_counts,
                "status":   "completed",
            },
        )

        # Also publish to the API result bus so the workflow can pick it up
        await self.publish(
            Subjects.API_RESULT,
            {
                "workflow_id":  task_id,
                "status":       "completed",
                "final_answer": final_proposal.get("result"),
                "team_id":      self.team_id,
                "winner":       winner,
            },
        )

        self._running = False
        await self._nats.close()

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _publish_failure(self, task_id: str, reason: str) -> None:
        self._log.warning("team_coordinator.failed",
                          task_id=task_id, reason=reason)
        await self.publish(
            Subjects.TASK_COMPLETION,
            {"task_id": task_id, "team_id": self.team_id,
             "status": "failed", "reason": reason},
        )
        self._running = False
        await self._nats.close()
