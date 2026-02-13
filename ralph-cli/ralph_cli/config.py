"""Configuration loading with pydantic-settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ralph configuration loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=Path.home() / ".claude/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram notifications
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # Recovery settings
    recovery_enabled: bool = True
    recovery_delays: list[int] = Field(default=[600, 1200, 1800])
    context_overflow_max_retries: int = 2

    # Timeouts (in seconds)
    health_check_timeout: int = 60
    review_timeout: int = 1800  # 30 min

    # Codex review loop settings
    codex_review_max_iterations: int = 3
    codex_review_fix_timeout: int = 900  # 15 min per claude fix
    codex_review_model: str = "gpt-5.3-codex"

    # Paths
    log_dir: Path = Field(default=Path.home() / ".claude/logs")
    cli_dir: Path = Field(default=Path.home() / ".claude/cli")

    @property
    def telegram_configured(self) -> bool:
        """Check if Telegram notifications are configured."""
        return bool(self.telegram_bot_token and self.telegram_chat_id)


# Global settings instance (lazy loaded)
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset global settings instance (for testing)."""
    global _settings
    _settings = None
