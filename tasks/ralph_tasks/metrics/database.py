"""PostgreSQL metrics database module.

Provides a lazy-singleton connection pool, schema management, and
create/query operations for session/task-execution metrics.

Configuration via environment variables:
- POSTGRES_URI (default: postgresql://ralph:ralph@localhost:5432/ralph)
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger("ralph-tasks.metrics")

_DEFAULT_URI = "postgresql://ralph:ralph@localhost:5432/ralph"

# Singleton state
_pool: ThreadedConnectionPool | None = None
_schema_ensured: bool = False
_pool_lock = threading.Lock()


def _get_pool() -> ThreadedConnectionPool:
    """Get or create the singleton connection pool (thread-safe)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                uri = os.environ.get("POSTGRES_URI", _DEFAULT_URI)
                _pool = ThreadedConnectionPool(minconn=1, maxconn=5, dsn=uri)
                parsed = urlparse(uri)
                logger.info(
                    "PostgreSQL connection pool created: %s:%s/%s",
                    parsed.hostname,
                    parsed.port,
                    parsed.path.lstrip("/"),
                )
    return _pool


@contextmanager
def get_conn() -> Iterator[Any]:
    """Context manager providing a connection with auto commit/rollback.

    On success: commits and returns connection to pool.
    On error: rolls back, returns connection to pool, and re-raises.
    """
    pool = _get_pool()
    conn = pool.getconn()
    close = False
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            logger.warning("Failed to rollback connection", exc_info=True)
            close = True
        raise
    finally:
        pool.putconn(conn, close=close)


def reset_pool() -> None:
    """Close all connections and reset singleton state (for testing)."""
    global _pool, _schema_ensured
    if _pool is not None:
        try:
            _pool.closeall()
        except Exception:
            logger.warning("Failed to close PostgreSQL pool", exc_info=True)
    _pool = None
    _schema_ensured = False


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    command_type VARCHAR NOT NULL,
    project VARCHAR NOT NULL,
    model VARCHAR,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    total_cost_usd FLOAT DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cache_read INTEGER DEFAULT 0,
    total_tool_calls INTEGER DEFAULT 0,
    exit_code INTEGER,
    error_type VARCHAR,
    claude_session_id VARCHAR,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS task_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    task_ref VARCHAR NOT NULL,
    cost_usd FLOAT DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    duration_seconds INTEGER DEFAULT 0,
    exit_code INTEGER,
    error_type VARCHAR,
    git_branch VARCHAR,
    files_changed INTEGER,
    recovery_attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions (started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions (project);
CREATE INDEX IF NOT EXISTS idx_task_executions_session_id ON task_executions (session_id);
"""


def ensure_schema() -> None:
    """Create tables and indexes if they don't exist (idempotent).

    Skips the DB round-trip after the first successful call in this process.
    Call ``reset_pool()`` to force re-check.
    """
    global _schema_ensured
    if _schema_ensured:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
    _schema_ensured = True
    logger.info("PostgreSQL metrics schema ensured")


def drop_schema() -> None:
    """Drop all metrics tables (for testing)."""
    global _schema_ensured
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS task_executions CASCADE")
            cur.execute("DROP TABLE IF EXISTS sessions CASCADE")
    _schema_ensured = False


# ---------------------------------------------------------------------------
# Period helper
# ---------------------------------------------------------------------------

_PERIOD_INTERVALS = {
    "7d": "7 days",
    "30d": "30 days",
    "90d": "90 days",
}

_VALID_PERIODS = frozenset(_PERIOD_INTERVALS) | {"all"}


def _period_where(period: str, project: str | None) -> tuple[str, list[Any]]:
    """Build WHERE clause and params for period/project filtering.

    Raises ValueError for unrecognised period values.
    """
    if period not in _VALID_PERIODS:
        raise ValueError(f"Unknown period: {period!r}. Must be one of {sorted(_VALID_PERIODS)}")

    clauses: list[str] = []
    params: list[Any] = []

    if period != "all":
        clauses.append(f"s.started_at >= NOW() - INTERVAL '{_PERIOD_INTERVALS[period]}'")

    if project:
        clauses.append("s.project = %s")
        params.append(project)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

_REQUIRED_SESSION_FIELDS = {"command_type", "project", "started_at"}

_SESSION_FIELDS = [
    "command_type",
    "project",
    "model",
    "started_at",
    "finished_at",
    "total_cost_usd",
    "total_input_tokens",
    "total_output_tokens",
    "total_cache_read",
    "total_tool_calls",
    "exit_code",
    "error_type",
    "claude_session_id",
]

_TE_FIELDS = [
    "task_ref",
    "cost_usd",
    "input_tokens",
    "output_tokens",
    "duration_seconds",
    "exit_code",
    "error_type",
    "git_branch",
    "files_changed",
    "recovery_attempts",
]


def create_session(data: dict) -> str:
    """Insert a session with optional task_executions.

    Args:
        data: dict with session fields. May include 'task_executions' key
              containing a list of dicts for the task_executions table.
              The dict is not modified.

    Returns:
        UUID string of the created session.

    Raises:
        ValueError: if required fields (command_type, project, started_at)
            are missing.
    """
    task_executions = data.get("task_executions", [])

    present = {k: data[k] for k in _SESSION_FIELDS if k in data}
    if not present:
        raise ValueError("No valid session fields provided")

    missing = _REQUIRED_SESSION_FIELDS - present.keys()
    if missing:
        raise ValueError(f"Missing required session fields: {sorted(missing)}")

    cols = ", ".join(present.keys())
    placeholders = ", ".join(["%s"] * len(present))
    values = list(present.values())

    with get_conn() as conn:
        with conn.cursor() as cur:
            # safe: cols from whitelist, values via %s params
            cur.execute(
                f"INSERT INTO sessions ({cols}) VALUES ({placeholders}) RETURNING id",
                values,
            )
            row = cur.fetchone()
            session_id = str(row[0])

            for te in task_executions:
                te_present = {k: te[k] for k in _TE_FIELDS if k in te}
                te_present["session_id"] = session_id
                te_cols = ", ".join(te_present.keys())
                te_placeholders = ", ".join(["%s"] * len(te_present))
                te_values = list(te_present.values())
                # safe: cols from whitelist, values via %s params
                cur.execute(
                    f"INSERT INTO task_executions ({te_cols}) VALUES ({te_placeholders})",
                    te_values,
                )

    return session_id


def get_summary(period: str = "30d", project: str | None = None) -> dict:
    """Get aggregated metrics summary.

    Args:
        period: Time window — '7d', '30d', '90d', or 'all'.
        project: Optional project name filter.

    Returns:
        dict with: total_sessions, successful, failed, total_cost,
        avg_cost_per_session, total_input_tokens, total_output_tokens,
        total_tokens.

        Sessions with ``exit_code IS NULL`` (in-progress or not yet recorded)
        are counted as successful.

    Raises:
        ValueError: if period is not one of '7d', '30d', '90d', 'all'.
    """
    where, params = _period_where(period, project)

    # safe: where clause from hardcoded _PERIOD_INTERVALS dict
    query = f"""
        SELECT
            COUNT(*) AS total_sessions,
            COUNT(*) FILTER (WHERE s.exit_code = 0 OR s.exit_code IS NULL) AS successful,
            COUNT(*) FILTER (WHERE s.exit_code IS NOT NULL AND s.exit_code != 0) AS failed,
            COALESCE(SUM(s.total_cost_usd), 0) AS total_cost,
            COALESCE(AVG(s.total_cost_usd), 0) AS avg_cost_per_session,
            COALESCE(SUM(s.total_input_tokens), 0) AS total_input_tokens,
            COALESCE(SUM(s.total_output_tokens), 0) AS total_output_tokens
        FROM sessions s
        {where}
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()

    return {
        "total_sessions": row[0],
        "successful": row[1],
        "failed": row[2],
        "total_cost": float(row[3]),
        "avg_cost_per_session": float(row[4]),
        "total_input_tokens": row[5],
        "total_output_tokens": row[6],
        "total_tokens": row[5] + row[6],
    }


_ALLOWED_GROUP_BY = frozenset({"command_type", "model"})

_METRIC_EXPRS = {
    "cost": "COALESCE(SUM(s.total_cost_usd), 0)",
    "tokens": "COALESCE(SUM(s.total_input_tokens + s.total_output_tokens), 0)",
    "sessions": "COUNT(*)",
}


def get_timeline(period: str = "30d", metric: str = "cost", project: str | None = None) -> dict:
    """Get time-series data grouped by day.

    Args:
        period: Time window — '7d', '30d', '90d', or 'all'.
        metric: What to aggregate — 'cost', 'tokens', or 'sessions'.
        project: Optional project filter.

    Returns:
        dict with: labels (list[str]), datasets (list[float|int]).

    Raises:
        ValueError: if period is not one of '7d', '30d', '90d', 'all'.
        ValueError: if metric is not one of the allowed values.
    """
    if metric not in _METRIC_EXPRS:
        raise ValueError(f"Unknown metric: {metric!r}. Must be one of {sorted(_METRIC_EXPRS)}")

    where, params = _period_where(period, project)
    metric_expr = _METRIC_EXPRS[metric]

    # safe: metric_expr from hardcoded _METRIC_EXPRS dict, where from _PERIOD_INTERVALS
    query = f"""
        SELECT
            DATE(s.started_at) AS day,
            {metric_expr} AS value
        FROM sessions s
        {where}
        GROUP BY DATE(s.started_at)
        ORDER BY day
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    labels = [row[0].isoformat() for row in rows]
    datasets = [float(row[1]) for row in rows]

    return {"labels": labels, "datasets": datasets}


def get_breakdown(
    period: str = "30d", group_by: str = "command_type", project: str | None = None
) -> dict:
    """Get metrics breakdown by a grouping field.

    Args:
        period: Time window — '7d', '30d', '90d', or 'all'.
        group_by: Field to group by — 'command_type' or 'model'.
        project: Optional project filter.

    Returns:
        dict with: labels (list[str]), data (list[float]).

    Raises:
        ValueError: if period is not one of '7d', '30d', '90d', 'all'.
        ValueError: if group_by is not one of the allowed fields.
    """
    if group_by not in _ALLOWED_GROUP_BY:
        raise ValueError(f"group_by must be one of {sorted(_ALLOWED_GROUP_BY)}")

    where, params = _period_where(period, project)

    # safe: group_by validated against allowed_fields whitelist
    query = f"""
        SELECT
            COALESCE(s.{group_by}, 'unknown') AS group_label,
            COALESCE(SUM(s.total_cost_usd), 0) AS total_cost
        FROM sessions s
        {where}
        GROUP BY s.{group_by}
        ORDER BY total_cost DESC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    labels = [row[0] for row in rows]
    data = [float(row[1]) for row in rows]

    return {"labels": labels, "data": data}
