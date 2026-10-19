"""Week 2: Extractions and Line Items migration

Revision ID: 002_week2_extractions
Revises: 001_initial_schema
Create Date: 2026-10-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_week2_extractions"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add error_message, processed_at, and attempts columns to documents
    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))

    # 2. Create extractions table
    op.create_table(
        "extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_extractions_document_id"),
    )
    op.create_index(op.f("ix_extractions_document_id"), "extractions", ["document_id"], unique=True)
    op.create_index(op.f("ix_extractions_org_id"), "extractions", ["org_id"], unique=False)

    # 3. Create line_items table
    op.create_table(
        "line_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["extraction_id"], ["extractions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_line_items_extraction_id"), "line_items", ["extraction_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_line_items_extraction_id"), table_name="line_items")
    op.drop_table("line_items")

    op.drop_index(op.f("ix_extractions_org_id"), table_name="extractions")
    op.drop_index(op.f("ix_extractions_document_id"), table_name="extractions")
    op.drop_table("extractions")

    op.drop_column("documents", "attempts")
    op.drop_column("documents", "processed_at")
    op.drop_column("documents", "error_message")
