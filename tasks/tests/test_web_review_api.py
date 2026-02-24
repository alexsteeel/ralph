"""Tests for review REST API endpoints in web.py."""

import pytest
from ralph_tasks.graph import crud
from ralph_tasks.web import app
from starlette.testclient import TestClient


@pytest.fixture
def _seed_project(neo4j_session):
    """Create workspace + project + tasks with findings for testing."""
    crud.create_workspace(neo4j_session, "default")
    crud.create_project(neo4j_session, "default", "test-proj")
    crud.create_task(neo4j_session, "test-proj", "Task one", number=1)
    crud.create_task(neo4j_session, "test-proj", "Task two", number=2)

    # Task 1: code-review findings
    f1 = crud.create_finding(
        neo4j_session,
        "test-proj",
        1,
        "code-review",
        "SQL injection risk",
        "code-reviewer",
        file="web.py",
        line_start=42,
        line_end=45,
    )
    f2 = crud.create_finding(
        neo4j_session,
        "test-proj",
        1,
        "code-review",
        "Unused import",
        "code-reviewer",
    )
    # Resolve f2
    crud.update_finding_status(neo4j_session, f2["element_id"], "resolved", response="Removed")

    # Task 1: security findings
    f3 = crud.create_finding(
        neo4j_session,
        "test-proj",
        1,
        "security",
        "XSS vulnerability",
        "security-reviewer",
        file="template.html",
        line_start=10,
    )
    crud.update_finding_status(
        neo4j_session, f3["element_id"], "declined", reason="Not exploitable"
    )

    # Add a comment to f1
    c1 = crud.create_comment(
        neo4j_session, f1["element_id"], "Fixed in commit abc123", "code-reviewer"
    )
    crud.reply_to_comment(neo4j_session, c1["element_id"], "Confirmed fix", "security-reviewer")

    return {"f1_id": f1["element_id"], "f2_id": f2["element_id"], "f3_id": f3["element_id"]}


@pytest.fixture
def api_client():
    """Starlette TestClient for the web app (raise_server_exceptions=False)."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.neo4j
class TestGetTaskReviews:
    """Tests for GET /api/task/{project}/{number}/reviews."""

    def test_get_reviews_empty(self, neo4j_session, api_client):
        """Task without findings returns empty review data."""
        crud.create_workspace(neo4j_session, "default")
        crud.create_project(neo4j_session, "default", "empty-proj")
        crud.create_task(neo4j_session, "empty-proj", "Empty task", number=1)

        res = api_client.get("/api/task/empty-proj/1/reviews")
        assert res.status_code == 200
        data = res.json()
        assert data["review_types"] == []
        assert data["findings"] == {}
        assert data["summary"] == {}

    def test_get_reviews_not_found(self, neo4j_session, api_client):
        """Non-existent task returns 404."""
        crud.create_workspace(neo4j_session, "default")
        crud.create_project(neo4j_session, "default", "proj-404")

        res = api_client.get("/api/task/proj-404/999/reviews")
        assert res.status_code == 404

    def test_get_reviews_with_findings(self, neo4j_session, api_client, _seed_project):
        """Task with findings returns findings with comments."""
        res = api_client.get("/api/task/test-proj/1/reviews")
        assert res.status_code == 200
        data = res.json()

        # Should have code-review findings
        assert "code-review" in data["review_types"]
        code_findings = data["findings"]["code-review"]
        assert len(code_findings) == 2

        # Check that one finding has comments
        f_with_comments = [f for f in code_findings if f["text"] == "SQL injection risk"]
        assert len(f_with_comments) == 1
        f1 = f_with_comments[0]
        assert f1["file"] == "web.py"
        assert f1["line_start"] == 42
        assert f1["line_end"] == 45
        assert f1["status"] == "open"
        assert f1["author"] == "code-reviewer"
        assert len(f1["comments"]) >= 1
        # Verify comment fields
        comment = f1["comments"][0]
        assert comment["text"] == "Fixed in commit abc123"
        assert comment["author"] == "code-reviewer"
        assert "created_at" in comment
        assert "element_id" in comment
        # Verify nested reply
        assert len(comment["replies"]) == 1
        reply = comment["replies"][0]
        assert reply["text"] == "Confirmed fix"
        assert reply["author"] == "security-reviewer"

    def test_get_reviews_grouped_by_type(self, neo4j_session, api_client, _seed_project):
        """Findings are grouped by review_type."""
        res = api_client.get("/api/task/test-proj/1/reviews")
        data = res.json()

        assert sorted(data["review_types"]) == ["code-review", "security"]
        assert "code-review" in data["findings"]
        assert "security" in data["findings"]
        assert len(data["findings"]["code-review"]) == 2
        assert len(data["findings"]["security"]) == 1

    def test_get_reviews_summary_counts(self, neo4j_session, api_client, _seed_project):
        """Summary counts are correct per review_type."""
        res = api_client.get("/api/task/test-proj/1/reviews")
        data = res.json()

        code_summary = data["summary"]["code-review"]
        assert code_summary["open"] == 1
        assert code_summary["resolved"] == 1
        assert code_summary["declined"] == 0

        security_summary = data["summary"]["security"]
        assert security_summary["open"] == 0
        assert security_summary["resolved"] == 0
        assert security_summary["declined"] == 1

    def test_get_reviews_resolved_declined_metadata(self, neo4j_session, api_client, _seed_project):
        """Resolved/declined findings include metadata fields."""
        res = api_client.get("/api/task/test-proj/1/reviews")
        data = res.json()

        # f2 is resolved with response="Removed"
        code_findings = data["findings"]["code-review"]
        resolved = [f for f in code_findings if f["status"] == "resolved"]
        assert len(resolved) == 1
        assert resolved[0]["response"] == "Removed"
        assert resolved[0]["resolved_at"] is not None

        # f3 is declined with reason="Not exploitable"
        sec_findings = data["findings"]["security"]
        declined = [f for f in sec_findings if f["status"] == "declined"]
        assert len(declined) == 1
        assert declined[0]["decline_reason"] == "Not exploitable"
        assert declined[0]["declined_at"] is not None


@pytest.mark.neo4j
class TestGetProjectReviewCounts:
    """Tests for GET /api/project/{name}/review-counts."""

    def test_get_review_counts_endpoint(self, neo4j_session, api_client, _seed_project):
        """Returns open finding counts per task."""
        res = api_client.get("/api/project/test-proj/review-counts")
        assert res.status_code == 200
        data = res.json()

        counts = data["counts"]
        # Task 1 has 1 open finding (code-review f1; f2=resolved, f3=declined)
        assert counts.get("1") == 1
        # Task 2 has no findings
        assert "2" not in counts

    def test_get_review_counts_empty_project(self, neo4j_session, api_client):
        """Project without findings returns empty counts."""
        crud.create_workspace(neo4j_session, "default")
        crud.create_project(neo4j_session, "default", "no-findings")
        crud.create_task(neo4j_session, "no-findings", "Clean task", number=1)

        res = api_client.get("/api/project/no-findings/review-counts")
        assert res.status_code == 200
        data = res.json()
        assert data["counts"] == {}
