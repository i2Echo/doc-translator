from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from doc_translator.models import JobFileKind, JobStatus, UserRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRead(ORMModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.USER
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class MessageResponse(BaseModel):
    message: str


class SettingsRead(BaseModel):
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
    privacy_notice: str


class SettingsUpdate(BaseModel):
    storage_mode: str = "local"
    local_storage_path: str
    file_retention_days: int = Field(ge=1, le=3650)
    model_base_url: str
    model_api_key: str
    model_name: str
    model_timeout_seconds: int = Field(ge=1, le=3600)
    ocr_enabled: bool
    ocr_language_hint: str
    max_upload_mb: int = Field(ge=1, le=2048)
    max_concurrent_jobs: int = Field(ge=1, le=16)


class SettingsTestRequest(BaseModel):
    model_base_url: str | None = None
    model_api_key: str | None = None
    model_name: str | None = None
    model_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)


class FileRead(ORMModel):
    id: str
    original_name: str
    content_type: str
    size_bytes: int
    kind: JobFileKind
    created_at: datetime
    deleted_at: datetime | None = None


class JobEventRead(ORMModel):
    id: str
    level: str
    message: str
    details: dict[str, Any] | None
    created_at: datetime


class JobRead(ORMModel):
    id: str
    status: JobStatus
    progress: int
    source_language: str
    target_language: str
    model_base_url_snapshot: str
    model_name_snapshot: str
    error_message: str | None
    page_count: int | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    created_by_user: UserRead
    input_file: FileRead
    output_file: FileRead | None = None


class JobDetail(JobRead):
    events: list[JobEventRead]


class AuditLogRead(ORMModel):
    id: str
    action: str
    entity_type: str
    entity_id: str | None
    ip_address: str | None
    details: dict[str, Any] | None
    created_at: datetime
    actor: UserRead | None = None


class StorageSummary(BaseModel):
    total_bytes: int
    active_file_count: int
    input_file_count: int
    output_file_count: int
    deleted_file_count: int


class ModelTestResult(BaseModel):
    ok: bool
    latency_ms: int
    preview: str

