"""
api/routes/families.py – Foster family CRUD endpoints.
"""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_pool, log_action
from services.capacity import available_capacity_sql

logger = structlog.get_logger()
router = APIRouter(tags=["families"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class FamilyCreate(BaseModel):
    name: str
    location: str = ""
    latitude: float | None = None
    longitude: float | None = None
    capacity: int = 1
    total_capacity: int | None = None
    experience: str = "new"
    experience_level: str | None = None
    specializations: str = ""
    languages: str = ""
    languages_arr: list[str] = []
    special_needs_trained: bool = False
    accepts_siblings: bool = False
    sibling_group_capable: bool | None = None
    emergency_available: bool = False
    home_type: str = "family"
    max_age: int = 18
    can_take_siblings: bool = False
    has_animals: bool = False
    active: bool = True


class FamilyUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    capacity: int | None = None
    total_capacity: int | None = None
    experience: str | None = None
    experience_level: str | None = None
    specializations: str | None = None
    languages: str | None = None
    languages_arr: list[str] | None = None
    special_needs_trained: bool | None = None
    accepts_siblings: bool | None = None
    sibling_group_capable: bool | None = None
    emergency_available: bool | None = None
    home_type: str | None = None
    max_age: int | None = None
    can_take_siblings: bool | None = None
    has_animals: bool | None = None
    active: bool | None = None


def _family_row_to_dict(row: asyncpg.Record) -> dict:
    def _fmt(val: Any) -> str | None:
        return val.isoformat() if val else None

    return {
        "id":                   row["id"],
        "family_id":            row["family_id"],
        "name":                 row["name"],
        "location":             row["location"],
        "latitude":             row.get("latitude"),
        "longitude":            row.get("longitude"),
        "capacity":             row["capacity"],
        "total_capacity":       row.get("total_capacity", row["capacity"]),
        "available_capacity":   row["available_capacity"],
        "experience":           row["experience"],
        "experience_level":     row.get("experience_level", row["experience"]),
        "specializations":      row["specializations"],
        "languages":            row["languages"],
        "languages_arr":        row.get("languages_arr") or [],
        "special_needs_trained": row["special_needs_trained"],
        "accepts_siblings":     row["accepts_siblings"],
        "sibling_group_capable": row.get("sibling_group_capable", row["accepts_siblings"]),
        "emergency_available":  row["emergency_available"],
        "home_type":            row.get("home_type", "family"),
        "max_age":              row["max_age"],
        "can_take_siblings":    row["can_take_siblings"],
        "has_animals":          row["has_animals"],
        "active":               row.get("active", True),
        "created_at":           _fmt(row.get("created_at")),
        "updated_at":           _fmt(row.get("updated_at")),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/families")
async def list_families(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT f.*,
              {available_capacity_sql("f")} AS available_capacity
            FROM families f
            WHERE f.active = TRUE
            ORDER BY f.name
            """
        )
    return {"families": [_family_row_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/families/{family_id}")
async def get_family(
    family_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT f.*,
              {available_capacity_sql("f")} AS available_capacity
            FROM families f
            WHERE f.family_id = $1
            """,
            family_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Family {family_id} not found")
    return _family_row_to_dict(row)


@router.post("/families", status_code=201)
async def create_family(
    family: FamilyCreate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    family_id = f"F-{uuid.uuid4().hex[:6].upper()}"
    total_capacity = int(family.total_capacity or family.capacity or 1)
    experience_level = family.experience_level or family.experience or "new"
    sibling_group_capable = (
        bool(family.sibling_group_capable)
        if family.sibling_group_capable is not None
        else bool(family.can_take_siblings or family.accepts_siblings)
    )
    languages_arr = (
        family.languages_arr
        if family.languages_arr
        else [p.strip() for p in (family.languages or "").split(",") if p.strip()]
    )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO families
                (family_id, name, location, latitude, longitude,
                 capacity, total_capacity, active,
                 experience, experience_level,
                 specializations, languages, languages_arr,
                 special_needs_trained, accepts_siblings, sibling_group_capable,
                 emergency_available, home_type,
                 max_age, can_take_siblings, has_animals)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::text[],$14,$15,$16,$17,$18,$19,$20,$21)
            RETURNING *
            """,
            family_id,
            family.name,
            family.location,
            family.latitude,
            family.longitude,
            int(family.capacity or total_capacity),
            total_capacity,
            bool(family.active),
            family.experience,
            experience_level,
            family.specializations,
            family.languages,
            languages_arr,
            family.special_needs_trained,
            family.accepts_siblings,
            sibling_group_capable,
            family.emergency_available,
            family.home_type,
            family.max_age,
            family.can_take_siblings,
            family.has_animals,
        )
    # Compute available_capacity for the new row (no active placements yet)
    result = dict(row)
    result["available_capacity"] = result.get("total_capacity", result.get("capacity", 1))
    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="CREATE_FAMILY",
        target_type="family", target_id=family_id,
        details={"name": family.name, "location": family.location, "capacity": family.capacity},
        request=request,
    )
    logger.info("api.create_family", family_id=family_id, name=family.name)
    return result


@router.put("/families/{family_id}")
async def update_family(
    family_id: str,
    update: FamilyUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM families WHERE family_id = $1", family_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Family {family_id} not found")

        fields: list[str] = []
        values: list[Any] = []
        idx = 1
        for col in (
            "name", "location", "latitude", "longitude",
            "capacity", "total_capacity", "active",
            "experience", "experience_level", "specializations",
            "languages", "languages_arr",
            "special_needs_trained", "accepts_siblings", "sibling_group_capable",
            "emergency_available", "home_type", "max_age",
            "can_take_siblings", "has_animals",
        ):
            val = getattr(update, col, None)
            if val is not None:
                fields.append(f"{col} = ${idx}")
                values.append(val)
                idx += 1
                if col == "languages":
                    arr = [p.strip() for p in (val or "").split(",") if p.strip()]
                    fields.append(f"languages_arr = ${idx}")
                    values.append(arr)
                    idx += 1

        if not fields:
            avail = await conn.fetchval(
                f"SELECT {available_capacity_sql('families')} "
                "FROM families WHERE family_id = $1",
                family_id,
            )
            result = dict(existing)
            result["available_capacity"] = avail or 0
            return _family_row_to_dict(
                await conn.fetchrow(
                    f"SELECT f.*, {available_capacity_sql('f')} AS available_capacity "
                    "FROM families f WHERE f.family_id = $1",
                    family_id,
                )
            )

        fields.append("updated_at = NOW()")
        values.append(family_id)
        set_clause = ", ".join(fields)
        row = await conn.fetchrow(
            f"UPDATE families SET {set_clause} WHERE family_id = ${idx} RETURNING *",
            *values,
        )
        avail = await conn.fetchval(
            f"SELECT {available_capacity_sql('families')} "
            "FROM families WHERE family_id = $1",
            family_id,
        )
    result = dict(row)
    result["available_capacity"] = avail or 0
    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="UPDATE_FAMILY",
        target_type="family", target_id=family_id,
        details={k: getattr(update, k) for k in ("name", "location", "capacity")
                 if getattr(update, k, None) is not None},
        request=request,
    )
    logger.info("api.update_family", family_id=family_id)
    return result


@router.delete("/families/{family_id}")
async def delete_family(
    family_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM families WHERE family_id = $1", family_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail=f"Family {family_id} not found")
    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="DELETE_FAMILY",
        target_type="family", target_id=family_id,
        details={},
        request=request,
    )
    logger.info("api.delete_family", family_id=family_id)
    return {"status": "deleted", "family_id": family_id}
