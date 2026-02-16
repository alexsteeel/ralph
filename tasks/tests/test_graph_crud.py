"""Tests for CRUD operations on all Neo4j node types."""

import pytest

from ralph_tasks.graph import crud


@pytest.mark.neo4j
class TestWorkspaceCRUD:
    def test_create_workspace(self, neo4j_session):
        ws = crud.create_workspace(neo4j_session, "test-ws", "A test workspace")
        assert ws["name"] == "test-ws"
        assert ws["description"] == "A test workspace"
        assert "created_at" in ws

    def test_get_workspace(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws1")
        ws = crud.get_workspace(neo4j_session, "ws1")
        assert ws is not None
        assert ws["name"] == "ws1"

    def test_get_workspace_not_found(self, neo4j_session):
        ws = crud.get_workspace(neo4j_session, "nonexistent")
        assert ws is None

    def test_list_workspaces(self, neo4j_session):
        crud.create_workspace(neo4j_session, "alpha")
        crud.create_workspace(neo4j_session, "beta")
        workspaces = crud.list_workspaces(neo4j_session)
        names = [w["name"] for w in workspaces]
        assert names == ["alpha", "beta"]


@pytest.mark.neo4j
class TestProjectCRUD:
    def test_create_project_under_workspace(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        proj = crud.create_project(neo4j_session, "ws", "proj1", "Description")
        assert proj["name"] == "proj1"
        assert proj["description"] == "Description"

    def test_create_project_under_project(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "parent")
        child = crud.create_project(neo4j_session, "parent", "child", parent_label="Project")
        assert child["name"] == "child"

    def test_create_duplicate_project_raises(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        with pytest.raises(ValueError, match="already exists"):
            crud.create_project(neo4j_session, "ws", "proj")

    def test_create_project_nonexistent_parent_raises(self, neo4j_session):
        with pytest.raises(ValueError, match="not found"):
            crud.create_project(neo4j_session, "nonexistent", "proj")

    def test_get_project(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj1")
        proj = crud.get_project(neo4j_session, "ws", "proj1")
        assert proj is not None
        assert proj["name"] == "proj1"

    def test_get_project_by_name(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "unique-proj")
        proj = crud.get_project_by_name(neo4j_session, "unique-proj")
        assert proj is not None
        assert proj["name"] == "unique-proj"

    def test_list_projects(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "alpha")
        crud.create_project(neo4j_session, "ws", "beta")
        projects = crud.list_projects(neo4j_session, "ws")
        names = [p["name"] for p in projects]
        assert names == ["alpha", "beta"]


@pytest.mark.neo4j
class TestTaskCRUD:
    def test_create_task(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        task = crud.create_task(neo4j_session, "proj", "First task")
        assert task["number"] == 1
        assert task["description"] == "First task"
        assert task["status"] == "todo"

    def test_create_task_auto_increment(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        t1 = crud.create_task(neo4j_session, "proj", "Task 1")
        t2 = crud.create_task(neo4j_session, "proj", "Task 2")
        assert t1["number"] == 1
        assert t2["number"] == 2

    def test_create_task_nonexistent_project_raises(self, neo4j_session):
        with pytest.raises(ValueError, match="not found"):
            crud.create_task(neo4j_session, "nonexistent", "Task")

    def test_get_task(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        task = crud.get_task(neo4j_session, "proj", 1)
        assert task is not None
        assert task["description"] == "Task"

    def test_get_task_not_found(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        assert crud.get_task(neo4j_session, "proj", 999) is None

    def test_list_tasks(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task A")
        crud.create_task(neo4j_session, "proj", "Task B")
        tasks = crud.list_tasks(neo4j_session, "proj")
        assert len(tasks) == 2
        assert tasks[0]["number"] == 1
        assert tasks[1]["number"] == 2

    def test_update_task(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        updated = crud.update_task(neo4j_session, "proj", 1, status="work")
        assert updated["status"] == "work"
        assert "updated_at" in updated

    def test_update_task_not_found_raises(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        with pytest.raises(ValueError, match="not found"):
            crud.update_task(neo4j_session, "proj", 999, status="done")

    def test_delete_task(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        assert crud.delete_task(neo4j_session, "proj", 1) is True
        assert crud.get_task(neo4j_session, "proj", 1) is None


@pytest.mark.neo4j
class TestSubtaskCRUD:
    def test_create_subtask(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Parent")
        sub = crud.create_subtask(neo4j_session, "proj", 1, "Subtask")
        assert sub["description"] == "Subtask"
        assert sub["number"] == 2  # next after parent

    def test_list_subtasks(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Parent")
        crud.create_subtask(neo4j_session, "proj", 1, "Sub A")
        crud.create_subtask(neo4j_session, "proj", 1, "Sub B")
        subs = crud.list_subtasks(neo4j_session, "proj", 1)
        assert len(subs) == 2

    def test_create_subtask_nonexistent_parent_raises(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        with pytest.raises(ValueError, match="not found"):
            crud.create_subtask(neo4j_session, "proj", 999, "Sub")


@pytest.mark.neo4j
class TestDependencyCRUD:
    def test_add_dependency(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task 1")
        crud.create_task(neo4j_session, "proj", "Task 2")
        assert crud.add_dependency(neo4j_session, "proj", 2, 1) is True

    def test_get_dependencies(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task 1")
        crud.create_task(neo4j_session, "proj", "Task 2")
        crud.add_dependency(neo4j_session, "proj", 2, 1)
        deps = crud.get_dependencies(neo4j_session, "proj", 2)
        assert len(deps) == 1
        assert deps[0]["number"] == 1

    def test_remove_dependency(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task 1")
        crud.create_task(neo4j_session, "proj", "Task 2")
        crud.add_dependency(neo4j_session, "proj", 2, 1)
        assert crud.remove_dependency(neo4j_session, "proj", 2, 1) is True
        assert len(crud.get_dependencies(neo4j_session, "proj", 2)) == 0

    def test_add_dependency_idempotent(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task 1")
        crud.create_task(neo4j_session, "proj", "Task 2")
        crud.add_dependency(neo4j_session, "proj", 2, 1)
        crud.add_dependency(neo4j_session, "proj", 2, 1)  # should not duplicate
        deps = crud.get_dependencies(neo4j_session, "proj", 2)
        assert len(deps) == 1


@pytest.mark.neo4j
class TestSectionCRUD:
    def test_create_section(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        section = crud.create_section(neo4j_session, "proj", 1, "plan", "The plan")
        assert section["type"] == "plan"
        assert section["content"] == "The plan"

    def test_get_section(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "description", "Desc text")
        section = crud.get_section(neo4j_session, "proj", 1, "description")
        assert section is not None
        assert section["content"] == "Desc text"

    def test_get_section_not_found(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        assert crud.get_section(neo4j_session, "proj", 1, "nonexistent") is None

    def test_update_section(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "plan", "v1")
        updated = crud.update_section(neo4j_session, "proj", 1, "plan", "v2")
        assert updated["content"] == "v2"

    def test_delete_section(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "plan", "content")
        assert crud.delete_section(neo4j_session, "proj", 1, "plan") is True
        assert crud.get_section(neo4j_session, "proj", 1, "plan") is None


@pytest.mark.neo4j
class TestFindingCRUD:
    def test_create_finding(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        finding = crud.create_finding(
            neo4j_session, "proj", 1, "code-review",
            text="Missing null check", author="reviewer", severity="major",
        )
        assert finding["text"] == "Missing null check"
        assert finding["status"] == "open"
        assert finding["severity"] == "major"
        assert "element_id" in finding

    def test_update_finding_status(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        finding = crud.create_finding(
            neo4j_session, "proj", 1, "code-review",
            text="Bug", author="reviewer",
        )
        updated = crud.update_finding_status(neo4j_session, finding["element_id"], "resolved")
        assert updated["status"] == "resolved"
        assert "resolved_at" in updated

    def test_list_findings(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        crud.create_finding(neo4j_session, "proj", 1, "code-review", "F1", "reviewer")
        crud.create_finding(neo4j_session, "proj", 1, "code-review", "F2", "reviewer")
        findings = crud.list_findings(neo4j_session, "proj", 1)
        assert len(findings) == 2

    def test_list_findings_filter_by_status(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        f1 = crud.create_finding(neo4j_session, "proj", 1, "code-review", "F1", "rev")
        crud.create_finding(neo4j_session, "proj", 1, "code-review", "F2", "rev")
        crud.update_finding_status(neo4j_session, f1["element_id"], "resolved")
        open_findings = crud.list_findings(neo4j_session, "proj", 1, status="open")
        assert len(open_findings) == 1
        assert open_findings[0]["text"] == "F2"


@pytest.mark.neo4j
class TestCommentCRUD:
    def test_create_comment(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        finding = crud.create_finding(
            neo4j_session, "proj", 1, "code-review", "Issue", "reviewer"
        )
        comment = crud.create_comment(
            neo4j_session, finding["element_id"], "Agreed, fixing.", "developer"
        )
        assert comment["text"] == "Agreed, fixing."
        assert comment["author"] == "developer"

    def test_reply_to_comment(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        finding = crud.create_finding(
            neo4j_session, "proj", 1, "code-review", "Issue", "reviewer"
        )
        comment = crud.create_comment(
            neo4j_session, finding["element_id"], "First comment", "dev"
        )
        reply = crud.reply_to_comment(
            neo4j_session, comment["element_id"], "Reply", "reviewer"
        )
        assert reply["text"] == "Reply"
        assert reply["author"] == "reviewer"

    def test_list_comments(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        finding = crud.create_finding(
            neo4j_session, "proj", 1, "code-review", "Issue", "rev"
        )
        crud.create_comment(neo4j_session, finding["element_id"], "C1", "dev")
        crud.create_comment(neo4j_session, finding["element_id"], "C2", "dev")
        comments = crud.list_comments(neo4j_session, finding["element_id"])
        assert len(comments) == 2


@pytest.mark.neo4j
class TestWorkflowCRUD:
    def test_create_workflow_run(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        run = crud.create_workflow_run(neo4j_session, "proj", 1, "implement")
        assert run["type"] == "implement"
        assert run["status"] == "pending"
        assert "element_id" in run

    def test_update_workflow_run(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        run = crud.create_workflow_run(neo4j_session, "proj", 1, "implement")
        updated = crud.update_workflow_run(neo4j_session, run["element_id"], "completed")
        assert updated["status"] == "completed"
        assert "completed_at" in updated

    def test_create_workflow_step(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        run = crud.create_workflow_run(neo4j_session, "proj", 1, "implement")
        step = crud.create_workflow_step(neo4j_session, run["element_id"], "test")
        assert step["name"] == "test"
        assert step["status"] == "pending"

    def test_update_workflow_step(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        run = crud.create_workflow_run(neo4j_session, "proj", 1, "implement")
        step = crud.create_workflow_step(neo4j_session, run["element_id"], "lint")
        updated = crud.update_workflow_step(
            neo4j_session, step["element_id"], "completed", output="All checks passed"
        )
        assert updated["status"] == "completed"
        assert updated["output"] == "All checks passed"
