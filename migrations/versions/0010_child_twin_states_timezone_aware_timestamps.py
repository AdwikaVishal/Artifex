"""Convert child_twin_states and twin_validation_log timestamp columns
to TIMESTAMP WITH TIME ZONE to match Python's timezone-aware datetime usage.

Child Digital Twin endpoint (api/routes/twin.py) uses datetime.now(timezone.utc)
for stale_at and other timestamps, which caused asyncpg DataError when binding
an aware datetime to a naive TIMESTAMP column.

Columns changed in child_twin_states:
  as_of, updated_at, stale_at

Columns changed in twin_validation_log:
  validated_at

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-04 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── child_twin_states ─────────────────────────────────────────────────
    op.alter_column(
        "child_twin_states",
        "as_of",
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="as_of::timestamptz",
        existing_nullable=False,
        existing_server_default=sa.text("NOW()"),
    )
    op.alter_column(
        "child_twin_states",
        "updated_at",
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="updated_at::timestamptz",
        existing_nullable=False,
        existing_server_default=sa.text("NOW()"),
    )
    op.alter_column(
        "child_twin_states",
        "stale_at",
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="stale_at::timestamptz",
        existing_nullable=False,
    )

    # ── twin_validation_log ───────────────────────────────────────────────
    op.alter_column(
        "twin_validation_log",
        "validated_at",
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="validated_at::timestamptz",
        existing_nullable=False,
        existing_server_default=sa.text("NOW()"),
    )


def downgrade() -> None:
    # Revert to naive TIMESTAMP
    op.alter_column(
        "child_twin_states",
        "as_of",
        type_=sa.TIMESTAMP(),
        postgresql_using="as_of::timestamp",
        existing_nullable=False,
        existing_server_default=sa.text("NOW()"),
    )
    op.alter_column(
        "child_twin_states",
        "updated_at",
        type_=sa.TIMESTAMP(),
        postgresql_using="updated_at::timestamp",
        existing_nullable=False,
        existing_server_default=sa.text("NOW()"),
    )
    op.alter_column(
        "child_twin_states",
        "stale_at",
        type_=sa.TIMESTAMP(),
        postgresql_using="stale_at::timestamp",
        existing_nullable=False,
    )
    op.alter_column(
        "twin_validation_log",
        "validated_at",
        type_=sa.TIMESTAMP(),
        postgresql_using="validated_at::timestamp",
        existing_nullable=False,
        existing_server_default=sa.text("NOW()"),
    )
