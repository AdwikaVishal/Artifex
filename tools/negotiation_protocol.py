"""
tools/negotiation_protocol.py – Message schemas and scoring logic for the
emergent swarm auction / team-formation protocol.

Agents use these classes to announce tasks, submit bids, and compute scores
without any central controller deciding the outcome.
"""

from __future__ import annotations

import json
from typing import Any


# ── Message schemas ───────────────────────────────────────────────────────────

class TaskAnnouncement:
    """
    Broadcast by the Planner (or EmergentSwarmWorkflow activity) to invite
    all agents to bid on a task.
    """

    def __init__(
        self,
        task_id: str,
        task_type: str,
        requirements: dict[str, Any],
        deadline: float,
        goal: str = "",
    ) -> None:
        self.task_id      = task_id
        self.task_type    = task_type
        self.requirements = requirements
        self.deadline     = deadline
        self.goal         = goal

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id":      self.task_id,
            "task_type":    self.task_type,
            "requirements": self.requirements,
            "deadline":     self.deadline,
            "goal":         self.goal,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskAnnouncement":
        return cls(
            task_id=d["task_id"],
            task_type=d.get("task_type", "unknown"),
            requirements=d.get("requirements", {}),
            deadline=d.get("deadline", 0.0),
            goal=d.get("goal", ""),
        )


class Bid:
    """
    Submitted by an agent in response to a TaskAnnouncement.
    score is 0–100; higher is better.
    proposed_team lists agent names the bidder wants to include.
    """

    def __init__(
        self,
        agent_id: str,
        task_id: str,
        score: float,
        proposed_team: list[str] | None = None,
        capabilities: list[str] | None = None,
    ) -> None:
        self.agent_id      = agent_id
        self.task_id       = task_id
        self.score         = score
        self.proposed_team = proposed_team or [agent_id]
        self.capabilities  = capabilities or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id":      self.agent_id,
            "task_id":       self.task_id,
            "score":         self.score,
            "proposed_team": self.proposed_team,
            "capabilities":  self.capabilities,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Bid":
        return cls(
            agent_id=d["agent_id"],
            task_id=d.get("task_id", ""),
            score=float(d.get("score", 0.0)),
            proposed_team=d.get("proposed_team"),
            capabilities=d.get("capabilities"),
        )


# ── Scoring heuristic ─────────────────────────────────────────────────────────

def compute_agent_score(agent_status: dict[str, Any], task_req: dict[str, Any]) -> float:
    """
    Heuristic bid score (0–100) based on:
      • Capability match  – does the agent support the required capability?  (50 pts)
      • Load factor       – fewer current tasks → higher score               (30 pts)
      • Historical success rate                                               (20 pts)

    Args:
        agent_status: dict with keys:
            capabilities   – list[str]
            current_tasks  – int   (default 0)
            success_rate   – float 0–1 (default 0.5)
        task_req: dict with optional key:
            required_capability – str
    """
    required = task_req.get("required_capability", "")
    caps     = agent_status.get("capabilities", [])

    capability_match = 1.0 if (required and required in caps) else (0.5 if not required else 0.3)
    load_factor      = 1.0 / (agent_status.get("current_tasks", 0) + 1)
    success_factor   = float(agent_status.get("success_rate", 0.5))

    return (capability_match * 50.0) + (load_factor * 30.0) + (success_factor * 20.0)
