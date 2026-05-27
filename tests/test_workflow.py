"""
test_workflow.py – integration-style tests for the LangGraph swarm workflow.

Uses mocked NATS so no real broker is needed.
The "capital of France" scenario verifies the full planner → executor → validator path.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.state import SwarmState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_nats_response(data: dict):
    """Return an AsyncMock that yields `data` when awaited."""
    return AsyncMock(return_value=data)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swarm_state_schema():
    """SwarmState TypedDict should accept all expected keys."""
    state: SwarmState = {
        "goal": "What is the capital of France?",
        "workflow_id": "wf-001",
        "plan": {},
        "tasks": [],
        "current_task_index": 0,
        "current_task": {},
        "last_result": None,
        "validation_passed": False,
        "validation_error": None,
        "final_answer": None,
        "history": [],
        "retry_count": 0,
        "max_retries": 3,
        "error": None,
    }
    assert state["goal"] == "What is the capital of France?"
    assert state["retry_count"] == 0


@pytest.mark.asyncio
async def test_planner_node_calls_nats():
    """planner_node should call NATS request on PLANNER_REQUEST subject."""
    plan = {
        "tasks": [
            {"id": "t1", "type": "execute", "tool": "http",
             "params": {"url": "https://example.com", "method": "GET"}}
        ]
    }

    with patch("workflows.swarm_graph._nats_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"plan": plan, "workflow_id": "wf-001"}

        from workflows.swarm_graph import planner_node

        state: SwarmState = {
            "goal": "What is the capital of France?",
            "workflow_id": "wf-001",
            "retry_count": 0,
            "error": None,
            "history": [],
        }
        result = await planner_node(state)

    mock_req.assert_called_once()
    subject_used = mock_req.call_args[0][0]
    assert subject_used == "agent.planner.request"
    assert "tasks" in result
    assert len(result["tasks"]) == 1


@pytest.mark.asyncio
async def test_executor_node_calls_nats():
    """executor_node should call NATS request on EXECUTOR_INBOX subject."""
    exec_result = {"status": "ok", "result": {"answer": "Paris"}, "task_id": "t1"}

    with patch("workflows.swarm_graph._nats_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"result": exec_result}

        from workflows.swarm_graph import executor_node

        state: SwarmState = {
            "goal": "What is the capital of France?",
            "workflow_id": "wf-001",
            "current_task": {"id": "t1", "type": "execute", "tool": "http", "params": {}},
            "current_task_index": 0,
            "tasks": [{"id": "t1", "type": "execute", "tool": "http", "params": {}}],
            "history": [],
        }
        result = await executor_node(state)

    mock_req.assert_called_once()
    subject_used = mock_req.call_args[0][0]
    assert subject_used == "agent.executor.inbox"
    assert result["last_result"]["status"] == "ok"


@pytest.mark.asyncio
async def test_validator_node_completed():
    """validator_node should set final_answer when status is 'completed'."""
    with patch("workflows.swarm_graph._nats_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {
            "status": "completed",
            "final_answer": "Paris",
            "workflow_id": "wf-001",
        }

        from workflows.swarm_graph import validator_node

        state: SwarmState = {
            "goal": "What is the capital of France?",
            "workflow_id": "wf-001",
            "current_task": {"id": "t1", "type": "execute", "tool": "http", "params": {}},
            "current_task_index": 0,
            "tasks": [{"id": "t1", "type": "execute", "tool": "http", "params": {}}],
            "last_result": {"status": "ok", "result": "Paris"},
            "history": [],
        }
        result = await validator_node(state)

    assert result["final_answer"] == "Paris"
    assert result["validation_passed"] is True


@pytest.mark.asyncio
async def test_validator_node_triggers_replan_on_failure():
    """validator_node should set error and increment retry_count on failure."""
    with patch("workflows.swarm_graph._nats_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {
            "status": "failed",
            "error": "result did not match expected schema",
        }

        from workflows.swarm_graph import validator_node

        state: SwarmState = {
            "goal": "What is the capital of France?",
            "workflow_id": "wf-001",
            "current_task": {"id": "t1", "type": "execute", "tool": "http", "params": {}},
            "current_task_index": 0,
            "tasks": [{"id": "t1", "type": "execute", "tool": "http", "params": {}}],
            "last_result": {"status": "error", "error": "404"},
            "retry_count": 0,
            "history": [],
        }
        result = await validator_node(state)

    assert result["validation_passed"] is False
    assert result["retry_count"] == 1
    assert "error" in result


@pytest.mark.asyncio
async def test_full_workflow_capital_of_france():
    """
    End-to-end: submit 'What is the capital of France?' and expect 'Paris'.
    All NATS calls are mocked.
    """
    plan = {
        "tasks": [
            {"id": "t1", "type": "execute", "tool": "http",
             "params": {"url": "https://restcountries.com/v3.1/name/france", "method": "GET"}}
        ]
    }

    call_count = {"n": 0}

    async def mock_nats_request(subject: str, payload: dict, **kwargs) -> dict:
        call_count["n"] += 1
        if "planner" in subject:
            return {"plan": plan, "workflow_id": "wf-e2e"}
        elif "executor" in subject:
            return {"result": {"status": "ok", "result": "Paris", "task_id": "t1"}}
        elif "validator" in subject:
            return {"status": "completed", "final_answer": "Paris", "workflow_id": "wf-e2e"}
        return {}

    with patch("workflows.swarm_graph._nats_request", side_effect=mock_nats_request):
        from workflows.swarm_graph import build_swarm_graph

        app = build_swarm_graph()
        initial_state: SwarmState = {
            "goal": "What is the capital of France?",
            "workflow_id": "wf-e2e",
            "retry_count": 0,
            "max_retries": 3,
            "history": [],
        }
        final_state = await app.ainvoke(initial_state)

    assert final_state.get("final_answer") == "Paris"
    # Planner, executor, and validator were each called once
    assert call_count["n"] == 3
