"""Tests for prompt loading utility."""

import pytest
from ralph_cli.prompts import load_prompt


class TestLoadPrompt:
    """Tests for load_prompt function."""

    def test_loads_existing_prompt(self):
        text = load_prompt(
            "review-code-reviewer",
            task_ref="proj#1",
            project="proj",
            number="1",
            base_commit="abc123",
            review_type="code-review",
            author="code-reviewer",
        )
        assert "proj#1" in text
        assert "code-review" in text
        assert "abc123" in text
        assert "code-reviewer" in text

    def test_loads_without_substitution(self):
        text = load_prompt("review-code-reviewer")
        assert "{task_ref}" in text

    def test_raises_for_missing_prompt(self):
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            load_prompt("nonexistent")

    def test_substitution_replaces_all_vars(self):
        text = load_prompt(
            "fix-review-issues",
            task_ref="proj#5",
            project="proj",
            number="5",
            section_types="code-review, security-review",
        )
        assert "proj#5" in text
        assert "{task_ref}" not in text
        assert "code-review, security-review" in text

    def test_all_prompt_files_loadable(self):
        """All bundled prompt files should load without errors."""
        prompts = [
            "review-code-reviewer",
            "review-comment-analyzer",
            "review-test-analyzer",
            "review-silent-failure-hunter",
            "fix-review-issues",
            "code-simplifier",
            "security-reviewer",
            "codex-reviewer",
            "codex-plan-reviewer",
            "finalization",
        ]
        for name in prompts:
            text = load_prompt(name)
            assert len(text) > 0, f"Prompt {name} is empty"
