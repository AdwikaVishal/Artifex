"""
api/db.py – Shared PostgreSQL connection pool and helper functions.

All route modules import from here so the pool is a true singleton.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any

import asyncpg
import structlog

logger = structlog.get_logger()
_process_logger = logging.getLogger("artifex.db")

DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://artifex:artifex123@postgres:5432/placements"
)

# ── Connection pool (module-level singleton) ──────────────────────────────────
_db_pool: asyncpg.Pool | None = None


def get_pool() -> asyncpg.Pool | None:
    """Return the current pool (may be None before init)."""
    return _db_pool


async def init_db_pool() -> None:
    """
    Create the asyncpg connection pool.
    Schema is managed exclusively by Alembic – no DDL here.
    """
    global _db_pool
    _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    logger.info("api.db_pool_ready", url=DATABASE_URL.split("@")[-1])


def run_alembic_upgrade() -> None:
    """
    Run ``alembic upgrade head`` synchronously at startup.

    Uses subprocess so we don't need to import Alembic's internals into the
    async event loop.  Exits the process on failure so Kubernetes / Docker
    restarts the container rather than serving requests against a stale schema.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini = os.path.join(repo_root, "alembic.ini")

    if not os.path.exists(alembic_ini):
        _process_logger.warning(
            "alembic.ini not found at %s – skipping schema migration", alembic_ini
        )
        return

    _process_logger.info("Running alembic upgrade head …")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", alembic_ini, "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        _process_logger.error(
            "alembic upgrade head FAILED:\nstdout: %s\nstderr: %s",
            result.stdout,
            result.stderr,
        )
        sys.exit(1)
    _process_logger.info("alembic upgrade head OK:\n%s", result.stdout or "(no output)")


# ── Placement helpers ─────────────────────────────────────────────────────────

async def store_placement(placement: dict) -> None:
    """Upsert a placement record into PostgreSQL."""
    if _db_pool is None:
        logger.warning("api.store_placement.no_pool")
        return
    async with _db_pool.acquire() as conn:
        family = placement.get("family")
        if not isinstance(family, dict):
            family = None
        family_id = family.get("family_id") if family else None
        await conn.execute(
            """
            INSERT INTO placements
                (workflow_id, child_id, family_id, family_json,
                 risk_score, risk_explanation, match_explanation, last_notes, status, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (workflow_id) DO UPDATE SET
                family_id         = EXCLUDED.family_id,
                risk_score        = EXCLUDED.risk_score,
                risk_explanation  = EXCLUDED.risk_explanation,
                match_explanation = COALESCE(EXCLUDED.match_explanation, placements.match_explanation),
                last_notes        = EXCLUDED.last_notes,
                family_json       = EXCLUDED.family_json,
                status            = EXCLUDED.status,
                updated_at        = NOW()
            """,
            placement.get("workflow_id", f"wf-{placement.get('child_id', 'unknown')}"),
            placement.get("child_id", "unknown"),
            family_id,
            json.dumps(family) if family else None,
            float(placement.get("risk_score", 0.0)),
            placement.get("risk_explanation"),
            placement.get("match_explanation"),
            placement.get("last_notes"),
            placement.get("status") or "active",
        )


async def store_workflow_event(
    workflow_id: str, stage: str, status: str, data: dict | None = None
) -> None:
    """Persist a workflow event and update workflow_status."""
    if _db_pool is None:
        logger.warning("api.store_workflow_event.no_pool")
        return
    safe_data = data or {}
    async with _db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO workflow_events (workflow_id, stage, status, data) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            workflow_id, stage, status, json.dumps(safe_data),
        )
        progress = int(safe_data.get("progress", 0))
        await conn.execute(
            "INSERT INTO workflow_status "
            "  (workflow_id, status, current_stage, progress, metadata, updated_at) "
            "VALUES ($1,$2,$3,$4,$5::jsonb,NOW()) "
            "ON CONFLICT (workflow_id) DO UPDATE SET "
            "  status=EXCLUDED.status, current_stage=EXCLUDED.current_stage, "
            "  progress=EXCLUDED.progress, "
            "  metadata=COALESCE(EXCLUDED.metadata, workflow_status.metadata), "
            "  updated_at=NOW()",
            workflow_id, status, stage, progress, json.dumps(safe_data),
        )


async def get_workflow_timeline(workflow_id: str, limit: int = 100) -> list[dict]:
    if _db_pool is None:
        return []
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage, status, data, timestamp FROM workflow_events "
            "WHERE workflow_id = $1 ORDER BY timestamp ASC LIMIT $2",
            workflow_id, limit,
        )
    return [dict(r) for r in rows]


async def get_workflow_status_db(workflow_id: str) -> dict | None:
    if _db_pool is None:
        return None
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT workflow_id, status, current_stage, progress, metadata, updated_at "
            "FROM workflow_status WHERE workflow_id = $1",
            workflow_id,
        )
    return dict(row) if row else None


async def store_ml_inference_log(
    workflow_id: str,
    child_id: str,
    payload: dict,
    result: dict,
    model_version: str | None = None,
) -> None:
    if _db_pool is None:
        return
    async with _db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO ml_inference_logs "
            "  (workflow_id, child_id, payload, result, model_version) "
            "VALUES ($1,$2,$3::jsonb,$4::jsonb,$5)",
            workflow_id, child_id,
            json.dumps(payload), json.dumps(result), model_version,
        )


async def store_prediction(
    workflow_id: str,
    child_id: str,
    recommended: dict,
    score: float | None = None,
    confidence: float | None = None,
    model_version: str | None = None,
    risk_score: float | None = None,
    feature_importance: list | None = None,
    top_matches: list | None = None,
) -> None:
    if _db_pool is None:
        return
    async with _db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO placement_predictions "
            "  (workflow_id, child_id, recommended, score, confidence, "
            "   risk_score, feature_importance, top_matches, model_version) "
            "VALUES ($1,$2,$3::jsonb,$4,$5,$6,$7::jsonb,$8::jsonb,$9)",
            workflow_id, child_id,
            json.dumps(recommended), score, confidence, risk_score,
            json.dumps(feature_importance) if feature_importance else None,
            json.dumps(top_matches) if top_matches else None,
            model_version,
        )


async def get_latest_prediction(workflow_id: str) -> dict | None:
    if _db_pool is None:
        return None
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT recommended, score, confidence, risk_score, "
            "       feature_importance, top_matches, model_version, created_at "
            "FROM placement_predictions "
            "WHERE workflow_id = $1 ORDER BY created_at DESC LIMIT 1",
            workflow_id,
        )
    if not row:
        return None
    result = dict(row)
    for col in ("recommended", "feature_importance", "top_matches"):
        val = result.get(col)
        if isinstance(val, str):
            try:
                result[col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return result


async def get_all_placements() -> list[dict]:
    """Fetch the 50 most recently updated placements from PostgreSQL."""
    if _db_pool is None:
        return []
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.*,
                ws.status AS ws_status,
                ws.current_stage,
                ws.progress,
                pp.recommended,
                pp.score AS match_score,
                pp.confidence AS confidence_score,
                pp.risk_score AS predicted_risk_score,
                pp.feature_importance,
                pp.top_matches
            FROM placements p
            LEFT JOIN workflow_status ws ON p.workflow_id = ws.workflow_id
            LEFT JOIN LATERAL (
                SELECT recommended, score, confidence, risk_score,
                       feature_importance, top_matches
                FROM placement_predictions
                WHERE workflow_id = p.workflow_id
                ORDER BY created_at DESC
                LIMIT 1
            ) pp ON TRUE
            ORDER BY p.updated_at DESC
            LIMIT 50
            """
        )
    result = []
    for row in rows:
        record = dict(row)
        for col in ("family_json", "recommended", "feature_importance", "top_matches"):
            val = record.get(col)
            if isinstance(val, str):
                try:
                    record[col] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass

        family = record.get("family_json") or record.get("family") or {}
        if isinstance(family, str):
            try:
                family = json.loads(family)
            except (json.JSONDecodeError, TypeError):
                family = {}
        if isinstance(family, dict):
            record["family"] = family
            record["family_id"] = record.get("family_id") or family.get("family_id")
            record["foster_family_name"] = (
                record.get("foster_family_name") or family.get("name")
            )
            record["location"] = record.get("location") or family.get("location")
            record["capacity"] = record.get("capacity") or family.get("capacity")

        recommended = record.get("recommended")
        if recommended is not None:
            if isinstance(recommended, dict):
                record["recommended_family"] = (
                    recommended.get("family") or recommended.get("name")
                )
                if record.get("capacity") is None:
                    record["capacity"] = (
                        recommended.get("capacity")
                        or recommended.get("available_capacity")
                    )
                if record.get("location") is None:
                    record["location"] = recommended.get("location")
                if not record.get("foster_family_name"):
                    record["foster_family_name"] = record["recommended_family"]
                if not record.get("family_id"):
                    record["family_id"] = recommended.get("family_id")
            else:
                record["recommended_family"] = recommended
                if not record.get("foster_family_name"):
                    record["foster_family_name"] = recommended

        # Prefer workflow_status.status over placements.status when present
        if record.get("ws_status"):
            record["status"] = record["ws_status"]

        if record.get("confidence_score") is None and record.get("confidence") is not None:
            record["confidence_score"] = record.get("confidence")

        if record.get("predicted_risk_score") is not None:
            record["risk_score"] = record.get("predicted_risk_score")

        result.append(record)

    logger.info("placements.response", count=len(result))
    return result


# ── Event deduplication (PostgreSQL-backed) ───────────────────────────────────

async def is_duplicate_event(event_id: str) -> bool:
    """
    Check and mark an event as processed using the processed_events table.

    Uses INSERT … ON CONFLICT DO NOTHING and checks affected rows.
    Falls back to Redis (if available) then in-memory set.
    """
    if _db_pool is not None:
        try:
            async with _db_pool.acquire() as conn:
                result = await conn.execute(
                    "INSERT INTO processed_events (event_id) VALUES ($1) "
                    "ON CONFLICT (event_id) DO NOTHING",
                    event_id,
                )
                # asyncpg returns "INSERT 0 <n>" – n=0 means conflict (duplicate)
                inserted = int(result.split()[-1])
                return inserted == 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("api.db_dedup_error", error=str(exc))

    # Fallback: in-memory set (single-replica only)
    if event_id in _processed_events_fallback:
        return True
    _processed_events_fallback.add(event_id)
    if len(_processed_events_fallback) > 10_000:
        _processed_events_fallback.clear()
    return False


_processed_events_fallback: set[str] = set()


async def cleanup_old_processed_events() -> None:
    """Delete processed_events rows older than 7 days. Run daily."""
    if _db_pool is None:
        return
    try:
        async with _db_pool.acquire() as conn:
            deleted = await conn.execute(
                "DELETE FROM processed_events "
                "WHERE processed_at < NOW() - INTERVAL '7 days'"
            )
        count = int(deleted.split()[-1])
        logger.info("api.processed_events_cleanup", deleted=count)
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.processed_events_cleanup_error", error=str(exc))


# ── Pending approvals (DB-backed, replaces in-memory list) ───────────────────

async def add_pending_approval(
    workflow_id: str,
    child_id: str,
    risk_score: float = 0.0,
) -> None:
    """Insert a pending approval record (idempotent via ON CONFLICT DO NOTHING)."""
    if _db_pool is None:
        return
    try:
        async with _db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pending_approvals (workflow_id, child_id, risk_score, status)
                VALUES ($1, $2, $3, 'pending')
                ON CONFLICT (workflow_id) DO NOTHING
                """,
                workflow_id, child_id, risk_score,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.add_pending_approval.error", error=str(exc))


async def get_pending_approvals_db() -> list[dict]:
    """Return all pending approval rows."""
    if _db_pool is None:
        return []
    try:
        async with _db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT workflow_id, child_id, risk_score, status, created_at "
                "FROM pending_approvals WHERE status = 'pending' "
                "ORDER BY created_at DESC"
            )
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.get_pending_approvals_db.error", error=str(exc))
        return []


async def resolve_pending_approval(workflow_id: str, new_status: str) -> None:
    """Mark a pending approval as approved/rejected."""
    if _db_pool is None:
        return
    try:
        async with _db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE pending_approvals SET status = $2 WHERE workflow_id = $1",
                workflow_id, new_status,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.resolve_pending_approval.error", error=str(exc))


# ── Audit log helper ──────────────────────────────────────────────────────────

import hashlib as _hashlib

_audit_hash_lock = __import__("asyncio").Lock()


def _compute_audit_hash(
    prev_hash: str,
    action: str,
    target_id: str,
    timestamp: str,
    user_id: str,
    role: str,
) -> str:
    """SHA-256 hash of the concatenated audit fields for tamper detection."""
    raw = f"{prev_hash}|{action}|{target_id}|{timestamp}|{user_id}|{role}"
    return _hashlib.sha256(raw.encode()).hexdigest()


async def log_action(
    user_id: str,
    role: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any],
    request: Any | None = None,
) -> None:
    """Write an immutable, hash-chained audit record to PostgreSQL. Non-blocking."""
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    try:
        if _db_pool is not None:
            async with _audit_hash_lock:
                async with _db_pool.acquire() as conn:
                    # Fetch the hash of the most recent audit entry for chaining
                    prev_row = await conn.fetchrow(
                        "SELECT hash FROM audit_logs ORDER BY id DESC LIMIT 1"
                    )
                    prev_hash: str = prev_row["hash"] if prev_row and prev_row["hash"] else "0" * 64

                    import datetime as _dt  # noqa: PLC0415
                    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
                    entry_hash = _compute_audit_hash(
                        prev_hash, action, target_id, ts, user_id, role
                    )

                    await conn.execute(
                        "INSERT INTO audit_logs "
                        "  (user_id, role, action, target_type, target_id, "
                        "   details, ip_address, user_agent, prev_hash, hash) "
                        "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)",
                        user_id, role, action, target_type, target_id,
                        json.dumps(details), ip, ua, prev_hash, entry_hash,
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.audit_log.error", action=action, error=str(exc))
