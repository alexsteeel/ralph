"""Tests for combined ASGI app: web UI + MCP mount + health endpoint."""

from unittest.mock import patch

import pytest
from ralph_tasks.web import app
from starlette.applications import Starlette
from starlette.testclient import TestClient


@pytest.fixture
def client():
    """TestClient for the FastAPI app."""
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

    def test_settings_api(self, client):
        response = client.get("/api/settings")
        assert response.status_code == 200
        assert response.json() == {}

    def test_task_api_404(self, client):
        """Non-existent task should 404 (mocking Neo4j)."""
        with patch("ralph_tasks.web.get_task", return_value=None):
            response = client.get("/api/task/nonexistent/999")
        assert response.status_code == 404


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
