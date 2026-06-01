"""Add hash chain to audit_logs and create pending_approvals table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── audit_logs: add hash-chain columns ────────────────────────────────────
    # prev_hash: SHA-256 of the previous row's hash (or '0'*64 for the first row)
    # hash:      SHA-256(prev_hash | action | target_id | timestamp | user_id | role)
    op.add_column(
        "audit_logs",
        sa.Column("prev_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("hash", sa.Text(), nullable=True),
    )
    op.create_index("idx_audit_hash", "audit_logs", ["hash"])

    # ── pending_approvals ─────────────────────────────────────────────────────
    op.create_table(
        "pending_approvals",
        sa.Column("workflow_id", sa.Text(), primary_key=True),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("risk_score", sa.Float(), server_default="0.0"),
        sa.Column("status", sa.Text(), server_default="pending"),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_pending_approvals_status", "pending_approvals", ["status"])
    op.create_index("idx_pending_approvals_created_at", "pending_approvals", ["created_at"])


def downgrade() -> None:
    op.drop_table("pending_approvals")
    op.drop_index("idx_audit_hash", table_name="audit_logs")
    op.drop_column("audit_logs", "hash")
    op.drop_column("audit_logs", "prev_hash")
