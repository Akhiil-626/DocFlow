"""Week 4A: Human Review Workflow, Export Batches, and Extraction Versioning

Revision ID: 004_week4a_human_review
Revises: 003_week3_validation_and_review
Create Date: 2026-10-19 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004_week4a_human_review"
down_revision: Union[str, None] = "003_week3_validation_and_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create export_batches table
    op.create_table(
        "export_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_export_batches_org_id"), "export_batches", ["org_id"], unique=False)

    # 2. Add review & export columns to documents
    op.add_column("documents", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("export_batch_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_documents_reviewed_by_users",
        "documents",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_documents_export_batch_id_export_batches",
        "documents",
        "export_batches",
        ["export_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_documents_export_batch_id"), "documents", ["export_batch_id"], unique=False)

    # 3. Add versioning and audit columns to extractions
    # First add original_data as nullable to allow backfill
    op.add_column("extractions", sa.Column("original_data", sa.JSON(), nullable=True))
    op.add_column(
        "extractions",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("extractions", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("extractions", sa.Column("edited_by", sa.Uuid(), nullable=True))

    op.create_foreign_key(
        "fk_extractions_edited_by_users",
        "extractions",
        "users",
        ["edited_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # Backfill original_data from data
    op.execute("UPDATE extractions SET original_data = data WHERE original_data IS NULL")
    op.alter_column("extractions", "original_data", nullable=False)


def downgrade() -> None:
    # 3. Revert extractions columns
    op.drop_constraint("fk_extractions_edited_by_users", "extractions", type_="foreignkey")
    op.drop_column("extractions", "edited_by")
    op.drop_column("extractions", "edited_at")
    op.drop_column("extractions", "version")
    op.drop_column("extractions", "original_data")

    # 2. Revert documents columns
    op.drop_index(op.f("ix_documents_export_batch_id"), table_name="documents")
    op.drop_constraint("fk_documents_export_batch_id_export_batches", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_reviewed_by_users", "documents", type_="foreignkey")
    op.drop_column("documents", "exported_at")
    op.drop_column("documents", "export_batch_id")
    op.drop_column("documents", "review_note")
    op.drop_column("documents", "reviewed_at")
    op.drop_column("documents", "reviewed_by")

    # 1. Revert export_batches table
    op.drop_index(op.f("ix_export_batches_org_id"), table_name="export_batches")
    op.drop_table("export_batches")
