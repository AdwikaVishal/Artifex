"""
api/routes/audit.py – Audit logs, explainability, and ethics endpoints.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_role
from api.db import get_pool

logger = structlog.get_logger()
router = APIRouter(tags=["audit"])


@router.get("/api/audit_logs")
async def get_audit_logs(
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(require_role("admin", "supervisor")),
) -> dict[str, Any]:
    """Return paginated audit log entries. Accessible by admins and supervisors only."""
    pool = get_pool()
    if pool is None:
        return {"logs": [], "count": 0}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp::text, user_id, role, action,
                   target_type, target_id, details, ip_address, user_agent,
                   prev_hash, hash
            FROM audit_logs
            ORDER BY timestamp DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
    logs = []
    for row in rows:
        r = dict(row)
        d = r.get("details")
        r["details"] = json.loads(d) if isinstance(d, str) else (d or {})
        logs.append(r)
    return {"logs": logs, "count": total, "limit": limit, "offset": offset}


@router.get("/api/audit_logs/verify")
async def verify_audit_log_integrity(
    user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Verify the SHA-256 hash chain integrity of the audit log.

    Walks every row in insertion order and recomputes each hash from its
    predecessor.  Returns a summary of any broken links.

    Only admins may call this endpoint.
    """
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp::text, user_id, role, action,
                   target_id, prev_hash, hash
            FROM audit_logs
            ORDER BY id ASC
            """
        )

    if not rows:
        return {"valid": True, "checked": 0, "broken": [], "message": "No audit logs found"}

    broken: list[dict[str, Any]] = []
    prev_hash = "0" * 64

    for row in rows:
        stored_prev = row["prev_hash"] or "0" * 64
        stored_hash = row["hash"] or ""

        # Recompute expected hash
        raw = (
            f"{stored_prev}|{row['action']}|{row['target_id'] or ''}|"
            f"{row['timestamp']}|{row['user_id'] or ''}|{row['role'] or ''}"
        )
        expected_hash = hashlib.sha256(raw.encode()).hexdigest()

        issues: list[str] = []
        if stored_prev != prev_hash:
            issues.append(
                f"prev_hash mismatch: stored={stored_prev[:16]}… expected={prev_hash[:16]}…"
            )
        if stored_hash and stored_hash != expected_hash:
            issues.append(
                f"hash mismatch: stored={stored_hash[:16]}… expected={expected_hash[:16]}…"
            )
        if not stored_hash:
            issues.append("hash column is NULL (row predates hash chain)")

        if issues:
            broken.append({"id": row["id"], "issues": issues})

        # Advance chain: use stored hash if present, else recomputed
        prev_hash = stored_hash or expected_hash

    valid = len(broken) == 0
    return {
        "valid": valid,
        "checked": len(rows),
        "broken": broken,
        "message": "Hash chain intact" if valid else f"{len(broken)} broken link(s) detected",
    }


@router.get("/api/fairness")
async def get_fairness_statement() -> dict[str, Any]:
    """Return the AI fairness and bias statement as structured data."""
    return {
        "title": "AI Fairness & Bias Statement",
        "last_updated": "May 2026",
        "summary": (
            "The Artifex swarm uses machine learning (XGBoost) and large language models "
            "to recommend foster placements and predict disruption risk. While we strive "
            "for accuracy, the models may reflect historical biases present in the training "
            "data (AFCARS)."
        ),
        "limitations": [
            "Risk scores are probabilistic and not definitive.",
            "The model may under-predict risk for certain demographic groups.",
            "Placement recommendations are based on limited features "
            "(age, siblings, special needs).",
            "LLM-generated explanations may contain errors; always verify with a caseworker.",
        ],
        "human_oversight": (
            "Every placement decision requires caseworker approval. "
            "High-risk alerts (risk > 75%) require supervisor confirmation. "
            "Users can reject any recommendation and provide feedback to retrain the model."
        ),
        "data_source": "AFCARS (Adoption and Foster Care Analysis and Reporting System)",
        "contact": "artifex-team@example.com",
    }
