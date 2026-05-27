"""
SwarmState – the shared state dict that flows through the LangGraph.

All fields are optional so nodes can update only what they touch.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class SwarmState(TypedDict, total=False):
    # ── Input ─────────────────────────────────────────────────────────────────
    goal: str                          # original user goal
    workflow_id: str                   # unique run identifier

    # ── Planning ──────────────────────────────────────────────────────────────
    plan: dict[str, Any]               # full plan from Planner
    tasks: list[dict[str, Any]]        # ordered task list
    current_task_index: int            # pointer into tasks

    # ── Execution ─────────────────────────────────────────────────────────────
    current_task: dict[str, Any]       # task currently being processed
    last_result: Optional[dict[str, Any]]  # most recent agent output

    # ── Validation ────────────────────────────────────────────────────────────
    validation_passed: bool
    validation_error: Optional[str]

    # ── Output ────────────────────────────────────────────────────────────────
    final_answer: Optional[Any]
    history: list[dict[str, Any]]      # audit trail of all results

    # ── Control ───────────────────────────────────────────────────────────────
    retry_count: int
    max_retries: int
    error: Optional[str]
