from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi import HTTPException
import redis
from sqlalchemy import func

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
from doc_translator.translation import run_translation_job


logger = logging.getLogger(__name__)

RECOVERABLE_JOB_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.PARSING,
    JobStatus.OCR_RUNNING,
    JobStatus.TRANSLATING,
    JobStatus.REBUILDING,
    JobStatus.VALIDATING,
}


class WorkerRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.stop_event = threading.Event()
        self.dispatch_thread: threading.Thread | None = None
        self.cleanup_thread: threading.Thread | None = None
        self.executor = ThreadPoolExecutor(max_workers=16)
        self.futures: dict[str, Future] = {}
        self.lock = threading.Lock()
        self.last_heartbeat: datetime | None = None

    def start(self) -> None:
        configure_logging(self.settings.log_level)
        with SessionLocal() as session:
            bootstrap_defaults(session)
        self.recover_orphaned_jobs()
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

    def recover_orphaned_jobs(self) -> None:
        try:
            redis_client = get_redis_client()
            queued_job_ids = set(redis_client.lrange(TRANSLATION_QUEUE_KEY, 0, -1))
        except redis.RedisError:
            logger.exception("Worker could not inspect Redis queue during orphaned-job recovery")
            return

        jobs_to_enqueue: list[str] = []
        recovered_count = 0
        cancelled_count = 0

        with SessionLocal() as session:
            jobs = (
                session.query(TranslationJob)
                .filter(TranslationJob.status.in_(tuple(RECOVERABLE_JOB_STATUSES)))
                .order_by(TranslationJob.created_at.asc())
                .all()
            )
            for job in jobs:
                if job.cancel_requested:
                    previous_status = job.status
                    job.status = JobStatus.CANCELLED
                    job.completed_at = datetime.now(timezone.utc)
                    job.events.clear()
                    session.add(
                        JobEvent(
                            job_id=job.id,
                            level="info",
                            message="Recovered orphaned job and finalized cancellation",
                            details={"recovery": "worker_startup", "previous_status": previous_status.value},
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
                    continue

                if job.status != JobStatus.QUEUED:
                    previous_status = job.status
                    job.status = JobStatus.QUEUED
                    job.progress = 0
                    job.started_at = None
                    job.completed_at = None
                    job.error_message = None
                    job.events.clear()
                    session.add(
                        JobEvent(
                            job_id=job.id,
                            level="info",
                            message="Recovered orphaned in-progress job and re-queued it",
                            details={"recovery": "worker_startup", "previous_status": previous_status.value},
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

                if job.id not in queued_job_ids:
                    jobs_to_enqueue.append(job.id)
                    queued_job_ids.add(job.id)

            session.commit()

        if jobs_to_enqueue:
            try:
                redis_client.rpush(TRANSLATION_QUEUE_KEY, *jobs_to_enqueue)
            except redis.RedisError:
                logger.exception("Worker could not re-enqueue recovered jobs")
                return

        if recovered_count or cancelled_count:
            logger.warning(
                "Recovered orphaned translation jobs on worker startup",
                extra={
                    "recovered_count": recovered_count,
                    "cancelled_count": cancelled_count,
                    "enqueued_count": len(jobs_to_enqueue),
                },
            )

    def dispatch_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                redis_client = get_redis_client()
                while not self.stop_event.is_set():
                    self.update_heartbeat()
                    self._prune_finished()
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
                        self.futures[job_id] = self.executor.submit(run_translation_job, job_id)
            except redis.RedisError:
                logger.exception("Worker lost Redis connectivity; retrying shortly")
                self.stop_event.wait(2)

    def _prune_finished(self) -> None:
        with self.lock:
            completed = [job_id for job_id, future in self.futures.items() if future.done()]
            for job_id in completed:
                self.futures.pop(job_id)

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
            cutoff = datetime.now(timezone.utc) - timedelta(days=runtime.file_retention_days)
            expired_files = (
                session.query(JobFile)
                .filter(JobFile.deleted_at.is_(None))
                .filter(JobFile.created_at < cutoff)
                .all()
            )
            for job_file in expired_files:
                try:
                    from pathlib import Path

                    Path(job_file.storage_path).unlink(missing_ok=True)
                    if job_file.kind.value == "output":
                        preview_sidecar_path(job_file.storage_path).unlink(missing_ok=True)
                        ppt_preview_pdf_path(job_file.storage_path, "source").unlink(missing_ok=True)
                        ppt_preview_pdf_path(job_file.storage_path, "translated").unlink(missing_ok=True)
                        babeldoc_ir_sidecar_path(Path(job_file.storage_path)).unlink(missing_ok=True)
                        babeldoc_structure_snapshot_path(Path(job_file.storage_path), "before_translation").unlink(missing_ok=True)
                        babeldoc_structure_snapshot_path(Path(job_file.storage_path), "after_translation").unlink(missing_ok=True)
                finally:
                    job_file.deleted_at = datetime.now(timezone.utc)
                    record_audit(
                        session,
                        action="files.retention_deleted",
                        entity_type="job_file",
                        entity_id=job_file.id,
                        details={"path": job_file.storage_path},
                    )
            session.commit()


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
