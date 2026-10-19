# The backend image (plan §0, §3): the API, the one-shot migration and the workers all run from it;
# compose.yaml picks the command. Dependencies come from uv.lock only (--frozen), without the dev
# group, and the project is installed into /app/.venv.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The dependencies first, so a source change does not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --no-create-home di1
USER di1

EXPOSE 8000
CMD ["uvicorn", "di1.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
