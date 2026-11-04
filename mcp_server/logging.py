import logging
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from mcp_server.domain.errors import DomainError

_TOOL_LOGGER_NAME = "mcp_server.tools"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


def configure_logging(level: str) -> None:
    normalized_level = level.upper()
    logging.basicConfig(
        level=normalized_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("mcp_server").setLevel(normalized_level)


def get_tool_logger() -> logging.Logger:
    return logging.getLogger(_TOOL_LOGGER_NAME)


@contextmanager
def log_tool_call(tool_name: str, arguments: Mapping[str, Any]) -> Iterator[None]:
    logger = get_tool_logger()
    safe_arguments = redact_arguments(arguments)
    started_at = time.perf_counter()

    try:
        yield
    except Exception as exc:
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.error(
            "tool_call tool=%s arguments=%s duration_ms=%.2f error_type=%s error=%s",
            tool_name,
            safe_arguments,
            duration_ms,
            type(exc).__name__,
            _short_error_message(exc),
            exc_info=not isinstance(exc, DomainError),
        )
        raise
    else:
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "tool_call tool=%s arguments=%s duration_ms=%.2f status=ok",
            tool_name,
            safe_arguments,
            duration_ms,
        )


def redact_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(key, value) for key, value in arguments.items()}


def _redact_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "***"
    if isinstance(value, Mapping):
        return redact_arguments(value)
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _short_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if len(message) > 300:
        return f"{message[:297]}..."
    return message


__all__ = [
    "configure_logging",
    "get_tool_logger",
    "log_tool_call",
    "redact_arguments",
]
