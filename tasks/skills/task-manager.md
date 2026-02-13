---
name: task-manager
description: "Manage development tasks via ralph-tasks MCP server. Use when user asks about tasks, projects, or task management."
---

# Task Manager Skill

Use ralph-tasks to manage development tasks.

## Task Naming Rule

Use infinitive form (что сделать?) with brief goal:
- "Добавить справку для пользователей"
- "Исправить ошибку авторизации"
- "Реализовать экспорт в PDF"
- "Обновить зависимости проекта"

## MCP Tools

| Tool | Description |
|------|-------------|
| `tasks()` | List all projects with task counts |
| `tasks(project)` | List tasks in a project |
| `tasks(project, number)` | Get full task details |
| `create_task(project, description, body?, plan?)` | Create a new task |
| `update_task(project, number, ...)` | Update task fields |
| `list_attachments(project, number)` | List attachments with paths |
| `add_attachment(project, number, source_path, filename?)` | Copy file to attachments |
| `delete_attachment(project, number, filename)` | Delete attachment |

## Task File Format

Tasks stored in `~/.md-task-mcp/{project}/tasks/{NNN}-{slug}.md`.
Attachments stored in `~/.md-task-mcp/{project}/tasks/{NNN}-{slug}/` folder:

```markdown
# Task 1: Task summary
status: todo
module: auth
branch: feature/task-1-summary
started: 2024-01-15 10:30
completed:
depends_on: 2, 3

## Description
Requirements and detailed description here.

## Plan
Implementation plan here.

## Report
Completion report here.

## Review
Code review feedback here.

## Blocks
What blocks this task (for hold status).
```

## Task Sections

| Section | Purpose |
|---------|---------|
| Description | Requirements, detailed task description |
| Plan | Implementation plan, approach |
| Report | Work completion report |
| Review | Code review feedback |
| Blocks | What blocks this task (used with hold status) |

## Workflows

### View Tasks

```
tasks()                    # List all projects
tasks("my-project")        # List tasks in project
tasks("my-project", 1)     # Get full task #1 details
```

### Create Task

```
create_task(
    project="my-project",
    description="Add user authentication",
    body="Requirements here...",
    plan="Implementation plan..."
)
```

### Update Task

```
update_task(
    project="my-project",
    number=1,
    status="work",           # hold, todo, work, done, approved
    module="auth",           # area/module name
    started="2024-01-15 10:30",
    branch="feature/task-1",
    body="Updated description",
    plan="Updated plan",
    report="Work completed",
    review="LGTM",
    blocks="Waiting for API spec",
    depends_on=[2, 3]
)
```

### Multiline Text

Use real line breaks for multiline content in `body`, `plan`, `report`, `review`, `blocks`:

```
update_task(
    project="my-project",
    number=1,
    plan="""## Steps

1. First step
2. Second step

## Notes

Additional details here."""
)
```

Markdown formatting (headers, lists, code blocks) is fully supported.

### Start Working on Task

**IMPORTANT:** When starting work on a task, ALWAYS:
1. Get current git branch: `git branch --show-current`
2. Update task with branch name and status:

```
update_task(
    project="my-project",
    number=1,
    status="work",
    started="YYYY-MM-DD HH:MM",
    branch="<current-git-branch>"
)
```

This ensures the task is linked to the correct git branch for tracking.

### Work with Attachments

```
# List attachments (returns paths)
list_attachments("my-project", 1)
# Returns: [{"name": "screenshot.png", "path": "/full/path/...", "size": 1234}, ...]

# Add attachment (copy file to task folder)
add_attachment("my-project", 1, "/path/to/file.png")
add_attachment("my-project", 1, "/path/to/file.png", "renamed.png")

# Read attachment content (use Claude's Read tool)
Read("/full/path/from/list_attachments/screenshot.png")

# Delete attachment
delete_attachment("my-project", 1, "screenshot.png")
```

## Status Values

- `hold` - Blocked/on hold
- `todo` - Not started
- `work` - In progress
- `done` - Completed
- `approved` - Reviewed and approved

## Module Field

Use `module` to categorize tasks by area/component:
- `auth` - Authentication/authorization
- `api` - API endpoints
- `ui` - User interface
- `db` - Database
- Custom names as needed

