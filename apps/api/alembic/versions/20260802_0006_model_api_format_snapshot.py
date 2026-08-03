from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_0006"
down_revision = "20260802_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "translation_jobs",
        sa.Column("model_api_format_snapshot", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE translation_jobs
        SET model_api_format_snapshot = COALESCE(
            (SELECT value FROM system_settings WHERE key = 'model_api_format'),
            'chat_completions'
        )
        """
    )
    op.alter_column("translation_jobs", "model_api_format_snapshot", nullable=False)


def downgrade() -> None:
    op.drop_column("translation_jobs", "model_api_format_snapshot")
