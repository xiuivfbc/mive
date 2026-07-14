import logging


class AccessLogFilter(logging.Filter):
    """Filter out noisy access log entries for polling endpoints."""

    SUPPRESS_PATHS = {
        "/creation-status",
        "/generate-characters/status",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for path in self.SUPPRESS_PATHS:
            if path in msg:
                return False
        return True


class ExcludeErrorFilter(logging.Filter):
    """Exclude ERROR and above — keeps backend.log clean of tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR
