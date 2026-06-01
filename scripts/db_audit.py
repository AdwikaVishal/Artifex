#!/usr/bin/env python3
"""
db_audit.py — Production readiness audit for Artifex PostgreSQL.

Generates a markdown report with:
  - table name
  - row count
  - missing columns vs expected schema
  - missing relationships (FK constraints)
  - production readiness signal

Usage:
  DATABASE_URL=postgresql://... python scripts/db_audit.py

Output:
  db_audit_report.md (repo root)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import asyncpg


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "db_audit_report.md"

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://artifex:artifex123@localhost:5432/placements"
)

TARGET_TABLES = [
    "children",
    "families",
    "placements",
    "placement_predictions",
    "placement_history",
    "active_placements",
    "workflow_events",
    "workflow_status",
    "ml_inference_logs",
]

# Expected columns (Phase 2 spec). We treat these as minimum for “production ready”.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "children": {
        "child_id",
        "first_name",
        "last_name",
        "age",
        "gender",
        "location",
        "sibling_group",
        "sibling_count",
        "special_needs",
        "medical_needs",
        "behavioral_support",
        "emergency_level",
        "school_continuity",
        "languages_arr",
        "notes",
        "created_at",
        "updated_at",
    },
    "families": {
        "family_id",
        "name",
        "location",
        "latitude",
        "longitude",
        "total_capacity",
        "experience_level",
        "languages_arr",
        "special_needs_trained",
        "sibling_group_capable",
        "home_type",
        "active",
        "created_at",
    },
    "placements": {
        "workflow_id",
        "child_id",
        "family_id",
        "family_json",
        "risk_score",
        "match_explanation",
        "status",
        "created_at",
        "updated_at",
    },
    "active_placements": {
        "id",
        "workflow_id",
        "child_id",
        "family_id",
        "placement_start",
        "placement_end",
        "status",
    },
    "placement_history": {
        "id",
        "child_id",
        "family_id",
        "placement_start",
        "placement_end",
        "duration_days",
        "outcome",
        "disruption",
        "disruption_reason",
        "created_at",
    },
    "placement_predictions": {
        "id",
        "workflow_id",
        "child_id",
        "recommended",
        "score",
        "confidence",
        "risk_score",
        "feature_importance",
        "top_matches",
        "model_version",
        "created_at",
    },
    "workflow_events": {"id", "workflow_id", "stage", "status", "data", "timestamp"},
    "workflow_status": {
        "workflow_id",
        "status",
        "current_stage",
        "progress",
        "metadata",
        "updated_at",
    },
    "ml_inference_logs": {
        "id",
        "workflow_id",
        "child_id",
        "payload",
        "result",
        "model_version",
        "timestamp",
    },
}


@dataclass(frozen=True)
class TableAudit:
    table: str
    row_count: int | None
    missing_columns: list[str]
    fk_count: int
    production_readiness: str


async def fetch_existing_tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        """
    )
    return {r["table_name"] for r in rows}


async def fetch_columns(conn: asyncpg.Connection, table: str) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
        """,
        table,
    )
    return {r["column_name"] for r in rows}


async def fetch_fk_count(conn: asyncpg.Connection, table: str) -> int:
    # FK constraints referencing other tables (on this table)
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.table_constraints tc
        WHERE tc.table_schema='public'
          AND tc.table_name=$1
          AND tc.constraint_type='FOREIGN KEY'
        """,
        table,
    )
    return int(row["cnt"] or 0)


async def fetch_row_count(conn: asyncpg.Connection, table: str) -> int | None:
    try:
        val = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        return int(val or 0)
    except Exception:
        return None


def readiness_label(row_count: int | None, missing_cols: list[str], fk_count: int, table: str) -> str:
    if row_count is None:
        return "unknown (query failed)"
    if missing_cols:
        return "not ready (missing columns)"
    if table in {"children", "families"} and row_count == 0:
        return "not ready (empty)"
    if table in {"placement_history"} and row_count == 0:
        return "blocked (no training outcomes yet)"
    if fk_count == 0 and table in {"placements", "active_placements", "placement_history", "placement_predictions"}:
        return "needs hardening (no FKs)"
    return "ready-ish (schema OK)"


async def run() -> int:
    conn = await asyncpg.connect(DATABASE_URL, timeout=8.0)
    try:
        existing_tables = await fetch_existing_tables(conn)
        audits: list[TableAudit] = []

        for t in TARGET_TABLES:
            if t not in existing_tables:
                audits.append(
                    TableAudit(
                        table=t,
                        row_count=None,
                        missing_columns=sorted(EXPECTED_COLUMNS.get(t, set())),
                        fk_count=0,
                        production_readiness="missing table",
                    )
                )
                continue

            cols = await fetch_columns(conn, t)
            expected = EXPECTED_COLUMNS.get(t, set())
            missing = sorted(expected - cols) if expected else []
            fk_cnt = await fetch_fk_count(conn, t)
            rc = await fetch_row_count(conn, t)
            audits.append(
                TableAudit(
                    table=t,
                    row_count=rc,
                    missing_columns=missing,
                    fk_count=fk_cnt,
                    production_readiness=readiness_label(rc, missing, fk_cnt, t),
                )
            )

        now = datetime.now(timezone.utc).isoformat()
        lines: list[str] = []
        lines.append("# Artifex — Database Audit Report (Phase 2)")
        lines.append("")
        lines.append(f"Generated: `{now}`")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        empty = [a.table for a in audits if a.row_count == 0]
        lines.append(f"- Empty tables: {', '.join(empty) if empty else '(none)'}")
        lines.append("")
        lines.append("## Table Audit")
        lines.append("")
        lines.append("| Table | Row Count | Missing Columns | FK Constraints | Production Readiness |")
        lines.append("|---|---:|---|---:|---|")
        for a in audits:
            missing_str = ", ".join(a.missing_columns) if a.missing_columns else ""
            rc = "N/A" if a.row_count is None else str(a.row_count)
            lines.append(f"| `{a.table}` | {rc} | {missing_str} | {a.fk_count} | {a.production_readiness} |")
        lines.append("")
        lines.append("## Validation SQL (copy/paste)")
        lines.append("")
        lines.append("```sql")
        lines.append("SELECT COUNT(*) FROM children;")
        lines.append("SELECT COUNT(*) FROM families;")
        lines.append("SELECT COUNT(*) FROM placement_history;")
        lines.append("SELECT COUNT(*) FROM active_placements;")
        lines.append("```")
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        lines.append("- If `placement_history` is empty, ML training is blocked (no real outcomes).")
        lines.append("- Consider adding FK constraints + NOT NULL constraints only after you confirm the workflow lifecycle (pending → matched → approved → closed).")

        REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote: {REPORT_PATH}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))

