# syntax=docker/dockerfile:1

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/database /app/chroma /app/data \
    && chown -R app:app /app

COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend ./backend
COPY mcp_server ./mcp_server
COPY frontend ./frontend
COPY scripts ./scripts
COPY data ./data

RUN uv sync --frozen --no-dev \
    && chown -R app:app /app

USER app

EXPOSE 8000 8080 8501

CMD ["uv", "run", "python", "-m", "mcp_server.server"]
