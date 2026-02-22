"""Prompt loading utility for CLI agents."""

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent

# Installed (wheel with force-include) → ralph_cli/_prompts/
# Development (uv run from source) → ralph-cli/prompts/
_PROMPTS_DIR = _PACKAGE_DIR / "_prompts"
if not _PROMPTS_DIR.exists():
    _PROMPTS_DIR = _PACKAGE_DIR.parent / "prompts"


def load_prompt(name: str, **kwargs: str) -> str:
    """Load prompt from .md file and substitute variables.

    Args:
        name: Prompt file name without extension (e.g., 'code-reviewer')
        **kwargs: Variables to substitute via str.format()

    Returns:
        Prompt text with variables substituted.

    Raises:
        FileNotFoundError: If prompt file doesn't exist.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    text = path.read_text()
    if kwargs:
        text = text.format(**kwargs)
    return text
