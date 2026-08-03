from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://localhost:3000"
    app_secret_key: str = "change-me"
    access_token_expire_minutes: int = 720

    # Known insecure defaults that must not be used in production.
    _INSECURE_DEFAULT_SECRET = "change-me"
    _INSECURE_DEFAULT_ADMIN_PASSWORD = "change-this-password"
    _MIN_SECRET_LENGTH = 32

    postgres_url: str = "postgresql+psycopg://doc_translator:doc_translator@postgres:5432/doc_translator"
    redis_url: str = "redis://redis:6379/0"

    storage_mode: str = "local"
    local_storage_path: str = "/data/files"
    file_retention_days: int = 7

    model_api_format: str = "chat_completions"
    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_name: str = "gpt-4.1-mini"
    model_timeout_seconds: int = 120

    ocr_enabled: bool = True
    ocr_language_hint: str = "auto"

    max_upload_mb: int = 100
    max_concurrent_jobs: int = 10

    admin_email: str = "admin@example.com"
    admin_password: str = "change-this-password"
    admin_name: str = "Administrator"

    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class InsecureConfigurationError(RuntimeError):
    """Raised when production starts with known-insecure default secrets."""


def assert_secure_for_production(settings: Settings) -> None:
    """Refuse to boot in production with insecure default secrets.

    Guards against the most common misdeployment: copying ``.env.example``
    and forgetting to rotate the JWT secret or the bootstrap admin password.
    """

    if settings.app_env != "production":
        return

    problems: list[str] = []
    if settings.app_secret_key == settings._INSECURE_DEFAULT_SECRET or len(settings.app_secret_key) < settings._MIN_SECRET_LENGTH:
        problems.append(
            f"app_secret_key must be set to a unique value of at least {settings._MIN_SECRET_LENGTH} characters "
            f"(still the default or too short)."
        )
    if settings.admin_password == settings._INSECURE_DEFAULT_ADMIN_PASSWORD:
        problems.append("admin_password must be changed from its default before running in production.")
    if problems:
        raise InsecureConfigurationError("; ".join(problems))
