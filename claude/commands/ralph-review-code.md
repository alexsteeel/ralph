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

## 3. ОБЯЗАТЕЛЬНО сохрани в review поле

После получения результатов от всех агентов, **ОБЯЗАТЕЛЬНО** вызови:

```
mcp__md-task-mcp__update_task(
    project=project,
    number=number,
    review=existing_review + "\n\n---\n\n### Code Review (5 agents)\n\n" + formatted_results
)
```

**НЕ записывай в blocks!** Только в `review` поле.

## 4. Верни статус

```
✅ Code Review записан: {project}#{number} — N замечаний
```
