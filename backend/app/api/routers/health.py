"""Health check endpoints"""
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import task_worker
from app.services.intelligence import index_worker
from app.services.savi_job_queue import arq_enabled

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Legacy health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/health/live")
async def health_live():
    """Process liveness probe — returns 200 if the API process is up."""
    return {"status": "alive"}


@router.get("/health/ready")
async def health_ready(response: Response):
    """Readiness probe — DB connectivity and background workers."""
    checks: dict[str, str] = {}
    ready = True

    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        finally:
            db.close()
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        ready = False

    if arq_enabled():
        checks["job_backend"] = "arq"
        checks["task_worker"] = "delegated_to_arq"
        checks["index_worker"] = "delegated_to_arq"
        # Redis reachability is best-effort; API can still accept enqueue
        try:
            import redis

            r = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")
            r.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
            ready = False
    else:
        checks["job_backend"] = "in_process"
        task_ok = task_worker.is_worker_running()
        checks["task_worker"] = "ok" if task_ok else "not_running"
        if not task_ok:
            ready = False

        index_ok = index_worker.is_index_worker_running()
        checks["index_worker"] = "ok" if index_ok else "not_running"
        if not index_ok:
            ready = False

    payload = {"status": "ready" if ready else "not_ready", "checks": checks}
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
