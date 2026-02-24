"""Tests for metrics REST API endpoints in web.py."""

from unittest.mock import patch

import pytest
from ralph_tasks.web import app
from starlette.testclient import TestClient


@pytest.fixture
def client():
    """TestClient without server exceptions raised."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_client(monkeypatch):
    """TestClient connected to an app that requires API key authentication."""
    monkeypatch.setenv("RALPH_TASKS_API_KEY", "test-key-123")
    return TestClient(app, raise_server_exceptions=False)


# =============================================================================
# POST /api/metrics/sessions
# =============================================================================


class TestCreateMetricsSession:
    """Tests for POST /api/metrics/sessions."""

    def test_success(self, client):
        """Full session payload creates session and returns session_id."""
        payload = {
            "command_type": "implement",
            "project": "ralph",
            "model": "opus",
            "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T01:00:00",
            "total_cost_usd": 1.5,
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
            "total_cache_read": 200,
            "total_tool_calls": 10,
            "exit_code": 0,
            "claude_session_id": "sess-123",
        }
        with patch("ralph_tasks.metrics.database.create_session", return_value="uuid-abc") as mock:
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["session_id"] == "uuid-abc"
        mock.assert_called_once()
        call_data = mock.call_args[0][0]
        assert call_data["command_type"] == "implement"
        assert call_data["project"] == "ralph"

    def test_minimal(self, client):
        """Minimal required fields succeed."""
        payload = {
            "command_type": "plan",
            "project": "test",
            "started_at": "2026-02-01T00:00:00",
        }
        with patch("ralph_tasks.metrics.database.create_session", return_value="uuid-min"):
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 200
        assert res.json()["session_id"] == "uuid-min"

    def test_with_task_executions(self, client):
        """Session with task_executions is passed through."""
        payload = {
            "command_type": "implement",
            "project": "ralph",
            "started_at": "2026-01-01T00:00:00",
            "task_executions": [
                {
                    "task_ref": "ralph#83",
                    "cost_usd": 0.5,
                    "input_tokens": 500,
                    "output_tokens": 250,
                    "duration_seconds": 120,
                    "exit_code": 0,
                    "git_branch": "feature-83",
                    "files_changed": 3,
                    "recovery_attempts": 0,
                }
            ],
        }
        with patch("ralph_tasks.metrics.database.create_session", return_value="uuid-te") as mock:
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 200
        call_data = mock.call_args[0][0]
        assert len(call_data["task_executions"]) == 1
        assert call_data["task_executions"][0]["task_ref"] == "ralph#83"

    def test_multiple_task_executions(self, client):
        """Session with multiple task_executions passes all through."""
        payload = {
            "command_type": "implement",
            "project": "ralph",
            "started_at": "2026-01-01T00:00:00",
            "task_executions": [
                {"task_ref": "ralph#83", "cost_usd": 0.5},
                {"task_ref": "ralph#84", "cost_usd": 0.3},
            ],
        }
        with patch("ralph_tasks.metrics.database.create_session", return_value="uuid-x") as mock:
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 200
        call_data = mock.call_args[0][0]
        assert len(call_data["task_executions"]) == 2
        assert call_data["task_executions"][1]["task_ref"] == "ralph#84"

    def test_missing_required_field_returns_422(self, client):
        """Missing required fields return 422."""
        payload = {"model": "opus"}  # missing command_type, project, started_at
        res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 422

    def test_task_execution_missing_task_ref_returns_422(self, client):
        """task_execution missing task_ref returns 422."""
        payload = {
            "command_type": "implement",
            "project": "ralph",
            "started_at": "2026-01-01T00:00:00",
            "task_executions": [{"cost_usd": 0.5}],  # missing task_ref
        }
        res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 422

    def test_invalid_started_at_returns_422(self, client):
        """Non-ISO-8601 started_at returns 422."""
        payload = {
            "command_type": "plan",
            "project": "test",
            "started_at": "not-a-date",
        }
        res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 422

    def test_value_error_returns_400(self, client):
        """ValueError from database layer returns 400, not 503."""
        payload = {
            "command_type": "implement",
            "project": "test",
            "started_at": "2026-01-01T00:00:00",
        }
        with patch(
            "ralph_tasks.metrics.database.create_session",
            side_effect=ValueError("Missing required fields"),
        ):
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 400

    def test_http_exception_propagates_unchanged(self, client):
        """HTTPException from database layer propagates with original status code."""
        from fastapi import HTTPException as FastAPIHTTPException

        payload = {
            "command_type": "implement",
            "project": "test",
            "started_at": "2026-01-01T00:00:00",
        }
        with patch(
            "ralph_tasks.metrics.database.create_session",
            side_effect=FastAPIHTTPException(status_code=409, detail="duplicate"),
        ):
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 409
        assert res.json()["detail"] == "duplicate"

    def test_offset_aware_datetimes_normalized_to_naive_utc(self, client):
        """Offset-aware datetimes are converted to naive UTC before storage."""
        from datetime import datetime

        payload = {
            "command_type": "implement",
            "project": "test",
            "started_at": "2026-01-15T15:00:00+03:00",
            "finished_at": "2026-01-15T16:00:00+03:00",
        }
        with patch("ralph_tasks.metrics.database.create_session", return_value="uuid-tz") as mock:
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 200
        call_data = mock.call_args[0][0]
        # +03:00 offset means 15:00+03:00 = 12:00 UTC
        assert call_data["started_at"] == datetime(2026, 1, 15, 12, 0, 0)
        assert call_data["finished_at"] == datetime(2026, 1, 15, 13, 0, 0)
        # Must be naive (no tzinfo) for TIMESTAMP columns
        assert call_data["started_at"].tzinfo is None
        assert call_data["finished_at"].tzinfo is None

    def test_naive_datetimes_passed_through_unchanged(self, client):
        """Naive datetimes (no timezone) are passed through as-is."""
        from datetime import datetime

        payload = {
            "command_type": "implement",
            "project": "test",
            "started_at": "2026-01-15T15:00:00",
        }
        with patch("ralph_tasks.metrics.database.create_session", return_value="uuid-nv") as mock:
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 200
        call_data = mock.call_args[0][0]
        assert call_data["started_at"] == datetime(2026, 1, 15, 15, 0, 0)
        assert call_data["started_at"].tzinfo is None

    def test_pg_unavailable_returns_503(self, client):
        """Database error returns 503."""
        payload = {
            "command_type": "implement",
            "project": "test",
            "started_at": "2026-01-01T00:00:00",
        }
        with patch(
            "ralph_tasks.metrics.database.create_session",
            side_effect=ConnectionError("PG down"),
        ):
            res = client.post("/api/metrics/sessions", json=payload)
        assert res.status_code == 503
        assert "Metrics service unavailable" in res.json()["detail"]


# =============================================================================
# GET /api/metrics/summary
# =============================================================================


class TestGetMetricsSummary:
    """Tests for GET /api/metrics/summary."""

    def test_default_params(self, client):
        """Default period=30d, no project filter."""
        mock_result = {
            "total_sessions": 5,
            "successful": 4,
            "failed": 1,
            "total_cost": 10.0,
            "avg_cost_per_session": 2.0,
            "total_input_tokens": 5000,
            "total_output_tokens": 2500,
            "total_tokens": 7500,
        }
        with patch("ralph_tasks.metrics.database.get_summary", return_value=mock_result) as mock:
            res = client.get("/api/metrics/summary")
        assert res.status_code == 200
        assert res.json() == mock_result
        mock.assert_called_once_with(period="30d", project=None)

    def test_custom_period(self, client):
        """Custom period=7d is passed through."""
        with patch("ralph_tasks.metrics.database.get_summary", return_value={}) as mock:
            res = client.get("/api/metrics/summary?period=7d")
        assert res.status_code == 200
        mock.assert_called_once_with(period="7d", project=None)

    def test_with_project(self, client):
        """Project filter is passed through."""
        with patch("ralph_tasks.metrics.database.get_summary", return_value={}) as mock:
            res = client.get("/api/metrics/summary?project=ralph")
        assert res.status_code == 200
        mock.assert_called_once_with(period="30d", project="ralph")

    def test_period_all(self, client):
        """Period=all is accepted."""
        with patch("ralph_tasks.metrics.database.get_summary", return_value={}) as mock:
            res = client.get("/api/metrics/summary?period=all")
        assert res.status_code == 200
        mock.assert_called_once_with(period="all", project=None)

    def test_invalid_period_returns_422(self, client):
        """Invalid period returns 422."""
        res = client.get("/api/metrics/summary?period=999d")
        assert res.status_code == 422

    def test_pg_unavailable_returns_503(self, client):
        """Database error returns 503."""
        with patch(
            "ralph_tasks.metrics.database.get_summary",
            side_effect=ConnectionError("PG down"),
        ):
            res = client.get("/api/metrics/summary")
        assert res.status_code == 503


# =============================================================================
# GET /api/metrics/timeline
# =============================================================================


class TestGetMetricsTimeline:
    """Tests for GET /api/metrics/timeline."""

    def test_default_params(self, client):
        """Default period=30d, metric=cost."""
        mock_result = {"labels": ["2026-01-01"], "datasets": [1.5]}
        with patch("ralph_tasks.metrics.database.get_timeline", return_value=mock_result) as mock:
            res = client.get("/api/metrics/timeline")
        assert res.status_code == 200
        assert res.json() == mock_result
        mock.assert_called_once_with(period="30d", metric="cost", project=None)

    def test_tokens_metric(self, client):
        """metric=tokens is accepted."""
        with patch("ralph_tasks.metrics.database.get_timeline", return_value={}) as mock:
            res = client.get("/api/metrics/timeline?metric=tokens")
        assert res.status_code == 200
        mock.assert_called_once_with(period="30d", metric="tokens", project=None)

    def test_invalid_period_all_returns_422(self, client):
        """Period=all is NOT allowed for timeline."""
        res = client.get("/api/metrics/timeline?period=all")
        assert res.status_code == 422

    def test_invalid_metric_returns_422(self, client):
        """Invalid metric returns 422."""
        res = client.get("/api/metrics/timeline?metric=sessions")
        assert res.status_code == 422

    def test_pg_unavailable_returns_503(self, client):
        """Database error returns 503."""
        with patch(
            "ralph_tasks.metrics.database.get_timeline",
            side_effect=ConnectionError("PG down"),
        ):
            res = client.get("/api/metrics/timeline")
        assert res.status_code == 503

    def test_with_project_filter(self, client):
        """Project filter is passed through."""
        with patch("ralph_tasks.metrics.database.get_timeline", return_value={}) as mock:
            res = client.get("/api/metrics/timeline?project=myproj&period=7d")
        assert res.status_code == 200
        mock.assert_called_once_with(period="7d", metric="cost", project="myproj")


# =============================================================================
# GET /api/metrics/breakdown
# =============================================================================


class TestGetMetricsBreakdown:
    """Tests for GET /api/metrics/breakdown."""

    def test_default_params(self, client):
        """Default period=30d, group_by=command_type."""
        mock_result = {"labels": ["implement", "plan"], "data": [5.0, 2.0]}
        with patch("ralph_tasks.metrics.database.get_breakdown", return_value=mock_result) as mock:
            res = client.get("/api/metrics/breakdown")
        assert res.status_code == 200
        assert res.json() == mock_result
        mock.assert_called_once_with(period="30d", group_by="command_type", project=None)

    def test_by_model(self, client):
        """group_by=model is accepted."""
        with patch("ralph_tasks.metrics.database.get_breakdown", return_value={}) as mock:
            res = client.get("/api/metrics/breakdown?group_by=model")
        assert res.status_code == 200
        mock.assert_called_once_with(period="30d", group_by="model", project=None)

    def test_period_all(self, client):
        """period=all is accepted for breakdown."""
        with patch("ralph_tasks.metrics.database.get_breakdown", return_value={}) as mock:
            res = client.get("/api/metrics/breakdown?period=all")
        assert res.status_code == 200
        mock.assert_called_once_with(period="all", group_by="command_type", project=None)

    def test_invalid_group_by_returns_422(self, client):
        """Invalid group_by returns 422."""
        res = client.get("/api/metrics/breakdown?group_by=user")
        assert res.status_code == 422

    def test_pg_unavailable_returns_503(self, client):
        """Database error returns 503."""
        with patch(
            "ralph_tasks.metrics.database.get_breakdown",
            side_effect=ConnectionError("PG down"),
        ):
            res = client.get("/api/metrics/breakdown")
        assert res.status_code == 503

    def test_with_period_and_project(self, client):
        """Period and project are passed through."""
        with patch("ralph_tasks.metrics.database.get_breakdown", return_value={}) as mock:
            res = client.get("/api/metrics/breakdown?period=90d&project=test")
        assert res.status_code == 200
        mock.assert_called_once_with(period="90d", group_by="command_type", project="test")


# =============================================================================
# GET /dashboard
# =============================================================================


class TestDashboardRoute:
    """Tests for GET /dashboard."""

    def test_returns_html(self, client):
        """Dashboard route returns HTML page."""
        res = client.get("/dashboard")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Dashboard" in res.text

    def test_no_auth_required(self, auth_client):
        """Dashboard is accessible without API key (not under /api/)."""
        res = auth_client.get("/dashboard")
        assert res.status_code == 200


# =============================================================================
# Auth protection
# =============================================================================


class TestMetricsAuthProtection:
    """Tests for API key protection on /api/metrics/* endpoints."""

    def test_post_sessions_requires_auth(self, auth_client):
        """POST /api/metrics/sessions requires API key."""
        res = auth_client.post(
            "/api/metrics/sessions",
            json={
                "command_type": "plan",
                "project": "test",
                "started_at": "2026-01-01T00:00:00",
            },
        )
        assert res.status_code == 401

    def test_get_summary_requires_auth(self, auth_client):
        """GET /api/metrics/summary requires API key."""
        res = auth_client.get("/api/metrics/summary")
        assert res.status_code == 401

    def test_get_timeline_requires_auth(self, auth_client):
        """GET /api/metrics/timeline requires API key."""
        res = auth_client.get("/api/metrics/timeline")
        assert res.status_code == 401

    def test_get_breakdown_requires_auth(self, auth_client):
        """GET /api/metrics/breakdown requires API key."""
        res = auth_client.get("/api/metrics/breakdown")
        assert res.status_code == 401

    def test_with_valid_bearer_token(self, auth_client):
        """Requests with valid Bearer token succeed."""
        with patch("ralph_tasks.metrics.database.get_summary", return_value={}):
            res = auth_client.get(
                "/api/metrics/summary",
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert res.status_code == 200

    def test_with_valid_x_api_key(self, auth_client):
        """Requests with valid X-API-Key header succeed."""
        with patch("ralph_tasks.metrics.database.get_summary", return_value={}):
            res = auth_client.get(
                "/api/metrics/summary",
                headers={"X-API-Key": "test-key-123"},
            )
        assert res.status_code == 200

    def test_auth_disabled_without_env_var(self, client):
        """Without RALPH_TASKS_API_KEY, auth is not enforced."""
        with patch("ralph_tasks.metrics.database.get_summary", return_value={}):
            res = client.get("/api/metrics/summary")
        assert res.status_code == 200
