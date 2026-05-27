"""
foster_workflow.py – Durable Temporal workflow for a single child's placement.

Lifecycle:
  1. Starts when a child referral arrives.
  2. Runs match_child_activity to find a suitable family.
  3. Publishes the match to the live dashboard via publish_match_activity.
  4. Waits indefinitely for weekly_check_in signals.
  5. On each check-in, recomputes disruption risk and fires an alert if > 75%.

The workflow survives crashes – Temporal replays the event history on restart.
All logging uses workflow.logger (sandbox-safe, no threading.Lock).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

_retry = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn(name="FosterPlacementWorkflow")
class FosterPlacementWorkflow:
    """Long-running workflow that monitors a child's foster placement."""

    def __init__(self) -> None:
        self._child: dict[str, Any] = {}
        self._matched_family: dict[str, Any] = {}
        self._risk_score: float = 0.0
        self._risk_history: list[dict] = []   # [{score, timestamp, notes}]
        self._alert_sent: bool = False
        self._placement_active: bool = True

    # ── Entry point ───────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, child: dict[str, Any]) -> dict[str, Any]:
        self._child = child
        child_id = child.get("child_id", "unknown")
        workflow_id = workflow.info().workflow_id

        workflow.logger.info(
            f"foster_workflow.started child_id={child_id} workflow_id={workflow_id}"
        )

        # Step 1 – match child to a family
        match_result = await workflow.execute_activity(
            "match_child_activity",
            args=[child],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_retry,
        )
        # match_child_activity now returns {family, score, explanation}
        if isinstance(match_result, dict) and "family" in match_result:
            self._matched_family   = match_result["family"]
            match_explanation      = match_result.get("explanation", "")
        else:
            # backward-compat: old activity returned the family dict directly
            self._matched_family   = match_result
            match_explanation      = ""

        workflow.logger.info(
            f"foster_workflow.matched child_id={child_id} "
            f"family_id={self._matched_family.get('family_id')}"
        )

        # Step 2 – push match to the live dashboard
        await workflow.execute_activity(
            "publish_match_activity",
            args=[{
                "child_id":          child_id,
                "family":            self._matched_family,
                "risk_score":        self._risk_score,
                "match_explanation": match_explanation,
                "workflow_id":       workflow_id,
            }],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_retry,
        )

        # Step 3 – wait forever for check-in signals (or placement closure)
        await workflow.wait_condition(lambda: not self._placement_active)

        workflow.logger.info(f"foster_workflow.closed child_id={child_id}")
        return {
            "child_id":      child_id,
            "family_id":     self._matched_family.get("family_id"),
            "final_risk":    self._risk_score,
            "alert_sent":    self._alert_sent,
        }

    # ── Signals ───────────────────────────────────────────────────────────────

    @workflow.signal
    async def weekly_check_in(self, score: int, notes: str) -> None:
        """
        Called by FosterMonitorAgent when a foster parent submits a check-in.
        score: 1 (very bad) – 5 (excellent)
        notes: free-text observations
        """
        child_id = self._child.get("child_id", "unknown")
        workflow.logger.info(
            f"foster_workflow.check_in child_id={child_id} score={score}"
        )

        # Recompute risk – pass previous_risk for cumulative decay model
        result = await workflow.execute_activity(
            "compute_risk_activity",
            args=[self._child, self._matched_family, score, notes, self._risk_score],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_retry,
        )
        # compute_risk_activity now returns {"risk": float, "explanation": str}
        new_risk    = result["risk"] if isinstance(result, dict) else float(result)
        explanation = result.get("explanation", "") if isinstance(result, dict) else ""
        self._risk_score = new_risk
        self._risk_history.append({
            "score":       new_risk,
            "check_score": score,
            "notes":       notes[:100],
        })

        # Update dashboard with full context
        await workflow.execute_activity(
            "publish_match_activity",
            args=[{
                "child_id":        child_id,
                "family":          self._matched_family,
                "risk_score":      self._risk_score,
                "risk_explanation": explanation,
                "risk_history":    self._risk_history[-5:],   # last 5 entries
                "workflow_id":     workflow.info().workflow_id,
                "last_notes":      notes,
            }],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_retry,
        )

        # Alert if risk exceeds threshold and we haven't already alerted
        if self._risk_score > 75 and not self._alert_sent:
            self._alert_sent = True
            await workflow.execute_activity(
                "send_alert_activity",
                # Pass full child profile so the consortium has rich context
                args=[self._matched_family, self._risk_score, notes, child_id, self._child],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_retry,
            )

    @workflow.signal
    async def close_placement(self) -> None:
        """Signal to end the workflow (child reunified, aged out, etc.)."""
        workflow.logger.info(
            f"foster_workflow.close_requested "
            f"child_id={self._child.get('child_id', 'unknown')}"
        )
        self._placement_active = False

    # ── Queries ───────────────────────────────────────────────────────────────

    @workflow.query
    def get_status(self) -> dict[str, Any]:
        """Return current placement status (queryable without interrupting the workflow)."""
        return {
            "child_id":    self._child.get("child_id"),
            "family_id":   self._matched_family.get("family_id"),
            "risk_score":  self._risk_score,
            "risk_history": self._risk_history[-5:],
            "alert_sent":  self._alert_sent,
            "active":      self._placement_active,
        }
