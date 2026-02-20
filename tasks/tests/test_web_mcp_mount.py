"""Tests for combined ASGI app: web UI + MCP mount + health endpoint."""

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


class TestMcpMount:
    """Tests for MCP mount at /mcp."""

    def test_mcp_mount_exists(self):
        """The app should have /mcp in its routes."""
        mount_paths = [
            r.path for r in app.routes if hasattr(r, "path") and not hasattr(r, "methods")
        ]
        assert "/mcp" in mount_paths

    def test_mcp_route_name(self):
        """The MCP mount should be named 'mcp'."""
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/mcp":
                assert route.name == "mcp"
                break
        else:
            pytest.fail("/mcp route not found")

    def test_mcp_mount_has_app(self):
        """The MCP mount should contain a sub-application."""
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/mcp":
                assert hasattr(route, "app")
                break
        else:
            pytest.fail("/mcp route not found")


class TestWebRoutesUnchanged:
    """Verify existing web routes still work after MCP mount."""

    def test_root_returns_html(self, client):
        """Root page should return HTML (mocking Neo4j dependency)."""
        with patch("ralph_tasks.web.list_projects", return_value=[]):
            response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

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


class TestGetMcpHttpApp:
    """Tests for mcp.get_mcp_http_app()."""

    def test_returns_starlette_app(self):
        from ralph_tasks.mcp import get_mcp_http_app

        http_app = get_mcp_http_app()
        assert isinstance(http_app, Starlette)

    def test_has_root_route(self):
        from ralph_tasks.mcp import get_mcp_http_app

        http_app = get_mcp_http_app()
        paths = [r.path for r in http_app.routes if hasattr(r, "path")]
        assert "/" in paths


class TestWebMainConfig:
    """Tests for web.main() configuration via environment variables."""

    def test_main_uses_default_host_port(self, monkeypatch):
        """main() should default to 127.0.0.1:8000 when env vars are unset."""
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
        """main() should read host/port from RALPH_TASKS_HOST/PORT env vars."""
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
        """Non-ASCII authorization header should not crash."""
        from ralph_tasks.web import _extract_token_from_headers

        headers = {b"authorization": b"\xff\xfe"}
        assert _extract_token_from_headers(headers) is None


class TestApiKeyAuth:
    """Tests for API key authentication middleware."""

    def test_health_no_auth_required(self, auth_client):
        """Health endpoint should work without authentication."""
        response = auth_client.get("/health")
        assert response.status_code == 200

    def test_api_401_without_key(self, auth_client):
        """/api/* should return 401 when no key is provided."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get("/api/task/test/1")
        assert response.status_code == 401
        assert "API key" in response.json()["detail"]

    def test_api_bearer_token(self, auth_client):
        """Authorization: Bearer <key> should grant access."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": f"Bearer {TEST_API_KEY}"},
            )
        assert response.status_code == 404  # 404 because task doesn't exist, not 401

    def test_api_x_api_key_header(self, auth_client):
        """X-API-Key header should grant access."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"X-API-Key": TEST_API_KEY},
            )
        assert response.status_code == 404

    def test_api_wrong_key(self, auth_client):
        """Wrong API key should return 401."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert response.status_code == 401

    def test_mcp_401_without_key(self, auth_client):
        """/mcp/* should return 401 when auth is enabled but no key provided."""
        response = auth_client.get("/mcp/")
        assert response.status_code == 401

    def test_no_auth_when_env_not_set(self, client):
        """When RALPH_TASKS_API_KEY is not set, all requests pass through."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = client.get("/api/task/test/1")
        assert response.status_code == 404  # Not 401

    def test_web_pages_no_auth(self, auth_client):
        """Root page and kanban pages should not require auth."""
        with patch("ralph_tasks.web.list_projects", return_value=[]):
            response = auth_client.get("/")
        assert response.status_code == 200

        with patch("ralph_tasks.web.list_tasks", return_value=[]):
            response = auth_client.get("/kanban/test-project")
        assert response.status_code == 200

    def test_bearer_case_insensitive(self, auth_client):
        """Bearer scheme should be case-insensitive per RFC 7235."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": f"bearer {TEST_API_KEY}"},
            )
        assert response.status_code == 404  # Authenticated, task not found

        with patch("ralph_tasks.web.get_task", return_value=None):
            response = auth_client.get(
                "/api/task/test/1",
                headers={"Authorization": f"BEARER {TEST_API_KEY}"},
            )
        assert response.status_code == 404

    def test_whitespace_only_key_is_disabled(self, monkeypatch):
        """Whitespace-only RALPH_TASKS_API_KEY should be treated as unset."""
        monkeypatch.setenv("RALPH_TASKS_API_KEY", "   ")
        client = TestClient(app, raise_server_exceptions=False)
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = client.get("/api/task/test/1")
        assert response.status_code == 404  # Not 401 -- auth disabled

    def test_mcp_root_path_protected(self, auth_client):
        """/mcp (without trailing slash) should also be protected."""
        response = auth_client.get("/mcp")
        assert response.status_code in (401, 307)  # 401 if no redirect, 307 if redirect


class TestUploadSizeLimit:
    """Tests for file upload size limit."""

    def test_small_file_accepted(self, client, monkeypatch):
        """A small file should be accepted."""
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "1")
        small_content = b"Hello, world!"

        with (
            patch("ralph_tasks.web.get_task") as mock_get,
            patch(
                "ralph_tasks.web.save_attachment",
                return_value={"name": "test.txt", "size": len(small_content)},
            ),
        ):
            mock_get.return_value = True  # Task exists
            response = client.post(
                "/api/task/test/1/attachments",
                files={"file": ("test.txt", io.BytesIO(small_content), "text/plain")},
            )
        assert response.status_code == 200

    def test_large_file_rejected_413(self, client, monkeypatch):
        """A file exceeding the limit should return 413."""
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "1")
        # Create content slightly over 1MB
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
        """Default max upload should be 50 MB."""
        monkeypatch.delenv("RALPH_TASKS_MAX_UPLOAD_MB", raising=False)
        from ralph_tasks.web import _get_max_upload_bytes

        assert _get_max_upload_bytes() == 50 * 1024 * 1024

    def test_invalid_max_upload_env_falls_back(self, monkeypatch):
        """Non-integer RALPH_TASKS_MAX_UPLOAD_MB should fall back to 50 MB."""
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "not-a-number")
        from ralph_tasks.web import _get_max_upload_bytes

        assert _get_max_upload_bytes() == 50 * 1024 * 1024

    def test_negative_max_upload_env_falls_back(self, monkeypatch):
        """Negative RALPH_TASKS_MAX_UPLOAD_MB should fall back to 50 MB."""
        monkeypatch.setenv("RALPH_TASKS_MAX_UPLOAD_MB", "-10")
        from ralph_tasks.web import _get_max_upload_bytes

        assert _get_max_upload_bytes() == 50 * 1024 * 1024
