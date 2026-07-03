from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

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


class UserListRead(BaseModel):
    items: list[UserRead]
    total: int
    offset: int
    limit: int
    has_more: bool


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
    # Masked: never returns the raw key to the client. Empty string means no
    # key is configured; otherwise only the last 4 characters are exposed so
    # the admin can confirm *which* key is set without being able to use it.
    model_api_key: str
    model_name: str
    model_timeout_seconds: int
    ocr_enabled: bool
    ocr_language_hint: str
    max_upload_mb: int
    max_concurrent_jobs: int
    privacy_notice: str


class SettingsUpdate(BaseModel):
    # Partial update: every field is Optional. ``None`` (field omitted) means
    # "leave unchanged"; an explicit value replaces the stored one. This lets
    # the admin save other settings without round-tripping the raw API key.
    storage_mode: str | None = Field(default=None)
    local_storage_path: str | None = None
    file_retention_days: int | None = Field(default=None, ge=1, le=3650)
    model_base_url: str | None = None
    model_api_key: str | None = None
    model_name: str | None = None
    model_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    ocr_enabled: bool | None = None
    ocr_language_hint: str | None = None
    max_upload_mb: int | None = Field(default=None, ge=1, le=2048)
    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=16)

    @model_validator(mode="after")
    def validate_model_endpoint_field(self) -> "SettingsUpdate":
        if self.model_base_url is not None:
            # Imported here to avoid a circular import (settings_service imports schemas).
            from doc_translator.settings_service import validate_model_endpoint

            validate_model_endpoint(self.model_base_url)
        return self


class SettingsTestRequest(BaseModel):
    model_base_url: str | None = None
    model_api_key: str | None = None
    model_name: str | None = None
    model_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_test_model_endpoint_field(self) -> "SettingsTestRequest":
        if self.model_base_url is not None:
            from doc_translator.settings_service import validate_model_endpoint

            validate_model_endpoint(self.model_base_url)
        return self


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


class JobPreviewPdfTextBlockRead(BaseModel):
    type: Literal["text"] = "text"
    block_id: str
    rect: list[float] = Field(min_length=4, max_length=4)
    font_name: str
    font_size_original: float
    font_size_current: float
    src_text: str
    tgt_text: str
    alignment: Literal["CENTER"] | None = None
    font_style: Literal["BOLD"] | None = None
    rotation: int | None = None
    layout_status: Literal["ok", "overflow"] | None = None


class JobPreviewPdfTableCellRead(BaseModel):
    cell_id: str
    row_index: int = Field(ge=1)
    col_index: int = Field(ge=1)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    rect: list[float] = Field(min_length=4, max_length=4)
    font_name: str
    font_size_original: float
    font_size_current: float
    src_text: str
    tgt_text: str
    alignment: Literal["CENTER"] | None = None
    font_style: Literal["BOLD"] | None = None
    rotation: int | None = None
    layout_status: Literal["ok", "overflow"] | None = None


class JobPreviewPdfTableBlockRead(BaseModel):
    type: Literal["table"]
    block_id: str
    table_rect: list[float] = Field(min_length=4, max_length=4)
    rows_count: int = Field(ge=1)
    cols_count: int = Field(ge=1)
    cells: list[JobPreviewPdfTableCellRead] = Field(default_factory=list)


class JobPreviewPageRead(BaseModel):
    id: str | None = None
    label: str | None = None
    source_text: str | None = None
    translated_text: str | None = None
    page_num: int | None = None
    page_width: float | None = None
    page_height: float | None = None
    blocks: list[JobPreviewPdfTextBlockRead | JobPreviewPdfTableBlockRead] = Field(default_factory=list)


class JobPreviewRead(BaseModel):
    job_id: str
    title: str
    output_name: str
    document_kind: Literal["pdf", "docx"]
    source_language: str
    target_language: str
    created_at: datetime
    updated_at: datetime
    pages: list[JobPreviewPageRead]


class JobPreviewPageUpdate(BaseModel):
    id: str
    translated_text: str


class JobPreviewPdfBlockUpdate(BaseModel):
    block_id: str | None = None
    cell_id: str | None = None
    tgt_text: str
    font_size_final: float = Field(ge=0.5)
    layout_status: Literal["ok", "overflow"] | None = None

    @model_validator(mode="after")
    def validate_identifier(self) -> "JobPreviewPdfBlockUpdate":
        if bool(self.block_id) == bool(self.cell_id):
            raise ValueError("Provide exactly one of block_id or cell_id")
        return self


class JobPreviewUpdate(BaseModel):
    pages: list[JobPreviewPageUpdate] | None = None
    status: Literal["validated"] | None = None
    payload: list[JobPreviewPdfBlockUpdate] | None = None


class AuditLogRead(ORMModel):
    id: str
    action: str
    entity_type: str
    entity_id: str | None
    ip_address: str | None
    details: dict[str, Any] | None
    created_at: datetime
    actor: UserRead | None = None


class AuditLogListRead(BaseModel):
    items: list[AuditLogRead]
    total: int
    offset: int
    limit: int
    has_more: bool


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
