from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    NO_RESULTS = "NO_RESULTS"


VALIDATION_ERROR = ErrorCode.VALIDATION_ERROR
ORDER_NOT_FOUND = ErrorCode.ORDER_NOT_FOUND
NO_RESULTS = ErrorCode.NO_RESULTS


class DomainError(Exception):
    def __init__(self, code: ErrorCode | str, message: str) -> None:
        self.code = ErrorCode(code)
        self.message = message
        super().__init__(message)
