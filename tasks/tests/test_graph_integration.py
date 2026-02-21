"""Integration tests: full lifecycle, recursive structures, cascade deletes."""

import pytest
from ralph_tasks.graph import crud
from ralph_tasks.graph.schema import ensure_schema


@pytest.mark.neo4j
class TestFullTaskLifecycle:
    """Test complete lifecycle from Workspace creation through Comment replies."""

    def test_full_lifecycle(self, neo4j_session):
        # 1. Create workspace
        ws = crud.create_workspace(neo4j_session, "main", "Main workspace")
        assert ws["name"] == "main"

        # 2. Create project
        proj = crud.create_project(neo4j_session, "main", "ralph", "Ralph project")
        assert proj["name"] == "ralph"

        # 3. Create task
        task = crud.create_task(neo4j_session, "ralph", "Add Neo4j support")
        assert task["number"] == 1

        # 4. Update task status
        task = crud.update_task(neo4j_session, "ralph", 1, status="work")
        assert task["status"] == "work"

        # 5. Add sections
        plan = crud.create_section(neo4j_session, "ralph", 1, "plan", "Implementation plan")
        assert plan["type"] == "plan"

        report = crud.create_section(neo4j_session, "ralph", 1, "report", "")
        assert report["content"] == ""

        # 6. Add code review section with findings
        crud.create_section(neo4j_session, "ralph", 1, "code-review")
        f1 = crud.create_finding(
            neo4j_session,
            "ralph",
            1,
            "code-review",
            "Missing error handling",
            "code-reviewer",
            file="src/main.py",
            line_start=42,
        )
        assert f1["status"] == "open"

        # 7. Comment on finding
        c1 = crud.create_comment(
            neo4j_session, f1["element_id"], "Will fix in next commit", "developer"
        )
        assert c1["author"] == "developer"

        # 8. Reply to comment
        reply = crud.reply_to_comment(neo4j_session, c1["element_id"], "Thanks!", "code-reviewer")
        assert reply["text"] == "Thanks!"

        # 9. Resolve finding
        f1_resolved = crud.update_finding_status(neo4j_session, f1["element_id"], "resolved")
        assert f1_resolved["status"] == "resolved"

        # 10. Create workflow run
        run = crud.create_workflow_run(neo4j_session, "ralph", 1, "implement")
        assert run["status"] == "pending"

        # 11. Add workflow steps
        step_impl = crud.create_workflow_step(neo4j_session, run["element_id"], "implement")
        step_test = crud.create_workflow_step(neo4j_session, run["element_id"], "test")

        # 12. Update step statuses
        crud.update_workflow_step(neo4j_session, step_impl["element_id"], "completed")
        updated_test = crud.update_workflow_step(
            neo4j_session, step_test["element_id"], "completed", output="All 42 tests passed"
        )
        assert updated_test["output"] == "All 42 tests passed"

        # 13. Complete workflow
        run_done = crud.update_workflow_run(neo4j_session, run["element_id"], "completed")
        assert run_done["status"] == "completed"

        # 14. Complete task
        task = crud.update_task(neo4j_session, "ralph", 1, status="done")
        assert task["status"] == "done"

        # 15. Update report section
        crud.update_section(neo4j_session, "ralph", 1, "report", "Task completed successfully")
        report = crud.get_section(neo4j_session, "ralph", 1, "report")
        assert report["content"] == "Task completed successfully"


@pytest.mark.neo4j
class TestRecursiveStructures:
    """Test recursive Project and Task nesting."""

    def test_nested_projects(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "parent")
        crud.create_project(neo4j_session, "parent", "child", parent_label="Project")
        crud.create_project(neo4j_session, "child", "grandchild", parent_label="Project")

        # Verify hierarchy
        children = crud.list_projects(neo4j_session, "parent")
        assert len(children) == 1
        assert children[0]["name"] == "child"

        grandchildren = crud.list_projects(neo4j_session, "child")
        assert len(grandchildren) == 1
        assert grandchildren[0]["name"] == "grandchild"

    def test_subtasks(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Parent task")
        crud.create_subtask(neo4j_session, "proj", 1, "Sub A")
        crud.create_subtask(neo4j_session, "proj", 1, "Sub B")

        subs = crud.list_subtasks(neo4j_session, "proj", 1)
        assert len(subs) == 2
        descriptions = {s["description"] for s in subs}
        assert descriptions == {"Sub A", "Sub B"}


@pytest.mark.neo4j
class TestCascadeDelete:
    """Test that deleting a task removes all related nodes."""

    def test_delete_task_with_sections_and_findings(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        crud.create_section(neo4j_session, "proj", 1, "code-review")
        finding = crud.create_finding(neo4j_session, "proj", 1, "code-review", "Issue", "rev")
        crud.create_comment(neo4j_session, finding["element_id"], "Comment", "dev")

        # Delete task
        crud.delete_task(neo4j_session, "proj", 1)

        # Verify all related nodes are gone
        assert crud.get_task(neo4j_session, "proj", 1) is None
        assert crud.get_section(neo4j_session, "proj", 1, "code-review") is None

        # Verify no orphan nodes exist
        result = neo4j_session.run(
            "MATCH (n) WHERE n:Section OR n:Finding OR n:Comment RETURN count(n) AS cnt"
        )
        assert result.single()["cnt"] == 0

    def test_delete_task_with_workflow(self, neo4j_session):
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task")
        run = crud.create_workflow_run(neo4j_session, "proj", 1, "implement")
        crud.create_workflow_step(neo4j_session, run["element_id"], "test")

        crud.delete_task(neo4j_session, "proj", 1)

        result = neo4j_session.run(
            "MATCH (n) WHERE n:WorkflowRun OR n:WorkflowStep RETURN count(n) AS cnt"
        )
        assert result.single()["cnt"] == 0


@pytest.mark.neo4j
class TestDependencyGraph:
    """Test complex dependency patterns."""

    def test_diamond_dependency(self, neo4j_session):
        """A depends on B and C; B and C both depend on D."""
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "A")
        crud.create_task(neo4j_session, "proj", "B")
        crud.create_task(neo4j_session, "proj", "C")
        crud.create_task(neo4j_session, "proj", "D")

        crud.add_dependency(neo4j_session, "proj", 1, 2)  # A->B
        crud.add_dependency(neo4j_session, "proj", 1, 3)  # A->C
        crud.add_dependency(neo4j_session, "proj", 2, 4)  # B->D
        crud.add_dependency(neo4j_session, "proj", 3, 4)  # C->D

        # A depends on B and C
        deps_a = crud.get_dependencies(neo4j_session, "proj", 1)
        dep_nums = {d["number"] for d in deps_a}
        assert dep_nums == {2, 3}

        # B depends on D
        deps_b = crud.get_dependencies(neo4j_session, "proj", 2)
        assert len(deps_b) == 1
        assert deps_b[0]["number"] == 4

    def test_chain_dependency(self, neo4j_session):
        """A->B->C (linear chain)."""
        crud.create_workspace(neo4j_session, "ws")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "A")
        crud.create_task(neo4j_session, "proj", "B")
        crud.create_task(neo4j_session, "proj", "C")

        crud.add_dependency(neo4j_session, "proj", 1, 2)
        crud.add_dependency(neo4j_session, "proj", 2, 3)

        # A directly depends on B only
        deps_a = crud.get_dependencies(neo4j_session, "proj", 1)
        assert len(deps_a) == 1
        assert deps_a[0]["number"] == 2

        # B directly depends on C only
        deps_b = crud.get_dependencies(neo4j_session, "proj", 2)
        assert len(deps_b) == 1
        assert deps_b[0]["number"] == 3


@pytest.mark.neo4j
class TestSchemaIdempotency:
    """Test that ensure_schema doesn't break existing data."""

    def test_schema_preserves_data(self, neo4j_session, neo4j_client):
        ensure_schema(neo4j_client)

        # Create data
        crud.create_workspace(neo4j_session, "ws", "Test workspace")
        crud.create_project(neo4j_session, "ws", "proj")
        crud.create_task(neo4j_session, "proj", "Task 1")

        # Re-run schema
        ensure_schema(neo4j_client)

        # Data should still be there
        ws = crud.get_workspace(neo4j_session, "ws")
        assert ws is not None
        assert ws["description"] == "Test workspace"

        task = crud.get_task(neo4j_session, "proj", 1)
        assert task is not None
        assert task["description"] == "Task 1"
