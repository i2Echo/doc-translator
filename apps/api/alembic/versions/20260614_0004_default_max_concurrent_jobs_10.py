from __future__ import annotations

from alembic import op


revision = "20260614_0004"
down_revision = "20260614_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        insert into system_settings (key, value, updated_at)
        values ('max_concurrent_jobs', '10', now())
        on conflict (key) do update
        set value = '10',
            updated_at = now()
        where system_settings.value = '2'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        update system_settings
        set value = '2',
            updated_at = now()
        where key = 'max_concurrent_jobs'
          and value = '10'
        """
    )
