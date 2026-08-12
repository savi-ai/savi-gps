"""Background job queue (ADR 0003) — Arq when enabled, else in-process workers.

Covers:
  - Savi Teammate orchestrator
  - Intelligence index / wiki CLI
  - Build code-generation tasks

When SAVI_USE_ARQ=true + REDIS_URL, API enqueues; run:
  arq app.workers.savi_arq.WorkerSettings
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

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


def _schedule_coro(coro_factory, *, label: str) -> Dict[str, Any]:
    """Fire-and-forget or run until complete from sync/async callers."""

    async def _go():
        return await coro_factory()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            fut = asyncio.ensure_future(_go())

            def _done(t):
                try:
                    t.result()
                except Exception as e:
                    logger.exception("Failed to enqueue %s: %s", label, e)

            fut.add_done_callback(_done)
            return {
                "queued": True,
                "backend": "arq" if arq_enabled() else "inline",
                "job_id": None,
                "pending_enqueue": True,
            }
        return loop.run_until_complete(_go())
    except RuntimeError:
        return asyncio.run(_go())


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

    out = _schedule_coro(_go, label="savi_orchestrate")
    if "mode" not in out:
        out["mode"] = mode
    return out


async def enqueue_index_run(run_id: str) -> Dict[str, Any]:
    """Enqueue Intelligence index/wiki job (Arq only)."""
    if not arq_enabled():
        return {"queued": False, "backend": "in_process_worker", "job_id": None}

    pool = await _get_arq_pool()
    job = await pool.enqueue_job(
        "execute_index_run",
        run_id,
        _job_id=f"index-run:{run_id}",
    )
    job_id = getattr(job, "job_id", None) or f"index-run:{run_id}"
    logger.info("Enqueued execute_index_run job_id=%s run_id=%s", job_id, run_id)
    return {"queued": True, "backend": "arq", "job_id": job_id}


def schedule_index_run(run_id: str) -> Dict[str, Any]:
    return _schedule_coro(lambda: enqueue_index_run(run_id), label="execute_index_run")


async def enqueue_build_task(task_id: str) -> Dict[str, Any]:
    """Enqueue Build generate_* task (Arq only)."""
    if not arq_enabled():
        return {"queued": False, "backend": "in_process_worker", "job_id": None}

    pool = await _get_arq_pool()
    job = await pool.enqueue_job(
        "execute_build_task",
        task_id,
        _job_id=f"build-task:{task_id}",
    )
    job_id = getattr(job, "job_id", None) or f"build-task:{task_id}"
    logger.info("Enqueued execute_build_task job_id=%s task_id=%s", job_id, task_id)
    return {"queued": True, "backend": "arq", "job_id": job_id}


def schedule_build_task(task_id: str) -> Dict[str, Any]:
    return _schedule_coro(lambda: enqueue_build_task(task_id), label="execute_build_task")


async def enqueue_application_wiki(tenant_id: str, application_id: str) -> Dict[str, Any]:
    """Enqueue or run application wiki generation."""
    if arq_enabled():
        pool = await _get_arq_pool()
        job = await pool.enqueue_job(
            "execute_application_wiki",
            tenant_id,
            application_id,
            _job_id=f"app-wiki:{application_id}",
        )
        job_id = getattr(job, "job_id", None) or f"app-wiki:{application_id}"
        logger.info(
            "Enqueued execute_application_wiki job_id=%s app=%s",
            job_id,
            application_id,
        )
        return {"queued": True, "backend": "arq", "job_id": job_id}

    from app.core.database import SessionLocal
    from app.services.intelligence.application_wiki_agent_service import (
        ApplicationWikiAgentService,
    )

    db = SessionLocal()
    try:
        result = await ApplicationWikiAgentService(db).generate_for_application(
            tenant_id, application_id
        )
        return {"queued": False, "backend": "inline", "result": result}
    finally:
        db.close()


def schedule_application_wiki(tenant_id: str, application_id: str) -> Dict[str, Any]:
    return _schedule_coro(
        lambda: enqueue_application_wiki(tenant_id, application_id),
        label="execute_application_wiki",
    )
