import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional


UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


class SingleLineJsonFormatter(logging.Formatter):
    """Render every log record as one JSON object on one physical line."""

    def format(self, record: logging.LogRecord) -> str:
        if isinstance(record.msg, Mapping):
            payload = dict(record.msg)
        else:
            message = record.getMessage()
            try:
                structured_message = json.loads(message)
            except (TypeError, ValueError):
                structured_message = None
            payload = (
                dict(structured_message)
                if isinstance(structured_message, Mapping)
                else {"message": message}
            )

        payload.update(
            {
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "level": record.levelname,
                "logger": record.name,
            }
        )

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # Preserve the dynamic provider/model context injected by validators.
        if hasattr(record, "provider_model"):
            payload["provider_model"] = record.provider_model

        # json.dumps escapes embedded CR/LF characters. Consequently prompts,
        # provider errors and tracebacks remain a single CRI/Loki event.
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def configure_single_line_json_logging(level: int) -> None:
    """Configure application and Uvicorn handlers with one-line JSON logs."""

    logging.basicConfig(level=level)
    logging.captureWarnings(True)
    formatter = SingleLineJsonFormatter()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    # Uvicorn configures these handlers before importing the ASGI app when it
    # is launched from the CLI, so include them in the same logging contract.
    for logger_name in UVICORN_LOGGER_NAMES:
        for handler in logging.getLogger(logger_name).handlers:
            handler.setFormatter(formatter)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info: Optional[Any] = None,
    **fields: Any,
) -> None:
    """Emit a structured event consumed by ``SingleLineJsonFormatter``."""

    logger.log(level, {"event": event, **fields}, exc_info=exc_info)


def exception_message(error: BaseException) -> str:
    """Return a useful message even for exceptions such as TimeoutError."""

    return str(error).strip() or type(error).__name__
