"""
api/routes/ml_audit.py – ML decision audit trail API.

Four endpoints for compliance officers and external auditors:
  GET /api/ml-audit/verify              – hash chain integrity check
  GET /api/ml-audit/decisions            – filtered decision query
  GET /api/ml-audit/decisions/{id}/verify – spot-check single hash
  GET /api/ml-audit/export               – CSV/JSON download
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from api.auth import require_role
from api.db import get_pool

logger = structlog.get_logger()
router = APIRouter(tags=["ml-audit"])


@router.get("/api/ml-audit/verify")
async def verify_ml_audit_hash_chain(
    user: dict = Depends(require_role("admin", "supervisor")),
) -> dict[str, Any]:
    """
    Verify the SHA-256 hash chain integrity of the ML decision audit table.

    Walks every row in insertion order and recomputes each hash from its
    predecessor using the ml_decision_audit hash algorithm:
      SHA-256(prev_hash|decision_type|child_id|decided_at|output_score|model_version)
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, decision_type, child_id, decided_at::text,
                   output_score, model_version, prev_hash, hash
            FROM ml_decision_audit
            ORDER BY id ASC
            """
        )

    if not rows:
        return {"valid": True, "checked": 0, "broken_links": [], "message": "No decisions found"}

    broken: list[dict[str, Any]] = []
    prev_hash = "0" * 64

    for row in rows:
        stored_prev = row["prev_hash"] or "0" * 64
        stored_hash = row["hash"] or ""

        raw = (
            f"{stored_prev}|{row['decision_type']}|{row['child_id']}|"
            f"{row['decided_at']}|{row['output_score'] or ''}|"
            f"{row['model_version'] or ''}"
        )
        expected = hashlib.sha256(raw.encode()).hexdigest()

        issues: list[str] = []
        if stored_prev != prev_hash:
            issues.append(
                f"prev_hash mismatch at row {row['id']}: "
                f"stored={stored_prev[:16]}… expected={prev_hash[:16]}…"
            )
        if stored_hash and stored_hash != expected:
            issues.append(
                f"hash mismatch at row {row['id']}: "
                f"stored={stored_hash[:16]}… expected={expected[:16]}…"
            )
        if not stored_hash:
            issues.append(f"hash is NULL at row {row['id']} (trigger may not have fired)")

        if issues:
            broken.append({"id": row["id"], "issues": issues})

        prev_hash = stored_hash or expected

    valid = len(broken) == 0
    return {
        "valid": valid,
        "checked": len(rows),
        "broken_links": broken,
        "oldest_row": rows[0]["decided_at"] if rows else None,
        "newest_row": rows[-1]["decided_at"] if rows else None,
        "message": (
            "Hash chain intact — all decisions verified"
            if valid
            else f"{len(broken)} broken link(s) detected"
        ),
    }


@router.get("/api/ml-audit/decisions")
async def get_ml_audit_decisions(
    child_id: str | None = Query(None),
    decision_type: str | None = Query(None),
    demographic_key: str | None = Query(None),
    demographic_val: str | None = Query(None),
    model_version: str | None = Query(None),
    min_score: float | None = Query(None, ge=0, le=100),
    max_score: float | None = Query(None, ge=0, le=100),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="decided_at:desc", pattern=r"^(decided_at|output_score):(asc|desc)$"),
    user: dict = Depends(require_role("admin", "supervisor")),
) -> dict[str, Any]:
    """
    Query the ML decision audit trail with flexible filters.

    Supports demographic filtering via JSONB key/value pairs
    (e.g. demographic_key=race&demographic_val=Black%20or%20African%20American).
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if child_id:
        conditions.append(f"child_id = ${idx}")
        params.append(child_id)
        idx += 1

    if decision_type:
        conditions.append(f"decision_type = ${idx}")
        params.append(decision_type)
        idx += 1

    if demographic_key and demographic_val:
        conditions.append(f"child_demographics->>${idx} = ${idx + 1}")
        params.append(demographic_key)
        params.append(demographic_val)
        idx += 2

    if model_version:
        conditions.append(f"model_version = ${idx}")
        params.append(model_version)
        idx += 1

    if min_score is not None:
        conditions.append(f"output_score >= ${idx}")
        params.append(min_score)
        idx += 1

    if max_score is not None:
        conditions.append(f"output_score <= ${idx}")
        params.append(max_score)
        idx += 1

    if from_date:
        conditions.append(f"decided_at >= ${idx}::timestamp")
        params.append(from_date)
        idx += 1

    if to_date:
        conditions.append(f"decided_at <= ${idx}::timestamp")
        params.append(to_date)
        idx += 1

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sort_col, sort_dir = sort.split(":")
    sort_sql = f"{sort_col} {sort_dir.upper()}"

    async with pool.acquire() as conn:
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM ml_decision_audit WHERE {where_clause}",
            *params,
        )
        rows = await conn.fetch(
            f"""
            SELECT id, child_id, placement_id, decision_type,
                   model_name, model_version, child_demographics,
                   output_score, output_label, output_confidence,
                   human_overridden, human_decision, decided_at::text, hash
            FROM ml_decision_audit
            WHERE {where_clause}
            ORDER BY {sort_sql}
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
            limit,
            offset,
        )

    decisions = []
    for r in rows:
        d = dict(r)
        dem = d.get("child_demographics")
        d["child_demographics"] = json.loads(dem) if isinstance(dem, str) else (dem or {})
        decisions.append(d)

    return {
        "decisions": decisions,
        "total": count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/ml-audit/decisions/{decision_id}/verify")
async def verify_single_ml_decision(
    decision_id: int,
    user: dict = Depends(require_role("admin", "supervisor")),
) -> dict[str, Any]:
    """Spot-check a single decision's hash against its stored fields."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, decision_type, child_id, decided_at::text,
                   output_score, model_version, prev_hash, hash
            FROM ml_decision_audit
            WHERE id = $1
            """,
            decision_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Decision not found")

    stored_hash = row["hash"] or ""
    stored_prev = row["prev_hash"] or "0" * 64

    raw = (
        f"{stored_prev}|{row['decision_type']}|{row['child_id']}|"
        f"{row['decided_at']}|{row['output_score'] or ''}|"
        f"{row['model_version'] or ''}"
    )
    recomputed = hashlib.sha256(raw.encode()).hexdigest()

    hash_matches = stored_hash == recomputed if stored_hash else False

    # Also check prev_hash links to the previous row
    prev_hash_matches: bool | None = None
    if row["id"] > 1:
        prev_row = await pool.fetchrow(
            "SELECT hash FROM ml_decision_audit WHERE id = $1",
            row["id"] - 1,
        )
        if prev_row:
            expected_prev = prev_row["hash"] or "0" * 64
            prev_hash_matches = stored_prev == expected_prev

    return {
        "id": decision_id,
        "hash": stored_hash,
        "recomputed_hash": recomputed,
        "prev_hash": stored_prev,
        "prev_hash_matches": prev_hash_matches,
        "verification": "PASS" if hash_matches else "FAIL" if stored_hash else "UNVERIFIED",
        "audited_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }


@router.get("/api/ml-audit/export")
async def export_ml_audit_decisions(
    format: str = Query(default="csv", pattern=r"^(csv|json)$"),
    child_id: str | None = Query(None),
    decision_type: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    model_version: str | None = Query(None),
    demographic_key: str | None = Query(None),
    demographic_val: str | None = Query(None),
    user: dict = Depends(require_role("admin", "supervisor")),
) -> Response:
    """Export ML audit decisions as CSV or JSON for external auditors."""
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if child_id:
        conditions.append(f"child_id = ${idx}")
        params.append(child_id)
        idx += 1
    if decision_type:
        conditions.append(f"decision_type = ${idx}")
        params.append(decision_type)
        idx += 1
    if from_date:
        conditions.append(f"decided_at >= ${idx}::timestamp")
        params.append(from_date)
        idx += 1
    if to_date:
        conditions.append(f"decided_at <= ${idx}::timestamp")
        params.append(to_date)
        idx += 1
    if model_version:
        conditions.append(f"model_version = ${idx}")
        params.append(model_version)
        idx += 1
    if demographic_key and demographic_val:
        conditions.append(f"child_demographics->>${idx} = ${idx + 1}")
        params.append(demographic_key)
        params.append(demographic_val)
        idx += 2

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, child_id, placement_id, decision_type,
                   model_name, model_version, decided_at::text,
                   output_score, output_label, output_confidence,
                   human_overridden, human_decision,
                   child_demographics->>'age' AS child_age,
                   child_demographics->>'gender' AS child_gender,
                   child_demographics->>'race' AS child_race,
                   child_demographics->>'fpl_percent' AS child_fpl_percent,
                   child_demographics->>'zip_code' AS child_zip_code,
                   feature_hash, hash, prev_hash
            FROM ml_decision_audit
            WHERE {where_clause}
            ORDER BY id ASC
            """
        )

    data = [dict(r) for r in rows]

    if format == "json":
        export = {
            "export_meta": {
                "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "decision_count": len(data),
                "format": "json",
            },
            "decisions": data,
        }
        return Response(
            content=json.dumps(export, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=ml_audit_export.json"},
        )

    # CSV format
    import csv
    import io

    output = io.StringIO()
    if data:
        writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
        writer.writeheader()
        for row in data:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    else:
        output.write("id,child_id,placement_id,decision_type,model_name,model_version,"
                      "decided_at,output_score,output_label,output_confidence,"
                      "human_overridden,human_decision,child_age,child_gender,"
                      "child_race,child_fpl_percent,child_zip_code,"
                      "feature_hash,hash,prev_hash\n")

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ml_audit_export.csv"},
    )
