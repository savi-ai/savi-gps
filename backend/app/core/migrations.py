"""Run Alembic migrations programmatically."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.logger import logger


def run_migrations() -> None:
    """Apply Alembic migrations up to head."""
    backend_root = Path(__file__).resolve().parent.parent.parent
    alembic_ini = backend_root / "alembic.ini"
    if not alembic_ini.exists():
        logger.warning("alembic.ini not found — skipping Alembic migrations")
        return

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations applied")
