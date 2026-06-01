"""
api/routes/children.py – Children CRUD endpoints.
"""
from __future__ import annotations

from typing import Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_pool, log_action

logger = structlog.get_logger()
router = APIRouter(tags=["children"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChildCreate(BaseModel):
    child_id: str
    first_name: str = ""
    last_name: str = ""
    age: int = 0
    gender: str = "O"
    location: str = ""
    sibling_group: bool = False
    sibling_count: int = 0
    special_needs: bool = False
    medical_needs: str = ""
    behavioral_support: str = ""
    emergency_level: str = "normal"
    languages: str = ""
    languages_arr: list[str] = []
    school_continuity: bool = False
    case_notes: str = ""


class ChildUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    age: int | None = None
    gender: str | None = None
    location: str | None = None
    sibling_group: bool | None = None
    sibling_count: int | None = None
    special_needs: bool | None = None
    medical_needs: str | None = None
    behavioral_support: str | None = None
    emergency_level: str | None = None
    languages: str | None = None
    languages_arr: list[str] | None = None
    school_continuity: bool | None = None
    case_notes: str | None = None


def _child_row_to_dict(row: asyncpg.Record) -> dict:
    def _fmt(val: Any) -> str | None:
        return val.isoformat() if val else None

    return {
        "child_id":           row["child_id"],
        "first_name":         row.get("first_name", ""),
        "last_name":          row.get("last_name", ""),
        "age":                row["age"],
        "gender":             row["gender"],
        "location":           row.get("location", ""),
        "sibling_group":      row.get("sibling_group", False),
        "sibling_count":      row.get("sibling_count", 0),
        "special_needs":      row.get("special_needs", False),
        "medical_needs":      row.get("medical_needs", ""),
        "behavioral_support": row.get("behavioral_support", ""),
        "emergency_level":    row.get("emergency_level", "normal"),
        "languages":          row.get("languages", ""),
        "languages_arr":      row.get("languages_arr") or [],
        "school_continuity":  row.get("school_continuity", False),
        "case_notes":         row.get("case_notes", row.get("notes", "")),
        "created_at":         _fmt(row.get("created_at")),
        "updated_at":         _fmt(row.get("updated_at")),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/children")
async def list_children(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM children ORDER BY created_at DESC")
    return {"children": [_child_row_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/children/{child_id}")
async def get_child(
    child_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM children WHERE child_id = $1", child_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Child {child_id} not found")
    return _child_row_to_dict(row)


@router.post("/children", status_code=201)
async def create_child(
    child: ChildCreate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO children
                (child_id, first_name, last_name, age, gender, location,
                 sibling_group, sibling_count, special_needs,
                 medical_needs, behavioral_support, emergency_level,
                 languages, languages_arr,
                 school_continuity,
                 case_notes, notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::text[],$15,$16,$16)
            RETURNING *
            """,
            child.child_id,
            child.first_name,
            child.last_name,
            child.age,
            child.gender,
            child.location,
            child.sibling_group,
            child.sibling_count,
            child.special_needs,
            child.medical_needs,
            child.behavioral_support,
            child.emergency_level,
            child.languages,
            child.languages_arr or [
                p.strip() for p in (child.languages or "").split(",") if p.strip()
            ],
            child.school_continuity,
            child.case_notes,
        )
    result = _child_row_to_dict(row)
    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="CREATE_CHILD",
        target_type="child", target_id=child.child_id,
        details={"age": child.age, "gender": child.gender, "location": child.location},
        request=request,
    )
    return result


@router.put("/children/{child_id}")
async def update_child(
    child_id: str,
    update: ChildUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM children WHERE child_id = $1", child_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Child {child_id} not found")

        fields: list[str] = []
        values: list[Any] = []
        idx = 1
        col_map = {
            "first_name": "first_name",
            "last_name": "last_name",
            "age": "age",
            "gender": "gender",
            "location": "location",
            "sibling_group": "sibling_group",
            "sibling_count": "sibling_count",
            "special_needs": "special_needs",
            "medical_needs": "medical_needs",
            "behavioral_support": "behavioral_support",
            "emergency_level": "emergency_level",
            "languages": "languages",
            "languages_arr": "languages_arr",
            "school_continuity": "school_continuity",
            "case_notes": "case_notes",
        }
        for attr, col in col_map.items():
            val = getattr(update, attr, None)
            if val is not None:
                fields.append(f"{col} = ${idx}")
                values.append(val)
                idx += 1
                if attr == "languages_arr":
                    fields.append(f"languages = ${idx}")
                    values.append(", ".join(val))
                    idx += 1
                if attr == "case_notes":
                    fields.append(f"notes = ${idx}")
                    values.append(val)
                    idx += 1
                if attr == "languages":
                    arr = [p.strip() for p in (val or "").split(",") if p.strip()]
                    fields.append(f"languages_arr = ${idx}")
                    values.append(arr)
                    idx += 1

        if not fields:
            return _child_row_to_dict(existing)

        fields.append("updated_at = NOW()")
        values.append(child_id)
        set_clause = ", ".join(fields)
        row = await conn.fetchrow(
            f"UPDATE children SET {set_clause} WHERE child_id = ${idx} RETURNING *",
            *values,
        )
    result = _child_row_to_dict(row)
    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="UPDATE_CHILD",
        target_type="child", target_id=child_id,
        details={k: getattr(update, k) for k in ("age", "gender", "location")
                 if getattr(update, k, None) is not None},
        request=request,
    )
    return result


@router.get("/children/{child_id}/timeline")
async def get_child_timeline(
    child_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a complete chronological life timeline for a child.

    Aggregates data from: children, placements, workflow_events, and check_ins.
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        # Child record
        child = await conn.fetchrow(
            "SELECT * FROM children WHERE child_id = $1", child_id
        )
        if not child:
            raise HTTPException(
                status_code=404, detail=f"Child {child_id} not found"
            )

        # All placements for this child
        placements = await conn.fetch(
            "SELECT * FROM placements WHERE child_id = $1 ORDER BY created_at ASC",
            child_id,
        )

        # Workflow events for all placements
        workflow_ids = [p["workflow_id"] for p in placements]
        events: list[Any] = []
        if workflow_ids:
            events = await conn.fetch(
                """
                SELECT we.workflow_id, we.stage, we.status, we.data, we.timestamp
                FROM workflow_events we
                WHERE we.workflow_id = ANY($1::text[])
                ORDER BY we.timestamp ASC
                """,
                workflow_ids,
            )

        # Check-ins for this child
        check_ins = await conn.fetch(
            """
            SELECT child_id, placement_id, mood_score, incident_reported,
                   notes, timestamp
            FROM check_ins
            WHERE child_id = $1
            ORDER BY timestamp ASC
            """,
            child_id,
        )

    timeline: list[dict[str, Any]] = []

    # Entry event
    entry_date = child.get("created_at")
    timeline.append(
        {
            "date": entry_date.isoformat() if entry_date else None,
            "type": "entry",
            "title": "Entered Care",
            "description": (
                child.get("intake_reason")
                or child.get("case_notes")
                or child.get("notes")
                or "Child entered the foster care system"
            ),
            "icon": "🏠",
        }
    )

    # Placement events
    for p in placements:
        import json as _json  # noqa: PLC0415

        fj = p.get("family_json")
        family: dict[str, Any] = {}
        if fj:
            family = _json.loads(fj) if isinstance(fj, str) else (fj or {})
        family_name = family.get("name") or p.get("family_id") or "Unknown family"
        risk = float(p.get("risk_score") or 0)
        p_date = p.get("created_at")
        timeline.append(
            {
                "date": p_date.isoformat() if p_date else None,
                "type": "placement",
                "title": f"Placement – {p.get('status', 'active').title()}",
                "description": f"Family: {family_name} · Risk {risk:.0f}%",
                "icon": "🏡",
                "risk_score": risk,
                "workflow_id": p["workflow_id"],
            }
        )

    # Significant workflow events (completed stages only, skip noise)
    _significant_stages = {
        "intake",
        "eligibility_validation",
        "ml_inference",
        "placement_matching",
        "recommendation_generated",
        "approval_pending",
        "placement_approved",
        "placement_rejected",
    }
    for ev in events:
        stage = (ev.get("stage") or "").lower()
        if stage not in _significant_stages:
            continue
        if ev.get("status") not in ("completed", "approved", "rejected"):
            continue
        ev_date = ev.get("timestamp")
        timeline.append(
            {
                "date": ev_date.isoformat() if ev_date else None,
                "type": "workflow",
                "title": stage.replace("_", " ").title(),
                "description": f"Workflow stage: {ev.get('status', '')}",
                "icon": "⚙️",
                "workflow_id": ev.get("workflow_id"),
            }
        )

    # Check-ins and incidents
    for ci in check_ins:
        is_incident = bool(ci.get("incident_reported"))
        mood = int(ci.get("mood_score") or 3)
        notes = (ci.get("notes") or "")[:120]
        ci_date = ci.get("timestamp")
        timeline.append(
            {
                "date": ci_date.isoformat() if ci_date else None,
                "type": "incident" if is_incident else "checkin",
                "title": "Incident Reported" if is_incident else "Check-in",
                "description": notes or (
                    f"Mood score: {mood}/5"
                ),
                "icon": "⚠️" if is_incident else "📝",
                "mood_score": mood,
            }
        )

    # Sort by date, putting None dates last
    timeline.sort(
        key=lambda x: x.get("date") or "9999-99-99"
    )

    child_name = " ".join(
        filter(
            None,
            [child.get("first_name", ""), child.get("last_name", "")],
        )
    ) or child_id

    return {
        "child_id": child_id,
        "child_name": child_name,
        "age": child.get("age"),
        "emergency_level": child.get("emergency_level", "normal"),
        "special_needs": child.get("special_needs", False),
        "school": child.get("school"),
        "milestones": child.get("milestones") or [],
        "therapy_history": child.get("therapy_history") or [],
        "timeline": timeline,
    }


@router.delete("/children/{child_id}")
async def delete_child(
    child_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM children WHERE child_id = $1", child_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail=f"Child {child_id} not found")
    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="DELETE_CHILD",
        target_type="child", target_id=child_id,
        details={},
        request=request,
    )
    return {"status": "deleted", "child_id": child_id}
