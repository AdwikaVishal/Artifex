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
from temporalio.client import Client, WorkflowExecutionStatus

from nats_client.client import NATSManager
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
                family_id        TEXT NOT NULL,
                family_json      JSONB NOT NULL,
                risk_score       REAL DEFAULT 0.0,
                risk_explanation TEXT,
                match_explanation TEXT,
                last_notes       TEXT,
                created_at       TIMESTAMP DEFAULT NOW(),
                updated_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        # Add match_explanation column if upgrading an existing DB
        await conn.execute("""
            ALTER TABLE placements
            ADD COLUMN IF NOT EXISTS match_explanation TEXT
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_child_id   ON placements(child_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_risk_score ON placements(risk_score DESC)"
        )
        # ── Foster families table (used by /api/foster_home and /api/search_families)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS families (
                id                   SERIAL PRIMARY KEY,
                name                 TEXT NOT NULL,
                location             TEXT DEFAULT '',
                capacity             INT  DEFAULT 1,
                available_capacity   INT  DEFAULT 1,
                experience           TEXT DEFAULT 'new',
                specializations      TEXT DEFAULT '',
                languages            TEXT DEFAULT '',
                special_needs_trained   BOOLEAN DEFAULT FALSE,
                accepts_siblings        BOOLEAN DEFAULT FALSE,
                emergency_available     BOOLEAN DEFAULT FALSE,
                created_at           TIMESTAMP DEFAULT NOW(),
                updated_at           TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_families_location ON families(location)"
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
        await conn.execute(
            """
            INSERT INTO placements
                (workflow_id, child_id, family_id, family_json,
                 risk_score, risk_explanation, match_explanation, last_notes, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, NOW())
            ON CONFLICT (workflow_id) DO UPDATE SET
                risk_score        = EXCLUDED.risk_score,
                risk_explanation  = EXCLUDED.risk_explanation,
                match_explanation = COALESCE(EXCLUDED.match_explanation, placements.match_explanation),
                last_notes        = EXCLUDED.last_notes,
                family_json       = EXCLUDED.family_json,
                updated_at        = NOW()
            """,
            placement.get("workflow_id", f"wf-{placement.get('child_id', 'unknown')}"),
            placement.get("child_id", "unknown"),
            placement.get("family", {}).get("family_id", "unknown"),
            json.dumps(placement.get("family", {})),
            float(placement.get("risk_score", 0.0)),
            placement.get("risk_explanation"),
            placement.get("match_explanation"),
            placement.get("last_notes"),
        )


async def get_all_placements() -> list[dict]:
    """Fetch the 50 most recently updated placements from PostgreSQL."""
    if _db_pool is None:
        return []
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM placements ORDER BY updated_at DESC LIMIT 50"
        )
    result = []
    for row in rows:
        record = dict(row)
        # Parse JSONB back to dict
        fj = record.get("family_json")
        record["family"] = json.loads(fj) if isinstance(fj, str) else (fj or {})
        result.append(record)
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
    import json as _json

    async def _handle(msg: dict) -> None:
        child_id = msg.get("child_id", "unknown")
        # Persist to PostgreSQL
        await store_placement(msg)
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
            await client.start_workflow(
                "FosterPlacementWorkflow",
                data,
                id=workflow_id,
                task_queue=settings["temporal_task_queue"],
            )
            REQUEST_COUNT.labels(endpoint="/events", status="202").inc()
            return {"status": "workflow_started", "workflow_id": workflow_id}
        except Exception as exc:  # noqa: BLE001
            # Workflow already exists for this child – idempotent
            if "already" in str(exc).lower() or "exists" in str(exc).lower():
                return {"status": "already_running", "workflow_id": workflow_id}
            logger.exception("api.foster_event.start_error", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
        return {"placements": placements, "count": len(placements)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("api.get_placements.db_error", error=str(exc))
        with _placements_lock:
            snapshot = list(_api_latest_placements)
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
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        status = await handle.query("get_status")
        return {"workflow_id": workflow_id, "status": status}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc


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


# ═══════════════════════════════════════════════════════════════════════════════
# Human-facing dashboard endpoints (caseworker UI)
# ═══════════════════════════════════════════════════════════════════════════════

# In-memory pending approvals store.
# In production, replace with a PostgreSQL table.
_pending_approvals: list[dict[str, Any]] = []
_approvals_lock = _threading.Lock()

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
    medical_needs: str = ""
    behavioral_support: str = ""
    sibling_group: bool = False
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
        await client.start_workflow(
            "FosterPlacementWorkflow",
            referral.model_dump(),
            id=workflow_id,
            task_queue=settings["temporal_task_queue"],
        )
    except Exception as exc:  # noqa: BLE001
        if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
            logger.exception("api.referral.start_error", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    with _approvals_lock:
        # Avoid duplicates
        if not any(a["workflow_id"] == workflow_id for a in _pending_approvals):
            _pending_approvals.append({
                "workflow_id":         workflow_id,
                "child_id":            referral.child_id,
                "recommended_family":  None,
                "risk_score":          0.0,
                "status":              "pending",
                "emergency_level":     referral.emergency_level,
            })

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
    Enriches entries with the latest risk score from PostgreSQL when available.
    """
    with _approvals_lock:
        approvals = list(_pending_approvals)

    # Enrich with latest DB data
    if _db_pool is not None:
        try:
            async with _db_pool.acquire() as conn:
                for entry in approvals:
                    row = await conn.fetchrow(
                        "SELECT risk_score, family_json FROM placements WHERE workflow_id = $1",
                        entry["workflow_id"],
                    )
                    if row:
                        entry["risk_score"] = float(row["risk_score"] or 0)
                        fj = row["family_json"]
                        family = json.loads(fj) if isinstance(fj, str) else (fj or {})
                        entry["recommended_family"] = family.get("name") or family.get("family_id")
        except Exception:  # noqa: BLE001
            pass  # return unenriched data on DB error

    return {"approvals": approvals, "count": len(approvals)}


@app.post("/api/approve")
async def approve_placement(
    approval: PlacementApproval,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """
    Approve or reject a recommended placement.

    Two-factor rule for high-risk placements (risk_score > 75):
      - Caseworker approval sets status to 'pending_supervisor'.
      - A supervisor must then call POST /api/supervisor_approve to finalise.
    Normal placements (risk ≤ 75) are finalised immediately by any caseworker.
    """
    # Look up current risk score for this workflow
    risk_score = 0.0
    with _approvals_lock:
        for entry in _pending_approvals:
            if entry["workflow_id"] == approval.workflow_id:
                risk_score = float(entry.get("risk_score", 0.0))
                break

    HIGH_RISK_THRESHOLD = 75.0
    is_high_risk = risk_score > HIGH_RISK_THRESHOLD
    role = user["role"]

    # ── High-risk + caseworker → escalate to supervisor ───────────────────────
    if is_high_risk and role == "caseworker" and approval.approved:
        with _approvals_lock:
            for entry in _pending_approvals:
                if entry["workflow_id"] == approval.workflow_id:
                    entry["status"]           = "pending_supervisor"
                    entry["caseworker_comment"] = approval.comment
                    entry["caseworker_id"]    = user["user_id"]
                    break
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
    global _pending_approvals
    with _approvals_lock:
        _pending_approvals = [
            a for a in _pending_approvals if a["workflow_id"] != approval.workflow_id
        ]

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
    REQUEST_COUNT.labels(endpoint="/api/approve", status="200").inc()
    return {"status": "approved" if approval.approved else "rejected"}


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
    global _pending_approvals
    with _approvals_lock:
        _pending_approvals = [
            a for a in _pending_approvals if a["workflow_id"] != approval.workflow_id
        ]

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
    return {"status": "supervisor_approved" if approval.approved else "supervisor_rejected"}


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
                await conn.execute(
                    """
                    INSERT INTO families
                        (name, location, capacity, available_capacity, experience,
                         specializations, languages,
                         special_needs_trained, accepts_siblings, emergency_available,
                         updated_at)
                    VALUES ($1, $2, $3, $3, $4, $5, $6, $7, $8, $9, NOW())
                    """,
                    home.get("name", "Unknown"),
                    home.get("location", ""),
                    int(home.get("capacity", 1)),
                    home.get("experience", "new"),
                    home.get("specializations", ""),
                    home.get("languages", ""),
                    bool(home.get("special_needs_trained", False)),
                    bool(home.get("accepts_siblings", False)),
                    bool(home.get("emergency_available", False) or home.get("accepts_emergency", False)),
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
                    SELECT id::text, name, location, capacity, available_capacity,
                           experience, specializations,
                           special_needs_trained, accepts_siblings
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
