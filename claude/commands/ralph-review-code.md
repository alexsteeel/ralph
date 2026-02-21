---
name: ralph-review-code
description: Run 5 code review agents in parallel, save results to task
arguments:
  - name: task_ref
    description: Task reference "project#N"
    required: true
---

Task ref: `$ARGUMENTS`

**ВАЖНО:** Это standalone review команда, НЕ полный workflow. Не требует confirmation phrase.

## 1. Получи задачу

Используй `mcp__md-task-mcp__tasks(project, number)` чтобы получить task.

## 2. Запусти 5 агентов ПАРАЛЛЕЛЬНО

Все 5 Task tool calls в **ОДНОМ сообщении**, передай контекст задачи:

- `pr-review-toolkit:code-reviewer`
- `pr-review-toolkit:silent-failure-hunter`
- `pr-review-toolkit:type-design-analyzer`
- `pr-review-toolkit:pr-test-analyzer`
- `pr-review-toolkit:comment-analyzer`

## 3. ОБЯЗАТЕЛЬНО сохрани как structured findings

После получения результатов от всех агентов, для КАЖДОГО замечания вызови:

```
add_review_finding(
    project=project,
    number=number,
    review_type="<agent-type>",  # e.g. "code-review", "silent-failure", "type-design", "test-coverage", "comment-analysis"
    text="<описание замечания>",
    author="<agent-name>",
    file="<path/to/file>",       # если применимо
    line_start=<N>,              # если применимо
    line_end=<M>                 # если применимо
)
```

**review_type по агентам:**
- `pr-review-toolkit:code-reviewer` → `"code-review"`
- `pr-review-toolkit:silent-failure-hunter` → `"silent-failure"`
- `pr-review-toolkit:type-design-analyzer` → `"type-design"`
- `pr-review-toolkit:pr-test-analyzer` → `"test-coverage"`
- `pr-review-toolkit:comment-analyzer` → `"comment-analysis"`

## 4. Верни статус

```
✅ Code Review записан: {project}#{number} — N findings добавлено
```
