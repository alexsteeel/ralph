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

## 3. ОБЯЗАТЕЛЬНО сохрани как structured findings

Для КАЖДОГО замечания вызови:

```
add_review_finding(
    project=project,
    number=number,
    review_type="code-simplifier",
    text="<описание замечания>",
    author="code-simplifier",
    file="<path/to/file>",       # если применимо
    line_start=<N>,              # если применимо
    line_end=<M>                 # если применимо
)
```

## 4. Верни статус

```
✅ Code Simplifier записан: {project}#{number} — N findings добавлено
```
