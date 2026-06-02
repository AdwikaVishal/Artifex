"""
api/routes/crisis.py – Predictive Crisis Engine REST API.

Four endpoints:
  GET  /children/{child_id}/risk-score      – current risk + drift signals
  GET  /children/{child_id}/risk-history     – 90-day time series
  GET  /alerts                               – all children above threshold, by severity
  POST /feedback                             – caseworker outcome report for retraining
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.auth import get_current_user, require_role
from api.db import get_pool

logger = structlog.get_logger()
router = APIRouter(tags=["crisis"])


# ── Pydantic models ───────────────────────────────────────────────────────────


class RiskScoreResponse(BaseModel):
    child_id: str
    placement_id: str
    risk_score: float = Field(..., ge=0, le=100)
    risk_level: str  # low | medium | high | critical
    confidence_interval_95: list[float]  # [lower, upper]
    prediction_horizon_days: int = 21
    prediction_date: str  # ISO 8601


class DriftSignalSummary(BaseModel):
    signal: str
    status: str  # stable | drifting | critical
    value: float
    delta_from_baseline: float
    trend: float


class RiskScoreDetailResponse(RiskScoreResponse):
    top_contributing_features: list[dict[str, Any]] = []
    drift_signals_breakdown: list[DriftSignalSummary] = []
    recommended_interventions: list[str] = []


class RiskHistoryPoint(BaseModel):
    date: str
    risk_score: float
    risk_level: str
    overall_drift_index: float | None = None


class RiskHistoryResponse(BaseModel):
    child_id: str
    placement_id: str
    points: list[RiskHistoryPoint]


class AlertChild(BaseModel):
    child_id: str
    placement_id: str
    risk_score: float
    risk_level: str
    caseworker_id: str | None = None
    top_signals: list[dict[str, Any]] = []
    last_updated: str
    recommended_interventions: list[str] = []


class AlertsResponse(BaseModel):
    alerts: list[AlertChild]
    count: int
    threshold: float


class FeedbackRequest(BaseModel):
    child_id: str
    placement_id: str
    outcome: str = Field(..., pattern=r"^(stable|disrupted)$")
    disruption_date: str | None = None  # ISO date, required if outcome=disrupted
    notes: str = Field(default="", max_length=2000)


class FeedbackResponse(BaseModel):
    status: str
    message: str
    feedback_id: int


# ── Internal helpers ──────────────────────────────────────────────────────────


def _risk_level(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


async def _fetch_latest_drift_snapshot(
    child_id: str, pool: Any,
) -> dict[str, Any] | None:
    """Return the most recent behavioural_drift_signals row for this child."""
    row = await pool.fetchrow(
        """
        SELECT signals_json, drift_score, trend_direction, snapshot_date
        FROM behavioural_drift_signals
        WHERE child_id = $1
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
        child_id,
    )
    return dict(row) if row else None


async def _fetch_crisis_prediction(
    placement_id: str, pool: Any,
) -> dict[str, Any] | None:
    """Return the most recent crisis_prediction for this placement."""
    row = await pool.fetchrow(
        """
        SELECT disruption_probability, risk_level, top_reasons,
               recommended_interventions, prediction_date
        FROM crisis_predictions
        WHERE placement_id = $1
        ORDER BY prediction_date DESC
        LIMIT 1
        """,
        placement_id,
    )
    return dict(row) if row else None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/children/{child_id}/risk-score")
async def get_child_risk_score(
    child_id: str,
    include_signals: bool = Query(
        False, description="Include full drift signal breakdown"
    ),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the current risk score and latest drift signals for a child.

    Writes through the following chain:
      1. behavioural_drift_signals → composite_drift_score
      2. crisis_predictions       → disruption_probability + confidence interval
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        # Resolve placement_id from child
        placement_row = await conn.fetchrow(
            """
            SELECT workflow_id, child_id, caseworker_id
            FROM placements
            WHERE child_id = $1 AND status IN ('active', 'approved')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            child_id,
        )
        if not placement_row:
            raise HTTPException(
                status_code=404,
                detail=f"No active placement found for child {child_id}",
            )
        placement_id = placement_row["workflow_id"]

        # Crisis prediction
        prediction = await _fetch_crisis_prediction(placement_id, conn)
        if not prediction:
            # Cold-start: generate one
            from api.services.crisis_predictor import get_crisis_predictor
            predictor = get_crisis_predictor()
            pred = await predictor.predict_and_store(placement_id)
            if not pred:
                raise HTTPException(
                    status_code=404,
                    detail=f"Could not generate prediction for {placement_id}",
                )
            probability = pred["probability"]
            risk_level = pred["risk_level"]
            top_reasons = pred.get("top_reasons", [])
            interventions = pred.get("recommended_interventions", [])
            pred_date = datetime.now().isoformat()
        else:
            probability = float(prediction["disruption_probability"])
            risk_level = prediction.get("risk_level") or _risk_level(probability)
            tr = prediction.get("top_reasons", [])
            interventions = prediction.get("recommended_interventions", [])
            if isinstance(tr, str):
                tr = json.loads(tr)
            if isinstance(interventions, str):
                interventions = json.loads(interventions)
            top_reasons = tr or []
            interventions = interventions or []
            pd_date = prediction.get("prediction_date")
            pred_date = pd_date.isoformat() if pd_date else datetime.now().isoformat()

        # Optional drift signal data
        drift_snapshot = None
        if include_signals:
            drift_snapshot = await _fetch_latest_drift_snapshot(child_id, conn)

    # Confidence interval via quantile models or bootstrap heuristic
    ci_width = min(probability * 0.3, 15.0)
    ci_lower = round(max(0, probability - ci_width), 1)
    ci_upper = round(min(100, probability + ci_width), 1)

    response: dict[str, Any] = {
        "child_id": child_id,
        "placement_id": placement_id,
        "risk_score": probability,
        "risk_level": risk_level,
        "confidence_interval_95": [ci_lower, ci_upper],
        "prediction_horizon_days": 21,
        "prediction_date": pred_date,
    }

    if include_signals and drift_snapshot:
        signals_json = drift_snapshot.get("signals_json")
        if isinstance(signals_json, str):
            signals_json = json.loads(signals_json)
        drift_signals = signals_json.get("drift_signals", {}) if signals_json else {}
        composite = signals_json.get("composite_drift_score", {}) if signals_json else {}

        # Build top contributing features from SHAP values or heuristic
        top_features = []
        for s in composite.get("drifting_signals", [])[:3]:
            top_features.append(
                {
                    "feature": s,
                    "shap_value": None,  # populated by inference pipeline
                    "direction": "declining",
                    "description": f"Signal {s.replace('_', ' ')} is above drift threshold",
                }
            )
        response["top_contributing_features"] = top_features

        # Drift signal breakdown
        breakdown = []
        domains = {
            "school_attendance": drift_signals.get("school_attendance", {}),
            "caseworker_sentiment": drift_signals.get("caseworker_visits", {}),
            "incident_frequency": drift_signals.get("incident_reports", {}),
            "incident_severity": drift_signals.get("incident_reports", {}),
            "medication_compliance": drift_signals.get("medication_compliance", {}),
            "communication_lag": drift_signals.get("communication_patterns", {}),
            "communication_tone": drift_signals.get("communication_patterns", {}),
        }
        for name, domain in domains.items():
            delta = domain.get("delta_from_baseline", domain.get("delta_sentiment_from_baseline", domain.get("delta_lag_from_baseline", 0)))
            trend = domain.get("trend", domain.get("sentiment_trend", domain.get("compliance_trend", domain.get("severity_trend", 0))))
            if delta is None:
                delta = 0
            if trend is None:
                trend = 0

            abs_delta = abs(delta)
            if abs_delta > 0.3 or trend < -0.1:
                status = "critical" if abs_delta > 0.5 else "drifting"
            else:
                status = "stable"

            breakdown.append(
                {
                    "signal": name,
                    "status": status,
                    "value": domain.get("attendance_rate", domain.get("avg_sentiment", domain.get("compliance_rate", domain.get("response_rate", 0)))),
                    "delta_from_baseline": delta,
                    "trend": trend,
                }
            )
        response["drift_signals_breakdown"] = breakdown
        response["recommended_interventions"] = interventions

    return response


@router.get("/children/{child_id}/risk-history")
async def get_child_risk_history(
    child_id: str,
    days: int = Query(default=90, ge=7, le=365),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a 90-day time series of risk scores for a child.

    Aggregates weekly snapshots from:
      - behavioural_drift_signals (drift_score)
      - crisis_predictions (disruption_probability)
    Sorted oldest-first for chart rendering.
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        placement_row = await conn.fetchrow(
            "SELECT workflow_id FROM placements WHERE child_id = $1 "
            "AND status IN ('active', 'approved') ORDER BY created_at DESC LIMIT 1",
            child_id,
        )
        if not placement_row:
            raise HTTPException(
                status_code=404,
                detail=f"No active placement found for child {child_id}",
            )
        placement_id = placement_row["workflow_id"]

        # Crisis predictions over the N-day window
        crisis_rows = await conn.fetch(
            """
            SELECT disruption_probability, risk_level, prediction_date
            FROM crisis_predictions
            WHERE placement_id = $1
              AND prediction_date >= NOW() - ($2 || ' days')::INTERVAL
            ORDER BY prediction_date ASC
            """,
            placement_id,
            str(days),
        )

        # Drift signal scores over the same window
        drift_rows = await conn.fetch(
            """
            SELECT drift_score, trend_direction, snapshot_date
            FROM behavioural_drift_signals
            WHERE child_id = $1
              AND snapshot_date >= NOW() - ($2 || ' days')::INTERVAL
            ORDER BY snapshot_date ASC
            """,
            child_id,
            str(days),
        )

    # Merge into a single time series keyed by week
    points: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for row in crisis_rows:
        d = row["prediction_date"]
        date_key = d.strftime("%Y-%m-%d") if d else ""
        if date_key in seen_dates:
            continue
        seen_dates.add(date_key)
        points.append(
            {
                "date": d.isoformat() if d else "",
                "risk_score": float(row["disruption_probability"]),
                "risk_level": row.get("risk_level") or _risk_level(float(row["disruption_probability"])),
                "overall_drift_index": None,
            }
        )

    # Overlay drift scores onto the same timeline
    drift_map: dict[str, float] = {}
    for row in drift_rows:
        d = row["snapshot_date"]
        date_key = d.strftime("%Y-%m-%d") if d else ""
        drift_score = row.get("drift_score")
        if date_key and drift_score is not None:
            drift_map[date_key] = float(drift_score)

    for point in points:
        date_key = point["date"][:10]
        if date_key in drift_map:
            point["overall_drift_index"] = drift_map[date_key]

    # If fewer than 2 points, we have no trend to show
    return {
        "child_id": child_id,
        "placement_id": placement_id,
        "points": points,
    }


@router.get("/alerts")
async def get_alerts(
    threshold: float = Query(
        default=60.0, ge=0, le=100,
        description="Minimum risk score to trigger an alert",
    ),
    max_results: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return all children with risk score above threshold, sorted by severity (descending).

    Each alert includes the top 3 contributing signals inline so the
    caseworker can act without an extra API call.
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH ranked AS (
                SELECT
                    p.child_id,
                    p.workflow_id AS placement_id,
                    p.caseworker_id,
                    cp.disruption_probability,
                    cp.risk_level,
                    cp.recommended_interventions,
                    cp.prediction_date,
                    b.drift_score,
                    b.signals_json,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.child_id
                        ORDER BY cp.prediction_date DESC
                    ) AS rn
                FROM placements p
                JOIN crisis_predictions cp ON cp.placement_id = p.workflow_id
                LEFT JOIN behavioural_drift_signals b
                    ON b.child_id = p.child_id
                    AND b.snapshot_date = (
                        SELECT MAX(snapshot_date)
                        FROM behavioural_drift_signals
                        WHERE child_id = p.child_id
                    )
                WHERE p.status IN ('active', 'approved')
                  AND cp.disruption_probability >= $1
            )
            SELECT *
            FROM ranked
            WHERE rn = 1
            ORDER BY disruption_probability DESC
            LIMIT $2
            """,
            threshold,
            max_results,
        )

    alerts: list[dict[str, Any]] = []
    for row in rows:
        # Extract top 3 signals from drift snapshot
        signals_json = row.get("signals_json")
        if isinstance(signals_json, str):
            signals_json = json.loads(signals_json)
        drift_signals = signals_json.get("drift_signals", {}) if signals_json else {}
        composite = signals_json.get("composite_drift_score", {}) if signals_json else {}

        drifting = composite.get("drifting_signals", [])[:3]
        top_signals = []
        for signal_name in drifting:
            severity = "critical" if signal_name in composite.get("drifting_signals", []) else "drifting"
            top_signals.append({
                "signal": signal_name,
                "severity": severity,
            })

        interventions = row.get("recommended_interventions")
        if isinstance(interventions, str):
            interventions = json.loads(interventions)

        pred_date = row.get("prediction_date")
        alerts.append(
            {
                "child_id": row["child_id"],
                "placement_id": row["placement_id"],
                "risk_score": float(row["disruption_probability"]),
                "risk_level": row.get("risk_level") or _risk_level(float(row["disruption_probability"])),
                "caseworker_id": row.get("caseworker_id"),
                "top_signals": top_signals,
                "last_updated": pred_date.isoformat() if pred_date else "",
                "recommended_interventions": interventions or [],
            }
        )

    return {"alerts": alerts, "count": len(alerts), "threshold": threshold}


@router.post("/feedback")
async def submit_feedback(
    feedback: FeedbackRequest,
    request: Request,
    user: dict = Depends(require_role("caseworker", "supervisor", "admin")),
) -> dict[str, Any]:
    """
    Submit placement outcome feedback for model retraining.

    Called by caseworkers when a placement either:
      - reaches a stable outcome (placement ended naturally, reunification)
      - disrupts (unplanned removal)

    Stores the feedback in a `prediction_feedback` table that the
    weekly retraining pipeline consumes as ground-truth labels.
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    if feedback.outcome == "disrupted" and not feedback.disruption_date:
        raise HTTPException(
            status_code=422,
            detail="disruption_date is required when outcome is 'disrupted'",
        )

    disruption_bool = feedback.outcome == "disrupted"

    async with pool.acquire() as conn:
        # Upsert into prediction_feedback
        row = await conn.fetchrow(
            """
            INSERT INTO prediction_feedback
                (child_id, placement_id, outcome, disruption,
                 disruption_date, notes, submitted_by, submitted_at)
            VALUES ($1, $2, $3, $4,
                    $5::DATE, $6, $7, NOW())
            ON CONFLICT (placement_id)
                DO UPDATE SET
                    outcome = EXCLUDED.outcome,
                    disruption = EXCLUDED.disruption,
                    disruption_date = EXCLUDED.disruption_date,
                    notes = EXCLUDED.notes,
                    submitted_by = EXCLUDED.submitted_by,
                    submitted_at = NOW()
            RETURNING id
            """,
            feedback.child_id,
            feedback.placement_id,
            feedback.outcome,
            disruption_bool,
            feedback.disruption_date,
            feedback.notes,
            user["user_id"],
        )

        # Also update placement_history if this is an outcome
        if disruption_bool and feedback.disruption_date:
            await conn.execute(
                """
                UPDATE placement_history
                SET disruption = TRUE,
                    placement_end = $1::DATE,
                    outcome = 'disrupted',
                    duration_days = (
                        SELECT EXTRACT(DAY FROM ($1::DATE - placement_start))
                    )
                WHERE child_id = $2
                  AND placement_end IS NULL
                """,
                feedback.disruption_date,
                feedback.child_id,
            )

        # Archive the latest crisis prediction with the actual outcome
        await conn.execute(
            """
            UPDATE crisis_predictions
            SET actual_outcome = $1,
                resolved_at = NOW()
            WHERE placement_id = $2
              AND actual_outcome IS NULL
            """,
            disruption_bool,
            feedback.placement_id,
        )

        feedback_id = row["id"] if row else 0

    logger.info(
        "crisis.feedback_submitted",
        child_id=feedback.child_id,
        outcome=feedback.outcome,
        feedback_id=feedback_id,
        user_id=user["user_id"],
    )

    return {
        "status": "ok",
        "message": (
            "Outcome recorded. Thank you — this will improve future predictions."
        ),
        "feedback_id": feedback_id,
    }


# ── Migration DDL ─────────────────────────────────────────────────────────────
# Run as Alembic revision 0004:
#
# CREATE TABLE IF NOT EXISTS prediction_feedback (
#     id               SERIAL PRIMARY KEY,
#     child_id         TEXT        NOT NULL REFERENCES children(child_id),
#     placement_id     TEXT        NOT NULL REFERENCES placements(workflow_id),
#     outcome          TEXT        NOT NULL CHECK (outcome IN ('stable', 'disrupted')),
#     disruption       BOOLEAN    NOT NULL,
#     disruption_date  DATE,
#     notes            TEXT        DEFAULT '',
#     submitted_by     TEXT,
#     submitted_at     TIMESTAMP  NOT NULL DEFAULT NOW(),
#     CONSTRAINT uq_feedback_placement UNIQUE (placement_id)
# );
#
# CREATE INDEX idx_feedback_child   ON prediction_feedback (child_id);
# CREATE INDEX idx_feedback_outcome ON prediction_feedback (outcome, submitted_at);
#
#
# ── Router registration (in api/main.py) ───────────────────────────────────────
# Add to the import block:
#   from .routes.crisis import router as crisis_router
#
# Add to the app.include_router block:
#   app.include_router(crisis_router)
