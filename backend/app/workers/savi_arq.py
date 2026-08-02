"""Arq worker settings for Savi Teammate (Phase B2).

Run:
  cd backend && arq app.workers.savi_arq.WorkerSettings

Requires REDIS_URL and SAVI_USE_ARQ=true on the API; worker needs DB access.
"""
from __future__ import annotations

from arq.connections import RedisSettings

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import logger


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
        # default: run_to_pr
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
            item = (
                SaviOrchestratorService(db).get_item(
                    tenant_id, team_id, savi_id, item_id
                )
            )
            if item:
                item.orchestrator_error = str(e)[:2000]
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


class WorkerSettings:
    functions = [savi_orchestrate]
    redis_settings = RedisSettings.from_dsn(
        settings.REDIS_URL or "redis://localhost:6379"
    )
    # CLI coding agents can run for a long time
    job_timeout = 60 * 30  # 30 minutes
    max_jobs = 5
