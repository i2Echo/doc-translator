from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from doc_translator.core.config import get_settings
from doc_translator.models import SystemSetting
from doc_translator.schemas import SettingsRead, SettingsUpdate


PRIVACY_NOTICE = (
    "Files remain in customer-controlled storage. If the configured model endpoint is external, "
    "document text is sent there for translation by design."
)


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


def get_settings_response(session: Session) -> SettingsRead:
    runtime = get_runtime_settings(session)
    return SettingsRead(
        storage_mode=runtime.storage_mode,
        local_storage_path=runtime.local_storage_path,
        file_retention_days=runtime.file_retention_days,
        model_base_url=runtime.model_base_url,
        model_api_key=runtime.model_api_key,
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
    current = get_settings_response(session)
    payload_data = payload.model_dump()

    for key, value in payload_data.items():
        existing = getattr(current, key)
        if value == "" and key == "model_api_key":
            value = existing
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

