"""Tests for core.py with Neo4j backend."""

import logging
from unittest.mock import patch

import pytest
from ralph_tasks import core
from ralph_tasks.core import SearchResult, _make_snippets, normalize_project_name
from ralph_tasks.graph import crud
from ralph_tasks.graph.schema import ensure_schema


@pytest.fixture
def graph_core(neo4j_client, tmp_path, monkeypatch):
    """Setup core module to use test Neo4j instance and temp attachment dir."""
    # Reset singleton
    core.reset_client()

    # Monkeypatch to use test client
    monkeypatch.setattr(core, "_client", neo4j_client)
    monkeypatch.setattr(core, "_schema_initialized", False)
    monkeypatch.setattr(core, "BASE_DIR", tmp_path)

    # Ensure schema is ready
    ensure_schema(neo4j_client)

    # Create default workspace
    with neo4j_client.session() as session:
        ws = crud.get_workspace(session, core.DEFAULT_WORKSPACE)
        if ws is None:
            crud.create_workspace(session, core.DEFAULT_WORKSPACE)
    monkeypatch.setattr(core, "_schema_initialized", True)

    yield neo4j_client

    # Cleanup: reset singleton but don't close (neo4j_client fixture does that)
    core._client = None
    core._schema_initialized = False


@pytest.mark.neo4j
class TestListProjects:
    def test_list_projects_empty(self, graph_core):
        assert core.list_projects() == []

    def test_create_project_and_list(self, graph_core):
        core.create_project("alpha")
        core.create_project("beta")
        projects = core.list_projects()
        assert "alpha" in projects
        assert "beta" in projects


@pytest.mark.neo4j
class TestProjectExists:
    def test_project_exists(self, graph_core):
        assert core.project_exists("nonexistent") is False
        core.create_project("myproj")
        assert core.project_exists("myproj") is True


@pytest.mark.neo4j
class TestProjectDescription:
    def test_get_set_description(self, graph_core):
        core.create_project("proj", "Initial desc")
        assert core.get_project_description("proj") == "Initial desc"
        core.set_project_description("proj", "Updated desc")
        assert core.get_project_description("proj") == "Updated desc"

    def test_set_description_creates_project(self, graph_core):
        core.set_project_description("new-proj", "Created via set")
        assert core.project_exists("new-proj")
        assert core.get_project_description("new-proj") == "Created via set"


@pytest.mark.neo4j
class TestCreateTask:
    def test_create_task_auto_number(self, graph_core):
        task1 = core.create_task("proj", "First task")
        task2 = core.create_task("proj", "Second task")
        assert task1.number == 1
        assert task2.number == 2

    def test_create_task_auto_creates_project(self, graph_core):
        task = core.create_task("new-proj", "Task in new project")
        assert task.number == 1
        assert core.project_exists("new-proj")

    def test_create_task_with_description_and_plan(self, graph_core):
        task = core.create_task(
            "proj", "Task with sections", description="The description", plan="The plan"
        )
        assert task.description == "The description"
        assert task.plan == "The plan"

    def test_create_task_with_fields(self, graph_core):
        task = core.create_task(
            "proj",
            "Full task",
            description="desc",
            plan="plan",
            status="work",
            module="auth",
            branch="feature/auth",
            started="2026-01-15 10:00",
        )
        assert task.status == "work"
        assert task.module == "auth"
        assert task.branch == "feature/auth"
        assert task.started == "2026-01-15 10:00"


@pytest.mark.neo4j
class TestGetTask:
    def test_get_task_with_sections(self, graph_core):
        core.create_task("proj", "Task", description="Body text", plan="Plan text")
        task = core.get_task("proj", 1)
        assert task is not None
        assert task.title == "Task"
        assert task.description == "Body text"
        assert task.plan == "Plan text"

    def test_get_task_not_found(self, graph_core):
        core.create_project("proj")
        assert core.get_task("proj", 999) is None


@pytest.mark.neo4j
class TestListTasks:
    def test_list_tasks_includes_sections(self, graph_core):
        core.create_task("proj", "Task A", description="Body A")
        core.create_task("proj", "Task B", description="Body B")
        tasks = core.list_tasks("proj")
        assert len(tasks) == 2
        assert tasks[0].number == 1
        assert tasks[1].number == 2
        # list_tasks now includes section content
        assert tasks[0].description == "Body A"
        assert tasks[1].description == "Body B"


@pytest.mark.neo4j
class TestUpdateTask:
    def test_update_task_fields(self, graph_core):
        core.create_task("proj", "Task")
        updated = core.update_task("proj", 1, title="Updated", module="api")
        assert updated.title == "Updated"
        assert updated.module == "api"

    def test_update_task_sections(self, graph_core):
        core.create_task("proj", "Task")
        updated = core.update_task(
            "proj",
            1,
            description="New description",
            plan="New plan",
            report="Report",
            blocks="Blocked",
        )
        assert updated.description == "New description"
        assert updated.plan == "New plan"
        assert updated.report == "Report"
        assert updated.blocks == "Blocked"

    def test_update_task_auto_started(self, graph_core):
        core.create_task("proj", "Task")
        updated = core.update_task("proj", 1, status="work")
        assert updated.status == "work"
        assert updated.started is not None

    def test_update_task_auto_completed(self, graph_core):
        core.create_task("proj", "Task", status="work")
        updated = core.update_task("proj", 1, status="done")
        assert updated.status == "done"
        assert updated.completed is not None

    def test_update_task_no_auto_started_if_already_set(self, graph_core):
        core.create_task("proj", "Task", started="2026-01-01 09:00")
        updated = core.update_task("proj", 1, status="work")
        assert updated.started == "2026-01-01 09:00"

    def test_update_task_depends_on(self, graph_core):
        core.create_task("proj", "Task 1")
        core.create_task("proj", "Task 2")
        core.create_task("proj", "Task 3")
        updated = core.update_task("proj", 3, depends_on=[1, 2])
        assert updated.depends_on == [1, 2]

    def test_update_task_not_found_raises(self, graph_core):
        core.create_project("proj")
        with pytest.raises(ValueError, match="not found"):
            core.update_task("proj", 999, title="Nope")

    def test_update_task_invalid_status_raises(self, graph_core):
        core.create_task("proj", "Task")
        with pytest.raises(ValueError, match="Invalid status"):
            core.update_task("proj", 1, status="invalid")

    def test_update_clear_section(self, graph_core):
        core.create_task("proj", "Task", description="Some description")
        updated = core.update_task("proj", 1, description="")
        assert updated.description == ""


@pytest.mark.neo4j
class TestDeleteTask:
    def test_delete_task(self, graph_core):
        core.create_task("proj", "Task")
        assert core.delete_task("proj", 1) is True
        assert core.get_task("proj", 1) is None

    @pytest.mark.minio
    def test_delete_task_with_attachments(self, graph_core, minio_storage):
        core.create_task("proj", "Task")
        core.save_attachment("proj", 1, "test.txt", b"data")
        assert core.list_attachments("proj", 1) != []

        assert core.delete_task("proj", 1) is True

        from ralph_tasks import storage

        assert storage.list_objects("proj", 1) == []


@pytest.mark.neo4j
class TestModuleAndBranch:
    def test_create_with_module_and_branch(self, graph_core):
        task = core.create_task("proj", "Task", module="auth", branch="feat/auth")
        assert task.module == "auth"
        assert task.branch == "feat/auth"

    def test_update_module_and_branch(self, graph_core):
        core.create_task("proj", "Task")
        updated = core.update_task("proj", 1, module="api", branch="feat/api")
        assert updated.module == "api"
        assert updated.branch == "feat/api"


@pytest.mark.neo4j
class TestToDict:
    def test_to_dict_fields(self, graph_core):
        task = core.create_task("proj", "Task", description="Desc", plan="Plan")
        d = task.to_dict()
        assert d["number"] == 1
        assert d["title"] == "Task"
        assert d["description"] == "Desc"
        assert d["plan"] == "Plan"
        assert d["status"] == "todo"
        assert "mtime" in d
        assert isinstance(d["mtime"], float)
        assert d["depends_on"] == []

    def test_to_dict_mtime_from_updated_at(self, graph_core):
        task = core.create_task("proj", "Task")
        d = task.to_dict()
        # updated_at is set by Neo4j, so mtime should be > 0
        assert d["mtime"] > 0


@pytest.mark.neo4j
class TestUpdatedAtSorting:
    def test_tasks_have_updated_at(self, graph_core):
        core.create_task("proj", "First")
        core.create_task("proj", "Second")
        tasks = core.list_tasks("proj")
        for t in tasks:
            assert t.updated_at != ""

    def test_updated_at_changes_on_update(self, graph_core):
        core.create_task("proj", "Task")
        task_before = core.get_task("proj", 1)
        core.update_task("proj", 1, title="Updated")
        task_after = core.get_task("proj", 1)
        # updated_at should be >= before (might be same if very fast)
        assert task_after.updated_at >= task_before.updated_at


# ---------------------------------------------------------------------------
# Project name normalization
# ---------------------------------------------------------------------------


class TestNormalizeProjectName:
    """Unit tests for normalize_project_name (no Neo4j required)."""

    def test_underscores_to_hyphens(self):
        assert normalize_project_name("face_recognition") == "face-recognition"

    def test_already_canonical(self):
        assert normalize_project_name("already-canonical") == "already-canonical"

    def test_strips_whitespace(self):
        assert normalize_project_name("  spaces  ") == "spaces"

    def test_mixed_separators(self):
        assert (
            normalize_project_name("mixed_dashes-and_underscores") == "mixed-dashes-and-underscores"
        )

    def test_empty_string(self):
        assert normalize_project_name("") == ""

    def test_only_underscores(self):
        assert normalize_project_name("___") == "---"

    def test_no_separators(self):
        assert normalize_project_name("simple") == "simple"


@pytest.mark.neo4j
class TestNormalizationIntegration:
    """Integration tests for project name normalization with Neo4j."""

    def test_create_with_underscore_access_with_hyphen(self, graph_core):
        """Creating a task with underscore should be accessible via hyphen."""
        core.create_task("test_proj", "Task via underscore")
        task = core.get_task("test-proj", 1)
        assert task is not None
        assert task.title == "Task via underscore"

    def test_create_with_hyphen_access_with_underscore(self, graph_core):
        """Creating a task with hyphen should be accessible via underscore."""
        core.create_task("test-proj", "Task via hyphen")
        task = core.get_task("test_proj", 1)
        assert task is not None
        assert task.title == "Task via hyphen"

    def test_list_projects_returns_canonical(self, graph_core):
        """list_projects should return canonical (hyphenated) names."""
        core.create_project("my_project")
        projects = core.list_projects()
        assert "my-project" in projects
        assert "my_project" not in projects

    def test_list_tasks_with_underscore(self, graph_core):
        """list_tasks should work with underscore variant."""
        core.create_task("my-proj", "Task 1")
        tasks = core.list_tasks("my_proj")
        assert len(tasks) == 1
        assert tasks[0].title == "Task 1"

    def test_update_task_with_underscore(self, graph_core):
        """update_task should work with underscore variant."""
        core.create_task("my-proj", "Task")
        updated = core.update_task("my_proj", 1, title="Updated")
        assert updated.title == "Updated"

    def test_delete_task_with_underscore(self, graph_core):
        """delete_task should work with underscore variant."""
        core.create_task("my-proj", "Task")
        assert core.delete_task("my_proj", 1) is True
        assert core.get_task("my-proj", 1) is None

    def test_project_exists_with_underscore(self, graph_core):
        """project_exists should resolve underscore to hyphen."""
        core.create_project("my-proj")
        assert core.project_exists("my_proj") is True

    def test_no_duplicate_projects(self, graph_core):
        """Creating project with both variants should not create duplicates."""
        core.create_project("my_proj")
        core.create_project("my-proj")  # should be a no-op
        projects = core.list_projects()
        assert projects.count("my-proj") == 1


@pytest.mark.neo4j
class TestProjectNameMigration:
    """Tests for automatic project name migration at startup."""

    def test_migration_renames_underscore_project(self, graph_core):
        """Projects created with underscores via crud should be migrated."""
        with graph_core.session() as session:
            crud.create_project(session, core.DEFAULT_WORKSPACE, "old_project")

        # Force re-migration (mock MinIO to avoid S3 connection errors)
        with patch("ralph_tasks.core.storage.migrate_project_prefix", return_value=0):
            with graph_core.session() as session:
                core._migrate_project_names(session)

        # Should now exist under canonical name
        assert core.project_exists("old-project") is True

    def test_migration_skips_conflict(self, graph_core, caplog):
        """Migration should skip when canonical name already exists."""
        with graph_core.session() as session:
            crud.create_project(session, core.DEFAULT_WORKSPACE, "conflict_proj")
            crud.create_project(session, core.DEFAULT_WORKSPACE, "conflict-proj")

        with caplog.at_level(logging.WARNING, logger="md-task-mcp"):
            with graph_core.session() as session:
                core._migrate_project_names(session)

        assert "Manual merge required" in caplog.text
        # Both should still exist
        with graph_core.session() as session:
            old = crud.get_project(session, core.DEFAULT_WORKSPACE, "conflict_proj")
            new = crud.get_project(session, core.DEFAULT_WORKSPACE, "conflict-proj")
            assert old is not None
            assert new is not None

    def test_migration_noop_for_canonical_names(self, graph_core):
        """Migration should do nothing for already-canonical names."""
        core.create_project("already-good")
        with graph_core.session() as session:
            core._migrate_project_names(session)
        assert core.project_exists("already-good") is True


@pytest.mark.neo4j
class TestReviewFindings:
    """Tests for structured review findings via core API."""

    def test_add_finding_basic(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding("proj", 1, "code-review", "Bug here", "reviewer-1")
        assert finding["text"] == "Bug here"
        assert finding["author"] == "reviewer-1"
        assert finding["status"] == "open"

    def test_add_finding_with_file(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding(
            "proj",
            1,
            "code-review",
            "Issue",
            "reviewer-1",
            file="src/main.py",
            line_start=10,
            line_end=20,
        )
        assert finding["file"] == "src/main.py"
        assert finding["line_start"] == 10
        assert finding["line_end"] == 20

    def test_list_findings_empty(self, graph_core):
        core.create_task("proj", "Task")
        findings = core.list_review_findings("proj", 1)
        assert findings == []

    def test_list_findings_with_type_filter(self, graph_core):
        core.create_task("proj", "Task")
        core.add_review_finding("proj", 1, "code-review", "Code issue", "r1")
        core.add_review_finding("proj", 1, "security", "Sec issue", "r2")

        code_findings = core.list_review_findings("proj", 1, review_type="code-review")
        sec_findings = core.list_review_findings("proj", 1, review_type="security")
        all_findings = core.list_review_findings("proj", 1)

        assert len(code_findings) == 1
        assert len(sec_findings) == 1
        assert len(all_findings) == 2

    def test_list_findings_with_status_filter(self, graph_core):
        core.create_task("proj", "Task")
        f1 = core.add_review_finding("proj", 1, "code-review", "Issue 1", "r1")
        core.add_review_finding("proj", 1, "code-review", "Issue 2", "r1")
        core.resolve_finding(f1["element_id"])

        open_findings = core.list_review_findings("proj", 1, status="open")
        resolved_findings = core.list_review_findings("proj", 1, status="resolved")

        assert len(open_findings) == 1
        assert len(resolved_findings) == 1

    def test_reply_to_finding(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding("proj", 1, "code-review", "Bug", "r1")
        comment = core.reply_to_finding(finding["element_id"], "Fixed it", "dev-1")
        assert comment["text"] == "Fixed it"
        assert comment["author"] == "dev-1"

    def test_resolve_finding(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding("proj", 1, "code-review", "Bug", "r1")
        resolved = core.resolve_finding(finding["element_id"], response="Done")
        assert resolved["status"] == "resolved"
        assert resolved["response"] == "Done"

    def test_resolve_finding_no_response(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding("proj", 1, "code-review", "Bug", "r1")
        resolved = core.resolve_finding(finding["element_id"])
        assert resolved["status"] == "resolved"

    def test_decline_finding(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding("proj", 1, "code-review", "Bug", "r1")
        declined = core.decline_finding(finding["element_id"], reason="Not a bug")
        assert declined["status"] == "declined"
        assert declined["decline_reason"] == "Not a bug"

    def test_decline_finding_without_reason_raises(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding("proj", 1, "code-review", "Bug", "r1")
        with pytest.raises(ValueError, match="reason is required"):
            core.decline_finding(finding["element_id"], reason="")

    def test_findings_with_comments_thread(self, graph_core):
        core.create_task("proj", "Task")
        finding = core.add_review_finding("proj", 1, "code-review", "Bug", "r1")
        core.reply_to_finding(finding["element_id"], "Comment 1", "dev-1")
        core.reply_to_finding(finding["element_id"], "Comment 2", "dev-2")

        findings = core.list_review_findings("proj", 1)
        assert len(findings) == 1
        assert len(findings[0]["comments"]) == 2

    def test_project_name_normalization(self, graph_core):
        """Findings work with underscore project names."""
        core.create_task("my-proj", "Task")
        core.add_review_finding("my_proj", 1, "code-review", "Bug", "r1")
        findings = core.list_review_findings("my_proj", 1)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# _make_snippets (unit tests, no Neo4j)
# ---------------------------------------------------------------------------


class TestMakeSnippets:
    """Unit tests for _make_snippets helper — no Neo4j required."""

    def test_single_keyword_match(self):
        text = "The quick brown fox jumps over the lazy dog"
        result = _make_snippets(text, ["fox"])
        assert "fox" in result

    def test_multiple_keywords(self):
        text = "a" * 200 + " postgres " + "b" * 200 + " observability " + "c" * 200
        result = _make_snippets(text, ["postgres", "observability"])
        assert "postgres" in result
        assert "observability" in result

    def test_case_insensitive(self):
        text = "PostgreSQL is a database"
        result = _make_snippets(text, ["postgresql"])
        assert "PostgreSQL" in result

    def test_no_match_returns_empty(self):
        text = "Hello world"
        result = _make_snippets(text, ["missing"])
        assert result == ""

    def test_empty_text_returns_empty(self):
        assert _make_snippets("", ["kw"]) == ""

    def test_empty_keywords_returns_empty(self):
        assert _make_snippets("some text", []) == ""

    def test_ellipsis_at_start(self):
        text = "x" * 100 + " keyword here"
        result = _make_snippets(text, ["keyword"])
        assert result.startswith("...")

    def test_ellipsis_at_end(self):
        text = "keyword here " + "x" * 100
        result = _make_snippets(text, ["keyword"])
        assert result.endswith("...")

    def test_no_ellipsis_at_start(self):
        """No leading ellipsis when keyword is at the very beginning."""
        text = "keyword at start"
        result = _make_snippets(text, ["keyword"])
        assert not result.startswith("...")

    def test_no_ellipsis_at_end(self):
        """No trailing ellipsis when keyword is at the very end."""
        text = "ends with keyword"
        result = _make_snippets(text, ["keyword"])
        assert not result.endswith("...")

    def test_overlapping_snippets_deduplicated(self):
        """Close keywords produce a single snippet, not two."""
        text = "aaa foo bbb bar ccc"
        result = _make_snippets(text, ["foo", "bar"])
        # foo at pos 4, bar at pos 12 — within window, only one snippet
        assert "|" not in result
        assert "foo" in result

    def test_distant_keywords_produce_separate_snippets(self):
        """Keywords far apart produce separate snippets joined by ' | '."""
        text = "a" * 200 + " alpha " + "b" * 200 + " beta " + "c" * 200
        result = _make_snippets(text, ["alpha", "beta"])
        assert " | " in result
        assert "alpha" in result
        assert "beta" in result


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


class TestSearchResult:
    """Unit tests for SearchResult dataclass — no Neo4j required."""

    def test_to_dict(self):
        sr = SearchResult(number=1, title="Task", status="todo", snippet="...match...")
        d = sr.to_dict()
        assert d == {
            "number": 1,
            "title": "Task",
            "status": "todo",
            "snippet": "...match...",
        }

    def test_to_dict_with_module(self):
        sr = SearchResult(number=1, title="Task", status="todo", snippet="...", module="auth")
        d = sr.to_dict()
        assert d["module"] == "auth"

    def test_to_dict_without_module(self):
        sr = SearchResult(number=1, title="Task", status="todo", snippet="...")
        d = sr.to_dict()
        assert "module" not in d


# ---------------------------------------------------------------------------
# search_tasks (integration, requires Neo4j)
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
class TestSearchTasks:
    def test_search_by_title(self, graph_core):
        core.create_task("proj", "Add PostgreSQL support")
        core.create_task("proj", "Fix login bug")
        results = core.search_tasks("proj", "postgresql")
        assert len(results) == 1
        assert results[0].number == 1

    def test_search_by_description(self, graph_core):
        core.create_task("proj", "Task one", description="Contains keyword foobar in body")
        core.create_task("proj", "Task two", description="Nothing special here")
        results = core.search_tasks("proj", "foobar")
        assert len(results) == 1
        assert results[0].number == 1

    def test_search_by_plan(self, graph_core):
        core.create_task("proj", "Task", plan="Use OpenSearch for indexing")
        results = core.search_tasks("proj", "opensearch")
        assert len(results) == 1

    def test_search_and_logic(self, graph_core):
        core.create_task("proj", "PostgreSQL monitoring", description="Add metrics dashboard")
        core.create_task("proj", "PostgreSQL backup", description="Cron job setup")
        results = core.search_tasks("proj", "postgresql dashboard")
        assert len(results) == 1
        assert results[0].number == 1

    def test_search_filter_by_status(self, graph_core):
        core.create_task("proj", "Done task", status="done", description="keyword")
        core.create_task("proj", "Todo task", description="keyword")
        results = core.search_tasks("proj", "keyword", status="todo")
        assert len(results) == 1
        assert results[0].status == "todo"

    def test_search_filter_by_module(self, graph_core):
        core.create_task("proj", "Auth task", module="auth", description="important keyword")
        core.create_task("proj", "API task", module="api", description="important keyword")
        results = core.search_tasks("proj", "keyword", module="auth")
        assert len(results) == 1
        assert results[0].number == 1

    def test_search_empty_query(self, graph_core):
        core.create_task("proj", "Some task")
        results = core.search_tasks("proj", "")
        assert results == []

    def test_search_no_matches(self, graph_core):
        core.create_task("proj", "Some task")
        results = core.search_tasks("proj", "nonexistent")
        assert results == []

    def test_search_returns_snippet(self, graph_core):
        core.create_task("proj", "Task", description="The quick brown fox jumps over lazy dog")
        results = core.search_tasks("proj", "fox")
        assert len(results) == 1
        assert "fox" in results[0].snippet

    def test_search_project_name_normalization(self, graph_core):
        core.create_task("my-proj", "Task", description="contains keyword")
        results = core.search_tasks("my_proj", "keyword")
        assert len(results) == 1
