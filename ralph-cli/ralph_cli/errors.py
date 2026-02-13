"""Error types and classification."""

import re
from enum import Enum
from pathlib import Path


class ErrorType(Enum):
    """Task execution error types."""

    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    API_TIMEOUT = "API_TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    OVERLOADED = "OVERLOADED"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
    FORBIDDEN = "FORBIDDEN"
    UNKNOWN = "UNKNOWN"

    @property
    def is_recoverable(self) -> bool:
        """Check if error is recoverable with retry."""
        return self in {
            ErrorType.AUTH_EXPIRED,
            ErrorType.API_TIMEOUT,
            ErrorType.RATE_LIMIT,
            ErrorType.OVERLOADED,
        }

    @property
    def is_fatal(self) -> bool:
        """Check if error should stop the pipeline."""
        return self == ErrorType.FORBIDDEN

    @property
    def is_success(self) -> bool:
        """Check if this represents successful completion."""
        return self == ErrorType.COMPLETED

    @property
    def needs_fresh_session(self) -> bool:
        """Check if error requires fresh session (not resume)."""
        return self == ErrorType.CONTEXT_OVERFLOW


# Patterns for text-based classification (order matters - first match wins)
_PATTERNS: list[tuple[ErrorType, list[str]]] = [
    (ErrorType.COMPLETED, [r"I confirm that all task phases are fully completed"]),
    (ErrorType.CONTEXT_OVERFLOW, [r"Prompt is too long", r"context.*overflow"]),
    (ErrorType.AUTH_EXPIRED, [r"401", r"[Uu]nauthorized", r"authentication.*failed"]),
    (ErrorType.RATE_LIMIT, [r"429", r"rate.?limit", r"too.many.requests"]),
    (ErrorType.OVERLOADED, [r"529", r"[Oo]verloaded"]),
    (ErrorType.FORBIDDEN, [r"403", r"[Ff]orbidden"]),
    (ErrorType.API_TIMEOUT, [r"Tokens: 0 in / 0 out"]),
    (ErrorType.ON_HOLD, [r"status.*hold", r"## Blocks", r"→ hold"]),
]


def classify_from_text(text: str) -> ErrorType:
    """Classify error type from raw text."""
    for error_type, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return error_type
    return ErrorType.UNKNOWN


def classify_from_log(log_path: Path) -> ErrorType:
    """Classify error type from log file."""
    if not log_path.exists():
        return ErrorType.UNKNOWN
    try:
        return classify_from_text(log_path.read_text())
    except Exception:
        return ErrorType.UNKNOWN


def classify_from_json(data: dict) -> tuple[ErrorType, str]:
    """Classify error type from JSON result data.

    Returns tuple of (ErrorType, detail message).
    """
    error_msg = str(data.get("result", ""))
    error_code = str(data.get("error_code", ""))
    errors = data.get("errors", [])
    all_text = f"{error_msg} {error_code} {' '.join(str(e) for e in errors)}".lower()

    if "prompt is too long" in all_text:
        return ErrorType.CONTEXT_OVERFLOW, "Prompt is too long - context overflow"
    if "401" in all_text or "unauthorized" in all_text:
        return ErrorType.AUTH_EXPIRED, "Authentication failed (401)"
    if "429" in all_text or "rate" in all_text and "limit" in all_text:
        return ErrorType.RATE_LIMIT, "Rate limited (429)"
    if "529" in all_text or "overloaded" in all_text:
        return ErrorType.OVERLOADED, "API overloaded (529)"
    if "403" in all_text or "forbidden" in all_text:
        return ErrorType.FORBIDDEN, "Forbidden (403)"

    usage = data.get("usage", {})
    if usage.get("input_tokens", 0) == 0 and usage.get("output_tokens", 0) == 0:
        return ErrorType.API_TIMEOUT, "API timeout (0 tokens)"

    return ErrorType.UNKNOWN, "Unknown error"
