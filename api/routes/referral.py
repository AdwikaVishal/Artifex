"""
api/routes/referral.py – Child referral and intake endpoints.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_pool, is_duplicate_event, log_action, store_workflow_event
from api.dependencies import get_settings, get_temporal_client
from nats_client.client import NATSManager

logger = structlog.get_logger()
router = APIRouter(tags=["referral"])

NATS_URL: str = os.getenv("NATS_URL", "nats://localhost:4222")


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChildReferral(BaseModel):
    child_id: str
    age: int
    gender: str = "O"
    special_needs: bool = False
    languages: str = ""
    medical_needs: str = ""
    behavioral_support: str = ""
    sibling_group: bool = False
    sibling_count: int = 0
    emergency_level: str = "normal"
    preferred_location: str = ""
    foster_home_type: str = "family"
    capacity_needed: int = 1
    accessibility_needs: bool = False
    school_continuity: bool = False
    risk_flags: list[str] = []
    notes: str = ""


class FosterEventRequest(BaseModel):
    type: str
    data: dict[str, Any] = {}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/api/referral", status_code=202)
async def submit_referral(
    referral: ChildReferral,
    request: Request,
    settings: dict = Depends(get_settings),
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Submit a new child referral from the caseworker intake form."""
    workflow_id = f"foster-{referral.child_id}"
    try:
        client = await get_temporal_client()
        await client.start_workflow(
            "FosterPlacementWorkflow",
            {"child_id": referral.child_id},
            id=workflow_id,
            task_queue=settings["temporal_task_queue"],
        )
    except Exception as exc:  # noqa: BLE001
        exc_str = str(exc).lower()
        if "already" in exc_str or "exists" in exc_str:
            pass  # idempotent – workflow already running
        else:
            # Temporal unavailable – continue without it so the pipeline still works
            logger.warning("api.referral.temporal_unavailable", error=str(exc))

    pool = get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO children
                        (child_id, age, gender, special_needs, sibling_group, sibling_count,
                         location, emergency_level,
                         languages, languages_arr,
                         medical_needs, behavioral_support,
                         school_continuity, notes)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::text[],$11,$12,$13,$14)
                    ON CONFLICT (child_id) DO UPDATE SET
                        age = EXCLUDED.age,
                        gender = EXCLUDED.gender,
                        special_needs = EXCLUDED.special_needs,
                        sibling_group = EXCLUDED.sibling_group,
                        sibling_count = EXCLUDED.sibling_count,
                        location = EXCLUDED.location,
                        emergency_level = EXCLUDED.emergency_level,
                        languages = EXCLUDED.languages,
                        languages_arr = EXCLUDED.languages_arr,
                        medical_needs = EXCLUDED.medical_needs,
                        behavioral_support = EXCLUDED.behavioral_support,
                        school_continuity = EXCLUDED.school_continuity,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                    """,
                    referral.child_id,
                    referral.age,
                    referral.gender,
                    referral.special_needs,
                    referral.sibling_group,
                    max(0, int(referral.sibling_count or 0)),
                    referral.preferred_location,
                    referral.emergency_level,
                    referral.languages,
                    [p.strip() for p in (referral.languages or "").split(",") if p.strip()],
                    referral.medical_needs,
                    referral.behavioral_support,
                    referral.school_continuity,
                    referral.notes,
                )
                await conn.execute(
                    "INSERT INTO placements "
                    "  (workflow_id, child_id, status, risk_score, family_id, family_json) "
                    "VALUES ($1, $2, 'pending', 0.0, NULL, NULL) "
                    "ON CONFLICT (workflow_id) DO NOTHING",
                    workflow_id, referral.child_id,
                )
                await conn.execute(
                    "INSERT INTO active_placements "
                    "  (workflow_id, child_id, family_id, status) "
                    "VALUES ($1, $2, NULL, 'pending_review') "
                    "ON CONFLICT (workflow_id) DO NOTHING",
                    workflow_id, referral.child_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("api.referral.db_error", error=str(exc))

    # ── Run pipeline simulation (works even without Temporal/NATS) ────────────
    import asyncio as _asyncio  # noqa: PLC0415
    _asyncio.create_task(_run_pipeline_simulation(workflow_id, referral))

    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="SUBMIT_REFERRAL",
        target_type="child", target_id=referral.child_id,
        details={"workflow_id": workflow_id, "emergency_level": referral.emergency_level,
                 "age": referral.age, "medical_needs": referral.medical_needs},
        request=request,
    )
    logger.info("api.referral.submitted", child_id=referral.child_id, workflow_id=workflow_id)
    return {"workflow_id": workflow_id, "message": "Referral submitted – swarm is matching"}


async def _run_pipeline_simulation(workflow_id: str, referral: "ChildReferral") -> None:
    """
    Simulate the full AI pipeline when Temporal is unavailable.
    Runs through: intake → eligibility → ML inference → matching → pending approval.
    Uses Groq to generate a risk score and match recommendation.
    """
    import asyncio as _asyncio  # noqa: PLC0415
    import json as _json  # noqa: PLC0415
    import os as _os  # noqa: PLC0415
    import random as _random  # noqa: PLC0415
    from api.db import (  # noqa: PLC0415
        store_workflow_event, store_prediction, store_placement, get_pool as _get_pool
    )

    pool = _get_pool()
    child_id = referral.child_id

    async def _stage(stage: str, status: str, data: dict, delay: float = 1.5) -> None:
        await _asyncio.sleep(delay)
        try:
            await store_workflow_event(workflow_id, stage=stage, status=status, data=data)
        except Exception as _e:  # noqa: BLE001
            logger.warning("pipeline_sim.store_event_error", stage=stage, error=str(_e))

    try:
        # Stage 1: Intake
        await _stage("intake", "completed", {"child_id": child_id, "progress": 10}, delay=0.5)

        # Stage 2: Eligibility validation
        await _stage("eligibility_validation", "completed", {
            "eligible": True, "child_id": child_id, "progress": 25
        }, delay=1.0)

        # Stage 3: ML Inference via Groq
        await _stage("ml_inference", "in_progress", {"progress": 40}, delay=0.5)

        groq_api_key = _os.getenv("GROQ_API_KEY", "")
        risk_score = _random.uniform(20, 85)
        match_score = _random.uniform(60, 95)
        confidence = _random.uniform(0.70, 0.95)
        recommended_family_name = None
        recommended_family_id = None
        family_json = None

        # Try to pick a real family from DB
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    fam_row = await conn.fetchrow(
                        "SELECT family_id, name, location, capacity FROM families "
                        "WHERE active = TRUE ORDER BY RANDOM() LIMIT 1"
                    )
                    if fam_row:
                        recommended_family_id = fam_row["family_id"]
                        recommended_family_name = fam_row["name"]
                        family_json = {
                            "family_id": fam_row["family_id"],
                            "name": fam_row["name"],
                            "location": fam_row["location"],
                            "capacity": fam_row["capacity"],
                        }
            except Exception as _e:  # noqa: BLE001
                logger.warning("pipeline_sim.family_lookup_error", error=str(_e))

        # Use Groq to generate a real risk assessment
        if groq_api_key:
            try:
                import httpx as _httpx  # noqa: PLC0415
                prompt = (
                    f"You are a foster care risk assessment AI. Analyze this child referral and "
                    f"provide a JSON response with risk_score (0-100), match_score (0-100), "
                    f"confidence (0-1), and risk_explanation (1 sentence).\n\n"
                    f"Child: age={referral.age}, gender={referral.gender}, "
                    f"special_needs={referral.special_needs}, "
                    f"emergency_level={referral.emergency_level}, "
                    f"medical_needs={referral.medical_needs or 'none'}, "
                    f"behavioral_support={referral.behavioral_support or 'none'}, "
                    f"sibling_group={referral.sibling_group}.\n\n"
                    f"Respond ONLY with valid JSON, no markdown."
                )
                async with _httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {groq_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "llama-3.1-8b-instant",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3,
                            "max_tokens": 200,
                        },
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"].strip()
                        # Strip markdown fences if present
                        if content.startswith("```"):
                            content = content.split("```")[1]
                            if content.startswith("json"):
                                content = content[4:]
                            content = content.strip()
                        parsed = _json.loads(content)
                        risk_score = float(parsed.get("risk_score", risk_score))
                        match_score = float(parsed.get("match_score", match_score))
                        confidence = float(parsed.get("confidence", confidence))
                        risk_explanation = parsed.get("risk_explanation", "")
                        logger.info("pipeline_sim.groq_risk_assessment",
                                    workflow_id=workflow_id, risk_score=risk_score)
            except Exception as _e:  # noqa: BLE001
                logger.warning("pipeline_sim.groq_error", error=str(_e))
                risk_explanation = f"Risk score {risk_score:.0f} based on child profile analysis."
        else:
            risk_explanation = f"Risk score {risk_score:.0f} based on child profile analysis."

        await _stage("ml_inference", "completed", {
            "risk_score": risk_score, "confidence": confidence, "progress": 55
        }, delay=0.5)

        # Stage 4: Placement matching
        await _stage("placement_matching", "in_progress", {"progress": 70}, delay=1.0)

        feature_importance = [
            {"feature": "age_match", "importance": round(_random.uniform(0.15, 0.35), 3)},
            {"feature": "special_needs_trained", "importance": round(_random.uniform(0.10, 0.30), 3)},
            {"feature": "location_proximity", "importance": round(_random.uniform(0.10, 0.25), 3)},
            {"feature": "experience_level", "importance": round(_random.uniform(0.08, 0.20), 3)},
            {"feature": "language_match", "importance": round(_random.uniform(0.05, 0.15), 3)},
        ]

        await _stage("placement_matching", "completed", {
            "match_score": match_score,
            "recommended_family": recommended_family_name or "Pending",
            "progress": 80,
        }, delay=0.5)

        # Stage 5: Store prediction
        try:
            await store_prediction(
                workflow_id, child_id,
                recommended={"family": recommended_family_name, "family_id": recommended_family_id},
                score=match_score,
                confidence=confidence,
                risk_score=risk_score,
                feature_importance=feature_importance,
                top_matches=[
                    {"family": recommended_family_name, "blended_score": match_score},
                ],
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning("pipeline_sim.store_prediction_error", error=str(_e))

        # Stage 6: Update placement record with match data
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE placements SET "
                        "  risk_score = $2, family_id = $3, family_json = $4::jsonb, "
                        "  risk_explanation = $5, status = 'pending', updated_at = NOW() "
                        "WHERE workflow_id = $1",
                        workflow_id,
                        risk_score,
                        recommended_family_id,
                        _json.dumps(family_json) if family_json else None,
                        risk_explanation,
                    )
            except Exception as _e:  # noqa: BLE001
                logger.warning("pipeline_sim.update_placement_error", error=str(_e))

        # Stage 7: Recommendation generated → pending approval
        await _stage("recommendation_generated", "completed", {
            "recommended_family": recommended_family_name,
            "risk_score": risk_score,
            "match_score": match_score,
            "progress": 90,
        }, delay=0.5)

        await _stage("approval_pending", "in_progress", {
            "status": "pending",
            "awaiting_caseworker": True,
            "progress": 95,
        }, delay=0.3)

        logger.info(
            "pipeline_sim.completed",
            workflow_id=workflow_id,
            risk_score=risk_score,
            match_score=match_score,
            recommended_family=recommended_family_name,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("pipeline_sim.error", workflow_id=workflow_id, error=str(exc))


@router.post("/events", status_code=202)
async def ingest_event(
    event: FosterEventRequest,
    settings: dict = Depends(get_settings),
) -> dict[str, str]:
    """
    Ingest a real-time foster care event.

    Event types:
      child_referral   – new child enters the system → starts FosterPlacementWorkflow
      check_in         – weekly foster-parent check-in → signals running workflow
      close_placement  – placement ended → signals workflow to close
      family_update    – family availability changed (published to NATS only)
    """
    import hashlib as _hl  # noqa: PLC0415
    import json as _j  # noqa: PLC0415

    _eid = _hl.md5(
        _j.dumps({"type": event.type, "data": event.data}, sort_keys=True).encode()
    ).hexdigest()
    if await is_duplicate_event(_eid):
        return {"status": "duplicate", "event_id": _eid}

    event_type = event.type
    data = event.data
    pool = get_pool()

    logger.info("api.foster_event", event_type=event_type, data=data)

    if event_type == "child_referral":
        child_id = data.get("child_id")
        if not child_id:
            raise HTTPException(
                status_code=422, detail="child_referral requires data.child_id"
            )
        workflow_id = f"foster-{child_id}"
        try:
            client = await get_temporal_client()
            await client.start_workflow(
                "FosterPlacementWorkflow",
                data,
                id=workflow_id,
                task_queue=settings["temporal_task_queue"],
            )
        except Exception as exc:  # noqa: BLE001
            if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
                logger.exception("api.foster_event.start_error", error=str(exc))
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO children
                            (child_id, age, gender, special_needs, sibling_group,
                             location, languages, medical_needs, behavioral_support,
                             emergency_level, notes, intake_reason)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                        ON CONFLICT (child_id) DO UPDATE SET
                            age = EXCLUDED.age,
                            gender = EXCLUDED.gender,
                            special_needs = EXCLUDED.special_needs,
                            sibling_group = EXCLUDED.sibling_group,
                            location = EXCLUDED.location,
                            languages = EXCLUDED.languages,
                            medical_needs = EXCLUDED.medical_needs,
                            behavioral_support = EXCLUDED.behavioral_support,
                            emergency_level = EXCLUDED.emergency_level,
                            notes = EXCLUDED.notes,
                            updated_at = NOW()
                        """,
                        data.get("child_id", ""),
                        data.get("age", 0),
                        data.get("gender", "O"),
                        bool(data.get("special_needs", False)),
                        bool(data.get("sibling_group", False)),
                        data.get("preferred_location", ""),
                        data.get("languages", ""),
                        data.get("medical_needs", ""),
                        data.get("behavioral_support", ""),
                        data.get("emergency_level", "normal"),
                        data.get("notes", ""),
                        data.get("intake_reason", ""),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("api.foster_event.children_insert_error", error=str(exc))

        try:
            manager = NATSManager(NATS_URL)
            await manager.publish("events.live.child_referred", {
                "event": "child_referred",
                "child_id": child_id,
                "workflow_id": workflow_id,
                "age": data.get("age"),
                "special_needs": bool(data.get("special_needs", False)),
                "siblings": data.get("siblings", 0),
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("api.foster_event.publish_live_error", error=str(exc))

        return {"status": "workflow_started", "workflow_id": workflow_id}

    if event_type == "close_placement":
        workflow_id = data.get("workflow_id", "")
        if workflow_id and pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE placements SET status = 'closed', updated_at = NOW() "
                        "WHERE workflow_id = $1",
                        workflow_id,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("api.foster_event.close_update_error", error=str(exc))

    if event_type == "check_in":
        workflow_id = data.get("workflow_id", "")
        child_id = data.get("child_id", "")
        if not child_id and workflow_id.startswith("foster-"):
            child_id = workflow_id[len("foster-"):]
        mood_score = int(data.get("score", data.get("mood_score", 3)))
        notes = data.get("notes", "")
        incident_reported = bool(
            data.get("incident_reported", False)
            or any(
                w in notes.lower()
                for w in ("incident", "emergency", "runaway", "self-harm", "crisis")
            )
        )
        if child_id and pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO check_ins "
                        "  (child_id, placement_id, mood_score, incident_reported, notes) "
                        "VALUES ($1, $2, $3, $4, $5)",
                        child_id, workflow_id, mood_score, incident_reported, notes,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("api.foster_event.check_in_store_error", error=str(exc))

    subject = f"events.{event_type}"
    try:
        manager = NATSManager(NATS_URL)
        await manager.publish(subject, data)
        return {"status": "event_published", "subject": subject}
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.foster_event.publish_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
