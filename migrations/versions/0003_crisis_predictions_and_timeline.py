"""Add crisis_predictions table and timeline columns to children.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── crisis_predictions ────────────────────────────────────────────────────
    op.create_table(
        "crisis_predictions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("placement_id", sa.Text(), nullable=False),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("prediction_date", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
        sa.Column("disruption_probability", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.Text(), nullable=True),  # low/medium/high/critical
        sa.Column("top_reasons", postgresql.JSONB(), nullable=True),
        sa.Column("recommended_interventions", postgresql.JSONB(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("actual_outcome", sa.Boolean(), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_crisis_predictions_placement",
        "crisis_predictions",
        ["placement_id"],
    )
    op.create_index(
        "idx_crisis_predictions_child",
        "crisis_predictions",
        ["child_id"],
    )
    op.create_index(
        "idx_crisis_predictions_date",
        "crisis_predictions",
        ["prediction_date"],
    )

    # ── children: add timeline columns ────────────────────────────────────────
    # school: current school name
    op.add_column(
        "children",
        sa.Column("school", sa.Text(), nullable=True),
    )
    # school_changes: [{school, date, reason}]
    op.add_column(
        "children",
        sa.Column(
            "school_changes",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
    )
    # therapy_history: [{type, provider, start_date, end_date}]
    op.add_column(
        "children",
        sa.Column(
            "therapy_history",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
    )
    # milestones: [{title, date, description}]
    op.add_column(
        "children",
        sa.Column(
            "milestones",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("children", "milestones")
    op.drop_column("children", "therapy_history")
    op.drop_column("children", "school_changes")
    op.drop_column("children", "school")
    op.drop_index("idx_crisis_predictions_date", table_name="crisis_predictions")
    op.drop_index("idx_crisis_predictions_child", table_name="crisis_predictions")
    op.drop_index("idx_crisis_predictions_placement", table_name="crisis_predictions")
    op.drop_table("crisis_predictions")
