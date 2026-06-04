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
from doc_translator.models import JobFile
from doc_translator.queueing import TRANSLATION_QUEUE_KEY, get_redis_client
from doc_translator.settings_service import get_runtime_settings
from doc_translator.translation import run_translation_job


logger = logging.getLogger(__name__)


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
