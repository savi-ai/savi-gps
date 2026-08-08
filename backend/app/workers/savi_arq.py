"""Arq worker for Savi GPS long-running jobs (ADR 0003 / Phase B2).

Run:
  cd backend && arq app.workers.savi_arq.WorkerSettings

Requires REDIS_URL. Set SAVI_USE_ARQ=true on the API so it enqueues instead of
running index/Build/Teammate work inside uvicorn.
"""
from __future__ import annotations

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import logger

try:
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover — worker process always has arq installed
    RedisSettings = None  # type: ignore


async def savi_orchestrate(
    ctx,
    tenant_id: str,
    team_id: str,
    savi_id: str,
    item_id: str,
    mode: str = "run_to_pr",
) -> dict:
    """Durable orchestrator job — runs outside uvicorn (ADR 0008)."""
    from app.services.savi_orchestrator_service import SaviOrchestratorService

    db = SessionLocal()
    try:
        orch = SaviOrchestratorService(db)
        if mode == "poll_feedback":
            result = await orch.poll_feedback(
                tenant_id, team_id, savi_id, item_id, iterate=True
            )
            return {"ok": True, "mode": mode, "result": result}
        if mode == "advance":
            item = await orch.advance_one(tenant_id, team_id, savi_id, item_id)
            return {
                "ok": True,
                "mode": mode,
                "phase": item.orchestrator_phase,
                "item_id": item.id,
            }
        item = await orch.run_to_pr(tenant_id, team_id, savi_id, item_id)
        return {
            "ok": True,
            "mode": "run_to_pr",
            "phase": item.orchestrator_phase,
            "item_id": item.id,
            "pr_url": item.pr_url,
            "error": item.orchestrator_error,
        }
    except Exception as e:
        logger.exception("savi_orchestrate failed item=%s: %s", item_id, e)
        try:
            item = SaviOrchestratorService(db).get_item(
                tenant_id, team_id, savi_id, item_id
            )
            if item:
                item.orchestrator_error = str(e)[:2000]
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


async def execute_index_run(ctx, run_id: str) -> dict:
    """Intelligence index + wiki generation (may invoke vendor CLI for a long time)."""
    from app.core.database import IndexRun
    from app.services.intelligence.indexer_service import IndexerService

    db = SessionLocal()
    try:
        run = db.query(IndexRun).filter(IndexRun.id == run_id).first()
        if not run:
            logger.error("execute_index_run: IndexRun %s not found", run_id)
            return {"ok": False, "error": "not_found", "run_id": run_id}
        if run.status not in ("pending", "running"):
            logger.info(
                "execute_index_run: skip run %s status=%s", run_id, run.status
            )
            return {"ok": True, "skipped": True, "status": run.status, "run_id": run_id}

        logger.info("execute_index_run starting run_id=%s", run_id)
        await IndexerService(db).execute_index_run(run)
        db.refresh(run)
        return {
            "ok": run.status == "completed",
            "run_id": run_id,
            "status": run.status,
            "error": run.error,
        }
    except Exception as e:
        logger.exception("execute_index_run failed run_id=%s: %s", run_id, e)
        raise
    finally:
        db.close()


async def execute_build_task(ctx, task_id: str) -> dict:
    """Build generate_features / stories / architecture / code / tests."""
    from app.core.database import Task
    from app.services.task_worker import TaskWorker

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error("execute_build_task: Task %s not found", task_id)
            return {"ok": False, "error": "not_found", "task_id": task_id}
        if task.status not in ("pending", "running"):
            logger.info(
                "execute_build_task: skip task %s status=%s", task_id, task.status
            )
            return {
                "ok": True,
                "skipped": True,
                "status": task.status,
                "task_id": task_id,
            }

        # Allow long code-gen when running under Arq (in-process default is 10m)
        worker = TaskWorker()
        worker.task_timeout = max(worker.task_timeout, 60 * 30)
        logger.info(
            "execute_build_task starting task_id=%s type=%s", task_id, task.task_type
        )
        await worker.process_task(task, db)
        db.refresh(task)
        return {
            "ok": task.status == "completed",
            "task_id": task_id,
            "status": task.status,
            "task_type": task.task_type,
        }
    except Exception as e:
        logger.exception("execute_build_task failed task_id=%s: %s", task_id, e)
        raise
    finally:
        db.close()


async def on_startup(ctx) -> None:
    """Re-queue orphaned pending DB rows after worker restart."""
    from app.core.database import IndexRun, Task
    from app.services.savi_job_queue import enqueue_build_task, enqueue_index_run

    db = SessionLocal()
    try:
        pending_runs = (
            db.query(IndexRun)
            .filter(IndexRun.status == "pending")
            .order_by(IndexRun.created_at.asc())
            .limit(50)
            .all()
        )
        for run in pending_runs:
            try:
                await enqueue_index_run(run.id)
            except Exception as e:
                logger.warning("startup enqueue index %s failed: %s", run.id, e)

        pending_tasks = (
            db.query(Task)
            .filter(Task.status == "pending")
            .order_by(Task.created_at.asc())
            .limit(50)
            .all()
        )
        for task in pending_tasks:
            try:
                await enqueue_build_task(task.id)
            except Exception as e:
                logger.warning("startup enqueue task %s failed: %s", task.id, e)

        logger.info(
            "Arq worker startup: requeued %s index runs, %s build tasks",
            len(pending_runs),
            len(pending_tasks),
        )
    finally:
        db.close()


class WorkerSettings:
    functions = [savi_orchestrate, execute_index_run, execute_build_task]
    on_startup = on_startup
    redis_settings = (
        RedisSettings.from_dsn(settings.REDIS_URL or "redis://localhost:6379")
        if RedisSettings is not None
        else None
    )
    # Wiki CLI / coding agents can run a long time
    job_timeout = 60 * 60  # 60 minutes
    max_jobs = 5
