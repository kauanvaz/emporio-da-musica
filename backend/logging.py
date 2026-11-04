import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.schemas import AgentAnswer

_TURN_LOGGER_NAME = "backend.turn"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    name: str
    result: Any = None


@dataclass(frozen=True)
class TurnRecord:
    session_id: str
    user_message: str
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    tool_results: Sequence[ToolResult] = field(default_factory=tuple)
    answer: AgentAnswer | None = None
    error: BaseException | None = None


def configure_logging(level: str) -> None:
    normalized_level = level.upper()
    logging.basicConfig(
        level=normalized_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("backend").setLevel(normalized_level)


def get_turn_logger() -> logging.Logger:
    return logging.getLogger(_TURN_LOGGER_NAME)


def log_turn(record: TurnRecord) -> None:
    logger = get_turn_logger()
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    tool_calls = [
        {
            "name": call.name,
            "arguments": redact_arguments(call.arguments),
        }
        for call in record.tool_calls
    ]
    tool_results = [
        {
            "name": result.name,
            "result": _redact_value("result", result.result),
        }
        for result in record.tool_results
    ]
    answer = (
        record.answer.model_dump(mode="json") if record.answer is not None else None
    )
    error = record.error

    if error is None:
        logger.info(
            "turn timestamp=%s session_id=%s input=%r tool_calls=%s "
            "tool_results=%s response=%s",
            timestamp,
            record.session_id,
            record.user_message,
            tool_calls,
            tool_results,
            answer,
        )
        return

    logger.error(
        "turn timestamp=%s session_id=%s input=%r tool_calls=%s "
        "tool_results=%s response=%s error_type=%s error=%s",
        timestamp,
        record.session_id,
        record.user_message,
        tool_calls,
        tool_results,
        answer,
        type(error).__name__,
        _short_error_message(error),
        exc_info=error,
    )


def redact_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(key, value) for key, value in arguments.items()}


def _redact_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "***"
    if isinstance(value, Mapping):
        return redact_arguments(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(key, item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _short_error_message(exc: BaseException) -> str:
    message = " ".join(str(exc).split())
    if len(message) > 300:
        return f"{message[:297]}..."
    return message


__all__ = [
    "ToolCall",
    "ToolResult",
    "TurnRecord",
    "configure_logging",
    "get_turn_logger",
    "log_turn",
    "redact_arguments",
]
