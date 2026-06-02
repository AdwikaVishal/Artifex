"""Create behavioural_drift_signals, prediction_feedback, ml_decision_audit,
fairness_audit_log tables, add race/fpl_percent/zip_code to children,
and attach hash-chain trigger for ml_decision_audit.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. children: new fairness columns ─────────────────────────────────────
    op.add_column(
        "children",
        sa.Column("race", sa.Text(), nullable=True,
                  comment="Self-reported race/ethnicity. Collected at intake per AFCARS standards."),
    )
    op.add_column(
        "children",
        sa.Column("fpl_percent", sa.Float(), nullable=True,
                  comment="Household income as % of Federal Poverty Level at time of removal. SES proxy."),
    )
    op.add_column(
        "children",
        sa.Column("zip_code", sa.Text(), nullable=True,
                  comment="3-digit ZIP code prefix of the child's home of origin. Geographic SES proxy."),
    )

    # ── 2. behavioural_drift_signals ───────────────────────────────────────────
    op.create_table(
        "behavioural_drift_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("placement_id", sa.Text(), nullable=False),
        sa.Column("snapshot_date", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("signals_json", postgresql.JSONB(), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=True),
        sa.Column("trend_direction", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
        sa.ForeignKeyConstraint(["placement_id"], ["placements.workflow_id"],),
        sa.UniqueConstraint("child_id", "window_start", "window_end", name="uq_child_window"),
    )
    op.create_index(
        "idx_behavioural_drift_child",
        "behavioural_drift_signals",
        ["child_id", sa.text("snapshot_date DESC")],
    )
    op.create_index(
        "idx_behavioural_drift_placement",
        "behavioural_drift_signals",
        ["placement_id", sa.text("snapshot_date DESC")],
    )
    op.create_index(
        "idx_behavioural_drift_score",
        "behavioural_drift_signals",
        [sa.text("drift_score DESC")],
    )

    # ── 3. prediction_feedback ─────────────────────────────────────────────────
    op.create_table(
        "prediction_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("placement_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("disruption", sa.Boolean(), nullable=False),
        sa.Column("disruption_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("submitted_by", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("outcome IN ('stable', 'disrupted')", name="ck_feedback_outcome"),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
        sa.ForeignKeyConstraint(["placement_id"], ["placements.workflow_id"],),
        sa.UniqueConstraint("placement_id", name="uq_feedback_placement"),
    )
    op.create_index("idx_feedback_child", "prediction_feedback", ["child_id"])
    op.create_index("idx_feedback_outcome", "prediction_feedback", ["outcome", "submitted_at"])

    # ── 4. ml_decision_audit ───────────────────────────────────────────────────
    op.create_table(
        "ml_decision_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # WHO
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("placement_id", sa.Text(), nullable=True),
        sa.Column("caseworker_id", sa.Text(), nullable=True),
        # WHAT
        sa.Column("decision_type", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("feature_hash", sa.Text(), nullable=True),
        # INPUT
        sa.Column("input_features", postgresql.JSONB(), nullable=False),
        sa.Column("child_demographics", postgresql.JSONB(), nullable=False),
        # OUTPUT
        sa.Column("output_score", sa.Float(), nullable=True),
        sa.Column("output_label", sa.Text(), nullable=True),
        sa.Column("output_confidence", sa.Float(), nullable=True),
        sa.Column("output_details", postgresql.JSONB(), nullable=True),
        # HUMAN FACTOR
        sa.Column("human_overridden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("human_decision", sa.Text(), nullable=True),
        sa.Column("human_comment", sa.Text(), nullable=True),
        sa.Column("overridden_by", sa.Text(), nullable=True),
        sa.Column("overridden_at", sa.TIMESTAMP(), nullable=True),
        # AUDIT INFRASTRUCTURE
        sa.Column("decided_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("ingested_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("hash", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "decision_type IN ('placement_match', 'risk_score', 'crisis_prediction', 'family_recommendation', 'human_override')",
            name="ck_ml_audit_decision_type",
        ),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
        sa.ForeignKeyConstraint(["placement_id"], ["placements.workflow_id"],),
        sa.UniqueConstraint("child_id", "decision_type", "decided_at", name="uq_decision"),
    )
    op.create_index("idx_ml_audit_child", "ml_decision_audit", ["child_id"])
    op.create_index("idx_ml_audit_type", "ml_decision_audit", ["decision_type"])
    op.create_index("idx_ml_audit_demographics", "ml_decision_audit", [sa.text("child_demographics")], postgresql_using="gin")
    op.create_index("idx_ml_audit_features", "ml_decision_audit", [sa.text("input_features")], postgresql_using="gin")
    op.create_index("idx_ml_audit_score", "ml_decision_audit", [sa.text("output_score DESC")])
    op.create_index("idx_ml_audit_decided_at", "ml_decision_audit", [sa.text("decided_at DESC")])
    op.create_index("idx_ml_audit_model_ver", "ml_decision_audit", ["model_version"])
    op.create_index("idx_ml_audit_hash", "ml_decision_audit", ["hash"])

    # ── 4a. Hash-chain trigger for ml_decision_audit ──────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION compute_ml_decision_hash()
        RETURNS TRIGGER AS $$
        DECLARE
          last_hash TEXT;
        BEGIN
          SELECT COALESCE(
            (SELECT hash FROM ml_decision_audit ORDER BY id DESC LIMIT 1),
            REPEAT('0', 64)
          ) INTO last_hash;
          NEW.prev_hash := last_hash;
          NEW.hash := encode(
            sha256(
              (last_hash || '|' || NEW.decision_type || '|' ||
               NEW.child_id || '|' || NEW.decided_at::text || '|' ||
               COALESCE(NEW.output_score::text, '') || '|' ||
               COALESCE(NEW.model_version, ''))::bytea
            ),
            'hex'
          );
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_ml_decision_audit_hash
          BEFORE INSERT ON ml_decision_audit
          FOR EACH ROW
          EXECUTE FUNCTION compute_ml_decision_hash();
        """
    )

    # ── 5. fairness_audit_log ──────────────────────────────────────────────────
    op.create_table(
        "fairness_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_week", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("model_version", sa.Text(), nullable=False),
        # Demographic parity
        sa.Column("dp_race", sa.Float(), nullable=True),
        sa.Column("dp_ses", sa.Float(), nullable=True),
        sa.Column("dp_gender", sa.Float(), nullable=True),
        sa.Column("dp_special_needs", sa.Float(), nullable=True),
        sa.Column("dp_age_group", sa.Float(), nullable=True),
        # Equalized odds
        sa.Column("fpr_disparity", sa.Float(), nullable=True),
        sa.Column("fnr_disparity", sa.Float(), nullable=True),
        # Calibration
        sa.Column("max_ece", sa.Float(), nullable=True),
        # Individual fairness
        sa.Column("consistency", sa.Float(), nullable=True),
        sa.Column("nn_disparity", sa.Float(), nullable=True),
        # Historical bias
        sa.Column("bar_race", sa.Float(), nullable=True),
        sa.Column("bar_ses", sa.Float(), nullable=True),
        # Alert flags
        sa.Column("flags", postgresql.JSONB(), nullable=True),
        sa.Column("overall_status", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_fairness_week",
        "fairness_audit_log",
        [sa.text("report_week DESC")],
    )


def downgrade() -> None:
    op.drop_table("fairness_audit_log")

    op.execute("DROP TRIGGER IF EXISTS trg_ml_decision_audit_hash ON ml_decision_audit")
    op.execute("DROP FUNCTION IF EXISTS compute_ml_decision_hash()")
    op.drop_table("ml_decision_audit")

    op.drop_table("prediction_feedback")

    op.drop_table("behavioural_drift_signals")

    op.drop_column("children", "zip_code")
    op.drop_column("children", "fpl_percent")
    op.drop_column("children", "race")
