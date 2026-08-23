"""Logging configuration"""
import logging
import sys
from pathlib import Path

from app.core.config import settings
import json


class JSONFormatter(logging.Formatter):
    """JSON log formatter"""

    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def _file_log_enabled() -> bool:
    flag = (getattr(settings, "LOG_TO_FILE", True))
    if isinstance(flag, str):
        return flag.strip().lower() not in ("0", "false", "no", "off")
    return bool(flag)


def _log_file_path() -> Path:
    log_dir = getattr(settings, "LOG_DIR", None)
    if log_dir:
        base = Path(log_dir)
    else:
        base = Path(__file__).resolve().parents[2] / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "gps.log"


def setup_logger(name: str = "gps"):
    """Setup logger with correlation ID support"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))

    if not logger.handlers:
        if settings.LOG_FORMAT == "json":
            formatter: logging.Formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        if _file_log_enabled():
            try:
                file_handler = logging.FileHandler(_log_file_path(), encoding="utf-8")
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            except OSError as e:
                # Do not fail startup if log dir is not writable
                sys.stderr.write(f"Could not open log file: {e}\n")

    return logger


logger = setup_logger()
