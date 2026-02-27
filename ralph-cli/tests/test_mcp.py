"""Tests for MCP role switching utilities."""

from unittest.mock import patch

import pytest
from ralph_cli.mcp import (
    _CODEX_URL_RE,
    McpRegistrationError,
    McpReviewerRole,
    McpRole,
    codex_mcp_role,
)


class TestMcpRoleUrl:
    def test_swe_url(self):
        assert McpRole.SWE.url() == "http://ai-sbx-ralph-tasks:8000/mcp-swe"

    def test_planner_url(self):
        assert McpRole.PLANNER.url() == "http://ai-sbx-ralph-tasks:8000/mcp-plan"

    def test_reviewer_url(self):
        role = McpReviewerRole("security-review")
        assert role.url() == "http://ai-sbx-ralph-tasks:8000/mcp-review?review_type=security-review"


class TestCodexUrlRegex:
    """Verify regex matches various URL formats in codex config.toml."""

    def test_matches_swe(self):
        line = 'url = "http://ai-sbx-ralph-tasks:8000/mcp-swe"'
        assert _CODEX_URL_RE.search(line)

    def test_matches_review_with_query(self):
        line = 'url = "http://ai-sbx-ralph-tasks:8000/mcp-review?review_type=codex-review"'
        assert _CODEX_URL_RE.search(line)

    def test_no_match_other_host(self):
        line = 'url = "http://other-host:8000/mcp-swe"'
        assert not _CODEX_URL_RE.search(line)


class TestCodexMcpRole:
    """Tests for codex config.toml patching (fail-closed)."""

    def test_patches_and_restores(self, tmp_path):
        config = tmp_path / "config.toml"
        original_content = (
            '[mcp_servers.ralph-tasks]\nurl = "http://ai-sbx-ralph-tasks:8000/mcp-swe"\n'
        )
        config.write_text(original_content)

        role = McpReviewerRole("codex-review")
        expected_url = "http://ai-sbx-ralph-tasks:8000/mcp-review?review_type=codex-review"

        with patch("ralph_cli.mcp._CODEX_CONFIG_PATH", config):
            with codex_mcp_role(role):
                patched = config.read_text()
                assert expected_url in patched
                assert "/mcp-swe" not in patched

        # After exit, original restored
        assert config.read_text() == original_content

    def test_restores_on_exception(self, tmp_path):
        config = tmp_path / "config.toml"
        original_content = (
            '[mcp_servers.ralph-tasks]\nurl = "http://ai-sbx-ralph-tasks:8000/mcp-swe"\n'
        )
        config.write_text(original_content)

        role = McpReviewerRole("codex-review")

        with patch("ralph_cli.mcp._CODEX_CONFIG_PATH", config):
            with pytest.raises(RuntimeError):
                with codex_mcp_role(role):
                    raise RuntimeError("boom")

        assert config.read_text() == original_content

    def test_raises_when_config_missing(self, tmp_path):
        config = tmp_path / "nonexistent" / "config.toml"

        with patch("ralph_cli.mcp._CODEX_CONFIG_PATH", config):
            with pytest.raises(McpRegistrationError, match="config not found"):
                with codex_mcp_role(McpReviewerRole("codex-review")):
                    pass

    def test_raises_when_url_not_found(self, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text('[mcp_servers.other]\nurl = "http://other:8000"\n')

        with patch("ralph_cli.mcp._CODEX_CONFIG_PATH", config):
            with pytest.raises(McpRegistrationError, match="URL not found"):
                with codex_mcp_role(McpReviewerRole("codex-review")):
                    pass

    def test_preserves_other_sections(self, tmp_path):
        config = tmp_path / "config.toml"
        original_content = (
            'profile = "default"\n'
            "\n"
            "[profiles.default]\n"
            'model = "gpt-5.3-codex"\n'
            "\n"
            "[mcp_servers.ralph-tasks]\n"
            'url = "http://ai-sbx-ralph-tasks:8000/mcp-swe"\n'
            "\n"
            "[mcp_servers.playwright]\n"
            'command = "playwright-mcp"\n'
        )
        config.write_text(original_content)

        with patch("ralph_cli.mcp._CODEX_CONFIG_PATH", config):
            with codex_mcp_role(McpReviewerRole("codex-review")):
                patched = config.read_text()
                # ralph-tasks URL changed
                assert "mcp-review?review_type=codex-review" in patched
                # Other sections preserved
                assert 'profile = "default"' in patched
                assert 'model = "gpt-5.3-codex"' in patched
                assert 'command = "playwright-mcp"' in patched
