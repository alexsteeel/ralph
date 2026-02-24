"""Tests for configuration loading."""

from ralph_cli.config import Settings


class TestSettings:
    """Tests for Settings class."""

    def test_defaults(self):
        """Test default configuration values."""
        # Create settings without any env vars
        settings = Settings(
            _env_file=None,  # Don't load from file
        )

        assert settings.telegram_bot_token is None
        assert settings.telegram_chat_id is None
        assert settings.recovery_enabled is True
        assert settings.recovery_delays == [3600, 7200, 10800]
        assert settings.context_overflow_max_retries == 2
        assert settings.ralph_tasks_api_url is None
        assert settings.ralph_tasks_api_key is None

    def test_telegram_configured_false(self):
        """Test telegram_configured when not configured."""
        settings = Settings(_env_file=None)
        assert not settings.telegram_configured

    def test_telegram_configured_partial(self):
        """Test telegram_configured with only token."""
        settings = Settings(
            _env_file=None,
            telegram_bot_token="token",
        )
        assert not settings.telegram_configured

    def test_telegram_configured_true(self):
        """Test telegram_configured when both values set."""
        settings = Settings(
            _env_file=None,
            telegram_bot_token="token",
            telegram_chat_id="chat",
        )
        assert settings.telegram_configured

    def test_load_from_env_file(self, temp_dir):
        """Test loading configuration from .env file."""
        env_file = temp_dir / ".env"
        env_file.write_text("""
TELEGRAM_BOT_TOKEN=test_token_123
TELEGRAM_CHAT_ID=test_chat_456
RECOVERY_ENABLED=true
RECOVERY_DELAYS=[60,120,180]
CONTEXT_OVERFLOW_MAX_RETRIES=3
""")
        settings = Settings(_env_file=env_file)

        assert settings.telegram_bot_token == "test_token_123"
        assert settings.telegram_chat_id == "test_chat_456"
        assert settings.recovery_enabled is True
        assert settings.recovery_delays == [60, 120, 180]
        assert settings.context_overflow_max_retries == 3

    def test_load_recovery_disabled(self, temp_dir):
        """Test loading with recovery disabled."""
        env_file = temp_dir / ".env"
        env_file.write_text("RECOVERY_ENABLED=false")

        settings = Settings(_env_file=env_file)
        assert settings.recovery_enabled is False

    def test_custom_paths(self, temp_dir):
        """Test setting custom paths."""
        settings = Settings(
            _env_file=None,
            log_dir=temp_dir / "logs",
        )
        assert settings.log_dir == temp_dir / "logs"

    def test_from_env_vars(self, monkeypatch):
        """Test loading from environment variables."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "env_chat")
        monkeypatch.setenv("CONTEXT_OVERFLOW_MAX_RETRIES", "5")

        settings = Settings(_env_file=None)

        assert settings.telegram_bot_token == "env_token"
        assert settings.telegram_chat_id == "env_chat"
        assert settings.context_overflow_max_retries == 5
