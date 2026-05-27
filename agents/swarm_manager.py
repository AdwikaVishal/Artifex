"""
agents/swarm_manager.py – Swarm Manager Agent

Facilitates emergent task auctions and ad-hoc team formation.
No hardcoded decisions: agents self-organise by bidding on announced tasks.

Protocol
────────
1. Planner (or EmergentSwarmWorkflow) publishes a TaskAnnouncement to
   swarm.task.announce.
2. Capable agents respond with Bids on swarm.task.bid within BID_WINDOW_S.
3. SwarmManager selects the winning bid (highest score), forms a team, and
   publishes to swarm.team.formed.
4. A TeamCoordinator is spawned as an asyncio task to run the team.
5. On completion the result is published to swarm.task.complete.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import structlog

from agents.base import BaseAgent
from agents.team_agent import TeamCoordinator
from nats_client.subjects import Subjects
from tools.negotiation_protocol import Bid

logger = structlog.get_logger()

# ── Configurable timeouts (tunable via env vars, no code change needed) ───────
BID_WINDOW_S: float       = float(os.getenv("AUCTION_WINDOW_SECONDS", "2"))
TEAM_CONFIRM_WAIT_S: float = float(os.getenv("TEAM_FORMATION_TIMEOUT_SECONDS", "2"))


class SwarmManager(BaseAgent):
    """
    Orchestrates task auctions and team formation without imposing a
    hardcoded execution plan.  Teams self-organise based on real-time bids.
    """

    def __init__(self) -> None:
        super().__init__(name="swarm_manager", metrics_port=9099)
        # task_id → list of raw bid dicts received during the auction window
        self._pending_bids: dict[str, list[dict[str, Any]]] = {}
        # task_id → asyncio.Event set when bids are ready to evaluate
        self._bid_events: dict[str, asyncio.Event] = {}
        # team_id → list of agent names
        self._active_teams: dict[str, list[str]] = {}
        # task_id → original announcement dict (needed by TeamCoordinator)
        self._announcements: dict[str, dict[str, Any]] = {}

    # ── Capabilities ──────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> list[str]:
        return ["swarm_manager", "auction", "team_formation"]

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.subscribe(Subjects.TASK_ANNOUNCEMENT, self._handle_task_announce)
        await self.subscribe(Subjects.TASK_BID,          self._handle_bid)
        await self.subscribe(Subjects.TASK_COMPLETION,   self._handle_task_complete)
        self._log.info("swarm_manager.ready")
        await self.log_event("SwarmManager online – ready to conduct auctions", "info")

        # Keep alive
        while self._running:
            await asyncio.sleep(3600)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _handle_task_announce(self, msg: dict[str, Any]) -> None:
        task_id = msg.get("task_id")
        if not task_id:
            self._log.warning("swarm_manager.announce.missing_task_id")
            return

        self._log.info("swarm_manager.auction_open", task_id=task_id,
                       task_type=msg.get("task_type"))
        await self.log_event(
            f"Auction opened for task {task_id} (type={msg.get('task_type')})", "info"
        )

        self._pending_bids[task_id]   = []
        self._bid_events[task_id]     = asyncio.Event()
        self._announcements[task_id]  = msg

        # Wait for the bid window, then evaluate
        await asyncio.sleep(BID_WINDOW_S)
        await self._evaluate_bids(task_id)

    async def _handle_bid(self, msg: dict[str, Any]) -> None:
        task_id = msg.get("task_id")
        if task_id and task_id in self._pending_bids:
            self._pending_bids[task_id].append(msg)
            self._log.debug("swarm_manager.bid_received",
                            task_id=task_id,
                            agent=msg.get("agent_id"),
                            score=msg.get("score"))

    async def _handle_task_complete(self, msg: dict[str, Any]) -> None:
        task_id = msg.get("task_id")
        team_id = f"team-{task_id}"
        if team_id in self._active_teams:
            del self._active_teams[team_id]
        self._log.info("swarm_manager.task_complete", task_id=task_id)
        await self.log_event(f"Task {task_id} completed by team {team_id}", "info")

    # ── Auction logic ─────────────────────────────────────────────────────────

    async def _evaluate_bids(self, task_id: str) -> None:
        bids = self._pending_bids.pop(task_id, [])
        self._log.info("swarm_manager.auction_closed",
                       task_id=task_id, bid_count=len(bids))

        if not bids:
            self._log.warning("swarm_manager.no_bids", task_id=task_id)
            await self.publish(Subjects.TASK_FAILED,
                               {"task_id": task_id, "reason": "no_bids"})
            await self.log_event(f"No bids received for task {task_id}", "warning")
            return

        winning_bid = self._select_best_bid(bids)
        self._log.info("swarm_manager.winner",
                       task_id=task_id,
                       agent=winning_bid.get("agent_id"),
                       score=winning_bid.get("score"))
        await self.log_event(
            f"Winning bid for {task_id}: agent={winning_bid.get('agent_id')} "
            f"score={winning_bid.get('score', 0):.1f}",
            "info",
        )
        await self._form_team(task_id, winning_bid)

    def _select_best_bid(self, bids: list[dict[str, Any]]) -> dict[str, Any]:
        """Return the bid with the highest score."""
        return max(bids, key=lambda b: float(b.get("score", 0)))

    # ── Team formation ────────────────────────────────────────────────────────

    async def _form_team(self, task_id: str, winning_bid: dict[str, Any]) -> None:
        team_id    = f"team-{task_id}"
        agent_ids  = winning_bid.get("proposed_team") or [winning_bid["agent_id"]]
        task_data  = self._announcements.get(task_id, {})

        # Notify each agent of the team invite
        for aid in agent_ids:
            await self.publish(
                f"agent.{aid}.team_invite",
                {"team_id": team_id, "task_id": task_id},
            )

        # Brief wait for confirmations (simplified – assume formed after delay)
        await asyncio.sleep(TEAM_CONFIRM_WAIT_S)

        self._active_teams[team_id] = agent_ids
        await self.publish(
            Subjects.TEAM_FORMED,
            {"team_id": team_id, "task_id": task_id, "agents": agent_ids},
        )
        self._log.info("swarm_manager.team_formed",
                       team_id=team_id, agents=agent_ids)
        await self.log_event(
            f"Team {team_id} formed with agents: {', '.join(agent_ids)}", "info"
        )

        # Spawn the TeamCoordinator as a background asyncio task
        coordinator = TeamCoordinator(
            team_id=team_id,
            member_ids=agent_ids,
            task=task_data,
            nats_url=self.nats_url,
        )
        asyncio.create_task(
            coordinator.start(),
            name=f"coordinator-{team_id}",
        )
