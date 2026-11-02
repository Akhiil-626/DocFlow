"""Cost-aware model routing extraction attempts table

Revision ID: 005_cost_aware_routing_attempts
Revises: 004_week4a_human_review
Create Date: 2026-11-02 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_cost_aware_routing_attempts"
down_revision: Union[str, None] = "004_week4a_human_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extraction_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "validation_error_codes",
            postgresql.ARRAY(sa.String(length=100)).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("escalation_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "attempt_no", name="uq_extraction_attempts_doc_attempt"),
    )
    op.create_index(op.f("ix_extraction_attempts_document_id"), "extraction_attempts", ["document_id"], unique=False)
    op.create_index(op.f("ix_extraction_attempts_org_id"), "extraction_attempts", ["org_id"], unique=False)
    op.create_index(op.f("ix_extraction_attempts_model"), "extraction_attempts", ["model"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_extraction_attempts_model"), table_name="extraction_attempts")
    op.drop_index(op.f("ix_extraction_attempts_org_id"), table_name="extraction_attempts")
    op.drop_index(op.f("ix_extraction_attempts_document_id"), table_name="extraction_attempts")
    op.drop_table("extraction_attempts")
