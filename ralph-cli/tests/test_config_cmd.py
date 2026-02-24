"""Tests for ralph config command."""

import json
from unittest.mock import patch

from ralph_cli.cli import app
from ralph_cli.config import Settings
from typer.testing import CliRunner

runner = CliRunner()


def _mock_settings(**overrides):
    """Create isolated Settings with no env file."""
    return Settings(_env_file=None, **overrides)


def _run_config_with(settings, *args):
    """Run `ralph config` with specific settings."""
    with patch("ralph_cli.commands.config_cmd.get_settings", return_value=settings):
        return runner.invoke(app, ["config", *args])


def _run_config(*args):
    """Run `ralph config` with default (isolated) settings."""
    return _run_config_with(_mock_settings(), *args)


class TestConfigAll:
    """Tests for `ralph config` (full output)."""

    def test_config_all_shows_key_fields(self):
        """Full output contains key config fields."""
        result = _run_config()
        assert result.exit_code == 0
        assert "recovery_enabled:" in result.output
        assert "log_dir:" in result.output
        assert "Ralph CLI Configuration" in result.output

    def test_config_all_shows_sections(self):
        """Full output has section headers."""
        result = _run_config()
        assert result.exit_code == 0
        assert "Telegram" in result.output
        assert "Recovery" in result.output
        assert "Paths" in result.output


class TestConfigJson:
    """Tests for `ralph config --json`."""

    def test_config_json_valid(self):
        """--json produces valid JSON with representative keys."""
        result = _run_config("--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "recovery_enabled" in data
        assert "log_dir" in data
        assert isinstance(data["log_dir"], str)
        assert "telegram_configured" in data

    def test_config_json_masks_token(self):
        """Secrets are masked in JSON output."""
        settings = _mock_settings(telegram_bot_token="my_secret_token_abc")
        result = _run_config_with(settings, "--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "****" in data["telegram_bot_token"]
        assert "my_secret_token_abc" not in data["telegram_bot_token"]


class TestConfigKey:
    """Tests for `ralph config <key>`."""

    def test_config_key_value(self):
        """`ralph config recovery_enabled` prints the value."""
        result = _run_config("recovery_enabled")
        assert result.exit_code == 0
        assert result.output.strip() == "true"

    def test_config_key_not_found(self):
        """Unknown key returns exit code 1 with error message."""
        result = _run_config("nonexistent_key")
        assert result.exit_code == 1
        # Typer CliRunner mixes stderr into output
        assert "Unknown config key" in result.output

    def test_config_key_json(self):
        """`ralph config recovery_enabled --json` returns JSON."""
        result = _run_config("recovery_enabled", "--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"recovery_enabled": True}

    def test_config_key_list_value(self):
        """List values are formatted as comma-separated."""
        result = _run_config("recovery_delays")
        assert result.exit_code == 0
        assert "3600" in result.output.strip()

    def test_config_key_none_value(self):
        """None values display as '(not set)'."""
        result = _run_config("telegram_bot_token")
        assert result.exit_code == 0
        assert "(not set)" in result.output

    def test_config_key_computed_property(self):
        """`ralph config telegram_configured` returns computed property value."""
        result = _run_config("telegram_configured")
        assert result.exit_code == 0
        assert result.output.strip() == "false"

    def test_config_key_false_boolean(self):
        """Boolean False is formatted as 'false'."""
        settings = _mock_settings(recovery_enabled=False)
        result = _run_config_with(settings, "recovery_enabled")
        assert result.exit_code == 0
        assert result.output.strip() == "false"

    def test_config_key_secret_json(self):
        """Secret key with --json returns masked value."""
        settings = _mock_settings(telegram_bot_token="my_super_secret_token")
        result = _run_config_with(settings, "telegram_bot_token", "--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "****" in data["telegram_bot_token"]
        assert "my_super_secret_token" not in json.dumps(data)


class TestConfigMasking:
    """Tests for secret masking."""

    def test_masks_token_in_full_output(self):
        """telegram_bot_token is masked in full output."""
        settings = _mock_settings(telegram_bot_token="secret_token_value")
        result = _run_config_with(settings)
        assert result.exit_code == 0
        assert "****" in result.output
        assert "secret_token_value" not in result.output

    def test_masks_api_key(self):
        """ralph_tasks_api_key is masked."""
        settings = _mock_settings(ralph_tasks_api_key="super_secret_key_xyz")
        result = _run_config_with(settings, "--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "****" in data["ralph_tasks_api_key"]
        assert "super_secret_key_xyz" not in json.dumps(data)

    def test_mask_shows_last_3_chars(self):
        """Masked value shows last 3 characters."""
        settings = _mock_settings(telegram_bot_token="abcdef123")
        result = _run_config_with(settings, "telegram_bot_token")
        assert result.exit_code == 0
        assert "****123" in result.output

    def test_masks_api_key_full_output(self):
        """ralph_tasks_api_key is masked in full (non-JSON) output."""
        settings = _mock_settings(ralph_tasks_api_key="super_secret_key_xyz")
        result = _run_config_with(settings)
        assert result.exit_code == 0
        assert "****xyz" in result.output
        assert "super_secret_key_xyz" not in result.output

    def test_mask_short_value(self):
        """Short secrets are fully masked."""
        settings = _mock_settings(telegram_bot_token="ab")
        result = _run_config_with(settings, "telegram_bot_token")
        assert result.exit_code == 0
        assert "****" in result.output
        assert "ab" not in result.output

    def test_config_key_secret_no_raw_leak(self):
        """Single-key lookup of secret does not leak raw value."""
        settings = _mock_settings(telegram_bot_token="super_secret_abc")
        result = _run_config_with(settings, "telegram_bot_token")
        assert result.exit_code == 0
        assert "super_secret_abc" not in result.output
        assert "****abc" in result.output


class TestConfigValidation:
    """Tests for configuration error handling."""

    def test_config_invalid_env_shows_error(self):
        """Invalid config values produce a user-friendly error, not a traceback."""
        with patch("ralph_cli.commands.config_cmd.get_settings", side_effect=_validation_error()):
            result = runner.invoke(app, ["config"])
        assert result.exit_code == 1
        # Typer CliRunner mixes stderr into output
        assert "validation failed" in result.output.lower()


def _validation_error():
    """Create a ValidationError for testing."""
    from pydantic import ValidationError

    try:
        Settings(_env_file=None, health_check_timeout="not_a_number")  # type: ignore[arg-type]
    except ValidationError as e:
        return e
    raise AssertionError("Expected ValidationError")
