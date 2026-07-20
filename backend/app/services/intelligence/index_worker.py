"""Background worker for repository index runs."""
from __future__ import annotations

import asyncio
import traceback
from typing import Optional

from app.core.database import SessionLocal
from app.core.logger import logger
from app.services.intelligence.indexer_service import IndexerService

_worker_running = False
_worker_task: Optional[asyncio.Task] = None


async def _index_worker_loop() -> None:
    global _worker_running
    logger.info("Intelligence index worker started")
    _worker_running = True
    poll_interval = 3

    while _worker_running:
        db = SessionLocal()
        try:
            indexer = IndexerService(db)
            pending = indexer.get_pending_runs(limit=1)
            if pending:
                for run in pending:
                    if not _worker_running:
                        break
                    await indexer.execute_index_run(run)
            else:
                await asyncio.sleep(poll_interval)
        except Exception as e:
            logger.error(f"Index worker error: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(poll_interval)
        finally:
            db.close()

    logger.info("Intelligence index worker stopped")


async def start_index_worker() -> None:
    global _worker_running, _worker_task
    if _worker_task is not None:
        return
    _worker_running = True
    _worker_task = asyncio.create_task(_index_worker_loop())
    logger.info("Intelligence index worker initialized")


async def stop_index_worker() -> None:
    global _worker_running, _worker_task
    _worker_running = False
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=30.0)
        except asyncio.TimeoutError:
            _worker_task.cancel()
    _worker_task = None
    _worker_running = False


def is_index_worker_running() -> bool:
    """Return True when the intelligence index worker loop is active."""
    return _worker_running and _worker_task is not None and not _worker_task.done()
