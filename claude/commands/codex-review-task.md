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
Запомни текущее содержимое `review` поля.

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
5. ДОБАВЬ результаты к существующему Review: update_task(project, number, review=existing + new)

Формат замечаний: Severity (CRITICAL/HIGH/MEDIUM/LOW), File, Line, Issue.
НЕ ИЗМЕНЯЙ КОД. Результаты ДОБАВЛЯЙ к существующему Review (append).
Если нет замечаний — 'NO ISSUES FOUND'.
" 2>&1 | tee "$LOG_FILE"
```

**ОБЯЗАТЕЛЬНО проверь exit code.** Если не 0 — сообщи ошибку, НЕ продолжай.

## 4. Проверь результат

Получи обновлённую задачу через `mcp__md-task-mcp__tasks(project, number)`.
Убедись что в review поле появились результаты от Codex.

**Если review не обновился** — codex не выполнил задачу. Сообщи ошибку, прочитай лог.

## 5. Верни статус

```text
✅ Codex Review: {project}#{number} — см. review поле задачи
```
