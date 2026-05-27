"""
swarm_graph.py – LangGraph StateGraph for the Artifex agent swarm.

Each node delegates work to an external agent via NATS request-reply.
The graph waits synchronously for the NATS reply before advancing.

Graph topology:
  planner → retriever → executor → validator
                ↑                       |
                └──── replan ───────────┘ (on failure)
                                        └── END (on success)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from nats_client.client import NATSManager
from nats_client.subjects import Subjects
from .state import SwarmState

logger = structlog.get_logger()

NATS_TIMEOUT = float(os.getenv("NATS_REQUEST_TIMEOUT", "60"))


# ── NATS helper (shared across nodes) ────────────────────────────────────────

async def _nats_request(subject: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send a NATS request and await the reply."""
    manager = NATSManager()
    if not manager.nc or manager.nc.is_closed:
        await manager.connect()
    return await manager.request(subject, payload, timeout=NATS_TIMEOUT)


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def planner_node(state: SwarmState) -> dict[str, Any]:
    """Call the Planner agent to decompose the goal into tasks."""
    goal = state.get("goal", "")
    workflow_id = state.get("workflow_id", str(uuid.uuid4()))
    retry_count = state.get("retry_count", 0)
    error = state.get("error")

    logger.info("graph.planner_node", goal=goal, workflow_id=workflow_id)

    subject = Subjects.PLANNER_REPLAN if (retry_count > 0 and error) else Subjects.PLANNER_REQUEST
    payload: dict[str, Any] = {
        "goal": goal,
        "workflow_id": workflow_id,
    }
    if error:
        payload["error"] = error
        payload["original_goal"] = goal

    response = await _nats_request(subject, payload)
    plan: dict = response.get("plan", {"tasks": []})
    tasks: list = plan.get("tasks", [])

    return {
        "plan": plan,
        "tasks": tasks,
        "current_task_index": 0,
        "current_task": tasks[0] if tasks else {},
        "history": state.get("history", []) + [{"node": "planner", "plan": plan}],
        "error": None,
        "workflow_id": workflow_id,
    }


async def retriever_node(state: SwarmState) -> dict[str, Any]:
    """Call the Retriever agent for the current task."""
    task = state.get("current_task", {})
    workflow_id = state.get("workflow_id", "")
    remaining = state.get("tasks", [])[state.get("current_task_index", 0) + 1:]

    logger.info("graph.retriever_node", task_id=task.get("id"), workflow_id=workflow_id)

    response = await _nats_request(Subjects.RETRIEVER_INBOX, {
        "task": task,
        "remaining_tasks": remaining,
        "workflow_id": workflow_id,
    })

    result = response.get("result", {})
    history = state.get("history", []) + [{"node": "retriever", "result": result}]
    return {"last_result": result, "history": history}


async def executor_node(state: SwarmState) -> dict[str, Any]:
    """Call the Executor agent for the current task."""
    task = state.get("current_task", {})
    workflow_id = state.get("workflow_id", "")
    remaining = state.get("tasks", [])[state.get("current_task_index", 0) + 1:]

    logger.info("graph.executor_node", task_id=task.get("id"), workflow_id=workflow_id)

    response = await _nats_request(Subjects.EXECUTOR_INBOX, {
        "task": task,
        "remaining_tasks": remaining,
        "workflow_id": workflow_id,
    })

    result = response.get("result", {})
    history = state.get("history", []) + [{"node": "executor", "result": result}]
    return {"last_result": result, "history": history}


async def validator_node(state: SwarmState) -> dict[str, Any]:
    """Call the Validator agent to check the last result."""
    task = state.get("current_task", {})
    last_result = state.get("last_result", {})
    workflow_id = state.get("workflow_id", "")
    goal = state.get("goal", "")
    tasks = state.get("tasks", [])
    idx = state.get("current_task_index", 0)
    remaining = tasks[idx + 1:]

    logger.info("graph.validator_node", task_id=task.get("id"), workflow_id=workflow_id)

    response = await _nats_request(Subjects.VALIDATOR_INBOX, {
        "task": task,
        "result": last_result,
        "remaining_tasks": remaining,
        "workflow_id": workflow_id,
        "original_goal": goal,
    })

    status = response.get("status", "failed")
    history = state.get("history", []) + [{"node": "validator", "status": status}]

    if status == "completed":
        return {
            "validation_passed": True,
            "final_answer": response.get("final_answer"),
            "history": history,
            "error": None,
        }
    elif status == "continue":
        # Advance to next task
        next_task = remaining[0] if remaining else {}
        return {
            "validation_passed": True,
            "current_task": next_task,
            "current_task_index": idx + 1,
            "history": history,
            "error": None,
        }
    else:
        # Failed – trigger replan
        return {
            "validation_passed": False,
            "error": response.get("error", "validation failed"),
            "retry_count": state.get("retry_count", 0) + 1,
            "history": history,
        }


# ── Routing functions ─────────────────────────────────────────────────────────

def route_after_planner(state: SwarmState) -> str:
    """Route to the correct first node based on the first task type."""
    tasks = state.get("tasks", [])
    if not tasks:
        return END  # type: ignore[return-value]
    first_type = tasks[0].get("type", "execute")
    # search and direct_answer both go to the executor node
    return {
        "retrieve":      "retriever",
        "execute":       "executor",
        "search":        "executor",
        "direct_answer": "executor",
        "validate":      "validator",
    }.get(first_type, "executor")


def route_after_validator(state: SwarmState) -> str:
    """After validation: finish, continue, or replan."""
    if state.get("final_answer") is not None:
        return END  # type: ignore[return-value]

    if not state.get("validation_passed", True):
        max_retries = state.get("max_retries", 3)
        if state.get("retry_count", 0) >= max_retries:
            return END  # type: ignore[return-value]
        return "planner"  # replan

    # Continue to next task
    next_task = state.get("current_task", {})
    task_type = next_task.get("type", "execute")
    return {"retrieve": "retriever", "execute": "executor", "validate": "validator"}.get(
        task_type, "executor"
    )


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_swarm_graph() -> Any:
    """Build and compile the LangGraph StateGraph."""
    graph = StateGraph(SwarmState)

    graph.add_node("planner", planner_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("executor", executor_node)
    graph.add_node("validator", validator_node)

    graph.set_entry_point("planner")

    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {"retriever": "retriever", "executor": "executor", "validator": "validator", END: END},
    )
    graph.add_edge("retriever", "validator")
    graph.add_edge("executor", "validator")
    graph.add_conditional_edges(
        "validator",
        route_after_validator,
        {
            "planner": "planner",
            "retriever": "retriever",
            "executor": "executor",
            "validator": "validator",
            END: END,
        },
    )

    return graph.compile()
