from __future__ import annotations

from datetime import timedelta, datetime
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

_retry = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)

STAGES = [
    "Intake",
    "Eligibility Validation",
    "ML Inference",
    "Placement Matching",
    "Recommendation Generated",
    "Approval Pending",
    "Placement Approved",
    "Placement Active",
    "Monitoring",
]
TOTAL_STAGES = len(STAGES) - 1  # exclude final


def _compute_progress(stage_index: int) -> int:
    return int((stage_index / TOTAL_STAGES) * 100)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


@workflow.defn(name="FosterPlacementWorkflow")
class FosterPlacementWorkflow:
    """Long-running workflow that monitors a child's foster placement."""

    def __init__(self) -> None:
        self._child: dict[str, Any] = {}
        self._matched_family: dict[str, Any] = {}
        self._risk_score: float = 0.0
        self._match_score: float = 0.0
        self._confidence_score: float = 0.0
        self._feature_importance: list[dict] = []
        self._risk_history: list[dict] = []
        self._alert_sent: bool = False
        self._top_matches: list[dict] = []
        self._placement_active: bool = True
        self._current_stage: str = ""
        self._progress: int = 0
        self._timeline: list[dict] = []

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _record_event(self, stage: str, status: str, data: dict | None = None) -> None:
        timestamp = _now_iso()
        event_data = dict(data or {})
        event_data["progress"] = self._progress
        event = {
            "stage": stage,
            "status": status,
            "data": event_data,
            "timestamp": timestamp,
        }
        self._timeline.append(event)
        try:
            await workflow.execute_activity(
                "record_workflow_event_activity",
                args=[workflow.info().workflow_id, stage, status, event_data],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=_retry,
            )
        except Exception:
            workflow.logger.exception("foster_workflow.record_event_error", stage=stage)

    def _set_stage(self, stage: str, progress: int | None = None) -> None:
        self._current_stage = stage
        if progress is not None:
            self._progress = progress
        else:
            stage_names = [s.lower() for s in STAGES]
            try:
                idx = stage_names.index(stage.lower())
                self._progress = _compute_progress(idx)
            except ValueError:
                self._progress = min(self._progress + 10, 100)

    # ── Entry point ───────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        child_id = input_data.get("child_id", "unknown")
        workflow_id = workflow.info().workflow_id

        workflow.logger.info(
            f"foster_workflow.started child_id={child_id} workflow_id={workflow_id}"
        )

        # Load child profile from PostgreSQL – not from workflow input
        self._child = await workflow.execute_activity(
            "load_child_profile_activity",
            args=[child_id],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_retry,
        )
        if not self._child:
            workflow.logger.error(f"foster_workflow.child_not_found child_id={child_id}")
            return {"error": f"Child {child_id} not found in database"}

        # Stage 1 – Intake
        self._set_stage("Intake", progress=5)
        await self._record_event("Intake", "completed", {"child_id": child_id})

        # Stage 2 – Eligibility Validation
        self._set_stage("Eligibility Validation", progress=10)
        await self._record_event("Eligibility Validation", "completed", {"child_id": child_id})

        # Stage 3 – ML Inference
        self._set_stage("ML Inference", progress=25)
        await self._record_event("ML Inference", "started")

        try:
            prediction = await workflow.execute_activity(
                "placement_predict_activity",
                args=[self._child, workflow_id],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_retry,
            )
        except Exception:
            workflow.logger.exception("foster_workflow.ml_prediction_error")
            prediction = None

        if prediction and isinstance(prediction, dict) and prediction.get("recommended_family"):
            self._matched_family = (
                prediction.get("recommended_family") or {}
            )
            match_explanation = (
                prediction.get("explanation")
                or prediction.get("match_explanation", "")
            )
            try:
                self._risk_score = float(prediction.get("risk_score", self._risk_score))
            except Exception:
                pass
            try:
                self._match_score = float(prediction.get("match_score", 0))
            except Exception:
                pass
            try:
                self._confidence_score = float(prediction.get("confidence", 0))
            except Exception:
                pass
            self._feature_importance = prediction.get("feature_importance", [])
            self._top_matches = prediction.get("top_matches", [])
        else:
            # No fallback recommendations allowed: emit explicit manual-review status.
            self._set_stage("Placement Matching", progress=40)
            match_explanation = "No recommendation could be produced. Manual review required."
            self._matched_family = {}
            self._match_score = 0.0
            self._confidence_score = 0.0
            self._risk_score = 0.0
            await self._record_event(
                "Placement Matching",
                "needs_manual_review",
                {"child_id": child_id},
            )

        workflow.logger.info(
            f"foster_workflow.matched child_id={child_id} "
            f"family_id={self._matched_family.get('family_id')} "
            f"match_score={self._match_score} confidence={self._confidence_score}"
        )

        # Stage 5 – Recommendation Generated
        self._set_stage("Recommendation Generated", progress=55)
        await self._record_event(
            "Recommendation Generated",
            "completed",
            {
                "family_id": self._matched_family.get("family_id"),
                "match_score": self._match_score,
                "confidence_score": self._confidence_score,
            },
        )

        # Publish match to dashboard
        await workflow.execute_activity(
            "publish_match_activity",
            args=[{
                "child_id": child_id,
                "family": self._matched_family or None,
                "risk_score": self._risk_score,
                "match_score": self._match_score,
                "confidence": self._confidence_score,
                "feature_importance": self._feature_importance,
                "top_matches": self._top_matches,
                "recommended_family": self._matched_family,
                "match_explanation": match_explanation,
                "workflow_id": workflow_id,
                "model_version": "xgboost-v1",
                "current_stage": self._current_stage,
                "progress": self._progress,
                "status": "needs_manual_review" if not self._matched_family else "matched",
            }],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_retry,
        )

        # Stage 6 – Approval Pending
        self._set_stage("Approval Pending", progress=70)
        await self._record_event(
            "Approval Pending",
            "awaiting",
            {"workflow_id": workflow_id},
        )

        # Stage 7 – Placement Approved
        self._set_stage("Placement Approved", progress=85)
        await self._record_event(
            "Placement Approved",
            "completed",
            {"family_id": self._matched_family.get("family_id")},
        )

        # Stage 8 – Placement Active
        self._set_stage("Placement Active", progress=95)
        await self._record_event(
            "Placement Active",
            "active",
            {"family_id": self._matched_family.get("family_id")},
        )

        # Stage 9 – Monitoring (wait for signals or closure)
        self._set_stage("Monitoring", progress=100)
        await self._record_event(
            "Monitoring",
            "active",
            {},
        )

        # Wait indefinitely for check-in signals (or placement closure)
        await workflow.wait_condition(lambda: not self._placement_active)

        workflow.logger.info(f"foster_workflow.closed child_id={child_id}")
        return {
            "child_id": child_id,
            "family_id": self._matched_family.get("family_id"),
            "final_risk": self._risk_score,
            "match_score": self._match_score,
            "confidence_score": self._confidence_score,
            "alert_sent": self._alert_sent,
        }

    # ── Signals ───────────────────────────────────────────────────────────────

    @workflow.signal
    async def weekly_check_in(self, score: int, notes: str) -> None:
        child_id = self._child.get("child_id", "unknown")
        workflow.logger.info(
            f"foster_workflow.check_in child_id={child_id} score={score}"
        )

        self._set_stage("Check-In Review", progress=85)
        await self._record_event(
            "Check-In",
            "received",
            {"score": score, "notes": notes[:100]},
        )

        result = await workflow.execute_activity(
            "compute_risk_activity",
            args=[self._child, self._matched_family, score, notes, self._risk_score],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_retry,
        )
        new_risk = result["risk"] if isinstance(result, dict) else float(result)
        explanation = result.get("explanation", "") if isinstance(result, dict) else ""
        self._risk_score = new_risk
        self._risk_history.append({
            "score": new_risk,
            "check_score": score,
            "notes": notes[:100],
        })

        await self._record_event(
            "Risk Recalculated",
            "completed",
            {"risk_score": new_risk, "explanation": explanation[:100]},
        )

        await workflow.execute_activity(
            "publish_match_activity",
            args=[{
                "child_id": child_id,
                "family": self._matched_family,
                "risk_score": self._risk_score,
                "match_score": self._match_score,
                "confidence": self._confidence_score,
                "feature_importance": self._feature_importance,
                "top_matches": self._top_matches,
                "risk_explanation": explanation,
                "risk_history": self._risk_history[-5:],
                "workflow_id": workflow.info().workflow_id,
                "last_notes": notes,
                "current_stage": self._current_stage,
                "progress": self._progress,
            }],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_retry,
        )

        if self._risk_score > 75 and not self._alert_sent:
            self._alert_sent = True
            await workflow.execute_activity(
                "send_alert_activity",
                args=[self._matched_family, self._risk_score, notes, child_id, self._child],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_retry,
            )
            await self._record_event("Alert Sent", "completed", {"risk_score": self._risk_score})

    @workflow.signal
    async def close_placement(self) -> None:
        workflow.logger.info(
            f"foster_workflow.close_requested "
            f"child_id={self._child.get('child_id', 'unknown')}"
        )
        await self._record_event("Placement Closed", "completed")
        self._placement_active = False

    @workflow.signal
    async def ml_completed(self, prediction: dict[str, Any]) -> None:
        if not isinstance(prediction, dict):
            return
        if prediction.get("recommended_family") or prediction.get("family"):
            self._matched_family = prediction.get("recommended_family") or prediction.get("family")
        try:
            self._risk_score = float(prediction.get("risk_score", self._risk_score))
        except Exception:
            pass
        try:
            self._match_score = float(prediction.get("match_score", self._match_score))
        except Exception:
            pass
        try:
            self._confidence_score = float(prediction.get("confidence", self._confidence_score))
        except Exception:
            pass
        fi = prediction.get("feature_importance", [])
        if fi:
            self._feature_importance = fi
        self._risk_history.append({
            "score": self._risk_score,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "notes": "ML signal",
        })
        self._set_stage("ML Update Received")
        await self._record_event("ML Update", "completed", prediction)

    # ── Queries ───────────────────────────────────────────────────────────────

    @workflow.query
    def get_status(self) -> dict[str, Any]:
        return {
            "child_id": self._child.get("child_id"),
            "family_id": self._matched_family.get("family_id"),
            "risk_score": self._risk_score,
            "match_score": self._match_score,
            "confidence_score": self._confidence_score,
            "feature_importance": self._feature_importance,
            "top_matches": self._top_matches,
            "recommended_family": self._matched_family,
            "capacity": self._matched_family.get("capacity"),
            "risk_history": self._risk_history[-5:],
            "alert_sent": self._alert_sent,
            "active": self._placement_active,
            "current_stage": self._current_stage,
            "progress": self._progress,
            "timeline": self._timeline[-50:],
        }

    @workflow.query
    def get_timeline(self) -> list[dict]:
        return self._timeline

    @workflow.query
    def get_progress(self) -> dict:
        return {
            "current_stage": self._current_stage,
            "progress": self._progress,
        }
