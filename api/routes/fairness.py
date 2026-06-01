"""
api/routes/fairness.py – Fairness & Bias metrics endpoints.

Computes disparity metrics across demographic groups using existing
placement and children data. No new columns required – uses gender,
special_needs, and emergency_level which already exist.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from api.db import get_pool

logger = structlog.get_logger()
router = APIRouter(tags=["fairness"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _calculate_disparity(
    placements: list[dict[str, Any]], group_by_field: str
) -> float:
    """
    Compute the max–min disparity in high-risk rate across demographic groups.

    A disparity of 0.05 means the highest-risk group has a 5 percentage-point
    higher rate of high-risk placements than the lowest-risk group.
    """
    groups: dict[str, dict[str, int]] = {}
    for p in placements:
        raw = p.get(group_by_field)
        group = str(raw) if raw is not None else "unknown"
        if group not in groups:
            groups[group] = {"total": 0, "high_risk": 0}
        groups[group]["total"] += 1
        if float(p.get("risk_score") or 0) > 70:
            groups[group]["high_risk"] += 1

    if len(groups) < 2:
        return 0.0

    rates = [
        g["high_risk"] / g["total"] if g["total"] > 0 else 0.0
        for g in groups.values()
    ]
    return round(max(rates) - min(rates), 4)


def _group_breakdown(
    placements: list[dict[str, Any]], group_by_field: str
) -> list[dict[str, Any]]:
    """Return per-group counts and high-risk rates for a given field."""
    groups: dict[str, dict[str, int]] = {}
    for p in placements:
        raw = p.get(group_by_field)
        group = str(raw) if raw is not None else "unknown"
        if group not in groups:
            groups[group] = {"total": 0, "high_risk": 0}
        groups[group]["total"] += 1
        if float(p.get("risk_score") or 0) > 70:
            groups[group]["high_risk"] += 1

    return [
        {
            "group": k,
            "total": v["total"],
            "high_risk": v["high_risk"],
            "high_risk_rate": round(
                v["high_risk"] / v["total"] if v["total"] > 0 else 0.0, 4
            ),
        }
        for k, v in sorted(groups.items())
    ]


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/api/fairness/metrics")
async def get_fairness_metrics(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Compute fairness metrics from existing placements.

    Uses gender, special_needs, and emergency_level as demographic proxies
    (the columns that actually exist in the children table).
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.workflow_id,
                p.risk_score,
                p.status,
                c.gender,
                c.special_needs,
                c.emergency_level,
                c.age
            FROM placements p
            JOIN children c ON c.child_id = p.child_id
            WHERE p.status IN ('active', 'approved', 'pending', 'pending_supervisor')
            """
        )

    placements = [dict(r) for r in rows]

    # Compute disparity for each demographic axis
    gender_bias = _calculate_disparity(placements, "gender")
    special_needs_bias = _calculate_disparity(placements, "special_needs")
    emergency_bias = _calculate_disparity(placements, "emergency_level")

    threshold = 0.05  # 5 percentage-point acceptable disparity

    all_biases = [gender_bias, special_needs_bias, emergency_bias]
    overall_status = "PASS" if all(b <= threshold for b in all_biases) else "REVIEW"

    return {
        "gender_bias": gender_bias,
        "special_needs_bias": special_needs_bias,
        "emergency_level_bias": emergency_bias,
        "threshold": threshold,
        "status": overall_status,
        "total_placements": len(placements),
        "last_calculated": datetime.now().isoformat(),
        "breakdowns": {
            "gender": _group_breakdown(placements, "gender"),
            "special_needs": _group_breakdown(placements, "special_needs"),
            "emergency_level": _group_breakdown(placements, "emergency_level"),
        },
    }


@router.get("/api/fairness/shap/{workflow_id}")
async def get_shap_explanation(
    workflow_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return SHAP-like feature importance explanation for a placement recommendation.

    Reads from placement_predictions which already stores feature_importance.
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        prediction = await conn.fetchrow(
            """
            SELECT feature_importance, top_matches, score, confidence
            FROM placement_predictions
            WHERE workflow_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            workflow_id,
        )

    if not prediction:
        raise HTTPException(
            status_code=404,
            detail=f"No prediction found for workflow {workflow_id}",
        )

    feature_importance = prediction.get("feature_importance") or []
    if isinstance(feature_importance, str):
        try:
            feature_importance = json.loads(feature_importance)
        except (json.JSONDecodeError, TypeError):
            feature_importance = []

    top_matches = prediction.get("top_matches") or []
    if isinstance(top_matches, str):
        try:
            top_matches = json.loads(top_matches)
        except (json.JSONDecodeError, TypeError):
            top_matches = []

    _feature_descriptions: dict[str, str] = {
        "age_match": "Child's age is within the family's accepted range",
        "age_gap": "Gap between child's age and family's maximum age",
        "location_match": "Family is in the child's preferred location",
        "special_needs_match": "Family is trained for the child's special needs",
        "language_match": "Family speaks the child's language(s)",
        "capacity": "Family has sufficient available capacity",
        "experience_high": "Family has high fostering experience",
        "experience_medium": "Family has medium fostering experience",
        "experience_low": "Family has low fostering experience",
        "family_past_success_rate": "Family's historical placement success rate",
        "sibling_match": "Family can accommodate the child's sibling group",
    }

    enriched_features = [
        {
            "feature": fi.get("feature", ""),
            "importance": fi.get("importance", 0),
            "description": _feature_descriptions.get(
                fi.get("feature", ""),
                fi.get("feature", "").replace("_", " ").title(),
            ),
        }
        for fi in sorted(
            feature_importance, key=lambda x: x.get("importance", 0), reverse=True
        )[:8]
    ]

    return {
        "workflow_id": workflow_id,
        "match_score": prediction.get("score"),
        "confidence_score": prediction.get("confidence"),
        "feature_importance": enriched_features,
        "top_matches": top_matches[:3],
    }
