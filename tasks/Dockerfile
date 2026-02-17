FROM python:3.12-slim

# Install uv for fast package installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install ralph-tasks package
# Build context must be the monorepo root: docker build -f tasks/Dockerfile .
COPY tasks/ /tmp/ralph-tasks/
RUN uv pip install --system --break-system-packages --no-cache /tmp/ralph-tasks/ \
    && rm -rf /tmp/ralph-tasks/

# Create non-root user
RUN groupadd --gid 1001 ralph-tasks \
    && useradd --uid 1001 --gid 1001 -m ralph-tasks

USER ralph-tasks

# Configuration via environment variables
ENV RALPH_TASKS_HOST=0.0.0.0
ENV RALPH_TASKS_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["ralph-tasks-web"]
