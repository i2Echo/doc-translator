from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_0005"
down_revision = "20260614_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("translation_jobs", sa.Column("worker_id", sa.String(length=64), nullable=True))
    op.add_column("translation_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_translation_jobs_worker_id", "translation_jobs", ["worker_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_translation_jobs_worker_id", table_name="translation_jobs")
    op.drop_column("translation_jobs", "lease_expires_at")
    op.drop_column("translation_jobs", "worker_id")
