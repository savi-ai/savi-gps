"""Append-only LLM call audit log for spend / hang diagnosis.

Writes JSONL under backend/logs/llm_audit.jsonl (or LLM_AUDIT_PATH).
Never stores prompts or API keys — only metadata.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.logger import logger

_lock = threading.Lock()

_DEFAULT_REL = Path(__file__).resolve().parents[2] / "logs" / "llm_audit.jsonl"


def _audit_path() -> Path:
    override = os.environ.get("LLM_AUDIT_PATH")
    if override:
        return Path(override)
    return _DEFAULT_REL


def log_llm_call(
    *,
    purpose: str,
    provider: str,
    model: Optional[str] = None,
    tenant_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    status: str = "ok",
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort append; never raises into callers."""
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "tenant_id": tenant_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "status": status,
            "duration_ms": duration_ms,
        }
        if error:
            row["error"] = error[:500]
        if extra:
            row["extra"] = extra
        line = json.dumps(row, default=str) + "\n"
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        logger.debug("llm_audit write failed: %s", e)
