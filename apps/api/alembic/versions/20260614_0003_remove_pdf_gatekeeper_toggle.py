from __future__ import annotations

from alembic import op


revision = "20260614_0003"
down_revision = "20260613_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE translation_jobs DROP COLUMN IF EXISTS pdf_gatekeeper_enabled")


def downgrade() -> None:
    op.execute("ALTER TABLE translation_jobs ADD COLUMN IF NOT EXISTS pdf_gatekeeper_enabled BOOLEAN NOT NULL DEFAULT TRUE")
