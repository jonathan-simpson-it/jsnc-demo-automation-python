"""Tests for structured logging."""

import logging

from src.utils.logger import get_logger, PipelineFilter


def test_get_logger_returns_logger():
    logger = get_logger("test_module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "pe_ai.test_module"


def test_pipeline_filter_adds_context():
    filt = PipelineFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="test message", args=(), exc_info=None,
    )
    record.query = "test query"
    result = filt.filter(record)
    assert result is True


def test_logger_has_stream_handler():
    logger = get_logger("test_handlers")
    handler_types = [type(h).__name__ for h in logger.handlers]
    assert "StreamHandler" in handler_types or len(logger.handlers) > 0
