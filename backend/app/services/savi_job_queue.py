"""Savi Teammate job queue (Phase B2) — Arq when enabled, else inline Alpha.

ADR 0003 / 0008: durable workers for orchestrator; uvicorn must not run long CLIs.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logger import logger

_arq_pool = None


def arq_enabled() -> bool:
    return bool(settings.SAVI_USE_ARQ and (settings.REDIS_URL or "").strip())


async def _get_arq_pool():
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
    except ImportError as e:
        raise RuntimeError(
            "arq is not installed — pip install arq redis, or set SAVI_USE_ARQ=false"
        ) from e

    _arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    return _arq_pool


async def enqueue_savi_orchestrate(
    tenant_id: str,
    team_id: str,
    savi_id: str,
    item_id: str,
    *,
    mode: str = "run_to_pr",
) -> Dict[str, Any]:
    """Enqueue orchestrator job. Returns {queued, job_id?, backend}."""
    if arq_enabled():
        pool = await _get_arq_pool()
        job = await pool.enqueue_job(
            "savi_orchestrate",
            tenant_id,
            team_id,
            savi_id,
            item_id,
            mode,
            _job_id=f"savi-orch:{item_id}:{mode}",
        )
        job_id = getattr(job, "job_id", None) or f"savi-orch:{item_id}:{mode}"
        logger.info(
            "Enqueued savi_orchestrate job_id=%s item=%s mode=%s",
            job_id,
            item_id,
            mode,
        )
        return {"queued": True, "backend": "arq", "job_id": job_id, "mode": mode}

    if settings.SAVI_ORCHESTRATOR_INLINE:
        from app.services.savi_orchestrator_service import schedule_orchestrator_run_inline

        schedule_orchestrator_run_inline(tenant_id, team_id, savi_id, item_id, mode=mode)
        return {
            "queued": True,
            "backend": "inline",
            "job_id": None,
            "mode": mode,
        }

    raise RuntimeError(
        "No job backend: set SAVI_USE_ARQ=true with REDIS_URL, "
        "or SAVI_ORCHESTRATOR_INLINE=true"
    )


def schedule_orchestrator_run(
    tenant_id: str, team_id: str, savi_id: str, item_id: str, *, mode: str = "run_to_pr"
) -> Dict[str, Any]:
    """Sync entry: schedule Arq or inline. Safe to call from FastAPI handlers."""

    async def _go():
        return await enqueue_savi_orchestrate(
            tenant_id, team_id, savi_id, item_id, mode=mode
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Fire-and-forget scheduling of the enqueue coroutine
            fut = asyncio.ensure_future(_go())

            def _done(t):
                try:
                    t.result()
                except Exception as e:
                    logger.exception("Failed to enqueue Savi orchestrator: %s", e)

            fut.add_done_callback(_done)
            return {
                "queued": True,
                "backend": "arq" if arq_enabled() else "inline",
                "job_id": None,
                "mode": mode,
                "pending_enqueue": True,
            }
        return loop.run_until_complete(_go())
    except RuntimeError:
        return asyncio.run(_go())
