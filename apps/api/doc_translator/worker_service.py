from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi import HTTPException
import redis
from sqlalchemy import func, or_

from doc_translator.audit import record_audit
from doc_translator.bootstrap import bootstrap_defaults
from doc_translator.core.config import get_settings
from doc_translator.core.logging import configure_logging
from doc_translator.db import SessionLocal, check_database_health
from doc_translator.models import JobEvent, JobFile, JobStatus, TranslationJob
from doc_translator.babeldoc_hooks import babeldoc_ir_sidecar_path, babeldoc_structure_snapshot_path
from doc_translator.preview import ppt_preview_pdf_path, preview_sidecar_path
from doc_translator.queueing import TRANSLATION_QUEUE_KEY, get_redis_client
from doc_translator.settings_service import get_runtime_settings
from doc_translator.translation import JOB_LEASE_DURATION, run_translation_job


logger = logging.getLogger(__name__)

RECOVERABLE_JOB_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.PARSING,
    JobStatus.OCR_RUNNING,
    JobStatus.TRANSLATING,
    JobStatus.REBUILDING,
    JobStatus.VALIDATING,
}
IN_PROGRESS_JOB_STATUSES = RECOVERABLE_JOB_STATUSES - {JobStatus.QUEUED}
QUEUE_RECONCILE_INTERVAL_SECONDS = 30


class WorkerRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.worker_id = f"worker-{uuid4()}"
        self.stop_event = threading.Event()
        self.dispatch_thread: threading.Thread | None = None
        self.cleanup_thread: threading.Thread | None = None
        self.executor = ThreadPoolExecutor(max_workers=16)
        self.futures: dict[str, Future] = {}
        self.lock = threading.Lock()
        self.last_heartbeat: datetime | None = None
        self.last_queue_reconcile_at = 0.0

    def start(self) -> None:
        configure_logging(self.settings.log_level)
        with SessionLocal() as session:
            bootstrap_defaults(session)
        try:
            self._reconcile_queued_jobs(get_redis_client(), force=True)
        except Exception:
            logger.exception("Initial job recovery failed; dispatch loop will retry")
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        self.cleanup_thread = threading.Thread(target=self.cleanup_loop, daemon=True)
        self.dispatch_thread.start()
        self.cleanup_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.dispatch_thread:
            self.dispatch_thread.join(timeout=5)
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)
        self.executor.shutdown(wait=False, cancel_futures=True)

    def update_heartbeat(self) -> None:
        self.last_heartbeat = datetime.now(timezone.utc)

    def dispatch_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                redis_client = get_redis_client()
                while not self.stop_event.is_set():
                    self.update_heartbeat()
                    self._prune_finished()
                    self._reconcile_queued_jobs(redis_client)
                    concurrency = self._load_concurrency_limit()
                    if len(self.futures) >= concurrency:
                        time.sleep(1)
                        continue

                    item = redis_client.blpop([TRANSLATION_QUEUE_KEY], timeout=1)
                    if item is None:
                        continue
                    _, job_id = item
                    with self.lock:
                        if job_id in self.futures:
                            continue
                        self.futures[job_id] = self.executor.submit(run_translation_job, job_id, self.worker_id)
            except redis.RedisError:
                logger.exception("Worker lost Redis connectivity; retrying shortly")
                self.stop_event.wait(2)
            except Exception:
                logger.exception("Worker dispatch loop failed; retrying shortly")
                self.stop_event.wait(2)

    def _prune_finished(self) -> None:
        with self.lock:
            completed = [job_id for job_id, future in self.futures.items() if future.done()]
            for job_id in completed:
                future = self.futures.pop(job_id)
                try:
                    future.result()
                except Exception:
                    logger.exception("Translation worker task crashed", extra={"job_id": job_id})

    def _reconcile_queued_jobs(self, redis_client: redis.Redis, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_queue_reconcile_at < QUEUE_RECONCILE_INTERVAL_SECONDS:
            return

        current_time = datetime.now(timezone.utc)
        with self.lock:
            active_job_ids = tuple(self.futures)

        recovered_count = 0
        cancelled_count = 0
        with SessionLocal() as session:
            if active_job_ids:
                (
                    session.query(TranslationJob)
                    .filter(
                        TranslationJob.id.in_(active_job_ids),
                        TranslationJob.worker_id == self.worker_id,
                        TranslationJob.status.in_(tuple(IN_PROGRESS_JOB_STATUSES)),
                    )
                    .update(
                        {TranslationJob.lease_expires_at: current_time + JOB_LEASE_DURATION},
                        synchronize_session=False,
                    )
                )

            recoverable_jobs = (
                session.query(TranslationJob)
                .filter(
                    TranslationJob.status.in_(tuple(RECOVERABLE_JOB_STATUSES)),
                    or_(
                        TranslationJob.status == JobStatus.QUEUED,
                        TranslationJob.lease_expires_at.is_(None),
                        TranslationJob.lease_expires_at < current_time,
                    ),
                )
                .order_by(TranslationJob.created_at.asc())
                .with_for_update(skip_locked=True)
                .all()
            )
            for job in recoverable_jobs:
                previous_status = job.status
                if job.cancel_requested:
                    job.status = JobStatus.CANCELLED
                    job.completed_at = current_time
                    session.add(
                        JobEvent(
                            job_id=job.id,
                            level="info",
                            message="Recovered orphaned job and finalized cancellation",
                            details={"recovery": "expired_lease", "previous_status": previous_status.value},
                        )
                    )
                    record_audit(
                        session,
                        action="jobs.recovered_cancelled",
                        entity_type="translation_job",
                        entity_id=job.id,
                        details={"previous_status": previous_status.value},
                    )
                    cancelled_count += 1
                elif job.status != JobStatus.QUEUED:
                    job.status = JobStatus.QUEUED
                    job.progress = 0
                    job.started_at = None
                    job.completed_at = None
                    job.error_message = None
                    session.add(
                        JobEvent(
                            job_id=job.id,
                            level="warning",
                            message="Recovered job after its worker lease expired",
                            details={"recovery": "expired_lease", "previous_status": previous_status.value},
                        )
                    )
                    record_audit(
                        session,
                        action="jobs.recovered_queued",
                        entity_type="translation_job",
                        entity_id=job.id,
                        details={"previous_status": previous_status.value},
                    )
                    recovered_count += 1
                job.worker_id = None
                job.lease_expires_at = None

            session.flush()
            database_job_ids = [
                job_id
                for (job_id,) in (
                    session.query(TranslationJob.id)
                    .filter(TranslationJob.status == JobStatus.QUEUED)
                    .order_by(TranslationJob.created_at.asc())
                    .all()
                )
            ]
            session.commit()

        queued_job_ids = set(redis_client.lrange(TRANSLATION_QUEUE_KEY, 0, -1))
        self.last_queue_reconcile_at = now
        missing_job_ids = [job_id for job_id in database_job_ids if job_id not in queued_job_ids]
        if missing_job_ids:
            redis_client.rpush(TRANSLATION_QUEUE_KEY, *missing_job_ids)
            logger.warning(
                "Re-enqueued jobs missing from Redis",
                extra={"job_count": len(missing_job_ids)},
            )
        if recovered_count or cancelled_count:
            logger.warning(
                "Recovered translation jobs with expired leases",
                extra={
                    "recovered_count": recovered_count,
                    "cancelled_count": cancelled_count,
                    "enqueued_count": len(missing_job_ids),
                },
            )

    def _load_concurrency_limit(self) -> int:
        with SessionLocal() as session:
            return max(1, get_runtime_settings(session).max_concurrent_jobs)

    def cleanup_loop(self) -> None:
        while not self.stop_event.is_set():
            self.update_heartbeat()
            try:
                self.run_cleanup_pass()
            except Exception:
                logger.exception("Retention cleanup failed")
            self.stop_event.wait(300)

    def run_cleanup_pass(self) -> None:
        with SessionLocal() as session:
            runtime = get_runtime_settings(session)
            storage_root = Path(runtime.local_storage_path).resolve()
            cutoff = datetime.now(timezone.utc) - timedelta(days=runtime.file_retention_days)
            expired_files = (
                session.query(JobFile)
                .filter(JobFile.deleted_at.is_(None))
                .filter(JobFile.created_at < cutoff)
                .all()
            )
            for job_file in expired_files:
                job_file_id = job_file.id
                storage_path = job_file.storage_path
                try:
                    artifact_paths = [Path(storage_path)]
                    if job_file.kind.value == "output":
                        artifact_paths.extend(
                            (
                                preview_sidecar_path(storage_path),
                                ppt_preview_pdf_path(storage_path, "source"),
                                ppt_preview_pdf_path(storage_path, "translated"),
                                babeldoc_ir_sidecar_path(Path(storage_path)),
                                babeldoc_structure_snapshot_path(Path(storage_path), "before_translation"),
                                babeldoc_structure_snapshot_path(Path(storage_path), "after_translation"),
                            )
                        )

                    for artifact_path in artifact_paths:
                        resolved_path = artifact_path.resolve()
                        if not resolved_path.is_relative_to(storage_root):
                            raise ValueError(f"Refusing to delete file outside storage root: {resolved_path}")
                        resolved_path.unlink(missing_ok=True)

                    job_file.deleted_at = datetime.now(timezone.utc)
                    record_audit(
                        session,
                        action="files.retention_deleted",
                        entity_type="job_file",
                        entity_id=job_file_id,
                        details={"path": storage_path},
                    )
                    session.commit()
                except (OSError, ValueError):
                    session.rollback()
                    logger.exception(
                        "Could not delete expired file",
                        extra={"job_file_id": job_file_id, "path": storage_path},
                    )


runtime = WorkerRuntime()
worker_app = FastAPI(title="Doc Translator Worker")


@worker_app.on_event("startup")
def on_startup() -> None:
    runtime.start()


@worker_app.on_event("shutdown")
def on_shutdown() -> None:
    runtime.stop()


@worker_app.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@worker_app.get("/health/ready")
def ready() -> dict:
    check_database_health()
    redis_client = get_redis_client()
    redis_client.ping()
    if runtime.dispatch_thread is None or not runtime.dispatch_thread.is_alive():
        raise HTTPException(status_code=503, detail="Dispatch loop is not running")
    if runtime.cleanup_thread is None or not runtime.cleanup_thread.is_alive():
        raise HTTPException(status_code=503, detail="Cleanup loop is not running")
    with SessionLocal() as session:
        pending_cleanup = session.query(func.count(JobFile.id)).scalar() or 0
    return {
        "status": "ok",
        "active_jobs": len(runtime.futures),
        "tracked_files": pending_cleanup,
        "last_heartbeat": runtime.last_heartbeat.isoformat() if runtime.last_heartbeat else None,
    }
