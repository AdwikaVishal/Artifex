"""
api/routes/timeline.py – Child Life Timeline REST API.

Endpoints:
  GET    /api/timeline/{child_id}               – list events (paginated, filtered, redact)
  POST   /api/timeline/{child_id}/events        – insert a new event (manual entry or admin)
  POST   /api/timeline/{child_id}/events/quick  – one-click quick-add event
  GET    /api/timeline/{child_id}/stats         – aggregate event stats
  GET    /api/timeline/{child_id}/export/pdf    – PDF export placeholder
  POST   /api/timeline/{child_id}/verify/{event_id} – mark event as verified
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from api.auth import get_current_user, require_role
from api.db import get_pool
from api.websockets.events import broadcast_child_event

logger = structlog.get_logger()
router = APIRouter(tags=["timeline"])


# ── Pydantic models ───────────────────────────────────────────────────────────

VALID_EVENT_TYPES = [
    "placement_start", "placement_end", "placement_change",
    "school_change", "incident_report", "court_date", "legal_milestone",
    "medical_appointment", "therapy_session", "sibling_contact",
    "family_visitation", "milestone", "crisis_alert", "drift_threshold",
    "prediction_feedback", "twin_simulation", "caseworker_assignment",
    "caseworker_change", "manual_entry",
    # Live-feed simplified types
    "school", "medical", "incident", "visit", "legal", "placement", "note",
]

VALID_SEAL_LEVELS = ["none", "partial", "full"]
VALID_SEVERITIES = ["low", "medium", "high", "critical"]


class CreateEventRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=64)
    event_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    event_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    title: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
    severity: str | None = Field(default="low")
    created_by: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    seal_level: str = Field(default="none")
    source_table: str | None = None
    source_id: int | None = None

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, v: str) -> str:
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type '{v}'. Must be one of: {', '.join(VALID_EVENT_TYPES)}")
        return v

    @field_validator("seal_level")
    @classmethod
    def valid_seal_level(cls, v: str) -> str:
        if v not in VALID_SEAL_LEVELS:
            raise ValueError(f"seal_level must be one of: {', '.join(VALID_SEAL_LEVELS)}")
        return v

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, v: str | None) -> str | None:
        if v and v not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(VALID_SEVERITIES)}")
        return v


class QuickAddRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
    severity: str | None = Field(default="low")

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, v: str) -> str:
        simplified = {"school", "medical", "incident", "visit", "legal", "placement", "note"}
        if v not in simplified:
            raise ValueError(f"Quick-add event_type must be one of: {', '.join(sorted(simplified))}")
        return v


class VerifyEventRequest(BaseModel):
    verified_by: str = Field(default="", max_length=128)


# ── Event response mapping ────────────────────────────────────────────────────

def _row_to_event(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "child_id": row["child_id"],
        "event_type": row["event_type"],
        "event_date": row["event_date"].isoformat() if hasattr(row["event_date"], "isoformat") else str(row["event_date"]),
        "event_time": row["event_time"].isoformat() if row.get("event_time") and hasattr(row["event_time"], "isoformat") else row.get("event_time"),
        "title": row.get("title"),
        "description": row.get("description"),
        "severity": row.get("severity", "low"),
        "created_by": row.get("created_by"),
        "payload": row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"]) if isinstance(row.get("payload"), str) else {},
        "seal_level": row["seal_level"],
        "is_verified": row["is_verified"],
        "verified_by": row.get("verified_by"),
        "verified_at": row["verified_at"].isoformat() if row.get("verified_at") and hasattr(row["verified_at"], "isoformat") else row.get("verified_at"),
        "source_table": row.get("source_table"),
        "source_id": row.get("source_id"),
        "conflict_resolution": row.get("conflict_resolution"),
        "superseded_by": row.get("superseded_by"),
        "recorded_at": row["recorded_at"].isoformat() if hasattr(row["recorded_at"], "isoformat") else str(row["recorded_at"]),
    }


def _event_to_broadcast(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Strip internal fields for WS broadcast."""
    return {
        k: v for k, v in event_dict.items()
        if k not in ("seal_level", "is_verified", "verified_by", "verified_at",
                     "source_table", "source_id", "conflict_resolution", "superseded_by")
    }


# ── Helper: auto-generate child event ─────────────────────────────────────────

async def auto_create_child_event(
    child_id: str,
    event_type: str,
    title: str,
    description: str | None = None,
    severity: str = "low",
    created_by: str = "system",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Insert a child_life_event and broadcast via WebSocket. Used by workflow actions."""
    pool = get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            row = await conn.fetchrow(
                """
                INSERT INTO child_life_events
                    (child_id, event_type, event_date, title, description,
                     severity, created_by, payload)
                VALUES ($1, $2, $3::date, $4, $5, $6, $7, $8::jsonb)
                RETURNING *
                """,
                child_id, event_type, today, title, description,
                severity, created_by,
                json.dumps(payload or {}),
            )
            if row:
                event_dict = _row_to_event(row)
                await broadcast_child_event(child_id, _event_to_broadcast(event_dict))
                return event_dict
    except Exception:
        logger.exception("auto_create_child_event.error", child_id=child_id, event_type=event_type)
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/api/timeline/{child_id}")
async def get_timeline(
    child_id: str,
    user: dict = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    event_type: str | None = Query(default=None, description="Filter by event type"),
    seal_level: str | None = Query(default=None, description="Filter by seal level"),
    redact: str | None = Query(default=None, description="Redaction level for export (none/partial/full)"),
    start_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Fetch paginated life timeline events for a child."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        child = await conn.fetchval("SELECT 1 FROM children WHERE child_id = $1", child_id)
        if not child:
            raise HTTPException(status_code=404, detail=f"Child {child_id} not found")

        conditions = ["child_id = $1"]
        params: list[Any] = [child_id]
        param_idx = 2

        if event_type:
            conditions.append(f"event_type = ${param_idx}")
            params.append(event_type)
            param_idx += 1

        if seal_level:
            conditions.append(f"seal_level = ${param_idx}")
            params.append(seal_level)
            param_idx += 1

        if start_date:
            conditions.append(f"event_date >= ${param_idx}::date")
            params.append(start_date)
            param_idx += 1

        if end_date:
            conditions.append(f"event_date <= ${param_idx}::date")
            params.append(end_date)
            param_idx += 1

        conditions.append("superseded_by IS NULL")

        where = " AND ".join(conditions)

        count_row = await conn.fetchval(f"SELECT COUNT(*) FROM child_life_events WHERE {where}", *params)

        offset = (page - 1) * per_page
        rows = await conn.fetch(
            f"""
            SELECT * FROM child_life_events
            WHERE {where}
            ORDER BY event_date DESC, id DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """,
            *params,
            per_page,
            offset,
        )

    events = [_row_to_event(r) for r in rows]

    redact_level = redact or "none"
    if redact_level != "none":
        for ev in events:
            if ev["seal_level"] == "full":
                if redact_level == "full":
                    ev["_redacted"] = True
                else:
                    ev["payload"] = {"_redacted": True}
            elif ev["seal_level"] == "partial" and redact_level in ("full", "partial"):
                ev["payload"] = {"_redacted": True}

    if redact_level == "full":
        events = [ev for ev in events if not ev.get("_redacted")]

    return {
        "child_id": child_id,
        "events": events,
        "total": count_row,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (count_row + per_page - 1) // per_page) if count_row else 1,
    }


@router.post("/api/timeline/{child_id}/events")
async def create_event(
    child_id: str,
    request: CreateEventRequest,
    req: Request,
    user: dict = Depends(require_role("caseworker", "supervisor", "admin")),
) -> dict[str, Any]:
    """Insert a new event into the child's life timeline. Broadcasts via WebSocket."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        child = await conn.fetchval("SELECT 1 FROM children WHERE child_id = $1", child_id)
        if not child:
            raise HTTPException(status_code=404, detail=f"Child {child_id} not found")

        row = await conn.fetchrow(
            """
            INSERT INTO child_life_events
                (child_id, event_type, event_date, event_time,
                 title, description, severity, created_by,
                 payload, seal_level, source_table, source_id)
            VALUES ($1, $2, $3::date, $4::time,
                    $5, $6, $7, $8,
                    $9::jsonb, $10, $11, $12)
            RETURNING *
            """,
            child_id,
            request.event_type,
            request.event_date,
            request.event_time,
            request.title,
            request.description,
            request.severity,
            request.created_by or user["user_id"],
            json.dumps(request.payload),
            request.seal_level,
            request.source_table,
            request.source_id,
        )

        event_dict = _row_to_event(row)

    # Broadcast to WebSocket subscribers
    await broadcast_child_event(child_id, _event_to_broadcast(event_dict))

    logger.info(
        "timeline.create_event",
        child_id=child_id,
        event_type=request.event_type,
        event_id=event_dict["id"],
        user_id=user["user_id"],
    )

    return {
        "status": "ok",
        "event": event_dict,
        "message": f"{request.event_type} event recorded",
    }


@router.post("/api/timeline/{child_id}/events/quick")
async def quick_add_event(
    child_id: str,
    request: QuickAddRequest,
    req: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """One-click quick-add event. Simplified form — just type, title, description, severity."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    now_time = now.strftime("%H:%M:%S")

    async with pool.acquire() as conn:
        child = await conn.fetchval("SELECT 1 FROM children WHERE child_id = $1", child_id)
        if not child:
            raise HTTPException(status_code=404, detail=f"Child {child_id} not found")

        row = await conn.fetchrow(
            """
            INSERT INTO child_life_events
                (child_id, event_type, event_date, event_time,
                 title, description, severity, created_by, payload)
            VALUES ($1, $2, $3::date, $4::time,
                    $5, $6, $7, $8, '{}'::jsonb)
            RETURNING *
            """,
            child_id,
            request.event_type,
            today,
            now_time,
            request.title or request.event_type.replace("_", " ").title(),
            request.description,
            request.severity,
            user["user_id"],
        )

        event_dict = _row_to_event(row)

    await broadcast_child_event(child_id, _event_to_broadcast(event_dict))

    return {
        "status": "ok",
        "event": event_dict,
        "message": f"{request.event_type} event recorded",
    }


@router.get("/api/timeline/{child_id}/stats")
async def get_child_event_stats(
    child_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Aggregate event statistics for a child."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        child = await conn.fetchrow(
            "SELECT child_id, age, emergency_level, special_needs, "
            "       first_name, last_name, location "
            "FROM children WHERE child_id = $1",
            child_id,
        )
        if not child:
            raise HTTPException(status_code=404, detail=f"Child {child_id} not found")

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM child_life_events WHERE child_id = $1 AND superseded_by IS NULL",
            child_id,
        )

        type_counts = await conn.fetch(
            """
            SELECT event_type, COUNT(*) as cnt
            FROM child_life_events
            WHERE child_id = $1 AND superseded_by IS NULL
            GROUP BY event_type
            ORDER BY cnt DESC
            """,
            child_id,
        )

        severity_counts = await conn.fetch(
            """
            SELECT severity, COUNT(*) as cnt
            FROM child_life_events
            WHERE child_id = $1 AND superseded_by IS NULL AND severity IS NOT NULL
            GROUP BY severity
            """,
            child_id,
        )

        last_event = await conn.fetchrow(
            """
            SELECT event_type, title, recorded_at
            FROM child_life_events
            WHERE child_id = $1 AND superseded_by IS NULL
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            child_id,
        )

    # Get current placement status
    pool2 = get_pool()
    placement_info = {}
    if pool2 is not None:
        try:
            async with pool2.acquire() as conn2:
                ap = await conn2.fetchrow(
                    "SELECT family_id, status, placement_start "
                    "FROM active_placements WHERE child_id = $1 AND status = 'active' "
                    "ORDER BY placement_start DESC LIMIT 1",
                    child_id,
                )
                if ap:
                    placement_info = {
                        "family_id": ap["family_id"],
                        "status": ap["status"],
                        "since": ap["placement_start"].isoformat() if hasattr(ap.get("placement_start"), "isoformat") else str(ap.get("placement_start", "")),
                    }
        except Exception:
            pass

    child_name = " ".join(filter(None, [child.get("first_name", ""), child.get("last_name", "")])) or child_id

    return {
        "child_id": child_id,
        "child_name": child_name,
        "age": child["age"],
        "emergency_level": child["emergency_level"],
        "special_needs": child["special_needs"],
        "location": child["location"],
        "total_events": total or 0,
        "by_type": {r["event_type"]: r["cnt"] for r in type_counts},
        "by_severity": {r["severity"]: r["cnt"] for r in severity_counts},
        "last_activity": last_event["recorded_at"].isoformat() if last_event and last_event.get("recorded_at") else None,
        "placement": placement_info,
    }


@router.post("/api/timeline/{child_id}/verify/{event_id}")
async def verify_event(
    child_id: str,
    event_id: int,
    request: VerifyEventRequest,
    req: Request,
    user: dict = Depends(require_role("supervisor", "admin")),
) -> dict[str, str]:
    """Mark a timeline event as verified by a supervisor."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE child_life_events
            SET is_verified = TRUE,
                verified_by = $1,
                verified_at = NOW()
            WHERE id = $2 AND child_id = $3
            """,
            request.verified_by or user["user_id"],
            event_id,
            child_id,
        )

        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Event not found")

        logger.info(
            "timeline.verify_event",
            child_id=child_id,
            event_id=event_id,
            verified_by=user["user_id"],
        )

    return {"status": "ok", "message": f"Event {event_id} verified"}


@router.get("/api/timeline/{child_id}/export/pdf")
async def export_timeline_pdf(
    child_id: str,
    user: dict = Depends(get_current_user),
    redact: str = Query(default="none", pattern=r"^(none|partial|full)$"),
) -> dict[str, Any]:
    """Export timeline as PDF (placeholder — returns data payload)."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        child = await conn.fetchrow(
            "SELECT child_id, age, gender, school, emergency_level FROM children WHERE child_id = $1",
            child_id,
        )
        if not child:
            raise HTTPException(status_code=404, detail=f"Child {child_id} not found")

        rows = await conn.fetch(
            """
            SELECT * FROM child_life_events
            WHERE child_id = $1 AND superseded_by IS NULL
            ORDER BY event_date DESC, id DESC
            """,
            child_id,
        )

    events = [_row_to_event(r) for r in rows]

    if redact != "none":
        for ev in events:
            if ev["seal_level"] == "full":
                if redact == "full":
                    ev["_redacted"] = True
                else:
                    ev["payload"] = {"_redacted": True}
            elif ev["seal_level"] == "partial" and redact in ("full", "partial"):
                ev["payload"] = {"_redacted": True}
    if redact == "full":
        events = [ev for ev in events if not ev.get("_redacted")]

    child_info = {
        "child_id": child["child_id"],
        "age": child["age"],
        "gender": child["gender"],
        "school": child["school"],
        "emergency_level": child["emergency_level"],
    }

    return {
        "status": "ok",
        "child_info": child_info,
        "events": events,
        "total_events": len(events),
        "redaction_level": redact,
        "generated_at": datetime.now().isoformat(),
        "pdf_url": f"/api/timeline/{child_id}/export/pdf/render",
        "footer_disclosure": (
            "This document was generated by the Artifex Child Life Timeline. "
            "Some events may be sealed or redacted per court order. "
            "Redaction level: " + redact + "."
        ),
    }
