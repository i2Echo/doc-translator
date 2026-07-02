from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from doc_translator.audit import record_audit
from doc_translator.auth import authenticate_user, create_access_token, get_current_user, require_admin
from doc_translator.babeldoc_hooks import babeldoc_structure_snapshot_path
from doc_translator.bootstrap import bootstrap_defaults
from doc_translator.core.config import get_settings
from doc_translator.core.logging import configure_logging
from doc_translator.db import SessionLocal, check_database_health, get_db
from doc_translator.models import AuditLog, JobFile, JobFileKind, JobStatus, TranslationJob, User
from doc_translator.preview import load_or_create_preview, update_preview
from doc_translator.queueing import enqueue_job, get_redis_client
from doc_translator.schemas import (
    AuditLogRead,
    AuditLogListRead,
    JobDetail,
    JobPreviewRead,
    JobPreviewUpdate,
    JobRead,
    ModelTestResult,
    SettingsRead,
    SettingsTestRequest,
    SettingsUpdate,
    StorageSummary,
    TokenResponse,
    UserCreate,
    UserListRead,
    UserRead,
    UserUpdate,
)
from doc_translator.settings_service import RuntimeSettings, get_runtime_settings, get_settings_response, update_settings
from doc_translator.storage import persist_upload
from doc_translator.translation import test_model_connection


def get_request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    with SessionLocal() as session:
        bootstrap_defaults(session)
    yield


app = FastAPI(title="Doc Translator API", version="0.1.0", lifespan=lifespan)

_TRANSLATION_LANGUAGE_ALIASES = {
    "auto": "auto",
    "auto detect": "auto",
    "zh": "chinese",
    "zh-cn": "chinese",
    "chinese": "chinese",
    "en": "english",
    "english": "english",
    "ja": "japanese",
    "japanese": "japanese",
    "ko": "korean",
    "korean": "korean",
    "ms": "malay",
    "malay": "malay",
    "th": "thai",
    "thai": "thai",
    "vi": "vietnamese",
    "vietnamese": "vietnamese",
}


def normalize_translation_language(language: str) -> str:
    normalized = language.strip().casefold()
    return _TRANSLATION_LANGUAGE_ALIASES.get(normalized, normalized)


def has_same_translation_language(source_language: str, target_language: str) -> bool:
    normalized_source_language = normalize_translation_language(source_language)
    if not normalized_source_language or normalized_source_language == "auto":
        return False
    return normalized_source_language == normalize_translation_language(target_language)


def load_job_or_404(session: Session, job_id: str, current_user: User) -> TranslationJob:
    job = (
        session.query(TranslationJob)
        .options(
            selectinload(TranslationJob.created_by_user),
            selectinload(TranslationJob.input_file),
            selectinload(TranslationJob.output_file),
            selectinload(TranslationJob.events),
        )
        .filter(TranslationJob.id == job_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if current_user.role.value != "admin" and job.created_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def build_runtime_override(runtime: RuntimeSettings, payload: SettingsTestRequest) -> RuntimeSettings:
    data = runtime.__dict__.copy()
    override = payload.model_dump(exclude_none=True)
    data.update(override)
    return RuntimeSettings(**data)


def ensure_job_has_previewable_output(job: TranslationJob) -> None:
    if job.status != JobStatus.COMPLETED or job.output_file is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preview is available after translation completes")
    if job.output_file.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Preview is no longer available because the translated file expired")


def load_job_document(job: TranslationJob, document_kind: str) -> JobFile:
    if document_kind == "source":
        return job.input_file
    if document_kind == "translated":
        if job.output_file is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No translated file is available yet")
        if job.output_file.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Translated file has expired")
        return job.output_file
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


def load_job_debug_artifact_path(job: TranslationJob, artifact_kind: str):
    if job.status != JobStatus.COMPLETED or job.output_file is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Debug artifacts are available after translation completes")
    if job.output_file.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Debug artifacts are no longer available because the translated file expired")
    if artifact_kind == "structure-before":
        path = babeldoc_structure_snapshot_path(Path(job.output_file.storage_path), "before_translation")
    elif artifact_kind == "structure-after":
        path = babeldoc_structure_snapshot_path(Path(job.output_file.storage_path), "after_translation")
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debug artifact not found")
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debug artifact not found")
    return path


@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_db),
) -> TokenResponse:
    user = authenticate_user(session, form_data.username, form_data.password)
    if user is None:
        record_audit(
            session,
            action="auth.login_failed",
            entity_type="user",
            entity_id=form_data.username,
            ip_address=get_request_ip(request),
            details={"username": form_data.username},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    record_audit(
        session,
        action="auth.login_succeeded",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        ip_address=get_request_ip(request),
    )
    session.commit()
    return TokenResponse(access_token=create_access_token(user), user=UserRead.model_validate(user))


@app.get("/api/v1/auth/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


@app.get("/api/v1/health/live")
def live() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
def ready() -> dict:
    check_database_health()
    redis_client = get_redis_client()
    redis_client.ping()
    return {"status": "ok"}


@app.get("/api/v1/users", response_model=UserListRead)
def list_users(
    _: User = Depends(require_admin),
    session: Session = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> UserListRead:
    query = session.query(User)
    total = session.query(func.count(User.id)).scalar() or 0
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return UserListRead(
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(users) < total,
    )


@app.post("/api/v1/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> UserRead:
    existing = session.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    from doc_translator.auth import hash_password

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    session.add(user)
    session.flush()
    record_audit(
        session,
        action="users.created",
        entity_type="user",
        entity_id=user.id,
        actor_id=admin.id,
        ip_address=get_request_ip(request),
        details={"email": user.email, "role": user.role.value},
    )
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@app.patch("/api/v1/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> UserRead:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    data = payload.model_dump(exclude_none=True)
    if "full_name" in data:
        user.full_name = data["full_name"]
    if "role" in data:
        user.role = data["role"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "password" in data:
        from doc_translator.auth import hash_password

        user.password_hash = hash_password(data["password"])
    record_audit(
        session,
        action="users.updated",
        entity_type="user",
        entity_id=user.id,
        actor_id=admin.id,
        ip_address=get_request_ip(request),
        details={"fields": sorted(data.keys())},
    )
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@app.get("/api/v1/settings", response_model=SettingsRead)
def read_settings(_: User = Depends(require_admin), session: Session = Depends(get_db)) -> SettingsRead:
    return get_settings_response(session)


@app.put("/api/v1/settings", response_model=SettingsRead)
def save_settings(
    payload: SettingsUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> SettingsRead:
    changed_keys = update_settings(session, payload, admin.id)
    record_audit(
        session,
        action="settings.updated",
        entity_type="system_settings",
        actor_id=admin.id,
        ip_address=get_request_ip(request),
        details={"changed_keys": changed_keys},
    )
    session.commit()
    return get_settings_response(session)


@app.post("/api/v1/settings/test-model", response_model=ModelTestResult)
def test_model(
    payload: SettingsTestRequest,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> ModelTestResult:
    runtime = build_runtime_override(get_runtime_settings(session), payload)
    latency_ms, preview = test_model_connection(runtime)
    record_audit(
        session,
        action="settings.model_test",
        entity_type="system_settings",
        actor_id=admin.id,
        ip_address=get_request_ip(request),
        details={"model_name": runtime.model_name, "model_base_url": runtime.model_base_url, "latency_ms": latency_ms},
    )
    session.commit()
    return ModelTestResult(ok=True, latency_ms=latency_ms, preview=preview)


@app.post("/api/v1/jobs/upload", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def upload_job(
    request: Request,
    file: UploadFile = File(...),
    source_language: str = Form(...),
    target_language: str = Form(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> JobRead:
    if has_same_translation_language(source_language, target_language):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target language are the same. No translation is needed, or choose a different target language.",
        )

    runtime = get_runtime_settings(session)
    file_meta = persist_upload(file, runtime)

    input_file = JobFile(kind=JobFileKind.INPUT, created_by=current_user.id, **file_meta)
    session.add(input_file)
    session.flush()

    job = TranslationJob(
        created_by=current_user.id,
        status=JobStatus.QUEUED,
        progress=0,
        source_language=source_language,
        target_language=target_language,
        input_file_id=input_file.id,
        model_base_url_snapshot=runtime.model_base_url,
        model_name_snapshot=runtime.model_name,
    )
    session.add(job)
    session.flush()
    record_audit(
        session,
        action="jobs.created",
        entity_type="translation_job",
        entity_id=job.id,
        actor_id=current_user.id,
        ip_address=get_request_ip(request),
        details={"file_name": input_file.original_name, "target_language": target_language},
    )
    session.commit()
    enqueue_job(job.id)

    job = load_job_or_404(session, job.id, current_user)
    return JobRead.model_validate(job)


@app.get("/api/v1/jobs", response_model=list[JobRead])
def list_jobs(current_user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> list[JobRead]:
    query = session.query(TranslationJob).options(
        selectinload(TranslationJob.created_by_user),
        selectinload(TranslationJob.input_file),
        selectinload(TranslationJob.output_file),
    )
    if current_user.role.value != "admin":
        query = query.filter(TranslationJob.created_by == current_user.id)
    jobs = query.order_by(TranslationJob.created_at.desc()).all()
    return [JobRead.model_validate(job) for job in jobs]


@app.get("/api/v1/jobs/{job_id}", response_model=JobDetail)
def job_detail(job_id: str, current_user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> JobDetail:
    job = load_job_or_404(session, job_id, current_user)
    return JobDetail.model_validate(job)


@app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> JobRead:
    job = load_job_or_404(session, job_id, current_user)
    if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job cannot be cancelled")
    job.cancel_requested = True
    if job.status == JobStatus.QUEUED:
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)
    record_audit(
        session,
        action="jobs.cancel_requested",
        entity_type="translation_job",
        entity_id=job.id,
        actor_id=current_user.id,
        ip_address=get_request_ip(request),
        details={"status": job.status.value},
    )
    session.commit()
    session.refresh(job)
    return JobRead.model_validate(job)


@app.post("/api/v1/jobs/{job_id}/retry", response_model=JobRead)
def retry_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> JobRead:
    job = load_job_or_404(session, job_id, current_user)
    if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or cancelled jobs can be retried")
    job.status = JobStatus.QUEUED
    job.progress = 0
    job.error_message = None
    job.cancel_requested = False
    job.started_at = None
    job.completed_at = None
    record_audit(
        session,
        action="jobs.retried",
        entity_type="translation_job",
        entity_id=job.id,
        actor_id=current_user.id,
        ip_address=get_request_ip(request),
    )
    session.commit()
    enqueue_job(job.id)
    session.refresh(job)
    return JobRead.model_validate(job)


@app.get("/api/v1/jobs/{job_id}/download")
def download_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    job = load_job_or_404(session, job_id, current_user)
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Download is available after translation completes")
    if job.output_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No translated file is available yet")
    if job.output_file.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Translated file has expired")
    record_audit(
        session,
        action="jobs.downloaded",
        entity_type="translation_job",
        entity_id=job.id,
        actor_id=current_user.id,
        ip_address=get_request_ip(request),
        details={"output_file_id": job.output_file.id},
    )
    session.commit()
    return FileResponse(path=job.output_file.storage_path, filename=job.output_file.original_name)


@app.get("/api/v1/jobs/{job_id}/documents/{document_kind}")
def read_job_document(
    job_id: str,
    document_kind: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    job = load_job_or_404(session, job_id, current_user)
    job_file = load_job_document(job, document_kind)
    return FileResponse(
        path=job_file.storage_path,
        media_type=job_file.content_type,
        filename=job_file.original_name,
        headers={"Content-Disposition": f'inline; filename="{job_file.original_name}"'},
    )


@app.get("/api/v1/jobs/{job_id}/debug-artifacts/{artifact_kind}")
def read_job_debug_artifact(
    job_id: str,
    artifact_kind: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    job = load_job_or_404(session, job_id, current_user)
    artifact_path = load_job_debug_artifact_path(job, artifact_kind)
    return FileResponse(
        path=artifact_path,
        media_type="application/json",
        filename=artifact_path.name,
    )


@app.get("/api/v1/jobs/{job_id}/preview", response_model=JobPreviewRead)
def read_job_preview(
    job_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> JobPreviewRead:
    job = load_job_or_404(session, job_id, current_user)
    ensure_job_has_previewable_output(job)
    try:
        preview = load_or_create_preview(job)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Could not prepare preview: {exc}") from exc
    return JobPreviewRead.model_validate(preview)


@app.put("/api/v1/jobs/{job_id}/preview", response_model=JobPreviewRead)
def save_job_preview(
    job_id: str,
    payload: JobPreviewUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> JobPreviewRead:
    job = load_job_or_404(session, job_id, current_user)
    ensure_job_has_previewable_output(job)
    try:
        preview = update_preview(job, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    record_audit(
        session,
        action="jobs.preview_updated",
        entity_type="translation_job",
        entity_id=job.id,
        actor_id=current_user.id,
        ip_address=get_request_ip(request),
        details={"page_count": len(preview["pages"])},
    )
    session.commit()
    return JobPreviewRead.model_validate(preview)


@app.get("/api/v1/audit-logs", response_model=AuditLogListRead)
def list_audit_logs(
    _: User = Depends(require_admin),
    session: Session = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
) -> AuditLogListRead:
    query = session.query(AuditLog).options(selectinload(AuditLog.actor))
    total = session.query(func.count(AuditLog.id)).scalar() or 0
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return AuditLogListRead(
        items=[AuditLogRead.model_validate(log) for log in logs],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(logs) < total,
    )


@app.get("/api/v1/storage/summary", response_model=StorageSummary)
def storage_summary(_: User = Depends(require_admin), session: Session = Depends(get_db)) -> StorageSummary:
    total_bytes = session.query(func.coalesce(func.sum(JobFile.size_bytes), 0)).filter(JobFile.deleted_at.is_(None)).scalar() or 0
    active_file_count = session.query(func.count(JobFile.id)).filter(JobFile.deleted_at.is_(None)).scalar() or 0
    input_file_count = (
        session.query(func.count(JobFile.id))
        .filter(JobFile.deleted_at.is_(None), JobFile.kind == JobFileKind.INPUT)
        .scalar()
        or 0
    )
    output_file_count = (
        session.query(func.count(JobFile.id))
        .filter(JobFile.deleted_at.is_(None), JobFile.kind == JobFileKind.OUTPUT)
        .scalar()
        or 0
    )
    deleted_file_count = session.query(func.count(JobFile.id)).filter(JobFile.deleted_at.is_not(None)).scalar() or 0
    return StorageSummary(
        total_bytes=total_bytes,
        active_file_count=active_file_count,
        input_file_count=input_file_count,
        output_file_count=output_file_count,
        deleted_file_count=deleted_file_count,
    )
