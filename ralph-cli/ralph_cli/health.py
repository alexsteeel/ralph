"""API health check."""

import json
import subprocess
import sys
from dataclasses import dataclass

from .config import Settings, get_settings
from .errors import ErrorType


@dataclass
class HealthResult:
    """Health check result."""

    error_type: ErrorType
    message: str

    @property
    def is_healthy(self) -> bool:
        """Check if API is healthy."""
        return self.error_type == ErrorType.COMPLETED

    @property
    def exit_code(self) -> int:
        """Get exit code for CLI."""
        mapping = {
            ErrorType.COMPLETED: 0,
            ErrorType.AUTH_EXPIRED: 1,
            ErrorType.RATE_LIMIT: 2,
            ErrorType.OVERLOADED: 4,
        }
        return mapping.get(self.error_type, 3)


def check_health(verbose: bool = False, settings: Settings | None = None) -> HealthResult:
    """Run health check against Claude API.

    Sends minimal request to verify API is responding.
    """
    if settings is None:
        settings = get_settings()

    timeout = settings.health_check_timeout

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "Reply with OK",
                "--model",
                "haiku",
                "--max-turns",
                "1",
                "--output-format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = result.stdout + result.stderr

        if verbose:
            print(f"Raw output: {output[:500]}", file=sys.stderr)

        # Try to parse JSON (may be multiple objects, take last result)
        lines = output.strip().split("\n")
        data = None

        for line in reversed(lines):
            try:
                data = json.loads(line)
                if data.get("type") == "result":
                    break
            except json.JSONDecodeError:
                continue

        if data is None:
            # No valid JSON, check raw output
            lower = output.lower()
            if "401" in output or "unauthorized" in lower:
                return HealthResult(ErrorType.AUTH_EXPIRED, "Authentication failed (401)")
            if "429" in output or "rate" in lower:
                return HealthResult(ErrorType.RATE_LIMIT, "Rate limited (429)")
            if "529" in output or "overloaded" in lower:
                return HealthResult(ErrorType.OVERLOADED, "API overloaded (529)")
            return HealthResult(ErrorType.UNKNOWN, f"Could not parse response: {output[:200]}")

        # Check result type
        if data.get("type") == "result":
            if data.get("is_error"):
                error_code = str(data.get("error_code", ""))
                errors = data.get("errors", [])
                error_msg = "; ".join(str(e) for e in errors) or str(data.get("result", ""))

                if "401" in error_code or "401" in error_msg:
                    return HealthResult(
                        ErrorType.AUTH_EXPIRED, f"Authentication error: {error_msg}"
                    )
                if "429" in error_code or "429" in error_msg or "rate" in error_msg.lower():
                    return HealthResult(ErrorType.RATE_LIMIT, f"Rate limited: {error_msg}")
                if "529" in error_code or "529" in error_msg or "overloaded" in error_msg.lower():
                    return HealthResult(ErrorType.OVERLOADED, f"API overloaded: {error_msg}")

                return HealthResult(ErrorType.UNKNOWN, f"API error: {error_msg}")

            # Success
            result_text = data.get("result", "")
            if "OK" in result_text.upper() or result_text:
                return HealthResult(ErrorType.COMPLETED, "API is responding")

        # Check usage - tokens indicate API working
        usage = data.get("usage", {})
        if usage.get("output_tokens", 0) > 0:
            return HealthResult(ErrorType.COMPLETED, "API is responding (got tokens)")

        return HealthResult(ErrorType.UNKNOWN, "No valid response from API")

    except subprocess.TimeoutExpired:
        return HealthResult(ErrorType.API_TIMEOUT, f"Health check timed out after {timeout}s")
    except FileNotFoundError:
        return HealthResult(ErrorType.UNKNOWN, "Claude CLI not found")
    except Exception as e:
        return HealthResult(ErrorType.UNKNOWN, f"Health check failed: {e}")
