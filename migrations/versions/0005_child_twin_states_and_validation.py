"""Create child_twin_states and twin_validation_log tables for the
Child Digital Twin simulation system.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. child_twin_states ──────────────────────────────────────────────────
    op.create_table(
        "child_twin_states",
        sa.Column("child_id", sa.Text(), primary_key=True),
        sa.Column("placement_id", sa.Text(), nullable=True),
        sa.Column("as_of", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("current_features", postgresql.JSONB(), nullable=False),
        sa.Column("outcome_probs", postgresql.JSONB(), nullable=True),
        sa.Column("pending_simulations", postgresql.JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("stale_at", sa.TIMESTAMP(), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
        sa.ForeignKeyConstraint(["placement_id"], ["placements.workflow_id"],),
    )
    op.create_index(
        "idx_twin_stale",
        "child_twin_states",
        [sa.text("stale_at ASC")],
    )

    # ── 2. twin_validation_log ─────────────────────────────────────────────────
    op.create_table(
        "twin_validation_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("validated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("mean_bias", sa.Float(), nullable=True),
        sa.Column("mse", sa.Float(), nullable=True),
        sa.Column("r_loss", sa.Float(), nullable=True),
        sa.Column("coherence_p", sa.Float(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("flags", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "idx_twin_val_model",
        "twin_validation_log",
        ["model_version", sa.text("validated_at DESC")],
    )

    # ── 3. Add counterfactual_simulation to ml_decision_audit decision_type CK ─
    op.execute(
        """
        ALTER TABLE ml_decision_audit
        DROP CONSTRAINT IF EXISTS ck_ml_audit_decision_type;
        """
    )
    op.execute(
        """
        ALTER TABLE ml_decision_audit
        ADD CONSTRAINT ck_ml_audit_decision_type
        CHECK (decision_type IN (
            'placement_match', 'risk_score', 'crisis_prediction',
            'family_recommendation', 'human_override', 'counterfactual_simulation'
        ));
        """
    )


def downgrade() -> None:
    # Restore original check constraint
    op.execute(
        """
        ALTER TABLE ml_decision_audit
        DROP CONSTRAINT IF EXISTS ck_ml_audit_decision_type;
        """
    )
    op.execute(
        """
        ALTER TABLE ml_decision_audit
        ADD CONSTRAINT ck_ml_audit_decision_type
        CHECK (decision_type IN (
            'placement_match', 'risk_score', 'crisis_prediction',
            'family_recommendation', 'human_override'
        ));
        """
    )

    op.drop_table("twin_validation_log")
    op.drop_table("child_twin_states")
