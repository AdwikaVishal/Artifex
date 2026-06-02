"""
api/routes/timeline.py – Child Life Timeline REST API.

Endpoints:
  GET    /api/timeline/{child_id}               – list events (paginated, filtered, redact)
  POST   /api/timeline/{child_id}/events        – insert a new event (manual entry or admin)
  GET    /api/timeline/{child_id}/export/pdf    – PDF export placeholder
  POST   /api/timeline/{child_id}/verify/{event_id} – mark event as verified
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from api.auth import get_current_user, require_role
from api.db import get_pool

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
]

VALID_SEAL_LEVELS = ["none", "partial", "full"]


class CreateEventRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=64)
    event_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    event_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}(:\d{2})?$")
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
    """
    Fetch paginated life timeline events for a child.

    Supports filtering by event_type, seal_level, date range.

    The `redact` parameter controls what sealed content to show:
      - `none` (default) — show all events, sealed records show placeholder
      - `partial` — hide partial-seal payloads, show full-seal as placeholders
      - `full` — hide all sealed content entirely
    """
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

        # Exclude superseded events by default
        conditions.append("superseded_by IS NULL")

        where = " AND ".join(conditions)

        # Count
        count_row = await conn.fetchval(f"SELECT COUNT(*) FROM child_life_events WHERE {where}", *params)

        # Fetch
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

    # Apply redaction
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

    # Remove fully redacted entries if requested
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
    """
    Insert a new event into the child's life timeline.

    Manual entries and system-generated events both use this endpoint.
    Events are append-only — corrections should use supersede.
    """
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
                 payload, seal_level, source_table, source_id)
            VALUES ($1, $2, $3::date, $4::time,
                    $5::jsonb, $6, $7, $8)
            RETURNING id
            """,
            child_id,
            request.event_type,
            request.event_date,
            request.event_time,
            json.dumps(request.payload),
            request.seal_level,
            request.source_table,
            request.source_id,
        )

        event_id = row["id"]

        logger.info(
            "timeline.create_event",
            child_id=child_id,
            event_type=request.event_type,
            event_id=event_id,
            user_id=user["user_id"],
        )

    return {
        "status": "ok",
        "event_id": event_id,
        "message": f"{request.event_type} event recorded",
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
    """
    Export timeline as PDF (placeholder — returns data payload).

    Actual PDF rendering will be implemented server-side via Playwright.
    """
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

    # Apply redaction per parameter
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
