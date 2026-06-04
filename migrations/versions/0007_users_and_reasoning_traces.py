"""Add users table for persistent auth and reasoning_traces for AI thought capture.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-04 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    """Check if a table already exists in the target database."""
    bind = op.get_bind()
    return inspect(bind).has_table(name)


def upgrade() -> None:
    # ── users (persistent auth, replaces in-memory _DEMO_USERS) ──────────────
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.Text(), unique=True, nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False, server_default="caseworker"),
            sa.Column("display_name", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
            sa.Column("last_login_at", sa.TIMESTAMP(), nullable=True),
        )
        op.create_index("idx_users_email", "users", ["email"])

    # ── reasoning_traces (AI thoughts, per workflow stage) ────────────────────
    if not _table_exists("reasoning_traces"):
        op.create_table(
            "reasoning_traces",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("workflow_id", sa.Text(), nullable=False),
            sa.Column("stage", sa.Text(), nullable=False),
            sa.Column("agent_name", sa.Text(), nullable=False),
            sa.Column("step_index", sa.Integer(), server_default="0"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("timestamp", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
        )
        op.create_index("idx_reasoning_workflow", "reasoning_traces", ["workflow_id"])
        op.create_index("idx_reasoning_workflow_stage", "reasoning_traces", ["workflow_id", "stage"])

    # ── agent_executions (per-execution metrics) ──────────────────────────────
    if not _table_exists("agent_executions"):
        op.create_table(
            "agent_executions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("workflow_id", sa.Text(), nullable=False),
            sa.Column("stage", sa.Text(), nullable=False),
            sa.Column("agent_name", sa.Text(), nullable=False),
            sa.Column("action", sa.Text(), nullable=True),
            sa.Column("output", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("latency_seconds", sa.Float(), nullable=True),
            sa.Column("status", sa.Text(), server_default="completed"),
            sa.Column("details", postgresql.JSONB(), nullable=True),
            sa.Column("started_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
            sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        )
        op.create_index("idx_executions_workflow", "agent_executions", ["workflow_id"])
        op.create_index("idx_executions_agent", "agent_executions", ["agent_name"])

    # Seed default admin/supervisor/caseworker users
    # Passwords are SHA-256 hashed (production should use bcrypt)
    import hashlib
    op.execute(
        "INSERT INTO users (email, password_hash, role, display_name) VALUES "
        "('admin@artifex.local', '{}', 'admin', 'Admin User'), "
        "('supervisor@artifex.local', '{}', 'supervisor', 'Supervisor User'), "
        "('caseworker@artifex.local', '{}', 'caseworker', 'Caseworker User') "
        "ON CONFLICT (email) DO NOTHING".format(
            hashlib.sha256(b"admin123").hexdigest(),
            hashlib.sha256(b"supervisor123").hexdigest(),
            hashlib.sha256(b"caseworker123").hexdigest(),
        )
    )


def downgrade() -> None:
    op.drop_table("agent_executions")
    op.drop_table("reasoning_traces")
    op.drop_table("users")
