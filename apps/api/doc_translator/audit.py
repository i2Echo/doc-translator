from sqlalchemy.orm import Session

from doc_translator.models import AuditLog


def record_audit(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_id: str | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        details=details,
    )
    session.add(log)
    return log

