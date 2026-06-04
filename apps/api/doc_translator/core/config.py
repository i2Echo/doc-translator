from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://localhost:3000"
    app_secret_key: str = "change-me"
    access_token_expire_minutes: int = 720

    postgres_url: str = "postgresql+psycopg://doc_translator:doc_translator@postgres:5432/doc_translator"
    redis_url: str = "redis://redis:6379/0"

    storage_mode: str = "local"
    local_storage_path: str = "/data/files"
    file_retention_days: int = 7

    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_name: str = "gpt-4.1-mini"
    model_timeout_seconds: int = 120

    ocr_enabled: bool = True
    ocr_language_hint: str = "auto"

    max_upload_mb: int = 100
    max_concurrent_jobs: int = 2

    admin_email: str = "admin@example.com"
    admin_password: str = "change-this-password"
    admin_name: str = "Administrator"

    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

