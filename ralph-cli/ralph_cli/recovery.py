"""Recovery loop for API errors."""

import time
from collections.abc import Callable

from .config import Settings
from .errors import ErrorType
from .health import check_health


def recovery_loop(
    settings: Settings,
    on_attempt: Callable[[int, int, int], None] | None = None,
    on_recovered: Callable[[], None] | None = None,
) -> bool:
    """Wait and check health with configured delays.

    Args:
        settings: Settings with recovery_delays
        on_attempt: Callback(attempt, max_attempts, delay) before each wait
        on_recovered: Callback when API recovers

    Returns:
        True if recovered, False if all attempts failed.
    """
    delays = settings.recovery_delays
    max_attempts = len(delays)

    for attempt, delay in enumerate(delays, 1):
        if on_attempt:
            on_attempt(attempt, max_attempts, delay)

        # Wait
        time.sleep(delay)

        # Check health
        result = check_health()

        if result.is_healthy:
            if on_recovered:
                on_recovered()
            return True

    return False


def should_recover(error_type: ErrorType, settings: Settings) -> bool:
    """Check if error type should trigger recovery."""
    if not settings.recovery_enabled:
        return False
    return error_type.is_recoverable


def should_retry_fresh(error_type: ErrorType, attempt: int, settings: Settings) -> bool:
    """Check if error should trigger fresh session retry.

    For context overflow, allows limited retries with fresh session.
    """
    if error_type != ErrorType.CONTEXT_OVERFLOW:
        return False
    return attempt < settings.context_overflow_max_retries
