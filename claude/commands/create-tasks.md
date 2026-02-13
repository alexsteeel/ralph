---
name: create-tasks
description: Create tasks in md-task-mcp from a list of notes
arguments:
  - name: notes
    description: List of notes/ideas (one per line or comma-separated)
    required: true
  - name: project
    description: Project name for md-task-mcp (default: myproject)
    required: false
---

Ты создаёшь задачи в md-task-mcp на основе списка заметок пользователя.

## Workflow

```
1. PARSE LIST → 2. QUICK ANALYSIS → 3. CLARIFY EACH → 4. CREATE TASKS → 5. SUMMARY
```

## Phase 1: Parse Notes List

Прочитай заметки: `{{notes}}`

Разбей на отдельные задачи:
- По строкам (если многострочный текст)
- По номерам (1. 2. 3. или - )
- По запятым/точкам (если одна строка)

Составь список:
```
1. <заметка 1> → <предварительное понимание>
2. <заметка 2> → <предварительное понимание>
...
```

## Phase 2: Quick Analysis

Для ВСЕХ заметок разом проведи краткий анализ:

1. Определи какие модули затрагиваются
2. Найди связи между заметками (может это одна задача?)
3. Проверь что упомянутые компоненты существуют

**Группировка**: Если несколько заметок относятся к одной фиче — предложи объединить.

## Phase 3: Clarify with User

Используй `AskUserQuestion` для **пакетного** уточнения.

### Общие вопросы (один раз для всех):

1. **Проект** (если не указан):
   - myproject (default)
   - другой

### Вопросы по каждой задаче:

Покажи таблицу и спроси подтверждение:

```
Распознал следующие задачи:

| # | Description | Module | Priority |
|---|-------------|--------|----------|
| 1 | Add export to Excel | web | medium |
| 2 | Fix camera reconnect | capture | high |
| 3 | Update employee sync | sync | medium |

Вопросы:
1. Задачи 2 и 3 похожи — объединить?
2. Для задачи 1 — экспорт чего именно: посещений, сотрудников, логов?
3. Приоритеты верные?

Подтвердить или изменить?
```

### Если есть неясности:
- Уточни через AskUserQuestion
- Предложи варианты интерпретации
- Спроси про группировку связанных задач

## Phase 4: Create Tasks

Для каждой подтверждённой задачи вызови `mcp__md-task-mcp__create_task`:

```python
create_task(
    project="{{project}}" or "myproject",
    description="<краткое описание 3-7 слов>",
    body="""
## Описание
<Полное описание на основе заметки и уточнений>

## Контекст
<Связанные компоненты, файлы>

## Требования
- <требование 1>
- ...

## Приоритет
<приоритет>
"""
)
```

**НЕ добавляй plan** — это будет при выполнении.

## Phase 5: Summary

Покажи итоговый список созданных задач:

```
✅ Создано N задач:

| # | Task | Description |
|---|------|-------------|
| 1 | project#5 | Add attendance export to Excel |
| 2 | project#6 | Fix camera auto-reconnect |
| 3 | project#7 | Update employee sync validation |

Для выполнения задачи используй:
/execute-python-task project#N
```

## Формат description

Краткий, 3-7 слов:
- `Add <feature>` — новое
- `Fix <bug>` — баг
- `Update <component>` — изменение
- `Refactor <area>` — рефакторинг
- `Remove <feature>` — удаление

## Checklist

- [ ] Список заметок распарсен
- [ ] Краткий анализ проведён
- [ ] Группировка предложена (если нужно)
- [ ] Уточнения получены пакетно
- [ ] Все задачи созданы
- [ ] Итоговая таблица показана

---

Начни с парсинга списка заметок: `{{notes}}`
