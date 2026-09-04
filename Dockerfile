FROM python:3.11-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY uv.lock pyproject.toml ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "uvicorn", "meridian.main:app", "--host", "0.0.0.0", "--port", "8000"]
