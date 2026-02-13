"""Tests for error classification."""

from ralph_cli.errors import ErrorType, classify_from_json, classify_from_text


class TestErrorType:
    """Tests for ErrorType enum."""

    def test_is_recoverable(self):
        """Test recoverable error types."""
        assert ErrorType.AUTH_EXPIRED.is_recoverable
        assert ErrorType.API_TIMEOUT.is_recoverable
        assert ErrorType.RATE_LIMIT.is_recoverable
        assert ErrorType.OVERLOADED.is_recoverable

        assert not ErrorType.COMPLETED.is_recoverable
        assert not ErrorType.CONTEXT_OVERFLOW.is_recoverable
        assert not ErrorType.FORBIDDEN.is_recoverable
        assert not ErrorType.UNKNOWN.is_recoverable

    def test_is_fatal(self):
        """Test fatal error types."""
        assert ErrorType.FORBIDDEN.is_fatal

        assert not ErrorType.COMPLETED.is_fatal
        assert not ErrorType.AUTH_EXPIRED.is_fatal
        assert not ErrorType.UNKNOWN.is_fatal

    def test_is_success(self):
        """Test success check."""
        assert ErrorType.COMPLETED.is_success
        assert not ErrorType.UNKNOWN.is_success
        assert not ErrorType.AUTH_EXPIRED.is_success

    def test_needs_fresh_session(self):
        """Test fresh session requirement."""
        assert ErrorType.CONTEXT_OVERFLOW.needs_fresh_session
        assert not ErrorType.AUTH_EXPIRED.needs_fresh_session
        assert not ErrorType.COMPLETED.needs_fresh_session


class TestClassifyFromText:
    """Tests for classify_from_text function."""

    def test_completed(self):
        """Test completed detection."""
        text = "I confirm that all task phases are fully completed"
        assert classify_from_text(text) == ErrorType.COMPLETED

    def test_context_overflow(self):
        """Test context overflow detection."""
        assert classify_from_text("Prompt is too long") == ErrorType.CONTEXT_OVERFLOW
        assert classify_from_text("context overflow error") == ErrorType.CONTEXT_OVERFLOW

    def test_auth_expired(self):
        """Test auth error detection."""
        assert classify_from_text("Error 401 unauthorized") == ErrorType.AUTH_EXPIRED
        assert classify_from_text("authentication failed") == ErrorType.AUTH_EXPIRED

    def test_rate_limit(self):
        """Test rate limit detection."""
        assert classify_from_text("Error 429") == ErrorType.RATE_LIMIT
        assert classify_from_text("rate limit exceeded") == ErrorType.RATE_LIMIT

    def test_overloaded(self):
        """Test overloaded detection."""
        assert classify_from_text("Error 529") == ErrorType.OVERLOADED
        assert classify_from_text("API overloaded") == ErrorType.OVERLOADED

    def test_forbidden(self):
        """Test forbidden detection."""
        assert classify_from_text("Error 403") == ErrorType.FORBIDDEN
        assert classify_from_text("Forbidden access") == ErrorType.FORBIDDEN

    def test_api_timeout(self):
        """Test API timeout detection."""
        assert classify_from_text("Tokens: 0 in / 0 out") == ErrorType.API_TIMEOUT

    def test_on_hold(self):
        """Test on hold detection."""
        assert classify_from_text("## Blocks\n- Problem") == ErrorType.ON_HOLD
        assert classify_from_text("status → hold") == ErrorType.ON_HOLD

    def test_unknown(self):
        """Test unknown error."""
        assert classify_from_text("some random error") == ErrorType.UNKNOWN
        assert classify_from_text("") == ErrorType.UNKNOWN


class TestClassifyFromJson:
    """Tests for classify_from_json function."""

    def test_context_overflow(self):
        """Test context overflow from JSON."""
        data = {"result": "Prompt is too long", "errors": []}
        error_type, _ = classify_from_json(data)
        assert error_type == ErrorType.CONTEXT_OVERFLOW

    def test_auth_error(self):
        """Test auth error from JSON."""
        data = {"error_code": "401", "errors": ["Unauthorized"]}
        error_type, _ = classify_from_json(data)
        assert error_type == ErrorType.AUTH_EXPIRED

    def test_rate_limit(self):
        """Test rate limit from JSON."""
        data = {"error_code": "429", "result": "rate limit"}
        error_type, _ = classify_from_json(data)
        assert error_type == ErrorType.RATE_LIMIT

    def test_overloaded(self):
        """Test overloaded from JSON."""
        data = {"errors": ["529 overloaded"]}
        error_type, _ = classify_from_json(data)
        assert error_type == ErrorType.OVERLOADED

    def test_api_timeout(self):
        """Test API timeout from JSON."""
        data = {"usage": {"input_tokens": 0, "output_tokens": 0}}
        error_type, _ = classify_from_json(data)
        assert error_type == ErrorType.API_TIMEOUT

    def test_unknown(self):
        """Test unknown error from JSON."""
        data = {"result": "success", "usage": {"input_tokens": 100, "output_tokens": 50}}
        error_type, _ = classify_from_json(data)
        assert error_type == ErrorType.UNKNOWN
