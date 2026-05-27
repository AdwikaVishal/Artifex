"""
conftest.py – shared pytest fixtures for Artifex tests.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ── Event loop ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ── Mock NATS ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_nats_manager():
    """Return a fully mocked NATSManager."""
    with patch("nats_client.client.NATSManager") as MockManager:
        instance = MockManager.return_value
        instance.nc = MagicMock()
        instance.nc.is_closed = False
        instance.connect = AsyncMock()
        instance.publish = AsyncMock()
        instance.subscribe = AsyncMock()
        instance.request = AsyncMock()
        instance.reply = AsyncMock()
        instance.close = AsyncMock()
        yield instance


# ── Mock Groq ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_groq_chat():
    """Mock ChatGroq to return a deterministic plan."""
    plan = {
        "tasks": [
            {"id": "t1", "type": "execute", "tool": "http",
             "params": {"url": "https://example.com", "method": "GET"}}
        ]
    }
    mock_response = MagicMock()
    mock_response.content = json.dumps(plan)

    with patch("langchain_groq.ChatGroq.ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = mock_response
        yield mock_invoke, plan


@pytest.fixture
def mock_groq_validator():
    """Mock ChatGroq for validator to return valid."""
    mock_response = MagicMock()
    mock_response.content = json.dumps({"valid": True, "reason": "looks good"})

    with patch("langchain_groq.ChatGroq.ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = mock_response
        yield mock_invoke
