---
name: ralph-review-simplify
description: Run code-simplifier agent, save results to task
arguments:
  - name: task_ref
    description: Task reference "project#N"
    required: true
---

Task ref: `$ARGUMENTS`

**ВАЖНО:** Это standalone review команда, НЕ полный workflow. Не требует confirmation phrase.

## 1. Получи задачу

Используй `mcp__md-task-mcp__tasks(project, number)` чтобы получить task.

## 2. Запусти агент

```
Task(subagent_type="code-simplifier:code-simplifier",
     prompt=task_context, model="opus")
```

## 3. ОБЯЗАТЕЛЬНО сохрани в review поле

```
mcp__md-task-mcp__update_task(
    project=project,
    number=number,
    review=existing_review + "\n\n---\n\n### Code Simplifier\n\n" + results
)
```

**НЕ записывай в blocks!** Только в `review` поле.

## 4. Верни статус

```
✅ Code Simplifier записан: {project}#{number} — N замечаний
```
