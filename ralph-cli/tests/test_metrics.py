"""Tests for fire-and-forget metrics submission."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest
from ralph_cli.config import Settings
from ralph_cli.metrics import submit_session_metrics


def _mock_ok_response(payload: dict | None = None) -> MagicMock:
    """Create a mock urlopen response context manager returning ok=True."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload or {"ok": True}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


@pytest.fixture(autouse=True)
def _reset_settings():
    """Reset settings singleton before each test."""
    from ralph_cli.config import reset_settings

    reset_settings()
    yield
    reset_settings()


class TestSubmitSessionMetrics:
    def test_no_url_configured_returns_false(self):
        """When ralph_tasks_api_url is None, no HTTP call is made."""
        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(_env_file=None, ralph_tasks_api_url=None)
            result = submit_session_metrics(
                command_type="implement",
                project="test",
                started_at=datetime(2026, 1, 1, 12, 0),
            )
            assert result is False

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_success(self, mock_urlopen):
        """Successful metric submission returns True."""
        mock_urlopen.return_value = _mock_ok_response({"ok": True, "session_id": "abc"})

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
            )
            result = submit_session_metrics(
                command_type="implement",
                project="test",
                started_at=datetime(2026, 1, 1, 12, 0),
                finished_at=datetime(2026, 1, 1, 13, 0),
                total_cost_usd=1.50,
                total_input_tokens=1000,
                total_output_tokens=500,
                exit_code=0,
            )

        assert result is True
        # Verify the request was made
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "http://localhost:8000/api/metrics/sessions"
        assert req.method == "POST"

        body = json.loads(req.data)
        assert body["command_type"] == "implement"
        assert body["project"] == "test"
        assert body["total_cost_usd"] == 1.50
        assert body["total_input_tokens"] == 1000
        assert body["total_output_tokens"] == 500
        assert body["exit_code"] == 0
        assert "started_at" in body
        assert "finished_at" in body

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_with_api_key(self, mock_urlopen):
        """API key is sent as Bearer token in Authorization header."""
        mock_urlopen.return_value = _mock_ok_response()

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
                ralph_tasks_api_key="secret-key-123",
            )
            submit_session_metrics(
                command_type="plan",
                project="test",
                started_at=datetime(2026, 1, 1),
            )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer secret-key-123"

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_without_api_key(self, mock_urlopen):
        """Without API key, no Authorization header is sent."""
        mock_urlopen.return_value = _mock_ok_response()

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
                ralph_tasks_api_key=None,
            )
            submit_session_metrics(
                command_type="plan",
                project="test",
                started_at=datetime(2026, 1, 1),
            )

        req = mock_urlopen.call_args[0][0]
        assert not req.has_header("Authorization")

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_server_error(self, mock_urlopen):
        """HTTP 500 from server does not crash, returns False."""
        mock_urlopen.side_effect = HTTPError(
            url="http://localhost:8000/api/metrics/sessions",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=None,
        )

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
            )
            result = submit_session_metrics(
                command_type="implement",
                project="test",
                started_at=datetime(2026, 1, 1),
            )

        assert result is False

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_connection_error(self, mock_urlopen):
        """Connection error does not crash, returns False."""
        mock_urlopen.side_effect = ConnectionError("Network unreachable")

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
            )
            result = submit_session_metrics(
                command_type="implement",
                project="test",
                started_at=datetime(2026, 1, 1),
            )

        assert result is False

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_with_task_executions(self, mock_urlopen):
        """Task executions are included in the payload."""
        mock_urlopen.return_value = _mock_ok_response()

        executions = [
            {
                "task_ref": "proj#1",
                "cost_usd": 0.50,
                "input_tokens": 500,
                "output_tokens": 200,
                "duration_seconds": 120,
                "exit_code": 0,
            },
            {
                "task_ref": "proj#2",
                "cost_usd": 0.75,
                "input_tokens": 700,
                "output_tokens": 300,
                "duration_seconds": 180,
                "exit_code": 0,
            },
        ]

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
            )
            submit_session_metrics(
                command_type="implement",
                project="test",
                started_at=datetime(2026, 1, 1),
                task_executions=executions,
            )

        body = json.loads(mock_urlopen.call_args[0][0].data)
        assert len(body["task_executions"]) == 2
        assert body["task_executions"][0]["task_ref"] == "proj#1"
        assert body["task_executions"][1]["cost_usd"] == 0.75

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_minimal(self, mock_urlopen):
        """Minimal submission with only required fields."""
        mock_urlopen.return_value = _mock_ok_response()

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
            )
            result = submit_session_metrics(
                command_type="interview",
                project="test",
                started_at=datetime(2026, 1, 1),
            )

        assert result is True
        body = json.loads(mock_urlopen.call_args[0][0].data)
        assert body["command_type"] == "interview"
        assert body["project"] == "test"
        # Optional fields should not be present
        assert "finished_at" not in body
        assert "exit_code" not in body
        assert "model" not in body
        assert "task_executions" not in body

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_with_optional_fields(self, mock_urlopen):
        """All optional fields are included when provided."""
        mock_urlopen.return_value = _mock_ok_response()

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
            )
            submit_session_metrics(
                command_type="implement",
                project="test",
                started_at=datetime(2026, 1, 1),
                finished_at=datetime(2026, 1, 1, 1),
                model="opus",
                claude_session_id="sess-123",
                error_type="COMPLETED",
                total_cache_read=100,
                total_tool_calls=50,
            )

        body = json.loads(mock_urlopen.call_args[0][0].data)
        assert body["model"] == "opus"
        assert body["claude_session_id"] == "sess-123"
        assert body["error_type"] == "COMPLETED"
        assert body["total_cache_read"] == 100
        assert body["total_tool_calls"] == 50

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_url_trailing_slash_stripped(self, mock_urlopen):
        """Trailing slash in API URL is handled correctly."""
        mock_urlopen.return_value = _mock_ok_response()

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000/",
            )
            submit_session_metrics(
                command_type="plan",
                project="test",
                started_at=datetime(2026, 1, 1),
            )

        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://localhost:8000/api/metrics/sessions"

    @patch("ralph_cli.metrics.urllib.request.urlopen")
    def test_submit_server_rejection(self, mock_urlopen):
        """Server returning ok=false returns False and logs warning."""
        mock_urlopen.return_value = _mock_ok_response({"ok": False, "error": "bad data"})

        with patch("ralph_cli.metrics.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                _env_file=None,
                ralph_tasks_api_url="http://localhost:8000",
            )
            with patch("ralph_cli.metrics.logger") as mock_logger:
                result = submit_session_metrics(
                    command_type="implement",
                    project="test",
                    started_at=datetime(2026, 1, 1),
                )

        assert result is False
        mock_logger.warning.assert_called_once()
