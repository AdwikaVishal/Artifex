"""
api/routes/placements.py – Placement CRUD and approval endpoints.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import get_current_user, require_role
from api.db import (
    get_pool,
    get_all_placements,
    log_action,
    store_placement,
    store_prediction,
    store_workflow_event,
)
from api.dependencies import get_settings, get_temporal_client

logger = structlog.get_logger()
router = APIRouter(tags=["placements"])

# In-process placement cache (populated by NATS subscriber in main.py)
_api_latest_placements: list[dict[str, Any]] = []
_placements_lock_ref: Any = None  # asyncio.Lock set by main.py


def set_placement_store(store: list, lock: Any) -> None:
    """Called by main.py to share the in-process cache and lock."""
    global _api_latest_placements, _placements_lock_ref
    _api_latest_placements = store
    _placements_lock_ref = lock


# ── Pydantic models ───────────────────────────────────────────────────────────

class PlacementApproval(BaseModel):
    workflow_id: str
    approved: bool
    comment: str = ""


class WorkflowEventRequest(BaseModel):
    workflow_id: str
    stage: str
    status: str
    data: dict[str, Any] = {}


class MlInferenceLogRequest(BaseModel):
    workflow_id: str
    child_id: str
    payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    model_version: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/foster/placements")
async def get_placements() -> dict[str, Any]:
    """Return placement snapshot from PostgreSQL (50 most recent)."""
    placements = await get_all_placements()
    logger.info("placements.response", count=len(placements))
    return {"placements": placements, "count": len(placements)}


@router.post("/foster/internal/placement", include_in_schema=False)
async def receive_placement(placement: dict) -> dict[str, str]:
    """Internal endpoint called by publish_match_activity in the temporal-worker."""
    child_id = placement.get("child_id", "unknown")
    await store_placement(placement)
    wf_id = placement.get("workflow_id") or f"foster-{child_id}"
    try:
        await store_workflow_event(
            wf_id, stage="placement_matched", status="completed", data=placement
        )
    except Exception:  # noqa: BLE001
        logger.exception("api.receive_placement.store_event_error", workflow_id=wf_id)
    try:
        recommended = {"family": placement.get("family")}
        await store_prediction(
            wf_id, child_id, recommended,
            score=placement.get("match_score") or placement.get("risk_score"),
            confidence=placement.get("confidence"),
            model_version=placement.get("model_version"),
            feature_importance=placement.get("feature_importance"),
            risk_score=placement.get("risk_score"),
            top_matches=placement.get("top_matches"),
        )
    except Exception:  # noqa: BLE001
        logger.exception("api.receive_placement.store_prediction_error", workflow_id=wf_id)
    # Update in-process cache
    if _placements_lock_ref is not None:
        async with _placements_lock_ref:
            for i, p in enumerate(_api_latest_placements):
                if p.get("child_id") == child_id:
                    _api_latest_placements[i] = placement
                    break
            else:
                _api_latest_placements.append(placement)
            del _api_latest_placements[50:]
    logger.info("api.receive_placement", child_id=child_id)
    return {"status": "ok"}


@router.post("/foster/internal/workflow_event", include_in_schema=False)
async def receive_workflow_event(event: WorkflowEventRequest) -> dict[str, str]:
    """Internal endpoint called by record_workflow_event_activity."""
    try:
        await store_workflow_event(
            event.workflow_id, stage=event.stage, status=event.status, data=event.data
        )
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "api.receive_workflow_event.error",
            workflow_id=event.workflow_id, stage=event.stage, error=str(exc),
        )
        return {"status": "error", "detail": str(exc)}


@router.post("/foster/internal/ml_inference_log", include_in_schema=False)
async def receive_ml_inference_log(req: MlInferenceLogRequest) -> dict[str, str]:
    """Internal endpoint for placement_predict_activity to log ML inference."""
    from api.db import store_ml_inference_log  # noqa: PLC0415
    try:
        await store_ml_inference_log(
            req.workflow_id, req.child_id, req.payload, req.result, req.model_version
        )
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("api.ml_inference_log.error", workflow_id=req.workflow_id, error=str(exc))
        return {"status": "error", "detail": str(exc)}


@router.get("/api/pending_approvals")
async def get_pending_approvals() -> dict[str, Any]:
    """Return placements awaiting caseworker approval."""
    approvals: list[dict[str, Any]] = []
    pool = get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT p.*, c.age, c.gender,
                           c.emergency_level AS child_emergency_level
                    FROM placements p
                    LEFT JOIN children c ON c.child_id = p.child_id
                    WHERE p.status IN ('pending', 'pending_supervisor')
                    ORDER BY p.created_at DESC
                    """
                )
                for row in rows:
                    fj = row.get("family_json")
                    family: dict = {}
                    if fj:
                        family = json.loads(fj) if isinstance(fj, str) else (fj or {})
                    approvals.append({
                        "workflow_id":        row["workflow_id"],
                        "child_id":           row["child_id"],
                        "recommended_family": family.get("name") or family.get("family_id"),
                        "risk_score":         float(row.get("risk_score") or 0),
                        "status":             row["status"],
                        "emergency_level":    (
                            row.get("child_emergency_level")
                            or row.get("emergency_level", "normal")
                        ),
                        "created_at": (
                            row.get("created_at").isoformat()
                            if row.get("created_at") else None
                        ),
                    })
        except Exception:  # noqa: BLE001
            pass
    return {"approvals": approvals, "count": len(approvals)}


@router.post("/api/approve")
async def approve_placement(
    approval: PlacementApproval,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Approve or reject a recommended placement."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        placement_row = await conn.fetchrow(
            "SELECT risk_score, status FROM placements WHERE workflow_id = $1",
            approval.workflow_id,
        )
    if not placement_row:
        raise HTTPException(
            status_code=404, detail=f"Placement {approval.workflow_id} not found"
        )
    try:
        risk_score = float(placement_row["risk_score"] or 0)
    except (TypeError, ValueError):
        risk_score = 0.0
    role = user["role"]

    HIGH_RISK_THRESHOLD = 75.0
    if risk_score > HIGH_RISK_THRESHOLD and role == "caseworker" and approval.approved:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE placements SET status = 'pending_supervisor', "
                "supervisor_required = TRUE, caseworker_id = $2, notes = $3 "
                "WHERE workflow_id = $1",
                approval.workflow_id, user["user_id"], approval.comment,
            )
        await log_action(
            user_id=user["user_id"], role=role,
            action="APPROVE_PLACEMENT_ESCALATED",
            target_type="placement", target_id=approval.workflow_id,
            details={"risk_score": risk_score, "comment": approval.comment,
                     "reason": "high_risk_requires_supervisor"},
            request=request,
        )
        return {
            "status":  "pending_supervisor",
            "message": (
                f"Risk score {risk_score:.0f}% exceeds threshold – "
                "awaiting supervisor approval"
            ),
        }

    new_status = "approved" if approval.approved else "rejected"
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE placements SET status = $2, notes = $3 WHERE workflow_id = $1",
            approval.workflow_id, new_status, approval.comment,
        )
        await conn.execute(
            "UPDATE active_placements SET status = $2 WHERE workflow_id = $1",
            approval.workflow_id, new_status,
        )
        # Update workflow_status so dashboard reflects the change immediately
        await conn.execute(
            "INSERT INTO workflow_status (workflow_id, status, current_stage, progress, updated_at) "
            "VALUES ($1, $2, $3, $4, NOW()) "
            "ON CONFLICT (workflow_id) DO UPDATE SET "
            "  status = EXCLUDED.status, current_stage = EXCLUDED.current_stage, "
            "  progress = EXCLUDED.progress, updated_at = NOW()",
            approval.workflow_id,
            new_status,
            "placement_approved" if approval.approved else "placement_rejected",
            100 if approval.approved else 0,
        )
        if approval.approved:
            placement = await conn.fetchrow(
                "SELECT child_id, family_json FROM placements WHERE workflow_id = $1",
                approval.workflow_id,
            )
            if placement:
                fj = placement.get("family_json")
                family = json.loads(fj) if isinstance(fj, str) else (fj or {})
                family_id = family.get("family_id") or family.get("id")
                if family_id:
                    # placement_history has no unique constraint – plain INSERT
                    await conn.execute(
                        "INSERT INTO placement_history "
                        "  (child_id, family_id, placement_start, outcome, disruption, duration_days) "
                        "VALUES ($1, $2, NOW(), 'active', FALSE, 0)",
                        placement["child_id"], family_id,
                    )

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(approval.workflow_id)
        signal_name = "approve_placement" if approval.approved else "reject_placement"
        await handle.signal(signal_name, approval.comment)
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.approve.signal_error",
                       workflow_id=approval.workflow_id, error=str(exc))

    await log_action(
        user_id=user["user_id"], role=role,
        action="APPROVE_PLACEMENT" if approval.approved else "REJECT_PLACEMENT",
        target_type="placement", target_id=approval.workflow_id,
        details={"approved": approval.approved, "comment": approval.comment,
                 "risk_score": risk_score},
        request=request,
    )
    return {"status": new_status}


@router.post("/api/supervisor_approve")
async def supervisor_approve(
    approval: PlacementApproval,
    request: Request,
    user: dict = Depends(require_role("supervisor", "admin")),
) -> dict[str, str]:
    """Final approval for high-risk placements (risk > 75). Supervisors/admins only."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    new_status = "approved" if approval.approved else "rejected"
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE placements SET status = $2, notes = $3 WHERE workflow_id = $1",
            approval.workflow_id, new_status, approval.comment,
        )
        await conn.execute(
            "UPDATE active_placements SET status = $2 WHERE workflow_id = $1",
            approval.workflow_id, new_status,
        )
        if approval.approved:
            placement = await conn.fetchrow(
                "SELECT child_id, family_json FROM placements WHERE workflow_id = $1",
                approval.workflow_id,
            )
            if placement:
                fj = placement.get("family_json")
                family = json.loads(fj) if isinstance(fj, str) else (fj or {})
                family_id = family.get("family_id") or family.get("id")
                if family_id:
                    await conn.execute(
                        "INSERT INTO placement_history "
                        "  (child_id, family_id, placement_start, outcome, disruption, duration_days) "
                        "VALUES ($1, $2, NOW(), 'active', FALSE, 0)",
                        placement["child_id"], family_id,
                    )

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(approval.workflow_id)
        signal_name = "approve_placement" if approval.approved else "reject_placement"
        await handle.signal(signal_name, approval.comment)
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.supervisor_approve.signal_error",
                       workflow_id=approval.workflow_id, error=str(exc))

    await log_action(
        user_id=user["user_id"], role=user["role"],
        action=(
            "SUPERVISOR_APPROVE_PLACEMENT"
            if approval.approved else "SUPERVISOR_REJECT_PLACEMENT"
        ),
        target_type="placement", target_id=approval.workflow_id,
        details={"approved": approval.approved, "comment": approval.comment},
        request=request,
    )
    return {
        "status": "supervisor_approved" if approval.approved else "supervisor_rejected"
    }


@router.get("/api/placements/{placement_id}/crisis-prediction")
async def get_crisis_prediction(
    placement_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the crisis prediction for a placement.

    Returns a cached prediction if one was generated within the last 24 hours;
    otherwise generates a fresh prediction and stores it.
    """
    from datetime import datetime  # noqa: PLC0415
    from api.services.crisis_predictor import get_crisis_predictor  # noqa: PLC0415

    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Try to return a cached prediction (< 24 h old)
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
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

    if existing:
        age_hours = (
            datetime.now() - existing["prediction_date"].replace(tzinfo=None)
        ).total_seconds() / 3600
        if age_hours < 24:
            top_reasons = existing["top_reasons"]
            interventions = existing["recommended_interventions"]
            if isinstance(top_reasons, str):
                top_reasons = json.loads(top_reasons)
            if isinstance(interventions, str):
                interventions = json.loads(interventions)
            return {
                "probability": float(existing["disruption_probability"]),
                "risk_level": existing["risk_level"],
                "top_reasons": top_reasons or [],
                "recommended_interventions": interventions or [],
                "prediction_date": existing["prediction_date"].isoformat(),
                "cached": True,
            }

    # Generate a fresh prediction
    predictor = get_crisis_predictor()
    prediction = await predictor.predict_and_store(placement_id)
    if prediction is None:
        raise HTTPException(
            status_code=404,
            detail=f"Placement {placement_id} not found or has no data",
        )
    prediction["cached"] = False
    return prediction


@router.post("/api/placements/{placement_id}/refresh-prediction")
async def refresh_crisis_prediction(
    placement_id: str,
    user: dict = Depends(require_role("caseworker", "supervisor", "admin")),
) -> dict[str, Any]:
    """Force-refresh the crisis prediction for a placement."""
    from api.services.crisis_predictor import get_crisis_predictor  # noqa: PLC0415

    predictor = get_crisis_predictor()
    prediction = await predictor.predict_and_store(placement_id)
    if prediction is None:
        raise HTTPException(
            status_code=404,
            detail=f"Placement {placement_id} not found or has no data",
        )
    prediction["cached"] = False
    return prediction


@router.get("/api/placement_explanation/{workflow_id}")
async def get_placement_explanation(workflow_id: str) -> dict[str, Any]:
    """Return explainability data for a specific placement."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT workflow_id, child_id, risk_score, risk_explanation, "
            "       match_explanation, family_json "
            "FROM placements WHERE workflow_id = $1",
            workflow_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Placement {workflow_id} not found")
    record = dict(row)
    fj = record.get("family_json")
    record["family"] = json.loads(fj) if isinstance(fj, str) else (fj or {})
    del record["family_json"]
    return record
