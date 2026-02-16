# Target Architecture (Graph-First, Multi-Agent)

Дата фиксации: 2026-02-15
Обновлено: 2026-02-15 (по итогам интервью ralph#9)

Документ описывает целевую архитектуру монорепо Ralph:
- хранение задач и ревью в графовой модели (Neo4j),
- оркестрация агентов только через `ralph`,
- явные состояния workflow на узлах графа,
- параллельные ревью без конфликтов записи.

## 1. Проблема текущего состояния

Текущая модель опирается на markdown-файлы и секции текста (`description/plan/review/report/blocks`).
Это приводит к ограничениям:
- конкурирующие ревью-агенты пишут в один текстовый раздел,
- состояние процесса выводится эвристически (по тексту/логам),
- сложно реализовать права доступа по ролям на уровне поддеревьев,
- ограниченная аналитика по этапам, ревью-типам, итерациям и стоимости.

## 2. Целевые принципы

1. `Graph-first storage`: проекты, задачи, секции, ревью и комментарии хранятся как графовые сущности.
2. `Agent orchestration via ralph`: запуск review-агентов только из `ralph-cli`, а не неявно из markdown-команд.
3. `State machine over graph`: состояние этапов хранится как статус узлов/рёбер, не как наличие фраз в тексте.
4. `Role-based access`: права задаются на уровне типов узлов и поддеревьев.
5. `Parallel-safe writes`: каждый агент пишет в свою секцию-ревью, без shared-text конфликтов.

## 3. Доменная модель

### Иерархия проектов (рекурсивная)

```
Workspace
  └── Project
        ├── Project          # вложенные проекты (без ограничения глубины)
        └── Task
              └── Task       # подзадачи (без ограничения глубины, ожидается 1-2 уровня)
```

- **Workspace** — корневой контейнер для всех проектов.
- **Project** — рекурсивно вложен через `CONTAINS_PROJECT`. Заменяет фиксированный Subproject.
- **Task** — рекурсивно вложен через `HAS_SUBTASK`. Заменяет фиксированный Subtask.

### Секции задачи (контентные + ревью)

```
Task
  ├── Section(description)        # контентная
  ├── Section(plan)               # контентная
  ├── Section(report)             # контентная
  ├── Section(blocks)             # контентная
  ├── Section(code-review)        # ревью-секция
  ├── Section(codex-review)       # ревью-секция
  ├── Section(simplifier-review)  # ревью-секция
  ├── Section(security-review)    # ревью-секция
  └── Section(...)                # type — произвольная строка, новые типы без миграции
```

Любая секция может содержать дерево замечаний:

```
Section
  └── Finding (status: open | resolved | declined)
        └── Comment
              └── Comment    # вложенные ответы (без ограничения глубины)
```

Ключевое решение: **ReviewType/ReviewRun заменены на Section с типом ревью**. Каждый агент пишет в свою секцию. Это проще и унифицирует контентные секции с ревью-секциями.

### Workflow (состояния выполнения)

```
Task
  └── WorkflowRun (type: interview | plan | implement)
        ├── WorkflowStep (implement)
        ├── WorkflowStep (test)
        ├── WorkflowStep (review)
        ├── WorkflowStep (lint)
        └── WorkflowStep (codex-review)
```

## 4. Граф-схема

### Nodes

```
(:Workspace {
    name: str,              # уникальное имя
    description: str,
    created_at: datetime
})

(:Project {
    name: str,              # уникальное в рамках parent
    description: str,
    created_at: datetime
})

(:Task {
    number: int,            # уникальный в рамках Project
    description: str,
    status: str,            # todo | work | done | approved | hold
    started: datetime | null,
    completed: datetime | null,
    created_at: datetime,
    updated_at: datetime
})

(:Section {
    type: str,              # произвольная строка, новые типы добавляются без миграции
                            # контентные: description | plan | report | blocks
                            # ревью: code-review | codex-review | simplifier-review |
                            # security-review | pr-test-review | comment-review |
                            # type-design-review | silent-failure-review | ...
    content: str,
    created_at: datetime,
    updated_at: datetime
})

(:Finding {
    text: str,              # описание замечания
    status: str,            # open | resolved | declined
    severity: str | null,   # critical | major | minor | info
    author: str,            # имя агента или человека
    created_at: datetime,
    resolved_at: datetime | null
})

(:Comment {
    text: str,
    author: str,
    created_at: datetime
})

(:WorkflowRun {
    type: str,              # interview | plan | implement
    status: str,            # pending | running | completed | failed
    started_at: datetime | null,
    completed_at: datetime | null
})

(:WorkflowStep {
    name: str,              # implement | test | review | lint | codex-review ...
    status: str,            # pending | running | completed | failed | skipped
    started_at: datetime | null,
    completed_at: datetime | null,
    output: str | null
})

(:Role {name})
```

### Relationships

```
(Workspace)-[:CONTAINS_PROJECT]->(Project)
(Project)-[:CONTAINS_PROJECT]->(Project)       # рекурсивная вложенность
(Project)-[:HAS_TASK]->(Task)
(Task)-[:HAS_SUBTASK]->(Task)                  # рекурсивные подзадачи
(Task)-[:DEPENDS_ON]->(Task)
(Task)-[:HAS_SECTION]->(Section)
(Task)-[:HAS_WORKFLOW_RUN]->(WorkflowRun)
(WorkflowRun)-[:HAS_STEP]->(WorkflowStep)
(Section)-[:HAS_FINDING]->(Finding)
(Finding)-[:HAS_COMMENT]->(Comment)
(Comment)-[:REPLIED_BY]->(Comment)             # вложенные ответы
(Role)-[:CAN_READ {scope}]->(NodeType|Subtree)
(Role)-[:CAN_WRITE {scope}]->(NodeType|Subtree)
```

### Constraints & Indexes

#### Unique Constraints
- `Workspace.name` — глобально уникально
- `(Project.name, parent)` — уникально в рамках parent (Workspace или Project)
- `(Task.number, Project)` — уникально в рамках Project

#### Full-text Indexes
- `Task.description` — поиск по описаниям задач
- `Finding.text` — поиск по замечаниям

#### Regular Indexes
- `Task.status` — фильтрация по статусу
- `Finding.status` — фильтрация по статусу замечаний
- `Section.type` — фильтрация по типу секции
- `WorkflowRun.type` — фильтрация по типу workflow

## 5. Workflow State Machine (Graph-based)

### Базовые статусы шагов

`pending | running | completed | failed | skipped`

### Типы workflow

| Workflow | Шаги |
|----------|------|
| `interview` | interview |
| `plan` | plan, review (Claude Code), review (Codex) |
| `implement` | implement, test, review, lint, codex-review |

Переходы валидируются правилами:
- нельзя завершить `report`, пока не завершены обязательные шаги;
- `reviews.completed` возможно только если все обязательные ревью-секции закрыты;
- `failed` требует связанной причины.

Главный принцип: `ralph` принимает решения по состоянию узлов `WorkflowStep`, а не по поиску фраз в transcript.

## 6. Параллельные ревью без конфликтов

### Целевое поведение

1. `ralph review` создаёт несколько ревью-секций параллельно (`code-review`, `security-review`, `codex-review`).
2. Каждый агент пишет findings только в свою Section.
3. Агрегированный итог строится как read-модель (fan-in), а не запись в общий markdown-блок.

### Результат

- нет перетирания полей `review`,
- независимые ретраи по каждому агенту,
- прозрачная история замечаний и решений.

## 7. Разделение прав (RBAC)

Минимальный baseline:

- `swe`:
  - read/write: секции `description`, `plan`, `report`,
  - read/write: ответы на findings (Comment),
  - изменение статусов шагов реализации.
- `reviewer`:
  - read: `Task`, `Section(description, plan)`,
  - write: ревью-секции, `Finding`, `Comment`,
  - запрет на запись в `plan/report/status` задачи.
- `orchestrator` (`ralph-cli`):
  - write: `WorkflowRun`, `WorkflowStep`,
  - создание ревью-секций и назначение агентов,
  - агрегирующие статусы и служебная телеметрия.

## 8. Совместимость и миграция

Рекомендуемый переход:

1. `Schema bootstrap` (#9): ввести узлы/рёбра, Neo4j инфраструктура, CRUD layer.
2. `Core rewrite` (#10): переписать `core.py` — чтение/запись через Neo4j.
3. `Migration` (#11): перенос существующих задач из markdown в Neo4j.
4. `Structured reviews` (#12): ревью-секции, findings, comments.
5. `Role-based access` (#13): права по ролям.
6. `Cutover`: выключить markdown как источник истины.

## 9. Инфраструктура

### Neo4j как shared сервис

Neo4j разворачивается как общий сервис (аналогично `ai-sbx-docker-proxy`):

- **Контейнер**: `ai-sbx-neo4j` в `sandbox/ralph_sandbox/resources/docker-proxy/docker-compose.yaml`
- **Образ**: `neo4j:2025`
- **Сеть**: `ai-sbx-proxy-internal` (доступен всем devcontainer)
- **Порты**: 7474 (HTTP), 7687 (Bolt)
- **Volumes**: `ai-sbx-neo4j-data`, `ai-sbx-neo4j-logs`

### Python driver

- Пакет: `tasks/ralph_tasks/graph/` (client, schema, crud)
- Runtime dependency: `neo4j>=5.0` в `tasks/pyproject.toml`
- Конфигурация: env vars `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`

### Контейнеризация ralph-tasks (#33)

MCP сервер `ralph-tasks` оборачивается в контейнер для доступа из всех devcontainer (отдельная задача #33, зависит от #9).

## 10. Связь с backlog

| Задача | Этап |
|--------|------|
| #9 | Инфраструктура Neo4j, схема, CRUD layer |
| #10 | Переход core на graph-персистентность |
| #11 | Миграция markdown → Neo4j |
| #12 | Структурированные ревью (секции, findings, comments) |
| #13 | Роли и права доступа |
| #16/#17 | Итеративные ревью-циклы через `ralph` |
| #18/#19 | Аналитика и unresolved workflow |
| #33 | Контейнеризация ralph-tasks MCP сервера |
