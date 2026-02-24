"""Integration tests for ralph_tasks.metrics.database module."""

from datetime import datetime, timedelta

import pytest


@pytest.mark.postgres
class TestSchema:
    """Tests for schema creation and idempotency."""

    def test_ensure_schema_creates_tables(self, pg_database):
        """ensure_schema() creates sessions and task_executions tables."""
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ('sessions', 'task_executions') "
                    "ORDER BY table_name"
                )
                tables = [row[0] for row in cur.fetchall()]
        assert tables == ["sessions", "task_executions"]

    def test_ensure_schema_idempotent(self, pg_database):
        """Multiple ensure_schema() calls are no-op after the first (Python guard)."""
        pg_database.ensure_schema()
        pg_database.ensure_schema()

        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ('sessions', 'task_executions') "
                    "ORDER BY table_name"
                )
                tables = [row[0] for row in cur.fetchall()]
        assert tables == ["sessions", "task_executions"]

    def test_drop_schema_removes_tables(self, pg_database):
        """drop_schema() removes tables, ensure_schema() restores them."""
        pg_database.drop_schema()

        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ('sessions', 'task_executions')"
                )
                tables = [row[0] for row in cur.fetchall()]
        assert tables == []

        # ensure_schema() should restore them
        pg_database.ensure_schema()
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ('sessions', 'task_executions') "
                    "ORDER BY table_name"
                )
                tables = [row[0] for row in cur.fetchall()]
        assert tables == ["sessions", "task_executions"]


@pytest.mark.postgres
class TestCreateSession:
    """Tests for create_session."""

    def test_create_session_minimal(self, pg_database):
        """Create a session with minimal required fields."""
        session_id = pg_database.create_session(
            {
                "command_type": "implement",
                "project": "test-project",
                "started_at": datetime.now(),
            }
        )
        assert session_id is not None
        assert len(session_id) == 36  # UUID format

    def test_create_session_with_all_fields(self, pg_database):
        """Create a session with all optional fields."""
        now = datetime.now()
        session_id = pg_database.create_session(
            {
                "command_type": "review",
                "project": "test-project",
                "model": "claude-opus-4-6",
                "started_at": now,
                "finished_at": now + timedelta(minutes=5),
                "total_cost_usd": 0.15,
                "total_input_tokens": 5000,
                "total_output_tokens": 2000,
                "total_cache_read": 1000,
                "total_tool_calls": 10,
                "exit_code": 0,
                "claude_session_id": "sess-123",
            }
        )
        assert session_id is not None

        # Verify data was stored
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT command_type, project, model FROM sessions WHERE id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        assert row == ("review", "test-project", "claude-opus-4-6")

    def test_create_session_with_task_executions(self, pg_database):
        """Create a session with associated task executions."""
        session_id = pg_database.create_session(
            {
                "command_type": "implement",
                "project": "test-project",
                "started_at": datetime.now(),
                "total_cost_usd": 0.50,
                "task_executions": [
                    {
                        "task_ref": "test-project#1",
                        "cost_usd": 0.30,
                        "input_tokens": 3000,
                        "output_tokens": 1000,
                        "duration_seconds": 120,
                        "exit_code": 0,
                        "git_branch": "feature-1",
                        "files_changed": 5,
                    },
                    {
                        "task_ref": "test-project#2",
                        "cost_usd": 0.20,
                        "input_tokens": 2000,
                        "output_tokens": 500,
                        "duration_seconds": 60,
                    },
                ],
            }
        )
        assert session_id is not None

        # Verify task_executions were created
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT task_ref FROM task_executions WHERE session_id = %s ORDER BY task_ref",
                    (session_id,),
                )
                refs = [row[0] for row in cur.fetchall()]
        assert refs == ["test-project#1", "test-project#2"]

    def test_create_session_no_fields_raises(self, pg_database):
        """create_session with no valid fields raises ValueError."""
        with pytest.raises(ValueError, match="No valid session fields"):
            pg_database.create_session({})

    def test_create_session_missing_required_fields_raises(self, pg_database):
        """create_session without required NOT NULL fields raises ValueError."""
        with pytest.raises(ValueError, match="Missing required session fields"):
            pg_database.create_session({"model": "opus"})

    def test_create_session_does_not_mutate_input(self, pg_database):
        """create_session does not modify the input dict."""
        data = {
            "command_type": "implement",
            "project": "test-project",
            "started_at": datetime.now(),
            "task_executions": [{"task_ref": "test#1"}],
        }
        original_keys = set(data.keys())
        pg_database.create_session(data)
        assert set(data.keys()) == original_keys
        assert "task_executions" in data


@pytest.mark.postgres
class TestGetSummary:
    """Tests for get_summary aggregation."""

    def test_get_summary_empty(self, pg_database):
        """Summary on empty database returns zeroes."""
        result = pg_database.get_summary(period="all")
        assert result["total_sessions"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0
        assert result["total_cost"] == 0.0
        assert result["total_tokens"] == 0

    def test_get_summary_with_data(self, pg_database):
        """Summary correctly aggregates session data."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj-a",
                "started_at": now,
                "total_cost_usd": 0.10,
                "total_input_tokens": 1000,
                "total_output_tokens": 500,
                "exit_code": 0,
            }
        )
        pg_database.create_session(
            {
                "command_type": "review",
                "project": "proj-a",
                "started_at": now,
                "total_cost_usd": 0.20,
                "total_input_tokens": 2000,
                "total_output_tokens": 800,
                "exit_code": 1,
            }
        )

        result = pg_database.get_summary(period="all")
        assert result["total_sessions"] == 2
        assert result["successful"] == 1
        assert result["failed"] == 1
        assert result["total_cost"] == pytest.approx(0.30, abs=0.001)
        assert result["avg_cost_per_session"] == pytest.approx(0.15, abs=0.001)
        assert result["total_input_tokens"] == 3000
        assert result["total_output_tokens"] == 1300
        assert result["total_tokens"] == 4300

    def test_get_summary_null_exit_code_counted_as_successful(self, pg_database):
        """Sessions without exit_code are counted as successful."""
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj",
                "started_at": datetime.now(),
            }
        )
        result = pg_database.get_summary(period="all")
        assert result["successful"] == 1
        assert result["failed"] == 0

    def test_get_summary_filtered_by_project(self, pg_database):
        """Summary filtered by project excludes other projects."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj-a",
                "started_at": now,
                "total_cost_usd": 0.10,
            }
        )
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj-b",
                "started_at": now,
                "total_cost_usd": 0.50,
            }
        )

        result = pg_database.get_summary(period="all", project="proj-a")
        assert result["total_sessions"] == 1
        assert result["total_cost"] == pytest.approx(0.10, abs=0.001)

    def test_get_summary_invalid_period_raises(self, pg_database):
        """Summary with unknown period raises ValueError."""
        with pytest.raises(ValueError, match="Unknown period"):
            pg_database.get_summary(period="14d")


@pytest.mark.postgres
class TestGetTimeline:
    """Tests for get_timeline time-series data."""

    def test_get_timeline_empty(self, pg_database):
        """Timeline on empty database returns empty lists."""
        result = pg_database.get_timeline(period="all", metric="cost")
        assert result == {"labels": [], "datasets": []}

    def test_get_timeline_cost(self, pg_database):
        """Timeline returns cost grouped by day."""
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj",
                "started_at": yesterday,
                "total_cost_usd": 0.10,
            }
        )
        pg_database.create_session(
            {
                "command_type": "review",
                "project": "proj",
                "started_at": now,
                "total_cost_usd": 0.20,
            }
        )

        result = pg_database.get_timeline(period="all", metric="cost")
        assert len(result["labels"]) >= 1
        assert len(result["datasets"]) >= 1
        assert sum(result["datasets"]) == pytest.approx(0.30, abs=0.001)

    def test_get_timeline_tokens(self, pg_database):
        """Timeline returns token counts."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj",
                "started_at": now,
                "total_input_tokens": 1000,
                "total_output_tokens": 500,
            }
        )

        result = pg_database.get_timeline(period="all", metric="tokens")
        assert result["datasets"][0] == 1500.0

    def test_get_timeline_sessions(self, pg_database):
        """Timeline returns session counts."""
        now = datetime.now()
        pg_database.create_session(
            {"command_type": "implement", "project": "proj", "started_at": now}
        )
        pg_database.create_session({"command_type": "review", "project": "proj", "started_at": now})

        result = pg_database.get_timeline(period="all", metric="sessions")
        assert result["datasets"][0] == 2.0

    def test_get_timeline_filtered_by_project(self, pg_database):
        """Timeline respects project filter."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj-a",
                "started_at": now,
                "total_cost_usd": 0.10,
            }
        )
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj-b",
                "started_at": now,
                "total_cost_usd": 0.50,
            }
        )

        result = pg_database.get_timeline(period="all", metric="cost", project="proj-a")
        assert sum(result["datasets"]) == pytest.approx(0.10, abs=0.001)

    def test_get_timeline_invalid_metric_raises(self, pg_database):
        """Timeline with unknown metric raises ValueError."""
        with pytest.raises(ValueError, match="Unknown metric"):
            pg_database.get_timeline(metric="bogus")

    def test_get_timeline_invalid_period_raises(self, pg_database):
        """Timeline with unknown period raises ValueError."""
        with pytest.raises(ValueError, match="Unknown period"):
            pg_database.get_timeline(period="1w")

    def test_get_timeline_period_filtering(self, pg_database):
        """Timeline with period=7d excludes old data."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj",
                "started_at": now - timedelta(days=60),
                "total_cost_usd": 1.00,
            }
        )
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj",
                "started_at": now,
                "total_cost_usd": 0.10,
            }
        )

        result_all = pg_database.get_timeline(period="all", metric="cost")
        result_7d = pg_database.get_timeline(period="7d", metric="cost")

        assert sum(result_all["datasets"]) == pytest.approx(1.10, abs=0.001)
        assert sum(result_7d["datasets"]) == pytest.approx(0.10, abs=0.001)


@pytest.mark.postgres
class TestGetBreakdown:
    """Tests for get_breakdown grouping."""

    def test_get_breakdown_empty(self, pg_database):
        """Breakdown on empty database returns empty lists."""
        result = pg_database.get_breakdown(period="all", group_by="command_type")
        assert result == {"labels": [], "data": []}

    def test_get_breakdown_by_command_type(self, pg_database):
        """Breakdown groups costs by command_type."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj",
                "started_at": now,
                "total_cost_usd": 0.30,
            }
        )
        pg_database.create_session(
            {
                "command_type": "review",
                "project": "proj",
                "started_at": now,
                "total_cost_usd": 0.10,
            }
        )

        result = pg_database.get_breakdown(period="all", group_by="command_type")
        assert "implement" in result["labels"]
        assert "review" in result["labels"]
        # implement has higher cost, should be first (ORDER BY total_cost DESC)
        assert result["labels"][0] == "implement"
        assert result["data"][0] == pytest.approx(0.30, abs=0.001)

    def test_get_breakdown_by_model(self, pg_database):
        """Breakdown groups costs by model."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj",
                "started_at": now,
                "model": "claude-opus-4-6",
                "total_cost_usd": 0.50,
            }
        )
        pg_database.create_session(
            {
                "command_type": "review",
                "project": "proj",
                "started_at": now,
                "model": "claude-sonnet-4-6",
                "total_cost_usd": 0.10,
            }
        )

        result = pg_database.get_breakdown(period="all", group_by="model")
        assert "claude-opus-4-6" in result["labels"]
        assert "claude-sonnet-4-6" in result["labels"]

    def test_get_breakdown_invalid_group_by(self, pg_database):
        """Breakdown with invalid group_by raises ValueError."""
        with pytest.raises(ValueError, match="group_by must be one of"):
            pg_database.get_breakdown(group_by="invalid_field")

    def test_get_breakdown_filtered_by_project(self, pg_database):
        """Breakdown respects project filter."""
        now = datetime.now()
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj-a",
                "started_at": now,
                "total_cost_usd": 0.10,
            }
        )
        pg_database.create_session(
            {
                "command_type": "implement",
                "project": "proj-b",
                "started_at": now,
                "total_cost_usd": 0.50,
            }
        )

        result = pg_database.get_breakdown(period="all", group_by="command_type", project="proj-a")
        assert sum(result["data"]) == pytest.approx(0.10, abs=0.001)


@pytest.mark.postgres
class TestPool:
    """Tests for connection pool management."""

    def test_get_conn_commit_on_success(self, pg_database):
        """get_conn() commits on normal exit."""
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sessions (command_type, project, started_at) "
                    "VALUES ('test', 'test-proj', NOW())"
                )

        # Data should be committed
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM sessions WHERE command_type = 'test'")
                count = cur.fetchone()[0]
        assert count == 1

    def test_get_conn_rollback_on_error(self, pg_database):
        """get_conn() rolls back on exception."""
        try:
            with pg_database.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sessions (command_type, project, started_at) "
                        "VALUES ('rollback-test', 'test-proj', NOW())"
                    )
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        # Data should NOT be committed
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM sessions WHERE command_type = 'rollback-test'")
                count = cur.fetchone()[0]
        assert count == 0

    def test_reset_pool(self, pg_database):
        """reset_pool() allows re-initialization of pool and schema."""
        pg_database.reset_pool()

        # Pool should re-initialize on next use
        pg_database.ensure_schema()
        with pg_database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone()[0] == 1
