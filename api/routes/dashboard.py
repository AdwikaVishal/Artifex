"""
api/routes/dashboard.py – Live dashboard metrics from PostgreSQL.
"""
from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException

from api.db import get_pool

logger = structlog.get_logger()

router = APIRouter(tags=["dashboard"])

# Agent heartbeat store – populated by the NATS heartbeat subscriber in main.py
_agent_heartbeats: dict[str, float] = {}
_heartbeat_lock_ref: Any = None  # set by main.py after import


def set_heartbeat_store(store: dict, lock: Any) -> None:
    """Called by main.py to share the heartbeat dict and lock."""
    global _agent_heartbeats, _heartbeat_lock_ref
    _agent_heartbeats = store
    _heartbeat_lock_ref = lock


@router.get("/dashboard/metrics")
async def dashboard_metrics() -> dict[str, Any]:
    """Live dashboard metrics computed from PostgreSQL – no mock/hardcoded data."""
    pool = get_pool()
    if pool is None:
        return {
            "active_workflows": 0, "pending_approvals": 0,
            "placements_matched": 0, "emergency_referrals": 0,
            "workflows_change": 0, "approvals_change": 0,
            "placements_change": 0, "emergency_change": 0,
        }
    async with pool.acquire() as conn:
        active_wf = await conn.fetchval(
            "SELECT COUNT(*) FROM placements "
            "WHERE status IN ('pending','pending_supervisor','approved')"
        )
        pending_approvals = await conn.fetchval(
            "SELECT COUNT(*) FROM placements "
            "WHERE status IN ('pending','pending_supervisor')"
        )
        placements_total = await conn.fetchval(
            "SELECT COUNT(*) FROM placements WHERE status = 'approved'"
        )
        emergency = await conn.fetchval(
            "SELECT COUNT(*) FROM children WHERE emergency_level = 'emergency'"
        )
        wf_change = await conn.fetchval(
            "SELECT COUNT(*) FROM placements "
            "WHERE created_at > NOW() - INTERVAL '24 hours'"
        )
        apr_change = await conn.fetchval(
            "SELECT COUNT(*) FROM placements "
            "WHERE status = 'pending' AND created_at > NOW() - INTERVAL '24 hours'"
        )
        pl_change = await conn.fetchval(
            "SELECT COUNT(*) FROM placements "
            "WHERE status = 'approved' AND created_at > NOW() - INTERVAL '24 hours'"
        )
        em_change = await conn.fetchval(
            "SELECT COUNT(*) FROM children "
            "WHERE emergency_level = 'emergency' "
            "AND created_at > NOW() - INTERVAL '24 hours'"
        )
    return {
        "active_workflows":    active_wf or 0,
        "pending_approvals":   pending_approvals or 0,
        "placements_matched":  placements_total or 0,
        "emergency_referrals": emergency or 0,
        "workflows_change":    wf_change or 0,
        "approvals_change":    apr_change or 0,
        "placements_change":   pl_change or 0,
        "emergency_change":    em_change or 0,
    }


@router.get("/dashboard/risk-distribution")
async def dashboard_risk_distribution() -> dict[str, int]:
    """Risk score distribution computed from live placements table."""
    pool = get_pool()
    if pool is None:
        return {"low": 0, "medium": 0, "high": 0, "critical": 0}
    async with pool.acquire() as conn:
        low = await conn.fetchval(
            "SELECT COUNT(*) FROM placements WHERE risk_score < 25"
        )
        medium = await conn.fetchval(
            "SELECT COUNT(*) FROM placements "
            "WHERE risk_score >= 25 AND risk_score < 50"
        )
        high = await conn.fetchval(
            "SELECT COUNT(*) FROM placements "
            "WHERE risk_score >= 50 AND risk_score < 75"
        )
        critical = await conn.fetchval(
            "SELECT COUNT(*) FROM placements WHERE risk_score >= 75"
        )
    return {
        "low":      low or 0,
        "medium":   medium or 0,
        "high":     high or 0,
        "critical": critical or 0,
    }


@router.get("/dashboard/events")
async def dashboard_events() -> dict[str, list[dict]]:
    """Recent workflow events from the placements table."""
    events: list[dict] = []
    pool = get_pool()
    if pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.workflow_id, p.child_id, p.status, p.risk_score,
                       p.created_at, c.emergency_level
                FROM placements p
                LEFT JOIN children c ON c.child_id = p.child_id
                ORDER BY p.created_at DESC
                LIMIT 50
                """
            )
            for row in rows:
                events.append({
                    "id":             row["workflow_id"],
                    "type":           "status_change",
                    "workflow_id":    row["workflow_id"],
                    "workflow_stage": row["status"],
                    "child_id":       row.get("child_id") or "",
                    "message":        (
                        f"Placement {row['status']} "
                        f"for child {row.get('child_id', 'N/A')}"
                    ),
                    "timestamp": (
                        row["created_at"].isoformat()
                        if row["created_at"] else ""
                    ),
                })
    return {"events": events}


@router.get("/dashboard/workflow-activity")
async def dashboard_workflow_activity() -> dict[str, list[dict]]:
    """
    Returns per-day workflow activity for the last 7 days from PostgreSQL.
    Each entry: { name: 'Mon', submitted: N, matched: N, approved: N }
    """
    pool = get_pool()
    if pool is None:
        return {"activity": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                TO_CHAR(day, 'Dy') AS name,
                COUNT(*) FILTER (WHERE TRUE)                          AS submitted,
                COUNT(*) FILTER (WHERE status IN ('approved','active','closed')) AS matched,
                COUNT(*) FILTER (WHERE status = 'approved')           AS approved
            FROM (
                SELECT
                    DATE_TRUNC('day', created_at) AS day,
                    status
                FROM placements
                WHERE created_at >= NOW() - INTERVAL '7 days'
            ) sub
            GROUP BY day
            ORDER BY day ASC
            """
        )
    activity = [
        {
            "name":      row["name"],
            "submitted": int(row["submitted"] or 0),
            "matched":   int(row["matched"] or 0),
            "approved":  int(row["approved"] or 0),
        }
        for row in rows
    ]
    return {"activity": activity}



async def agent_status(agent_name: str) -> dict[str, Any]:
    """Return the last heartbeat timestamp for a named agent."""
    last_seen = _agent_heartbeats.get(agent_name)
    now = time.time()
    if last_seen is None:
        status = "unknown"
        age = None
    elif now - last_seen < 90:
        status = "healthy"
        age = round(now - last_seen, 1)
    else:
        status = "stale"
        age = round(now - last_seen, 1)
    return {"agent": agent_name, "status": status, "last_heartbeat_age_s": age}


@router.get("/agent/status")
async def all_agent_statuses() -> dict[str, Any]:
    """Return status for all known agents from the heartbeats store."""
    agents: dict[str, Any] = {}
    now = time.time()
    for name, last_seen in list(_agent_heartbeats.items()):
        if last_seen is None:
            status = "unknown"
            age = None
        elif now - last_seen < 90:
            status = "healthy"
            age = round(now - last_seen, 1)
        else:
            status = "stale"
            age = round(now - last_seen, 1)
        agents[name] = {"name": name, "status": status, "last_heartbeat_age_s": age}
    return {"agents": agents}


@router.get("/api/agents")
async def get_agents() -> dict[str, Any]:
    """
    Detailed agent registry info.
    Returns every known agent with its current status, uptime estimate, and
    a human-readable label.  Used by the front-end orchestration page.
    """
    now = time.time()
    result: dict[str, Any] = {}
    for name, last_seen in list(_agent_heartbeats.items()):
        if last_seen is None:
            status = "unknown"
            age = None
        elif now - last_seen < 90:
            status = "active"
            age = round(now - last_seen, 1)
        else:
            status = "idle"
            age = round(now - last_seen, 1)
        label = name.replace("_", " ").title()
        result[name] = {
            "id": name,
            "name": label,
            "type": name,
            "status": status,
            "last_heartbeat_age_s": age,
        }
    return {"agents": result}


@router.get("/api/heartbeats")
async def get_heartbeats() -> dict[str, Any]:
    """Raw heartbeat timestamps for all registered agents."""
    now = time.time()
    heartbeats: dict[str, Any] = {}
    for name, ts in list(_agent_heartbeats.items()):
        heartbeats[name] = {
            "last_seen_ts": ts,
            "age_s": round(now - ts, 1) if ts else None,
        }
    return {"heartbeats": heartbeats}


@router.get("/api/monitoring")
async def get_monitoring() -> dict[str, Any]:
    """
    Combined monitoring payload: agent statuses + database metrics.
    Single endpoint the monitoring page can call to get everything it needs.
    """
    now = time.time()
    agents: dict[str, Any] = {}
    for name, last_seen in list(_agent_heartbeats.items()):
        if last_seen is None:
            status = "unknown"
        elif now - last_seen < 90:
            status = "healthy"
        else:
            status = "stale"
        agents[name] = {
            "name": name,
            "status": status,
            "last_heartbeat_age_s": round(now - last_seen, 1) if last_seen else None,
        }

    pool = get_pool()
    metrics = {"active_workflows": 0, "pending_approvals": 0, "healthy_agents": 0, "total_agents": len(agents)}
    if pool:
        async with pool.acquire() as conn:
            metrics["active_workflows"] = await conn.fetchval(
                "SELECT COUNT(*) FROM placements WHERE status IN ('pending','pending_supervisor','approved')"
            ) or 0
            metrics["pending_approvals"] = await conn.fetchval(
                "SELECT COUNT(*) FROM placements WHERE status IN ('pending','pending_supervisor')"
            ) or 0

    healthy_count = sum(1 for a in agents.values() if a["status"] == "healthy")
    metrics["healthy_agents"] = healthy_count

    return {"agents": agents, "metrics": metrics}
