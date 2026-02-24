"""Tests for combined ASGI app: web UI + MCP role mounts + health endpoint."""

import io
from unittest.mock import patch

import pytest
from ralph_tasks.web import app
from starlette.applications import Starlette
from starlette.testclient import TestClient

TEST_API_KEY = "test-secret-key-12345"


@pytest.fixture
def client():
    """TestClient for the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_client(monkeypatch):
    """TestClient with API key authentication enabled."""
    monkeypatch.setenv("RALPH_TASKS_API_KEY", TEST_API_KEY)
    return TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ralph-tasks"


class TestMcpRoleMounts:
    """Tests for role-based MCP mounts at /mcp-swe, /mcp-review, /mcp-plan."""

    def test_all_role_mounts_exist(self):
        """The app should have /mcp-swe, /mcp-review, /mcp-plan in its routes."""
        mount_paths = [
            r.path for r in app.routes if hasattr(r, "path") and not hasattr(r, "methods")
        ]
        assert "/mcp-swe" in mount_paths
        assert "/mcp-review" in mount_paths
        assert "/mcp-plan" in mount_paths

    def test_old_mcp_mount_removed(self):
        """The old /mcp mount should no longer exist."""
        mount_paths = [
            r.path for r in app.routes if hasattr(r, "path") and not hasattr(r, "methods")
        ]
        assert "/mcp" not in mount_paths

    def test_swe_mount_name(self):
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/mcp-swe":
                assert route.name == "mcp-swe"
                break
        else:
            pytest.fail("/mcp-swe route not found")

    def test_reviewer_mount_name(self):
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/mcp-review":
                assert route.name == "mcp-review"
                break
        else:
            pytest.fail("/mcp-review route not found")

    def test_planner_mount_name(self):
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/mcp-plan":
                assert route.name == "mcp-plan"
                break
        else:
            pytest.fail("/mcp-plan route not found")

    def test_each_mount_has_app(self):
        for path in ("/mcp-swe", "/mcp-review", "/mcp-plan"):
            for route in app.routes:
                if hasattr(route, "path") and route.path == path:
                    assert hasattr(route, "app"), f"{path} mount has no app"
                    break
            else:
                pytest.fail(f"{path} route not found")


class TestMcpRoleApps:
    """Tests for get_*_mcp_app() factory functions."""

    def test_swe_app_returns_starlette(self):
        from ralph_tasks.mcp import get_swe_mcp_app

        assert isinstance(get_swe_mcp_app(), Starlette)

    def test_reviewer_app_returns_starlette(self):
        from ralph_tasks.mcp import get_reviewer_mcp_app

        assert isinstance(get_reviewer_mcp_app(), Starlette)

    def test_planner_app_returns_starlette(self):
        from ralph_tasks.mcp import get_planner_mcp_app

        assert isinstance(get_planner_mcp_app(), Starlette)


class TestReviewTypeValidation:
    """Tests for ReviewTypeValidationMiddleware."""

    def test_mcp_review_requires_review_type(self, client):
        """Requests to /mcp-review without review_type should get 400."""
        response = client.get("/mcp-review/")
        assert response.status_code == 400
        assert "review_type" in response.json()["detail"]

    def test_mcp_review_with_review_type_passes(self, client):
        """Requests to /mcp-review with review_type should pass through."""
        response = client.get("/mcp-review/?review_type=code-review")
        # Should not be 400 (the actual response depends on the MCP app)
        assert response.status_code != 400

    def test_mcp_swe_no_review_type_needed(self, client):
        """Requests to /mcp-swe should not require review_type."""
        response = client.get("/mcp-swe/")
        assert response.status_code != 400

    def test_mcp_plan_no_review_type_needed(self, client):
        """Requests to /mcp-plan should not require review_type."""
        response = client.get("/mcp-plan/")
        assert response.status_code != 400


class TestWebRoutesUnchanged:
    """Verify existing web routes still work after MCP mount."""

    def test_root_returns_html(self, client):
        """Root page should return HTML (mocking Neo4j dependency)."""
        with patch("ralph_tasks.web.list_projects", return_value=[]):
            response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_projects_page_has_dashboard_link(self, client):
        """Projects page should have a link to the dashboard."""
        with patch("ralph_tasks.web.list_projects", return_value=[]):
            response = client.get("/")
        assert response.status_code == 200
        assert 'data-testid="dashboard-link"' in response.text
        assert 'href="/dashboard"' in response.text

    def test_settings_api_removed(self, client):
        """Settings endpoint was removed along with backup functionality."""
        response = client.get("/api/settings")
        assert response.status_code == 404

    def test_task_api_404(self, client):
        """Non-existent task should 404 (mocking Neo4j)."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = client.get("/api/task/nonexistent/999")
        assert response.status_code == 404


class TestKanbanRedirect:
    """Tests for project name normalization redirect in kanban."""

    def test_underscore_redirects_to_hyphen(self, client):
        """Kanban with underscore name should 301 redirect to hyphen."""
        response = client.get("/kanban/my_project", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/kanban/my-project"

    def test_canonical_name_no_redirect(self, client):
        """Kanban with canonical name should render normally (no redirect)."""
        with patch("ralph_tasks.web.list_tasks", return_value=[]):
            response = client.get("/kanban/my-project")
        assert response.status_code == 200

    def test_redirect_preserves_query_params(self, client):
        """301 redirect should preserve query parameters."""
        response = client.get("/kanban/my_project?filter=todo", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/kanban/my-project?filter=todo"

    def test_kanban_renders_review_badges(self, client):
        """Kanban cards show review badge when review_counts has data."""
        from ralph_tasks.core import Task

        task = Task(number=1, title="Test task", status="todo", updated_at="2026-01-01T00:00:00")
        with (
            patch("ralph_tasks.web.list_tasks", return_value=[task]),
            patch("ralph_tasks.web.count_open_findings", return_value={1: 3}),
        ):
            response = client.get("/kanban/test-proj")
        assert response.status_code == 200
        assert 'data-testid="review-badge-1"' in response.text
        assert "3 open" in response.text

    def test_kanban_graceful_degradation(self, client):
        """Kanban renders without badges when count_open_findings raises."""
        from ralph_tasks.core import Task

        task = Task(number=1, title="Test task", status="todo", updated_at="2026-01-01T00:00:00")
        with (
            patch("ralph_tasks.web.list_tasks", return_value=[task]),
            patch("ralph_tasks.web.count_open_findings", side_effect=ConnectionError("Neo4j down")),
        ):
            response = client.get("/kanban/test-proj")
        assert response.status_code == 200
        assert 'data-testid="review-badge-' not in response.text


class TestWebMainConfig:
    """Tests for web.main() configuration via environment variables."""

    def test_main_uses_default_host_port(self, monkeypatch):
        monkeypatch.delenv("RALPH_TASKS_HOST", raising=False)
        monkeypatch.delenv("RALPH_TASKS_PORT", raising=False)

        captured = {}

        def mock_uvicorn_run(app, host, port):
            captured["host"] = host
            captured["port"] = port

        with patch("ralph_tasks.web.uvicorn.run", side_effect=mock_uvicorn_run):
            from ralph_tasks.web import main

            main()

        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8000

    def test_main_uses_custom_host_port(self, monkeypatch):
        monkeypatch.setenv("RALPH_TASKS_HOST", "0.0.0.0")
        monkeypatch.setenv("RALPH_TASKS_PORT", "3000")

        captured = {}

        def mock_uvicorn_run(app, host, port):
            captured["host"] = host
            captured["port"] = port

        with patch("ralph_tasks.web.uvicorn.run", side_effect=mock_uvicorn_run):
            from ralph_tasks.web import main

            main()

        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 3000


class TestExtractToken:
    """Tests for _extract_token_from_headers helper."""

    def test_bearer_token_extracted(self):
        from ralph_tasks.web import _extract_token_from_headers

        headers = {b"authorization": b"Bearer my-secret"}
        assert _extract_token_from_headers(headers) == "my-secret"

    def test_bearer_case_insensitive(self):
        from ralph_tasks.web import _extract_token_from_headers

        headers = {b"authorization": b"bearer my-secret"}
        assert _extract_token_from_headers(headers) == "my-secret"

    def test_x_api_key_fallback(self):
        from ralph_tasks.web import _extract_token_from_headers

        headers = {b"x-api-key": b"my-secret"}
        assert _extract_token_from_headers(headers) == "my-secret"

    def test_no_auth_headers(self):
        from ralph_tasks.web import _extract_token_from_headers

        assert _extract_token_from_headers({}) is None

    def test_binary_auth_header_returns_none(self):
        from ralph_tasks.web import _extract_token_from_headers

        headers = {b"authorization": b"\xff\xfe"}
        assert _extract_token_from_headers(headers) is None


class TestApiKeyAuth:
    """Tests for API key authentication middleware."""

    def test_health_no_auth_required(self, auth_client):
        response = auth_client.get("/health")
        assert response.status_code == 200

    def test_api_401_without_key(self, auth_client):
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get("/api/task/test/1")
        assert response.status_code == 401
        assert "API key" in response.json()["detail"]

    def test_api_bearer_token(self, auth_client):
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": f"Bearer {TEST_API_KEY}"},
            )
        assert response.status_code == 404

    def test_api_x_api_key_header(self, auth_client):
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"X-API-Key": TEST_API_KEY},
            )
        assert response.status_code == 404

    def test_api_wrong_key(self, auth_client):
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert response.status_code == 401

    def test_mcp_swe_401_without_key(self, auth_client):
        """/mcp-swe should return 401 when auth is enabled but no key provided."""
        response = auth_client.get("/mcp-swe/")
        assert response.status_code == 401

    def test_mcp_review_401_without_key(self, auth_client):
        """/mcp-review should return 401 when auth is enabled but no key provided."""
        response = auth_client.get("/mcp-review/?review_type=code")
        assert response.status_code == 401

    def test_mcp_plan_401_without_key(self, auth_client):
        """/mcp-plan should return 401 when auth is enabled but no key provided."""
        response = auth_client.get("/mcp-plan/")
        assert response.status_code == 401

    def test_no_auth_when_env_not_set(self, client):
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = client.get("/api/task/test/1")
        assert response.status_code == 404

    def test_web_pages_no_auth(self, auth_client):
        with patch("ralph_tasks.web.list_projects", return_value=[]):
            response = auth_client.get("/")
        assert response.status_code == 200

        with patch("ralph_tasks.web.list_tasks", return_value=[]):
            response = auth_client.get("/kanban/test-project")
        assert response.status_code == 200

    def test_bearer_case_insensitive(self, auth_client):
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": f"bearer {TEST_API_KEY}"},
            )
        assert response.status_code == 404

        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": f"BEARER {TEST_API_KEY}"},
            )
        assert response.status_code == 404

    def test_whitespace_only_key_is_disabled(self, monkeypatch):
        monkeypatch.setenv("RALPH_TASKS_API_KEY", "   ")
        client = TestClient(app, raise_server_exceptions=False)
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = client.get("/api/task/test/1")
        assert response.status_code == 404

    def test_mcp_swe_root_path_protected(self, auth_client):
        """/mcp-swe (without trailing slash) should also be protected."""
        response = auth_client.get("/mcp-swe")
        assert response.status_code in (401, 307)


class TestUploadSizeLimit:
    """Tests for file upload size limit."""

    def test_small_file_accepted(self, client, monkeypatch):
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "1")
        small_content = b"Hello, world!"

        with (
            patch("ralph_tasks.web.get_task") as mock_get,
            patch(
                "ralph_tasks.web.save_attachment",
                return_value={"name": "test.txt", "size": len(small_content)},
            ),
        ):
            mock_get.return_value = True
            response = client.post(
                "/api/task/test/1/attachments",
                files={"file": ("test.txt", io.BytesIO(small_content), "text/plain")},
            )
        assert response.status_code == 200

    def test_large_file_rejected_413(self, client, monkeypatch):
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "1")
        large_content = b"x" * (1024 * 1024 + 1)

        with patch("ralph_tasks.web.get_task") as mock_get:
            mock_get.return_value = True
            response = client.post(
                "/api/task/test/1/attachments",
                files={"file": ("big.bin", io.BytesIO(large_content), "application/octet-stream")},
            )
        assert response.status_code == 413
        assert "too large" in response.json()["detail"]

    def test_default_limit_50mb(self, monkeypatch):
        monkeypatch.delenv("RALPH_TASKS_MAX_UPLOAD_MB", raising=False)
        from ralph_tasks.web import _get_max_upload_bytes

        assert _get_max_upload_bytes() == 50 * 1024 * 1024

    def test_invalid_max_upload_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "not-a-number")
        from ralph_tasks.web import _get_max_upload_bytes

        assert _get_max_upload_bytes() == 50 * 1024 * 1024

    def test_negative_max_upload_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "-10")
        from ralph_tasks.web import _get_max_upload_bytes

        assert _get_max_upload_bytes() == 50 * 1024 * 1024


class TestTaskApiFieldNames:
    """Tests for renamed field names in task API."""

    def test_create_task_uses_title_field(self, client):
        """POST /api/task/{project} should accept 'title' field."""
        with patch("ralph_tasks.web._create_task") as mock_create:
            from ralph_tasks.core import Task

            mock_create.return_value = Task(number=1, title="Test Task")
            response = client.post(
                "/api/task/test-project",
                json={"title": "Test Task"},
            )
        assert response.status_code == 200
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args[0][1] == "Test Task"

    def test_create_task_rejects_empty_title(self, client):
        """POST /api/task/{project} should reject empty title."""
        response = client.post(
            "/api/task/test-project",
            json={"title": "   "},
        )
        assert response.status_code == 400

    def test_update_task_accepts_title_field(self, client):
        """POST /api/task/{project}/{number} should accept 'title' field."""
        from ralph_tasks.core import Task

        updated = Task(number=1, title="Updated Title")
        with patch("ralph_tasks.web._update_task", return_value=updated):
            response = client.post(
                "/api/task/test/1",
                json={"title": "Updated Title"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["task"]["title"] == "Updated Title"

    def test_update_task_accepts_description_field(self, client):
        """POST /api/task/{project}/{number} should accept 'description' field."""
        from ralph_tasks.core import Task

        updated = Task(number=1, title="Task", description="New desc")
        with patch("ralph_tasks.web._update_task", return_value=updated):
            response = client.post(
                "/api/task/test/1",
                json={"description": "New desc"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["task"]["description"] == "New desc"

    def test_get_task_returns_new_field_names(self, client):
        """GET /api/task/{project}/{number} should return title/description."""
        from ralph_tasks.core import Task

        task = Task(number=1, title="My Task", description="Details here")
        with patch("ralph_tasks.web.get_task", return_value=task):
            response = client.get("/api/task/test/1")
        assert response.status_code == 200
        data = response.json()
        assert "title" in data
        assert "description" in data
        assert data["title"] == "My Task"
        assert data["description"] == "Details here"

    def test_monthly_api_returns_title(self, client):
        """GET /api/monthly/{month} should return 'title' field for tasks."""
        from ralph_tasks.core import Task

        tasks = [
            Task(number=1, title="Task 1", status="done", completed="2026-02-15 10:00"),
        ]
        with (
            patch("ralph_tasks.web.list_projects", return_value=["test"]),
            patch("ralph_tasks.web.list_tasks", return_value=tasks),
        ):
            response = client.get("/api/monthly/2026-02")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["title"] == "Task 1"
