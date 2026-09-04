"""Structured logging for the PE AI pipeline."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class PipelineFilter(logging.Filter):
    """Inject pipeline context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "query"):
            record.query = ""
        if not hasattr(record, "agent_type"):
            record.agent_type = ""
        if not hasattr(record, "node"):
            record.node = ""
        if not hasattr(record, "latency_ms"):
            record.latency_ms = 0
        return True


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured output."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("query", "agent_type", "node", "latency_ms"):
            val = getattr(record, field, None)
            if val:
                log_entry[field] = val
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def get_logger(
    name: str,
    level: int = logging.INFO,
    json_output: bool = False,
) -> logging.Logger:
    full_name = f"pe_ai.{name}" if not name.startswith("pe_ai.") else name
    logger = logging.getLogger(full_name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        if json_output:
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            ))
        logger.addHandler(handler)
        logger.addFilter(PipelineFilter())

    logger.setLevel(level)
    return logger
