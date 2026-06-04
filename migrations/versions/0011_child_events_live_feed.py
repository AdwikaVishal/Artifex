"""Add title, description, severity, created_by columns to child_life_events
for live event stream support. Add new event types for quick-add workflow.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-04 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns to child_life_events for live event stream
    op.add_column("child_life_events", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("child_life_events", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "child_life_events",
        sa.Column("severity", sa.Text(), nullable=True, server_default=sa.text("'low'")),
    )
    op.add_column("child_life_events", sa.Column("created_by", sa.Text(), nullable=True))
    op.create_index("idx_cle_severity", "child_life_events", ["severity"])
    op.create_index("idx_cle_created_by", "child_life_events", ["created_by"])


def downgrade() -> None:
    op.drop_index("idx_cle_created_by", table_name="child_life_events")
    op.drop_index("idx_cle_severity", table_name="child_life_events")
    op.drop_column("child_life_events", "created_by")
    op.drop_column("child_life_events", "severity")
    op.drop_column("child_life_events", "description")
    op.drop_column("child_life_events", "title")
