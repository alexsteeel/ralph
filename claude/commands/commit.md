---
name: commit
description: Create a commit following repository style
---

Создай коммит для текущих изменений, соблюдая стиль репозитория.

## Workflow

1. **Анализ стиля коммитов**
   ```bash
   git log --oneline -10
   git log -5 --format="%B---"
   ```
   Определи:
   - Язык (English/Russian)
   - Формат (conventional commits, plain, etc.)
   - Стиль глаголов (imperative, past tense)
   - Наличие Co-Authored-By (добавляй ТОЛЬКО если используется в репозитории)

2. **Просмотр изменений**
   ```bash
   git status
   git diff --staged
   git diff
   ```

3. **Staging изменений**
   - Добавь релевантные файлы по имени
   - НЕ используй `git add -A` или `git add .`
   - Исключи sensitive файлы (.env, credentials)

4. **Создание коммита**
   - Сообщение в стиле репозитория
   - Если в репозитории короткие однострочные сообщения — пиши так же, НЕ добавляй многострочные описания
   - Co-Authored-By добавляй ТОЛЬКО если он есть в предыдущих коммитах
   - HEREDOC используй только если в репозитории многострочные сообщения:
   ```bash
   git commit -m "$(cat <<'EOF'
   Commit message here
   EOF
   )"
   ```

## Результат

После коммита покажи:
```bash
git log --oneline -1
git status
```
