"""
test_planner.py – unit tests for PlannerAgent.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.planner import PlannerAgent


@pytest.fixture
def planner():
    with patch("agents.planner.ChatGroq"):
        agent = PlannerAgent()
        agent._nats = MagicMock()
        agent._nats.publish = AsyncMock()
        agent._nats.subscribe = AsyncMock()
        agent._nats.connect = AsyncMock()
        return agent


@pytest.mark.asyncio
async def test_generate_plan_returns_tasks(planner):
    """_generate_plan should return a dict with a non-empty tasks list."""
    expected_plan = {
        "tasks": [
            {"id": "t1", "type": "execute", "tool": "http",
             "params": {"url": "https://api.example.com/capital/france", "method": "GET"}}
        ]
    }
    mock_response = MagicMock()
    mock_response.content = json.dumps(expected_plan)
    planner._llm.ainvoke = AsyncMock(return_value=mock_response)

    plan = await planner._generate_plan("What is the capital of France?")

    assert "tasks" in plan
    assert len(plan["tasks"]) > 0
    assert plan["tasks"][0]["type"] in ("retrieve", "execute", "validate")


@pytest.mark.asyncio
async def test_generate_plan_handles_invalid_json(planner):
    """_generate_plan should return a fallback plan on JSON parse error."""
    mock_response = MagicMock()
    mock_response.content = "This is not JSON at all."
    planner._llm.ainvoke = AsyncMock(return_value=mock_response)

    plan = await planner._generate_plan("Some goal")

    assert "tasks" in plan
    assert len(plan["tasks"]) == 1  # fallback single task


@pytest.mark.asyncio
async def test_handle_request_publishes_to_executor(planner):
    """handle_request should publish the first task to the correct subject."""
    plan = {
        "tasks": [
            {"id": "t1", "type": "execute", "tool": "http",
             "params": {"url": "https://example.com", "method": "GET"}}
        ]
    }
    mock_response = MagicMock()
    mock_response.content = json.dumps(plan)
    planner._llm.ainvoke = AsyncMock(return_value=mock_response)

    msg = {"goal": "What is the capital of France?", "workflow_id": "wf-test-001"}
    await planner.handle_request(msg)

    planner._nats.publish.assert_called_once()
    call_args = planner._nats.publish.call_args
    subject = call_args[0][0]
    assert subject == "agent.executor.inbox"


@pytest.mark.asyncio
async def test_handle_request_replies_when_reply_to_set(planner):
    """handle_request should reply to _reply subject when present."""
    plan = {
        "tasks": [
            {"id": "t1", "type": "retrieve", "params": {"query": "capital of France"}}
        ]
    }
    mock_response = MagicMock()
    mock_response.content = json.dumps(plan)
    planner._llm.ainvoke = AsyncMock(return_value=mock_response)
    planner._nats.reply = AsyncMock()

    msg = {
        "goal": "What is the capital of France?",
        "workflow_id": "wf-test-002",
        "_reply": "_INBOX.abc123",
    }
    await planner.handle_request(msg)

    planner._nats.reply.assert_called_once()
    reply_subject = planner._nats.reply.call_args[0][0]
    assert reply_subject == "_INBOX.abc123"


@pytest.mark.asyncio
async def test_handle_replan_includes_error_context(planner):
    """handle_replan should augment the goal with the error before replanning."""
    captured_goals = []

    async def capture_plan(goal: str):
        captured_goals.append(goal)
        return {"tasks": [{"id": "t1", "type": "execute", "tool": "http", "params": {}}]}

    planner._generate_plan = capture_plan

    msg = {
        "original_goal": "What is the capital of France?",
        "error": "HTTP 404 not found",
        "workflow_id": "wf-test-003",
    }
    await planner.handle_replan(msg)

    assert len(captured_goals) == 1
    assert "HTTP 404 not found" in captured_goals[0]
