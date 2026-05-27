"""
RecoveryAgent – diagnoses failures and suggests corrected tasks.

Listens on:
  validator.failed      – validation failures
  agent.planner.replan  – explicit replan requests

Uses an LLM to classify the failure and produce a corrected task,
then publishes back to agent.planner.request.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from langchain_groq import ChatGroq
from langchain.schema import HumanMessage, SystemMessage

from nats_client.subjects import Subjects
from .base import BaseAgent

logger = structlog.get_logger()

DIAGNOSIS_PROMPT = """You are a failure-diagnosis AI for an agent swarm.
Given a failed task and its error, classify the failure and suggest a corrected task.

Return JSON only:
{
  "failure_class": "tool_error | llm_error | data_error | timeout | unknown",
  "root_cause": "<one sentence>",
  "corrected_task": {
    "id": "<same id as failed task>",
    "type": "retrieve | execute | validate",
    "tool": "<tool name if execute>",
    "params": { ... }
  }
}
"""


class RecoveryAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="recovery", metrics_port=9096)
        self._llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.0,
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.subscribe(Subjects.VALIDATOR_FAILED, self.handle_failure, queue="recovery")
        await self.subscribe(Subjects.PLANNER_REPLAN, self.handle_replan, queue="recovery")
        self._log.info("recovery.ready")
        while self._running:
            await asyncio.sleep(3600)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def handle_failure(self, msg: dict[str, Any]) -> None:
        workflow_id: str = msg.get("workflow_id", "unknown")
        failed_task: dict = msg.get("failed_task", {})
        error: str = msg.get("error", "unknown error")
        original_goal: str = msg.get("original_goal", "")

        self._log.info("recovery.handle_failure", workflow_id=workflow_id, error=error)

        diagnosis = await self._diagnose(failed_task, error)
        corrected_task = diagnosis.get("corrected_task", failed_task)

        self._log.info(
            "recovery.diagnosis",
            failure_class=diagnosis.get("failure_class"),
            root_cause=diagnosis.get("root_cause"),
            workflow_id=workflow_id,
        )

        # Send corrected task back to planner as a new request
        await self.publish(Subjects.PLANNER_REQUEST, {
            "goal": original_goal,
            "workflow_id": workflow_id,
            "hint_task": corrected_task,
            "recovery": True,
        })

    async def handle_replan(self, msg: dict[str, Any]) -> None:
        # Recovery agent observes replan events for logging / metrics only.
        # The Planner handles the actual replanning.
        workflow_id: str = msg.get("workflow_id", "unknown")
        self._log.info("recovery.observed_replan", workflow_id=workflow_id)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _diagnose(self, failed_task: dict, error: str) -> dict[str, Any]:
        messages = [
            SystemMessage(content=DIAGNOSIS_PROMPT),
            HumanMessage(content=f"Failed task: {json.dumps(failed_task)}\nError: {error}"),
        ]
        try:
            response = await self._llm.ainvoke(messages)
            return json.loads(response.content.strip())
        except Exception as exc:  # noqa: BLE001
            self._log.warning("recovery.diagnosis_error", error=str(exc))
            return {
                "failure_class": "unknown",
                "root_cause": str(exc),
                "corrected_task": failed_task,
            }
