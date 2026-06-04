"""Add missing columns to children and families tables that code expects.

Columns added:
  children:  sibling_count, first_name, last_name, languages_arr,
             school_continuity, case_notes
  families:  total_capacity, active, latitude, longitude,
             experience_level, languages_arr, sibling_group_capable, home_type

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-04 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect
from typing import Any

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_context().connection
    insp = inspect(conn)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def upgrade() -> None:
    # ── children table ──────────────────────────────────────────────────────
    if not _has_column("children", "sibling_count"):
        op.add_column("children", sa.Column("sibling_count", sa.Integer(), server_default="0"))
    if not _has_column("children", "first_name"):
        op.add_column("children", sa.Column("first_name", sa.Text(), server_default=""))
    if not _has_column("children", "last_name"):
        op.add_column("children", sa.Column("last_name", sa.Text(), server_default=""))
    if not _has_column("children", "languages_arr"):
        op.add_column("children", sa.Column("languages_arr", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]")))
    if not _has_column("children", "school_continuity"):
        op.add_column("children", sa.Column("school_continuity", sa.Boolean(), server_default="false"))
    if not _has_column("children", "case_notes"):
        op.add_column("children", sa.Column("case_notes", sa.Text(), server_default=""))

    # ── families table ──────────────────────────────────────────────────────
    if not _has_column("families", "total_capacity"):
        op.add_column("families", sa.Column("total_capacity", sa.Integer(), server_default="1"))
    if not _has_column("families", "active"):
        op.add_column("families", sa.Column("active", sa.Boolean(), server_default="true"))
    if not _has_column("families", "latitude"):
        op.add_column("families", sa.Column("latitude", sa.Float(), nullable=True))
    if not _has_column("families", "longitude"):
        op.add_column("families", sa.Column("longitude", sa.Float(), nullable=True))
    if not _has_column("families", "experience_level"):
        op.add_column("families", sa.Column("experience_level", sa.Text(), server_default="new"))
    if not _has_column("families", "languages_arr"):
        op.add_column("families", sa.Column("languages_arr", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]")))
    if not _has_column("families", "sibling_group_capable"):
        op.add_column("families", sa.Column("sibling_group_capable", sa.Boolean(), server_default="false"))
    if not _has_column("families", "home_type"):
        op.add_column("families", sa.Column("home_type", sa.Text(), server_default="family"))


def downgrade() -> None:
    # ── families table (reverse order) ──────────────────────────────────────
    for col in ("home_type", "sibling_group_capable", "languages_arr", "experience_level",
                "longitude", "latitude", "active", "total_capacity"):
        if _has_column("families", col):
            op.drop_column("families", col)

    # ── children table (reverse order) ──────────────────────────────────────
    for col in ("case_notes", "school_continuity", "languages_arr", "last_name", "first_name", "sibling_count"):
        if _has_column("children", col):
            op.drop_column("children", col)
