"""Logging configuration"""
import logging
import sys
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


def setup_logger(name: str = "gps"):
    """Setup logger with correlation ID support"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        
        if settings.LOG_FORMAT == "json":
            formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


logger = setup_logger()

