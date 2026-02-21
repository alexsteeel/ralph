---
name: codex-review-task
description: Run Codex CLI review for a task, save results to task
arguments:
  - name: task_ref
    description: Task reference "project#N"
    required: true
---

Task ref: `$ARGUMENTS`

**ВАЖНО:** Это standalone команда для ручного запуска codex review. Не требует confirmation phrase.

> В `ralph review` codex вызывается **напрямую из Python CLI** (без Claude).
> Эта команда — для случаев когда нужен codex review отдельно.

## 1. Проверь доступность Codex

```bash
which codex || { echo "ERROR: codex not found"; exit 1; }
```

**Если codex не найден — СТОП. НЕ заменяй своим ревью.**

## 2. Получи задачу

Используй `mcp__md-task-mcp__tasks(project, number)` чтобы получить task.
Запомни текущие findings через `list_review_findings`.

## 3. Запусти codex review НАПРЯМУЮ

```bash
REVIEW_DIR="$HOME/.claude/logs/reviews"
mkdir -p "$REVIEW_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TASK_SAFE=$(echo "$ARGUMENTS" | tr '#' '_')
LOG_FILE="${REVIEW_DIR}/${TASK_SAFE}_codex-review_${TIMESTAMP}.log"

codex review \
  --uncommitted \
  -c 'profiles.review.model="gpt-5.3-codex"' \
  -c 'profiles.review.model_reasoning_effort="xhigh"' \
  -c 'profile="review"' \
  "
Ты выполняешь код-ревью для задачи $ARGUMENTS.

1. Получи детали задачи через MCP md-task-mcp: tasks(project, number)
2. Прочитай CLAUDE.md в директории тестов для получения URL и credentials
3. Проанализируй незакоммиченные изменения на соответствие ТЗ
4. Если есть frontend изменения — проверь UI через playwright MCP
5. Для КАЖДОГО замечания вызови add_review_finding(project, number, review_type='codex-review', text='описание', author='codex', file='path', line_start=N)

НЕ ИЗМЕНЯЙ КОД. Используй add_review_finding для каждого замечания.
Если нет замечаний — НЕ создавай findings.
" 2>&1 | tee "$LOG_FILE"
```

**ОБЯЗАТЕЛЬНО проверь exit code.** Если не 0 — сообщи ошибку, НЕ продолжай.

## 4. Проверь результат

Проверь findings через `list_review_findings(project, number, review_type="codex-review")`.
Убедись что Codex добавил findings.

**Если findings не появились** — codex не выполнил задачу. Сообщи ошибку, прочитай лог.

## 5. Верни статус

```text
✅ Codex Review: {project}#{number} — см. review поле задачи
```
