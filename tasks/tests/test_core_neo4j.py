"""Tests for core.py with Neo4j backend."""

import logging

import pytest
from ralph_tasks import core
from ralph_tasks.core import normalize_project_name
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

    def test_create_task_with_body_and_plan(self, graph_core):
        task = core.create_task("proj", "Task with sections", body="The body", plan="The plan")
        assert task.body == "The body"
        assert task.plan == "The plan"

    def test_create_task_with_fields(self, graph_core):
        task = core.create_task(
            "proj",
            "Full task",
            body="desc",
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
        core.create_task("proj", "Task", body="Body text", plan="Plan text")
        task = core.get_task("proj", 1)
        assert task is not None
        assert task.description == "Task"
        assert task.body == "Body text"
        assert task.plan == "Plan text"

    def test_get_task_not_found(self, graph_core):
        core.create_project("proj")
        assert core.get_task("proj", 999) is None


@pytest.mark.neo4j
class TestListTasks:
    def test_list_tasks_no_sections(self, graph_core):
        core.create_task("proj", "Task A", body="Body A")
        core.create_task("proj", "Task B", body="Body B")
        tasks = core.list_tasks("proj")
        assert len(tasks) == 2
        assert tasks[0].number == 1
        assert tasks[1].number == 2
        # Summary mode — no section content
        assert tasks[0].body == ""
        assert tasks[1].body == ""


@pytest.mark.neo4j
class TestUpdateTask:
    def test_update_task_fields(self, graph_core):
        core.create_task("proj", "Task")
        updated = core.update_task("proj", 1, description="Updated", module="api")
        assert updated.description == "Updated"
        assert updated.module == "api"

    def test_update_task_sections(self, graph_core):
        core.create_task("proj", "Task")
        updated = core.update_task(
            "proj",
            1,
            body="New body",
            plan="New plan",
            report="Report",
            review="Review",
            blocks="Blocked",
        )
        assert updated.body == "New body"
        assert updated.plan == "New plan"
        assert updated.report == "Report"
        assert updated.review == "Review"
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
            core.update_task("proj", 999, description="Nope")

    def test_update_task_invalid_status_raises(self, graph_core):
        core.create_task("proj", "Task")
        with pytest.raises(ValueError, match="Invalid status"):
            core.update_task("proj", 1, status="invalid")

    def test_update_clear_section(self, graph_core):
        core.create_task("proj", "Task", body="Some body")
        updated = core.update_task("proj", 1, body="")
        assert updated.body == ""


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
        task = core.create_task("proj", "Task", body="Body", plan="Plan")
        d = task.to_dict()
        assert d["number"] == 1
        assert d["description"] == "Task"
        assert d["body"] == "Body"
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
        core.update_task("proj", 1, description="Updated")
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
        assert task.description == "Task via underscore"

    def test_create_with_hyphen_access_with_underscore(self, graph_core):
        """Creating a task with hyphen should be accessible via underscore."""
        core.create_task("test-proj", "Task via hyphen")
        task = core.get_task("test_proj", 1)
        assert task is not None
        assert task.description == "Task via hyphen"

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
        assert tasks[0].description == "Task 1"

    def test_update_task_with_underscore(self, graph_core):
        """update_task should work with underscore variant."""
        core.create_task("my-proj", "Task")
        updated = core.update_task("my_proj", 1, description="Updated")
        assert updated.description == "Updated"

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

        # Force re-migration
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
