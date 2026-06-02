"""Initial schema – all Artifex tables.

Revision ID: 0001
Revises:
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── placements ────────────────────────────────────────────────────────────
    op.create_table(
        "placements",
        sa.Column("workflow_id", sa.Text(), primary_key=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("family_id", sa.Text(), nullable=True),
        sa.Column("family_json", postgresql.JSONB(), nullable=True),
        sa.Column("risk_score", sa.Float(), server_default="0.0"),
        sa.Column("risk_explanation", sa.Text(), nullable=True),
        sa.Column("match_explanation", sa.Text(), nullable=True),
        sa.Column("last_notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active"),
        sa.Column("supervisor_required", sa.Boolean(), server_default="false"),
        sa.Column("caseworker_id", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_child_id", "placements", ["child_id"])
    op.create_index("idx_risk_score", "placements", [sa.text("risk_score DESC")])
    op.create_index("idx_status", "placements", ["status"])

    # ── workflow_events ───────────────────────────────────────────────────────
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_wf_events_wfid", "workflow_events", ["workflow_id"])

    # ── workflow_status ───────────────────────────────────────────────────────
    op.create_table(
        "workflow_status",
        sa.Column("workflow_id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_stage", sa.Text(), nullable=True),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )

    # ── placement_predictions ─────────────────────────────────────────────────
    op.create_table(
        "placement_predictions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("recommended", postgresql.JSONB(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), server_default="0.0"),
        sa.Column("feature_importance", postgresql.JSONB(), nullable=True),
        sa.Column("top_matches", postgresql.JSONB(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )

    # ── ml_inference_logs ─────────────────────────────────────────────────────
    op.create_table(
        "ml_inference_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Text(), nullable=True),
        sa.Column("child_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )

    # ── families ──────────────────────────────────────────────────────────────
    op.create_table(
        "families",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("family_id", sa.Text(), unique=True, nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), server_default=""),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("capacity", sa.Integer(), server_default="1"),
        sa.Column("available_capacity", sa.Integer(), server_default="1"),
        sa.Column("total_capacity", sa.Integer(), server_default="1"),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("experience", sa.Text(), server_default="new"),
        sa.Column("experience_level", sa.Text(), server_default="new"),
        sa.Column("specializations", sa.Text(), server_default=""),
        sa.Column("languages", sa.Text(), server_default=""),
        sa.Column(
            "languages_arr",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("special_needs_trained", sa.Boolean(), server_default="false"),
        sa.Column("accepts_siblings", sa.Boolean(), server_default="false"),
        sa.Column("sibling_group_capable", sa.Boolean(), server_default="false"),
        sa.Column("home_type", sa.Text(), server_default="family"),
        sa.Column("emergency_available", sa.Boolean(), server_default="false"),
        sa.Column("max_age", sa.Integer(), server_default="18"),
        sa.Column("can_take_siblings", sa.Boolean(), server_default="false"),
        sa.Column("has_animals", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_families_location", "families", ["location"])

    # ── children ──────────────────────────────────────────────────────────────
    op.create_table(
        "children",
        sa.Column("child_id", sa.Text(), primary_key=True),
        sa.Column("first_name", sa.Text(), server_default=""),
        sa.Column("last_name", sa.Text(), server_default=""),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("gender", sa.Text(), nullable=True),
        sa.Column("special_needs", sa.Boolean(), server_default="false"),
        sa.Column("sibling_group", sa.Boolean(), server_default="false"),
        sa.Column("sibling_count", sa.Integer(), server_default="0"),
        sa.Column("location", sa.Text(), server_default=""),
        sa.Column("languages", sa.Text(), server_default=""),
        sa.Column(
            "languages_arr",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("medical_needs", sa.Text(), server_default=""),
        sa.Column("behavioral_support", sa.Text(), server_default=""),
        sa.Column("intake_reason", sa.Text(), server_default=""),
        sa.Column("emergency_level", sa.Text(), server_default="normal"),
        sa.Column("school_continuity", sa.Boolean(), server_default="false"),
        sa.Column("case_notes", sa.Text(), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_children_age", "children", ["age"])
    op.create_index("idx_children_location", "children", ["location"])

    # ── active_placements ─────────────────────────────────────────────────────
    op.create_table(
        "active_placements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("family_id", sa.Text(), nullable=True),
        sa.Column("placement_start", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
        sa.Column("placement_end", sa.TIMESTAMP(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active"),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint("uq_ap_workflow_id", "active_placements", ["workflow_id"])
    op.create_index("idx_ap_workflow_id", "active_placements", ["workflow_id"])
    op.create_index("idx_ap_family_id", "active_placements", ["family_id"])
    op.create_index("idx_ap_status", "active_placements", ["status"])

    # ── placement_history ─────────────────────────────────────────────────────
    op.create_table(
        "placement_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=True),
        sa.Column("family_id", sa.Text(), nullable=True),
        sa.Column("placement_start", sa.Date(), nullable=True),
        sa.Column("placement_end", sa.Date(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("disruption", sa.Boolean(), server_default="false"),
        sa.Column("disruption_reason", sa.Text(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_ph_child_id", "placement_history", ["child_id"])
    op.create_index("idx_ph_family_id", "placement_history", ["family_id"])
    op.create_index(
        "idx_ph_dates", "placement_history", ["placement_start", "placement_end"]
    )

    # ── check_ins ─────────────────────────────────────────────────────────────
    op.create_table(
        "check_ins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("placement_id", sa.Text(), nullable=True),
        sa.Column("mood_score", sa.Integer(), server_default="3"),
        sa.Column("incident_reported", sa.Boolean(), server_default="false"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("timestamp", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_checkins_child_id", "check_ins", ["child_id"])
    op.create_index(
        "idx_checkins_timestamp", "check_ins", [sa.text("timestamp DESC")]
    )
    op.create_index("idx_checkins_placement_id", "check_ins", ["placement_id"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_audit_timestamp", "audit_logs", [sa.text("timestamp DESC")]
    )
    op.create_index(
        "idx_audit_target", "audit_logs", ["target_type", "target_id"]
    )

    # ── processed_events (deduplication) ─────────────────────────────────────
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column(
            "processed_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_processed_events_processed_at",
        "processed_events",
        ["processed_at"],
    )


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("audit_logs")
    op.drop_table("check_ins")
    op.drop_table("placement_history")
    op.drop_table("active_placements")
    op.drop_table("children")
    op.drop_table("families")
    op.drop_table("ml_inference_logs")
    op.drop_table("placement_predictions")
    op.drop_table("workflow_status")
    op.drop_table("workflow_events")
    op.drop_table("placements")
