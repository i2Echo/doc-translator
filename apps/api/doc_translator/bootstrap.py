from pathlib import Path

from sqlalchemy.orm import Session

from doc_translator.auth import hash_password
from doc_translator.core.config import get_settings
from doc_translator.models import User, UserRole
from doc_translator.settings_service import get_runtime_settings, seed_missing_settings
from doc_translator.storage import ensure_storage_directories


def bootstrap_defaults(session: Session) -> None:
    settings = get_settings()
    seed_missing_settings(session)

    existing_admin = session.query(User).filter(User.email == settings.admin_email.lower()).first()
    if existing_admin is None:
        session.add(
            User(
                email=settings.admin_email.lower(),
                full_name=settings.admin_name,
                password_hash=hash_password(settings.admin_password),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
    session.commit()

    runtime = get_runtime_settings(session)
    ensure_storage_directories(runtime.local_storage_path)
    Path(runtime.local_storage_path).mkdir(parents=True, exist_ok=True)

