import ipaddress
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from doc_translator.core.config import get_settings
from doc_translator.models import SystemSetting
from doc_translator.schemas import SettingsRead, SettingsUpdate


PRIVACY_NOTICE = (
    "Files remain in customer-controlled storage. If the configured model endpoint is external, "
    "document text is sent there for translation by design."
)


class InvalidModelEndpointError(ValueError):
    """Raised when a configured model endpoint is not allowed (SSRF guard)."""


def validate_model_endpoint(base_url: str) -> str:
    """Validate an admin-configured model endpoint to prevent SSRF.

    Rejects non-http(s) schemes and loopback / link-local / private / metadata
    IP hosts. An empty URL is allowed (validated before the admin sets one).
    """

    url = (base_url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise InvalidModelEndpointError(f"Model endpoint must use http or https (got {parsed.scheme!r}).")
    host = (parsed.hostname or "").lower()
    if not host:
        raise InvalidModelEndpointError("Model endpoint is missing a host.")
    # Reject the cloud-metadata IP and obvious internal targets by name first.
    if host in {"metadata.google.internal"}:
        raise InvalidModelEndpointError("Model endpoint must not point to a metadata service.")
    try:
        # host may be a hostname or an IP literal; only screen IP literals here.
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        if addr.is_loopback or addr.is_link_local or addr.is_private or addr.is_unspecified or addr.is_reserved:
            raise InvalidModelEndpointError(
                "Model endpoint must not point to a loopback, link-local, private, reserved, or unspecified address."
            )
    return url


@dataclass(frozen=True)
class SettingDefinition:
    env_name: str
    default: Any
    caster: Callable[[Any], Any]


@dataclass(frozen=True)
class RuntimeSettings:
    storage_mode: str
    local_storage_path: str
    file_retention_days: int
    model_base_url: str
    model_api_key: str
    model_name: str
    model_timeout_seconds: int
    ocr_enabled: bool
    ocr_language_hint: str
    max_upload_mb: int
    max_concurrent_jobs: int


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


settings = get_settings()
SETTING_DEFINITIONS: dict[str, SettingDefinition] = {
    "storage_mode": SettingDefinition("STORAGE_MODE", settings.storage_mode, str),
    "local_storage_path": SettingDefinition("LOCAL_STORAGE_PATH", settings.local_storage_path, str),
    "file_retention_days": SettingDefinition("FILE_RETENTION_DAYS", settings.file_retention_days, int),
    "model_base_url": SettingDefinition("MODEL_BASE_URL", settings.model_base_url, str),
    "model_api_key": SettingDefinition("MODEL_API_KEY", settings.model_api_key, str),
    "model_name": SettingDefinition("MODEL_NAME", settings.model_name, str),
    "model_timeout_seconds": SettingDefinition("MODEL_TIMEOUT_SECONDS", settings.model_timeout_seconds, int),
    "ocr_enabled": SettingDefinition("OCR_ENABLED", settings.ocr_enabled, as_bool),
    "ocr_language_hint": SettingDefinition("OCR_LANGUAGE_HINT", settings.ocr_language_hint, str),
    "max_upload_mb": SettingDefinition("MAX_UPLOAD_MB", settings.max_upload_mb, int),
    "max_concurrent_jobs": SettingDefinition("MAX_CONCURRENT_JOBS", settings.max_concurrent_jobs, int),
}


def seed_missing_settings(session: Session) -> None:
    for key, definition in SETTING_DEFINITIONS.items():
        if session.get(SystemSetting, key) is None:
            session.add(SystemSetting(key=key, value=str(definition.default)))


def _read_setting_value(session: Session, key: str) -> Any:
    definition = SETTING_DEFINITIONS[key]
    setting = session.get(SystemSetting, key)
    raw_value = definition.default if setting is None else setting.value
    return definition.caster(raw_value)


def get_runtime_settings(session: Session) -> RuntimeSettings:
    values = {key: _read_setting_value(session, key) for key in SETTING_DEFINITIONS}
    return RuntimeSettings(**values)


def mask_api_key(raw_key: str) -> str:
    """Return a non-sensitive view of the model API key for API responses."""
    if not raw_key:
        return ""
    if len(raw_key) <= 4:
        return "****"
    return f"****{raw_key[-4:]}"


def get_settings_response(session: Session) -> SettingsRead:
    runtime = get_runtime_settings(session)
    return SettingsRead(
        storage_mode=runtime.storage_mode,
        local_storage_path=runtime.local_storage_path,
        file_retention_days=runtime.file_retention_days,
        model_base_url=runtime.model_base_url,
        model_api_key=mask_api_key(runtime.model_api_key),
        model_name=runtime.model_name,
        model_timeout_seconds=runtime.model_timeout_seconds,
        ocr_enabled=runtime.ocr_enabled,
        ocr_language_hint=runtime.ocr_language_hint,
        max_upload_mb=runtime.max_upload_mb,
        max_concurrent_jobs=runtime.max_concurrent_jobs,
        privacy_notice=PRIVACY_NOTICE,
    )


def update_settings(session: Session, payload: SettingsUpdate, actor_id: str | None) -> list[str]:
    changed_keys: list[str] = []
    runtime = get_runtime_settings(session)
    # model_dump(exclude_unset=True) yields only fields the client actually
    # sent; omitted fields stay None and are left untouched.
    payload_data = payload.model_dump(exclude_unset=True)

    for key, value in payload_data.items():
        if key not in SETTING_DEFINITIONS:
            continue
        # None on a partial update means "leave unchanged".
        if value is None:
            continue
        # SSRF guard on the model endpoint (also enforced at the schema layer).
        if key == "model_base_url":
            validate_model_endpoint(str(value))
        existing = getattr(runtime, key)
        if existing != value:
            setting = session.get(SystemSetting, key)
            if setting is None:
                setting = SystemSetting(key=key, value=str(value), updated_by=actor_id)
                session.add(setting)
            else:
                setting.value = str(value)
                setting.updated_by = actor_id
            changed_keys.append(key)
    return changed_keys

