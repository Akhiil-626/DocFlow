"""Week 3: Validation Issues, Review Queue, and Duplicate Detection Indexes

Revision ID: 003_week3_validation_and_review
Revises: 002_week2_extractions
Create Date: 2026-10-18 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_week3_validation_and_review"
down_revision: Union[str, None] = "002_week2_extractions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add review_reason and validated_at columns to documents
    op.add_column("documents", sa.Column("review_reason", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))

    # 2. Create validation_issues table
    op.create_table(
        "validation_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("field", sa.String(length=100), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_validation_issues_document_id"), "validation_issues", ["document_id"], unique=False)
    op.create_index(op.f("ix_validation_issues_org_id"), "validation_issues", ["org_id"], unique=False)
    op.create_index(op.f("ix_validation_issues_code"), "validation_issues", ["code"], unique=False)

    # 3. Create composite index for efficient duplicate detection
    op.create_index("ix_documents_org_id_sha256", "documents", ["org_id", "sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_org_id_sha256", table_name="documents")
    op.drop_index(op.f("ix_validation_issues_code"), table_name="validation_issues")
    op.drop_index(op.f("ix_validation_issues_org_id"), table_name="validation_issues")
    op.drop_index(op.f("ix_validation_issues_document_id"), table_name="validation_issues")
    op.drop_table("validation_issues")
    op.drop_column("documents", "validated_at")
    op.drop_column("documents", "review_reason")
