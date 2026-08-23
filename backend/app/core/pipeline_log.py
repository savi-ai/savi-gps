"""Structured pipeline audit log for index + wiki generation.

Append-only JSONL under backend/logs/pipeline.jsonl (or PIPELINE_LOG_PATH).
Use for diagnosing long-running wiki/index jobs without storing secrets.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.logger import logger

_lock = threading.Lock()

_DEFAULT_REL = Path(__file__).resolve().parents[2] / "logs" / "pipeline.jsonl"


def logs_dir() -> Path:
    override = os.environ.get("LOG_DIR")
    if override:
        return Path(override)
    return _DEFAULT_REL.parent


def pipeline_log_path() -> Path:
    override = os.environ.get("PIPELINE_LOG_PATH")
    if override:
        return Path(override)
    return _DEFAULT_REL


def pipeline_enabled() -> bool:
    flag = (os.environ.get("PIPELINE_LOG") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def log_pipeline(
    *,
    stage: str,
    message: str = "",
    status: str = "info",
    repository_id: Optional[str] = None,
    repository_name: Optional[str] = None,
    index_run_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort append; never raises into callers."""
    if not pipeline_enabled():
        return
    try:
        path = pipeline_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "message": message,
        }
        if repository_id:
            row["repository_id"] = repository_id
        if repository_name:
            row["repository_name"] = repository_name
        if index_run_id:
            row["index_run_id"] = index_run_id
        if tenant_id:
            row["tenant_id"] = tenant_id
        if duration_ms is not None:
            row["duration_ms"] = duration_ms
        if extra:
            row["extra"] = extra
        line = json.dumps(row, default=str) + "\n"
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
        # Mirror key stages to main logger for live terminal tail
        if status in ("start", "ok", "error", "warn", "heartbeat"):
            logger.info(
                "[pipeline] %s %s repo=%s run=%s %s",
                stage,
                status,
                repository_id or "-",
                (index_run_id or "-")[:8] if index_run_id else "-",
                message,
            )
    except Exception as e:
        logger.debug("pipeline_log write failed: %s", e)


class PipelineTimer:
    """Context manager: log start/end with duration."""

    def __init__(
        self,
        stage: str,
        *,
        repository_id: Optional[str] = None,
        repository_name: Optional[str] = None,
        index_run_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.stage = stage
        self.repository_id = repository_id
        self.repository_name = repository_name
        self.index_run_id = index_run_id
        self.tenant_id = tenant_id
        self.extra = extra or {}
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.monotonic()
        log_pipeline(
            stage=self.stage,
            status="start",
            message=f"{self.stage} started",
            repository_id=self.repository_id,
            repository_name=self.repository_name,
            index_run_id=self.index_run_id,
            tenant_id=self.tenant_id,
            extra=self.extra,
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = int((time.monotonic() - self._t0) * 1000)
        if exc_type is None:
            log_pipeline(
                stage=self.stage,
                status="ok",
                message=f"{self.stage} completed",
                repository_id=self.repository_id,
                repository_name=self.repository_name,
                index_run_id=self.index_run_id,
                tenant_id=self.tenant_id,
                duration_ms=ms,
                extra=self.extra,
            )
        else:
            log_pipeline(
                stage=self.stage,
                status="error",
                message=str(exc)[:500],
                repository_id=self.repository_id,
                repository_name=self.repository_name,
                index_run_id=self.index_run_id,
                tenant_id=self.tenant_id,
                duration_ms=ms,
                extra=self.extra,
            )
        return False
