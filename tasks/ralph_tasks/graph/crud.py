"""CRUD operations for all Neo4j node types."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import Session

logger = logging.getLogger(__name__)

_ALLOWED_PARENT_LABELS = frozenset({"Workspace", "Project"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


def create_workspace(session: Session, name: str, description: str = "") -> dict:
    """Create a Workspace node. Returns created node properties."""
    result = session.run(
        """
        CREATE (w:Workspace {name: $name, description: $description, created_at: $now})
        RETURN w {.*} AS workspace
        """,
        name=name,
        description=description,
        now=_now(),
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Failed to create workspace '{name}'")
    return dict(record["workspace"])


def get_workspace(session: Session, name: str) -> dict | None:
    result = session.run(
        "MATCH (w:Workspace {name: $name}) RETURN w {.*} AS workspace",
        name=name,
    )
    record = result.single()
    return dict(record["workspace"]) if record else None


def list_workspaces(session: Session) -> list[dict]:
    result = session.run("MATCH (w:Workspace) RETURN w {.*} AS workspace ORDER BY w.name")
    return [dict(r["workspace"]) for r in result]


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


def create_project(
    session: Session,
    parent_name: str,
    name: str,
    description: str = "",
    parent_label: str = "Workspace",
) -> dict:
    """Create a Project under a parent (Workspace or Project).

    parent_label: "Workspace" or "Project" — determines what node type to attach to.
    Composite uniqueness (name within parent) is enforced at the application level.
    """
    if parent_label not in _ALLOWED_PARENT_LABELS:
        raise ValueError(
            f"Invalid parent_label '{parent_label}'. "
            f"Must be one of: {', '.join(sorted(_ALLOWED_PARENT_LABELS))}"
        )

    # Check for duplicate
    check = session.run(
        f"""
        MATCH (parent:{parent_label} {{name: $parent_name}})-[:CONTAINS_PROJECT]->(p:Project {{name: $name}})
        RETURN p
        """,
        parent_name=parent_name,
        name=name,
    )
    if check.single():
        raise ValueError(f"Project '{name}' already exists under {parent_label} '{parent_name}'")

    result = session.run(
        f"""
        MATCH (parent:{parent_label} {{name: $parent_name}})
        CREATE (parent)-[:CONTAINS_PROJECT]->(p:Project {{
            name: $name, description: $description, created_at: $now
        }})
        RETURN p {{.*}} AS project
        """,
        parent_name=parent_name,
        name=name,
        description=description,
        now=_now(),
    )
    record = result.single()
    if record is None:
        raise ValueError(f"{parent_label} '{parent_name}' not found")
    return dict(record["project"])


def get_project(session: Session, workspace_name: str, project_name: str) -> dict | None:
    """Get a project by workspace and project name (direct child only)."""
    result = session.run(
        """
        MATCH (w:Workspace {name: $ws})-[:CONTAINS_PROJECT]->(p:Project {name: $name})
        RETURN p {.*} AS project
        """,
        ws=workspace_name,
        name=project_name,
    )
    record = result.single()
    return dict(record["project"]) if record else None


def get_project_by_name(session: Session, name: str) -> dict | None:
    """Get a project by name (global lookup, returns first match)."""
    result = session.run(
        "MATCH (p:Project {name: $name}) RETURN p {.*} AS project LIMIT 1",
        name=name,
    )
    record = result.single()
    return dict(record["project"]) if record else None


def list_projects(session: Session, parent_name: str) -> list[dict]:
    """List projects under a parent (Workspace or Project)."""
    result = session.run(
        """
        MATCH (parent {name: $parent_name})-[:CONTAINS_PROJECT]->(p:Project)
        WHERE parent:Workspace OR parent:Project
        RETURN p {.*} AS project
        ORDER BY p.name
        """,
        parent_name=parent_name,
    )
    return [dict(r["project"]) for r in result]


def rename_project(
    session: Session, workspace_name: str, old_name: str, new_name: str
) -> dict | None:
    """Rename a project. Returns updated project dict or None if not found."""
    result = session.run(
        """
        MATCH (w:Workspace {name: $ws})-[:CONTAINS_PROJECT]->(p:Project {name: $old_name})
        SET p.name = $new_name
        RETURN p {.*} AS project
        """,
        ws=workspace_name,
        old_name=old_name,
        new_name=new_name,
    )
    record = result.single()
    return dict(record["project"]) if record else None


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


def create_task(
    session: Session,
    project_name: str,
    description: str,
    **fields: Any,
) -> dict:
    """Create a Task under a Project.

    If ``number`` is provided in fields, uses it directly;
    otherwise auto-assigns next number atomically.
    """
    now = _now()
    props: dict[str, Any] = {
        "description": description,
        "status": fields.get("status", "todo"),
        "created_at": now,
        "updated_at": now,
    }
    for field in ("started", "completed", "module", "branch"):
        val = fields.get(field)
        if val is not None:
            props[field] = val

    explicit_number = fields.get("number")
    if explicit_number is not None:
        props["number"] = explicit_number
        result = session.run(
            """
            MATCH (p:Project {name: $project})
            CREATE (p)-[:HAS_TASK]->(t:Task $props)
            RETURN t {.*} AS task
            """,
            project=project_name,
            props=props,
        )
    else:
        result = session.run(
            """
            MATCH (p:Project {name: $project})
            OPTIONAL MATCH (p)-[:HAS_TASK]->(existing:Task)
            WITH p, COALESCE(MAX(existing.number), 0) + 1 AS next_number
            CREATE (p)-[:HAS_TASK]->(t:Task $props)
            SET t.number = next_number
            RETURN t {.*} AS task
            """,
            project=project_name,
            props=props,
        )
    record = result.single()
    if record is None:
        raise ValueError(f"Project '{project_name}' not found")
    return dict(record["task"])


def get_task(session: Session, project_name: str, number: int) -> dict | None:
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        RETURN t {.*} AS task
        """,
        project=project_name,
        number=number,
    )
    record = result.single()
    return dict(record["task"]) if record else None


def list_tasks(session: Session, project_name: str) -> list[dict]:
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task)
        OPTIONAL MATCH (t)-[:HAS_SECTION]->(s:Section)
        OPTIONAL MATCH (t)-[:DEPENDS_ON]->(dep:Task)
        WITH t,
             collect(DISTINCT {type: s.type, content: s.content}) AS sections,
             collect(DISTINCT dep.number) AS deps
        RETURN t {.*} AS task, sections, deps
        ORDER BY t.number
        """,
        project=project_name,
    )
    tasks = []
    for r in result:
        task_dict = dict(r["task"])
        for sec in r["sections"]:
            if sec["type"] is not None:
                task_dict[f"section_{sec['type']}"] = sec["content"] or ""
        task_dict["depends_on"] = sorted([d for d in r["deps"] if d is not None])
        tasks.append(task_dict)
    return tasks


def update_task(
    session: Session,
    project_name: str,
    number: int,
    **fields: Any,
) -> dict:
    """Update task fields. Only provided fields are updated."""
    fields["updated_at"] = _now()
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        SET t += $fields
        RETURN t {.*} AS task
        """,
        project=project_name,
        number=number,
        fields=fields,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Task #{number} not found in project '{project_name}'")
    return dict(record["task"])


def delete_task(session: Session, project_name: str, number: int) -> bool:
    """Delete a task and all related nodes (sections, findings, comments, workflows)."""
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        OPTIONAL MATCH (t)-[:HAS_SECTION]->(s:Section)
        OPTIONAL MATCH (s)-[:HAS_FINDING]->(f:Finding)
        OPTIONAL MATCH (f)-[:HAS_COMMENT]->(c:Comment)
        OPTIONAL MATCH (c)-[:REPLIED_BY*0..]->(reply:Comment)
        OPTIONAL MATCH (t)-[:HAS_WORKFLOW_RUN]->(wr:WorkflowRun)
        OPTIONAL MATCH (wr)-[:HAS_STEP]->(ws:WorkflowStep)
        OPTIONAL MATCH (t)-[:HAS_SUBTASK]->(sub:Task)
        DETACH DELETE t, s, f, c, reply, wr, ws, sub
        RETURN count(*) AS deleted
        """,
        project=project_name,
        number=number,
    )
    record = result.single()
    return record is not None and record["deleted"] > 0


def get_task_full(session: Session, project_name: str, number: int) -> dict | None:
    """Load a Task with all its Sections and depends_on in one query.

    Returns a dict with task properties plus ``section_<type>`` keys
    for each attached Section's content, and ``depends_on`` list of ints.
    Returns None if the task does not exist.
    """
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        OPTIONAL MATCH (t)-[:HAS_SECTION]->(s:Section)
        OPTIONAL MATCH (t)-[:DEPENDS_ON]->(dep:Task)
        WITH t, collect(DISTINCT {type: s.type, content: s.content}) AS sections,
             collect(DISTINCT dep.number) AS deps
        RETURN t {.*} AS task, sections, deps
        """,
        project=project_name,
        number=number,
    )
    record = result.single()
    if record is None:
        return None
    task_dict = dict(record["task"])
    for sec in record["sections"]:
        if sec["type"] is not None:
            task_dict[f"section_{sec['type']}"] = sec["content"] or ""
    # Filter out None from deps (comes from OPTIONAL MATCH when no deps)
    task_dict["depends_on"] = sorted([d for d in record["deps"] if d is not None])
    return task_dict


def upsert_section(
    session: Session,
    project_name: str,
    task_number: int,
    section_type: str,
    content: str,
) -> dict | None:
    """Create or update a Section. Empty content deletes the section.

    Returns section dict on create/update, None on delete.
    """
    if not content:
        # Delete section if it exists
        delete_section(session, project_name, task_number, section_type)
        return None

    now = _now()
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        MERGE (t)-[:HAS_SECTION]->(s:Section {type: $type})
        ON CREATE SET s.content = $content, s.created_at = $now, s.updated_at = $now
        ON MATCH SET s.content = $content, s.updated_at = $now
        RETURN s {.*} AS section
        """,
        project=project_name,
        number=task_number,
        type=section_type,
        content=content,
        now=now,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Task #{task_number} not found in project '{project_name}'")
    return dict(record["section"])


def sync_dependencies(
    session: Session,
    project_name: str,
    task_number: int,
    depends_on: list[int],
) -> list[int]:
    """Replace all DEPENDS_ON relationships for a task.

    Deletes existing DEPENDS_ON edges and creates new ones.
    Returns the list of dependency numbers actually created.
    """
    # Delete existing dependencies
    session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
              -[r:DEPENDS_ON]->()
        DELETE r
        """,
        project=project_name,
        number=task_number,
    )

    if not depends_on:
        return []

    # Create new dependencies
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        UNWIND $deps AS dep_num
        MATCH (p)-[:HAS_TASK]->(dep:Task {number: dep_num})
        MERGE (t)-[:DEPENDS_ON]->(dep)
        RETURN dep.number AS dep_number
        """,
        project=project_name,
        number=task_number,
        deps=depends_on,
    )
    return sorted([r["dep_number"] for r in result])


# ---------------------------------------------------------------------------
# Subtask
# ---------------------------------------------------------------------------


def create_subtask(
    session: Session,
    project_name: str,
    parent_task_number: int,
    description: str,
    **fields: Any,
) -> dict:
    """Create a subtask linked to a parent task via HAS_SUBTASK. Atomic numbering."""
    now = _now()
    props: dict[str, Any] = {
        "description": description,
        "status": fields.get("status", "todo"),
        "created_at": now,
        "updated_at": now,
    }

    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(parent:Task {number: $parent_number})
        OPTIONAL MATCH (p)-[:HAS_TASK|HAS_SUBTASK*]->(existing:Task)
        WITH parent, COALESCE(MAX(existing.number), 0) + 1 AS next_number
        CREATE (parent)-[:HAS_SUBTASK]->(t:Task $props)
        SET t.number = next_number
        RETURN t {.*} AS task
        """,
        project=project_name,
        parent_number=parent_task_number,
        props=props,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Parent task #{parent_task_number} not found in project '{project_name}'")
    return dict(record["task"])


def list_subtasks(session: Session, project_name: str, task_number: int) -> list[dict]:
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(parent:Task {number: $number})
              -[:HAS_SUBTASK]->(sub:Task)
        RETURN sub {.*} AS task
        ORDER BY sub.number
        """,
        project=project_name,
        number=task_number,
    )
    return [dict(r["task"]) for r in result]


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def add_dependency(
    session: Session,
    project_name: str,
    task_number: int,
    depends_on_number: int,
) -> bool:
    """Add a DEPENDS_ON relationship between two tasks."""
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t1:Task {number: $num1})
        MATCH (p)-[:HAS_TASK]->(t2:Task {number: $num2})
        MERGE (t1)-[r:DEPENDS_ON]->(t2)
        RETURN r
        """,
        project=project_name,
        num1=task_number,
        num2=depends_on_number,
    )
    return result.single() is not None


def remove_dependency(
    session: Session,
    project_name: str,
    task_number: int,
    depends_on_number: int,
) -> bool:
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t1:Task {number: $num1})
              -[r:DEPENDS_ON]->(t2:Task {number: $num2})
        DELETE r
        RETURN count(r) AS deleted
        """,
        project=project_name,
        num1=task_number,
        num2=depends_on_number,
    )
    record = result.single()
    return record is not None and record["deleted"] > 0


def get_dependencies(session: Session, project_name: str, task_number: int) -> list[dict]:
    """Get tasks that a given task depends on."""
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
              -[:DEPENDS_ON]->(dep:Task)
        RETURN dep {.*} AS task
        ORDER BY dep.number
        """,
        project=project_name,
        number=task_number,
    )
    return [dict(r["task"]) for r in result]


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


def create_section(
    session: Session,
    project_name: str,
    task_number: int,
    section_type: str,
    content: str = "",
) -> dict:
    now = _now()
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        CREATE (t)-[:HAS_SECTION]->(s:Section {
            type: $type, content: $content, created_at: $now, updated_at: $now
        })
        RETURN s {.*} AS section
        """,
        project=project_name,
        number=task_number,
        type=section_type,
        content=content,
        now=now,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Task #{task_number} not found in project '{project_name}'")
    return dict(record["section"])


def get_section(
    session: Session, project_name: str, task_number: int, section_type: str
) -> dict | None:
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
              -[:HAS_SECTION]->(s:Section {type: $type})
        RETURN s {.*} AS section
        """,
        project=project_name,
        number=task_number,
        type=section_type,
    )
    record = result.single()
    return dict(record["section"]) if record else None


def update_section(
    session: Session,
    project_name: str,
    task_number: int,
    section_type: str,
    content: str,
) -> dict:
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
              -[:HAS_SECTION]->(s:Section {type: $type})
        SET s.content = $content, s.updated_at = $now
        RETURN s {.*} AS section
        """,
        project=project_name,
        number=task_number,
        type=section_type,
        content=content,
        now=_now(),
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Section '{section_type}' not found for task #{task_number}")
    return dict(record["section"])


def delete_section(
    session: Session,
    project_name: str,
    task_number: int,
    section_type: str,
) -> bool:
    """Delete a section and all its findings and comments."""
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
              -[:HAS_SECTION]->(s:Section {type: $type})
        OPTIONAL MATCH (s)-[:HAS_FINDING]->(f:Finding)
        OPTIONAL MATCH (f)-[:HAS_COMMENT]->(c:Comment)
        OPTIONAL MATCH (c)-[:REPLIED_BY*0..]->(reply:Comment)
        DETACH DELETE s, f, c, reply
        RETURN count(*) AS deleted
        """,
        project=project_name,
        number=task_number,
        type=section_type,
    )
    record = result.single()
    return record is not None and record["deleted"] > 0


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


def create_finding(
    session: Session,
    project_name: str,
    task_number: int,
    section_type: str,
    text: str,
    author: str,
    severity: str | None = None,
) -> dict:
    now = _now()
    props: dict[str, Any] = {
        "text": text,
        "status": "open",
        "author": author,
        "created_at": now,
    }
    if severity:
        props["severity"] = severity

    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
              -[:HAS_SECTION]->(s:Section {type: $section_type})
        CREATE (s)-[:HAS_FINDING]->(f:Finding $props)
        RETURN f {.*} AS finding, elementId(f) AS finding_id
        """,
        project=project_name,
        number=task_number,
        section_type=section_type,
        props=props,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Section '{section_type}' not found for task #{task_number}")
    finding = dict(record["finding"])
    finding["element_id"] = record["finding_id"]
    return finding


def update_finding_status(session: Session, element_id: str, status: str) -> dict:
    now = _now()
    params: dict[str, Any] = {"eid": element_id, "status": status}
    set_clause = "SET f.status = $status"
    if status == "resolved":
        set_clause += ", f.resolved_at = $now"
        params["now"] = now

    result = session.run(
        f"""
        MATCH (f:Finding) WHERE elementId(f) = $eid
        {set_clause}
        RETURN f {{.*}} AS finding
        """,
        **params,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Finding with elementId '{element_id}' not found")
    return dict(record["finding"])


def list_findings(
    session: Session,
    project_name: str,
    task_number: int,
    section_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    where_clauses = []
    params: dict[str, Any] = {"project": project_name, "number": task_number}

    if section_type:
        where_clauses.append("s.type = $section_type")
        params["section_type"] = section_type
    if status:
        where_clauses.append("f.status = $status")
        params["status"] = status

    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    result = session.run(
        f"""
        MATCH (p:Project {{name: $project}})-[:HAS_TASK]->(t:Task {{number: $number}})
              -[:HAS_SECTION]->(s:Section)-[:HAS_FINDING]->(f:Finding)
        {where}
        RETURN f {{.*}} AS finding, elementId(f) AS finding_id, s.type AS section_type
        ORDER BY f.created_at
        """,
        **params,
    )
    findings = []
    for r in result:
        f = dict(r["finding"])
        f["element_id"] = r["finding_id"]
        f["section_type"] = r["section_type"]
        findings.append(f)
    return findings


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------


def create_comment(session: Session, finding_element_id: str, text: str, author: str) -> dict:
    now = _now()
    result = session.run(
        """
        MATCH (f:Finding) WHERE elementId(f) = $fid
        CREATE (f)-[:HAS_COMMENT]->(c:Comment {text: $text, author: $author, created_at: $now})
        RETURN c {.*} AS comment, elementId(c) AS comment_id
        """,
        fid=finding_element_id,
        text=text,
        author=author,
        now=now,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Finding with elementId '{finding_element_id}' not found")
    comment = dict(record["comment"])
    comment["element_id"] = record["comment_id"]
    return comment


def reply_to_comment(session: Session, comment_element_id: str, text: str, author: str) -> dict:
    now = _now()
    result = session.run(
        """
        MATCH (parent:Comment) WHERE elementId(parent) = $cid
        CREATE (parent)-[:REPLIED_BY]->(reply:Comment {text: $text, author: $author, created_at: $now})
        RETURN reply {.*} AS comment, elementId(reply) AS comment_id
        """,
        cid=comment_element_id,
        text=text,
        author=author,
        now=now,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Comment with elementId '{comment_element_id}' not found")
    comment = dict(record["comment"])
    comment["element_id"] = record["comment_id"]
    return comment


def list_comments(session: Session, finding_element_id: str) -> list[dict]:
    result = session.run(
        """
        MATCH (f:Finding)-[:HAS_COMMENT]->(c:Comment)
        WHERE elementId(f) = $fid
        OPTIONAL MATCH (c)-[:REPLIED_BY*0..]->(reply:Comment)
        WITH c, collect(DISTINCT reply {.*, element_id: elementId(reply)}) AS replies
        RETURN c {.*} AS comment, elementId(c) AS comment_id, replies
        ORDER BY c.created_at
        """,
        fid=finding_element_id,
    )
    comments = []
    for r in result:
        c = dict(r["comment"])
        c["element_id"] = r["comment_id"]
        c["replies"] = r["replies"]
        comments.append(c)
    return comments


# ---------------------------------------------------------------------------
# WorkflowRun / WorkflowStep
# ---------------------------------------------------------------------------


def create_workflow_run(
    session: Session,
    project_name: str,
    task_number: int,
    workflow_type: str,
) -> dict:
    now = _now()
    result = session.run(
        """
        MATCH (p:Project {name: $project})-[:HAS_TASK]->(t:Task {number: $number})
        CREATE (t)-[:HAS_WORKFLOW_RUN]->(wr:WorkflowRun {
            type: $type, status: 'pending', started_at: $now
        })
        RETURN wr {.*} AS workflow_run, elementId(wr) AS run_id
        """,
        project=project_name,
        number=task_number,
        type=workflow_type,
        now=now,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"Task #{task_number} not found in project '{project_name}'")
    run = dict(record["workflow_run"])
    run["element_id"] = record["run_id"]
    return run


def update_workflow_run(session: Session, element_id: str, status: str) -> dict:
    params: dict[str, Any] = {"eid": element_id, "status": status}
    set_clause = "SET wr.status = $status"
    if status in ("completed", "failed"):
        set_clause += ", wr.completed_at = $now"
        params["now"] = _now()

    result = session.run(
        f"""
        MATCH (wr:WorkflowRun) WHERE elementId(wr) = $eid
        {set_clause}
        RETURN wr {{.*}} AS workflow_run
        """,
        **params,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"WorkflowRun with elementId '{element_id}' not found")
    return dict(record["workflow_run"])


def create_workflow_step(
    session: Session,
    run_element_id: str,
    name: str,
) -> dict:
    result = session.run(
        """
        MATCH (wr:WorkflowRun) WHERE elementId(wr) = $rid
        CREATE (wr)-[:HAS_STEP]->(ws:WorkflowStep {
            name: $name, status: 'pending'
        })
        RETURN ws {.*} AS workflow_step, elementId(ws) AS step_id
        """,
        rid=run_element_id,
        name=name,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"WorkflowRun with elementId '{run_element_id}' not found")
    step = dict(record["workflow_step"])
    step["element_id"] = record["step_id"]
    return step


def update_workflow_step(
    session: Session,
    element_id: str,
    status: str,
    output: str | None = None,
) -> dict:
    params: dict[str, Any] = {"eid": element_id, "status": status}
    set_clause = "SET ws.status = $status"
    if status == "running":
        set_clause += ", ws.started_at = $now"
        params["now"] = _now()
    elif status in ("completed", "failed"):
        set_clause += ", ws.completed_at = $now"
        params["now"] = _now()
    if output is not None:
        set_clause += ", ws.output = $output"
        params["output"] = output

    result = session.run(
        f"""
        MATCH (ws:WorkflowStep) WHERE elementId(ws) = $eid
        {set_clause}
        RETURN ws {{.*}} AS workflow_step
        """,
        **params,
    )
    record = result.single()
    if record is None:
        raise ValueError(f"WorkflowStep with elementId '{element_id}' not found")
    return dict(record["workflow_step"])
