"""Add missing columns to placements table.

Columns added:
  placements:  notes, supervisor_required, caseworker_id

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-04 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_context().connection
    insp = inspect(conn)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def upgrade() -> None:
    # ── placements table ────────────────────────────────────────────────────
    if not _has_column("placements", "notes"):
        op.add_column("placements", sa.Column("notes", sa.Text(), server_default=""))
    if not _has_column("placements", "supervisor_required"):
        op.add_column("placements", sa.Column("supervisor_required", sa.Boolean(), server_default="false"))
    if not _has_column("placements", "caseworker_id"):
        op.add_column("placements", sa.Column("caseworker_id", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ("notes", "supervisor_required", "caseworker_id"):
        if _has_column("placements", col):
            op.drop_column("placements", col)
