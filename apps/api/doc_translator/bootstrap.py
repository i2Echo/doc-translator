import logging
from pathlib import Path

from sqlalchemy.orm import Session

from doc_translator.audit import record_audit
from doc_translator.auth import hash_password
from doc_translator.core.config import get_settings
from doc_translator.models import User, UserRole
from doc_translator.settings_service import get_runtime_settings, seed_missing_settings
from doc_translator.storage import ensure_storage_directories


logger = logging.getLogger(__name__)


def bootstrap_defaults(session: Session) -> None:
    settings = get_settings()
    seed_missing_settings(session)

    # Only seed the bootstrap admin when the system has NO active admin at all.
    # The previous check ("does admin_email already exist?") would silently
    # create a second admin — with the default password — on any start where
    # that email was absent, even if other admins already existed.
    active_admin = (
        session.query(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
        .first()
    )
    if active_admin is None:
        if settings.admin_password == settings._INSECURE_DEFAULT_ADMIN_PASSWORD:
            logger.warning(
                "No active admin found but admin_password is still the insecure default; "
                "skipping bootstrap admin creation. Set ADMIN_PASSWORD before starting."
            )
        else:
            session.add(
                User(
                    email=settings.admin_email.lower(),
                    full_name=settings.admin_name,
                    password_hash=hash_password(settings.admin_password),
                    role=UserRole.ADMIN,
                    is_active=True,
                )
            )
            record_audit(
                session,
                action="auth.bootstrap_admin_created",
                entity_type="user",
                entity_id=settings.admin_email.lower(),
                details={"email": settings.admin_email.lower()},
            )
    session.commit()

    runtime = get_runtime_settings(session)
    ensure_storage_directories(runtime.local_storage_path)
    Path(runtime.local_storage_path).mkdir(parents=True, exist_ok=True)
