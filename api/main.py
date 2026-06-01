"""
Artifex REST API

Endpoints:
  POST /swarm/run              – submit a goal, start a Temporal workflow
  GET  /swarm/status/{wf_id}   – query workflow state
  POST /chat                   – plain-text question → plain-text answer (blocking, 60 s timeout)
  GET  /health                 – liveness probe
  GET  /metrics                – Prometheus metrics
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid

import threading as _threading
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from dotenv import load_dotenv

load_dotenv()  # load .env before any os.getenv() calls

# Validate required env vars at startup so failures are obvious
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://artifex:artifex123@postgres:5432/placements")

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field
from temporalio.client import (
    WorkflowExecutionStatus,
    WorkflowQueryFailedError,
    WorkflowQueryRejectedError,
)
from temporalio.service import RPCError

from nats_client.client import NATSManager
from services.capacity import available_capacity_sql
from .dependencies import get_settings, get_temporal_client

logger = structlog.get_logger()

# ── PostgreSQL connection pool ────────────────────────────────────────────────
_db_pool: asyncpg.Pool | None = None


async def _init_db_pool() -> None:
    """Create the asyncpg connection pool and ensure the schema exists."""
    global _db_pool
    _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with _db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS placements (
                workflow_id      TEXT PRIMARY KEY,
                child_id         TEXT NOT NULL,
                family_id        TEXT,
                family_json      JSONB,
                risk_score       REAL DEFAULT 0.0,
                risk_explanation TEXT,
                match_explanation TEXT,
                last_notes       TEXT,
                status           TEXT DEFAULT 'active',
                created_at       TIMESTAMP DEFAULT NOW(),
                updated_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        # Add match_explanation column if upgrading an existing DB
        await conn.execute("""
            ALTER TABLE placements
            ADD COLUMN IF NOT EXISTS match_explanation TEXT
        """)
        await conn.execute("""
            ALTER TABLE placements
            ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'
        """)
        # Remove NOT NULL constraints from older schemas that used fake placeholders
        await conn.execute("""
            ALTER TABLE placements
            ALTER COLUMN family_id DROP NOT NULL
        """)
        await conn.execute("""
            ALTER TABLE placements
            ALTER COLUMN family_json DROP NOT NULL
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_child_id   ON placements(child_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_risk_score ON placements(risk_score DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_status ON placements(status)"
        )
        # ── Workflow events / status tables for realtime tracking
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_events (
                id          SERIAL PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                stage       TEXT NOT NULL,
                status      TEXT NOT NULL,
                data        JSONB,
                timestamp   TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_wf_events_wfid ON workflow_events(workflow_id)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_status (
                workflow_id   TEXT PRIMARY KEY,
                status        TEXT NOT NULL,
                current_stage TEXT,
                progress      INT DEFAULT 0,
                metadata      JSONB,
                updated_at    TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS placement_predictions (
                id                  SERIAL PRIMARY KEY,
                workflow_id         TEXT NOT NULL,
                child_id            TEXT NOT NULL,
                recommended         JSONB NOT NULL,
                score               REAL,
                confidence          REAL,
                risk_score          REAL DEFAULT 0.0,
                feature_importance  JSONB,
                top_matches         JSONB,
                model_version       TEXT,
                created_at          TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            ALTER TABLE placement_predictions
            ADD COLUMN IF NOT EXISTS risk_score REAL DEFAULT 0.0
        """)
        await conn.execute("""
            ALTER TABLE placement_predictions
            ADD COLUMN IF NOT EXISTS feature_importance JSONB
        """)
        await conn.execute("""
            ALTER TABLE placement_predictions
            ADD COLUMN IF NOT EXISTS top_matches JSONB
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ml_inference_logs (
                id            SERIAL PRIMARY KEY,
                workflow_id   TEXT,
                child_id      TEXT,
                payload       JSONB,
                result        JSONB,
                model_version TEXT,
                timestamp     TIMESTAMP DEFAULT NOW()
            )
        """)
        # ── Foster families table (used by /api/foster_home and /api/search_families)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS families (
                id                   SERIAL PRIMARY KEY,
                family_id            TEXT UNIQUE,
                name                 TEXT NOT NULL,
                location             TEXT DEFAULT '',
                latitude             DOUBLE PRECISION,
                longitude            DOUBLE PRECISION,
                capacity             INT  DEFAULT 1,
                available_capacity   INT  DEFAULT 1,  -- deprecated; capacity is computed from active_placements
                total_capacity       INT  DEFAULT 1,
                active               BOOLEAN DEFAULT TRUE,
                experience           TEXT DEFAULT 'new',   -- legacy
                experience_level     TEXT DEFAULT 'new',
                specializations      TEXT DEFAULT '',
                languages            TEXT DEFAULT '',      -- legacy
                languages_arr        TEXT[] DEFAULT '{}'::text[],
                special_needs_trained   BOOLEAN DEFAULT FALSE,
                accepts_siblings        BOOLEAN DEFAULT FALSE,
                sibling_group_capable  BOOLEAN DEFAULT FALSE,
                home_type            TEXT DEFAULT 'family',
                emergency_available     BOOLEAN DEFAULT FALSE,
                max_age              INT  DEFAULT 18,
                can_take_siblings    BOOLEAN DEFAULT FALSE,
                has_animals          BOOLEAN DEFAULT FALSE,
                created_at           TIMESTAMP DEFAULT NOW(),
                updated_at           TIMESTAMP DEFAULT NOW()
            )
        """)
        # Add family_id column if upgrading from an older schema
        await conn.execute("""
            ALTER TABLE families
            ADD COLUMN IF NOT EXISTS family_id TEXT
        """)
        await conn.execute("""
            ALTER TABLE families
            ADD COLUMN IF NOT EXISTS max_age INT DEFAULT 18
        """)
        await conn.execute("""
            ALTER TABLE families
            ADD COLUMN IF NOT EXISTS can_take_siblings BOOLEAN DEFAULT FALSE
        """)
        await conn.execute("""
            ALTER TABLE families
            ADD COLUMN IF NOT EXISTS has_animals BOOLEAN DEFAULT FALSE
        """)
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS total_capacity INT DEFAULT 1")
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE")
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS experience_level TEXT DEFAULT 'new'")
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS languages_arr TEXT[] DEFAULT '{}'::text[]")
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS sibling_group_capable BOOLEAN DEFAULT FALSE")
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
        await conn.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS home_type TEXT DEFAULT 'family'")
        # Backfill v2 fields from legacy columns
        await conn.execute("UPDATE families SET total_capacity = capacity WHERE total_capacity IS NULL")
        await conn.execute("UPDATE families SET experience_level = experience WHERE experience_level IS NULL")
        await conn.execute(
            "UPDATE families SET sibling_group_capable = (can_take_siblings OR accepts_siblings) "
            "WHERE sibling_group_capable = FALSE AND (can_take_siblings OR accepts_siblings) = TRUE"
        )
        await conn.execute(
            "UPDATE families "
            "SET languages_arr = string_to_array(languages, ',') "
            "WHERE (languages_arr IS NULL OR array_length(languages_arr, 1) IS NULL) AND languages IS NOT NULL AND languages <> ''"
        )
        # Set a unique family_id for any existing rows that don't have one
        await conn.execute("""
            UPDATE families
            SET family_id = 'F-' || id
            WHERE family_id IS NULL
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_families_location ON families(location)"
        )
        # ── Children table (intake records) ───────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS children (
                child_id         TEXT PRIMARY KEY,
                first_name       TEXT DEFAULT '',
                last_name        TEXT DEFAULT '',
                age              INT,
                gender           TEXT,
                special_needs    BOOLEAN DEFAULT FALSE,
                sibling_group    BOOLEAN DEFAULT FALSE,
                sibling_count    INT DEFAULT 0,
                location         TEXT DEFAULT '',
                languages        TEXT DEFAULT '',
                languages_arr    TEXT[] DEFAULT '{}'::text[],
                medical_needs    TEXT DEFAULT '',
                behavioral_support TEXT DEFAULT '',
                intake_reason    TEXT DEFAULT '',
                emergency_level  TEXT DEFAULT 'normal',
                school_continuity BOOLEAN DEFAULT FALSE,
                case_notes       TEXT DEFAULT '',
                notes            TEXT DEFAULT '',  -- legacy/backwards-compat (deprecated)
                created_at       TIMESTAMP DEFAULT NOW(),
                updated_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        # Add missing columns when upgrading an older DB
        await conn.execute("ALTER TABLE children ADD COLUMN IF NOT EXISTS first_name TEXT DEFAULT ''")
        await conn.execute("ALTER TABLE children ADD COLUMN IF NOT EXISTS last_name TEXT DEFAULT ''")
        await conn.execute("ALTER TABLE children ADD COLUMN IF NOT EXISTS sibling_count INT DEFAULT 0")
        await conn.execute("ALTER TABLE children ADD COLUMN IF NOT EXISTS school_continuity BOOLEAN DEFAULT FALSE")
        await conn.execute("ALTER TABLE children ADD COLUMN IF NOT EXISTS languages_arr TEXT[] DEFAULT '{}'::text[]")
        await conn.execute("ALTER TABLE children ADD COLUMN IF NOT EXISTS case_notes TEXT DEFAULT ''")
        # Backfill case_notes from legacy notes when present
        await conn.execute(
            "UPDATE children SET case_notes = notes WHERE (case_notes IS NULL OR case_notes = '') AND notes IS NOT NULL AND notes <> ''"
        )
        # Backfill languages_arr from legacy CSV string when present
        await conn.execute(
            "UPDATE children "
            "SET languages_arr = string_to_array(languages, ',') "
            "WHERE (languages_arr IS NULL OR array_length(languages_arr, 1) IS NULL) AND languages IS NOT NULL AND languages <> ''"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_children_age ON children(age)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_children_location ON children(location)"
        )
        # ── Active placements table (for capacity tracking) ────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_placements (
                id               SERIAL PRIMARY KEY,
                workflow_id      TEXT NOT NULL,
                child_id         TEXT NOT NULL,
                family_id        TEXT,
                placement_start  TIMESTAMP DEFAULT NOW(),
                placement_end    TIMESTAMP,
                status           TEXT DEFAULT 'active',
                created_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        # Ensure pending rows are possible (before a family is selected)
        await conn.execute("ALTER TABLE active_placements ALTER COLUMN family_id DROP NOT NULL")
        # Provide idempotency for workflow_id upserts
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_ap_workflow_id ON active_placements(workflow_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ap_workflow_id ON active_placements(workflow_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ap_family_id  ON active_placements(family_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ap_status     ON active_placements(status)"
        )

        # ── Placement history table (training data for ML) ────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS placement_history (
                id               SERIAL PRIMARY KEY,
                child_id         TEXT,
                family_id        TEXT,
                placement_start  DATE,
                placement_end    DATE,
                outcome          TEXT,
                disruption       BOOLEAN DEFAULT FALSE,
                disruption_reason TEXT,
                duration_days    INT,
                created_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ph_child_id  ON placement_history(child_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ph_family_id ON placement_history(family_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ph_dates ON placement_history(placement_start, placement_end)"
        )
        # Add duration_days column if upgrading from an older schema
        await conn.execute("""
            ALTER TABLE placement_history
            ADD COLUMN IF NOT EXISTS duration_days INT
        """)
        # ── Check-ins table (real-time risk monitoring data) ──────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS check_ins (
                id                SERIAL PRIMARY KEY,
                child_id          TEXT NOT NULL,
                placement_id      TEXT,
                mood_score        INT DEFAULT 3,
                incident_reported BOOLEAN DEFAULT FALSE,
                notes             TEXT DEFAULT '',
                timestamp         TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_checkins_child_id ON check_ins(child_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_checkins_timestamp ON check_ins(timestamp DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_checkins_placement_id ON check_ins(placement_id)"
        )
        # ── Audit log table ───────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMP DEFAULT NOW(),
                user_id     TEXT,
                role        TEXT,
                action      TEXT NOT NULL,
                target_type TEXT,
                target_id   TEXT,
                details     JSONB,
                ip_address  TEXT,
                user_agent  TEXT
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_type, target_id)"
        )
    logger.info("api.db_pool_ready", url=DATABASE_URL.split("@")[-1])


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


async def store_workflow_event(workflow_id: str, stage: str, status: str, data: dict | None = None) -> None:
    """Persist a workflow event to the workflow_events table and update workflow_status."""
    if _db_pool is None:
        logger.warning("api.store_workflow_event.no_pool")
        return
    safe_data = data or {}
    async with _db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO workflow_events (workflow_id, stage, status, data) VALUES ($1, $2, $3, $4::jsonb)",
            workflow_id, stage, status, json.dumps(safe_data),
        )
        # Extract progress from data dict if present, default to 0
        progress = int(safe_data.get("progress", 0))
        await conn.execute(
            "INSERT INTO workflow_status (workflow_id, status, current_stage, progress, metadata, updated_at) VALUES ($1,$2,$3,$4,$5::jsonb,NOW())"
            " ON CONFLICT (workflow_id) DO UPDATE SET status=EXCLUDED.status, current_stage=EXCLUDED.current_stage, progress=EXCLUDED.progress, metadata=COALESCE(EXCLUDED.metadata, workflow_status.metadata), updated_at=NOW()",
            workflow_id, status, stage, progress, json.dumps(safe_data),
        )


async def get_workflow_timeline(workflow_id: str, limit: int = 100) -> list[dict]:
    if _db_pool is None:
        return []
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage, status, data, timestamp FROM workflow_events WHERE workflow_id = $1 ORDER BY timestamp ASC LIMIT $2",
            workflow_id, limit,
        )
    return [dict(r) for r in rows]


async def get_workflow_status_db(workflow_id: str) -> dict | None:
    if _db_pool is None:
        return None
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT workflow_id, status, current_stage, progress, metadata, updated_at FROM workflow_status WHERE workflow_id = $1",
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
            """
            INSERT INTO ml_inference_logs
                (workflow_id, child_id, payload, result, model_version)
            VALUES ($1,$2,$3::jsonb,$4::jsonb,$5)
            """,
            workflow_id,
            child_id,
            json.dumps(payload),
            json.dumps(result),
            model_version,
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
            """
            INSERT INTO placement_predictions
                (workflow_id, child_id, recommended, score, confidence,
                 risk_score, feature_importance, top_matches, model_version)
            VALUES ($1,$2,$3::jsonb,$4,$5,$6,$7::jsonb,$8::jsonb,$9)
            """,
            workflow_id,
            child_id,
            json.dumps(recommended),
            score,
            confidence,
            risk_score,
            json.dumps(feature_importance) if feature_importance else None,
            json.dumps(top_matches) if top_matches else None,
            model_version,
        )


async def get_latest_prediction(workflow_id: str) -> dict | None:
    if _db_pool is None:
        return None
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT recommended, score, confidence, risk_score,
                   feature_importance, top_matches, model_version, created_at
            FROM placement_predictions
            WHERE workflow_id = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            workflow_id,
        )
    if not row:
        return None
    result = dict(row)
    # asyncpg returns JSONB columns as str by default — parse them
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
                ws.status AS status,
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
                SELECT recommended, score, confidence, risk_score, feature_importance, top_matches
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
            record["foster_family_name"] = record.get("foster_family_name") or family.get("name")
            record["location"] = record.get("location") or family.get("location")
            record["capacity"] = record.get("capacity") or family.get("capacity")

        recommended = record.get("recommended")
        if recommended is not None:
            if isinstance(recommended, dict):
                record["recommended_family"] = recommended.get("family") or recommended.get("name")
                if record.get("capacity") is None:
                    record["capacity"] = recommended.get("capacity") or recommended.get("available_capacity")
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

        if record.get("status") is None and record.get("workflow_status") is not None:
            record["status"] = record["workflow_status"]

        if record.get("confidence_score") is None and record.get("confidence") is not None:
            record["confidence_score"] = record.get("confidence")

        if record.get("predicted_risk_score") is not None:
            record["risk_score"] = record.get("predicted_risk_score")

        result.append(record)

    logger.info("placements.response", count=len(result))
    return result

# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter("artifex_api_requests_total", "Total API requests", ["endpoint", "status"])
REQUEST_LATENCY = Histogram("artifex_api_latency_seconds", "API request latency", ["endpoint"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4096, description="Natural language goal")
    max_retries: int = Field(default=3, ge=0, le=10)


class RunResponse(BaseModel):
    workflow_id: str
    trace_id: str
    status: str = "started"
    message: str = "Workflow submitted successfully"


class StatusResponse(BaseModel):
    workflow_id: str
    status: str
    result: Any = None


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast if required env vars are missing
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. "
            "Add it to your .env file or export it in your shell."
        )

    # Initialise PostgreSQL connection pool
    await _init_db_pool()

    # Connect NATS on startup
    manager = NATSManager(NATS_URL)
    await manager.connect()
    logger.info("api.startup", nats_url=NATS_URL, groq_model="llama-3.1-8b-instant")
    # Subscribe to foster.placements from the temporal-worker
    placement_task   = asyncio.create_task(_placement_subscriber(manager))
    heartbeat_task   = asyncio.create_task(_heartbeat_subscriber(manager))
    # Start background data refresh task (every 15 minutes)
    from scripts.load_afcars_data import background_refresh  # noqa: PLC0415
    refresh_task = asyncio.create_task(background_refresh(interval_seconds=900))
    yield
    placement_task.cancel()
    heartbeat_task.cancel()
    refresh_task.cancel()
    await manager.close()
    logger.info("api.shutdown")


app = FastAPI(
    title="Artifex Agent Swarm API",
    description="Production multi-agent system powered by LangGraph + NATS + Temporal",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the Next.js dev server (port 3000) and any localhost origin to call the API.
# In production, replace "*" with your actual frontend domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",

        # Vite frontend
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auto-instrument FastAPI with OpenTelemetry
FastAPIInstrumentor.instrument_app(app)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/swarm/run", response_model=RunResponse, status_code=202)
async def run_swarm(
    request: RunRequest,
    settings: dict = Depends(get_settings),
) -> RunResponse:
    """
    Submit a natural-language goal to the agent swarm.
    Returns a workflow_id and trace_id for tracking.
    """
    workflow_id = f"artifex-{uuid.uuid4().hex[:12]}"
    trace_id = uuid.uuid4().hex

    logger.info("api.run_swarm", goal=request.goal[:80], workflow_id=workflow_id)

    try:
        client = await get_temporal_client()
        await client.start_workflow(
            "ArtifexSwarmWorkflow",
            request.goal,
            id=workflow_id,
            task_queue=settings["temporal_task_queue"],
        )
        REQUEST_COUNT.labels(endpoint="/swarm/run", status="202").inc()
        return RunResponse(workflow_id=workflow_id, trace_id=trace_id)

    except Exception as exc:  # noqa: BLE001
        logger.exception("api.run_swarm.error", error=str(exc))
        REQUEST_COUNT.labels(endpoint="/swarm/run", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {exc}") from exc


@app.get("/swarm/status/{workflow_id}", response_model=StatusResponse)
async def get_status(workflow_id: str) -> StatusResponse:
    """Query the current state of a running or completed workflow."""
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        status_map = {
            WorkflowExecutionStatus.RUNNING: "running",
            WorkflowExecutionStatus.COMPLETED: "completed",
            WorkflowExecutionStatus.FAILED: "failed",
            WorkflowExecutionStatus.CANCELED: "canceled",
            WorkflowExecutionStatus.TERMINATED: "terminated",
            WorkflowExecutionStatus.TIMED_OUT: "timed_out",
        }
        status_str = status_map.get(desc.status, "unknown")

        result = None
        if desc.status == WorkflowExecutionStatus.COMPLETED:
            result = await handle.result()

        REQUEST_COUNT.labels(endpoint="/swarm/status", status="200").inc()
        return StatusResponse(workflow_id=workflow_id, status=status_str, result=result)

    except Exception as exc:  # noqa: BLE001
        logger.exception("api.get_status.error", workflow_id=workflow_id, error=str(exc))
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc


@app.get("/health")
async def health() -> dict[str, str]:
    """Kubernetes liveness / readiness probe."""
    return {"status": "ok", "service": "artifex-api"}


@app.post("/chat", response_class=PlainTextResponse)
async def chat(request: Request, settings: dict = Depends(get_settings)) -> str:
    """
    Plain-text conversational endpoint.

    Send a question as raw text body (Content-Type: text/plain) or as a
    JSON body {"goal": "..."}.  Returns a plain-text answer with sources.

    Blocks until the workflow completes (polls every 2 s, 60 s hard timeout).

    Example:
        curl -X POST http://localhost:8000/chat \\
             -H "Content-Type: text/plain" \\
             -d "Who won the latest Formula 1 race?"
    """
    # ── Parse body (text/plain or JSON) ──────────────────────────────────────
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        question = body.get("goal") or body.get("question") or body.get("query", "")
    else:
        raw = await request.body()
        question = raw.decode("utf-8").strip()

    if not question:
        raise HTTPException(status_code=400, detail="Empty question – send text in the request body")

    workflow_id = f"chat-{uuid.uuid4().hex[:12]}"
    logger.info("api.chat", question=question[:80], workflow_id=workflow_id)

    # ── Start Temporal workflow ───────────────────────────────────────────────
    try:
        client = await get_temporal_client()
        handle = await client.start_workflow(
            "ArtifexSwarmWorkflow",
            question,
            id=workflow_id,
            task_queue=settings["temporal_task_queue"],
        )
        REQUEST_COUNT.labels(endpoint="/chat", status="202").inc()
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.chat.start_error", error=str(exc))
        REQUEST_COUNT.labels(endpoint="/chat", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {exc}") from exc

    # ── Poll for completion (max 60 s) ────────────────────────────────────────
    deadline = time.monotonic() + 60.0
    result: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        try:
            desc = await handle.describe()
            from temporalio.client import WorkflowExecutionStatus as WES
            if desc.status == WES.COMPLETED:
                result = await handle.result()
                break
            elif desc.status in (WES.FAILED, WES.CANCELED, WES.TERMINATED, WES.TIMED_OUT):
                raise HTTPException(
                    status_code=500,
                    detail=f"Workflow ended with status: {desc.status.name}",
                )
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            pass  # workflow not yet visible – keep polling
        await asyncio.sleep(2)

    if result is None:
        REQUEST_COUNT.labels(endpoint="/chat", status="504").inc()
        raise HTTPException(
            status_code=504,
            detail=f"Workflow {workflow_id} did not complete within 60 seconds. "
                   f"Poll GET /swarm/status/{workflow_id} for the result.",
        )

    REQUEST_COUNT.labels(endpoint="/chat", status="200").inc()

    # ── Format plain-text response ────────────────────────────────────────────
    final = result.get("final_answer", result)

    if isinstance(final, dict):
        answer  = final.get("answer", "")
        sources = final.get("sources", [])
    elif isinstance(final, list) and final:
        # list of document dicts from retriever
        answer  = final[0].get("payload", {}).get("text", str(final[0]))
        sources = []
    else:
        answer  = str(final) if final else "No answer returned."
        sources = []

    output = answer or "No answer returned."
    if sources:
        source_lines = "\n".join(
            f"  • {s.get('title', s.get('url', ''))}: {s.get('url', '')}"
            for s in sources
            if isinstance(s, dict)
        )
        output += f"\n\nSources:\n{source_lines}"

    return output



# ── NATS heartbeat subscriber ────────────────────────────────────────────────

async def _heartbeat_subscriber(manager: NATSManager) -> None:
    """
    Background task: subscribe to agent.*.heartbeat and update the in-process
    heartbeat store so /agent/status/<name> can report liveness.
    Agents publish {"agent": "<name>", "ts": <unix_float>} every 30 s.
    """
    async def _handle(msg: dict) -> None:
        agent_name = msg.get("agent") or msg.get("name", "unknown")
        with _heartbeat_lock:
            _agent_heartbeats[agent_name] = time.time()
        logger.debug("api.heartbeat_received", agent=agent_name)

    await manager.subscribe("agent.*.heartbeat", _handle)
    logger.info("api.nats_subscriber_ready", subject="agent.*.heartbeat")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass


# ── NATS placement subscriber ─────────────────────────────────────────────────

async def _placement_subscriber(manager: NATSManager) -> None:
    """
    Background task: subscribe to foster.placements and upsert into PostgreSQL.
    Also keeps the in-process cache in sync for low-latency WebSocket reads.
    Runs for the lifetime of the API process.
    """

    async def _handle(msg: dict) -> None:
        child_id = msg.get("child_id", "unknown")
        # Persist to PostgreSQL
        await store_placement(msg)
        # Persist workflow event and prediction info for realtime tracking
        wf_id = msg.get("workflow_id") or msg.get("workflowId") or f"foster-{child_id}"
        try:
            await store_workflow_event(wf_id, stage="placement_matched", status="completed", data=msg)
        except Exception:  # noqa: BLE001
            logger.exception("api._placement_subscriber.store_event_error", workflow_id=wf_id)
        # Persist a placement_prediction record (family recommendation + score)
        try:
            recommended = {"family": msg.get("family"), "explanation": msg.get("match_explanation")}
            await store_prediction(
                wf_id,
                child_id,
                recommended,
                score=msg.get("match_score") or msg.get("score") or msg.get("risk_score"),
                confidence=msg.get("confidence"),
                risk_score=msg.get("risk_score"),
                feature_importance=msg.get("feature_importance"),
                top_matches=msg.get("top_matches"),
                model_version=msg.get("model_version"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("api._placement_subscriber.store_prediction_error", workflow_id=wf_id)
        # Update in-process cache for WebSocket push
        global _api_latest_placements
        with _placements_lock:
            for i, p in enumerate(_api_latest_placements):
                if p.get("child_id") == child_id:
                    _api_latest_placements[i] = msg
                    break
            else:
                _api_latest_placements.append(msg)
            _api_latest_placements = _api_latest_placements[-50:]
        # Publish live event
        try:
            family_name = (msg.get("family") or {}).get("name", "?")
            risk = msg.get("risk_score", 0)
            nats_mgr = NATSManager(NATS_URL)
            await nats_mgr.publish("events.live.placement_recommended", {
                "event": "placement_recommended",
                "child_id": child_id,
                "workflow_id": wf_id,
                "family_name": family_name,
                "family_id": (msg.get("family") or {}).get("family_id", ""),
                "risk_score": risk,
                "match_score": msg.get("match_score"),
                "confidence": msg.get("confidence"),
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            })
        except Exception:  # noqa: BLE001
            pass

        logger.info("api.placement_received_nats",
                    child_id=child_id, total=len(_api_latest_placements))

    await manager.subscribe("foster.placements", _handle)
    logger.info("api.nats_subscriber_ready", subject="foster.placements")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Foster Care Swarm endpoints
# ═══════════════════════════════════════════════════════════════════════════════

# In-process placement store – populated by the temporal-worker via HTTP push.
# The worker and API run in separate containers so they cannot share memory;
# the worker calls POST /foster/internal/placement after each match.
_api_latest_placements: list[dict[str, Any]] = []
_placements_lock = _threading.Lock()

# Agent heartbeat store – updated by NATS subscriber
_agent_heartbeats: dict[str, float] = {}
_heartbeat_lock = _threading.Lock()

# Idempotency set – prevents duplicate event processing
# In production replace with Redis SETNX with TTL.
_processed_events: set[str] = set()

class FosterEventRequest(BaseModel):
    type: str = Field(..., description="child_referral | check_in | close_placement | family_update")
    data: dict[str, Any] = Field(default_factory=dict)


@app.post("/events", status_code=202)
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

    Examples:
      {"type": "child_referral", "data": {"child_id": "C001", "age": 8, "siblings": 1, "special_needs": false}}
      {"type": "check_in",       "data": {"workflow_id": "foster-C001", "score": 4, "notes": "Settling in well"}}
      {"type": "close_placement","data": {"workflow_id": "foster-C001"}}
    """
    import hashlib as _hl
    import json as _j
    _eid = _hl.md5(_j.dumps({"type": event.type, "data": event.data}, sort_keys=True).encode()).hexdigest()
    if _eid in _processed_events:
        return {"status": "duplicate", "event_id": _eid}
    _processed_events.add(_eid)
    if len(_processed_events) > 10_000:   # prevent unbounded growth
        _processed_events.clear()

    event_type = event.type
    data       = event.data

    logger.info("api.foster_event", event_type=event_type, data=data)

    # ── child_referral: start a new Temporal workflow ─────────────────────────
    if event_type == "child_referral":
        child_id    = data.get("child_id")
        if not child_id:
            raise HTTPException(status_code=422, detail="child_referral requires data.child_id")

        workflow_id = f"foster-{child_id}"
        try:
            client = await get_temporal_client()
            logger.info("api.foster_event.starting_workflow", workflow_id=workflow_id, child_id=child_id)
            await client.start_workflow(
                "FosterPlacementWorkflow",
                data,
                id=workflow_id,
                task_queue=settings["temporal_task_queue"],
            )
            logger.info("api.foster_event.started_workflow", workflow_id=workflow_id, child_id=child_id)
        except Exception as exc:  # noqa: BLE001
            # Workflow already exists for this child – idempotent
            if "already" in str(exc).lower() or "exists" in str(exc).lower():
                pass
            else:
                logger.exception("api.foster_event.start_error", error=str(exc))
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Save to children table
        if _db_pool is not None:
            try:
                async with _db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO children
                            (child_id, age, gender, special_needs, sibling_group,
                             location, languages, medical_needs, behavioral_support,
                             emergency_level, notes, intake_reason)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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

        # Publish live event
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

        REQUEST_COUNT.labels(endpoint="/events", status="202").inc()
        return {"status": "workflow_started", "workflow_id": workflow_id}

    # ── close_placement: mark placement as closed in DB before publishing ────
    if event_type == "close_placement":
        workflow_id = data.get("workflow_id", "")
        if workflow_id and _db_pool is not None:
            try:
                async with _db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE placements SET status = 'closed', updated_at = NOW() WHERE workflow_id = $1",
                        workflow_id,
                    )
                    logger.info(
                        "api.foster_event.placement_closed",
                        workflow_id=workflow_id,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("api.foster_event.close_update_error", error=str(exc))

    # ── check_in: persist check-in to DB for real-time risk monitoring ───────
    if event_type == "check_in":
        workflow_id = data.get("workflow_id", "")
        child_id = data.get("child_id", "")
        if not child_id and workflow_id.startswith("foster-"):
            child_id = workflow_id[len("foster-"):]
        mood_score = int(data.get("score", data.get("mood_score", 3)))
        notes = data.get("notes", "")
        incident_reported = bool(
            data.get("incident_reported", False)
            or any(w in notes.lower() for w in ("incident", "emergency", "runaway", "self-harm", "crisis"))
        )
        if child_id and _db_pool is not None:
            try:
                async with _db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO check_ins
                            (child_id, placement_id, mood_score, incident_reported, notes)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        child_id,
                        workflow_id,
                        mood_score,
                        incident_reported,
                        notes,
                    )
                    logger.info(
                        "api.foster_event.check_in_stored",
                        child_id=child_id,
                        mood=mood_score,
                        incident=incident_reported,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("api.foster_event.check_in_store_error", error=str(exc))

    # ── All other event types: publish to NATS for FosterMonitorAgent ─────────
    subject = f"events.{event_type}"
    try:
        manager = NATSManager(NATS_URL)
        await manager.publish(subject, data)
        REQUEST_COUNT.labels(endpoint="/events", status="202").inc()
        return {"status": "event_published", "subject": subject}
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.foster_event.publish_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/foster/placements")
async def get_placements() -> dict[str, Any]:
    """
    Return placement snapshot from PostgreSQL (50 most recent, by updated_at).
    Falls back to the in-process cache if the DB is unavailable.
    """
    try:
        placements = await get_all_placements()
        logger.info("placements.response", count=len(placements))
        return {"placements": placements, "count": len(placements)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.get_placements.db_error", error=str(exc))
        with _placements_lock:
            snapshot = list(_api_latest_placements)
        logger.info("placements.response", count=len(snapshot), source="cache")
        return {"placements": snapshot, "count": len(snapshot), "source": "cache"}


@app.post("/foster/internal/placement", include_in_schema=False)
async def receive_placement(placement: dict) -> dict[str, str]:
    """
    Internal endpoint called by publish_match_activity in the temporal-worker
    container to push a placement update into PostgreSQL and the in-process cache.
    Not exposed in the public OpenAPI docs.
    """
    global _api_latest_placements
    child_id = placement.get("child_id", "unknown")
    # Persist to PostgreSQL
    await store_placement(placement)
    # Persist prediction and workflow event
    wf_id = placement.get("workflow_id") or f"foster-{child_id}"
    try:
        await store_workflow_event(
            wf_id,
            stage="placement_matched",
            status="completed",
            data=placement,
        )
    except Exception:  # noqa: BLE001
        logger.exception("api.receive_placement.store_event_error", workflow_id=wf_id)
    try:
        recommended = {"family": placement.get("family")}
        await store_prediction(
            wf_id,
            child_id,
            recommended,
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
    with _placements_lock:
        for i, p in enumerate(_api_latest_placements):
            if p.get("child_id") == child_id:
                _api_latest_placements[i] = placement
                break
        else:
            _api_latest_placements.append(placement)
        _api_latest_placements = _api_latest_placements[-50:]
    logger.info("api.receive_placement", child_id=child_id, total=len(_api_latest_placements))
    return {"status": "ok"}


class WorkflowEventRequest(BaseModel):
    workflow_id: str
    stage: str
    status: str
    data: dict[str, Any] = {}


@app.post("/foster/internal/workflow_event", include_in_schema=False)
async def receive_workflow_event(event: WorkflowEventRequest) -> dict[str, str]:
    """
    Internal endpoint called by record_workflow_event_activity to persist
    a workflow event and update the workflow_status table.
    """
    try:
        await store_workflow_event(
            event.workflow_id,
            stage=event.stage,
            status=event.status,
            data=event.data,
        )
        logger.info(
            "api.receive_workflow_event",
            workflow_id=event.workflow_id,
            stage=event.stage,
            status=event.status,
        )
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "api.receive_workflow_event.error",
            workflow_id=event.workflow_id,
            stage=event.stage,
            error=str(exc),
        )
        return {"status": "error", "detail": str(exc)}


class MlInferenceLogRequest(BaseModel):
    workflow_id: str
    child_id: str
    payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    model_version: str | None = None


@app.post("/foster/internal/ml_inference_log", include_in_schema=False)
async def receive_ml_inference_log(req: MlInferenceLogRequest) -> dict[str, str]:
    """Internal endpoint for placement_predict_activity to log ML inference."""
    try:
        await store_ml_inference_log(
            req.workflow_id,
            req.child_id,
            req.payload,
            req.result,
            req.model_version,
        )
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("api.ml_inference_log.error", workflow_id=req.workflow_id, error=str(exc))
        return {"status": "error", "detail": str(exc)}


@app.get("/agent/status/{agent_name}")
async def agent_status(agent_name: str) -> dict[str, Any]:
    """
    Return the last heartbeat timestamp for an agent.
    Agents publish to agent.<name>.heartbeat every 30 s.
    Status is 'healthy' if a heartbeat was seen in the last 90 s.
    """
    with _heartbeat_lock:
        last_seen = _agent_heartbeats.get(agent_name)
    now = time.time()
    if last_seen is None:
        status = "unknown"
        age    = None
    elif now - last_seen < 90:
        status = "healthy"
        age    = round(now - last_seen, 1)
    else:
        status = "stale"
        age    = round(now - last_seen, 1)
    return {"agent": agent_name, "status": status, "last_heartbeat_age_s": age}


@app.get("/foster/status/{workflow_id}")
async def get_foster_status(workflow_id: str) -> dict[str, Any]:
    """Query a running FosterPlacementWorkflow via Temporal query."""
    normalized_workflow_id = _normalize_foster_workflow_id(workflow_id)
    if normalized_workflow_id != workflow_id:
        logger.info(
            "api.get_foster_status.normalized_workflow_id",
            original_workflow_id=workflow_id,
            normalized_workflow_id=normalized_workflow_id,
        )
    workflow_id = normalized_workflow_id
    logger.info("api.get_foster_status.request", workflow_id=workflow_id)
    try:
        client = await get_temporal_client()
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.get_foster_status.temporal_connect_error", workflow_id=workflow_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Unable to connect to Temporal for workflow {workflow_id}",
        ) from exc

    handle = client.get_workflow_handle(workflow_id)
    try:
        status = await handle.query("get_status")
        # Enrich with DB-stored status, timeline and prediction if available
        timeline = await get_workflow_timeline(workflow_id, limit=200)
        wf_db = await get_workflow_status_db(workflow_id)
        prediction = await get_latest_prediction(workflow_id)

        # Merge sources: prefer DB prediction, then workflow query, then DB status
        recommended_family: Any = None
        match_score: float | None = None
        confidence_score: float | None = None
        risk_score: float | None = None
        feature_importance: list | None = None
        top_matches: list | None = None

        if prediction:
            rec = prediction.get("recommended")
            if isinstance(rec, dict):
                recommended_family = rec.get("family") or rec
            elif isinstance(rec, str):
                try:
                    rec_parsed = json.loads(rec)
                    recommended_family = rec_parsed.get("family") or rec_parsed
                except (json.JSONDecodeError, TypeError):
                    recommended_family = rec
            else:
                recommended_family = rec

            match_score = prediction.get("score") or None
            confidence_score = prediction.get("confidence") or None
            risk_score = prediction.get("risk_score") or None
            feature_importance = prediction.get("feature_importance") or None
            top_matches = prediction.get("top_matches") or None

        # Fall back to workflow query fields where DB prediction is missing
        wf_status = status if isinstance(status, dict) else {}
        if match_score is None:
            match_score = wf_status.get("match_score") or None
        if confidence_score is None:
            confidence_score = wf_status.get("confidence_score") or None
        if risk_score is None:
            risk_score = wf_status.get("risk_score") or None
        if feature_importance is None:
            feature_importance = wf_status.get("feature_importance") or None
        if recommended_family is None:
            recommended_family = wf_status.get("recommended_family") or None
        if top_matches is None:
            top_matches = wf_status.get("top_matches") or None

        capacity = None
        if isinstance(recommended_family, dict):
            capacity = recommended_family.get("capacity") or recommended_family.get("available_capacity")
        if capacity is None:
            capacity = wf_status.get("capacity")

        response = {
            "workflow_id": workflow_id,
            "status": (wf_db and wf_db.get("status")) or wf_status.get("status", "active"),
            "active": wf_status.get("active", True),
            "child_id": wf_status.get("child_id"),
            "family_id": wf_status.get("family_id"),
            "recommended_family": recommended_family.get("name") or recommended_family.get("family_id") if isinstance(recommended_family, dict) else recommended_family,
            "match_score": match_score,
            "confidence_score": confidence_score,
            "risk_score": risk_score,
            "capacity": capacity,
            "current_stage": wf_status.get("current_stage") or (wf_db and wf_db.get("current_stage")) or None,
            "progress": wf_status.get("progress") or (wf_db and wf_db.get("progress")) or 0,
            "timeline": timeline,
            "feature_importance": feature_importance,
            "top_matches": top_matches,
        }

        logger.info("api.get_foster_status.success", workflow_id=workflow_id, status=response)
        return response
    except WorkflowQueryRejectedError as exc:
        logger.warning("api.get_foster_status.workflow_not_found", workflow_id=workflow_id, error=str(exc))
        raise HTTPException(status_code=404, detail=f"Workflow not found or not queryable: {workflow_id}") from exc
    except RPCError as exc:
        message = str(exc).lower()
        if "workflow not found" in message or "not found" in message:
            logger.warning("api.get_foster_status.workflow_not_found", workflow_id=workflow_id, error=str(exc))
            raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc
        logger.exception("api.get_foster_status.rpc_error", workflow_id=workflow_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Temporal RPC error while querying workflow {workflow_id}",
        ) from exc
    except WorkflowQueryFailedError as exc:
        logger.exception("api.get_foster_status.query_failed", workflow_id=workflow_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Workflow query failed for {workflow_id}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.get_foster_status.unexpected_error", workflow_id=workflow_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected error querying workflow {workflow_id}",
        ) from exc


@app.get("/workflow/{workflow_id}")
async def workflow_summary(workflow_id: str) -> dict[str, Any]:
    """Return combined workflow status and latest placement/prediction info."""
    wf = await get_workflow_status_db(workflow_id)
    timeline = await get_workflow_timeline(workflow_id, limit=50)
    # fallback to Temporal query if DB has no status
    if not wf:
        try:
            client = await get_temporal_client()
            handle = client.get_workflow_handle(workflow_id)
            desc = await handle.describe()
            from temporalio.client import WorkflowExecutionStatus as WES
            status_map = {
                WES.RUNNING: "running",
                WES.COMPLETED: "completed",
                WES.FAILED: "failed",
                WES.CANCELED: "canceled",
                WES.TERMINATED: "terminated",
                WES.TIMED_OUT: "timed_out",
            }
            wf = {
                "workflow_id": workflow_id,
                "status": status_map.get(desc.status, "unknown"),
                "current_stage": None,
                "progress": 0,
                "updated_at": None,
            }
        except Exception:
            wf = {"workflow_id": workflow_id, "status": "unknown", "current_stage": None, "progress": 0}
    return {**wf, "timeline": timeline}


@app.get("/workflow/{workflow_id}/timeline")
async def workflow_timeline(workflow_id: str) -> dict[str, Any]:
    timeline = await get_workflow_timeline(workflow_id, limit=500)
    return {"workflow_id": workflow_id, "timeline": timeline}


@app.get("/workflow/{workflow_id}/progress")
async def workflow_progress(workflow_id: str) -> dict[str, Any]:
    wf = await get_workflow_status_db(workflow_id)
    if not wf:
        return {"workflow_id": workflow_id, "progress": 0}
    return {"workflow_id": workflow_id, "progress": wf.get("progress", 0), "status": wf.get("status")}


@app.websocket("/workflow/{workflow_id}/stream")
async def workflow_stream(websocket: WebSocket, workflow_id: str) -> None:
    """WebSocket that streams live workflow updates for a single workflow_id."""
    await websocket.accept()
    logger.info("ws.workflow.connected", workflow_id=workflow_id, client=str(websocket.client))
    try:
        while True:
            # Read latest status and recent timeline
            wf = await get_workflow_status_db(workflow_id)
            timeline = await get_workflow_timeline(workflow_id, limit=200)
            payload = {
                "workflow_id": workflow_id,
                "status": wf.get("status") if wf else "unknown",
                "current_stage": wf.get("current_stage") if wf else None,
                "progress": wf.get("progress") if wf else 0,
                "updated_at": wf.get("updated_at") if wf else None,
                "timeline": timeline,
            }
            try:
                await websocket.send_json(payload)
            except Exception:
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info("ws.workflow.disconnected", workflow_id=workflow_id)


def _normalize_foster_workflow_id(raw_id: str) -> str:
    if not isinstance(raw_id, str):
        return str(raw_id)

    trimmed = raw_id.strip()
    if trimmed.lower().startswith("foster-"):
        return trimmed

    # CHILD-123 => foster-123
    m = re.match(r"^CHILD-(\d+)$", trimmed, re.IGNORECASE)
    if m:
        return f"foster-{m.group(1)}"

    # CH-123 => foster-123
    m2 = re.match(r"^CH-(\d+)$", trimmed, re.IGNORECASE)
    if m2:
        return f"foster-{m2.group(1)}"

    # Pure digits => foster-<digits>
    if re.fullmatch(r"\d+", trimmed):
        return f"foster-{trimmed}"

    # Default: prefix with foster- preserving non-numeric IDs (e.g., CABC123)
    return f"foster-{trimmed}"


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for the live foster care dashboard.
    Pushes placement updates every 2 seconds, reading from PostgreSQL.

    Connect with:
      wscat -c ws://localhost:8000/ws/dashboard
      or open dashboard.py (Streamlit)
    """
    await websocket.accept()
    logger.info("ws.dashboard.connected", client=str(websocket.client))
    try:
        while True:
            try:
                placements = await get_all_placements()
            except Exception:  # noqa: BLE001
                # Fall back to in-process cache on DB error
                with _placements_lock:
                    placements = list(_api_latest_placements)
            await websocket.send_json({
                "placements": placements,
                "count":      len(placements),
            })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        logger.info("ws.dashboard.disconnected")


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket) -> None:
    """
    WebSocket endpoint that streams real-time agent log events to the dashboard.

    Subscribes to the NATS wildcard subject agent.*.log and forwards each
    message as a JSON frame:
      {"agent": "planner", "message": "...", "type": "info|warning|error|replan|vote|specialist|memory", "timestamp": "HH:MM:SS"}

    Agents publish to this subject via:
      await self.publish(f"agent.{self.name}.log", {"agent": ..., "message": ..., "type": ...})
    """
    await websocket.accept()
    logger.info("ws.logs.connected", client=str(websocket.client))

    # Keep a reference so the NATS callback can reach the websocket
    _ws = websocket

    async def _on_log(msg: dict) -> None:
        try:
            if not msg.get("timestamp"):
                msg["timestamp"] = __import__("datetime").datetime.now().strftime("%H:%M:%S")
            await _ws.send_json(msg)
        except Exception:  # noqa: BLE001
            pass  # client disconnected

    try:
        manager = NATSManager(NATS_URL)
        await manager.subscribe("agent.*.log", _on_log)
        logger.info("ws.logs.subscribed", subject="agent.*.log")
        # Keep the connection alive until the client disconnects
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping", "agent": "system", "message": "keepalive"})
            except Exception:  # noqa: BLE001
                break
    except WebSocketDisconnect:
        logger.info("ws.logs.disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.logs.error", error=str(exc))


@app.websocket("/ws/workflow")
async def websocket_workflow(websocket: WebSocket) -> None:
    """
    WebSocket endpoint that streams workflow step events to the timeline view.

    Subscribes to the NATS wildcard subject workflow.*.step and forwards each
    message as a JSON frame:
      {
        "workflow_id": "foster-C001",
        "step": "retriever",
        "status": "running|completed|failed|retrying",
        "attempt": 1,
        "message": "...",
        "timestamp": "HH:MM:SS"
      }
    """
    await websocket.accept()
    logger.info("ws.workflow.connected", client=str(websocket.client))

    _ws = websocket

    async def _on_step(msg: dict) -> None:
        try:
            if not msg.get("timestamp"):
                msg["timestamp"] = __import__("datetime").datetime.now().strftime("%H:%M:%S")
            await _ws.send_json(msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        manager = NATSManager(NATS_URL)
        await manager.subscribe("workflow.*.step", _on_step)
        logger.info("ws.workflow.subscribed", subject="workflow.*.step")
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping", "agent": "system", "message": "keepalive"})
            except Exception:  # noqa: BLE001
                break
    except WebSocketDisconnect:
        logger.info("ws.workflow.disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.workflow.error", error=str(exc))


# ── Live events WebSocket (NATS-backed push for the dashboard) ───────────────


@app.websocket("/ws/events")
async def websocket_live_events(websocket: WebSocket) -> None:
    """
    WebSocket endpoint that streams all live foster-care events to the dashboard.

    Subscribes to the NATS wildcard subject ``events.live.*`` and forwards
    every message as a JSON frame to every connected client.

    Event types pushed:
      child_referred       – new child entered the system
      ml_completed         – ML placement prediction finished
      placement_recommended – a family was recommended
      placement_approved   – supervisor approved the placement
      risk_increased       – a child's risk score rose significantly
      case_escalated       – high-risk alert triggered

    Connect from the dashboard:
      ws = new WebSocket("ws://localhost:8000/ws/events")
      ws.onmessage = (ev) => { const event = JSON.parse(ev.data); ... }
    """
    await websocket.accept()
    logger.info("ws.live_events.connected", client=str(websocket.client))

    _ws = websocket

    async def _on_event(msg: dict) -> None:
        try:
            if not msg.get("timestamp"):
                msg["timestamp"] = __import__("datetime").datetime.now().isoformat()
            await _ws.send_json(msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        manager = NATSManager(NATS_URL)
        await manager.subscribe("events.live.>", _on_event)
        logger.info("ws.live_events.subscribed", subject="events.live.>")
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping", "event": "keepalive"})
            except Exception:  # noqa: BLE001
                break
    except WebSocketDisconnect:
        logger.info("ws.live_events.disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.live_events.error", error=str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard API endpoints (live data from PostgreSQL)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard/metrics")
async def dashboard_metrics() -> dict[str, Any]:
    """Live dashboard metrics computed from PostgreSQL – no mock/hardcoded data."""
    if _db_pool is None:
        return {"active_workflows": 0, "pending_approvals": 0, "placements_matched": 0,
                "emergency_referrals": 0, "workflows_change": 0, "approvals_change": 0,
                "placements_change": 0, "emergency_change": 0}
    async with _db_pool.acquire() as conn:
        active_wf       = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE status IN ('pending','pending_supervisor','approved')")
        pending_approvals = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE status IN ('pending','pending_supervisor')")
        placements_total = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE status = 'approved'")
        emergency        = await conn.fetchval("SELECT COUNT(*) FROM children WHERE emergency_level = 'emergency'")
        wf_change        = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE created_at > NOW() - INTERVAL '24 hours'")
        apr_change       = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE status = 'pending' AND created_at > NOW() - INTERVAL '24 hours'")
        pl_change        = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE status = 'approved' AND created_at > NOW() - INTERVAL '24 hours'")
        em_change        = await conn.fetchval("SELECT COUNT(*) FROM children WHERE emergency_level = 'emergency' AND created_at > NOW() - INTERVAL '24 hours'")
    return {
        "active_workflows":   active_wf or 0,
        "pending_approvals":  pending_approvals or 0,
        "placements_matched": placements_total or 0,
        "emergency_referrals": emergency or 0,
        "workflows_change":   wf_change or 0,
        "approvals_change":   apr_change or 0,
        "placements_change":  pl_change or 0,
        "emergency_change":   em_change or 0,
    }


@app.get("/dashboard/risk-distribution")
async def dashboard_risk_distribution() -> dict[str, int]:
    """Risk score distribution computed from live placements table."""
    if _db_pool is None:
        return {"low": 0, "medium": 0, "high": 0, "critical": 0}
    async with _db_pool.acquire() as conn:
        low      = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE risk_score < 25")
        medium   = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE risk_score >= 25 AND risk_score < 50")
        high     = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE risk_score >= 50 AND risk_score < 75")
        critical = await conn.fetchval("SELECT COUNT(*) FROM placements WHERE risk_score >= 75")
    return {
        "low":      low or 0,
        "medium":   medium or 0,
        "high":     high or 0,
        "critical": critical or 0,
    }


@app.get("/dashboard/events")
async def dashboard_events() -> dict[str, list[dict]]:
    """Recent workflow events from the placements table."""
    events: list[dict] = []
    if _db_pool is not None:
        async with _db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.workflow_id, p.child_id, p.status, p.risk_score, p.created_at,
                       c.emergency_level
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
                    "message":        f"Placement {row['status']} for child {row.get('child_id', 'N/A')}",
                    "timestamp":      row["created_at"].isoformat() if row["created_at"] else "",
                })
    return {"events": events}


@app.get("/agent/status")
async def all_agent_statuses() -> dict[str, Any]:
    """Return status for all known agents from the heartbeats store."""
    agents: dict[str, Any] = {}
    now = time.time()
    known_agents = list(_agent_heartbeats.keys())
    if not known_agents:
        return {"agents": {}}
    for name in known_agents:
        last_seen = _agent_heartbeats.get(name)
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


# ═══════════════════════════════════════════════════════════════════════════════
# Human-facing dashboard endpoints (caseworker UI)
# ═══════════════════════════════════════════════════════════════════════════════

# All data comes from PostgreSQL – no in-memory storage.

# ── RBAC helpers ──────────────────────────────────────────────────────────────

async def get_current_user(request: Request) -> dict[str, str]:
    """
    Extract user identity from request headers.
    For demo: reads X-User-Role and X-User-Id headers.
    In production: validate a JWT and extract claims.
    """
    role    = request.headers.get("X-User-Role", "caseworker")
    user_id = request.headers.get("X-User-Id",   "caseworker@example.com")
    return {"role": role, "user_id": user_id}


def require_role(*allowed_roles: str):
    """FastAPI dependency that enforces role-based access control."""
    async def _dep(user: dict = Depends(get_current_user)) -> dict[str, str]:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user['role']}' is not permitted. Required: {list(allowed_roles)}",
            )
        return user
    return _dep


# ── Audit log helper ──────────────────────────────────────────────────────────

async def log_action(
    user_id: str,
    role: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any],
    request: Request | None = None,
) -> None:
    """
    Write an immutable audit record to PostgreSQL.
    Non-blocking: failures are logged but never raise to the caller.
    """
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    try:
        if _db_pool is not None:
            async with _db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_logs
                        (user_id, role, action, target_type, target_id,
                         details, ip_address, user_agent)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                    """,
                    user_id, role, action, target_type, target_id,
                    json.dumps(details), ip, ua,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.audit_log.error", action=action, error=str(exc))


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


class PlacementApproval(BaseModel):
    workflow_id: str
    approved: bool
    comment: str = ""


@app.post("/api/referral", status_code=202)
async def submit_referral(
    referral: ChildReferral,
    request: Request,
    settings: dict = Depends(get_settings),
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """
    Submit a new child referral from the caseworker intake form.
    Starts a FosterPlacementWorkflow and adds an entry to the pending approvals list.
    """
    workflow_id = f"foster-{referral.child_id}"
    try:
        client = await get_temporal_client()
        logger.info("api.referral.starting_workflow", workflow_id=workflow_id, child_id=referral.child_id)
        # Only pass child_id – the workflow loads the full profile from PostgreSQL
        await client.start_workflow(
            "FosterPlacementWorkflow",
            {"child_id": referral.child_id},
            id=workflow_id,
            task_queue=settings["temporal_task_queue"],
        )
        logger.info("api.referral.started_workflow", workflow_id=workflow_id, child_id=referral.child_id)
    except Exception as exc:  # noqa: BLE001
        if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
            logger.exception("api.referral.start_error", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Save/update the child record (real intake). The workflow itself only receives child_id.
    if _db_pool is not None:
        try:
            async with _db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO children
                        (child_id, age, gender, special_needs, sibling_group, sibling_count,
                         location, emergency_level,
                         languages, languages_arr,
                         medical_needs, behavioral_support,
                         school_continuity,
                         notes)
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("api.referral.children_insert_error", error=str(exc))

    # Insert pending placement record into DB
    if _db_pool is not None:
        try:
            async with _db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO placements
                        (workflow_id, child_id, status, risk_score, family_id, family_json)
                    VALUES ($1, $2, 'pending', 0.0, NULL, NULL)
                    ON CONFLICT (workflow_id) DO NOTHING
                    """,
                    workflow_id, referral.child_id,
                )
                # Also create an active_placements tracking row
                await conn.execute(
                    """
                    INSERT INTO active_placements
                        (workflow_id, child_id, family_id, status)
                    VALUES ($1, $2, NULL, 'pending_review')
                    ON CONFLICT (workflow_id) DO NOTHING
                    """,
                    workflow_id, referral.child_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("api.referral.placement_insert_error", error=str(exc))

    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="SUBMIT_REFERRAL",
        target_type="child", target_id=referral.child_id,
        details={"workflow_id": workflow_id, "emergency_level": referral.emergency_level,
                 "age": referral.age, "medical_needs": referral.medical_needs},
        request=request,
    )
    logger.info("api.referral.submitted", child_id=referral.child_id, workflow_id=workflow_id)
    REQUEST_COUNT.labels(endpoint="/api/referral", status="202").inc()
    return {"workflow_id": workflow_id, "message": "Referral submitted – swarm is matching"}


@app.get("/api/pending_approvals")
async def get_pending_approvals() -> dict[str, Any]:
    """
    Return placements awaiting caseworker approval.
    All data comes from PostgreSQL – no in-memory storage.
    """
    approvals: list[dict[str, Any]] = []
    if _db_pool is not None:
        try:
            async with _db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT p.*, c.age, c.gender, c.emergency_level as child_emergency_level
                    FROM placements p
                    LEFT JOIN children c ON c.child_id = p.child_id
                    WHERE p.status IN ('pending', 'pending_supervisor')
                    ORDER BY p.created_at DESC
                    """
                )
                for row in rows:
                    fj = row.get("family_json")
                    family = {}
                    if fj:
                        family = json.loads(fj) if isinstance(fj, str) else (fj or {})
                    approvals.append({
                        "workflow_id":        row["workflow_id"],
                        "child_id":           row["child_id"],
                        "recommended_family": family.get("name") or family.get("family_id"),
                        "risk_score":         float(row.get("risk_score") or 0),
                        "status":             row["status"],
                        "emergency_level":    row.get("child_emergency_level") or row.get("emergency_level", "normal"),
                        "created_at":         row.get("created_at").isoformat() if row.get("created_at") else None,
                    })
        except Exception:  # noqa: BLE001
            pass
    return {"approvals": approvals, "count": len(approvals)}


@app.post("/api/approve")
async def approve_placement(
    approval: PlacementApproval,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """
    Approve or reject a recommended placement.
    All data comes from PostgreSQL – no in-memory storage.

    Two-factor rule for high-risk placements (risk_score > 75):
      - Caseworker approval sets status to 'pending_supervisor'.
      - A supervisor must then call POST /api/supervisor_approve to finalise.
    Normal placements (risk ≤ 75) are finalised immediately by any caseworker.
    """
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Look up current risk score from DB
    async with _db_pool.acquire() as conn:
        placement_row = await conn.fetchrow(
            "SELECT risk_score, status FROM placements WHERE workflow_id = $1",
            approval.workflow_id,
        )
    if not placement_row:
        raise HTTPException(status_code=404, detail=f"Placement {approval.workflow_id} not found")
    risk_score = float(placement_row["risk_score"] or 0)
    current_status = placement_row["status"]

    HIGH_RISK_THRESHOLD = 75.0
    is_high_risk = risk_score > HIGH_RISK_THRESHOLD
    role = user["role"]

    # ── High-risk + caseworker → escalate to supervisor ───────────────────────
    if is_high_risk and role == "caseworker" and approval.approved:
        async with _db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE placements
                SET status = 'pending_supervisor',
                    supervisor_required = TRUE,
                    caseworker_id = $2,
                    notes = $3
                WHERE workflow_id = $1
                """,
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
        logger.info("api.approve.escalated_to_supervisor",
                    workflow_id=approval.workflow_id, risk_score=risk_score)
        REQUEST_COUNT.labels(endpoint="/api/approve", status="200").inc()
        return {
            "status":  "pending_supervisor",
            "message": f"Risk score {risk_score:.0f}% exceeds threshold – awaiting supervisor approval",
        }

    # ── Normal approval / rejection ───────────────────────────────────────────
    new_status = "approved" if approval.approved else "rejected"
    async with _db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE placements SET status = $2, notes = $3 WHERE workflow_id = $1",
            approval.workflow_id, new_status, approval.comment,
        )
        await conn.execute(
            "UPDATE active_placements SET status = $2 WHERE workflow_id = $1",
            approval.workflow_id, new_status,
        )
        # If approved, update family capacity
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
                    # Also write to placement_history
                    await conn.execute(
                        """
                        INSERT INTO placement_history
                            (child_id, family_id, placement_start, outcome, disruption, duration_days)
                        VALUES ($1, $2, NOW(), 'active', FALSE, 0)
                        ON CONFLICT DO NOTHING
                        """,
                        placement["child_id"], family_id,
                    )

    # Signal the running workflow so it can proceed / abort
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(approval.workflow_id)
        signal_name = "approve_placement" if approval.approved else "reject_placement"
        await handle.signal(signal_name, approval.comment)
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.approve.signal_error", workflow_id=approval.workflow_id, error=str(exc))

    action_name = "APPROVE_PLACEMENT" if approval.approved else "REJECT_PLACEMENT"
    await log_action(
        user_id=user["user_id"], role=role,
        action=action_name,
        target_type="placement", target_id=approval.workflow_id,
        details={"approved": approval.approved, "comment": approval.comment,
                 "risk_score": risk_score},
        request=request,
    )
    logger.info("api.placement_decision", workflow_id=approval.workflow_id,
                approved=approval.approved)
    # Publish live event when approved
    if approval.approved:
        try:
            manager = NATSManager(NATS_URL)
            await manager.publish("events.live.placement_approved", {
                "event": "placement_approved",
                "workflow_id": approval.workflow_id,
                "comment": approval.comment or "",
                "risk_score": risk_score,
                "approved_by": user["user_id"],
                "role": role,
                "supervisor_approved": False,
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            })
        except Exception:  # noqa: BLE001
            pass
    REQUEST_COUNT.labels(endpoint="/api/approve", status="200").inc()
    return {"status": new_status}


@app.post("/api/supervisor_approve")
async def supervisor_approve(
    approval: PlacementApproval,
    request: Request,
    user: dict = Depends(require_role("supervisor", "admin")),
) -> dict[str, str]:
    """
    Final approval for high-risk placements (risk > 75).
    Only supervisors and admins can call this endpoint.
    """
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    new_status = "approved" if approval.approved else "rejected"
    async with _db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE placements SET status = $2, notes = $3 WHERE workflow_id = $1",
            approval.workflow_id, new_status, approval.comment,
        )
        await conn.execute(
            "UPDATE active_placements SET status = $2 WHERE workflow_id = $1",
            approval.workflow_id, new_status,
        )
        # If approved, update family capacity
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
                        """
                        INSERT INTO placement_history
                            (child_id, family_id, placement_start, outcome, disruption, duration_days)
                        VALUES ($1, $2, NOW(), 'active', FALSE, 0)
                        ON CONFLICT DO NOTHING
                        """,
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

    action_name = "SUPERVISOR_APPROVE_PLACEMENT" if approval.approved else "SUPERVISOR_REJECT_PLACEMENT"
    await log_action(
        user_id=user["user_id"], role=user["role"],
        action=action_name,
        target_type="placement", target_id=approval.workflow_id,
        details={"approved": approval.approved, "comment": approval.comment},
        request=request,
    )
    logger.info("api.supervisor_approve", workflow_id=approval.workflow_id,
                approved=approval.approved)
    # Publish live event when supervisor approves
    if approval.approved:
        try:
            manager = NATSManager(NATS_URL)
            await manager.publish("events.live.placement_approved", {
                "event": "placement_approved",
                "workflow_id": approval.workflow_id,
                "comment": approval.comment or "",
                "supervisor_id": user["user_id"],
                "supervisor_approved": True,
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            })
        except Exception:  # noqa: BLE001
            pass
    return {"status": "supervisor_approved" if approval.approved else "supervisor_rejected"}


# ── Children CRUD ─────────────────────────────────────────────────────────────

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
    def _fmt(val):
        return val.isoformat() if val else None
    return {
        "child_id": row["child_id"],
        "first_name": row.get("first_name", ""),
        "last_name": row.get("last_name", ""),
        "age": row["age"],
        "gender": row["gender"],
        "location": row.get("location", ""),
        "sibling_group": row.get("sibling_group", False),
        "sibling_count": row.get("sibling_count", 0),
        "special_needs": row.get("special_needs", False),
        "medical_needs": row.get("medical_needs", ""),
        "behavioral_support": row.get("behavioral_support", ""),
        "emergency_level": row.get("emergency_level", "normal"),
        "languages": row.get("languages", ""),
        "languages_arr": row.get("languages_arr") or [],
        "school_continuity": row.get("school_continuity", False),
        "case_notes": row.get("case_notes", row.get("notes", "")),
        "created_at": _fmt(row.get("created_at")),
        "updated_at": _fmt(row.get("updated_at")),
    }


@app.get("/children")
async def list_children(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """List all children, ordered by created_at descending."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM children ORDER BY created_at DESC"
        )
    return {"children": [_child_row_to_dict(r) for r in rows], "count": len(rows)}


@app.get("/children/{child_id}")
async def get_child(
    child_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Get a single child by child_id."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM children WHERE child_id = $1", child_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Child {child_id} not found")
    return _child_row_to_dict(row)


@app.post("/children", status_code=201)
async def create_child(
    child: ChildCreate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """Create a new child record."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO children
                (child_id, first_name, last_name, age, gender, location,
                 sibling_group, sibling_count, special_needs,
                 medical_needs, behavioral_support, emergency_level,
                 languages, languages_arr,
                 school_continuity,
                 case_notes, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::text[], $15, $16, $16)
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
            child.languages_arr or [p.strip() for p in (child.languages or "").split(",") if p.strip()],
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


@app.put("/children/{child_id}")
async def update_child(
    child_id: str,
    update: ChildUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """Update a child's details."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM children WHERE child_id = $1", child_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Child {child_id} not found")

        fields = []
        values = []
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
            # write both to keep backward compatibility
            "case_notes": "case_notes",
        }
        for attr, col in col_map.items():
            val = getattr(update, attr, None)
            if val is not None:
                fields.append(f"{col} = ${idx}")
                # Keep languages (string) and languages_arr (array) in sync
                if attr == "languages_arr":
                    values.append(val)
                    # also backfill legacy string representation for older UI code paths
                    fields.append(f"languages = ${idx + 1}")
                    values.append(", ".join(val))
                    idx += 1
                else:
                    values.append(val)
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


@app.delete("/children/{child_id}")
async def delete_child(
    child_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a child record."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
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


# ── Families CRUD ─────────────────────────────────────────────────────────────

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
    def _fmt(val):
        return val.isoformat() if val else None
    return {
        "id": row["id"],
        "family_id": row["family_id"],
        "name": row["name"],
        "location": row["location"],
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "capacity": row["capacity"],  # legacy
        "total_capacity": row.get("total_capacity", row["capacity"]),
        "available_capacity": row["available_capacity"],
        "experience": row["experience"],  # legacy
        "experience_level": row.get("experience_level", row["experience"]),
        "specializations": row["specializations"],
        "languages": row["languages"],  # legacy
        "languages_arr": row.get("languages_arr") or [],
        "special_needs_trained": row["special_needs_trained"],
        "accepts_siblings": row["accepts_siblings"],
        "sibling_group_capable": row.get("sibling_group_capable", row["accepts_siblings"]),
        "emergency_available": row["emergency_available"],
        "home_type": row.get("home_type", "family"),
        "max_age": row["max_age"],
        "can_take_siblings": row["can_take_siblings"],
        "has_animals": row["has_animals"],
        "active": row.get("active", True),
        "created_at": _fmt(row.get("created_at")),
        "updated_at": _fmt(row.get("updated_at")),
    }


@app.get("/families")
async def list_families(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """List all foster families, ordered by name."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
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


@app.get("/families/{family_id}")
async def get_family(
    family_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Get a single family by family_id."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
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


@app.post("/families", status_code=201)
async def create_family(
    family: FamilyCreate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """Create a new foster family."""
    if _db_pool is None:
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
    async with _db_pool.acquire() as conn:
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
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::text[], $14, $15, $16, $17, $18, $19, $20, $21)
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
    result = _family_row_to_dict(row)

    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="CREATE_FAMILY",
        target_type="family", target_id=family_id,
        details={"name": family.name, "location": family.location, "capacity": family.capacity},
        request=request,
    )
    logger.info("api.create_family", family_id=family_id, name=family.name)
    return result


@app.put("/families/{family_id}")
async def update_family(
    family_id: str,
    update: FamilyUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """Update a foster family's details."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM families WHERE family_id = $1", family_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Family {family_id} not found")

        fields = []
        values = []
        idx = 1
        for col in (
            "name", "location",
            "latitude", "longitude",
            "capacity", "total_capacity",
            "active",
            "experience", "experience_level",
            "specializations",
            "languages", "languages_arr",
            "special_needs_trained",
            "accepts_siblings", "sibling_group_capable",
            "emergency_available",
            "home_type",
            "max_age",
            "can_take_siblings",
            "has_animals",
        ):
            val = getattr(update, col, None)
            if val is not None:
                fields.append(f"{col} = ${idx}")
                values.append(val)
                idx += 1
                if col == "languages":
                    # keep languages_arr in sync
                    arr = [p.strip() for p in (val or "").split(",") if p.strip()]
                    fields.append(f"languages_arr = ${idx}")
                    values.append(arr)
                    idx += 1

        if not fields:
            return _family_row_to_dict(existing)

        fields.append("updated_at = NOW()")
        values.append(family_id)
        set_clause = ", ".join(fields)
        row = await conn.fetchrow(
            f"UPDATE families SET {set_clause} WHERE family_id = ${idx} RETURNING *",
            *values,
        )
    result = _family_row_to_dict(row)

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


@app.delete("/families/{family_id}")
async def delete_family(
    family_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a foster family."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
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


@app.post("/api/foster_home")
async def register_foster_home(
    home: dict[str, Any],
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """
    Register a new foster home.
    Inserts into the families table and publishes a family_update event to NATS
    so the retriever agent can re-index the family in Qdrant.
    """
    if _db_pool is not None:
        try:
            async with _db_pool.acquire() as conn:
                family_id = f"F-{uuid.uuid4().hex[:6].upper()}"
                await conn.execute(
                    """
                    INSERT INTO families
                        (family_id, name, location,
                         capacity, total_capacity, active,
                         experience, experience_level,
                         specializations, languages, languages_arr,
                         special_needs_trained, accepts_siblings, sibling_group_capable,
                         emergency_available,
                         max_age, can_take_siblings, has_animals, updated_at)
                    VALUES ($1, $2, $3, $4, $4, TRUE, $5, $5, $6, $7, string_to_array($7, ','), $8, $9, $9, $10, $11, $12, $13, NOW())
                    """,
                    family_id,
                    home.get("name", "Unknown"),
                    home.get("location", ""),
                    int(home.get("capacity", 1)),
                    home.get("experience", "new"),
                    home.get("specializations", ""),
                    home.get("languages", ""),
                    bool(home.get("special_needs_trained", False)),
                    bool(home.get("accepts_siblings", False)),
                    bool(home.get("emergency_available", False) or home.get("accepts_emergency", False)),
                    int(home.get("max_age", 18)),
                    bool(home.get("can_take_siblings", False) or home.get("accepts_siblings", False)),
                    bool(home.get("has_animals", False)),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("api.foster_home.db_error", error=str(exc))
            raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    # Publish to NATS so the retriever can update the vector index
    try:
        manager = NATSManager(NATS_URL)
        await manager.publish("events.family_update", home)
    except Exception:  # noqa: BLE001
        pass  # NATS offline is non-fatal for registration

    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="REGISTER_FOSTER_HOME",
        target_type="family", target_id=home.get("name", "unknown"),
        details={"location": home.get("location"), "capacity": home.get("capacity"),
                 "specializations": home.get("specializations")},
        request=request,
    )
    logger.info("api.foster_home.registered", name=home.get("name"))
    return {"status": "ok", "message": "Foster home registered"}


@app.post("/api/incident")
async def report_incident(
    data: dict[str, Any],
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """
    Log an incident for a placement.
    Publishes a check_in event to NATS so the FosterMonitorAgent updates the risk score.
    """
    try:
        manager = NATSManager(NATS_URL)
        await manager.publish("events.check_in", {
            **data,
            "event_type": "incident",
            "timestamp":  __import__("datetime").datetime.now().isoformat(),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.incident.publish_error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to publish incident: {exc}") from exc

    await log_action(
        user_id=user["user_id"], role=user["role"],
        action="REPORT_INCIDENT",
        target_type="placement", target_id=data.get("workflow_id", "unknown"),
        details={"type": data.get("type"), "severity": data.get("severity"),
                 "notes": data.get("notes", "")[:200]},
        request=request,
    )
    logger.info("api.incident.reported", workflow_id=data.get("workflow_id"))
    return {"status": "ok", "message": "Incident logged – swarm will update risk score"}


@app.get("/api/search_families")
async def search_families(q: str = "") -> dict[str, Any]:
    """
    Semantic search over foster families.
    Queries Qdrant via the retriever agent's NATS request-reply channel.
    Falls back to a PostgreSQL ILIKE search if NATS is unavailable.
    """
    if not q.strip():
        return {"results": [], "query": q}

    # Try NATS request-reply to the retriever agent
    try:
        manager = NATSManager(NATS_URL)
        response = await manager.request(
            "agent.retriever.search",
            {"query": q, "top_k": 10},
            timeout=5.0,
        )
        results = response.get("results", [])
        return {"results": results, "query": q, "source": "vector"}
    except Exception:  # noqa: BLE001
        pass  # fall through to DB search

    # Fallback: PostgreSQL text search on families table + placements family_json
    if _db_pool is not None:
        try:
            async with _db_pool.acquire() as conn:
                # Search the dedicated families table first
                rows = await conn.fetch(
                    """
                    SELECT id::text, family_id, name, location, capacity, available_capacity,
                           experience, specializations,
                           special_needs_trained, accepts_siblings, max_age,
                           can_take_siblings, has_animals
                    FROM families
                    WHERE name            ILIKE $1
                       OR location        ILIKE $1
                       OR specializations ILIKE $1
                       OR languages       ILIKE $1
                    ORDER BY updated_at DESC
                    LIMIT 10
                    """,
                    f"%{q}%",
                )
            results = [
                {
                    "id":                   row["id"],
                    "family_id":            row["family_id"],
                    "name":                 row["name"],
                    "location":             row["location"],
                    "capacity":             row["capacity"],
                    "available_capacity":   row["available_capacity"],
                    "experience":           row["experience"],
                    "specializations":      row["specializations"],
                    "special_needs_trained": row["special_needs_trained"],
                    "accepts_siblings":     row["accepts_siblings"],
                    "score":                None,
                }
                for row in rows
            ]
            return {"results": results, "query": q, "source": "database"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("api.search_families.db_error", error=str(exc))

    return {"results": [], "query": q, "source": "none"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus metrics endpoint."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ═══════════════════════════════════════════════════════════════════════════════
# Audit logs, explainability, and ethics endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/audit_logs")
async def get_audit_logs(
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(require_role("admin", "supervisor")),
) -> dict[str, Any]:
    """
    Return paginated audit log entries.
    Accessible by admins and supervisors only.
    """
    if _db_pool is None:
        return {"logs": [], "count": 0}
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp::text, user_id, role, action,
                   target_type, target_id, details, ip_address, user_agent
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


@app.get("/api/placement_explanation/{workflow_id}")
async def get_placement_explanation(workflow_id: str) -> dict[str, Any]:
    """
    Return the explainability data for a specific placement:
      - match_explanation: why this family was chosen
      - risk_score + risk_explanation: what drives the risk score
    """
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT workflow_id, child_id, risk_score, risk_explanation,
                   match_explanation, family_json
            FROM placements
            WHERE workflow_id = $1
            """,
            workflow_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Placement {workflow_id} not found")
    record = dict(row)
    fj = record.get("family_json")
    record["family"] = json.loads(fj) if isinstance(fj, str) else (fj or {})
    del record["family_json"]
    return record


@app.get("/api/fairness")
async def get_fairness_statement() -> dict[str, Any]:
    """
    Return the AI fairness and bias statement as structured data.
    The frontend renders this as the FairnessStatement page.
    """
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
            "Placement recommendations are based on limited features (age, siblings, special needs).",
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


# ═══════════════════════════════════════════════════════════════════════════════
# Emergent swarm endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class EmergentRunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4096,
                      description="Natural-language goal for the emergent swarm")


@app.post("/emergent/run", status_code=202)
async def emergent_run(
    request: EmergentRunRequest,
    settings: dict = Depends(get_settings),
) -> dict[str, str]:
    """
    Submit a goal to the emergent swarm.

    Unlike /swarm/run (fixed planner → executor → validator chain), this
    endpoint starts an EmergentSwarmWorkflow where agents self-organise:
      1. A TaskAnnouncement is broadcast to all agents.
      2. Agents bid based on their current load, capabilities, and success rate.
      3. SwarmManager selects the winning bid and forms an ad-hoc team.
      4. TeamCoordinator runs consensus voting among team members.
      5. The final result is published back to the API result bus.

    Poll GET /swarm/status/{workflow_id} for the result.
    """
    workflow_id = f"emergent-{uuid.uuid4().hex[:12]}"
    logger.info("api.emergent_run", goal=request.goal[:80], workflow_id=workflow_id)

    try:
        client = await get_temporal_client()
        await client.start_workflow(
            "EmergentSwarmWorkflow",
            request.goal,
            id=workflow_id,
            task_queue=settings["temporal_task_queue"],
        )
        REQUEST_COUNT.labels(endpoint="/emergent/run", status="202").inc()
        return {
            "workflow_id": workflow_id,
            "status":      "started",
            "message":     "Emergent swarm auction initiated – agents are bidding",
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.emergent_run.error", error=str(exc))
        REQUEST_COUNT.labels(endpoint="/emergent/run", status="500").inc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start emergent workflow: {exc}",
        ) from exc
