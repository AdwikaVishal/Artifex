"""Create child_life_events (append-only) and 5 supporting tables
for the Child Life Timeline.

child_life_events is the materialized event store populated by a batch
pipeline from supporting tables. It is append-only — corrections create
new rows referencing the superseded row via superseded_by.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. child_life_events (append-only, core) ──────────────────────────────
    op.create_table(
        "child_life_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("seal_level", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("source_table", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("conflict_resolution", sa.Text(), nullable=True),
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
        sa.ForeignKeyConstraint(["superseded_by"], ["child_life_events.id"],),
    )
    op.create_index("idx_cle_child_date", "child_life_events", ["child_id", sa.text("event_date DESC")],)
    op.create_index("idx_cle_event_type", "child_life_events", ["event_type"],)
    op.create_index("idx_cle_recorded_at", "child_life_events", ["recorded_at"],)
    op.create_index("idx_cle_superseded_by", "child_life_events", ["superseded_by"],)

    # ── 2. school_enrollments ─────────────────────────────────────────────────
    op.create_table(
        "school_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("school_name", sa.Text(), nullable=False),
        sa.Column("grade", sa.Text(), nullable=True),
        sa.Column("enrolled_on", sa.Date(), nullable=False),
        sa.Column("withdrawn_on", sa.Date(), nullable=True),
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
        sa.Column("school_district", sa.Text(), nullable=True),
        sa.Column("iep_active", sa.Boolean(), nullable=True),
        sa.Column("attendance_rate_pct", sa.Float(), nullable=True),
        sa.Column("days_out_of_school", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
    )
    op.create_index("idx_school_child", "school_enrollments", ["child_id", sa.text("enrolled_on DESC")],)

    # ── 3. court_dates ────────────────────────────────────────────────────────
    op.create_table(
        "court_dates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("court_date", sa.Date(), nullable=False),
        sa.Column("court_type", sa.Text(), nullable=False),
        sa.Column("judge_name", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("next_court_date", sa.Date(), nullable=True),
        sa.Column("legal_representation", sa.Text(), nullable=True),
        sa.Column("case_plan_updates", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
    )
    op.create_index("idx_court_child", "court_dates", ["child_id", sa.text("court_date DESC")],)

    # ── 4. medical_events ─────────────────────────────────────────────────────
    op.create_table(
        "medical_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("provider_name", sa.Text(), nullable=True),
        sa.Column("diagnosis", postgresql.JSONB(), nullable=True),
        sa.Column("prescriptions", postgresql.JSONB(), nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("attendance", sa.Text(), nullable=True),
        sa.Column("therapeutic_goal", sa.Text(), nullable=True),
        sa.Column("child_sentiment", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
    )
    op.create_index("idx_medical_child", "medical_events", ["child_id", sa.text("event_date DESC")],)
    op.create_index("idx_medical_type", "medical_events", ["event_type"],)

    # ── 5. sibling_contacts ───────────────────────────────────────────────────
    op.create_table(
        "sibling_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("sibling_id", sa.Text(), nullable=True),
        sa.Column("sibling_name", sa.Text(), nullable=True),
        sa.Column("contact_type", sa.Text(), nullable=False),
        sa.Column("contact_date", sa.Date(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("missed", sa.Boolean(), nullable=True),
        sa.Column("missed_reason", sa.Text(), nullable=True),
        sa.Column("child_sentiment", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
    )
    op.create_index("idx_sibling_child", "sibling_contacts", ["child_id", sa.text("contact_date DESC")],)

    # ── 6. family_visitations ─────────────────────────────────────────────────
    op.create_table(
        "family_visitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("family_member", sa.Text(), nullable=True),
        sa.Column("relationship", sa.Text(), nullable=True),
        sa.Column("visit_type", sa.Text(), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("scheduled_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("occurred", sa.Boolean(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("supervised", sa.Boolean(), nullable=True),
        sa.Column("post_visit_summary", sa.Text(), nullable=True),
        sa.Column("child_sentiment", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
    )
    op.create_index("idx_visitation_child", "family_visitations", ["child_id", sa.text("visit_date DESC")],)

    # ── 7. caseworker_assignments ─────────────────────────────────────────────
    op.create_table(
        "caseworker_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("caseworker_id", sa.Text(), nullable=False),
        sa.Column("caseworker_name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("assigned_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.child_id"],),
    )
    op.create_index("idx_cw_child", "caseworker_assignments", ["child_id", sa.text("assigned_on DESC")],)

    # ── 8. Add timeline event types to ml_decision_audit CK ───────────────────
    # (No CK change needed — child_life_events is separate from ml_decision_audit)


def downgrade() -> None:
    op.drop_table("caseworker_assignments")
    op.drop_table("family_visitations")
    op.drop_table("sibling_contacts")
    op.drop_table("medical_events")
    op.drop_table("court_dates")
    op.drop_table("school_enrollments")
    op.drop_table("child_life_events")
