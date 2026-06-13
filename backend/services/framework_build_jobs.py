"""In-memory async jobs for framework preview generation with live progress."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable

from flask import Flask

logger = logging.getLogger(__name__)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_MAX_LOG_LINES = 80


class FrameworkBuildReporter:
    """Collects incremental build logs for frontend polling."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def _mutate(self, fn) -> None:
        with _lock:
            job = _jobs.get(self.job_id)
            if job:
                fn(job)

    def set_percent(self, percent: int, phase: str) -> None:
        pct = max(0, min(100, int(percent)))

        def update(job):
            job["percent"] = pct
            job["phase"] = phase

        self._mutate(update)

    def log(self, message: str, *, status: str = "done", key: str | None = None) -> None:
        if not message:
            return

        def update(job):
            logs = job["logs"]
            if key:
                for entry in logs:
                    if entry.get("key") == key:
                        entry["message"] = message
                        entry["status"] = status
                        return
                logs.append({"message": message, "status": status, "key": key})
            else:
                logs.append({"message": message, "status": status})
            if len(logs) > _MAX_LOG_LINES:
                del logs[: len(logs) - _MAX_LOG_LINES]

        self._mutate(update)

    def complete_log(self, key: str) -> None:
        def update(job):
            for entry in job["logs"]:
                if entry.get("key") == key:
                    entry["status"] = "done"

        self._mutate(update)


def _run_job(
    job_id: str,
    user_id: int,
    app: Flask,
    build_fn: Callable[[FrameworkBuildReporter], dict],
) -> None:
    with app.app_context():
        from backend.services.llm_usage_context import LlmUsageContext, llm_usage_scope

        usage_ctx = LlmUsageContext(user_id=user_id, source="framework")
        reporter = FrameworkBuildReporter(job_id)
        try:
            with llm_usage_scope(usage_ctx):
                reporter.set_percent(2, "Starting framework design")
                reporter.log("Preparing job description and agent context", status="active", key="start")
                result = build_fn(reporter)
            reporter.complete_log("start")
            reporter.set_percent(100, "Framework ready")
            reporter.log("Multi-agent framework is ready for review", status="done")

            def finish(job):
                job["status"] = "complete"
                job["result"] = result
                job["finished_at"] = datetime.now(timezone.utc).isoformat()

            with _lock:
                if job_id in _jobs:
                    finish(_jobs[job_id])
        except Exception as exc:
            logger.exception("Framework build job %s failed", job_id)

            def fail(job):
                job["status"] = "failed"
                job["error"] = str(exc) or "Framework build failed"
                job["finished_at"] = datetime.now(timezone.utc).isoformat()

            with _lock:
                if job_id in _jobs:
                    fail(_jobs[job_id])


def start_job(user_id: int, build_fn: Callable[[FrameworkBuildReporter], dict], app: Flask) -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "user_id": user_id,
            "status": "running",
            "percent": 0,
            "phase": "Starting",
            "logs": [],
            "result": None,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, user_id, app, build_fn),
        daemon=True,
        name=f"framework-job-{job_id[:8]}",
    )
    thread.start()
    return job_id


def get_job(job_id: str, user_id: int) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["user_id"] != user_id:
            return None
        return {
            "id": job["id"],
            "status": job["status"],
            "percent": job["percent"],
            "phase": job["phase"],
            "logs": [
                {"message": e["message"], "status": e.get("status", "done")}
                for e in job["logs"]
            ],
            "result": job["result"] if job["status"] == "complete" else None,
            "error": job["error"] if job["status"] == "failed" else None,
        }
