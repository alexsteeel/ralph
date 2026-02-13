---
name: linters
description: Run linters (ruff, djlint) on the codebase
---

Запусти линтеры для проверки качества кода.

## Python Linting (ruff)

```bash
# Проверка Python кода
ruff check services/web/app/
ruff check scripts/
```

## HTML Template Linting (djlint)

```bash
# Проверка HTML шаблонов (только check, без авто-форматирования)
djlint services/web/templates/ --check
```

## Игнорируемые правила djlint

Следующие правила игнорируются (см. pyproject.toml):
- H006: img без width/height (Bootstrap responsive)
- H019: javascript: в href (pagination links)
- H021: Inline styles (для динамических стилей)
- H030/H031: meta/script в head (Jinja2)
- J018: Jinja2 whitespace
- T003: endblock без имени

## Workflow

1. Запусти ruff check
2. Если есть ошибки → исправь их
3. Запусти djlint --check
4. Если есть ошибки → исправь их
5. Повтори пока все линтеры не пройдут

## Результат

Сообщи результат:
- ✅ Все линтеры прошли успешно
- ❌ Найдены ошибки: [список]
