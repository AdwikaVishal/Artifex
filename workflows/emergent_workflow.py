"""
workflows/emergent_workflow.py – EmergentSwarmWorkflow

An alternative Temporal workflow that uses the auction / team-formation
protocol instead of a fixed planner → executor → validator chain.

Flow
────
1. announce_task_activity  – publishes TaskAnnouncement to NATS
2. wait_for_team_activity  – polls NATS for swarm.team.formed (up to 30 s)
3. wait_for_result_activity – polls NATS for swarm.task.complete (up to 120 s)

The actual work is done by the self-organised team (SwarmManager +
TeamCoordinator + bidding agents) – Temporal only provides durability and
timeout guarantees.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

import structlog

logger = structlog.get_logger()

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "artifex-queue")

# ── Configurable timeouts (match swarm_manager.py env vars) ──────────────────
_AUCTION_WINDOW_S      = float(os.getenv("AUCTION_WINDOW_SECONDS", "2"))
_TEAM_FORMATION_S      = float(os.getenv("TEAM_FORMATION_TIMEOUT_SECONDS", "2"))
# Total time to wait for a team: auction + formation + small buffer
_TEAM_WAIT_TIMEOUT_S   = _AUCTION_WINDOW_S + _TEAM_FORMATION_S + 10.0

_retry_once = RetryPolicy(maximum_attempts=1)
_retry_3    = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)


# ── Activities ────────────────────────────────────────────────────────────────

@activity.defn(name="announce_task_activity")
async def announce_task_activity(announcement_json: str) -> str:
    """
    Publish a TaskAnnouncement to NATS so all agents can bid.
    Returns the task_id for downstream activities.
    """
    import nats as nats_lib  # noqa: PLC0415

    nats_url = os.getenv("NATS_URL", "nats://nats:4222")
    nc = await nats_lib.connect(nats_url)
    try:
        from nats_client.subjects import Subjects  # noqa: PLC0415
        await nc.publish(Subjects.TASK_ANNOUNCEMENT, announcement_json.encode())
        logger.info("announce_task_activity.published")
    finally:
        await nc.drain()

    data = json.loads(announcement_json)
    return data.get("task_id", "")


@activity.defn(name="wait_for_team_activity")
async def wait_for_team_activity(task_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
    """
    Subscribe to swarm.team.formed and wait until the SwarmManager announces
    the team for this task_id (or timeout).
    """
    import nats as nats_lib  # noqa: PLC0415
    from nats_client.subjects import Subjects  # noqa: PLC0415

    nats_url = os.getenv("NATS_URL", "nats://nats:4222")
    nc = await nats_lib.connect(nats_url)
    result: dict[str, Any] = {}
    event = asyncio.Event()

    async def _handler(msg):  # type: ignore[no-untyped-def]
        nonlocal result
        try:
            data = json.loads(msg.data.decode())
            if data.get("task_id") == task_id:
                result = data
                event.set()
        except Exception:  # noqa: BLE001
            pass

    sub = await nc.subscribe(Subjects.TEAM_FORMED, cb=_handler)
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("wait_for_team_activity.timeout", task_id=task_id)
        result = {"task_id": task_id, "status": "timeout", "agents": []}
    finally:
        await sub.unsubscribe()
        await nc.drain()

    return result


@activity.defn(name="wait_for_result_activity")
async def wait_for_result_activity(task_id: str, timeout_s: float = 120.0) -> dict[str, Any]:
    """
    Subscribe to swarm.task.complete and wait for the TeamCoordinator to
    publish the final result for this task_id (or timeout).
    """
    import nats as nats_lib  # noqa: PLC0415
    from nats_client.subjects import Subjects  # noqa: PLC0415

    nats_url = os.getenv("NATS_URL", "nats://nats:4222")
    nc = await nats_lib.connect(nats_url)
    result: dict[str, Any] = {}
    event = asyncio.Event()

    async def _handler(msg):  # type: ignore[no-untyped-def]
        nonlocal result
        try:
            data = json.loads(msg.data.decode())
            if data.get("task_id") == task_id:
                result = data
                event.set()
        except Exception:  # noqa: BLE001
            pass

    sub = await nc.subscribe(Subjects.TASK_COMPLETION, cb=_handler)
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("wait_for_result_activity.timeout", task_id=task_id)
        result = {
            "task_id": task_id,
            "status":  "timeout",
            "result":  None,
            "reason":  "team did not complete within timeout",
        }
    finally:
        await sub.unsubscribe()
        await nc.drain()

    return result


# ── Workflow ──────────────────────────────────────────────────────────────────

@workflow.defn(name="EmergentSwarmWorkflow")
class EmergentSwarmWorkflow:
    """
    Durable Temporal workflow that delegates execution to the emergent swarm.

    Unlike ArtifexSwarmWorkflow (fixed plan), this workflow only:
      1. Announces the task.
      2. Waits for a team to form.
      3. Waits for the team's result.

    All intelligence lives in the bidding agents and TeamCoordinator.
    """

    def __init__(self) -> None:
        self._task_completed = False
        self._final_result: dict[str, Any] = {}

    @workflow.run
    async def run(self, goal: str) -> dict[str, Any]:
        workflow_id = workflow.info().workflow_id
        task_id     = workflow_id   # reuse workflow_id as task_id for traceability

        workflow.logger.info(
            f"emergent_workflow.started goal={goal!r} task_id={task_id}"
        )

        # Build announcement
        import json as _j  # noqa: PLC0415
        import time as _t  # noqa: PLC0415
        announcement = {
            "task_id":      task_id,
            "task_type":    "complex_task",
            "requirements": {"goal": goal, "required_capability": ""},
            "deadline":     _t.time() + 120.0,
            "goal":         goal,
        }
        announcement_json = _j.dumps(announcement)

        # ── Step 1: announce ──────────────────────────────────────────────────
        await workflow.execute_activity(
            announce_task_activity,
            args=[announcement_json],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_retry_3,
        )
        workflow.logger.info(f"emergent_workflow.announced task_id={task_id}")

        # ── Step 2: wait for team ─────────────────────────────────────────────
        # Timeout is driven by AUCTION_WINDOW_SECONDS + TEAM_FORMATION_TIMEOUT_SECONDS
        # so it stays in sync with swarm_manager without code changes.
        import os as _os  # noqa: PLC0415
        _auction   = float(_os.getenv("AUCTION_WINDOW_SECONDS", "2"))
        _formation = float(_os.getenv("TEAM_FORMATION_TIMEOUT_SECONDS", "2"))
        _team_wait = _auction + _formation + 10.0   # buffer for NATS round-trip

        team_info = await workflow.execute_activity(
            wait_for_team_activity,
            args=[task_id, _team_wait],
            start_to_close_timeout=timedelta(seconds=_team_wait + 10),
            retry_policy=_retry_once,
        )
        workflow.logger.info(
            f"emergent_workflow.team_formed "
            f"agents={team_info.get('agents')} status={team_info.get('status')}"
        )

        if team_info.get("status") == "timeout":
            return {
                "workflow_id":  workflow_id,
                "goal":         goal,
                "final_answer": None,
                "status":       "failed",
                "reason":       "no team formed within 30 s – no agents bid on the task",
            }

        # ── Step 3: wait for result ───────────────────────────────────────────
        result = await workflow.execute_activity(
            wait_for_result_activity,
            args=[task_id, 120.0],
            start_to_close_timeout=timedelta(seconds=130),
            retry_policy=_retry_once,
        )
        workflow.logger.info(
            f"emergent_workflow.result status={result.get('status')} "
            f"winner={result.get('winner')}"
        )

        return {
            "workflow_id":  workflow_id,
            "goal":         goal,
            "final_answer": result.get("result"),
            "team_id":      result.get("team_id"),
            "winner":       result.get("winner"),
            "votes":        result.get("votes"),
            "status":       result.get("status", "completed"),
        }
